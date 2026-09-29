"""
AutoCal Service - 自动校准闭环服务门面 (P1 集成)

将已有的 AutoCalWorkflow + DDC/CI 显示器控制适配器接入产品链路：

    - 显示器 DDC/CI 连接 / 能力查询 / 控制项读写 / 快照回滚
    - 自动校准闭环（基线测量 → 求解 → DDC 写入 → 验证 → 迭代）
    - 进度回调（状态 / 百分比 / 迭代记录），供 Backend 转发到 Web UI

本模块不依赖 Qt，可独立测试；Backend 负责：
    - 提供同步测量桥 measure_fn（显示色块 + measure_sync）
    - 在后台线程调用 start()
    - 将回调转为 pyqtSignal

Reference:
    - src/workflows/autocal_workflow.py (闭环工作流)
    - src/instruments/display_control.py (DDC/CI 适配器)
    - docs/calman_level_upgrade_plan.md (P0 差距项①②)
"""

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.instruments.display_control import (
    ControlType,
    DisplayControlAdapter,
    DisplayControlError,
    FakeDisplayControlAdapter,
    create_fake_display_adapter,
)
from src.workflows.autocal_workflow import (
    AutoCalConfig,
    AutoCalMode,
    AutoCalState,
    AutoCalTarget,
    AutoCalWorkflow,
)

logger = logging.getLogger(__name__)


# 控制项名称（Web UI / JSON 使用字符串）与 ControlType 的映射
CONTROL_NAME_MAP: Dict[str, ControlType] = {
    "brightness": ControlType.BRIGHTNESS,
    "contrast": ControlType.CONTRAST,
    "color_temp": ControlType.COLOR_TEMP,
    "red_gain": ControlType.RED_GAIN,
    "green_gain": ControlType.GREEN_GAIN,
    "blue_gain": ControlType.BLUE_GAIN,
    "red_offset": ControlType.RED_OFFSET,
    "green_offset": ControlType.GREEN_OFFSET,
    "blue_offset": ControlType.BLUE_OFFSET,
    "backlight": ControlType.BACKLIGHT,
    "hue": ControlType.HUE,
    "saturation": ControlType.SATURATION,
}

# AutoCal 支持的校准目标白点（与 AutoCalTarget.WHITE_POINTS 对齐）
SUPPORTED_WHITE_POINTS = ["D50", "D55", "D60", "D65", "D70", "D75", "native"]


class AutoCalServiceError(Exception):
    """AutoCal 服务错误"""

    def __init__(self, message: str, error_code: str = "UNKNOWN"):
        super().__init__(message)
        self.error_code = error_code


class AutoCalService:
    """
    自动校准服务

    管理生命周期：
        1. DDC/CI 适配器连接（真适配器优先，失败降级假适配器用于演练）
        2. AutoCalWorkflow 实例化与运行
        3. 停止 / 回滚 / 会话查询
    """

    def __init__(self, session_dir: Optional[Path] = None):
        self._display_adapter: Optional[DisplayControlAdapter] = None
        self._workflow: Optional[AutoCalWorkflow] = None
        self._session_dir = session_dir
        self._running = False
        self._lock = threading.Lock()

        # 进度回调（由 Backend 注入）
        self.on_state: Optional[Callable[[str, str], None]] = None
        self.on_progress: Optional[Callable[[str, float], None]] = None
        self.on_iteration: Optional[Callable[[Dict[str, Any]], None]] = None

    # ==================================================================
    # 显示器控制 (DDC/CI)
    # ==================================================================

    def connect_display(
        self,
        display_id: int = 1,
        allow_fake: bool = False,
    ) -> Dict[str, Any]:
        """
        连接显示器 DDC/CI 控制通道

        Args:
            display_id: 显示器序号 (1-based)
            allow_fake: DDC 不可用时是否降级为模拟适配器（演练模式）

        Returns:
            {"success": bool, "capabilities": {...}, "is_fake": bool, "error": str}
        """
        try:
            from src.instruments.display_control import DDCCIAdapter

            adapter = DDCCIAdapter(display_id=display_id)
            adapter.connect()
            self._display_adapter = adapter
            logger.info(f"DDC/CI connected: display {display_id}")
        except (DisplayControlError, Exception) as e:
            if not allow_fake:
                return {
                    "success": False,
                    "error": f"DDC/CI 连接失败: {e}",
                    "capabilities": None,
                    "is_fake": False,
                }
            # 演练模式：模拟适配器
            self._display_adapter = create_fake_display_adapter(display_id=display_id)
            self._display_adapter.connect()
            logger.warning(f"DDC/CI unavailable, using fake adapter: {e}")

        return {
            "success": True,
            "capabilities": self.get_capabilities(),
            "is_fake": isinstance(self._display_adapter, FakeDisplayControlAdapter),
            "error": "",
        }

    def disconnect_display(self) -> Dict[str, Any]:
        """断开显示器控制连接"""
        if self._display_adapter:
            try:
                self._display_adapter.disconnect()
            except Exception as e:
                logger.warning(f"Disconnect error: {e}")
            self._display_adapter = None
        return {"success": True}

    def is_display_connected(self) -> bool:
        """显示器控制通道是否已连接"""
        return bool(self._display_adapter and self._display_adapter.is_connected)

    def get_capabilities(self) -> Optional[Dict[str, Any]]:
        """获取显示器控制能力集（控制项列表及范围）"""
        if not self._display_adapter:
            return None
        try:
            return self._display_adapter.get_capabilities().to_dict()
        except DisplayControlError as e:
            logger.error(f"Get capabilities failed: {e}")
            return None

    def read_control(self, name: str) -> Dict[str, Any]:
        """读取单个控制项当前值"""
        control = self._resolve_control(name)
        try:
            value = self._require_adapter().read_control(control)
            return {"success": True, "name": name, "value": value}
        except DisplayControlError as e:
            return {"success": False, "name": name, "error": str(e)}

    def write_control(self, name: str, value: int) -> Dict[str, Any]:
        """写入单个控制项（写前自动保存回滚快照）"""
        control = self._resolve_control(name)
        adapter = self._require_adapter()
        try:
            if not adapter.has_snapshot:
                adapter.save_snapshot(source="before_manual_write")
            result = adapter.write_control(control, int(value))
            return {"success": bool(result and result.success), "name": name, "value": int(value)}
        except DisplayControlError as e:
            return {"success": False, "name": name, "error": str(e)}

    def save_snapshot(self, source: str = "manual") -> Dict[str, Any]:
        """保存当前控制值快照"""
        try:
            snapshot = self._require_adapter().save_snapshot(source=source)
            return {"success": True, "snapshot": snapshot.to_dict()}
        except DisplayControlError as e:
            return {"success": False, "error": str(e)}

    def rollback(self) -> Dict[str, Any]:
        """回滚到最近快照"""
        try:
            success = self._require_adapter().rollback()
            return {"success": bool(success)}
        except DisplayControlError as e:
            return {"success": False, "error": str(e)}

    # ==================================================================
    # 自动校准闭环
    # ==================================================================

    @property
    def is_running(self) -> bool:
        """校准是否正在运行"""
        return self._running

    def get_status(self) -> Dict[str, Any]:
        """获取服务当前状态"""
        return {
            "running": self._running,
            "display_connected": self.is_display_connected(),
            "state": self._workflow.get_current_state().value if self._workflow else "idle",
            "capabilities": self.get_capabilities(),
        }

    def start(
        self,
        measure_fn: Callable[[Tuple[int, int, int], str], Any],
        target_config: Dict[str, Any],
        autocal_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        执行自动校准闭环（阻塞直到完成或取消；应在后台线程调用）

        Args:
            measure_fn: 同步测量桥 (rgb, name) -> MeasurementPoint
            target_config: 校准目标（white_point / target_Y / gamma / duv / dE 阈值）
            autocal_config: 工作流配置（dry_run / max_iterations / settling 等）

        Returns:
            AutoCalSession.to_dict() 会话结果
        """
        with self._lock:
            if self._running:
                raise AutoCalServiceError("校准已在运行中", "ALREADY_RUNNING")
            self._running = True

        try:
            adapter = self._require_adapter()
            target = self._parse_target(target_config)
            config = self._parse_config(autocal_config)

            # 用计数包装测量桥，向前端推送进度
            wrapped_measure = self._wrap_measure_fn(measure_fn, config)

            self._workflow = AutoCalWorkflow(
                display_adapter=adapter,
                measure_callback=wrapped_measure,
                session_dir=self._session_dir,
            )
            self._workflow.set_state_change_callback(self._on_state_change)

            display_name = (target_config.get("display_name") or "").strip()
            session = self._workflow.run(target, config, display_name=display_name)
            return session.to_dict()
        finally:
            self._running = False

    def stop(self) -> Dict[str, Any]:
        """请求取消当前校准（非阻塞）"""
        if self._workflow and self._running:
            self._workflow.cancel()
            return {"success": True, "message": "已请求取消，正在等待安全停止点..."}
        return {"success": False, "message": "没有正在运行的校准"}

    # ==================================================================
    # 内部方法
    # ==================================================================

    def _require_adapter(self) -> DisplayControlAdapter:
        if not self._display_adapter:
            raise AutoCalServiceError(
                "显示器控制通道未连接，请先连接 DDC/CI", "DISPLAY_NOT_CONNECTED"
            )
        return self._display_adapter

    def _resolve_control(self, name: str) -> ControlType:
        control = CONTROL_NAME_MAP.get(name)
        if not control:
            raise AutoCalServiceError(f"未知控制项: {name}", "UNKNOWN_CONTROL")
        return control

    def _parse_target(self, config: Dict[str, Any]) -> AutoCalTarget:
        """解析并约束校准目标"""
        white_point = str(config.get("white_point", "D65"))
        if white_point not in SUPPORTED_WHITE_POINTS:
            white_point = "D65"

        def _clamp_float(value, default, lo, hi):
            try:
                return max(lo, min(hi, float(value)))
            except (TypeError, ValueError):
                return default

        return AutoCalTarget(
            target_white_point=white_point,
            target_Y_white=_clamp_float(config.get("target_Y_white"), 100.0, 20.0, 1000.0),
            target_gamma=_clamp_float(config.get("target_gamma"), 2.2, 1.4, 3.0),
            target_duv_max=_clamp_float(config.get("target_duv_max"), 0.005, 0.001, 0.02),
            delta_e_threshold=_clamp_float(config.get("delta_e_threshold"), 2.0, 0.5, 10.0),
            max_iterations=int(_clamp_float(config.get("max_iterations"), 5, 1, 10)),
        )

    def _parse_config(self, config: Dict[str, Any]) -> AutoCalConfig:
        """解析并约束工作流配置"""
        mode_str = str(config.get("mode", "auto"))
        mode = AutoCalMode(mode_str) if mode_str in [m.value for m in AutoCalMode] else AutoCalMode.AUTO

        def _clamp_float(value, default, lo, hi):
            try:
                return max(lo, min(hi, float(value)))
            except (TypeError, ValueError):
                return default

        return AutoCalConfig(
            mode=mode,
            dry_run=bool(config.get("dry_run", False)),
            enable_manual_guide=bool(config.get("enable_manual_guide", True)),
            enable_rollback=bool(config.get("enable_rollback", True)),
            max_iterations=int(_clamp_float(config.get("max_iterations"), 5, 1, 10)),
            convergence_threshold=_clamp_float(config.get("convergence_threshold"), 1.0, 0.1, 5.0),
            settling_time=_clamp_float(config.get("settling_time"), 2.0, 0.5, 30.0),
            grayscale_steps=int(_clamp_float(config.get("grayscale_steps"), 5, 3, 21)),
            include_primaries=bool(config.get("include_primaries", True)),
        )

    def _wrap_measure_fn(
        self,
        measure_fn: Callable,
        config: AutoCalConfig,
    ) -> Callable[[Tuple[int, int, int], str], Any]:
        """包装测量桥：统计完成点数并推送进度"""
        per_iteration = 2 + config.grayscale_steps + (3 if config.include_primaries else 0)
        total_estimate = per_iteration * 2  # 基线 + 至少一次验证
        state = {"count": 0}

        def wrapped(rgb: Tuple[int, int, int], name: str):
            point = measure_fn(rgb, name)
            state["count"] += 1
            if self.on_progress:
                percent = min(95.0, state["count"] / max(total_estimate, 1) * 90.0)
                label = f"测量 {name} (RGB {rgb[0]},{rgb[1]},{rgb[2]})"
                try:
                    self.on_progress(label, percent)
                except Exception:
                    pass
            return point

        return wrapped

    def _on_state_change(self, old_state: AutoCalState, new_state: AutoCalState) -> None:
        """工作流状态变化 → 回调转发"""
        if self.on_state:
            try:
                self.on_state(old_state.value, new_state.value)
            except Exception:
                pass

    def attach_iteration_reporter(self) -> None:
        """迭代完成后推送记录（由 Backend 在 finished 前通过会话数据实现，此处预留钩子）"""
        # 迭代记录随 session.to_dict() 一并返回；实时逐迭代推送
        # 依赖 workflow 内部回调，当前版本在完成后统一上报。
        pass

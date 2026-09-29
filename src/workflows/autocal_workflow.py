"""
AutoCal Workflow - 自动校准闭环工作流

本模块实现从测量到自动调整显示器参数的完整闭环：

    1. preflight: 检查环境和设备状态
    2. baseline measurement: 获取当前测量值
    3. solve adjustment: 计算调整方案
    4. apply adjustment: 应用调整或生成手动调整指导
    5. verify: 验证调整效果
    6. iterate: 循环迭代直到达标或达到最大迭代次数

关键设计：
    - 每次写设备前保存 rollback snapshot
    - 支持 dry-run 模式（只计算不执行）
    - 自动失败时生成手动调整指导
    - 支持最大迭代次数限制

Reference:
    - docs/professional_optimization_plan.md (P5-A 任务)
"""

import copy
import json
import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from src.instruments.display_control import (
    ControlType,
    DisplayControlAdapter,
    DisplayCapabilities,
    DisplayCapability,
    ControlSnapshot,
    AdjustmentResult,
    AdjustmentBatch,
    DisplayControlError,
    FakeDisplayControlAdapter,
    ManualAdjustmentGuide,
    ManualAdjustmentGuideGenerator,
    create_fake_display_adapter,
)

from src.color_science import (
    delta_e_ciede2000,
    xyz_to_lab,
    xyY_to_xyz,
    cct_duv_from_xy,
    get_white_point_xy,
    WHITE_POINTS,
)


logger = logging.getLogger(__name__)


# ==============================================================================
# Enums and Data Classes
# ==============================================================================

class AutoCalState(Enum):
    """
    自动校准工作流状态

    - IDLE: 初始状态
    - PREFLIGHT: 正在进行环境检查
    - BASELINE: 正在进行基线测量
    - SOLVING: 正在计算调整方案
    - APPLYING: 正在应用调整
    - VERIFYING: 正在验证调整效果
    - ITERATING: 正在进行迭代调整
    - COMPLETED: 校准完成
    - FAILED: 校准失败
    - ROLLBACK: 已回滚
    """
    IDLE = "idle"
    PREFLIGHT = "preflight"
    BASELINE = "baseline"
    SOLVING = "solving"
    APPLYING = "applying"
    VERIFYING = "verifying"
    ITERATING = "iterating"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLBACK = "rollback"
    CANCELLED = "cancelled"


class AutoCalMode(Enum):
    """
    校准模式

    - AUTO: 自动调整 (使用 DDC/CI)
    - MANUAL: 手动调整 (生成指导文档)
    - HYBRID: 混合模式 (自动 + 手动指导)
    """
    AUTO = "auto"
    MANUAL = "manual"
    HYBRID = "hybrid"


class AdjustmentSolver(Enum):
    """
    调整求解器类型

    - SIMPLE: 简单线性求解器
    - ITERATIVE: 迭代逼近求解器
    - ML: 机器学习求解器 (未来)
    """
    SIMPLE = "simple"
    ITERATIVE = "iterative"
    ML = "ml"


@dataclass
class AutoCalTarget:
    """
    校准目标

    Attributes:
        target_white_point: 目标白点名称 ("D65", "D50", etc.)
        target_cct: 目标 CCT (K)
        target_duv_max: 目标 Duv 最大偏差
        target_Y_white: 目标白场亮度 (cd/m²)
        target_gamma: 目标 Gamma
        delta_e_threshold: Delta E 合格阈值
        max_iterations: 最大迭代次数
    """
    target_white_point: str = "D65"
    target_cct: float = 6500.0
    target_duv_max: float = 0.005
    target_Y_white: float = 100.0
    target_gamma: float = 2.2
    delta_e_threshold: float = 2.0
    max_iterations: int = 5

    def get_white_xy(self) -> Tuple[float, float]:
        """获取目标白点 xy"""
        wp = WHITE_POINTS.get(self.target_white_point)
        if wp:
            return wp  # WHITE_POINTS values are (x, y) tuples
        # 默认 D65
        return (0.3127, 0.3290)


@dataclass
class MeasurementPoint:
    """
    单个测量点

    Attributes:
        rgb: RGB 值 (0-255)
        name: 色块名称
        xyY: 测量 xyY 值
        xyz: 测量 XYZ 值
        Y: 亮度 (cd/m²)
        timestamp: 测量时间
        iteration: 迭代次数 (用于追踪变化)
    """
    rgb: Tuple[int, int, int]
    name: str = ""
    xyY: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    xyz: Optional[Tuple[float, float, float]] = None
    Y: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    iteration: int = 0

    def __post_init__(self):
        if self.Y == 0.0 and self.xyY[2] > 0:
            self.Y = self.xyY[2]

    @property
    def xy(self) -> Tuple[float, float]:
        """获取 xy 坐标"""
        return (self.xyY[0], self.xyY[1])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rgb": list(self.rgb),
            "name": self.name,
            "xyY": list(self.xyY),
            "xyz": list(self.xyz) if self.xyz else None,
            "Y": self.Y,
            "timestamp": self.timestamp.isoformat(),
            "iteration": self.iteration,
        }


@dataclass
class BaselineMeasurement:
    """
    基线测量结果

    Attributes:
        white_point: 白场测量点
        black_point: 黑场测量点
        gray_points: 灰阶测量点列表
        primary_points: RGB primaries 测量点
        timestamp: 测量时间
        iteration: 迭代次数
    """
    white_point: Optional[MeasurementPoint] = None
    black_point: Optional[MeasurementPoint] = None
    gray_points: List[MeasurementPoint] = field(default_factory=list)
    primary_points: Dict[str, MeasurementPoint] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    iteration: int = 0

    def get_white_xyY(self) -> Optional[Tuple[float, float, float]]:
        """获取白场 xyY"""
        if self.white_point:
            return self.white_point.xyY
        return None

    def get_white_Y(self) -> float:
        """获取白场亮度"""
        if self.white_point:
            return self.white_point.Y
        return 0.0

    def get_cct_duv(self) -> Tuple[float, float]:
        """获取白场 CCT 和 Duv"""
        if self.white_point and self.white_point.xyY:
            return cct_duv_from_xy(self.white_point.xy[0], self.white_point.xy[1])
        return (0.0, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "white_point": self.white_point.to_dict() if self.white_point else None,
            "black_point": self.black_point.to_dict() if self.black_point else None,
            "gray_points": [p.to_dict() for p in self.gray_points],
            "primary_points": {k: v.to_dict() for k, v in self.primary_points.items()},
            "timestamp": self.timestamp.isoformat(),
            "iteration": self.iteration,
        }


@dataclass
class AdjustmentSolution:
    """
    调整方案

    Attributes:
        controls: 控制值调整 {ControlType: delta}
        absolute_values: 绝对控制值 {ControlType: value}
        predicted_effect: 预测效果说明
        confidence: 信心度 (0-1)
        solver: 求解器类型
        iteration: 迭代次数
    """
    controls: Dict[ControlType, int] = field(default_factory=dict)
    absolute_values: Dict[ControlType, int] = field(default_factory=dict)
    predicted_effect: str = ""
    confidence: float = 0.5
    solver: AdjustmentSolver = AdjustmentSolver.SIMPLE
    iteration: int = 0

    def get_total_change(self) -> int:
        """获取总变化量"""
        return sum(abs(v) for v in self.controls.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "controls": {k.value: v for k, v in self.controls.items()},
            "absolute_values": {k.value: v for k, v in self.absolute_values.items()},
            "predicted_effect": self.predicted_effect,
            "confidence": self.confidence,
            "solver": self.solver.value,
            "iteration": self.iteration,
        }


@dataclass
class VerificationResult:
    """
    验证结果

    Attributes:
        delta_e_avg: 平均 Delta E
        delta_e_max: 最大 Delta E
        cct: 当前白场 CCT
        duv: 当前白场 Duv
        Y_white: 白场亮度
        gamma_avg: 平均 Gamma
        passed: 是否达标
        pass_details: 各项合格详情
        iteration: 迭代次数
    """
    delta_e_avg: float = 0.0
    delta_e_max: float = 0.0
    cct: float = 6500.0
    duv: float = 0.0
    Y_white: float = 100.0
    gamma_avg: float = 2.2
    passed: bool = False
    pass_details: Dict[str, bool] = field(default_factory=dict)
    iteration: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "delta_e_avg": self.delta_e_avg,
            "delta_e_max": self.delta_e_max,
            "cct": self.cct,
            "duv": self.duv,
            "Y_white": self.Y_white,
            "gamma_avg": self.gamma_avg,
            "passed": self.passed,
            "pass_details": self.pass_details,
            "iteration": self.iteration,
        }


@dataclass
class IterationRecord:
    """
    单次迭代记录

    Attributes:
        iteration_number: 迭代编号
        baseline: 基线测量
        solution: 调整方案
        batch: 调整批次结果
        verification: 验证结果
        snapshot: 控制值快照
        timestamp: 时间戳
    """
    iteration_number: int = 0
    baseline: Optional[BaselineMeasurement] = None
    solution: Optional[AdjustmentSolution] = None
    batch: Optional[AdjustmentBatch] = None
    verification: Optional[VerificationResult] = None
    snapshot: Optional[ControlSnapshot] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration_number": self.iteration_number,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "solution": self.solution.to_dict() if self.solution else None,
            "batch": self.batch.to_dict() if self.batch else None,
            "verification": self.verification.to_dict() if self.verification else None,
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class AutoCalSession:
    """
    自动校准会话

    Attributes:
        session_id: 会话 ID
        display_id: 显示器 ID
        display_name: 显示器名称
        state: 当前状态
        mode: 校准模式
        target: 校准目标
        dry_run: 是否 dry-run
        start_time: 开始时间
        end_time: 结束时间
        iterations: 迭代记录列表
        final_result: 最终验证结果
        manual_guide: 手动调整指导
        rollback_performed: 是否执行了回滚
        error_message: 错误信息
    """
    session_id: str = ""
    display_id: int = 0
    display_name: str = ""
    state: AutoCalState = AutoCalState.IDLE
    mode: AutoCalMode = AutoCalMode.AUTO
    target: AutoCalTarget = field(default_factory=AutoCalTarget)
    dry_run: bool = False
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    iterations: List[IterationRecord] = field(default_factory=list)
    final_result: Optional[VerificationResult] = None
    manual_guide: Optional[ManualAdjustmentGuide] = None
    rollback_performed: bool = False
    error_message: str = ""

    @property
    def duration_seconds(self) -> float:
        """计算持续时间"""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return (datetime.now() - self.start_time).total_seconds()

    @property
    def iteration_count(self) -> int:
        """获取迭代次数"""
        return len(self.iterations)

    def add_iteration(self, record: IterationRecord) -> None:
        """添加迭代记录"""
        self.iterations.append(record)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "display_id": self.display_id,
            "display_name": self.display_name,
            "state": self.state.value,
            "mode": self.mode.value,
            "target": asdict(self.target),
            "dry_run": self.dry_run,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "iterations": [i.to_dict() for i in self.iterations],
            "final_result": self.final_result.to_dict() if self.final_result else None,
            "manual_guide": self.manual_guide.to_dict() if self.manual_guide else None,
            "rollback_performed": self.rollback_performed,
            "error_message": self.error_message,
            "duration_seconds": self.duration_seconds,
            "iteration_count": self.iteration_count,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def save_to_file(self, path: Union[str, Path]) -> bool:
        """保存会话到文件"""
        try:
            Path(path).write_text(self.to_json(), encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"Failed to save session: {e}")
            return False


@dataclass
class AutoCalConfig:
    """
    自动校准配置

    Attributes:
        mode: 校准模式
        solver: 求解器类型
        dry_run: 是否 dry-run
        enable_manual_guide: 是否生成手动指导
        enable_rollback: 是否启用回滚
        max_iterations: 最大迭代次数
        convergence_threshold: 收敛阈值 (Delta E)
        measure_delay: 测量间隔 (秒)
        settling_time: 显示器稳定时间 (秒)
        grayscale_steps: 灰阶测量点数
        include_primaries: 是否测量 primaries
    """
    mode: AutoCalMode = AutoCalMode.AUTO
    solver: AdjustmentSolver = AdjustmentSolver.SIMPLE
    dry_run: bool = False
    enable_manual_guide: bool = True
    enable_rollback: bool = True
    max_iterations: int = 5
    convergence_threshold: float = 1.0
    measure_delay: float = 0.5
    settling_time: float = 2.0
    grayscale_steps: int = 5
    include_primaries: bool = True


class AutoCalError(Exception):
    """
    自动校准异常

    Attributes:
        error_code: 错误代码
        state: 异常发生时的状态
        recoverable: 是否可恢复
        suggestion: 建议
    """
    def __init__(
        self,
        message: str,
        error_code: str = "UNKNOWN",
        state: AutoCalState = AutoCalState.FAILED,
        recoverable: bool = False,
        suggestion: str = ""
    ):
        super().__init__(message)
        self.error_code = error_code
        self.state = state
        self.recoverable = recoverable
        self.suggestion = suggestion


# ==============================================================================
# Adjustment Solver
# ==============================================================================

class SimpleAdjustmentSolver:
    """
    简单调整求解器

    基于线性近似计算 RGB gain/offset 调整。
    """

    def __init__(self, config: AutoCalConfig):
        self._config = config

    def solve(
        self,
        baseline: BaselineMeasurement,
        target: AutoCalTarget,
        current_controls: Dict[ControlType, int],
        iteration: int = 0,
    ) -> AdjustmentSolution:
        """
        计算调整方案

        Args:
            baseline: 基线测量
            target: 校准目标
            current_controls: 当前控制值
            iteration: 当前迭代次数

        Returns:
            AdjustmentSolution 调整方案
        """
        if not baseline.white_point:
            return AdjustmentSolution(
                predicted_effect="No white point measurement available",
                confidence=0.0,
                iteration=iteration,
            )

        # 计算白场偏差
        measured_xy = baseline.white_point.xy
        target_xy = target.get_white_xy()

        # 计算偏差
        dx = measured_xy[0] - target_xy[0]
        dy = measured_xy[1] - target_xy[1]

        # 简单线性调整：基于 RGB 对白点的影响
        # 红色增加 -> x 增加
        # 绿色增加 -> y 增加
        # 蓝色增加 -> x/y 都减少 (相对)

        # 计算调整量 (每单位 gain 变化对 xy 的影响约为 0.005)
        gain_scale = 0.005  # 每单位 gain 变化对 xy 的影响

        adjustments = {}
        absolute_values = {}

        # 当前 RGB gain 值
        current_r = current_controls.get(ControlType.RED_GAIN, 50)
        current_g = current_controls.get(ControlType.GREEN_GAIN, 50)
        current_b = current_controls.get(ControlType.BLUE_GAIN, 50)

        # 调整 RGB gain 以校正白点
        # dx > 0 表示 x 过高，需要减少红色或增加蓝色
        # dy > 0 表示 y 过高，需要减少绿色或增加蓝色

        # 收敛判定必须用 duv（uv 空间欧氏距离）与 target_duv_max 比较；
        # dx/dy 是 xy 空间偏差，量纲与 duv 不同（典型差 2~5 倍且随 CCT 变化），
        # 直接比较会导致收敛判定过严（振荡）或过松
        def _xy_to_uv(x: float, y: float):
            denom = -2.0 * x + 12.0 * y + 3.0
            if denom <= 0:
                return None
            return (4.0 * x / denom, 6.0 * y / denom)

        measured_uv = _xy_to_uv(measured_xy[0], measured_xy[1])
        target_uv = _xy_to_uv(target_xy[0], target_xy[1])
        if measured_uv is None or target_uv is None:
            duv = float("inf")
        else:
            duv = math.hypot(measured_uv[0] - target_uv[0],
                             measured_uv[1] - target_uv[1])

        if duv > target.target_duv_max:
            # 需要调整
            # 简化算法：根据偏差方向调整 RGB gain

            if dx > 0:
                # x 过高，减少红色或增加蓝色
                r_delta = -int(dx / gain_scale)
                b_delta = int(dx / gain_scale * 0.5)
            elif dx < 0:
                # x 过低，增加红色或减少蓝色
                r_delta = int(-dx / gain_scale)
                b_delta = -int(-dx / gain_scale * 0.5)
            else:
                r_delta = 0
                b_delta = 0

            if dy > 0:
                # y 过高，减少绿色或增加蓝色
                g_delta = -int(dy / gain_scale)
                b_delta += int(dy / gain_scale * 0.5)
            elif dy < 0:
                # y 过低，增加绿色或减少蓝色
                g_delta = int(-dy / gain_scale)
                b_delta -= int(-dy / gain_scale * 0.5)
            else:
                g_delta = 0

            # 约束调整量
            max_adjustment = 10  # 单次最大调整
            r_delta = max(-max_adjustment, min(max_adjustment, r_delta))
            g_delta = max(-max_adjustment, min(max_adjustment, g_delta))
            b_delta = max(-max_adjustment, min(max_adjustment, b_delta))

            if r_delta != 0:
                adjustments[ControlType.RED_GAIN] = r_delta
                absolute_values[ControlType.RED_GAIN] = max(0, min(100, current_r + r_delta))
            if g_delta != 0:
                adjustments[ControlType.GREEN_GAIN] = g_delta
                absolute_values[ControlType.GREEN_GAIN] = max(0, min(100, current_g + g_delta))
            if b_delta != 0:
                adjustments[ControlType.BLUE_GAIN] = b_delta
                absolute_values[ControlType.BLUE_GAIN] = max(0, min(100, current_b + b_delta))

        # 亮度调整
        measured_Y = baseline.get_white_Y()
        if measured_Y > 0 and abs(measured_Y - target.target_Y_white) > 5:
            y_delta = int((target.target_Y_white - measured_Y) / 2)  # 简化：每单位亮度约 2 cd/m²
            y_delta = max(-10, min(10, y_delta))

            current_brightness = current_controls.get(ControlType.BRIGHTNESS, 50)
            adjustments[ControlType.BRIGHTNESS] = y_delta
            absolute_values[ControlType.BRIGHTNESS] = max(0, min(100, current_brightness + y_delta))

        # 预测效果
        predicted_effect = ""
        if adjustments:
            predicted_effect = f"预期校正白点偏差: dx={dx:.4f}, dy={dy:.4f}"
            if ControlType.BRIGHTNESS in adjustments:
                predicted_effect += f", 亮度偏差: {measured_Y:.1f} -> {target.target_Y_white:.1f}"

        return AdjustmentSolution(
            controls=adjustments,
            absolute_values=absolute_values,
            predicted_effect=predicted_effect,
            confidence=0.5 if adjustments else 1.0,
            solver=AdjustmentSolver.SIMPLE,
            iteration=iteration,
        )


# ==============================================================================
# AutoCalWorkflow
# ==============================================================================

class AutoCalWorkflow:
    """
    自动校准闭环工作流

    完成从测量到自动调整显示器参数的闭环：
        1. preflight: 检查环境和设备状态
        2. baseline measurement: 获取当前测量值
        3. solve adjustment: 计算调整方案
        4. apply adjustment: 应用调整或生成手动调整指导
        5. verify: 验证调整效果
        6. iterate: 循环迭代直到达标或达到最大迭代次数

    关键特性：
        - 每次写设备前保存 rollback snapshot
        - 支持 dry-run 模式
        - 自动失败时生成手动调整指导
        - 支持最大迭代次数限制

    Example:
        >>> workflow = AutoCalWorkflow(display_adapter, measure_callback)
        >>> session = workflow.run(target, config)
        >>> if session.state == AutoCalState.COMPLETED:
        >>>     print("校准成功")
    """

    def __init__(
        self,
        display_adapter: DisplayControlAdapter,
        measure_callback: Callable[
            [Tuple[int, int, int], str],
            MeasurementPoint
        ],
        preflight_checker: Optional[Any] = None,  # PreflightChecker
        session_dir: Optional[Path] = None,
    ):
        """
        初始化工作流

        Args:
            display_adapter: 显示器控制适配器
            measure_callback: 测量回调函数 (rgb, name) -> MeasurementPoint
            preflight_checker: PreflightChecker 实例 (可选)
            session_dir: 会话数据保存目录 (可选)
        """
        self._display_adapter = display_adapter
        self._measure_callback = measure_callback
        self._preflight_checker = preflight_checker
        self._session_dir = session_dir

        # 配置
        self._config: Optional[AutoCalConfig] = None
        self._target: Optional[AutoCalTarget] = None

        # 会话状态
        self._session: Optional[AutoCalSession] = None

        # 求解器
        self._solver: Optional[SimpleAdjustmentSolver] = None

        # 手动调整指导生成器
        self._guide_generator = ManualAdjustmentGuideGenerator()

        # 状态变化回调
        self._state_change_callback: Optional[Callable[AutoCalState, AutoCalState]] = None

        # 取消请求标志（由外部线程设置，在安全点检查）
        self._cancel_requested = False

        logger.info("AutoCalWorkflow initialized")

    def cancel(self) -> None:
        """请求取消当前校准

        线程安全：可在任意线程调用。工作流在下一个安全点
        （迭代边界 / 单个测量点之间）停止并进入 CANCELLED 状态。
        已写入的显示器调整不会被自动回滚（可手动调用 rollback()）。
        """
        self._cancel_requested = True
        logger.info("AutoCalWorkflow cancel requested")

    @property
    def is_cancel_requested(self) -> bool:
        """是否已请求取消"""
        return self._cancel_requested

    def set_state_change_callback(
        self,
        callback: Callable[AutoCalState, AutoCalState]
    ) -> None:
        """设置状态变化回调"""
        self._state_change_callback = callback

    def _update_state(self, new_state: AutoCalState) -> None:
        """更新状态"""
        old_state = self._session.state if self._session else AutoCalState.IDLE
        if self._session:
            self._session.state = new_state

        if self._state_change_callback and old_state != new_state:
            self._state_change_callback(old_state, new_state)

        logger.info(f"State changed: {old_state.value} -> {new_state.value}")

    def run(
        self,
        target: AutoCalTarget,
        config: AutoCalConfig,
        display_name: str = "",
    ) -> AutoCalSession:
        """
        执行自动校准工作流

        Args:
            target: 校准目标
            config: 校准配置
            display_name: 显示器名称 (可选)

        Returns:
            AutoCalSession 校准会话结果
        """
        # 初始化
        self._target = target
        self._config = config
        self._solver = SimpleAdjustmentSolver(config)

        # 创建会话
        self._session = AutoCalSession(
            session_id=f"autocal_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            display_id=self._display_adapter.display_id,
            display_name=display_name,
            state=AutoCalState.IDLE,
            mode=config.mode,
            target=target,
            dry_run=config.dry_run,
        )

        logger.info(f"AutoCalWorkflow started: session_id={self._session.session_id}, mode={config.mode.value}")

        try:
            # Step 1: Preflight
            self._preflight()

            # Step 2: Baseline measurement
            baseline = self._measure_baseline(iteration=0)

            # 迭代调整
            iteration = 0
            passed = False

            while iteration < target.max_iterations:
                # 安全点：检查取消请求
                if self._cancel_requested:
                    self._session.error_message = "Cancelled by user"
                    self._update_state(AutoCalState.CANCELLED)
                    break

                iteration += 1

                # Step 3: Solve adjustment
                self._update_state(AutoCalState.SOLVING)
                current_controls = self._get_current_controls()
                solution = self._solver.solve(baseline, target, current_controls, iteration)

                if not solution.controls:
                    # 无需调整，已完成 - 记录这次迭代
                    verification = self._verify(baseline, target, iteration)
                    iteration_record = IterationRecord(
                        iteration_number=iteration,
                        baseline=baseline,
                        solution=solution,
                        batch=AdjustmentBatch(all_success=True, dry_run=config.dry_run),
                        verification=verification,
                    )
                    self._session.add_iteration(iteration_record)
                    passed = True
                    break

                # Step 4: Apply adjustment
                self._update_state(AutoCalState.APPLYING)
                batch = self._apply_adjustment(solution, config.dry_run)

                if not batch.all_success and not config.dry_run:
                    # 调整失败，尝试 rollback
                    if config.enable_rollback and self._display_adapter.has_snapshot:
                        self._update_state(AutoCalState.ROLLBACK)
                        self._display_adapter.rollback()
                        self._session.rollback_performed = True
                        logger.warning("Adjustment failed, rollback performed")

                    # 生成手动调整指导
                    if config.enable_manual_guide:
                        self._session.manual_guide = self._generate_manual_guide(solution, batch)

                    self._update_state(AutoCalState.FAILED)
                    self._session.error_message = "Adjustment application failed"
                    break

                # Step 5: Verify
                self._update_state(AutoCalState.VERIFYING)
                # 等待显示器稳定
                import time
                time.sleep(config.settling_time)

                verification_baseline = self._measure_baseline(iteration=iteration)
                verification = self._verify(verification_baseline, target, iteration)

                # 记录迭代
                iteration_record = IterationRecord(
                    iteration_number=iteration,
                    baseline=baseline,
                    solution=solution,
                    batch=batch,
                    verification=verification,
                    snapshot=self._display_adapter.save_snapshot(f"iteration_{iteration}"),
                )
                self._session.add_iteration(iteration_record)

                # 检查是否达标
                if verification.passed:
                    passed = True
                    break

                # 继续迭代
                self._update_state(AutoCalState.ITERATING)
                baseline = verification_baseline

                # 检查收敛
                if verification.delta_e_avg < config.convergence_threshold:
                    logger.info("Convergence achieved, but target not met")
                    break

            # 最终结果
            if passed:
                self._update_state(AutoCalState.COMPLETED)
                if not config.dry_run:
                    self._display_adapter.commit()

                # 最终验证 - 使用最后一次迭代的 verification 作为 final_result
                if self._session.iterations:
                    self._session.final_result = self._session.iterations[-1].verification
                else:
                    # Fallback: 直接使用 baseline 验证
                    self._session.final_result = self._verify(baseline, target, iteration)
            else:
                # 达到最大迭代次数仍未达标
                if iteration >= target.max_iterations:
                    self._session.error_message = f"Max iterations ({target.max_iterations}) reached without convergence"

                # 如果是手动模式或需要手动指导，生成指导
                if config.mode == AutoCalMode.MANUAL or (config.enable_manual_guide and not passed):
                    self._session.manual_guide = self._generate_final_manual_guide()

                self._update_state(AutoCalState.FAILED if not config.dry_run else AutoCalState.COMPLETED)

        except AutoCalError as e:
            logger.error(f"AutoCalWorkflow error: {e}")
            self._session.error_message = str(e)
            self._update_state(e.state)

            # 用户取消时不自动回滚（保留当前状态，可手动 rollback()）
            if e.error_code != "CANCELLED":
                # 尝试 rollback
                if config.enable_rollback and self._display_adapter.has_snapshot:
                    try:
                        self._display_adapter.rollback()
                        self._session.rollback_performed = True
                    except Exception as rollback_error:
                        logger.error(f"Rollback failed: {rollback_error}")

        except Exception as e:
            logger.error(f"AutoCalWorkflow unexpected error: {e}")
            self._session.error_message = str(e)
            self._update_state(AutoCalState.FAILED)

        # 结束会话
        self._session.end_time = datetime.now()

        # 保存会话
        if self._session_dir:
            session_file = self._session_dir / f"{self._session.session_id}.json"
            self._session.save_to_file(session_file)

        logger.info(f"AutoCalWorkflow completed: state={self._session.state.value}, iterations={self._session.iteration_count}")

        return self._session

    def _preflight(self) -> None:
        """
        Preflight 检查

        检查环境和设备状态，确保可以开始校准。
        """
        self._update_state(AutoCalState.PREFLIGHT)

        # 检查显示器连接
        if not self._display_adapter.is_connected:
            try:
                self._display_adapter.connect()
            except DisplayControlError as e:
                raise AutoCalError(
                    message=f"Failed to connect to display: {e}",
                    error_code="DISPLAY_NOT_CONNECTED",
                    state=AutoCalState.FAILED,
                    recoverable=True,
                    suggestion="Check display connection and DDC/CI support",
                )

        # 检查显示器能力
        caps = self._display_adapter.get_capabilities()
        self._guide_generator.set_capabilities(caps)

        # 检查是否有可写控制项
        writable_controls = caps.get_writable_controls()
        if not writable_controls:
            raise AutoCalError(
                message="No writable controls available",
                error_code="NO_WRITABLE_CONTROLS",
                state=AutoCalState.FAILED,
                recoverable=False,
                suggestion="Display does not support DDC/CI control",
            )

        logger.info(f"Preflight passed: {len(writable_controls)} writable controls available")

    def _measure_baseline(self, iteration: int = 0) -> BaselineMeasurement:
        """
        测量基线

        Args:
            iteration: 当前迭代次数

        Returns:
            BaselineMeasurement 基线测量结果
        """
        self._update_state(AutoCalState.BASELINE)

        baseline = BaselineMeasurement(iteration=iteration)

        try:
            # 取消检查：基线测量点之间
            if self._cancel_requested:
                raise AutoCalError(
                    message="Cancelled by user",
                    error_code="CANCELLED",
                    state=AutoCalState.CANCELLED,
                )

            # 白场测量
            baseline.white_point = self._measure_callback((255, 255, 255), "white")

            # 黑场测量
            baseline.black_point = self._measure_callback((0, 0, 0), "black")

            # 灰阶测量
            gray_steps = self._config.grayscale_steps if self._config else 5
            for i in range(1, gray_steps + 1):
                if self._cancel_requested:
                    raise AutoCalError(
                        message="Cancelled by user",
                        error_code="CANCELLED",
                        state=AutoCalState.CANCELLED,
                    )
                level = int(255 * i / (gray_steps + 1))
                gray_point = self._measure_callback((level, level, level), f"gray_{i}")
                baseline.gray_points.append(gray_point)

            # RGB primaries 测量
            if self._config and self._config.include_primaries:
                baseline.primary_points["red"] = self._measure_callback((255, 0, 0), "red")
                baseline.primary_points["green"] = self._measure_callback((0, 255, 0), "green")
                baseline.primary_points["blue"] = self._measure_callback((0, 0, 255), "blue")

        except AutoCalError:
            # 取消等内部控制流异常原样上抛，保留状态码
            raise
        except Exception as e:
            raise AutoCalError(
                message=f"Baseline measurement failed: {e}",
                error_code="MEASUREMENT_FAILED",
                state=AutoCalState.FAILED,
                recoverable=True,
                suggestion="Check instrument connection and try again",
            )

        return baseline

    def _get_current_controls(self) -> Dict[ControlType, int]:
        """获取当前控制值"""
        controls = {}
        caps = self._display_adapter.get_capabilities()

        for cap in caps.capabilities:
            if cap.readable:
                try:
                    value = self._display_adapter.read_control(cap.control_type)
                    controls[cap.control_type] = value
                except DisplayControlError:
                    pass

        return controls

    def _apply_adjustment(
        self,
        solution: AdjustmentSolution,
        dry_run: bool = False,
    ) -> AdjustmentBatch:
        """
        应用调整方案

        Args:
            solution: 调整方案
            dry_run: 是否 dry-run

        Returns:
            AdjustmentBatch 调整结果
        """
        # 使用绝对值
        adjustments = solution.absolute_values

        if not adjustments:
            return AdjustmentBatch(
                results=[],
                dry_run=dry_run,
                all_success=True,
            )

        # 保存 rollback snapshot
        if not dry_run and self._config and self._config.enable_rollback:
            snapshot = self._display_adapter.save_snapshot("before_apply")

        # 批量写入
        batch = self._display_adapter.write_batch(adjustments, dry_run=dry_run)

        return batch

    def _verify(
        self,
        baseline: BaselineMeasurement,
        target: AutoCalTarget,
        iteration: int = 0,
    ) -> VerificationResult:
        """
        验证调整效果

        Args:
            baseline: 当前测量基线
            target: 校准目标
            iteration: 当前迭代次数

        Returns:
            VerificationResult 验证结果
        """
        result = VerificationResult(iteration=iteration)

        if not baseline.white_point:
            result.passed = False
            result.pass_details["white_point"] = False
            return result

        # 计算白场 CCT/Duv
        cct, duv = baseline.get_cct_duv()
        result.cct = cct
        result.duv = duv

        # 白场亮度
        result.Y_white = baseline.get_white_Y()

        # 计算 Gamma (简化)
        if baseline.gray_points:
            result.gamma_avg = self._estimate_gamma(baseline.gray_points)

        # 计算 Delta E (白场偏差)
        target_xy = target.get_white_xy()
        target_xyz = xyY_to_xyz(target_xy[0], target_xy[1], target.target_Y_white)

        if baseline.white_point.xyz:
            # 假设 D65 作为参考白点
            ref_white = WHITE_POINTS.get("D65")
            if ref_white:
                ref_xyz = (ref_white.X, ref_white.Y, ref_white.Z)
                lab_measured = xyz_to_lab(baseline.white_point.xyz, ref_xyz)
                lab_target = xyz_to_lab(target_xyz, ref_xyz)
                result.delta_e_avg = delta_e_ciede2000(lab_measured, lab_target)

        # 判断是否达标
        pass_details = {
            "cct": abs(cct - target.target_cct) < 200,
            "duv": abs(duv) < target.target_duv_max,
            "Y_white": abs(result.Y_white - target.target_Y_white) < 10,
            "gamma": abs(result.gamma_avg - target.target_gamma) < 0.1,
            "delta_e": result.delta_e_avg < target.delta_e_threshold,
        }

        result.pass_details = pass_details
        result.passed = all(pass_details.values())

        logger.info(f"Verification: passed={result.passed}, delta_e={result.delta_e_avg:.2f}, cct={cct:.0f}K, duv={duv:.4f}")

        return result

    def _estimate_gamma(self, gray_points: List[MeasurementPoint]) -> float:
        """
        估算 Gamma 值

        简化算法：基于灰阶亮度曲线拟合。
        """
        if len(gray_points) < 2:
            return 2.2

        # 使用最小二乘法拟合
        # Y = (input/255)^gamma * Y_max
        # log(Y) = gamma * log(input/255) + log(Y_max)

        import math

        sum_log_input = 0.0
        sum_log_Y = 0.0
        sum_log_input_sq = 0.0
        sum_log_input_Y = 0.0
        n = 0

        for point in gray_points:
            if point.Y > 0 and point.rgb[0] > 0:
                log_input = math.log(point.rgb[0] / 255.0)
                log_Y = math.log(point.Y)
                sum_log_input += log_input
                sum_log_Y += log_Y
                sum_log_input_sq += log_input * log_input
                sum_log_input_Y += log_input * log_Y
                n += 1

        if n < 2:
            return 2.2

        # Linear regression: gamma = slope
        gamma = (n * sum_log_input_Y - sum_log_input * sum_log_Y) / (n * sum_log_input_sq - sum_log_input * sum_log_input)

        # 约束到合理范围
        return max(1.5, min(3.0, gamma))

    def _generate_manual_guide(
        self,
        solution: AdjustmentSolution,
        batch: AdjustmentBatch,
    ) -> ManualAdjustmentGuide:
        """
        生成手动调整指导

        Args:
            solution: 调整方案
            batch: 调整批次结果

        Returns:
            ManualAdjustmentGuide
        """
        current_values = self._get_current_controls()
        target_values = solution.absolute_values

        return self._guide_generator.generate(
            current_values=current_values,
            target_values=target_values,
            display_name=self._session.display_name if self._session else "",
            summary="自动调整失败，请按照以下步骤手动调整显示器 OSD 设置",
        )

    def _generate_final_manual_guide(self) -> ManualAdjustmentGuide:
        """
        生成最终手动调整指导

        基于最终测量偏差生成指导。
        """
        # 获取最后一次迭代的测量和方案
        if self._session and self._session.iterations:
            last_iteration = self._session.iterations[-1]
            if last_iteration.solution:
                return self._generate_manual_guide(
                    last_iteration.solution,
                    last_iteration.batch or AdjustmentBatch(),
                )

        # 默认指导
        return ManualAdjustmentGuide(
            display_name=self._session.display_name if self._session else "",
            summary="校准未达标，建议手动调整显示器 OSD 设置",
            steps=[],
            estimated_time=5,
        )

    def rollback(self) -> bool:
        """
        手动回滚到初始状态

        Returns:
            True 如果回滚成功
        """
        if self._display_adapter.has_snapshot:
            try:
                success = self._display_adapter.rollback()
                if success and self._session:
                    self._session.rollback_performed = True
                    self._update_state(AutoCalState.ROLLBACK)
                return success
            except DisplayControlError as e:
                logger.error(f"Manual rollback failed: {e}")
                return False
        return False

    def get_session(self) -> Optional[AutoCalSession]:
        """获取当前会话"""
        return self._session

    def get_current_state(self) -> AutoCalState:
        """获取当前状态"""
        return self._session.state if self._session else AutoCalState.IDLE


# ==============================================================================
# Factory Functions
# ==============================================================================

def create_autocal_workflow(
    display_adapter: Optional[DisplayControlAdapter] = None,
    measure_callback: Optional[Callable] = None,
    use_fake: bool = True,
    fake_brightness: int = 50,
    fake_rgb_gain: Tuple[int, int, int] = (50, 50, 50),
) -> AutoCalWorkflow:
    """
    创建自动校准工作流

    Args:
        display_adapter: 显示器控制适配器 (可选)
        measure_callback: 测量回调函数 (可选)
        use_fake: 是否使用假适配器
        fake_brightness: 假适配器初始亮度
        fake_rgb_gain: 假适配器初始 RGB gain

    Returns:
        AutoCalWorkflow
    """
    if display_adapter is None:
        if use_fake:
            display_adapter = create_fake_display_adapter(
                display_id=0,
                initial_brightness=fake_brightness,
                initial_rgb_gain=fake_rgb_gain,
            )
        else:
            display_adapter = create_display_adapter(display_id=1, use_ddcci=True)

    if measure_callback is None:
        # 使用假测量回调
        def fake_measure_callback(rgb: Tuple[int, int, int], name: str) -> MeasurementPoint:
            # 模拟测量结果
            # 白场模拟
            if rgb == (255, 255, 255):
                # 假设偏差白点
                xyY = (0.3140, 0.3310, 100.0)  # 略有偏差
            elif rgb == (0, 0, 0):
                xyY = (0.0, 0.0, 0.1)
            elif name.startswith("gray"):
                level = rgb[0] / 255.0
                Y = 100.0 * (level ** 2.2)
                xyY = (0.3127, 0.3290, Y)
            else:
                # primaries
                xyY = (0.3127, 0.3290, 50.0)

            return MeasurementPoint(rgb=rgb, name=name, xyY=xyY)

        measure_callback = fake_measure_callback

    return AutoCalWorkflow(display_adapter=display_adapter, measure_callback=measure_callback)


def run_autocal_dry_run(
    target: Optional[AutoCalTarget] = None,
    config: Optional[AutoCalConfig] = None,
) -> AutoCalSession:
    """
    执行 dry-run 自动校准

    用于测试和验证 workflow，不实际改变显示器设置。

    Args:
        target: 校准目标 (可选，使用默认值)
        config: 校准配置 (可选，使用 dry-run 默认值)

    Returns:
        AutoCalSession 校准会话结果
    """
    target = target or AutoCalTarget()
    config = config or AutoCalConfig(dry_run=True, enable_rollback=False)

    workflow = create_autocal_workflow(use_fake=True)
    return workflow.run(target, config)
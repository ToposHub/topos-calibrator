"""
Display Control Adapter - 显示器控制接口

本模块定义显示器自动调整的抽象接口：
    - DisplayControlAdapter: 显示器控制抽象接口
    - DisplayCapability: 控制项能力描述
    - ControlType: 控制项类型枚举
    - DDCCIAdapter: DDC/CI 协议实现
    - FakeDisplayControlAdapter: 测试用假适配器
    - ManualAdjustmentGuide: 手动调整指导生成器

设计原则：
    - 所有写操作前必须保存 rollback snapshot
    - 支持 dry-run 模式（只计算不执行）
    - 支持 commit/rollback 事务机制
    - DDC/CI 控制需要权限检查（macOS Accessibility）

Reference:
    - docs/professional_optimization_plan.md (P5-A 任务)
"""

import copy
import json
import logging
import subprocess
import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


logger = logging.getLogger(__name__)


# ==============================================================================
# Enums and Data Classes
# ==============================================================================

class ControlType(Enum):
    """显示器控制项类型"""
    BRIGHTNESS = "brightness"          # 亮度 (VCP code 0x10)
    CONTRAST = "contrast"              # 对比度 (VCP code 0x12)
    COLOR_TEMP = "color_temp"          # 色温预设 (VCP code 0x0E)
    RED_GAIN = "red_gain"              # RGB Gain - 红色增益 (VCP code 0x16)
    GREEN_GAIN = "green_gain"          # RGB Gain - 绿色增益 (VCP code 0x18)
    BLUE_GAIN = "blue_gain"            # RGB Gain - 蓝色增益 (VCP code 0x1A)
    RED_OFFSET = "red_offset"          # RGB Offset - 红色偏移 (VCP code 0x52)
    GREEN_OFFSET = "green_offset"      # RGB Offset - 绿色偏移 (VCP code 0x54)
    BLUE_OFFSET = "blue_offset"        # RGB Offset - 蓝色偏移 (VCP code 0x56)
    BACKLIGHT = "backlight"            # 背光亮度 (VCP code 0x13)
    HUE = "hue"                        # 色调 (VCP code 0x1C)
    SATURATION = "saturation"          # 饱和度 (VCP code 0x1D)


class ControlCategory(Enum):
    """控制项类别"""
    LUMINANCE = "luminance"            # 亮度相关
    COLOR = "color"                    # 色彩相关
    RGB_CHANNEL = "rgb_channel"        # RGB 通道


@dataclass
class DisplayCapability:
    """
    单个控制项能力描述

    Attributes:
        control_type: 控制项类型
        name: 控制项名称 (显示用)
        vcp_code: DDC/CI VCP code (十六进制)
        min_value: 最小值
        max_value: 最大值
        default_value: 默认值 (可选)
        current_value: 当前值 (可选)
        unit: 单位 (百分比、K 等)
        category: 控制项类别
        writable: 是否可写
        readable: 是否可读
        description: 详细描述
    """
    control_type: ControlType
    name: str
    vcp_code: str = ""
    min_value: int = 0
    max_value: int = 100
    default_value: Optional[int] = None
    current_value: Optional[int] = None
    unit: str = "%"
    category: ControlCategory = ControlCategory.LUMINANCE
    writable: bool = True
    readable: bool = True
    description: str = ""

    def value_in_range(self, value: int) -> bool:
        """检查值是否在有效范围内"""
        return self.min_value <= value <= self.max_value

    def clamp_value(self, value: int) -> int:
        """将值约束到有效范围"""
        return max(self.min_value, min(self.max_value, value))

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "control_type": self.control_type.value,
            "name": self.name,
            "vcp_code": self.vcp_code,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "default_value": self.default_value,
            "current_value": self.current_value,
            "unit": self.unit,
            "category": self.category.value,
            "writable": self.writable,
            "readable": self.readable,
            "description": self.description,
        }


@dataclass
class DisplayCapabilities:
    """
    显示器完整能力集

    Attributes:
        display_id: 显示器 ID
        display_name: 显示器名称
        manufacturer: 制造商
        model: 型号
        serial: 序列号
        capabilities: 控制项能力列表
        supports_ddcci: 是否支持 DDC/CI
        supports_manual: 是否支持手动调整指导
    """
    display_id: int = 0
    display_name: str = ""
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    capabilities: List[DisplayCapability] = field(default_factory=list)
    supports_ddcci: bool = False
    supports_manual: bool = True

    def get_capability(self, control_type: ControlType) -> Optional[DisplayCapability]:
        """获取特定控制项能力"""
        for cap in self.capabilities:
            if cap.control_type == control_type:
                return cap
        return None

    def get_writable_controls(self) -> List[DisplayCapability]:
        """获取所有可写控制项"""
        return [cap for cap in self.capabilities if cap.writable]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "display_id": self.display_id,
            "display_name": self.display_name,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "serial": self.serial,
            "capabilities": [cap.to_dict() for cap in self.capabilities],
            "supports_ddcci": self.supports_ddcci,
            "supports_manual": self.supports_manual,
        }


@dataclass
class ControlSnapshot:
    """
    控制值快照 - 用于 rollback

    Attributes:
        timestamp: 快照时间
        display_id: 显示器 ID
        values: 控制值字典 {ControlType: value}
        source: 快照来源 (initial, before_adjustment, etc.)
        metadata: 元数据
    """
    timestamp: datetime = field(default_factory=datetime.now)
    display_id: int = 0
    values: Dict[ControlType, int] = field(default_factory=dict)
    source: str = "initial"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "display_id": self.display_id,
            "values": {k.value: v for k, v in self.values.items()},
            "source": self.source,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """转换为 JSON"""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def save_to_file(self, path: Union[str, Path]) -> bool:
        """保存到文件"""
        try:
            Path(path).write_text(self.to_json(), encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}")
            return False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ControlSnapshot":
        """从字典创建"""
        values = {}
        for k, v in data.get("values", {}).items():
            try:
                control_type = ControlType(k)
                values[control_type] = v
            except ValueError:
                pass

        return cls(
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat())),
            display_id=data.get("display_id", 0),
            values=values,
            source=data.get("source", "initial"),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> Optional["ControlSnapshot"]:
        """从文件加载"""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load snapshot: {e}")
            return None


@dataclass
class AdjustmentResult:
    """
    调整结果

    Attributes:
        control_type: 控制项类型
        requested_value: 请求值
        applied_value: 实际应用值
        success: 是否成功
        message: 结果消息
        timestamp: 时间戳
    """
    control_type: ControlType
    requested_value: int
    applied_value: Optional[int] = None
    success: bool = True
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "control_type": self.control_type.value,
            "requested_value": self.requested_value,
            "applied_value": self.applied_value,
            "success": self.success,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class AdjustmentBatch:
    """
    批量调整结果

    Attributes:
        results: 调整结果列表
        snapshot_before: 调整前快照
        snapshot_after: 调整后快照 (可选)
        dry_run: 是否为 dry-run
        all_success: 是否全部成功
        timestamp: 时间戳
    """
    results: List[AdjustmentResult] = field(default_factory=list)
    snapshot_before: Optional[ControlSnapshot] = None
    snapshot_after: Optional[ControlSnapshot] = None
    dry_run: bool = False
    all_success: bool = True
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "results": [r.to_dict() for r in self.results],
            "snapshot_before": self.snapshot_before.to_dict() if self.snapshot_before else None,
            "snapshot_after": self.snapshot_after.to_dict() if self.snapshot_after else None,
            "dry_run": self.dry_run,
            "all_success": self.all_success,
            "timestamp": self.timestamp.isoformat(),
        }


class DisplayControlError(Exception):
    """
    显示器控制异常

    Attributes:
        error_code: 错误代码
        control_type: 相关控制项 (可选)
        recoverable: 是否可恢复
        suggestion: 建议
    """
    def __init__(
        self,
        message: str,
        error_code: str = "UNKNOWN",
        control_type: Optional[ControlType] = None,
        recoverable: bool = False,
        suggestion: str = ""
    ):
        super().__init__(message)
        self.error_code = error_code
        self.control_type = control_type
        self.recoverable = recoverable
        self.suggestion = suggestion


# ==============================================================================
# DisplayControlAdapter Interface
# ==============================================================================

class DisplayControlAdapter(ABC):
    """
    显示器控制抽象接口

    所有显示器控制实现必须实现此接口，支持：
        - get_capabilities(): 获取显示器能力集
        - read_control(name): 读取单个控制项
        - write_control(name, value): 写入单个控制项
        - commit(): 提交所有变更
        - rollback(): 回滚到之前状态

    实现要求：
        - 每次 write_control 前自动保存 rollback snapshot
        - 支持 dry_run 模式（只计算不执行）
        - 提供 rollback 机制
        - 所有操作应超时可控

    Reference: docs/professional_optimization_plan.md (P5-A)
    """

    @abstractmethod
    def connect(self) -> bool:
        """
        连接显示器控制通道

        Returns:
            True 如果连接成功

        Raises:
            DisplayControlError: 连接失败
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """
        断开显示器控制连接
        """
        pass

    @abstractmethod
    def get_capabilities(self) -> DisplayCapabilities:
        """
        获取显示器能力集

        Returns:
            DisplayCapabilities 包含所有可控制项信息

        Raises:
            DisplayControlError: 获取失败
        """
        pass

    @abstractmethod
    def read_control(self, control_type: ControlType) -> int:
        """
        读取单个控制项当前值

        Args:
            control_type: 控制项类型

        Returns:
            当前值

        Raises:
            DisplayControlError: 读取失败或不支持
        """
        pass

    @abstractmethod
    def write_control(
        self,
        control_type: ControlType,
        value: int,
        dry_run: bool = False
    ) -> AdjustmentResult:
        """
        写入单个控制项

        Args:
            control_type: 控制项类型
            value: 目标值
            dry_run: 是否为 dry-run（只计算不执行）

        Returns:
            AdjustmentResult 包含调整结果

        Raises:
            DisplayControlError: 写入失败或值超出范围

        Note:
            每次写入前自动保存 rollback snapshot
        """
        pass

    @abstractmethod
    def write_batch(
        self,
        adjustments: Dict[ControlType, int],
        dry_run: bool = False
    ) -> AdjustmentBatch:
        """
        批量写入控制项

        Args:
            adjustments: 控制项值字典
            dry_run: 是否为 dry-run

        Returns:
            AdjustmentBatch 包含所有调整结果

        Note:
            批量写入前统一保存 snapshot，可一次性 rollback
        """
        pass

    @abstractmethod
    def commit(self) -> bool:
        """
        提交所有变更

        确认所有变更已生效，清除 rollback snapshot。

        Returns:
            True 如果提交成功
        """
        pass

    @abstractmethod
    def rollback(self) -> bool:
        """
        回滚到之前状态

        使用保存的 rollback snapshot 恢复显示器设置。

        Returns:
            True 如果回滚成功

        Raises:
            DisplayControlError: 回滚失败或无可用 snapshot
        """
        pass

    @abstractmethod
    def save_snapshot(self, source: str = "manual") -> ControlSnapshot:
        """
        手动保存控制值快照

        Args:
            source: 快照来源标识

        Returns:
            ControlSnapshot 当前控制值快照
        """
        pass

    @abstractmethod
    def load_snapshot(self, snapshot: ControlSnapshot) -> bool:
        """
        加载控制值快照

        Args:
            snapshot: 要加载的快照

        Returns:
            True 如果加载成功
        """
        pass

    @property
    @abstractmethod
    def display_id(self) -> int:
        """
        目标显示器 ID

        Returns:
            显示器 ID
        """
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """
        是否已连接

        Returns:
            True 如果已连接
        """
        pass

    @property
    @abstractmethod
    def has_snapshot(self) -> bool:
        """
        是否有可用的 rollback snapshot

        Returns:
            True 如果有可用 snapshot
        """
        pass

    @abstractmethod
    def clear_snapshot(self) -> None:
        """
        清除保存的 rollback snapshot
        """
        pass

    def is_writable(self, control_type: ControlType) -> bool:
        """
        检查控制项是否可写

        Args:
            control_type: 控制项类型

        Returns:
            True 如果可写
        """
        caps = self.get_capabilities()
        cap = caps.get_capability(control_type)
        return cap is not None and cap.writable

    def get_value_range(
        self,
        control_type: ControlType
    ) -> Optional[Tuple[int, int]]:
        """
        获取控制项值范围

        Args:
            control_type: 控制项类型

        Returns:
            (min, max) 或 None 如果不支持
        """
        caps = self.get_capabilities()
        cap = caps.get_capability(control_type)
        if cap:
            return (cap.min_value, cap.max_value)
        return None


# ==============================================================================
# FakeDisplayControlAdapter - 测试用假适配器
# ==============================================================================

class FakeDisplayControlAdapter(DisplayControlAdapter):
    """
    假显示器控制适配器 - 用于测试

    不依赖真实硬件，可配置预设值和模拟错误。
    用于：
        - 单元测试
        - CI/CD 测试
        - 开发调试

    Example:
        >>> adapter = FakeDisplayControlAdapter()
        >>> adapter.connect()
        >>> caps = adapter.get_capabilities()
        >>> adapter.write_control(ControlType.BRIGHTNESS, 80)
        >>> adapter.rollback()  # 恢复到之前值
    """

    # VCP code mapping for DDC/CI simulation
    VCP_CODES = {
        ControlType.BRIGHTNESS: "0x10",
        ControlType.CONTRAST: "0x12",
        ControlType.COLOR_TEMP: "0x0E",
        ControlType.RED_GAIN: "0x16",
        ControlType.GREEN_GAIN: "0x18",
        ControlType.BLUE_GAIN: "0x1A",
        ControlType.RED_OFFSET: "0x52",
        ControlType.GREEN_OFFSET: "0x54",
        ControlType.BLUE_OFFSET: "0x56",
        ControlType.BACKLIGHT: "0x13",
        ControlType.HUE: "0x1C",
        ControlType.SATURATION: "0x1D",
    }

    # Default capabilities for a typical monitor
    DEFAULT_CAPABILITIES = [
        DisplayCapability(
            control_type=ControlType.BRIGHTNESS,
            name="Brightness",
            vcp_code="0x10",
            min_value=0,
            max_value=100,
            default_value=50,
            unit="%",
            category=ControlCategory.LUMINANCE,
            description="Adjust display brightness level",
        ),
        DisplayCapability(
            control_type=ControlType.CONTRAST,
            name="Contrast",
            vcp_code="0x12",
            min_value=0,
            max_value=100,
            default_value=50,
            unit="%",
            category=ControlCategory.LUMINANCE,
            description="Adjust display contrast level",
        ),
        DisplayCapability(
            control_type=ControlType.COLOR_TEMP,
            name="Color Temperature",
            vcp_code="0x0E",
            min_value=0,
            max_value=6,
            default_value=2,  # 6500K
            unit="preset",
            category=ControlCategory.COLOR,
            description="Color temperature preset (0=4000K, 1=5000K, 2=6500K, 3=7500K, 4=8200K, 5=9300K, 6=10000K)",
        ),
        DisplayCapability(
            control_type=ControlType.RED_GAIN,
            name="Red Gain",
            vcp_code="0x16",
            min_value=0,
            max_value=100,
            default_value=50,
            unit="%",
            category=ControlCategory.RGB_CHANNEL,
            description="Red channel gain/brightness",
        ),
        DisplayCapability(
            control_type=ControlType.GREEN_GAIN,
            name="Green Gain",
            vcp_code="0x18",
            min_value=0,
            max_value=100,
            default_value=50,
            unit="%",
            category=ControlCategory.RGB_CHANNEL,
            description="Green channel gain/brightness",
        ),
        DisplayCapability(
            control_type=ControlType.BLUE_GAIN,
            name="Blue Gain",
            vcp_code="0x1A",
            min_value=0,
            max_value=100,
            default_value=50,
            unit="%",
            category=ControlCategory.RGB_CHANNEL,
            description="Blue channel gain/brightness",
        ),
        DisplayCapability(
            control_type=ControlType.RED_OFFSET,
            name="Red Offset",
            vcp_code="0x52",
            min_value=0,
            max_value=100,
            default_value=50,
            unit="%",
            category=ControlCategory.RGB_CHANNEL,
            description="Red channel offset/black level",
            writable=True,
        ),
        DisplayCapability(
            control_type=ControlType.GREEN_OFFSET,
            name="Green Offset",
            vcp_code="0x54",
            min_value=0,
            max_value=100,
            default_value=50,
            unit="%",
            category=ControlCategory.RGB_CHANNEL,
            description="Green channel offset/black level",
            writable=True,
        ),
        DisplayCapability(
            control_type=ControlType.BLUE_OFFSET,
            name="Blue Offset",
            vcp_code="0x56",
            min_value=0,
            max_value=100,
            default_value=50,
            unit="%",
            category=ControlCategory.RGB_CHANNEL,
            description="Blue channel offset/black level",
            writable=True,
        ),
    ]

    def __init__(
        self,
        display_id: int = 0,
        display_name: str = "Fake Display",
        manufacturer: str = "Test",
        model: str = "Virtual Monitor",
        initial_values: Optional[Dict[ControlType, int]] = None,
        capabilities: Optional[List[DisplayCapability]] = None,
    ):
        """
        初始化假适配器

        Args:
            display_id: 显示器 ID
            display_name: 显示器名称
            manufacturer: 制造商
            model: 型号
            initial_values: 初始控制值
            capabilities: 自定义能力列表
        """
        self._display_id = display_id
        self._display_name = display_name
        self._manufacturer = manufacturer
        self._model = model
        self._connected = False

        # 使用自定义能力或默认能力
        self._capabilities = capabilities or self.DEFAULT_CAPABILITIES.copy()

        # 初始化控制值
        self._current_values: Dict[ControlType, int] = {}
        if initial_values:
            self._current_values = copy.deepcopy(initial_values)
        else:
            # 使用默认值
            for cap in self._capabilities:
                self._current_values[cap.control_type] = cap.default_value or cap.min_value

        # Rollback snapshot
        self._rollback_snapshot: Optional[ControlSnapshot] = None

        # 操作历史
        self._operation_history: List[AdjustmentResult] = []

        # 错误模拟
        self._simulate_error: bool = False
        self._error_code: str = ""
        self._error_message: str = ""
        self._error_controls: set = set()

        # Dry-run 模式全局开关
        self._global_dry_run: bool = False

        logger.info(f"FakeDisplayControlAdapter initialized for display {display_id}")

    def simulate_error(
        self,
        error_code: str,
        message: str,
        control_type: Optional[ControlType] = None
    ) -> None:
        """
        配置错误模拟

        Args:
            error_code: 错误代码
            message: 错误消息
            control_type: 仅针对特定控制项 (可选)
        """
        self._simulate_error = True
        self._error_code = error_code
        self._error_message = message
        if control_type:
            self._error_controls.add(control_type)

    def clear_error(self) -> None:
        """清除错误模拟"""
        self._simulate_error = False
        self._error_code = ""
        self._error_message = ""
        self._error_controls.clear()

    def set_global_dry_run(self, enabled: bool) -> None:
        """设置全局 dry-run 模式"""
        self._global_dry_run = enabled

    def set_initial_values(self, values: Dict[ControlType, int]) -> None:
        """设置初始控制值"""
        self._current_values = copy.deepcopy(values)
        self._rollback_snapshot = None

    def _check_error(self, control_type: Optional[ControlType] = None) -> None:
        """检查是否应触发错误"""
        if self._simulate_error:
            if control_type and self._error_controls and control_type not in self._error_controls:
                return
            raise DisplayControlError(
                message=self._error_message,
                error_code=self._error_code,
                control_type=control_type,
                recoverable=self._error_code in ["TIMEOUT", "BUSY"],
            )

    def connect(self) -> bool:
        """模拟连接"""
        self._check_error()
        self._connected = True
        logger.info(f"FakeDisplayControlAdapter connected to display {self._display_id}")
        return True

    def disconnect(self) -> None:
        """模拟断开"""
        self._connected = False
        self._rollback_snapshot = None
        logger.info(f"FakeDisplayControlAdapter disconnected from display {self._display_id}")

    def get_capabilities(self) -> DisplayCapabilities:
        """获取能力集"""
        self._check_error()

        if not self._connected:
            raise DisplayControlError(
                message="Display control not connected",
                error_code="NOT_CONNECTED",
                recoverable=True,
                suggestion="Call connect() before get_capabilities()",
            )

        # 更新当前值到能力描述
        caps_copy = []
        for cap in self._capabilities:
            cap_copy = copy.deepcopy(cap)
            cap_copy.current_value = self._current_values.get(cap.control_type)
            caps_copy.append(cap_copy)

        return DisplayCapabilities(
            display_id=self._display_id,
            display_name=self._display_name,
            manufacturer=self._manufacturer,
            model=self._model,
            capabilities=caps_copy,
            supports_ddcci=True,
            supports_manual=True,
        )

    def read_control(self, control_type: ControlType) -> int:
        """读取控制值"""
        self._check_error(control_type)

        if not self._connected:
            raise DisplayControlError(
                message="Display control not connected",
                error_code="NOT_CONNECTED",
                recoverable=True,
            )

        cap = self.get_capabilities().get_capability(control_type)
        if cap is None or not cap.readable:
            raise DisplayControlError(
                message=f"Control {control_type.value} not supported or not readable",
                error_code="UNSUPPORTED_CONTROL",
                control_type=control_type,
                recoverable=False,
            )

        return self._current_values.get(control_type, cap.default_value or cap.min_value)

    def write_control(
        self,
        control_type: ControlType,
        value: int,
        dry_run: bool = False
    ) -> AdjustmentResult:
        """写入控制值"""
        self._check_error(control_type)

        if not self._connected:
            raise DisplayControlError(
                message="Display control not connected",
                error_code="NOT_CONNECTED",
                recoverable=True,
            )

        cap = self.get_capabilities().get_capability(control_type)
        if cap is None or not cap.writable:
            raise DisplayControlError(
                message=f"Control {control_type.value} not supported or not writable",
                error_code="UNSUPPORTED_CONTROL",
                control_type=control_type,
                recoverable=False,
            )

        # 检查值范围
        if not cap.value_in_range(value):
            raise DisplayControlError(
                message=f"Value {value} out of range [{cap.min_value}, {cap.max_value}]",
                error_code="VALUE_OUT_OF_RANGE",
                control_type=control_type,
                recoverable=True,
                suggestion=f"Use value between {cap.min_value} and {cap.max_value}",
            )

        # 应用全局 dry-run 或参数 dry-run
        effective_dry_run = dry_run or self._global_dry_run

        # 保存 rollback snapshot（如果是真实写入）
        if not effective_dry_run and not self._rollback_snapshot:
            self._rollback_snapshot = self.save_snapshot(source="before_write")

        # 约束值到有效范围
        clamped_value = cap.clamp_value(value)

        # 执行写入（非 dry-run）
        if not effective_dry_run:
            self._current_values[control_type] = clamped_value

        result = AdjustmentResult(
            control_type=control_type,
            requested_value=value,
            applied_value=clamped_value if not effective_dry_run else None,
            success=True,
            message=f"{'Dry-run: ' if effective_dry_run else ''}Value {'would be' if effective_dry_run else 'set'} to {clamped_value}",
        )

        self._operation_history.append(result)
        logger.info(f"write_control: {control_type.value} = {clamped_value} (dry_run={effective_dry_run})")

        return result

    def write_batch(
        self,
        adjustments: Dict[ControlType, int],
        dry_run: bool = False
    ) -> AdjustmentBatch:
        """批量写入控制值"""
        self._check_error()

        if not self._connected:
            raise DisplayControlError(
                message="Display control not connected",
                error_code="NOT_CONNECTED",
                recoverable=True,
            )

        effective_dry_run = dry_run or self._global_dry_run

        # 保存 rollback snapshot（如果是真实写入）
        snapshot_before = None
        if not effective_dry_run:
            snapshot_before = self.save_snapshot(source="before_batch_write")
            self._rollback_snapshot = snapshot_before

        results = []
        all_success = True

        for control_type, value in adjustments.items():
            try:
                result = self.write_control(control_type, value, dry_run=effective_dry_run)
                # 覆盖 message 以区分 batch 操作
                result.message = f"Batch {'dry-run: ' if effective_dry_run else ''}{control_type.value} {'would be' if effective_dry_run else 'set'} to {value}"
                results.append(result)
            except DisplayControlError as e:
                results.append(AdjustmentResult(
                    control_type=control_type,
                    requested_value=value,
                    success=False,
                    message=str(e),
                ))
                all_success = False

        # 获取调整后快照（非 dry-run）
        snapshot_after = None
        if not effective_dry_run and all_success:
            snapshot_after = self.save_snapshot(source="after_batch_write")

        return AdjustmentBatch(
            results=results,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after,
            dry_run=effective_dry_run,
            all_success=all_success,
        )

    def commit(self) -> bool:
        """提交变更"""
        self._check_error()

        if not self._connected:
            return False

        # 清除 rollback snapshot
        self._rollback_snapshot = None
        logger.info(f"Commit: rollback snapshot cleared for display {self._display_id}")
        return True

    def rollback(self) -> bool:
        """回滚到之前状态"""
        self._check_error()

        if not self._connected:
            raise DisplayControlError(
                message="Display control not connected",
                error_code="NOT_CONNECTED",
                recoverable=True,
            )

        if not self._rollback_snapshot:
            raise DisplayControlError(
                message="No rollback snapshot available",
                error_code="NO_SNAPSHOT",
                recoverable=False,
                suggestion="Save snapshot before making changes",
            )

        # 加载 rollback snapshot
        success = self.load_snapshot(self._rollback_snapshot)

        if success:
            logger.info(f"Rollback successful for display {self._display_id}")
            # 清除已使用的 snapshot
            self._rollback_snapshot = None

        return success

    def save_snapshot(self, source: str = "manual") -> ControlSnapshot:
        """保存控制值快照"""
        self._check_error()

        if not self._connected:
            raise DisplayControlError(
                message="Display control not connected",
                error_code="NOT_CONNECTED",
                recoverable=True,
            )

        return ControlSnapshot(
            timestamp=datetime.now(),
            display_id=self._display_id,
            values=copy.deepcopy(self._current_values),
            source=source,
            metadata={"manufacturer": self._manufacturer, "model": self._model},
        )

    def load_snapshot(self, snapshot: ControlSnapshot) -> bool:
        """加载控制值快照"""
        self._check_error()

        if not self._connected:
            return False

        # 恢复控制值
        for control_type, value in snapshot.values.items():
            if control_type in self._current_values:
                cap = self.get_capabilities().get_capability(control_type)
                if cap and cap.writable:
                    self._current_values[control_type] = cap.clamp_value(value)

        logger.info(f"Snapshot loaded: {len(snapshot.values)} controls restored")
        return True

    @property
    def display_id(self) -> int:
        """显示器 ID"""
        return self._display_id

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._connected

    @property
    def has_snapshot(self) -> bool:
        """是否有可用的 rollback snapshot"""
        return self._rollback_snapshot is not None

    def clear_snapshot(self) -> None:
        """清除 rollback snapshot"""
        self._rollback_snapshot = None

    def get_operation_history(self) -> List[AdjustmentResult]:
        """获取操作历史"""
        return self._operation_history.copy()

    def reset(self) -> None:
        """重置所有状态"""
        self._current_values.clear()
        for cap in self._capabilities:
            self._current_values[cap.control_type] = cap.default_value or cap.min_value
        self._rollback_snapshot = None
        self._operation_history.clear()
        self._simulate_error = False
        self._global_dry_run = False


# ==============================================================================
# DDCCIAdapter - DDC/CI 协议实现
# ==============================================================================

class DDCCIAdapter(DisplayControlAdapter):
    """
    DDC/CI 协议实现

    通过 DDC/CI (Display Data Channel Command Interface) 协议
    与显示器通信，实现自动亮度、对比度、RGB 增益调整。

    平台支持：
        - macOS: 使用 ddcctl 或显示器内置 API
        - Windows: 使用 Windows API 或 ddcctl
        - Linux: 使用 ddcutil

    注意：
        - macOS 需要 Accessibility 权限
        - Linux 需要 i2c-dev 模块和权限
        - Windows 通常直接支持

    Reference: docs/professional_optimization_plan.md (P5-A)
    """

    # DDC/CI VCP codes
    VCP_CODES = FakeDisplayControlAdapter.VCP_CODES.copy()

    # 平台工具映射
    PLATFORM_TOOLS = {
        "Darwin": ["ddcctl", "m1ddc"],   # macOS
        "Windows": ["ddcctl.exe"],       # Windows
        "Linux": ["ddcutil"],            # Linux
    }

    def __init__(
        self,
        display_id: int = 1,
        tool_path: Optional[str] = None,
        timeout: float = 5.0,
    ):
        """
        初始化 DDC/CI 适配器

        Args:
            display_id: 显示器 ID (1-based for most tools)
            tool_path: DDC 工具路径 (可选，自动检测)
            timeout: 命令超时时间 (秒)
        """
        self._display_id = display_id
        self._timeout = timeout
        self._connected = False
        self._rollback_snapshot: Optional[ControlSnapshot] = None

        # 检测平台和工具
        self._platform = platform.system()
        self._tool_path = tool_path or self._detect_tool()
        self._tool_name = self._get_tool_name()

        # 缓存能力集
        self._capabilities_cache: Optional[DisplayCapabilities] = None

        logger.info(f"DDCCIAdapter initialized: platform={self._platform}, tool={self._tool_name}")

    def _detect_tool(self) -> Optional[str]:
        """检测平台 DDC 工具"""
        tools = self.PLATFORM_TOOLS.get(self._platform, [])

        for tool in tools:
            # 检查 PATH
            result = subprocess.run(
                ["which", tool] if self._platform != "Windows" else ["where", tool],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                return result.stdout.strip().split("\n")[0]

        return None

    def _get_tool_name(self) -> str:
        """获取工具名称"""
        if self._tool_path:
            return Path(self._tool_path).name
        return "unknown"

    def _run_command(
        self,
        args: List[str],
        timeout: Optional[float] = None
    ) -> Tuple[int, str, str]:
        """
        执行 DDC 工具命令

        Args:
            args: 命令参数
            timeout: 超时时间

        Returns:
            (returncode, stdout, stderr)
        """
        if not self._tool_path:
            raise DisplayControlError(
                message="No DDC/CI tool available",
                error_code="NO_TOOL",
                recoverable=False,
                suggestion=f"Install ddcutil (Linux) or ddcctl (macOS/Windows)",
            )

        timeout = timeout or self._timeout

        try:
            result = subprocess.run(
                [self._tool_path] + args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return (result.returncode, result.stdout, result.stderr)
        except subprocess.TimeoutExpired:
            raise DisplayControlError(
                message=f"DDC/CI command timeout after {timeout}s",
                error_code="TIMEOUT",
                recoverable=True,
                suggestion="Check display connection or increase timeout",
            )
        except Exception as e:
            raise DisplayControlError(
                message=f"DDC/CI command failed: {e}",
                error_code="COMMAND_FAILED",
                recoverable=False,
            )

    def _parse_vcp_value(self, output: str) -> Optional[int]:
        """
        解析 VCP 值输出

        不同工具输出格式不同：
            - ddcutil: "VCP code 0x10 (Brightness): current value = 50"
            - ddcctl: "Display 1: brightness = 50"
        """
        # 尝试多种格式解析
        import re

        # ddcutil 格式
        match = re.search(r"current value\s*=\s*(\d+)", output)
        if match:
            return int(match.group(1))

        # ddcctl 格式
        match = re.search(r"=\s*(\d+)", output)
        if match:
            return int(match.group(1))

        # 直接数字
        match = re.search(r"(\d+)", output)
        if match:
            return int(match.group(1))

        return None

    def connect(self) -> bool:
        """连接显示器"""
        if not self._tool_path:
            raise DisplayControlError(
                message="No DDC/CI tool available",
                error_code="NO_TOOL",
                recoverable=False,
            )

        # 测试连接 - 尝试读取亮度
        try:
            vcp_code = self.VCP_CODES.get(ControlType.BRIGHTNESS)
            if self._tool_name == "ddcutil":
                args = ["getvcp", vcp_code, "--display", str(self._display_id)]
            elif self._tool_name == "ddcctl":
                args = ["-d", str(self._display_id), "-b", "?"]
            else:
                args = ["get", vcp_code]

            ret, out, err = self._run_command(args)

            if ret == 0:
                self._connected = True
                logger.info(f"DDC/CI connected to display {self._display_id}")
                return True
            else:
                raise DisplayControlError(
                    message=f"Failed to connect to display: {err}",
                    error_code="CONNECT_FAILED",
                    recoverable=True,
                    suggestion=f"Check display {self._display_id} supports DDC/CI",
                )

        except DisplayControlError:
            raise
        except Exception as e:
            raise DisplayControlError(
                message=f"Connection error: {e}",
                error_code="CONNECT_ERROR",
                recoverable=False,
            )

    def disconnect(self) -> None:
        """断开连接"""
        self._connected = False
        self._rollback_snapshot = None
        self._capabilities_cache = None

    def get_capabilities(self) -> DisplayCapabilities:
        """获取能力集"""
        if not self._connected:
            raise DisplayControlError(
                message="Not connected",
                error_code="NOT_CONNECTED",
                recoverable=True,
            )

        # 使用缓存
        if self._capabilities_cache:
            return self._capabilities_cache

        # 构建能力集（基于已知 VCP codes）
        caps = []
        for control_type, vcp_code in self.VCP_CODES.items():
            try:
                # 尝试读取当前值以确认支持
                value = self.read_control(control_type)
                cap = DisplayCapability(
                    control_type=control_type,
                    name=control_type.value.replace("_", " ").title(),
                    vcp_code=vcp_code,
                    min_value=0,
                    max_value=100,
                    current_value=value,
                    writable=True,
                    readable=True,
                )
                caps.append(cap)
            except DisplayControlError:
                # 不支持的控制项
                pass

        self._capabilities_cache = DisplayCapabilities(
            display_id=self._display_id,
            display_name=f"Display {self._display_id}",
            supports_ddcci=True,
            supports_manual=True,
            capabilities=caps,
        )

        return self._capabilities_cache

    def read_control(self, control_type: ControlType) -> int:
        """读取控制值"""
        if not self._connected:
            raise DisplayControlError(
                message="Not connected",
                error_code="NOT_CONNECTED",
                recoverable=True,
            )

        vcp_code = self.VCP_CODES.get(control_type)
        if not vcp_code:
            raise DisplayControlError(
                message=f"Unknown VCP code for {control_type.value}",
                error_code="UNKNOWN_VCP",
                control_type=control_type,
                recoverable=False,
            )

        # 构建命令
        if self._tool_name == "ddcutil":
            args = ["getvcp", vcp_code, "--display", str(self._display_id)]
        elif self._tool_name == "ddcctl":
            # ddcctl 使用特定参数
            control_map = {
                ControlType.BRIGHTNESS: ["-b", "?"],
                ControlType.CONTRAST: ["-c", "?"],
                ControlType.RED_GAIN: ["-rg", "?"],
                ControlType.GREEN_GAIN: ["-gg", "?"],
                ControlType.BLUE_GAIN: ["-bg", "?"],
            }
            args = ["-d", str(self._display_id)] + control_map.get(control_type, ["get", vcp_code])
        else:
            args = ["get", vcp_code, str(self._display_id)]

        ret, out, err = self._run_command(args)

        if ret != 0:
            raise DisplayControlError(
                message=f"Failed to read {control_type.value}: {err}",
                error_code="READ_FAILED",
                control_type=control_type,
                recoverable=True,
            )

        value = self._parse_vcp_value(out)
        if value is None:
            raise DisplayControlError(
                message=f"Failed to parse value: {out}",
                error_code="PARSE_FAILED",
                control_type=control_type,
                recoverable=False,
            )

        return value

    def write_control(
        self,
        control_type: ControlType,
        value: int,
        dry_run: bool = False
    ) -> AdjustmentResult:
        """写入控制值"""
        if not self._connected:
            raise DisplayControlError(
                message="Not connected",
                error_code="NOT_CONNECTED",
                recoverable=True,
            )

        vcp_code = self.VCP_CODES.get(control_type)
        if not vcp_code:
            raise DisplayControlError(
                message=f"Unknown VCP code",
                error_code="UNKNOWN_VCP",
                control_type=control_type,
                recoverable=False,
            )

        # Dry-run: 只返回模拟结果
        if dry_run:
            return AdjustmentResult(
                control_type=control_type,
                requested_value=value,
                applied_value=None,
                success=True,
                message=f"Dry-run: would set {control_type.value} to {value}",
            )

        # 保存 rollback snapshot
        if not self._rollback_snapshot:
            self._rollback_snapshot = self.save_snapshot(source="before_write")

        # 构建写入命令
        if self._tool_name == "ddcutil":
            args = ["setvcp", vcp_code, str(value), "--display", str(self._display_id)]
        elif self._tool_name == "ddcctl":
            control_map = {
                ControlType.BRIGHTNESS: ["-b", str(value)],
                ControlType.CONTRAST: ["-c", str(value)],
                ControlType.RED_GAIN: ["-rg", str(value)],
                ControlType.GREEN_GAIN: ["-gg", str(value)],
                ControlType.BLUE_GAIN: ["-bg", str(value)],
            }
            args = ["-d", str(self._display_id)] + control_map.get(control_type, ["setvcp", vcp_code, str(value)])
        else:
            args = ["set", vcp_code, str(value), str(self._display_id)]

        ret, out, err = self._run_command(args)

        if ret != 0:
            raise DisplayControlError(
                message=f"Failed to write {control_type.value}: {err}",
                error_code="WRITE_FAILED",
                control_type=control_type,
                recoverable=True,
            )

        return AdjustmentResult(
            control_type=control_type,
            requested_value=value,
            applied_value=value,
            success=True,
            message=f"Set {control_type.value} to {value}",
        )

    def write_batch(
        self,
        adjustments: Dict[ControlType, int],
        dry_run: bool = False
    ) -> AdjustmentBatch:
        """批量写入"""
        if dry_run:
            results = []
            for ct, val in adjustments.items():
                results.append(AdjustmentResult(
                    control_type=ct,
                    requested_value=val,
                    applied_value=None,
                    success=True,
                    message=f"Dry-run: would set {ct.value} to {val}",
                ))
            return AdjustmentBatch(
                results=results,
                dry_run=True,
                all_success=True,
            )

        # 真实写入
        snapshot_before = self.save_snapshot(source="before_batch_write")
        self._rollback_snapshot = snapshot_before

        results = []
        all_success = True

        for control_type, value in adjustments.items():
            try:
                result = self.write_control(control_type, value, dry_run=False)
                results.append(result)
            except DisplayControlError as e:
                results.append(AdjustmentResult(
                    control_type=control_type,
                    requested_value=value,
                    success=False,
                    message=str(e),
                ))
                all_success = False

        snapshot_after = None
        if all_success:
            snapshot_after = self.save_snapshot(source="after_batch_write")

        return AdjustmentBatch(
            results=results,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after,
            dry_run=False,
            all_success=all_success,
        )

    def commit(self) -> bool:
        """提交变更"""
        self._rollback_snapshot = None
        return True

    def rollback(self) -> bool:
        """回滚"""
        if not self._rollback_snapshot:
            raise DisplayControlError(
                message="No rollback snapshot",
                error_code="NO_SNAPSHOT",
                recoverable=False,
            )

        return self.load_snapshot(self._rollback_snapshot)

    def save_snapshot(self, source: str = "manual") -> ControlSnapshot:
        """保存快照"""
        values = {}
        for control_type in self.VCP_CODES.keys():
            try:
                value = self.read_control(control_type)
                values[control_type] = value
            except DisplayControlError:
                pass

        return ControlSnapshot(
            timestamp=datetime.now(),
            display_id=self._display_id,
            values=values,
            source=source,
        )

    def load_snapshot(self, snapshot: ControlSnapshot) -> bool:
        """加载快照"""
        for control_type, value in snapshot.values.items():
            try:
                self.write_control(control_type, value, dry_run=False)
            except DisplayControlError as e:
                logger.warning(f"Failed to restore {control_type.value}: {e}")

        self._rollback_snapshot = None
        return True

    @property
    def display_id(self) -> int:
        return self._display_id

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def has_snapshot(self) -> bool:
        return self._rollback_snapshot is not None

    def clear_snapshot(self) -> None:
        self._rollback_snapshot = None


# ==============================================================================
# ManualAdjustmentGuide - 手动调整指导生成器
# ==============================================================================

@dataclass
class ManualAdjustmentStep:
    """
    单个手动调整步骤

    Attributes:
        control_type: 控制项类型
        control_name: 控制项名称
        current_value: 当前值
        target_value: 目标值
        delta: 变化量
        direction: 方向 (increase/decrease)
        priority: 优先级 (1-5, 1 最高)
        instructions: 具体操作指导
        expected_effect: 预期效果说明
    """
    control_type: ControlType
    control_name: str
    current_value: int
    target_value: int
    delta: int
    direction: str = ""
    priority: int = 3
    instructions: str = ""
    expected_effect: str = ""

    def __post_init__(self):
        if not self.direction:
            self.direction = "increase" if self.delta > 0 else "decrease"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "control_type": self.control_type.value,
            "control_name": self.control_name,
            "current_value": self.current_value,
            "target_value": self.target_value,
            "delta": self.delta,
            "direction": self.direction,
            "priority": self.priority,
            "instructions": self.instructions,
            "expected_effect": self.expected_effect,
        }


@dataclass
class ManualAdjustmentGuide:
    """
    手动调整指导文档

    当无法自动调整时，生成详细的 OSD 手动调整指导。

    Attributes:
        display_name: 显示器名称
        timestamp: 生成时间
        steps: 调整步骤列表
        summary: 概述说明
        osd_access_instructions: OSD 菜单访问指导
        order: 推荐调整顺序
        estimated_time: 预估完成时间 (分钟)
        validation_checklist: 验证检查项
    """
    display_name: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    steps: List[ManualAdjustmentStep] = field(default_factory=list)
    summary: str = ""
    osd_access_instructions: str = ""
    order: List[str] = field(default_factory=list)
    estimated_time: int = 5
    validation_checklist: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "display_name": self.display_name,
            "timestamp": self.timestamp.isoformat(),
            "steps": [s.to_dict() for s in self.steps],
            "summary": self.summary,
            "osd_access_instructions": self.osd_access_instructions,
            "order": self.order,
            "estimated_time": self.estimated_time,
            "validation_checklist": self.validation_checklist,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def to_markdown(self) -> str:
        """生成 Markdown 格式指导"""
        lines = [
            f"# 手动调整指导 - {self.display_name}",
            "",
            f"**生成时间**: {self.timestamp.strftime('%Y-%m-%d %H:%M')}",
            f"**预估用时**: {self.estimated_time} 分钟",
            "",
            "## 概述",
            "",
            self.summary,
            "",
            "## OSD 菜单访问",
            "",
            self.osd_access_instructions,
            "",
            "## 调整步骤",
            "",
            "按以下顺序调整可获得最佳效果:",
            "",
        ]

        # 添加步骤
        for i, step in enumerate(self.steps, 1):
            lines.extend([
                f"### 步骤 {i}: {step.control_name}",
                "",
                f"| 属性 | 值 |",
                f"|---|---|",
                f"| 当前值 | {step.current_value} |",
                f"| 目标值 | {step.target_value} |",
                f"| 变化量 | {step.delta:+d} ({step.direction}) |",
                f"| 优先级 | {step.priority} |",
                "",
                f"**操作指导**: {step.instructions}",
                "",
                f"**预期效果**: {step.expected_effect}",
                "",
            ])

        # 添加验证检查
        lines.extend([
            "## 验证检查",
            "",
            "完成调整后，请检查以下项目:",
            "",
        ])
        for item in self.validation_checklist:
            lines.append(f"- {item}")

        return "\n".join(lines)

    def export_to_file(self, path: Union[str, Path], format: str = "json") -> bool:
        """导出到文件"""
        try:
            path = Path(path)
            if format == "json":
                path.write_text(self.to_json(), encoding="utf-8")
            elif format == "md":
                path.write_text(self.to_markdown(), encoding="utf-8")
            else:
                raise ValueError(f"Unknown format: {format}")
            return True
        except Exception as e:
            logger.error(f"Failed to export guide: {e}")
            return False


class ManualAdjustmentGuideGenerator:
    """
    手动调整指导生成器

    根据测量偏差生成 OSD 手动调整指导。
    """

    # 默认 OSD 访问指导
    DEFAULT_OSD_INSTRUCTIONS = """
1. 按显示器上的 MENU 按钮进入 OSD 菜单
2. 使用方向键导航到 "Color" 或 "Picture" 设置
3. 选择需要调整的选项
4. 使用方向键调整数值
5. 按 MENU 或 EXIT 保存并退出
"""

    # 控制项效果说明
    CONTROL_EFFECTS = {
        ControlType.BRIGHTNESS: "调整整体亮度，影响白场亮度",
        ControlType.CONTRAST: "调整对比度，影响白场亮度和黑场保持",
        ControlType.RED_GAIN: "调整红色增益，影响白平衡红色成分",
        ControlType.GREEN_GAIN: "调整绿色增益，影响白平衡绿色成分",
        ControlType.BLUE_GAIN: "调整蓝色增益，影响白平衡蓝色成分",
        ControlType.RED_OFFSET: "调整红色黑场偏移，影响低亮度红色平衡",
        ControlType.GREEN_OFFSET: "调整绿色黑场偏移，影响低亮度绿色平衡",
        ControlType.BLUE_OFFSET: "调整蓝色黑场偏移，影响低亮度蓝色平衡",
        ControlType.COLOR_TEMP: "选择色温预设，影响整体白平衡",
    }

    # 控制项操作指导
    CONTROL_INSTRUCTIONS = {
        ControlType.BRIGHTNESS: "在 OSD 菜单中找到 'Brightness' 选项，调整到目标值",
        ControlType.CONTRAST: "在 OSD 菜单中找到 'Contrast' 选项，调整到目标值",
        ControlType.RED_GAIN: "在 'Color Settings' 中找到 'RGB Gain' 或 'White Balance'，调整 Red 值",
        ControlType.GREEN_GAIN: "在 'Color Settings' 中找到 'RGB Gain' 或 'White Balance'，调整 Green 值",
        ControlType.BLUE_GAIN: "在 'Color Settings' 中找到 'RGB Gain' 或 'White Balance'，调整 Blue 值",
        ControlType.RED_OFFSET: "在 'Color Settings' 中找到 'RGB Offset' 或 'Black Level'，调整 Red 值",
        ControlType.GREEN_OFFSET: "在 'Color Settings' 中找到 'RGB Offset' 或 'Black Level'，调整 Green 值",
        ControlType.BLUE_OFFSET: "在 'Color Settings' 中找到 'RGB Offset' 或 'Black Level'，调整 Blue 值",
        ControlType.COLOR_TEMP: "在 'Color Settings' 中选择色温预设 (6500K/D65 推荐)",
    }

    # 控制项优先级 (1 最高)
    CONTROL_PRIORITY = {
        ControlType.BRIGHTNESS: 2,
        ControlType.CONTRAST: 3,
        ControlType.COLOR_TEMP: 1,
        ControlType.RED_GAIN: 4,
        ControlType.GREEN_GAIN: 4,
        ControlType.BLUE_GAIN: 4,
        ControlType.RED_OFFSET: 5,
        ControlType.GREEN_OFFSET: 5,
        ControlType.BLUE_OFFSET: 5,
    }

    def __init__(self, display_capabilities: Optional[DisplayCapabilities] = None):
        """
        初始化生成器

        Args:
            display_capabilities: 显示器能力集 (可选)
        """
        self._capabilities = display_capabilities

    def set_capabilities(self, capabilities: DisplayCapabilities) -> None:
        """设置显示器能力集"""
        self._capabilities = capabilities

    def generate(
        self,
        current_values: Dict[ControlType, int],
        target_values: Dict[ControlType, int],
        display_name: str = "",
        summary: str = "",
    ) -> ManualAdjustmentGuide:
        """
        生成手动调整指导

        Args:
            current_values: 当前控制值
            target_values: 目标控制值
            display_name: 显示器名称
            summary: 概述说明 (可选)

        Returns:
            ManualAdjustmentGuide 调整指导
        """
        steps = []

        for control_type, target_value in target_values.items():
            current_value = current_values.get(control_type, 50)
            delta = target_value - current_value

            if delta == 0:
                continue  # 无需调整

            # 获取控制项名称
            if self._capabilities:
                cap = self._capabilities.get_capability(control_type)
                control_name = cap.name if cap else control_type.value
            else:
                control_name = control_type.value.replace("_", " ").title()

            step = ManualAdjustmentStep(
                control_type=control_type,
                control_name=control_name,
                current_value=current_value,
                target_value=target_value,
                delta=delta,
                priority=self.CONTROL_PRIORITY.get(control_type, 3),
                instructions=self.CONTROL_INSTRUCTIONS.get(control_type, "在 OSD 中找到对应选项调整"),
                expected_effect=self.CONTROL_EFFECTS.get(control_type, ""),
            )
            steps.append(step)

        # 按优先级排序
        steps.sort(key=lambda s: s.priority)

        # 推荐调整顺序
        order = [s.control_name for s in steps]

        # 验证检查项
        validation_checklist = [
            "白场亮度达到目标值 (测量确认)",
            "白平衡正确 (CCT 接近目标，Duv < 0.005)",
            "灰阶跟踪正确 (Gamma 接近目标)",
            "色域覆盖达到要求",
            "黑场无明显偏色",
        ]

        # 估算时间 (每个步骤约 1 分钟)
        estimated_time = len(steps)

        # 默认概述
        if not summary:
            summary = f"根据测量结果，需要调整 {len(steps)} 个控制项以达到目标校准效果。"

        return ManualAdjustmentGuide(
            display_name=display_name,
            timestamp=datetime.now(),
            steps=steps,
            summary=summary,
            osd_access_instructions=self.DEFAULT_OSD_INSTRUCTIONS,
            order=order,
            estimated_time=estimated_time,
            validation_checklist=validation_checklist,
        )

    def generate_from_adjustment_batch(
        self,
        batch: AdjustmentBatch,
        display_name: str = "",
    ) -> ManualAdjustmentGuide:
        """
        从调整批次生成指导

        Args:
            batch: AdjustmentBatch 包含调整结果
            display_name: 显示器名称

        Returns:
            ManualAdjustmentGuide
        """
        current_values = {}
        target_values = {}

        for result in batch.results:
            current_values[result.control_type] = result.requested_value
            # 在 dry-run 模式下，使用 requested 作为目标
            target_values[result.control_type] = result.requested_value

        # 从 snapshot_before 获取当前值
        if batch.snapshot_before:
            current_values = batch.snapshot_before.values.copy()

        return self.generate(
            current_values=current_values,
            target_values=target_values,
            display_name=display_name,
            summary=f"Dry-run 模式调整指导 - 共 {len(batch.results)} 项需要调整",
        )


# ==============================================================================
# Factory Functions
# ==============================================================================

def create_fake_display_adapter(
    display_id: int = 0,
    initial_brightness: int = 50,
    initial_contrast: int = 50,
    initial_rgb_gain: Tuple[int, int, int] = (50, 50, 50),
) -> FakeDisplayControlAdapter:
    """
    创建预配置的假适配器

    Args:
        display_id: 显示器 ID
        initial_brightness: 初始亮度
        initial_contrast: 初始对比度
        initial_rgb_gain: 初始 RGB gain (R, G, B)

    Returns:
        FakeDisplayControlAdapter
    """
    initial_values = {
        ControlType.BRIGHTNESS: initial_brightness,
        ControlType.CONTRAST: initial_contrast,
        ControlType.RED_GAIN: initial_rgb_gain[0],
        ControlType.GREEN_GAIN: initial_rgb_gain[1],
        ControlType.BLUE_GAIN: initial_rgb_gain[2],
        ControlType.COLOR_TEMP: 2,  # 6500K
        ControlType.RED_OFFSET: 50,
        ControlType.GREEN_OFFSET: 50,
        ControlType.BLUE_OFFSET: 50,
    }

    return FakeDisplayControlAdapter(
        display_id=display_id,
        initial_values=initial_values,
    )


def create_display_adapter(
    display_id: int = 1,
    use_ddcci: bool = True,
    tool_path: Optional[str] = None,
) -> DisplayControlAdapter:
    """
    创建显示器控制适配器

    Args:
        display_id: 显示器 ID
        use_ddcci: 是否使用 DDC/CI
        tool_path: DDC 工具路径 (可选)

    Returns:
        DisplayControlAdapter (DDCCIAdapter 或 FakeDisplayControlAdapter)
    """
    if use_ddcci:
        adapter = DDCCIAdapter(display_id=display_id, tool_path=tool_path)
        try:
            adapter.connect()
            return adapter
        except DisplayControlError:
            logger.warning("DDC/CI not available, falling back to fake adapter")
            return create_fake_display_adapter(display_id=display_id)
    else:
        return create_fake_display_adapter(display_id=display_id)
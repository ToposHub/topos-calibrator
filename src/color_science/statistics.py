"""
测量统计分析模块 - Measurement Repeatability and Statistics

参考标准：
    - CIE 15:2004 - 色度学测量不确定度
    - ISO 11664-4 - 色差计算与测量重复性
    - ASTM E2194 - 测量仪器重复性评估

本模块实现：
    - XYZ/xyY/Lab 多次测量统计分析
    - 重复性评估（均值、标准差、最大偏差）
    - 阈值判断与警告
    - 测量记录与 Repeatability Summary 输出
    - 异常值检测与剔除 (MAD, IQR, Z-score)
    - 置信度评估

使用场景：
    1. 暗部多重采样（XYZ 线性平均）
    2. 关键色块重复测量验证
    3. 测量 session 输出 repeatability summary
    4. UI 超阈值提示重新测量
    5. 异常值剔除以提高测量可信度
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union
from enum import Enum


# ==============================================================================
# 数据类型定义
# ==============================================================================

class MeasurementStatus(Enum):
    """测量状态标记"""
    PASS = "pass"           # 通过阈值
    WARN = "warn"           # 接近阈值，建议关注
    FAIL = "fail"           # 超过阈值，建议重测
    UNKNOWN = "unknown"     # 数据不足，无法判断


class OutlierRejectionMethod(Enum):
    """
    异常值剔除方法

    用于检测并剔除测量中的异常读数，提高测量可信度。

    Attributes:
        NONE: 不剔除异常值
        MAD: Median Absolute Deviation (推荐用于小样本，鲁棒性好)
        IQR: Interquartile Range (基于四分位数)
        Z_SCORE: Z-score 方法 (需要足够样本量)
        GRUBBS: Grubbs' test (单异常值检测)
        CUSTOM: 用户自定义阈值
    """
    NONE = "none"
    MAD = "mad"
    IQR = "iqr"
    Z_SCORE = "z_score"
    GRUBBS = "grubbs"
    CUSTOM = "custom"


class LuminanceLevel(Enum):
    """
    亮度级别分类

    用于根据亮度调整测量策略和阈值。
    """
    DARK = "dark"       # Y < 1.0 cd/m²
    MID = "mid"         # 1.0 <= Y < 50.0 cd/m²
    BRIGHT = "bright"   # Y >= 50.0 cd/m²


class AveragingMethod(Enum):
    """平均方法"""
    XYZ_LINEAR = "xyz_linear"   # XYZ 线性平均（推荐用于暗部）
    XY_Y_LINEAR = "xyY_linear"  # xyY 线性平均（不推荐）
    LAB_LINEAR = "lab_linear"   # Lab 线性平均（不推荐）
    Y_ONLY = "y_only"           # 仅 Y 平均


@dataclass
class SingleMeasurement:
    """
    单次测量记录

    记录每次测量的原始数据、时间戳、探头状态等

    Attributes:
        xyz: XYZ 三刺激值 (X, Y, Z)，Y 单位为 cd/m²
        xyY: CIE xyY 值 (x, y, Y)
        timestamp: 测量时间戳
        instrument_status: 探头状态信息
        metadata: 其他元数据（温度、积分时间等）
    """
    xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    xyY: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    timestamp: datetime = field(default_factory=datetime.now)
    instrument_status: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def X(self) -> float:
        """X 值"""
        return self.xyz[0]

    @property
    def Y(self) -> float:
        """Y 值（亮度）"""
        return self.xyz[1]

    @property
    def Z(self) -> float:
        """Z 值"""
        return self.xyz[2]

    @property
    def x(self) -> float:
        """x 坐标"""
        return self.xyY[0]

    @property
    def y(self) -> float:
        """y 坐标"""
        return self.xyY[1]

    @property
    def luminance(self) -> float:
        """亮度 (cd/m²)"""
        return self.xyY[2]


@dataclass
class MeasurementStatistics:
    """
    测量统计数据

    Attributes:
        count: 测量次数
        mean_xyz: XYZ 均值
        mean_xyY: xyY 均值（从 XYZ 均值计算）
        std_xyz: XYZ 标准差
        std_xyY: xyY 标准差
        max_deviation_xyz: XYZ 最大偏差
        max_deviation_xyY: xyY 最大偏差
        range_xyz: XYZ 范围（最大-最小）
        range_xyY: xyY 范围
        averaging_method: 使用的平均方法
        measurements: 原始测量记录列表
        timestamp_start: 首次测量时间
        timestamp_end: 最后测量时间
        duration_ms: 测量总时长（毫秒）
        confidence: 置信度评估（0-1）
    """
    count: int = 0
    mean_xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    mean_xyY: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    std_xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    std_xyY: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    max_deviation_xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    max_deviation_xyY: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    range_xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    range_xyY: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    averaging_method: AveragingMethod = AveragingMethod.XYZ_LINEAR
    measurements: List[SingleMeasurement] = field(default_factory=list)
    timestamp_start: Optional[datetime] = None
    timestamp_end: Optional[datetime] = None
    duration_ms: float = 0.0
    confidence: float = 0.0

    @property
    def mean_Y(self) -> float:
        """平均亮度"""
        return self.mean_xyz[1]

    @property
    def std_Y(self) -> float:
        """Y 标准差"""
        return self.std_xyz[1]

    @property
    def relative_std_Y(self) -> float:
        """Y 相对标准差（百分比）"""
        if self.mean_Y == 0:
            return 0.0
        return (self.std_Y / self.mean_Y) * 100.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "count": self.count,
            "mean_xyz": list(self.mean_xyz),
            "mean_xyY": list(self.mean_xyY),
            "std_xyz": list(self.std_xyz),
            "std_xyY": list(self.std_xyY),
            "max_deviation_xyz": list(self.max_deviation_xyz),
            "max_deviation_xyY": list(self.max_deviation_xyY),
            "range_xyz": list(self.range_xyz),
            "range_xyY": list(self.range_xyY),
            "averaging_method": self.averaging_method.value,
            "timestamp_start": self.timestamp_start.isoformat() if self.timestamp_start else None,
            "timestamp_end": self.timestamp_end.isoformat() if self.timestamp_end else None,
            "duration_ms": self.duration_ms,
            "confidence": self.confidence,
            "relative_std_Y_percent": self.relative_std_Y,
        }


@dataclass
class RepeatabilityThreshold:
    """
    重复性阈值配置

    用于判断测量是否通过或需要重测

    Attributes:
        std_Y_threshold: Y 标准差阈值 (cd/m²)
        relative_std_Y_threshold: Y 相对标准差阈值 (百分比)
        max_deviation_Y_threshold: Y 最大偏差阈值 (cd/m²)
        delta_xy_threshold: xy 坐标变化阈值
        delta_uv_threshold: u'v' 坐标变化阈值
        min_measurements: 最少测量次数
        warn_threshold_factor: WARN 状态因子（阈值乘以此因子）
    """
    std_Y_threshold: float = 0.1          # cd/m²
    relative_std_Y_threshold: float = 2.0  # 百分比
    max_deviation_Y_threshold: float = 0.2  # cd/m²
    delta_xy_threshold: float = 0.005     # xy 坐标
    delta_uv_threshold: float = 0.003     # u'v' 坐标
    min_measurements: int = 3
    warn_threshold_factor: float = 0.8    # 80% 阈值为 WARN


@dataclass
class RepeatabilityResult:
    """
    重复性评估结果

    Attributes:
        statistics: 测量统计数据
        threshold: 使用的阈值配置
        status: 测量状态 (PASS/WARN/FAIL)
        violations: 超阈值项列表
        warnings: 接近阈值项列表
        recommendation: 建议操作
        needs_remeasurement: 是否需要重新测量
    """
    statistics: MeasurementStatistics = field(default_factory=MeasurementStatistics)
    threshold: RepeatabilityThreshold = field(default_factory=RepeatabilityThreshold)
    status: MeasurementStatus = MeasurementStatus.UNKNOWN
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendation: str = ""
    needs_remeasurement: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "statistics": self.statistics.to_dict(),
            "threshold": {
                "std_Y_threshold": self.threshold.std_Y_threshold,
                "relative_std_Y_threshold": self.threshold.relative_std_Y_threshold,
                "max_deviation_Y_threshold": self.threshold.max_deviation_Y_threshold,
                "delta_xy_threshold": self.threshold.delta_xy_threshold,
                "min_measurements": self.threshold.min_measurements,
            },
            "status": self.status.value,
            "violations": self.violations,
            "warnings": self.warnings,
            "recommendation": self.recommendation,
            "needs_remeasurement": self.needs_remeasurement,
        }


@dataclass
class PatchRepeatabilityRecord:
    """
    单个色块的重复性记录

    Attributes:
        patch_index: 色块索引
        patch_name: 色块名称
        rgb: 请求的 RGB 值
        measurements: 测量记录列表
        statistics: 统计数据
        result: 重复性评估结果
        was_remeasured: 是否执行了重测
        remeasure_count: 重测次数
    """
    patch_index: int = 0
    patch_name: str = ""
    rgb: Tuple[int, int, int] = (0, 0, 0)
    measurements: List[SingleMeasurement] = field(default_factory=list)
    statistics: MeasurementStatistics = field(default_factory=MeasurementStatistics)
    result: RepeatabilityResult = field(default_factory=RepeatabilityResult)
    was_remeasured: bool = False
    remeasure_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "patch_index": self.patch_index,
            "patch_name": self.patch_name,
            "rgb": list(self.rgb),
            "measurements": [
                {
                    "xyz": list(m.xyz),
                    "xyY": list(m.xyY),
                    "timestamp": m.timestamp.isoformat(),
                    "instrument_status": m.instrument_status,
                    "metadata": m.metadata,
                }
                for m in self.measurements
            ],
            "statistics": self.statistics.to_dict(),
            "result": self.result.to_dict(),
            "was_remeasured": self.was_remeasured,
            "remeasure_count": self.remeasure_count,
        }


@dataclass
class SessionRepeatabilitySummary:
    """
    整个测量 session 的重复性总结

    Attributes:
        session_id: Session ID
        total_patches: 总色块数
        passed_patches: 通过色块数
        warned_patches: 警告色块数
        failed_patches: 失败色块数
        patches: 各色块的重复性记录
        overall_status: 整体状态
        overall_recommendation: 整体建议
        timestamp: 生成时间
    """
    session_id: str = ""
    total_patches: int = 0
    passed_patches: int = 0
    warned_patches: int = 0
    failed_patches: int = 0
    patches: List[PatchRepeatabilityRecord] = field(default_factory=list)
    overall_status: MeasurementStatus = MeasurementStatus.UNKNOWN
    overall_recommendation: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def pass_rate(self) -> float:
        """通过率"""
        if self.total_patches == 0:
            return 0.0
        return (self.passed_patches / self.total_patches) * 100.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "session_id": self.session_id,
            "total_patches": self.total_patches,
            "passed_patches": self.passed_patches,
            "warned_patches": self.warned_patches,
            "failed_patches": self.failed_patches,
            "pass_rate_percent": self.pass_rate,
            "patches": [p.to_dict() for p in self.patches],
            "overall_status": self.overall_status.value,
            "overall_recommendation": self.overall_recommendation,
            "timestamp": self.timestamp.isoformat(),
        }


# ==============================================================================
# 统计计算函数
# ==============================================================================

def calculate_mean(
    values: List[Union[float, Tuple[float, ...]]]
) -> Union[float, Tuple[float, ...]]:
    """
    计算均值

    Args:
        values: 数值列表或元组列表

    Returns:
        均值（浮点数或元组）
    """
    if not values:
        return 0.0 if isinstance(values, list) and len(values) == 0 else (0.0,)

    # 判断是单个数值还是元组
    first = values[0]
    if isinstance(first, (int, float)):
        return sum(values) / len(values)
    elif isinstance(first, tuple):
        n = len(first)
        result = []
        for i in range(n):
            component_sum = sum(v[i] for v in values)
            result.append(component_sum / len(values))
        return tuple(result)
    else:
        raise ValueError(f"不支持的值类型: {type(first)}")


def calculate_std(
    values: List[Union[float, Tuple[float, ...]]],
    mean: Optional[Union[float, Tuple[float, ...]]] = None
) -> Union[float, Tuple[float, ...]]:
    """
    计算标准差

    Args:
        values: 数值列表或元组列表
        mean: 均值（如果未提供则自动计算）

    Returns:
        标准差（浮点数或元组）
    """
    if len(values) < 2:
        return 0.0 if isinstance(values[0], (int, float)) else (0.0,) * len(values[0]) if values else (0.0,)

    if mean is None:
        mean = calculate_mean(values)

    first = values[0]
    if isinstance(first, (int, float)):
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        return math.sqrt(variance)
    elif isinstance(first, tuple):
        n = len(first)
        result = []
        for i in range(n):
            variance = sum((v[i] - mean[i]) ** 2 for v in values) / (len(values) - 1)
            result.append(math.sqrt(variance))
        return tuple(result)
    else:
        raise ValueError(f"不支持的值类型: {type(first)}")


def calculate_max_deviation(
    values: List[Union[float, Tuple[float, ...]]],
    mean: Optional[Union[float, Tuple[float, ...]]] = None
) -> Union[float, Tuple[float, ...]]:
    """
    计算最大偏差（最大绝对偏离）

    Args:
        values: 数值列表或元组列表
        mean: 均值（如果未提供则自动计算）

    Returns:
        最大偏差（浮点数或元组）
    """
    if not values:
        return 0.0

    if mean is None:
        mean = calculate_mean(values)

    first = values[0]
    if isinstance(first, (int, float)):
        return max(abs(v - mean) for v in values)
    elif isinstance(first, tuple):
        n = len(first)
        result = []
        for i in range(n):
            max_dev = max(abs(v[i] - mean[i]) for v in values)
            result.append(max_dev)
        return tuple(result)
    else:
        raise ValueError(f"不支持的值类型: {type(first)}")


def calculate_range(
    values: List[Union[float, Tuple[float, ...]]]
) -> Union[float, Tuple[float, ...]]:
    """
    计算范围（最大值 - 最小值）

    Args:
        values: 数值列表或元组列表

    Returns:
        范围（浮点数或元组）
    """
    if not values:
        return 0.0

    first = values[0]
    if isinstance(first, (int, float)):
        return max(values) - min(values)
    elif isinstance(first, tuple):
        n = len(first)
        result = []
        for i in range(n):
            component_values = [v[i] for v in values]
            result.append(max(component_values) - min(component_values))
        return tuple(result)
    else:
        raise ValueError(f"不支持的值类型: {type(first)}")


def xyz_to_xyY(X: float, Y: float, Z: float) -> Tuple[float, float, float]:
    """
    XYZ 转 xyY

    Args:
        X, Y, Z: XYZ 值

    Returns:
        Tuple[float, float, float]: (x, y, Y)
    """
    total = X + Y + Z
    if total > 0:
        x = X / total
        y = Y / total
    else:
        x = 0.0
        y = 0.0
    return (x, y, Y)


def xyY_to_xyz(x: float, y: float, Y: float) -> Tuple[float, float, float]:
    """
    xyY 转 XYZ

    Args:
        x, y, Y: xyY 值

    Returns:
        Tuple[float, float, float]: (X, Y, Z)
    """
    if y > 0:
        X = (x / y) * Y
        Z = ((1 - x - y) / y) * Y
    else:
        X = 0.0
        Z = 0.0
    return (X, Y, Z)


def xy_to_uv_1976(x: float, y: float) -> Tuple[float, float]:
    """
    xy 转 u'v' (CIE 1976)

    Args:
        x, y: xy 坐标

    Returns:
        Tuple[float, float]: (u', v')
    """
    denominator = -2.0 * x + 12.0 * y + 3.0
    if denominator == 0:
        return (0.0, 0.0)
    u = 4.0 * x / denominator
    v = 9.0 * y / denominator
    return (u, v)


# ==============================================================================
# 核心统计分析函数
# ==============================================================================

def calculate_measurement_statistics(
    measurements: List[SingleMeasurement],
    method: AveragingMethod = AveragingMethod.XYZ_LINEAR
) -> MeasurementStatistics:
    """
    计算测量统计数据

    支持多种平均方法：
    - XYZ_LINEAR: XYZ 线性平均（推荐用于暗部）
    - XY_Y_LINEAR: xyY 线性平均（不推荐，仅用于兼容）
    - LAB_LINEAR: Lab 线性平均（不推荐）
    - Y_ONLY: 仅 Y 平均

    Args:
        measurements: 测量记录列表
        method: 平均方法

    Returns:
        MeasurementStatistics: 统计数据
    """
    if not measurements:
        return MeasurementStatistics(count=0)

    count = len(measurements)

    # 提取 XYZ 值
    xyz_values = [m.xyz for m in measurements]

    # 提取 xyY 值
    xyY_values = [m.xyY for m in measurements]

    # 计算时间信息
    timestamps = [m.timestamp for m in measurements]
    timestamp_start = min(timestamps)
    timestamp_end = max(timestamps)
    duration_ms = (timestamp_end - timestamp_start).total_seconds() * 1000.0

    # 根据平均方法计算均值
    if method == AveragingMethod.XYZ_LINEAR:
        # XYZ 线性平均（推荐）
        mean_xyz = calculate_mean(xyz_values)
        mean_xyY = xyz_to_xyY(*mean_xyz)

    elif method == AveragingMethod.XY_Y_LINEAR:
        # xyY 线性平均（不推荐，但保留兼容）
        # 注意：这种方法可能导致 x/y 计算偏差
        mean_xyY_direct = calculate_mean(xyY_values)
        mean_xyz = xyY_to_xyz(*mean_xyY_direct)
        mean_xyY = mean_xyY_direct  # 保持原样

    elif method == AveragingMethod.Y_ONLY:
        # 仅 Y 平均
        Y_values = [m.Y for m in measurements]
        mean_Y = calculate_mean(Y_values)
        # 使用首个测量的 x, y
        first_xy = measurements[0].xyY[:2]
        mean_xyY = (first_xy[0], first_xy[1], mean_Y)
        mean_xyz = xyY_to_xyz(*mean_xyY)

    elif method == AveragingMethod.LAB_LINEAR:
        # Lab 线性平均需要 Lab 转换（需要白点）
        # 此处简化为 XYZ 平均（实际 Lab 平均需要额外参数）
        mean_xyz = calculate_mean(xyz_values)
        mean_xyY = xyz_to_xyY(*mean_xyz)

    else:
        raise ValueError(f"未知的平均方法: {method}")

    # 计算标准差
    std_xyz = calculate_std(xyz_values, mean_xyz)
    std_xyY = calculate_std(xyY_values, mean_xyY)

    # 计算最大偏差
    max_deviation_xyz = calculate_max_deviation(xyz_values, mean_xyz)
    max_deviation_xyY = calculate_max_deviation(xyY_values, mean_xyY)

    # 计算范围
    range_xyz = calculate_range(xyz_values)
    range_xyY = calculate_range(xyY_values)

    # 计算置信度
    # 基于标准差的简单置信度评估
    if count >= 3:
        # 使用 Y 的相对标准差作为置信度指标
        if mean_xyz[1] > 0:
            relative_std = std_xyz[1] / mean_xyz[1]
            confidence = max(0.0, min(1.0, 1.0 - relative_std * 5))  # 5倍系数调整
        else:
            confidence = 0.5  # 暗部默认置信度
    else:
        confidence = 0.3  # 测量次数不足时置信度较低

    return MeasurementStatistics(
        count=count,
        mean_xyz=mean_xyz,
        mean_xyY=mean_xyY,
        std_xyz=std_xyz,
        std_xyY=std_xyY,
        max_deviation_xyz=max_deviation_xyz,
        max_deviation_xyY=max_deviation_xyY,
        range_xyz=range_xyz,
        range_xyY=range_xyY,
        averaging_method=method,
        measurements=measurements,
        timestamp_start=timestamp_start,
        timestamp_end=timestamp_end,
        duration_ms=duration_ms,
        confidence=confidence,
    )


def evaluate_repeatability(
    statistics: MeasurementStatistics,
    threshold: RepeatabilityThreshold,
    luminance_level: Optional[str] = None
) -> RepeatabilityResult:
    """
    评估测量重复性

    根据阈值判断测量是否通过、警告或失败

    Args:
        statistics: 测量统计数据
        threshold: 阈值配置
        luminance_level: 亮度级别（"dark", "mid", "bright"）用于调整阈值

    Returns:
        RepeatabilityResult: 评估结果
    """
    violations: List[str] = []
    warnings: List[str] = []

    # 获取警告阈值因子
    warn_factor = threshold.warn_threshold_factor

    # 检查测量次数
    if statistics.count < threshold.min_measurements:
        status = MeasurementStatus.UNKNOWN
        recommendation = f"测量次数不足（{statistics.count} < {threshold.min_measurements}），建议增加测量次数"
        return RepeatabilityResult(
            statistics=statistics,
            threshold=threshold,
            status=status,
            violations=[],
            warnings=[],
            recommendation=recommendation,
            needs_remeasurement=True,
        )

    # 根据亮度级别调整阈值（暗部测量更容易有噪声）
    effective_std_threshold = threshold.std_Y_threshold
    effective_relative_std_threshold = threshold.relative_std_Y_threshold
    effective_max_dev_threshold = threshold.max_deviation_Y_threshold

    if luminance_level == "dark":
        # 暗部放宽阈值（2倍）
        effective_std_threshold *= 2.0
        effective_relative_std_threshold *= 2.0
        effective_max_dev_threshold *= 2.0
    elif luminance_level == "bright":
        # 高亮度收紧阈值（0.5倍）
        effective_std_threshold *= 0.5
        effective_relative_std_threshold *= 0.5
        effective_max_dev_threshold *= 0.5

    # 检查 Y 标准差
    std_Y = statistics.std_xyz[1]
    if std_Y > effective_std_threshold:
        violations.append(f"Y 标准差 {std_Y:.4f} > 阈值 {effective_std_threshold:.4f} cd/m²")
    elif std_Y > effective_std_threshold * warn_factor:
        warnings.append(f"Y 标准差接近阈值: {std_Y:.4f} (阈值 {effective_std_threshold:.4f})")

    # 检查 Y 相对标准差
    relative_std_Y = statistics.relative_std_Y
    if relative_std_Y > effective_relative_std_threshold:
        violations.append(f"Y 相对标准差 {relative_std_Y:.2f}% > 阈值 {effective_relative_std_threshold:.2f}%")
    elif relative_std_Y > effective_relative_std_threshold * warn_factor:
        warnings.append(f"Y 相对标准差接近阈值: {relative_std_Y:.2f}% (阈值 {effective_relative_std_threshold:.2f}%)")

    # 检查 Y 最大偏差
    max_dev_Y = statistics.max_deviation_xyz[1]
    if max_dev_Y > effective_max_dev_threshold:
        violations.append(f"Y 最大偏差 {max_dev_Y:.4f} > 阈值 {effective_max_dev_threshold:.4f} cd/m²")
    elif max_dev_Y > effective_max_dev_threshold * warn_factor:
        warnings.append(f"Y 最大偏差接近阈值: {max_dev_Y:.4f} (阈值 {effective_max_dev_threshold:.4f})")

    # 检查 xy 坐标变化
    max_dev_x = statistics.max_deviation_xyY[0]
    max_dev_y = statistics.max_deviation_xyY[1]
    if max_dev_x > threshold.delta_xy_threshold:
        violations.append(f"x 最大偏差 {max_dev_x:.5f} > 阈值 {threshold.delta_xy_threshold:.5f}")
    elif max_dev_x > threshold.delta_xy_threshold * warn_factor:
        warnings.append(f"x 最大偏差接近阈值: {max_dev_x:.5f}")

    if max_dev_y > threshold.delta_xy_threshold:
        violations.append(f"y 最大偏差 {max_dev_y:.5f} > 阈值 {threshold.delta_xy_threshold:.5f}")
    elif max_dev_y > threshold.delta_xy_threshold * warn_factor:
        warnings.append(f"y 最大偏差接近阈值: {max_dev_y:.5f}")

    # 计算 u'v' 变化
    u1, v1 = xy_to_uv_1976(statistics.mean_xyY[0], statistics.mean_xyY[1])
    u_values = [xy_to_uv_1976(m.x, m.y)[0] for m in statistics.measurements]
    v_values = [xy_to_uv_1976(m.x, m.y)[1] for m in statistics.measurements]
    max_dev_u = max(abs(u - u1) for u in u_values) if u_values else 0.0
    max_dev_v = max(abs(v - v1) for v in v_values) if v_values else 0.0

    if max_dev_u > threshold.delta_uv_threshold or max_dev_v > threshold.delta_uv_threshold:
        violations.append(f"u'v' 最大偏差 ({max_dev_u:.5f}, {max_dev_v:.5f}) > 阈值 {threshold.delta_uv_threshold:.5f}")

    # 确定状态
    if violations:
        status = MeasurementStatus.FAIL
        recommendation = "测量重复性超过阈值，建议重新测量此色块"
        needs_remeasurement = True
    elif warnings:
        status = MeasurementStatus.WARN
        recommendation = "测量重复性接近阈值，建议关注或在条件允许时重新测量"
        needs_remeasurement = False
    else:
        status = MeasurementStatus.PASS
        recommendation = "测量重复性良好，结果可信"
        needs_remeasurement = False

    return RepeatabilityResult(
        statistics=statistics,
        threshold=threshold,
        status=status,
        violations=violations,
        warnings=warnings,
        recommendation=recommendation,
        needs_remeasurement=needs_remeasurement,
    )


def generate_repeatability_summary(
    session_id: str,
    patch_records: List[PatchRepeatabilityRecord]
) -> SessionRepeatabilitySummary:
    """
    生成 Session 重复性总结

    Args:
        session_id: Session ID
        patch_records: 各色块的重复性记录

    Returns:
        SessionRepeatabilitySummary: Session 总结
    """
    total_patches = len(patch_records)
    passed = sum(1 for r in patch_records if r.result.status == MeasurementStatus.PASS)
    warned = sum(1 for r in patch_records if r.result.status == MeasurementStatus.WARN)
    failed = sum(1 for r in patch_records if r.result.status == MeasurementStatus.FAIL)

    # 确定整体状态
    if failed > 0:
        overall_status = MeasurementStatus.FAIL
        overall_recommendation = f"{failed} 个色块超过阈值，建议重新测量后继续"
    elif warned > total_patches * 0.3:  # 超过 30% 警告
        overall_status = MeasurementStatus.WARN
        overall_recommendation = f"{warned} 个色块接近阈值，建议检查测量条件"
    elif warned > 0:
        overall_status = MeasurementStatus.WARN
        overall_recommendation = "少数色块接近阈值，整体测量质量良好"
    else:
        overall_status = MeasurementStatus.PASS
        overall_recommendation = "所有色块测量重复性良好"

    return SessionRepeatabilitySummary(
        session_id=session_id,
        total_patches=total_patches,
        passed_patches=passed,
        warned_patches=warned,
        failed_patches=failed,
        patches=patch_records,
        overall_status=overall_status,
        overall_recommendation=overall_recommendation,
        timestamp=datetime.now(),
    )


# ==============================================================================
# 辅助函数
# ==============================================================================

def get_luminance_level(Y: float) -> str:
    """
    根据亮度判断亮度级别

    Args:
        Y: 亮度值 (cd/m²)

    Returns:
        str: "dark", "mid", "bright"
    """
    if Y < 1.0:
        return "dark"
    elif Y < 50.0:
        return "mid"
    else:
        return "bright"


def create_single_measurement(
    xyz: Tuple[float, float, float],
    xyY: Optional[Tuple[float, float, float]] = None,
    instrument_status: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> SingleMeasurement:
    """
    创建单次测量记录（便捷函数）

    Args:
        xyz: XYZ 值
        xyY: xyY 值（如果未提供则从 XYZ 计算）
        instrument_status: 探头状态
        metadata: 其他元数据

    Returns:
        SingleMeasurement: 测量记录
    """
    if xyY is None:
        xyY = xyz_to_xyY(*xyz)

    return SingleMeasurement(
        xyz=xyz,
        xyY=xyY,
        timestamp=datetime.now(),
        instrument_status=instrument_status or {},
        metadata=metadata or {},
    )


def average_measurements_xyz(
    measurements: List[SingleMeasurement]
) -> Tuple[Tuple[float, float, float], MeasurementStatistics]:
    """
    XYZ 线性平均（便捷函数）

    用于暗部多重采样的主要平均方法

    Args:
        measurements: 测量记录列表

    Returns:
        Tuple[Tuple[float, float, float], MeasurementStatistics]: (均值XYZ, 统计数据)
    """
    stats = calculate_measurement_statistics(measurements, AveragingMethod.XYZ_LINEAR)
    return (stats.mean_xyz, stats)


# ==============================================================================
# 异常值检测与剔除
# ==============================================================================

@dataclass
class OutlierDetectionResult:
    """
    异常值检测结果

    Attributes:
        method: 使用的检测方法
        outlier_indices: 异常值索引列表
        accepted_measurements: 接受的测量列表
        rejected_measurements: 拒绝的测量列表
        threshold_used: 使用的阈值
        rejection_ratio: 拒绝比例
    """
    method: OutlierRejectionMethod = OutlierRejectionMethod.NONE
    outlier_indices: List[int] = field(default_factory=list)
    accepted_measurements: List[SingleMeasurement] = field(default_factory=list)
    rejected_measurements: List[SingleMeasurement] = field(default_factory=list)
    threshold_used: float = 0.0
    rejection_ratio: float = 0.0

    @property
    def has_outliers(self) -> bool:
        """是否有异常值"""
        return len(self.outlier_indices) > 0


def detect_outliers_mad(
    measurements: List[SingleMeasurement],
    threshold: float = 3.0,
    use_component: str = "Y"
) -> OutlierDetectionResult:
    """
    使用 MAD (Median Absolute Deviation) 方法检测异常值

    MAD 方法对小样本和偏态分布更鲁棒，推荐用于测量数据。

    公式:
        MAD = median(|x_i - median(x)|)
        Modified z-score = 0.6745 * (x_i - median(x)) / MAD
        异常值: |Modified z-score| > threshold

    Args:
        measurements: 测量记录列表
        threshold: MAD 阈值 (默认 3.0，推荐范围 2.5-3.5)
        use_component: 使用哪个分量 ("X", "Y", "Z", "all")

    Returns:
        OutlierDetectionResult: 检测结果
    """
    if len(measurements) < 3:
        return OutlierDetectionResult(
            method=OutlierRejectionMethod.MAD,
            accepted_measurements=measurements,
            threshold_used=threshold,
        )

    outlier_indices: List[int] = []

    if use_component == "all":
        # 对每个分量单独检测
        for comp_idx in range(3):
            values = [m.xyz[comp_idx] for m in measurements]
            median_val = _calculate_median(values)
            mad = _calculate_mad(values, median_val)

            if mad > 0:
                for i, val in enumerate(values):
                    modified_z = 0.6745 * abs(val - median_val) / mad
                    if modified_z > threshold:
                        if i not in outlier_indices:
                            outlier_indices.append(i)
    else:
        # 对单个分量检测
        comp_idx = {"X": 0, "Y": 1, "Z": 2}.get(use_component, 1)
        values = [m.xyz[comp_idx] for m in measurements]
        median_val = _calculate_median(values)
        mad = _calculate_mad(values, median_val)

        if mad > 0:
            for i, val in enumerate(values):
                modified_z = 0.6745 * abs(val - median_val) / mad
                if modified_z > threshold:
                    outlier_indices.append(i)

    # 分离接受的和拒绝的测量
    accepted = [m for i, m in enumerate(measurements) if i not in outlier_indices]
    rejected = [m for i, m in enumerate(measurements) if i in outlier_indices]

    rejection_ratio = len(outlier_indices) / len(measurements) if measurements else 0.0

    return OutlierDetectionResult(
        method=OutlierRejectionMethod.MAD,
        outlier_indices=outlier_indices,
        accepted_measurements=accepted,
        rejected_measurements=rejected,
        threshold_used=threshold,
        rejection_ratio=rejection_ratio,
    )


def detect_outliers_iqr(
    measurements: List[SingleMeasurement],
    iqr_factor: float = 1.5,
    use_component: str = "Y"
) -> OutlierDetectionResult:
    """
    使用 IQR (Interquartile Range) 方法检测异常值

    适合较大样本量的数据。

    公式:
        Q1 = 25th percentile, Q3 = 75th percentile
        IQR = Q3 - Q1
        Lower bound = Q1 - iqr_factor * IQR
        Upper bound = Q3 + iqr_factor * IQR
        异常值: x_i < Lower bound OR x_i > Upper bound

    Args:
        measurements: 测量记录列表
        iqr_factor: IQR 因子 (默认 1.5，严格可用 1.0)
        use_component: 使用哪个分量

    Returns:
        OutlierDetectionResult: 检测结果
    """
    if len(measurements) < 4:
        return OutlierDetectionResult(
            method=OutlierRejectionMethod.IQR,
            accepted_measurements=measurements,
            threshold_used=iqr_factor,
        )

    outlier_indices: List[int] = []
    comp_idx = {"X": 0, "Y": 1, "Z": 2}.get(use_component, 1)
    values = [m.xyz[comp_idx] for m in measurements]

    sorted_values = sorted(values)
    n = len(sorted_values)

    # 计算 Q1 和 Q3
    q1_idx = int(n * 0.25)
    q3_idx = int(n * 0.75)

    q1 = sorted_values[q1_idx]
    q3 = sorted_values[q3_idx]
    iqr = q3 - q1

    lower_bound = q1 - iqr_factor * iqr
    upper_bound = q3 + iqr_factor * iqr

    for i, val in enumerate(values):
        if val < lower_bound or val > upper_bound:
            outlier_indices.append(i)

    accepted = [m for i, m in enumerate(measurements) if i not in outlier_indices]
    rejected = [m for i, m in enumerate(measurements) if i in outlier_indices]

    rejection_ratio = len(outlier_indices) / len(measurements) if measurements else 0.0

    return OutlierDetectionResult(
        method=OutlierRejectionMethod.IQR,
        outlier_indices=outlier_indices,
        accepted_measurements=accepted,
        rejected_measurements=rejected,
        threshold_used=iqr_factor,
        rejection_ratio=rejection_ratio,
    )


def detect_outliers_zscore(
    measurements: List[SingleMeasurement],
    threshold: float = 2.0,
    use_component: str = "Y"
) -> OutlierDetectionResult:
    """
    使用 Z-score 方法检测异常值

    适合样本量 >= 10 的数据，基于正态分布假设。

    公式:
        z = (x - mean) / std
        异常值: |z| > threshold

    Args:
        measurements: 测量记录列表
        threshold: Z-score 阈值 (默认 2.0)
        use_component: 使用哪个分量

    Returns:
        OutlierDetectionResult: 检测结果
    """
    if len(measurements) < 10:
        # 样本量不足，建议使用 MAD
        return OutlierDetectionResult(
            method=OutlierRejectionMethod.Z_SCORE,
            accepted_measurements=measurements,
            threshold_used=threshold,
        )

    outlier_indices: List[int] = []
    comp_idx = {"X": 0, "Y": 1, "Z": 2}.get(use_component, 1)
    values = [m.xyz[comp_idx] for m in measurements]

    mean_val = calculate_mean(values)
    std_val = calculate_std(values, mean_val)

    if std_val > 0:
        for i, val in enumerate(values):
            z = abs(val - mean_val) / std_val
            if z > threshold:
                outlier_indices.append(i)

    accepted = [m for i, m in enumerate(measurements) if i not in outlier_indices]
    rejected = [m for i, m in enumerate(measurements) if i in outlier_indices]

    rejection_ratio = len(outlier_indices) / len(measurements) if measurements else 0.0

    return OutlierDetectionResult(
        method=OutlierRejectionMethod.Z_SCORE,
        outlier_indices=outlier_indices,
        accepted_measurements=accepted,
        rejected_measurements=rejected,
        threshold_used=threshold,
        rejection_ratio=rejection_ratio,
    )


def detect_outliers(
    measurements: List[SingleMeasurement],
    method: OutlierRejectionMethod = OutlierRejectionMethod.MAD,
    threshold: float = 3.0,
    use_component: str = "Y"
) -> OutlierDetectionResult:
    """
    综合异常值检测函数

    根据选择的自动方法检测异常值。

    Args:
        measurements: 测量记录列表
        method: 检测方法
        threshold: 阈值参数
        use_component: 使用哪个分量

    Returns:
        OutlierDetectionResult: 检测结果
    """
    if method == OutlierRejectionMethod.NONE:
        return OutlierDetectionResult(
            method=method,
            accepted_measurements=measurements,
            threshold_used=0.0,
        )
    elif method == OutlierRejectionMethod.MAD:
        return detect_outliers_mad(measurements, threshold, use_component)
    elif method == OutlierRejectionMethod.IQR:
        return detect_outliers_iqr(measurements, threshold, use_component)
    elif method == OutlierRejectionMethod.Z_SCORE:
        return detect_outliers_zscore(measurements, threshold, use_component)
    else:
        # 默认使用 MAD
        return detect_outliers_mad(measurements, threshold, use_component)


def _calculate_median(values: List[float]) -> float:
    """计算中位数"""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    n = len(sorted_values)
    if n % 2 == 0:
        return (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2.0
    else:
        return sorted_values[n // 2]


def _calculate_mad(values: List[float], median: float) -> float:
    """计算 MAD (Median Absolute Deviation)"""
    if not values:
        return 0.0
    deviations = [abs(v - median) for v in values]
    return _calculate_median(deviations)


# ==============================================================================
# 置信度评估与低亮区处理
# ==============================================================================

@dataclass
class PatchMeasurementPolicy:
    """
    单个色块的测量策略配置

    用于 per-patch 定制测量策略。

    Attributes:
        repeat_count: 重复测量次数
        outlier_rejection_method: 异常值剔除方法
        outlier_threshold: 异常值剔除阈值
        confidence_threshold: 最低置信度要求
        settling_time_ms: 稳定等待时间
        integration_time_factor: 积分时间因子 (相对于标准)
        min_accepted_readings: 最少接受读数
        force_dark_handling: 强制使用暗部处理策略
    """
    repeat_count: int = 3
    outlier_rejection_method: OutlierRejectionMethod = OutlierRejectionMethod.MAD
    outlier_threshold: float = 3.0
    confidence_threshold: float = 0.7
    settling_time_ms: Optional[int] = None
    integration_time_factor: float = 1.0
    min_accepted_readings: int = 2
    force_dark_handling: bool = False


def get_luminance_policy(
    Y: float,
    base_policy: Optional[PatchMeasurementPolicy] = None
) -> PatchMeasurementPolicy:
    """
    根据亮度自动获取测量策略

    低亮区会自动使用更严格的策略：
    - 更高的重复次数
    - 更长的积分时间
    - 放宽的异常值阈值

    Args:
        Y: 亮度值 (cd/m²)
        base_policy: 基础策略 (可选，用于叠加调整)

    Returns:
        PatchMeasurementPolicy: 调整后的测量策略
    """
    base = base_policy or PatchMeasurementPolicy()

    level = get_luminance_level_enum(Y)

    if level == LuminanceLevel.DARK:
        # 低亮区策略：更高重复次数、更长积分时间、放宽异常阈值
        return PatchMeasurementPolicy(
            repeat_count=max(base.repeat_count, 5),
            outlier_rejection_method=base.outlier_rejection_method,
            outlier_threshold=base.outlier_threshold * 1.5,  # 放宽
            confidence_threshold=base.confidence_threshold * 0.8,  # 放宽
            settling_time_ms=base.settling_time_ms or 500,
            integration_time_factor=max(base.integration_time_factor, 2.0),
            min_accepted_readings=max(base.min_accepted_readings, 3),
            force_dark_handling=True,
        )
    elif level == LuminanceLevel.MID:
        # 中等亮度：标准策略
        return PatchMeasurementPolicy(
            repeat_count=base.repeat_count,
            outlier_rejection_method=base.outlier_rejection_method,
            outlier_threshold=base.outlier_threshold,
            confidence_threshold=base.confidence_threshold,
            settling_time_ms=base.settling_time_ms or 300,
            integration_time_factor=base.integration_time_factor,
            min_accepted_readings=base.min_accepted_readings,
            force_dark_handling=base.force_dark_handling,
        )
    else:
        # 高亮度：可以更快测量
        return PatchMeasurementPolicy(
            repeat_count=max(base.repeat_count, 2),
            outlier_rejection_method=base.outlier_rejection_method,
            outlier_threshold=base.outlier_threshold * 0.8,  # 收紧
            confidence_threshold=base.confidence_threshold,
            settling_time_ms=base.settling_time_ms or 200,
            integration_time_factor=base.integration_time_factor,
            min_accepted_readings=base.min_accepted_readings,
            force_dark_handling=False,
        )


def get_luminance_level_enum(Y: float) -> LuminanceLevel:
    """
    根据亮度返回 LuminanceLevel enum

    Args:
        Y: 亮度值 (cd/m²)

    Returns:
        LuminanceLevel: 亮度级别
    """
    if Y < 1.0:
        return LuminanceLevel.DARK
    elif Y < 50.0:
        return LuminanceLevel.MID
    else:
        return LuminanceLevel.BRIGHT


def calculate_confidence_score(
    statistics: MeasurementStatistics,
    outlier_result: Optional[OutlierDetectionResult] = None
) -> float:
    """
    计算置信度评分

    基于：
    - 测量次数
    - 相对标准差
    - 异常值剔除结果
    - 亮度级别

    Args:
        statistics: 测量统计数据
        outlier_result: 异常值检测结果 (可选)

    Returns:
        float: 置信度评分 (0-1)
    """
    if statistics.count == 0:
        return 0.0

    # 基础置信度：来自统计数据
    base_confidence = statistics.confidence

    # 测量次数因子
    count_factor = min(1.0, statistics.count / 5.0)  # 5次为满分

    # 相对标准差因子
    relative_std = statistics.relative_std_Y
    if relative_std < 1.0:
        std_factor = 1.0
    elif relative_std < 2.0:
        std_factor = 0.9
    elif relative_std < 5.0:
        std_factor = 0.7
    else:
        std_factor = 0.5

    # 异常值剔除因子
    if outlier_result and outlier_result.has_outliers:
        # 有异常值时，根据剔除比例调整
        rejection_factor = 1.0 - outlier_result.rejection_ratio * 0.5
    else:
        rejection_factor = 1.0

    # 综合置信度
    confidence = base_confidence * count_factor * std_factor * rejection_factor

    # 确保在 [0, 1] 范围内
    return max(0.0, min(1.0, confidence))


def get_measurement_quality_status(
    confidence: float,
    threshold: RepeatabilityThreshold,
    luminance_level: LuminanceLevel = LuminanceLevel.MID
) -> MeasurementStatus:
    """
    根据置信度获取测量质量状态

    Args:
        confidence: 置信度评分
        threshold: 阈值配置
        luminance_level: 亮度级别

    Returns:
        MeasurementStatus: 质量状态
    """
    # 根据亮度级别调整置信度阈值
    if luminance_level == LuminanceLevel.DARK:
        # 暗部放宽要求
        pass_threshold = 0.6
        warn_threshold = 0.4
    elif luminance_level == LuminanceLevel.BRIGHT:
        # 高亮度收紧要求
        pass_threshold = 0.85
        warn_threshold = 0.7
    else:
        # 中等亮度标准阈值
        pass_threshold = 0.75
        warn_threshold = 0.5

    if confidence >= pass_threshold:
        return MeasurementStatus.PASS
    elif confidence >= warn_threshold:
        return MeasurementStatus.WARN
    else:
        return MeasurementStatus.FAIL
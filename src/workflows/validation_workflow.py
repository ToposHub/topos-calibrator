"""
Validation Workflow - 校准与验证闭环工作流

专业校色工具必须区分：
- 校准前测量（baseline）
- 校准后测量（after calibration）
- 验证测量（independent verification）

本模块实现：
    - MeasurementType: 测量类型枚举（baseline, after_calibration, verification）
    - ValidationRun: 单次验证运行记录
    - ValidationSession: 同一 display/session 下多 run 管理
    - ValidationThreshold: 预设合格阈值（sRGB/Rec.709 等）
    - ValidationResult: 验证结果与合格/不合格判断
    - VerificationPatchGenerator: 独立验证色块生成
    - BeforeAfterComparison: Before/After 对比报告

    【统一验收层设计】
    - ValidationInput: 所有 workflow 的统一输入接口
    - ValidationOutput: 所有 workflow 的统一输出 JSON
    - validate_from_input(): 入口函数，ICC/LUT/measurement-only 三条路径调用
    - generator.py 只消费 ValidationOutput，不再自己计算指标

关键设计原则：
    - 验证色块独立于建模色块，避免"自己考自己"
    - 验证数据不能覆盖建模数据
    - 支持同一 display 下多次验证 run
    - ICC/LUT/measurement-only 三条路径输出同一种 validation JSON

Reference:
    - docs/professional_optimization_plan.md (P4-D 任务)
    - docs/agent_handoffs/P2-A_color_science_module.md (色彩科学模块)
"""

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable, Set

from src.color_science import (
    delta_e_ciede2000,
    gamut_coverage_percent,
    gamut_area_ratio,
    gamut_metrics,
    cct_duv_from_xy,
    xyz_to_lab,
    xyY_to_xyz,
    get_white_point_xy,
    WHITE_POINTS,
    xyz_to_srgb,
    lab_to_xyz,
    srgb_to_xyz,
)
from src.color_science.gamut_sampling import (
    GamutSampler,
    SamplingStrategy,
    polygon_vertices_from_rgbw,
    polygon_intersection_area,
    lab_to_rgb_for_sampler,
)
from src.color_science.transfer import (
    identify_black_patch,
    identify_white_patch,
    prepare_measurements_for_eotf,
    calculate_eotf_errors,
)
from src.measurement_analyzer import STANDARD_GAMUTS


logger = logging.getLogger(__name__)


# ==============================================================================
# 统一验收层 - 输入/输出数据结构
# ==============================================================================

class WorkflowType(Enum):
    """
    工作流类型 - 标识验证来源

    - ICC_PROFILE: ICC Profile 生成工作流
    - LUT_GENERATION: 3D LUT 生成工作流
    - MEASUREMENT_ONLY: 仅测量工作流 (无 profile/LUT)
    """
    ICC_PROFILE = "icc_profile"
    LUT_GENERATION = "lut_generation"
    MEASUREMENT_ONLY = "measurement_only"


@dataclass
class SamplePoint:
    """
    单个测量样本点

    Attributes:
        rgb: RGB 值 (0-255)
        name: 色块名称
        xyz: 测量 XYZ 值 (可选)
        xyY: 测量 xyY 值
        target_xyY: 目标 xyY 值 (用于计算 Delta E)
        delta_e: Delta E 2000 值 (计算后填充)
    """
    rgb: Tuple[int, int, int]
    name: str
    xyY: Tuple[float, float, float]
    xyz: Optional[Tuple[float, float, float]] = None
    target_xyY: Optional[Tuple[float, float, float]] = None
    delta_e: Optional[float] = None


@dataclass
class GrayscalePoint:
    """
    灰阶测量点

    Attributes:
        input_level: 输入级别 (0-100%)
        Y: 测量亮度 (cd/m²)
        measured_gamma: 该点测量的 Gamma 值
    """
    input_level: float
    Y: float
    measured_gamma: Optional[float] = None


@dataclass
class GamutPoint:
    """
    色域测量点 (RGBW)

    Attributes:
        color_name: 颜色名称 (red, green, blue, white, black)
        xy: xy 坐标
        Y: 亮度
    """
    color_name: str
    xy: Tuple[float, float]
    Y: float


@dataclass
class ValidationInput:
    """
    统一验证输入 - 所有 workflow 共用

    所有 workflow (ICC, LUT, measurement-only) 完成后调用
    ValidationWorkflow.validate_from_input(input) 得到统一输出。

    Attributes:
        workflow_type: 工作流类型 (ICC/LUT/measurement-only)
        target_color_space: 目标色彩空间名称 ("sRGB", "Rec.709", "DCI-P3", "Rec.2020")
        target_gamma: 目标 Gamma 值
        target_white_point: 目标白点名称 ("D65", "D50", "D60")

        measured_samples: 测量的样本数据列表
        grayscale_data: 灰阶测量数据列表
        gamut_data: RGBW 色域测量数据

        applied_profile_path: 应用 ICC Profile 路径 (可选)
        applied_lut_path: 应用 LUT 路径 (可选)

        device_info: 设备信息 (探头、显示器)
        session_id: 会话 ID
        timestamp: 测量时间
    """
    workflow_type: WorkflowType = WorkflowType.MEASUREMENT_ONLY
    target_color_space: str = "sRGB"
    target_gamma: float = 2.2
    target_white_point: str = "D65"

    # 测量数据
    measured_samples: List[SamplePoint] = field(default_factory=list)
    grayscale_data: List[GrayscalePoint] = field(default_factory=list)
    gamut_data: Dict[str, GamutPoint] = field(default_factory=dict)

    # 校准文件 (可选)
    applied_profile_path: Optional[str] = None
    applied_lut_path: Optional[str] = None

    # 元数据
    device_info: Dict[str, str] = field(default_factory=dict)
    session_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "workflow_type": self.workflow_type.value,
            "target_color_space": self.target_color_space,
            "target_gamma": self.target_gamma,
            "target_white_point": self.target_white_point,
            "measured_samples": [
                {
                    "rgb": list(s.rgb),
                    "name": s.name,
                    "xyY": list(s.xyY),
                    "xyz": list(s.xyz) if s.xyz else None,
                    "target_xyY": list(s.target_xyY) if s.target_xyY else None,
                    "delta_e": s.delta_e,
                } for s in self.measured_samples
            ],
            "grayscale_data": [
                {
                    "input_level": g.input_level,
                    "Y": g.Y,
                    "measured_gamma": g.measured_gamma,
                } for g in self.grayscale_data
            ],
            "gamut_data": {
                k: {
                    "color_name": v.color_name,
                    "xy": list(v.xy),
                    "Y": v.Y,
                } for k, v in self.gamut_data.items()
            },
            "applied_profile_path": self.applied_profile_path,
            "applied_lut_path": self.applied_lut_path,
            "device_info": self.device_info,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
        }


@dataclass
class GrayscaleTrackingPoint:
    """
    灰阶跟踪点 - 验证输出中的灰阶数据

    Attributes:
        input_level: 输入级别 (0-100%)
        Y: 测量亮度 (cd/m²)
        measured_gamma: 该点 Gamma 值
        target_gamma: 目标 Gamma 值
        gamma_error: Gamma 误差
        delta_e: 该点 Delta E (如果有)
    """
    input_level: float
    Y: float
    measured_gamma: Optional[float] = None
    target_gamma: float = 2.2
    gamma_error: Optional[float] = None
    delta_e: Optional[float] = None


@dataclass
class PassFailResult:
    """
    单项指标合格/不合格判定

    Attributes:
        metric_name: 指标名称
        value: 实测值
        threshold: 阈值
        passed: 是否合格
        reason: 判定原因
    """
    metric_name: str
    value: float
    threshold: float
    passed: bool
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "value": self.value,
            "threshold": self.threshold,
            "passed": self.passed,
            "reason": self.reason,
        }


@dataclass
class ValidationOutput:
    """
    统一验证输出 - 所有 workflow 共用

    报告生成器 generator.py 只消费此结构，不再自己计算指标。

    Attributes:
        workflow_type: 工作流类型
        target_color_space: 目标色彩空间
        validation_id: 验证 ID
        timestamp: 验证时间

        delta_e_avg: 平均 Delta E
        delta_e_max: 最大 Delta E
        delta_e_95: 95% Delta E
        delta_e_distribution: Delta E 分布统计

        grayscale_tracking: 灰阶跟踪数据 (每点详情)
        gamma_avg: 平均 Gamma 值
        gamma_error_avg: Gamma 平均误差

        gamut_coverage: 色域覆盖率 (%)
        gamut_area_ratio: 色域面积比 (%)

        white_point_cct: 白点 CCT (K)
        white_point_duv: 白点 Duv
        white_point_error: 白点误差

        peak_luminance: 峰值亮度 (cd/m²)
        black_luminance: 黑场亮度 (cd/m²)
        contrast_ratio: 对比度

        pass_fail: 各指标的合格/不合格判定
        overall_status: 综合状态 (PASSED/WARNING/FAILED)
        overall_summary: 综合判定说明

        raw_data: 原始输入数据 (用于报告生成)
        applied_file: 应用校准文件信息
    """
    workflow_type: WorkflowType = WorkflowType.MEASUREMENT_ONLY
    target_color_space: str = "sRGB"
    validation_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Delta E 统计
    delta_e_avg: float = 0.0
    delta_e_max: float = 0.0
    delta_e_95: float = 0.0
    delta_e_distribution: Dict[str, int] = field(default_factory=dict)

    # Gamma/EOTF
    grayscale_tracking: List[GrayscaleTrackingPoint] = field(default_factory=list)
    gamma_avg: Optional[float] = None
    gamma_error_avg: float = 0.0

    # 色域
    gamut_coverage: float = 0.0
    gamut_area_ratio: float = 0.0
    measured_gamut_triangle: List[Tuple[float, float]] = field(default_factory=list)
    standard_gamut_triangle: List[Tuple[float, float]] = field(default_factory=list)

    # 白点
    white_point_cct: float = 6500.0
    white_point_duv: float = 0.0
    white_point_error: float = 0.0

    # 亮度/对比度
    peak_luminance: float = 100.0
    black_luminance: float = 0.0
    contrast_ratio: float = 0.0

    # 合格判定
    pass_fail: Dict[str, PassFailResult] = field(default_factory=dict)
    overall_status: str = "PENDING"
    overall_summary: str = ""

    # 原始数据和校准文件
    raw_data: Optional[Dict[str, Any]] = None
    applied_file: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式 - 用于报告生成器消费

        输出标准 JSON 结构，报告生成器直接读取此结构。
        """
        return {
            "validation_id": self.validation_id,
            "workflow_type": self.workflow_type.value,
            "target_color_space": self.target_color_space,
            "timestamp": self.timestamp,

            # Delta E
            "delta_e": {
                "avg": self.delta_e_avg,
                "max": self.delta_e_max,
                "95": self.delta_e_95,
                "distribution": self.delta_e_distribution,
            },

            # Gamma/EOTF
            "gamma": {
                "avg": self.gamma_avg,
                "error_avg": self.gamma_error_avg,
                "grayscale_tracking": [
                    {
                        "input_level": g.input_level,
                        "Y": g.Y,
                        "measured_gamma": g.measured_gamma,
                        "target_gamma": g.target_gamma,
                        "gamma_error": g.gamma_error,
                        "delta_e": g.delta_e,
                    } for g in self.grayscale_tracking
                ],
            },

            # 色域
            "gamut": {
                "coverage": self.gamut_coverage,
                "area_ratio": self.gamut_area_ratio,
                "measured_triangle": [list(p) for p in self.measured_gamut_triangle],
                "standard_triangle": [list(p) for p in self.standard_gamut_triangle],
            },

            # 白点
            "white_point": {
                "cct": self.white_point_cct,
                "duv": self.white_point_duv,
                "error": self.white_point_error,
            },

            # 亮度
            "luminance": {
                "peak": self.peak_luminance,
                "black": self.black_luminance,
                "contrast_ratio": self.contrast_ratio,
            },

            # 合格判定
            "pass_fail": {
                k: v.to_dict() for k, v in self.pass_fail.items()
            },
            "overall_status": self.overall_status,
            "overall_summary": self.overall_summary,

            # 校准文件
            "applied_file": self.applied_file,
        }

    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# ==============================================================================
# 测量类型枚举
# ==============================================================================

class MeasurementType(Enum):
    """
    测量类型 - 区分不同测量目的

    专业校色工具必须明确区分：
    - BASELINE: 校准前测量，记录显示器原始状态
    - AFTER_CALIBRATION: 校准后测量，记录校准效果
    - VERIFICATION: 独立验证测量，使用独立色块验证校准质量

    重要：VERIFICATION 色块不能与建模色块相同，避免"自己考自己"
    """
    BASELINE = "baseline"
    AFTER_CALIBRATION = "after_calibration"
    VERIFICATION = "verification"


class ValidationStatus(Enum):
    """
    验证状态

    - PENDING: 待验证
    - RUNNING: 正在验证
    - PASSED: 验证合格
    - FAILED: 验证不合格
    - WARNING: 验证完成但有警告
    """
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


# ==============================================================================
# 预设阈值 - sRGB/Rec.709 标准合格阈值
# ==============================================================================

@dataclass
class ValidationThreshold:
    """
    验证合格阈值

    不同标准有不同的合格阈值。sRGB/Rec.709 有默认值：
    - Delta E 平均值阈值
    - Delta E 最大值阈值
    - 白点 CCT 偏移阈值
    - 白点 Duv 阈值
    - Gamma 偏移阈值
    - 色域覆盖率阈值

    参考：
    - ISO 12647-7 (印刷验证标准)
    - SMPTE RP 431-2 (DCI-P3 验证)
    - ITU-R BT.1886 (电视标准)
    """
    # Delta E 阈值
    delta_e_avg_threshold: float = 2.0  # 平均 Delta E < 2.0 为合格
    delta_e_max_threshold: float = 6.0  # 最大 Delta E < 6.0 为合格
    delta_e_95_threshold: float = 4.0   # 95% 色块 Delta E < 4.0

    # 白点阈值
    white_point_cct_tolerance: float = 200.0  # CCT 偏移 < 200K
    white_point_duv_tolerance: float = 0.005  # Duv < 0.005

    # Gamma 阈值
    gamma_tolerance: float = 0.05  # Gamma 偏移 < 0.05

    # 色域阈值
    gamut_coverage_threshold: float = 95.0  # 覆盖率 >= 95%
    gamut_area_tolerance: float = 5.0       # 面积比偏差 < 5%

    # 亮度阈值
    luminance_tolerance: float = 5.0  # 亮度偏差 < 5%
    contrast_ratio_tolerance: float = 0.1  # 对比度偏差 < 10%

    # 标准名称
    standard_name: str = "sRGB/Rec.709"

    def is_delta_e_passed(self, avg_delta_e: float, max_delta_e: float) -> Tuple[bool, str]:
        """
        判断 Delta E 是否合格

        Returns:
            Tuple[bool, str]: (是否合格, 原因说明)
        """
        if avg_delta_e <= self.delta_e_avg_threshold:
            if max_delta_e <= self.delta_e_max_threshold:
                return True, f"平均 Delta E {avg_delta_e:.2f} <= {self.delta_e_avg_threshold}, 最大 {max_delta_e:.2f} <= {self.delta_e_max_threshold}"
            else:
                return False, f"平均 Delta E 合格但最大 Delta E {max_delta_e:.2f} > {self.delta_e_max_threshold}"
        else:
            return False, f"平均 Delta E {avg_delta_e:.2f} > {self.delta_e_avg_threshold}"

    def is_white_point_passed(self, cct_offset: float, duv: float) -> Tuple[bool, str]:
        """
        判断白点是否合格

        Returns:
            Tuple[bool, str]: (是否合格, 原因说明)
        """
        if abs(cct_offset) <= self.white_point_cct_tolerance:
            if abs(duv) <= self.white_point_duv_tolerance:
                return True, f"CCT偏移 {abs(cct_offset):.0f}K <= {self.white_point_cct_tolerance}K, Duv {abs(duv):.4f} <= {self.white_point_duv_tolerance}"
            else:
                return False, f"CCT合格但 Duv {abs(duv):.4f} > {self.white_point_duv_tolerance}"
        else:
            return False, f"CCT偏移 {abs(cct_offset):.0f}K > {self.white_point_cct_tolerance}K"

    def is_gamma_passed(self, gamma_offset: float) -> Tuple[bool, str]:
        """
        判断 Gamma 是否合格

        Returns:
            Tuple[bool, str]: (是否合格, 原因说明)
        """
        if abs(gamma_offset) <= self.gamma_tolerance:
            return True, f"Gamma偏移 {abs(gamma_offset):.3f} <= {self.gamma_tolerance}"
        else:
            return False, f"Gamma偏移 {abs(gamma_offset):.3f} > {self.gamma_tolerance}"

    def is_gamut_passed(self, coverage: float, area_ratio: float) -> Tuple[bool, str]:
        """
        判断色域是否合格

        Returns:
            Tuple[bool, str]: (是否合格, 原因说明)
        """
        if coverage >= self.gamut_coverage_threshold:
            if abs(area_ratio - 100.0) <= self.gamut_area_tolerance:
                return True, f"覆盖率 {coverage:.1f}% >= {self.gamut_coverage_threshold}%"
            else:
                return True, f"覆盖率合格，面积比偏差 {abs(area_ratio - 100.0):.1f}%"
        else:
            return False, f"覆盖率 {coverage:.1f}% < {self.gamut_coverage_threshold}%"


# 标准阈值预设
STANDARD_THRESHOLDS: Dict[str, ValidationThreshold] = {
    "sRGB": ValidationThreshold(
        delta_e_avg_threshold=2.0,
        delta_e_max_threshold=6.0,
        delta_e_95_threshold=4.0,
        white_point_cct_tolerance=200.0,
        white_point_duv_tolerance=0.005,
        gamma_tolerance=0.05,
        gamut_coverage_threshold=95.0,
        standard_name="sRGB (IEC 61966-2-1)",
    ),
    "Rec.709": ValidationThreshold(
        delta_e_avg_threshold=2.0,
        delta_e_max_threshold=6.0,
        delta_e_95_threshold=4.0,
        white_point_cct_tolerance=200.0,
        white_point_duv_tolerance=0.005,
        gamma_tolerance=0.05,
        gamut_coverage_threshold=95.0,
        standard_name="Rec.709 (BT.709)",
    ),
    "DCI-P3": ValidationThreshold(
        delta_e_avg_threshold=3.0,
        delta_e_max_threshold=8.0,
        delta_e_95_threshold=5.0,
        white_point_cct_tolerance=300.0,
        white_point_duv_tolerance=0.007,
        gamma_tolerance=0.05,
        gamut_coverage_threshold=90.0,
        standard_name="DCI-P3 (SMPTE RP 431-2)",
    ),
    "Rec.2020": ValidationThreshold(
        delta_e_avg_threshold=3.0,
        delta_e_max_threshold=8.0,
        delta_e_95_threshold=5.0,
        white_point_cct_tolerance=200.0,
        white_point_duv_tolerance=0.005,
        gamma_tolerance=0.05,
        gamut_coverage_threshold=80.0,  # Rec.2020 很大，覆盖率要求降低
        standard_name="Rec.2020 (BT.2020)",
    ),
    "AdobeRGB": ValidationThreshold(
        delta_e_avg_threshold=2.5,
        delta_e_max_threshold=7.0,
        delta_e_95_threshold=4.5,
        white_point_cct_tolerance=200.0,
        white_point_duv_tolerance=0.005,
        gamma_tolerance=0.05,
        gamut_coverage_threshold=90.0,
        standard_name="Adobe RGB (1998)",
    ),
}


def get_threshold_for_standard(standard: str) -> ValidationThreshold:
    """
    获取指定标准的验证阈值

    Args:
        standard: 标准名称 ("sRGB", "Rec.709", "DCI-P3", "Rec.2020", "AdobeRGB")

    Returns:
        ValidationThreshold: 验证阈值
    """
    if standard in STANDARD_THRESHOLDS:
        return STANDARD_THRESHOLDS[standard]

    # 默认返回 sRGB/Rec.709 阈值
    logger.warning(f"未知标准 '{standard}'，使用默认 sRGB/Rec.709 阈值")
    return STANDARD_THRESHOLDS["sRGB"]


# ==============================================================================
# 验证色块生成 - 独立于建模色块
# ==============================================================================

@dataclass
class VerificationPatchConfig:
    """
    验证色块配置

    验证色块必须独立于建模色块，避免"自己考自己"

    Attributes:
        count: 验证色块数量 (建议 30-100)
        strategy: 采样策略
        include_grayscale: 包含灰阶色块
        include_primary_secondary: 包含原色和二次色
        include_skin_tones: 包含肤色
        avoid_modeling_patches: 避免与建模色块重叠
        seed: 随机种子 (用于可复现)
    """
    count: int = 50
    strategy: SamplingStrategy = SamplingStrategy.ICC_STANDARD
    include_grayscale: bool = True
    include_primary_secondary: bool = True
    include_skin_tones: bool = True
    avoid_modeling_patches: bool = True
    seed: Optional[int] = None


class VerificationPatchGenerator:
    """
    验证色块生成器

    生成独立于建模色块的验证色块，确保验证有效性

    关键原则：
    - 验证色块不能与建模色块完全相同
    - 覆盖关键色域区域
    - 包含灰阶验证
    - 可复现（使用种子）
    """

    # 标准灰阶百分比
    GRAYSCALE_LEVELS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

    # 原色和二次色
    PRIMARY_COLORS = [
        (255, 0, 0, "Red"),
        (0, 255, 0, "Green"),
        (0, 0, 255, "Blue"),
    ]

    SECONDARY_COLORS = [
        (255, 255, 0, "Yellow"),
        (255, 0, 255, "Magenta"),
        (0, 255, 255, "Cyan"),
    ]

    # 肤色参考点 (Lab 空间)
    SKIN_TONE_LAB = [
        (65.0, 15.0, 20.0),  # 浅肤色
        (50.0, 20.0, 25.0),  # 中等肤色
        (35.0, 15.0, 15.0),  # 深肤色
    ]

    def __init__(self, config: Optional[VerificationPatchConfig] = None):
        """
        初始化验证色块生成器

        Args:
            config: 验证色块配置 (默认使用标准配置)
        """
        self._config = config or VerificationPatchConfig()

    def generate(
        self,
        model_patches: Optional[List[Tuple[int, int, int, str]]] = None,
        target_gamut: str = "sRGB"
    ) -> List[Tuple[int, int, int, str]]:
        """
        生成验证色块列表

        Args:
            model_patches: 建模色块列表 (用于避免重叠)
            target_gamut: 目标色域

        Returns:
            List[Tuple[int, int, int, str]]: 验证色块 [(r, g, b, name), ...]
        """
        patches: List[Tuple[int, int, int, str]] = []
        model_set: Set[Tuple[int, int, int]] = set()

        # 收集建模色块 RGB 值 (用于避免重叠)
        if model_patches and self._config.avoid_modeling_patches:
            for r, g, b, _ in model_patches:
                # 允许小偏差 (±3) 以避免完全相同
                for dr in range(-3, 4):
                    for dg in range(-3, 4):
                        for db in range(-3, 4):
                            model_set.add((
                                max(0, min(255, r + dr)),
                                max(0, min(255, g + dg)),
                                max(0, min(255, b + db))
                            ))

        # 1. 灰阶色块 (使用标准灰阶)
        if self._config.include_grayscale:
            for level in self.GRAYSCALE_LEVELS:
                v = int(level * 255 / 100)
                rgb = (v, v, v)
                if rgb not in model_set:
                    patches.append((v, v, v, f"Gray_{level}%"))

        # 2. 原色和二次色
        if self._config.include_primary_secondary:
            for r, g, b, name in self.PRIMARY_COLORS:
                rgb = (r, g, b)
                if rgb not in model_set:
                    patches.append((r, g, b, name))
            for r, g, b, name in self.SECONDARY_COLORS:
                rgb = (r, g, b)
                if rgb not in model_set:
                    patches.append((r, g, b, name))

        # 3. 肤色
        if self._config.include_skin_tones:
            for i, (L, a, b) in enumerate(self.SKIN_TONE_LAB):
                try:
                    rgb = lab_to_rgb_for_sampler(L, a, b)
                    rgb = (
                        max(0, min(255, int(rgb[0]))),
                        max(0, min(255, int(rgb[1]))),
                        max(0, min(255, int(rgb[2])))
                    )
                    if rgb not in model_set:
                        patches.append((*rgb, f"Skin_{i+1}"))
                except Exception as e:
                    logger.warning(f"肤色转换失败: {e}")

        # 4. 随机采样填充剩余数量
        remaining_count = self._config.count - len(patches)
        if remaining_count > 0:
            sampler = GamutSampler(strategy=self._config.strategy)
            random_patches = sampler.generate_patches(remaining_count)
            for patch in random_patches:
                rgb = patch.rgb
                rgb = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
                if rgb not in model_set:
                    patches.append((*rgb, patch.purpose or f"Verify_{len(patches)}"))
                    model_set.add(rgb)

        logger.info(f"生成 {len(patches)} 个验证色块 (目标: {self._config.count}, 避免 {len(model_set)} 个建模色块)")
        return patches


# ==============================================================================
# 验证运行记录
# ==============================================================================

@dataclass
class MeasurementPoint:
    """
    单个测量点数据

    Attributes:
        rgb: RGB 值 (0-255)
        name: 色块名称
        xyz: 测量 XYZ 值
        xyY: 测量 xyY 值
        target_xyY: 目标 xyY 值 (计算得到)
        delta_e: Delta E 2000
        timestamp: 测量时间
        measurement_type: 测量类型
    """
    rgb: Tuple[int, int, int]
    name: str
    xyz: Tuple[float, float, float]
    xyY: Tuple[float, float, float]
    target_xyY: Optional[Tuple[float, float, float]] = None
    delta_e: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)
    measurement_type: MeasurementType = MeasurementType.VERIFICATION


@dataclass
class ValidationRun:
    """
    单次验证运行记录

    同一 display/session 下可以有多个 run

    Attributes:
        run_id: 运行 ID
        run_number: 运行序号 (第几次验证)
        measurement_type: 测量类型
        target_standard: 目标标准 (sRGB, Rec.709 等)
        threshold: 使用阈值
        gamut_data: 色域测量数据 (RGBW)
        grayscale_data: 灰阶测量数据
        verification_points: 验证色块测量点
        white_point_measured: 测量白点 xy
        white_point_cct: 测量 CCT
        white_point_duv: 测量 Duv
        peak_luminance: 峰值亮度
        black_luminance: 黑场亮度
        gamma_estimate: Gamma 估算值
        gamut_coverage: 色域覆盖率
        gamut_area_ratio: 色域面积比
        delta_e_avg: 平均 Delta E
        delta_e_max: 最大 Delta E
        delta_e_95: 95% Delta E
        started_at: 开始时间
        completed_at: 完成时间
        status: 验证状态
        result: 验证结果详情
        notes: 备注
    """
    run_id: str = ""
    run_number: int = 1
    measurement_type: MeasurementType = MeasurementType.VERIFICATION
    target_standard: str = "sRGB"
    threshold: ValidationThreshold = field(default_factory=lambda: STANDARD_THRESHOLDS["sRGB"])

    # 测量数据
    gamut_data: Dict[str, MeasurementPoint] = field(default_factory=dict)
    grayscale_data: List[MeasurementPoint] = field(default_factory=list)
    verification_points: List[MeasurementPoint] = field(default_factory=list)

    # 计算指标
    white_point_measured: Tuple[float, float] = (0.3127, 0.3290)
    white_point_cct: float = 6500.0
    white_point_duv: float = 0.0
    peak_luminance: float = 100.0
    black_luminance: float = 0.0
    gamma_estimate: Optional[float] = None
    gamut_coverage: float = 0.0
    gamut_area_ratio: float = 0.0
    delta_e_avg: float = 0.0
    delta_e_max: float = 0.0
    delta_e_95: float = 0.0

    # 时间信息
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # 验证状态
    status: ValidationStatus = ValidationStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    notes: str = ""

    def calculate_metrics(self) -> None:
        """
        计算验证指标

        包括：
        - Delta E 统计
        - 白点 CCT/Duv
        - Gamma 估算
        - 色域覆盖率
        """
        # 计算 Delta E 统计
        if self.verification_points:
            delta_e_values = [p.delta_e for p in self.verification_points if p.delta_e is not None]
            if delta_e_values:
                self.delta_e_avg = sum(delta_e_values) / len(delta_e_values)
                self.delta_e_max = max(delta_e_values)
                # 95 percentile
                sorted_values = sorted(delta_e_values)
                idx_95 = int(len(sorted_values) * 0.95)
                self.delta_e_95 = sorted_values[min(idx_95, len(sorted_values) - 1)]

        # 从白点数据计算 CCT/Duv
        white_point = self.gamut_data.get("white")
        if white_point:
            x, y = white_point.xyY[0], white_point.xyY[1]
            self.white_point_measured = (x, y)
            self.white_point_cct, self.white_point_duv = cct_duv_from_xy(x, y)
            self.peak_luminance = white_point.xyY[2]

        # 从黑点数据获取黑场亮度
        black_point = self.gamut_data.get("black")
        if black_point:
            self.black_luminance = black_point.xyY[2]

        # 计算色域覆盖率
        if len(self.gamut_data) >= 3:
            red = self.gamut_data.get("red")
            green = self.gamut_data.get("green")
            blue = self.gamut_data.get("blue")
            if red and green and blue:
                measured_vertices = [
                    (red.xyY[0], red.xyY[1]),
                    (green.xyY[0], green.xyY[1]),
                    (blue.xyY[0], blue.xyY[1]),
                ]
                metrics = gamut_metrics(measured_vertices, self.target_standard)
                self.gamut_coverage = metrics.get("coverage_percent", 0.0)
                self.gamut_area_ratio = metrics.get("area_ratio_percent", 0.0)

    def validate(self) -> Tuple[ValidationStatus, Dict[str, Any]]:
        """
        执行验证判断

        Returns:
            Tuple[ValidationStatus, Dict]: (验证状态, 详细结果)
        """
        self.calculate_metrics()

        results: Dict[str, Any] = {
            "delta_e": {},
            "white_point": {},
            "gamma": {},
            "gamut": {},
            "overall": {},
        }

        passed_checks = []
        failed_checks = []
        warning_checks = []

        # 1. Delta E 验证
        if self.delta_e_avg > 0:
            passed, reason = self.threshold.is_delta_e_passed(self.delta_e_avg, self.delta_e_max)
            results["delta_e"] = {
                "avg": self.delta_e_avg,
                "max": self.delta_e_max,
                "95": self.delta_e_95,
                "passed": passed,
                "reason": reason,
            }
            if passed:
                passed_checks.append("delta_e")
            else:
                failed_checks.append("delta_e")
                results["delta_e"]["threshold_avg"] = self.threshold.delta_e_avg_threshold
                results["delta_e"]["threshold_max"] = self.threshold.delta_e_max_threshold

        # 2. 白点验证
        target_white = get_white_point_xy("D65")
        cct_offset = self.white_point_cct - 6500.0
        passed, reason = self.threshold.is_white_point_passed(cct_offset, self.white_point_duv)
        results["white_point"] = {
            "measured_x": self.white_point_measured[0],
            "measured_y": self.white_point_measured[1],
            "target_x": target_white[0],
            "target_y": target_white[1],
            "cct": self.white_point_cct,
            "cct_offset": cct_offset,
            "duv": self.white_point_duv,
            "passed": passed,
            "reason": reason,
        }
        if passed:
            passed_checks.append("white_point")
        else:
            failed_checks.append("white_point")

        # 3. Gamma 验证
        if self.gamma_estimate is not None:
            # 目标 Gamma 2.2 (sRGB/Rec.709)
            gamma_offset = self.gamma_estimate - 2.2
            passed, reason = self.threshold.is_gamma_passed(gamma_offset)
            results["gamma"] = {
                "measured": self.gamma_estimate,
                "target": 2.2,
                "offset": gamma_offset,
                "passed": passed,
                "reason": reason,
            }
            if passed:
                passed_checks.append("gamma")
            else:
                failed_checks.append("gamma")

        # 4. 色域验证
        passed, reason = self.threshold.is_gamut_passed(self.gamut_coverage, self.gamut_area_ratio)
        results["gamut"] = {
            "coverage": self.gamut_coverage,
            "area_ratio": self.gamut_area_ratio,
            "passed": passed,
            "reason": reason,
        }
        if passed:
            passed_checks.append("gamut")
        else:
            failed_checks.append("gamut")

        # 综合判断
        if len(failed_checks) == 0:
            self.status = ValidationStatus.PASSED
            results["overall"]["status"] = "PASSED"
            results["overall"]["summary"] = f"所有指标合格 ({len(passed_checks)}项通过)"
        elif len(failed_checks) <= 2:
            self.status = ValidationStatus.WARNING
            results["overall"]["status"] = "WARNING"
            results["overall"]["summary"] = f"{len(failed_checks)}项不合格: {', '.join(failed_checks)}"
        else:
            self.status = ValidationStatus.FAILED
            results["overall"]["status"] = "FAILED"
            results["overall"]["summary"] = f"{len(failed_checks)}项不合格: {', '.join(failed_checks)}"

        results["overall"]["passed_checks"] = passed_checks
        results["overall"]["failed_checks"] = failed_checks

        self.result = results
        self.completed_at = datetime.now()

        return self.status, results


# ==============================================================================
# 验证 Session - 多 Run 管理
# ==============================================================================

@dataclass
class ValidationSession:
    """
    验证会话 - 同一 display/session 下多 run 管理

    Attributes:
        session_id: 会话 ID
        display_id: 显示器 ID
        display_name: 显示器名称
        target_standard: 目标标准
        baseline_run: 基线测量 run (校准前)
        calibration_runs: 校准后测量 runs
        verification_runs: 验证 runs
        all_runs: 所有 runs 列表
        created_at: 创建时间
        last_updated: 最后更新时间
        manifest: 会话 manifest (记录所有 artifacts)
    """
    session_id: str = ""
    display_id: int = 0
    display_name: str = ""
    target_standard: str = "sRGB"

    # 不同测量类型的 runs
    baseline_run: Optional[ValidationRun] = None
    calibration_runs: List[ValidationRun] = field(default_factory=list)
    verification_runs: List[ValidationRun] = field(default_factory=list)

    # 所有 runs 列表 (便于查询)
    all_runs: List[ValidationRun] = field(default_factory=list)

    # 时间信息
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)

    # Manifest
    manifest: Dict[str, Any] = field(default_factory=dict)

    def add_run(self, run: ValidationRun) -> None:
        """
        添加验证 run

        Args:
            run: 验证 run
        """
        # 分配 run number
        run.run_number = len(self.all_runs) + 1

        # 根据测量类型分类存储
        if run.measurement_type == MeasurementType.BASELINE:
            self.baseline_run = run
        elif run.measurement_type == MeasurementType.AFTER_CALIBRATION:
            self.calibration_runs.append(run)
        elif run.measurement_type == MeasurementType.VERIFICATION:
            self.verification_runs.append(run)

        self.all_runs.append(run)
        self.last_updated = datetime.now()

        logger.info(f"添加 run {run.run_number} ({run.measurement_type.value}) 到 session {self.session_id}")

    def get_latest_calibration_run(self) -> Optional[ValidationRun]:
        """获取最近的校准后测量 run"""
        if self.calibration_runs:
            return self.calibration_runs[-1]
        return None

    def get_latest_verification_run(self) -> Optional[ValidationRun]:
        """获取最近的验证 run"""
        if self.verification_runs:
            return self.verification_runs[-1]
        return None

    def get_run_by_id(self, run_id: str) -> Optional[ValidationRun]:
        """根据 ID 获取 run"""
        for run in self.all_runs:
            if run.run_id == run_id:
                return run
        return None


# ==============================================================================
# Before/After 对比
# ==============================================================================

@dataclass
class BeforeAfterComparison:
    """
    Before/After 对比报告

    对比校准前和校准后的效果

    Attributes:
        before_run: 校准前 run
        after_run: 校准后 run
        delta_e_improvement: Delta E 改善
        white_point_improvement: 白点改善
        gamma_improvement: Gamma 改善
        gamut_improvement: 色域改善
        contrast_improvement: 对比度改善
        improvement_summary: 改善汇总
    """
    before_run: Optional[ValidationRun] = None
    after_run: Optional[ValidationRun] = None

    # 改善数据
    delta_e_improvement: Optional[float] = None
    white_point_improvement: Optional[float] = None  # Duv 绝对值改善
    gamma_improvement: Optional[float] = None
    gamut_improvement: Optional[float] = None
    contrast_improvement: Optional[float] = None

    # 汇总
    improvement_summary: Dict[str, Any] = field(default_factory=dict)

    def compare(self) -> Dict[str, Any]:
        """
        执行对比计算

        Returns:
            Dict: 对比结果
        """
        if not self.before_run or not self.after_run:
            return {"error": "需要 before 和 after run 数据"}

        before = self.before_run
        after = self.after_run

        comparison: Dict[str, Any] = {
            "before": {},
            "after": {},
            "improvement": {},
        }

        # 1. Delta E 对比
        before_delta_e = before.delta_e_avg
        after_delta_e = after.delta_e_avg
        self.delta_e_improvement = before_delta_e - after_delta_e
        comparison["before"]["delta_e_avg"] = before_delta_e
        comparison["before"]["delta_e_max"] = before.delta_e_max
        comparison["after"]["delta_e_avg"] = after_delta_e
        comparison["after"]["delta_e_max"] = after.delta_e_max
        comparison["improvement"]["delta_e_avg"] = self.delta_e_improvement
        comparison["improvement"]["delta_e_improved"] = self.delta_e_improvement > 0

        # 2. 白点对比
        before_duv = abs(before.white_point_duv)
        after_duv = abs(after.white_point_duv)
        self.white_point_improvement = before_duv - after_duv
        comparison["before"]["white_point_cct"] = before.white_point_cct
        comparison["before"]["white_point_duv"] = before.white_point_duv
        comparison["after"]["white_point_cct"] = after.white_point_cct
        comparison["after"]["white_point_duv"] = after.white_point_duv
        comparison["improvement"]["white_point_duv"] = self.white_point_improvement
        comparison["improvement"]["white_point_improved"] = self.white_point_improvement > 0

        # 3. Gamma 对比
        if before.gamma_estimate and after.gamma_estimate:
            before_gamma_offset = abs(before.gamma_estimate - 2.2)
            after_gamma_offset = abs(after.gamma_estimate - 2.2)
            self.gamma_improvement = before_gamma_offset - after_gamma_offset
            comparison["before"]["gamma"] = before.gamma_estimate
            comparison["before"]["gamma_offset"] = before_gamma_offset
            comparison["after"]["gamma"] = after.gamma_estimate
            comparison["after"]["gamma_offset"] = after_gamma_offset
            comparison["improvement"]["gamma_offset"] = self.gamma_improvement
            comparison["improvement"]["gamma_improved"] = self.gamma_improvement > 0

        # 4. 色域对比
        self.gamut_improvement = after.gamut_coverage - before.gamut_coverage
        comparison["before"]["gamut_coverage"] = before.gamut_coverage
        comparison["before"]["gamut_area_ratio"] = before.gamut_area_ratio
        comparison["after"]["gamut_coverage"] = after.gamut_coverage
        comparison["after"]["gamut_area_ratio"] = after.gamut_area_ratio
        comparison["improvement"]["gamut_coverage"] = self.gamut_improvement
        comparison["improvement"]["gamut_improved"] = self.gamut_improvement > 0

        # 5. 对比度对比
        before_contrast = before.peak_luminance / before.black_luminance if before.black_luminance > 0 else 0
        after_contrast = after.peak_luminance / after.black_luminance if after.black_luminance > 0 else 0
        self.contrast_improvement = after_contrast - before_contrast
        comparison["before"]["contrast_ratio"] = before_contrast
        comparison["before"]["peak_luminance"] = before.peak_luminance
        comparison["before"]["black_luminance"] = before.black_luminance
        comparison["after"]["contrast_ratio"] = after_contrast
        comparison["after"]["peak_luminance"] = after.peak_luminance
        comparison["after"]["black_luminance"] = after.black_luminance
        comparison["improvement"]["contrast_ratio"] = self.contrast_improvement
        comparison["improvement"]["contrast_improved"] = self.contrast_improvement > 0

        # 综合评估
        improved_count = sum([
            comparison["improvement"]["delta_e_improved"],
            comparison["improvement"]["white_point_improved"],
            comparison["improvement"].get("gamma_improved", False),
            comparison["improvement"]["gamut_improved"],
            comparison["improvement"]["contrast_improved"],
        ])

        total_checks = 5
        comparison["improvement"]["overall_improved_count"] = improved_count
        comparison["improvement"]["overall_improved_percent"] = (improved_count / total_checks) * 100

        if improved_count >= 4:
            comparison["improvement"]["overall_result"] = "优秀改善"
        elif improved_count >= 3:
            comparison["improvement"]["overall_result"] = "良好改善"
        elif improved_count >= 2:
            comparison["improvement"]["overall_result"] = "部分改善"
        elif improved_count >= 1:
            comparison["improvement"]["overall_result"] = "轻微改善"
        else:
            comparison["improvement"]["overall_result"] = "无改善或恶化"

        self.improvement_summary = comparison
        return comparison


# ==============================================================================
# 验证工作流服务
# ==============================================================================

class ValidationWorkflowService:
    """
    验证工作流服务

    协调完整的校准验证流程：
    1. 基线测量 (baseline)
    2. 执行校准
    3. 校准后测量 (after calibration)
    4. 独立验证测量 (verification)
    5. Before/After 对比报告

    关键原则：
    - 验证色块独立于建模色块
    - 验证数据不能覆盖建模数据
    - 支持同一 display 下多次验证 run
    """

    def __init__(
        self,
        target_standard: str = "sRGB",
        threshold: Optional[ValidationThreshold] = None
    ):
        """
        初始化验证工作流服务

        Args:
            target_standard: 目标标准
            threshold: 验证阈值 (默认使用标准阈值)
        """
        self._target_standard = target_standard
        self._threshold = threshold or get_threshold_for_standard(target_standard)
        self._session: Optional[ValidationSession] = None
        self._model_patches: List[Tuple[int, int, int, str]] = []

        # 回调函数
        self._on_run_added_callbacks: List[Callable[[ValidationRun], None]] = []
        self._on_validation_complete_callbacks: List[Callable[[ValidationRun, Dict], None]] = []
        self._on_comparison_complete_callbacks: List[Callable[[BeforeAfterComparison, Dict], None]] = []

    @property
    def session(self) -> Optional[ValidationSession]:
        """获取当前会话"""
        return self._session

    @property
    def threshold(self) -> ValidationThreshold:
        """获取验证阈值"""
        return self._threshold

    @property
    def target_standard(self) -> str:
        """获取目标标准"""
        return self._target_standard

    def set_model_patches(self, patches: List[Tuple[int, int, int, str]]) -> None:
        """
        设置建模色块列表

        用于生成验证色块时避免重叠

        Args:
            patches: 建模色块 [(r, g, b, name), ...]
        """
        self._model_patches = patches.copy()
        logger.info(f"设置建模色块 {len(patches)} 个，验证色块将避免重叠")

    def create_session(
        self,
        display_id: int,
        display_name: str,
        session_id: Optional[str] = None
    ) -> ValidationSession:
        """
        创建验证会话

        Args:
            display_id: 显示器 ID
            display_name: 显示器名称
            session_id: 会话 ID (自动生成如果未提供)

        Returns:
            ValidationSession: 新建的验证会话
        """
        if not session_id:
            session_id = f"validation_{display_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        self._session = ValidationSession(
            session_id=session_id,
            display_id=display_id,
            display_name=display_name,
            target_standard=self._target_standard,
            created_at=datetime.now(),
        )

        logger.info(f"创建验证会话 {session_id} (显示器: {display_name}, 标准: {self._target_standard})")
        return self._session

    def create_run(
        self,
        measurement_type: MeasurementType,
        run_id: Optional[str] = None
    ) -> ValidationRun:
        """
        创建验证 run

        Args:
            measurement_type: 测量类型
            run_id: Run ID (自动生成如果未提供)

        Returns:
            ValidationRun: 新建的验证 run
        """
        if not run_id:
            run_id = f"run_{measurement_type.value}_{datetime.now().strftime('%H%M%S')}"

        run = ValidationRun(
            run_id=run_id,
            measurement_type=measurement_type,
            target_standard=self._target_standard,
            threshold=self._threshold,
            started_at=datetime.now(),
        )

        return run

    def add_measurement_point(
        self,
        run: ValidationRun,
        rgb: Tuple[int, int, int],
        name: str,
        xyz: Tuple[float, float, float],
        xyY: Tuple[float, float, float],
        is_gamut_point: bool = False,
        is_grayscale_point: bool = False,
        target_xyY: Optional[Tuple[float, float, float]] = None
    ) -> MeasurementPoint:
        """
        添加测量点到 run

        Args:
            run: 验证 run
            rgb: RGB 值
            name: 色块名称
            xyz: 测量 XYZ
            xyY: 测量 xyY
            is_gamut_point: 是否为色域测量点 (RGBW)
            is_grayscale_point: 是否为灰阶点
            target_xyY: 目标 xyY (用于计算 Delta E)

        Returns:
            MeasurementPoint: 创建的测量点
        """
        point = MeasurementPoint(
            rgb=rgb,
            name=name,
            xyz=xyz,
            xyY=xyY,
            target_xyY=target_xyY,
            measurement_type=run.measurement_type,
        )

        # 计算 Delta E (如果有目标值)
        if target_xyY:
            try:
                # 转换到 Lab 计算 Delta E
                measured_lab = xyz_to_lab(xyY_to_xyz(xyY[0], xyY[1], xyY[2])[0], xyY[2], xyY_to_xyz(xyY[0], xyY[1], xyY[2])[2])
                target_lab = xyz_to_lab(xyY_to_xyz(target_xyY[0], target_xyY[1], target_xyY[2])[0], target_xyY[2], xyY_to_xyz(target_xyY[0], target_xyY[1], target_xyY[2])[2])
                point.delta_e = delta_e_ciede2000(measured_lab, target_lab)
            except Exception as e:
                logger.warning(f"Delta E 计算失败: {e}")

        # 分类存储
        if is_gamut_point:
            color_name = name.lower()
            if "red" in color_name or "r" == color_name:
                run.gamut_data["red"] = point
            elif "green" in color_name or "g" == color_name:
                run.gamut_data["green"] = point
            elif "blue" in color_name or "b" == color_name:
                run.gamut_data["blue"] = point
            elif "white" in color_name or "w" == color_name:
                run.gamut_data["white"] = point
            elif "black" in color_name:
                run.gamut_data["black"] = point
        elif is_grayscale_point:
            run.grayscale_data.append(point)
        else:
            run.verification_points.append(point)

        return point

    def complete_run(self, run: ValidationRun) -> Tuple[ValidationStatus, Dict[str, Any]]:
        """
        完成 run 并执行验证

        Args:
            run: 验证 run

        Returns:
            Tuple[ValidationStatus, Dict]: (验证状态, 结果详情)
        """
        status, result = run.validate()

        # 添加到 session
        if self._session:
            self._session.add_run(run)
            self._notify_run_added(run)

        self._notify_validation_complete(run, result)

        logger.info(f"完成 run {run.run_id}: {status.value}")
        return status, result

    def generate_verification_patches(
        self,
        config: Optional[VerificationPatchConfig] = None
    ) -> List[Tuple[int, int, int, str]]:
        """
        生成验证色块

        Args:
            config: 验证色块配置

        Returns:
            List[Tuple[int, int, int, str]]: 验证色块列表
        """
        config = config or VerificationPatchConfig()
        generator = VerificationPatchGenerator(config)
        return generator.generate(self._model_patches, self._target_standard)

    def compare_before_after(
        self,
        before_run_id: Optional[str] = None,
        after_run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        对比 before 和 after

        Args:
            before_run_id: Before run ID (默认使用 baseline)
            after_run_id: After run ID (默认使用最近的 calibration run)

        Returns:
            Dict: 对比结果
        """
        if not self._session:
            return {"error": "没有活跃的验证会话"}

        # 获取 before run
        if before_run_id:
            before_run = self._session.get_run_by_id(before_run_id)
        else:
            before_run = self._session.baseline_run

        # 获取 after run
        if after_run_id:
            after_run = self._session.get_run_by_id(after_run_id)
        else:
            after_run = self._session.get_latest_calibration_run()

        if not before_run or not after_run:
            return {"error": "需要 before (baseline) 和 after (calibration) run"}

        comparison = BeforeAfterComparison(
            before_run=before_run,
            after_run=after_run,
        )

        result = comparison.compare()
        self._notify_comparison_complete(comparison, result)

        return result

    # ========== 回调注册 ==========

    def on_run_added(self, callback: Callable[[ValidationRun], None]) -> None:
        """注册 run 添加回调"""
        self._on_run_added_callbacks.append(callback)

    def on_validation_complete(
        self, callback: Callable[[ValidationRun, Dict], None]
    ) -> None:
        """注册验证完成回调"""
        self._on_validation_complete_callbacks.append(callback)

    def on_comparison_complete(
        self, callback: Callable[[BeforeAfterComparison, Dict], None]
    ) -> None:
        """注册对比完成回调"""
        self._on_comparison_complete_callbacks.append(callback)

    def _notify_run_added(self, run: ValidationRun) -> None:
        """通知 run 添加"""
        for callback in self._on_run_added_callbacks:
            try:
                callback(run)
            except Exception as e:
                logger.error(f"Run added callback error: {e}")

    def _notify_validation_complete(
        self, run: ValidationRun, result: Dict
    ) -> None:
        """通知验证完成"""
        for callback in self._on_validation_complete_callbacks:
            try:
                callback(run, result)
            except Exception as e:
                logger.error(f"Validation complete callback error: {e}")

    def _notify_comparison_complete(
        self, comparison: BeforeAfterComparison, result: Dict
    ) -> None:
        """通知对比完成"""
        for callback in self._on_comparison_complete_callbacks:
            try:
                callback(comparison, result)
            except Exception as e:
                logger.error(f"Comparison complete callback error: {e}")

    # ========== 数据导出 ==========

    def export_session_summary(self) -> Dict[str, Any]:
        """
        导出会话汇总

        Returns:
            Dict: 会话汇总数据
        """
        if not self._session:
            return {"error": "没有活跃的验证会话"}

        return {
            "session_id": self._session.session_id,
            "display_id": self._session.display_id,
            "display_name": self._session.display_name,
            "target_standard": self._session.target_standard,
            "created_at": self._session.created_at.isoformat(),
            "last_updated": self._session.last_updated.isoformat(),
            "total_runs": len(self._session.all_runs),
            "baseline_run_id": self._session.baseline_run.run_id if self._session.baseline_run else None,
            "calibration_runs": [r.run_id for r in self._session.calibration_runs],
            "verification_runs": [r.run_id for r in self._session.verification_runs],
            "threshold": {
                "standard_name": self._threshold.standard_name,
                "delta_e_avg": self._threshold.delta_e_avg_threshold,
                "delta_e_max": self._threshold.delta_e_max_threshold,
                "white_point_cct_tolerance": self._threshold.white_point_cct_tolerance,
                "white_point_duv_tolerance": self._threshold.white_point_duv_tolerance,
                "gamma_tolerance": self._threshold.gamma_tolerance,
                "gamut_coverage": self._threshold.gamut_coverage_threshold,
            },
        }

    def export_run_data(self, run: ValidationRun) -> Dict[str, Any]:
        """
        导出 run 数据

        Args:
            run: 验证 run

        Returns:
            Dict: run 数据
        """
        return {
            "run_id": run.run_id,
            "run_number": run.run_number,
            "measurement_type": run.measurement_type.value,
            "target_standard": run.target_standard,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "status": run.status.value,
            "metrics": {
                "delta_e_avg": run.delta_e_avg,
                "delta_e_max": run.delta_e_max,
                "delta_e_95": run.delta_e_95,
                "white_point_cct": run.white_point_cct,
                "white_point_duv": run.white_point_duv,
                "peak_luminance": run.peak_luminance,
                "black_luminance": run.black_luminance,
                "gamma_estimate": run.gamma_estimate,
                "gamut_coverage": run.gamut_coverage,
                "gamut_area_ratio": run.gamut_area_ratio,
            },
            "gamut_points": {
                k: {
                    "rgb": v.rgb,
                    "xyY": v.xyY,
                } for k, v in run.gamut_data.items()
            },
            "grayscale_points": [
                {
                    "rgb": p.rgb,
                    "name": p.name,
                    "xyY": p.xyY,
                    "delta_e": p.delta_e,
                } for p in run.grayscale_data
            ],
            "verification_points": [
                {
                    "rgb": p.rgb,
                    "name": p.name,
                    "xyY": p.xyY,
                    "target_xyY": p.target_xyY,
                    "delta_e": p.delta_e,
                } for p in run.verification_points
            ],
            "result": run.result,
            "notes": run.notes,
        }

    # ========== 统一验收层入口函数 ==========

    def validate_from_input(self, input_data: ValidationInput) -> ValidationOutput:
        """
        统一验收入口 - 所有 workflow 的共同验收层

        ICC/LUT/measurement-only 三条路径完成后调用此方法，
        得到统一的 ValidationOutput JSON。

        Args:
            input_data: ValidationInput 包含目标色彩空间、测量数据等

        Returns:
            ValidationOutput: 统一的验证输出 JSON，报告生成器直接消费此结构

        Note:
            此方法是唯一的验证计算入口，generator.py 不再自己计算指标，
            只消费此方法的输出。
        """
        logger.info(
            f"validate_from_input 开始: workflow_type={input_data.workflow_type.value}, "
            f"target={input_data.target_color_space}, "
            f"samples={len(input_data.measured_samples)}, "
            f"grayscale={len(input_data.grayscale_data)}, "
            f"gamut={len(input_data.gamut_data)}"
        )

        # 创建输出对象
        output = ValidationOutput(
            workflow_type=input_data.workflow_type,
            target_color_space=input_data.target_color_space,
            validation_id=f"validation_{input_data.session_id}_{datetime.now().strftime('%H%M%S')}",
            timestamp=datetime.now().isoformat(),
        )

        # 获取阈值
        threshold = get_threshold_for_standard(input_data.target_color_space)

        # 1. 计算 Delta E 统计
        self._calculate_delta_e_metrics(input_data, output)

        # 2. 计算 Gamma/EOTF 指标
        self._calculate_gamma_metrics(input_data, output)

        # 3. 计算色域覆盖率
        self._calculate_gamut_metrics(input_data, output)

        # 4. 计算白点指标
        self._calculate_white_point_metrics(input_data, output)

        # 5. 计算亮度/对比度
        self._calculate_luminance_metrics(input_data, output)

        # 6. 执行合格判定
        self._evaluate_pass_fail(input_data, output, threshold)

        # 7. 设置校准文件信息
        if input_data.applied_profile_path or input_data.applied_lut_path:
            output.applied_file = {
                "profile_path": input_data.applied_profile_path,
                "lut_path": input_data.applied_lut_path,
            }

        # 8. 保存原始数据引用 (用于报告生成)
        output.raw_data = input_data.to_dict()

        logger.info(
            f"validate_from_input 完成: delta_e_avg={output.delta_e_avg:.2f}, "
            f"gamma_avg={output.gamma_avg}, "
            f"gamut_coverage={output.gamut_coverage:.1f}%, "
            f"status={output.overall_status}"
        )

        return output

    def _calculate_delta_e_metrics(
        self,
        input_data: ValidationInput,
        output: ValidationOutput
    ) -> None:
        """
        计算 Delta E 统计指标

        Args:
            input_data: 输入数据
            output: 输出对象 (会被修改)
        """
        if not input_data.measured_samples:
            output.delta_e_avg = 0.0
            output.delta_e_max = 0.0
            output.delta_e_95 = 0.0
            return

        delta_e_values = []

        # 计算每个样本点的 Delta E
        for sample in input_data.measured_samples:
            if sample.target_xyY:
                # 计算 Delta E 2000
                try:
                    # 转换到 Lab
                    measured_xyz = xyY_to_xyz(sample.xyY[0], sample.xyY[1], sample.xyY[2])
                    target_xyz = xyY_to_xyz(sample.target_xyY[0], sample.target_xyY[1], sample.target_xyY[2])

                    # 使用 D65 作为参考白
                    ref_white = get_white_point_xyz("D65")
                    measured_lab = xyz_to_lab(measured_xyz[0], measured_xyz[1], measured_xyz[2], ref_white)
                    target_lab = xyz_to_lab(target_xyz[0], target_xyz[1], target_xyz[2], ref_white)

                    delta_e = delta_e_ciede2000(measured_lab, target_lab)
                    sample.delta_e = delta_e
                    delta_e_values.append(delta_e)
                except Exception as e:
                    logger.warning(f"Delta E 计算失败 ({sample.name}): {e}")

        if delta_e_values:
            output.delta_e_avg = sum(delta_e_values) / len(delta_e_values)
            output.delta_e_max = max(delta_e_values)

            # 95 percentile
            sorted_values = sorted(delta_e_values)
            idx_95 = int(len(sorted_values) * 0.95)
            output.delta_e_95 = sorted_values[min(idx_95, len(sorted_values) - 1)]

            # Delta E 分布统计
            output.delta_e_distribution = {
                "<1": sum(1 for v in delta_e_values if v < 1),
                "1-2": sum(1 for v in delta_e_values if 1 <= v < 2),
                "2-3": sum(1 for v in delta_e_values if 2 <= v < 3),
                "3-4": sum(1 for v in delta_e_values if 3 <= v < 4),
                ">4": sum(1 for v in delta_e_values if v >= 4),
            }

    def _calculate_gamma_metrics(
        self,
        input_data: ValidationInput,
        output: ValidationOutput
    ) -> None:
        """
        计算 Gamma/EOTF 指标

        Args:
            input_data: 输入数据
            output: 输出对象 (会被修改)
        """
        if not input_data.grayscale_data:
            return

        # 获取白场和黑场亮度
        white_Y = 100.0
        black_Y = 0.0

        if "white" in input_data.gamut_data:
            white_Y = input_data.gamut_data["white"].Y
        if "black" in input_data.gamut_data:
            black_Y = input_data.gamut_data["black"].Y

        gamma_values = []
        tracking_points = []

        for gray in input_data.grayscale_data:
            input_level = gray.input_level / 100.0 if gray.input_level > 1 else gray.input_level
            Y = gray.Y

            # 计算该点 Gamma
            if input_level > 0.01 and input_level < 0.99 and Y > black_Y:
                Y_normalized = (Y - black_Y) / (white_Y - black_Y)

                if Y_normalized > 0 and Y_normalized < 1:
                    measured_gamma = math.log(Y_normalized) / math.log(input_level)

                    if 1.0 <= measured_gamma <= 4.0:  # 合理范围
                        gamma_values.append(measured_gamma)
                        gray.measured_gamma = measured_gamma

            # 创建跟踪点
            tracking_point = GrayscaleTrackingPoint(
                input_level=gray.input_level,
                Y=gray.Y,
                measured_gamma=gray.measured_gamma,
                target_gamma=input_data.target_gamma,
                gamma_error=abs(gray.measured_gamma - input_data.target_gamma) if gray.measured_gamma else None,
            )
            tracking_points.append(tracking_point)

        output.grayscale_tracking = tracking_points

        if gamma_values:
            output.gamma_avg = sum(gamma_values) / len(gamma_values)
            output.gamma_error_avg = abs(output.gamma_avg - input_data.target_gamma)

    def _calculate_gamut_metrics(
        self,
        input_data: ValidationInput,
        output: ValidationOutput
    ) -> None:
        """
        计算色域覆盖率指标

        Args:
            input_data: 输入数据
            output: 输出对象 (会被修改)
        """
        # 提取 RGB 三点
        required_colors = ["red", "green", "blue"]
        measured_triangle = []

        for color in required_colors:
            if color in input_data.gamut_data:
                point = input_data.gamut_data[color]
                measured_triangle.append(point.xy)

        if len(measured_triangle) != 3:
            logger.warning("色域测量数据不完整，无法计算覆盖率")
            return

        output.measured_gamut_triangle = measured_triangle

        # 获取标准色域三角形
        standard = input_data.target_color_space
        if standard in STANDARD_GAMUTS:
            std_gamut = STANDARD_GAMUTS[standard]
            output.standard_gamut_triangle = [
                std_gamut["red"],
                std_gamut["green"],
                std_gamut["blue"],
            ]

            # 计算覆盖率
            metrics = gamut_metrics(measured_triangle, standard)
            output.gamut_coverage = metrics.get("coverage_percent", 0.0)
            output.gamut_area_ratio = metrics.get("area_ratio_percent", 0.0)

    def _calculate_white_point_metrics(
        self,
        input_data: ValidationInput,
        output: ValidationOutput
    ) -> None:
        """
        计算白点指标 (CCT, Duv)

        Args:
            input_data: 输入数据
            output: 输出对象 (会被修改)
        """
        if "white" not in input_data.gamut_data:
            return

        white_point = input_data.gamut_data["white"]
        x, y = white_point.xy

        # 计算 CCT 和 Duv
        cct, duv = cct_duv_from_xy(x, y)
        output.white_point_cct = cct
        output.white_point_duv = duv

        # 计算白点误差 (相对于目标白点)
        target_white = get_white_point_xy(input_data.target_white_point)

        # u'v' 色差
        def xy_to_uv_prime(x, y):
            denom = -2 * x + 12 * y + 3
            if denom == 0:
                return (0, 0)
            return (4 * x / denom, 9 * y / denom)

        measured_uv = xy_to_uv_prime(x, y)
        target_uv = xy_to_uv_prime(target_white[0], target_white[1])

        delta_u = measured_uv[0] - target_uv[0]
        delta_v = measured_uv[1] - target_uv[1]

        # ΔE = 13 * sqrt(Δu'² + Δv'²)
        output.white_point_error = 13 * math.sqrt(delta_u ** 2 + delta_v ** 2)

    def _calculate_luminance_metrics(
        self,
        input_data: ValidationInput,
        output: ValidationOutput
    ) -> None:
        """
        计算亮度/对比度指标

        Args:
            input_data: 输入数据
            output: 输出对象 (会被修改)
        """
        if "white" in input_data.gamut_data:
            output.peak_luminance = input_data.gamut_data["white"].Y

        if "black" in input_data.gamut_data:
            output.black_luminance = input_data.gamut_data["black"].Y

        # 计算对比度
        if output.black_luminance > 0:
            output.contrast_ratio = output.peak_luminance / output.black_luminance

    def _evaluate_pass_fail(
        self,
        input_data: ValidationInput,
        output: ValidationOutput,
        threshold: ValidationThreshold
    ) -> None:
        """
        执行合格判定

        Args:
            input_data: 输入数据
            output: 输出对象 (会被修改)
            threshold: 验证阈值
        """
        passed_checks = []
        failed_checks = []

        # 1. Delta E 判定
        if output.delta_e_avg > 0:
            passed, reason = threshold.is_delta_e_passed(output.delta_e_avg, output.delta_e_max)
            output.pass_fail["delta_e"] = PassFailResult(
                metric_name="Delta E 平均",
                value=output.delta_e_avg,
                threshold=threshold.delta_e_avg_threshold,
                passed=passed,
                reason=reason,
            )
            if passed:
                passed_checks.append("delta_e")
            else:
                failed_checks.append("delta_e")

        # 2. 白点判定
        cct_offset = output.white_point_cct - 6500.0
        passed, reason = threshold.is_white_point_passed(cct_offset, output.white_point_duv)
        output.pass_fail["white_point"] = PassFailResult(
            metric_name="白点",
            value=output.white_point_duv,
            threshold=threshold.white_point_duv_tolerance,
            passed=passed,
            reason=reason,
        )
        if passed:
            passed_checks.append("white_point")
        else:
            failed_checks.append("white_point")

        # 3. Gamma 判定
        if output.gamma_avg:
            gamma_offset = abs(output.gamma_avg - input_data.target_gamma)
            passed, reason = threshold.is_gamma_passed(gamma_offset)
            output.pass_fail["gamma"] = PassFailResult(
                metric_name="Gamma",
                value=output.gamma_avg,
                threshold=threshold.gamma_tolerance,
                passed=passed,
                reason=reason,
            )
            if passed:
                passed_checks.append("gamma")
            else:
                failed_checks.append("gamma")

        # 4. 色域判定
        passed, reason = threshold.is_gamut_passed(output.gamut_coverage, output.gamut_area_ratio)
        output.pass_fail["gamut"] = PassFailResult(
            metric_name="色域覆盖率",
            value=output.gamut_coverage,
            threshold=threshold.gamut_coverage_threshold,
            passed=passed,
            reason=reason,
        )
        if passed:
            passed_checks.append("gamut")
        else:
            failed_checks.append("gamut")

        # 综合判定
        if len(failed_checks) == 0:
            output.overall_status = "PASSED"
            output.overall_summary = f"所有指标合格 ({len(passed_checks)}项通过)"
        elif len(failed_checks) <= 2:
            output.overall_status = "WARNING"
            output.overall_summary = f"{len(failed_checks)}项不合格: {', '.join(failed_checks)}"
        else:
            output.overall_status = "FAILED"
            output.overall_summary = f"{len(failed_checks)}项不合格: {', '.join(failed_checks)}"


# ==============================================================================
# 统一验收层便捷函数
# ==============================================================================

def validate_from_input(input_data: ValidationInput) -> ValidationOutput:
    """
    统一验收便捷函数 - 所有 workflow 的共同验收入口

    Args:
        input_data: ValidationInput 包含目标色彩空间、测量数据等

    Returns:
        ValidationOutput: 统一的验证输出 JSON

    Example:
        >>> input = ValidationInput(
        ...     workflow_type=WorkflowType.ICC_PROFILE,
        ...     target_color_space="sRGB",
        ...     measured_samples=[...],
        ...     grayscale_data=[...],
        ...     gamut_data={"red": ..., "green": ..., "blue": ..., "white": ...},
        ...     applied_profile_path="/path/to/profile.icc",
        ... )
        >>> output = validate_from_input(input)
        >>> report_generator.generate_from_validation_output(output)
    """
    service = ValidationWorkflowService(input_data.target_color_space)
    return service.validate_from_input(input_data)


# ==============================================================================
# 辅助函数
# ==============================================================================

def calculate_target_xyY_for_rgb(
    rgb: Tuple[int, int, int],
    standard: str = "sRGB"
) -> Tuple[float, float, float]:
    """
    计算 RGB 对应的目标 xyY 值

    Args:
        rgb: RGB 值 (0-255)
        standard: 目标标准

    Returns:
        Tuple[float, float, float]: 目标 xyY
    """
    # 简化实现：使用 sRGB 转换
    # 完整实现需要考虑不同标准的 primaries
    from src.color_science import srgb_to_xyz, xyz_to_xyY

    # 归一化 RGB
    r, g, b = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0

    # sRGB 线性化
    def srgb_linearize(v):
        if v <= 0.04045:
            return v / 12.92
        else:
            return ((v + 0.055) / 1.055) ** 2.4

    r_lin = srgb_linearize(r)
    g_lin = srgb_linearize(g)
    b_lin = srgb_linearize(b)

    # 转换到 XYZ (Y=100 归一化)
    X, Y, Z = srgb_to_xyz(int(rgb[0]), int(rgb[1]), int(rgb[2]))
    Y_normalized = Y / 100.0 * 100.0  # 保持 Y 范围

    # 转换到 xyY
    x = X / (X + Y_normalized + Z) if (X + Y_normalized + Z) > 0 else 0.3127
    y = Y_normalized / (X + Y_normalized + Z) if (X + Y_normalized + Z) > 0 else 0.3290

    return (x, y, Y_normalized)
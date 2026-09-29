"""
LUT Workflow - 1D/3D LUT generation workflow for color calibration.

This workflow implements the LUT creation pipeline:
- Define source color space (Rec.709, sRGB, Display P3, DCI-P3, Rec.2020 PQ/HLG)
- Validate measurement data density before LUT generation
- Generate ICC profile from measured data (or use existing ICC)
- Create 1D/3D LUT via collink (ArgyllCMS)
- Run validation patch set after LUT generation
- Record all parameters and results in manifest

Key features:
- Support 1D LUT (VCGT) and 3D LUT
- Grid sizes: 17, 21, 33, 65 (17/21 basic, 33/65 advanced)
- Interpolation: trilinear, tetrahedral
- Target spaces: sRGB, Rec.709, P3-D65, BT.2020, HDR PQ
- Measurement density validation (warn if insufficient)
- Automatic validation patch set after LUT generation
- Export to .cube format
- Manifest recording with measurement hash and validation results

Reference:
- docs/agent_handoffs/P4-A_argyll_adapter_refactor.md (CollinkParams)
- docs/agent_handoffs/P2-A_color_science_module.md (color spaces)
- docs/professional_optimization_plan.md (P4-C requirements)
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from src.instruments.argyll_params import (
    CollinkParams,
    ColprofParams,
    RenderingIntent,
    QualityLevel,
    map_error_to_suggestion,
)
from src.color_science import (
    WHITE_POINTS,
    COLOR_SPACES,
    get_white_point_xy,
)
from src.storage.manifest import (
    ArtifactManifest,
    ManifestEntry,
    generate_manifest,
    save_manifest,
    compute_file_hash,
)


logger = logging.getLogger(__name__)


# ==============================================================================
# LUT 类型定义
# ==============================================================================

class LUTType(Enum):
    """
    LUT 类型 - 1D 或 3D

    - 1D: 单通道 LUT，用于灰阶/色阶调整（VCGT）
    - 3D: 三通道 LUT，用于完整的色彩空间映射
    """
    LUT1D = "1d"  # 1D LUT (灰阶/色阶)
    LUT3D = "3d"  # 3D LUT (色彩空间映射)


class InterpolationMethod(Enum):
    """
    插值方法 - 用于 LUT 应用时的采样

    - Trilinear: 三线性插值，速度快，精度一般
    - Tetrahedral: 四面体插值，精度高，速度稍慢
    """
    TRILINEAR = "trilinear"
    TETRAHEDRAL = "tetrahedral"


class GridSize(Enum):
    """
    LUT Grid 尺寸

    - SIZE_17: 快速预览，文件小，精度低（基础选项）
    - SIZE_21: 平衡预览，文件适中（基础选项）
    - SIZE_33: 推荐，平衡精度和性能
    - SIZE_65: 高精度，文件较大（高级选项）
    """
    SIZE_17 = 17   # 基础选项
    SIZE_21 = 21   # 基础选项
    SIZE_33 = 33   # 推荐
    SIZE_65 = 65   # 高级选项


class TargetSpace(Enum):
    """
    目标色彩空间 - LUT 映射的目标空间

    包含 SDR 和 HDR 目标空间：
    - SRGB: 计算机显示器标准
    - REC709: 视频校准标准 (BT.709 + BT.1886)
    - P3_D65: Apple Display P3，D65 白点
    - BT2020: Rec.2020 SDR 广色域
    - HDR_PQ: Rec.2020 + SMPTE ST 2084 PQ EOTF
    - HDR_HLG: Rec.2020 + Hybrid Log-Gamma
    """
    SRGB = "sRGB"
    REC709 = "Rec709"
    P3_D65 = "P3-D65"
    BT2020 = "BT.2020"
    HDR_PQ = "HDR_PQ"
    HDR_HLG = "HDR_HLG"


# Grid 尺寸到类别映射
GRID_SIZE_CATEGORY = {
    GridSize.SIZE_17: "basic",
    GridSize.SIZE_21: "basic",
    GridSize.SIZE_33: "recommended",
    GridSize.SIZE_65: "advanced",
}

# 推荐的测量点密度阈值（根据 LUT 类型和 Grid 尺寸）
MIN_MEASUREMENT_DENSITY = {
    LUTType.LUT1D: {
        GridSize.SIZE_17: 50,
        GridSize.SIZE_21: 50,
        GridSize.SIZE_33: 100,
        GridSize.SIZE_65: 200,
    },
    LUTType.LUT3D: {
        GridSize.SIZE_17: 200,
        GridSize.SIZE_21: 300,
        GridSize.SIZE_33: 500,
        GridSize.SIZE_65: 1000,
    },
}


# ==============================================================================
# 源色彩空间预设定义
# ==============================================================================

class SourceSpacePreset(Enum):
    """
    源色彩空间预设 - 用于 3D LUT 制作时的源空间定义。

    每个预设包含完整的色彩空间信息：
    - primaries: RGB primaries xy 坐标
    - white_point: 白点名称
    - transfer_function: 传递函数类型
    - ArgyllCMS ICC 映射: 对应的 ArgyllCMS/ref 目录 ICC 文件
    """
    # Rec.709 Gamma 2.4 (BT.709 + BT.1886，视频校准标准)
    REC709_GAMMA24 = "Rec709_Gamma24"

    # sRGB (IEC 61966-2-1，计算机显示器标准)
    SRGB = "sRGB"

    # Display P3 (Apple P3，D65 白点)
    DISPLAY_P3 = "DisplayP3"

    # DCI-P3 (SMPTE RP 431-2，D60 白点，影院标准)
    DCI_P3 = "DCI-P3"

    # Rec.2020 PQ (BT.2100 HDR，SMPTE ST 2084 EOTF)
    REC2020_PQ = "Rec2020_PQ"

    # Rec.2020 HLG (BT.2100 HDR，Hybrid Log-Gamma)
    REC2020_HLG = "Rec2020_HLG"

    # Rec.2020 Gamma 2.4 (SDR 广色域)
    REC2020_GAMMA24 = "Rec2020_Gamma24"


class TransferFunctionType(Enum):
    """传递函数类型"""
    GAMMA_22 = "gamma22"
    GAMMA_24 = "gamma24"
    SRGB = "sRGB"
    BT1886 = "bt1886"
    PQ = "pq"        # SMPTE ST 2084
    HLG = "hlg"      # Hybrid Log-Gamma
    LINEAR = "linear"


@dataclass
class SourceSpaceDefinition:
    """
    源色彩空间的完整定义。

    Attributes:
        name: 显示名称
        preset: 预设类型
        primaries_name: primaries 名称（如 "Rec709", "P3", "Rec2020"）
        white_point: 白点名称（如 "D65", "D60"）
        gamma: Gamma 值（对于 Gamma 曲线）
        transfer_function: 传递函数类型
        argyll_icc_name: ArgyllCMS/ref 目录中的 ICC 文件名
        description: 详细描述
    """
    name: str
    preset: SourceSpacePreset
    primaries_name: str
    white_point: str
    gamma: Optional[float] = None
    transfer_function: TransferFunctionType = TransferFunctionType.GAMMA_24
    argyll_icc_name: str = ""
    description: str = ""

    @property
    def white_point_xy(self) -> Tuple[float, float]:
        """获取白点 xy 坐标"""
        return get_white_point_xy(self.white_point)


# 源色彩空间预设完整定义
SOURCE_SPACE_DEFINITIONS: Dict[SourceSpacePreset, SourceSpaceDefinition] = {
    SourceSpacePreset.REC709_GAMMA24: SourceSpaceDefinition(
        name="Rec.709 Gamma 2.4",
        preset=SourceSpacePreset.REC709_GAMMA24,
        primaries_name="Rec709",
        white_point="D65",
        gamma=2.4,
        transfer_function=TransferFunctionType.BT1886,
        argyll_icc_name="Rec709.icm",
        description="BT.709 色域 + BT.1886 Gamma 2.4，视频校准标准"
    ),

    SourceSpacePreset.SRGB: SourceSpaceDefinition(
        name="sRGB",
        preset=SourceSpacePreset.SRGB,
        primaries_name="sRGB",
        white_point="D65",
        gamma=None,  # sRGB 使用分段曲线，不是纯 Gamma
        transfer_function=TransferFunctionType.SRGB,
        argyll_icc_name="sRGB.icm",
        description="IEC 61966-2-1 sRGB，计算机显示器和网页标准"
    ),

    SourceSpacePreset.DISPLAY_P3: SourceSpaceDefinition(
        name="Display P3",
        preset=SourceSpacePreset.DISPLAY_P3,
        primaries_name="P3",
        white_point="D65",
        gamma=2.2,  # Apple Display P3 使用 Gamma 2.2
        transfer_function=TransferFunctionType.GAMMA_22,
        argyll_icc_name="DisplayP3.icm",
        description="Apple Display P3，D65 白点，广色域显示器标准"
    ),

    SourceSpacePreset.DCI_P3: SourceSpaceDefinition(
        name="DCI-P3",
        preset=SourceSpacePreset.DCI_P3,
        primaries_name="P3",
        white_point="D60",  # DCI-P3 使用 D60 白点
        gamma=2.6,  # DCI-P3 使用 Gamma 2.6
        transfer_function=TransferFunctionType.GAMMA_24,
        argyll_icc_name="SMPTE431_P3.icm",
        description="SMPTE RP 431-2 DCI-P3，D60 白点，影院投影标准"
    ),

    SourceSpacePreset.REC2020_PQ: SourceSpaceDefinition(
        name="Rec.2020 PQ",
        preset=SourceSpacePreset.REC2020_PQ,
        primaries_name="Rec2020",
        white_point="D65",
        gamma=None,
        transfer_function=TransferFunctionType.PQ,
        argyll_icc_name="Rec2020.icm",
        description="BT.2100 HDR，Rec.2020 色域 + SMPTE ST 2084 PQ EOTF"
    ),

    SourceSpacePreset.REC2020_HLG: SourceSpaceDefinition(
        name="Rec.2020 HLG",
        preset=SourceSpacePreset.REC2020_HLG,
        primaries_name="Rec2020",
        white_point="D65",
        gamma=None,
        transfer_function=TransferFunctionType.HLG,
        argyll_icc_name="Rec2020.icm",
        description="BT.2100 HDR，Rec.2020 色域 + Hybrid Log-Gamma OETF"
    ),

    SourceSpacePreset.REC2020_GAMMA24: SourceSpaceDefinition(
        name="Rec.2020 Gamma 2.4",
        preset=SourceSpacePreset.REC2020_GAMMA24,
        primaries_name="Rec2020",
        white_point="D65",
        gamma=2.4,
        transfer_function=TransferFunctionType.BT1886,
        argyll_icc_name="Rec2020.icm",
        description="BT.2020 色域 + BT.1886 Gamma 2.4，SDR 广色域"
    ),
}


# ==============================================================================
# LUT 规格定义（使用新的 GridSize）
# ==============================================================================

# 保留旧的 LUTSize 作为别名（兼容性）
LUTSize = GridSize


class LUTFormat(Enum):
    """LUT 输出格式"""
    CUBE = "cube"   # Resolve .cube 格式（主要支持）
    # 后续扩展格式：
    # MADVR = "madvr"  # madVR 格式
    # DISPLAYCAL = "3dl"  # DisplayCAL .3dl 格式


@dataclass
class LUTSpec:
    """
    LUT 规格定义。

    Attributes:
        lut_type: LUT 类型（1D 或 3D）
        size: Grid 尺寸（17、21、33、65）
        format: 输出格式（.cube）
        interpolation: 插值方法
        input_range: 输入范围 ("full" 0-255 或 "limited" 16-235)
    """
    lut_type: LUTType = LUTType.LUT3D
    size: GridSize = GridSize.SIZE_33
    format: LUTFormat = LUTFormat.CUBE
    interpolation: InterpolationMethod = InterpolationMethod.TRILINEAR
    input_range: str = "full"  # "full" 或 "limited"

    def get_min_measurement_count(self) -> int:
        """
        获取此规格所需的最小测量点数

        Returns:
            int: 最小测量点数
        """
        return MIN_MEASUREMENT_DENSITY.get(self.lut_type, {}).get(self.size, 500)

    def get_category(self) -> str:
        """
        获取 Grid 尺寸类别（basic/recommended/advanced）

        Returns:
            str: 类别名称
        """
        return GRID_SIZE_CATEGORY.get(self.size, "recommended")


# ==============================================================================
# LUT 工作流配置
# ==============================================================================

@dataclass
class LUTWorkflowConfig:
    """
    LUT 工作流配置。

    Attributes:
        lut_type: LUT 类型（1D 或 3D）
        source_space: 源色彩空间预设
        target_space: 目标色彩空间
        target_icc_path: 目标 ICC Profile 路径（实测 ICC 或指定 ICC）
        output_path: 输出 .cube 文件路径
        lut_spec: LUT 规格定义（grid size、interpolation、format）
        intent: 渲染意图
        use_bpc: 黑场补偿
        argyll_path: ArgyllCMS bin 目录路径
        session_dir: 工作流会话目录（存放中间文件）
        measurement_data_path: 输入测量数据路径（用于 hash 计算）
        auto_validate: LUT 生成后自动运行 validation
        validation_patch_count: 验证色块数量
    """
    lut_type: LUTType = LUTType.LUT3D
    source_space: SourceSpacePreset = SourceSpacePreset.REC709_GAMMA24
    target_space: TargetSpace = TargetSpace.REC709
    target_icc_path: str = ""
    output_path: str = ""
    lut_spec: LUTSpec = field(default_factory=LUTSpec)
    intent: RenderingIntent = RenderingIntent.RELATIVE_COLORIMETRIC
    use_bpc: bool = True
    argyll_path: str = ""
    session_dir: str = ""
    measurement_data_path: str = ""
    auto_validate: bool = True  # LUT 生成后自动验证
    validation_patch_count: int = 50  # 验证色块数量

    def get_source_definition(self) -> SourceSpaceDefinition:
        """获取源色彩空间定义"""
        return SOURCE_SPACE_DEFINITIONS[self.source_space]

    def validate(self) -> Tuple[bool, str]:
        """
        验证配置参数。

        Returns:
            Tuple[bool, str]: (是否有效, 错误消息)
        """
        # 检查目标 ICC 文件
        if not self.target_icc_path:
            return (False, "目标 ICC Profile 路径未指定")
        if not os.path.exists(self.target_icc_path):
            return (False, f"目标 ICC 文件不存在: {self.target_icc_path}")

        # 检查输出路径
        if not self.output_path:
            return (False, "输出路径未指定")

        # 检查 BPC + intent 参数组合
        if self.intent == RenderingIntent.PERCEPTUAL and self.use_bpc:
            # 感知意图不支持 BPC，自动禁用
            return (True, "警告: 感知意图自动禁用 BPC")

        # 检查 LUT 尺寸
        valid_sizes = [GridSize.SIZE_17, GridSize.SIZE_21, GridSize.SIZE_33, GridSize.SIZE_65]
        if self.lut_spec.size not in valid_sizes:
            return (False, f"无效的 LUT 尺寸: {self.lut_spec.size}")

        # 检查测量数据路径（如果指定）
        if self.measurement_data_path and not os.path.exists(self.measurement_data_path):
            return (False, f"测量数据文件不存在: {self.measurement_data_path}")

        return (True, "")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 manifest 记录）"""
        return {
            "lut_type": self.lut_type.value,
            "source_space": self.source_space.value,
            "target_space": self.target_space.value,
            "target_icc_path": self.target_icc_path,
            "output_path": self.output_path,
            "lut_spec": {
                "size": self.lut_spec.size.value,
                "format": self.lut_spec.format.value,
                "interpolation": self.lut_spec.interpolation.value,
                "input_range": self.lut_spec.input_range,
                "category": self.lut_spec.get_category(),
            },
            "intent": self.intent.value,
            "use_bpc": self.use_bpc,
            "auto_validate": self.auto_validate,
            "validation_patch_count": self.validation_patch_count,
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """从字典加载"""
        self.lut_type = LUTType(data.get("lut_type", "3d"))
        self.source_space = SourceSpacePreset(data.get("source_space", "Rec709_Gamma24"))
        self.target_space = TargetSpace(data.get("target_space", "Rec709"))
        self.target_icc_path = data.get("target_icc_path", "")
        self.output_path = data.get("output_path", "")

        spec_data = data.get("lut_spec", {})
        self.lut_spec = LUTSpec(
            lut_type=self.lut_type,
            size=GridSize(spec_data.get("size", 33)),
            format=LUTFormat(spec_data.get("format", "cube")),
            interpolation=InterpolationMethod(spec_data.get("interpolation", "trilinear")),
            input_range=spec_data.get("input_range", "full"),
        )

        self.intent = RenderingIntent(data.get("intent", "r"))
        self.use_bpc = data.get("use_bpc", True)
        self.auto_validate = data.get("auto_validate", True)
        self.validation_patch_count = data.get("validation_patch_count", 50)


# ==============================================================================
# 测量点密度校验
# ==============================================================================

@dataclass
class DensityCheckResult:
    """
    测量点密度校验结果

    Attributes:
        sufficient: 是否足够
        measurement_count: 实际测量点数
        required_count: 最小要求点数
        recommendation: 建议（如需补测）
        deficit: 缺少的点数
    """
    sufficient: bool = True
    measurement_count: int = 0
    required_count: int = 0
    recommendation: str = ""
    deficit: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "sufficient": self.sufficient,
            "measurement_count": self.measurement_count,
            "required_count": self.required_count,
            "recommendation": self.recommendation,
            "deficit": self.deficit,
        }

    def to_json(self) -> str:
        """转换为 JSON"""
        return json.dumps(self.to_dict(), indent=2)


def check_measurement_density(
    measurement_count: int,
    lut_spec: LUTSpec,
    strict: bool = False
) -> DensityCheckResult:
    """
    检查测量点密度是否足够生成指定规格的 LUT

    Args:
        measurement_count: 实际测量点数
        lut_spec: LUT 规格
        strict: 是否严格检查（不足时返回 False 并阻断）

    Returns:
        DensityCheckResult: 校验结果

    Note:
        sufficient 字段表示测量点是否充足。
        在非严格模式下，即使不足也返回 sufficient=False，
        但用户可以选择继续生成（只是会有警告）。
    """
    required = lut_spec.get_min_measurement_count()

    if measurement_count >= required:
        return DensityCheckResult(
            sufficient=True,
            measurement_count=measurement_count,
            required_count=required,
            recommendation="测量点数充足，可以生成 LUT",
            deficit=0,
        )

    deficit = required - measurement_count
    recommendation = (
        f"测量点数不足（当前 {measurement_count}，需要至少 {required}）\n"
        f"建议补测 {deficit} 个色块以确保 LUT 精度\n"
        f"或降低 Grid 尺寸（如从 {lut_spec.size.value} 改为 {GridSize.SIZE_17.value})"
    )

    # sufficient 表示是否充足（用于 UI 显示警告）
    # strict 模式下阻断，非严格模式下允许继续但有警告
    return DensityCheckResult(
        sufficient=False,  # 标记为不足
        measurement_count=measurement_count,
        required_count=required,
        recommendation=recommendation,
        deficit=deficit,
    )


# ==============================================================================
# LUT 生成报告（含验证结果）
# ==============================================================================

@dataclass
class LUTValidationResult:
    """
    LUT 验证结果

    Attributes:
        validated: 是否已验证
        patch_count: 验证色块数
        delta_e_avg: 平均 Delta E
        delta_e_max: 最大 Delta E
        delta_e_95: 95% Delta E
        passed: 是否合格
        details: 详细结果（before/after 对比）
    """
    validated: bool = False
    patch_count: int = 0
    delta_e_avg: float = 0.0
    delta_e_max: float = 0.0
    delta_e_95: float = 0.0
    passed: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "validated": self.validated,
            "patch_count": self.patch_count,
            "delta_e_avg": self.delta_e_avg,
            "delta_e_max": self.delta_e_max,
            "delta_e_95": self.delta_e_95,
            "passed": self.passed,
            "details": self.details,
        }


@dataclass
class LUTGenerationReport:
    """
    LUT 生成报告。

    包含完整的 LUT 元数据：
    - 源空间信息
    - 目标空间信息
    - 渲染参数
    - LUT 规格
    - 生成时间和状态
    - 测量数据 hash
    - 验证结果

    Attributes:
        source_space_name: 源色彩空间名称
        source_primaries: 源 primaries 名称
        source_white_point: 源白点
        source_transfer_function: 源传递函数
        target_icc_path: 目标 ICC 路径
        target_icc_name: 目标 ICC 名称
        target_space: 目标色彩空间
        intent: 渲染意图
        use_bpc: 是否启用 BPC
        lut_type: LUT 类型（1D/3D）
        lut_size: LUT 尺寸
        lut_format: LUT 格式
        interpolation: 插值方法
        output_path: 输出文件路径
        file_size_bytes: 文件大小
        generated_at: 生成时间
        generation_time_ms: 生成耗时（毫秒）
        success: 是否成功
        error_message: 错误消息
        argyll_version: ArgyllCMS 版本
        collink_command: 执行的 collink 命令
        measurement_hash: 测量数据 hash
        measurement_count: 测量点数
        density_check: 测量密度校验结果
        validation_result: 验证结果
        manifest_path: manifest 文件路径
    """
    source_space_name: str = ""
    source_primaries: str = ""
    source_white_point: str = ""
    source_transfer_function: str = ""
    target_icc_path: str = ""
    target_icc_name: str = ""
    target_space: str = ""
    intent: str = ""
    use_bpc: bool = True
    lut_type: str = "3d"
    lut_size: int = 33
    lut_format: str = "cube"
    interpolation: str = "trilinear"
    output_path: str = ""
    file_size_bytes: int = 0
    generated_at: str = ""
    generation_time_ms: int = 0
    success: bool = False
    error_message: str = ""
    argyll_version: str = ""
    collink_command: str = ""
    measurement_hash: str = ""
    measurement_count: int = 0
    density_check: Dict[str, Any] = field(default_factory=dict)
    validation_result: LUTValidationResult = field(default_factory=LUTValidationResult)
    manifest_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "source_space": {
                "name": self.source_space_name,
                "primaries": self.source_primaries,
                "white_point": self.source_white_point,
                "transfer_function": self.source_transfer_function,
            },
            "target_space": {
                "icc_path": self.target_icc_path,
                "icc_name": self.target_icc_name,
                "target_space": self.target_space,
            },
            "rendering": {
                "intent": self.intent,
                "use_bpc": self.use_bpc,
            },
            "lut_spec": {
                "lut_type": self.lut_type,
                "size": self.lut_size,
                "format": self.lut_format,
                "interpolation": self.interpolation,
            },
            "output": {
                "path": self.output_path,
                "file_size_bytes": self.file_size_bytes,
            },
            "generation": {
                "generated_at": self.generated_at,
                "generation_time_ms": self.generation_time_ms,
                "success": self.success,
                "error_message": self.error_message,
                "argyll_version": self.argyll_version,
                "collink_command": self.collink_command,
            },
            "measurement": {
                "hash": self.measurement_hash,
                "count": self.measurement_count,
                "density_check": self.density_check,
            },
            "validation": self.validation_result.to_dict(),
            "manifest_path": self.manifest_path,
        }

    def to_json_string(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


# ==============================================================================
# LUT 工作流状态
# ==============================================================================

class LUTWorkflowState(Enum):
    """LUT 工作流状态"""
    IDLE = "idle"
    CHECKING_DENSITY = "checking_density"  # 测量点密度校验
    VALIDATING_CONFIG = "validating_config"
    GENERATING_PROFILE = "generating_profile"
    GENERATING_LUT = "generating_lut"
    VALIDATING_LUT = "validating_lut"      # LUT 格式验证
    RUNNING_VALIDATION = "running_validation"  # 运行验证测量
    COMPLETED = "completed"
    FAILED = "failed"
    SUSPENDED = "suspended"  # 暂停（可恢复）
    CANCELLED = "cancelled"  # 取消（不可恢复）


# ==============================================================================
# LUT 工作流 Session
# ==============================================================================

@dataclass
class LUTWorkflowSession:
    """
    LUT 工作流 Session 状态

    用于 checkpoint/recovery 和 manifest 记录
    """
    session_id: str = ""
    config: LUTWorkflowConfig = field(default_factory=LUTWorkflowConfig)
    state: LUTWorkflowState = LUTWorkflowState.IDLE

    # 进度追踪
    current_step: str = ""
    progress_percent: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # 文件路径
    icc_file: Optional[str] = None
    lut_file: Optional[str] = None
    manifest_file: Optional[str] = None

    # 测量信息
    measurement_count: int = 0
    measurement_hash: str = ""

    # 验证结果
    validation_done: bool = False
    validation_results: Dict[str, Any] = field(default_factory=dict)

    # 错误追踪
    last_error: Optional[str] = None
    recoverable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """序列化到字典"""
        return {
            "session_id": self.session_id,
            "config": self.config.to_dict(),
            "state": self.state.value,
            "current_step": self.current_step,
            "progress_percent": self.progress_percent,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "icc_file": self.icc_file,
            "lut_file": self.lut_file,
            "manifest_file": self.manifest_file,
            "measurement_count": self.measurement_count,
            "measurement_hash": self.measurement_hash,
            "validation_done": self.validation_done,
            "validation_results": self.validation_results,
            "last_error": self.last_error,
            "recoverable": self.recoverable,
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """从字典加载"""
        self.session_id = data.get("session_id", "")
        self.config.from_dict(data.get("config", {}))
        self.state = LUTWorkflowState(data.get("state", "idle"))
        self.current_step = data.get("current_step", "")
        self.progress_percent = data.get("progress_percent", 0)

        started = data.get("started_at")
        if started:
            self.started_at = datetime.fromisoformat(started)
        completed = data.get("completed_at")
        if completed:
            self.completed_at = datetime.fromisoformat(completed)

        self.icc_file = data.get("icc_file")
        self.lut_file = data.get("lut_file")
        self.manifest_file = data.get("manifest_file")
        self.measurement_count = data.get("measurement_count", 0)
        self.measurement_hash = data.get("measurement_hash", "")
        self.validation_done = data.get("validation_done", False)
        self.validation_results = data.get("validation_results", {})
        self.last_error = data.get("last_error")
        self.recoverable = data.get("recoverable", True)


# ==============================================================================
# LUT 工作流核心类
# ==============================================================================

class LUTWorkflow:
    """
    1D/3D LUT 生成工作流。

    主要流程：
    1. 校验测量点密度
    2. 验证配置参数（源空间、目标 ICC、BPC/intent）
    3. 获取源色彩空间 ICC 文件（ArgyllCMS/ref 目录）
    4. 执行 collink 命令生成 LUT
    5. 验证生成的 .cube 文件格式
    6. 自动运行验证色块集（可选）
    7. 生成元数据报告和 manifest

    使用示例：
        >>> config = LUTWorkflowConfig(
        ...     source_space=SourceSpacePreset.REC709_GAMMA24,
        ...     target_icc_path="/path/to/measured.icc",
        ...     output_path="/path/to/output.cube",
        ...     lut_spec=LUTSpec(size=GridSize.SIZE_33),
        ...     measurement_count=600,
        ... )
        >>> workflow = LUTWorkflow(config)
        >>> success, report = workflow.generate()
        >>> if success:
        ...     print(report.to_json_string())

    Thread Safety:
        此类不是线程安全的。在 Qt 应用中，确保所有操作在主线程执行。
    """

    # 性能上限（验收标准）
    MAX_GENERATION_TIME_MS = 30000  # 30 秒

    def __init__(
        self,
        config: LUTWorkflowConfig,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_state_change: Optional[Callable[[LUTWorkflowState, LUTWorkflowState], None]] = None,
        on_validation_request: Optional[Callable[[List[Tuple[int, int, int, str]]], None]] = None,
        on_completed: Optional[Callable[[LUTGenerationReport], None]] = None,
    ):
        """
        初始化 LUT 工作流。

        Args:
            config: LUT 工作流配置
            on_progress: 进度回调 (current, total, message)
            on_status: 状态消息回调
            on_state_change: 状态变化回调 (old_state, new_state)
            on_validation_request: 验证请求回调（传入验证色块列表）
            on_completed: 完成回调（传入生成报告）
        """
        self._config = config
        self._on_progress = on_progress
        self._on_status = on_status
        self._on_state_change = on_state_change
        self._on_validation_request = on_validation_request
        self._on_completed = on_completed

        self._state = LUTWorkflowState.IDLE
        self._report: Optional[LUTGenerationReport] = None
        self._session: Optional[LUTWorkflowSession] = None
        self._session_dir: Optional[Path] = None
        self._start_time: Optional[float] = None

        # 进程管理
        self._current_process: Optional[subprocess.Popen] = None
        self._cancelled: bool = False

    @property
    def state(self) -> LUTWorkflowState:
        """获取当前状态"""
        return self._state

    @property
    def report(self) -> Optional[LUTGenerationReport]:
        """获取生成报告"""
        return self._report

    @property
    def session(self) -> Optional[LUTWorkflowSession]:
        """获取当前 session"""
        return self._session

    @property
    def session_dir(self) -> Optional[Path]:
        """获取 session 目录"""
        return self._session_dir

    def _notify_progress(self, current: int, total: int, message: str) -> None:
        """通知进度"""
        if self._session:
            self._session.progress_percent = int(current * 100 / total) if total > 0 else 0
            self._session.current_step = message
        if self._on_progress:
            self._on_progress(current, total, message)

    def _notify_status(self, message: str) -> None:
        """通知状态"""
        if self._on_status:
            self._on_status(message)
        logger.info(message)

    def _notify_state_change(self, old_state: LUTWorkflowState, new_state: LUTWorkflowState) -> None:
        """通知状态变化"""
        logger.info(f"LUT Workflow state: {old_state.value} -> {new_state.value}")
        if self._on_state_change:
            try:
                self._on_state_change(old_state, new_state)
            except Exception as e:
                logger.error(f"State change callback error: {e}")

    def _set_state(self, state: LUTWorkflowState) -> None:
        """设置状态"""
        old_state = self._state
        self._state = state
        if self._session:
            self._session.state = state
        self._notify_state_change(old_state, state)
        self._notify_status(f"状态: {state.value}")

    def start(self, measurement_count: int = 0, measurement_path: str = "") -> LUTWorkflowSession:
        """
        启动 LUT 工作流

        Args:
            measurement_count: 测量点数（用于密度校验）
            measurement_path: 测量数据路径（用于 hash 计算）

        Returns:
            LUTWorkflowSession: 创建的 session
        """
        if self._state != LUTWorkflowState.IDLE:
            raise RuntimeError(f"Workflow already active: {self._state.value}")

        # 创建 session
        session_id = f"lut-{datetime.now().strftime('%Y%m%d_%H%M%S')}-{os.urandom(3).hex()}"
        self._session = LUTWorkflowSession(
            session_id=session_id,
            config=self._config,
            state=LUTWorkflowState.IDLE,
            started_at=datetime.now(),
            measurement_count=measurement_count,
        )

        # 创建 session 目录
        if self._config.session_dir:
            self._session_dir = Path(self._config.session_dir)
        else:
            project_root = Path(__file__).parent.parent.parent
            sessions_dir = project_root / "measurements" / "lut_sessions"
            self._session_dir = sessions_dir / session_id

        self._session_dir.mkdir(parents=True, exist_ok=True)

        # 计算测量 hash（如果提供了路径）
        if measurement_path and os.path.exists(measurement_path):
            self._session.measurement_hash = compute_file_hash(Path(measurement_path))
            self._config.measurement_data_path = measurement_path

        self._start_time = time.time()
        self._set_state(LUTWorkflowState.CHECKING_DENSITY)

        return self._session

    def get_session_info(self) -> Dict[str, Any]:
        """获取 session 信息"""
        if self._session:
            return self._session.to_dict()
        return {"state": self._state.value, "session_id": None}

    def pause(self) -> bool:
        """暂停工作流（保存 checkpoint）"""
        if self._state in [LUTWorkflowState.IDLE, LUTWorkflowState.COMPLETED,
                           LUTWorkflowState.FAILED, LUTWorkflowState.CANCELLED]:
            return False

        # 保存 checkpoint
        if self._session and self._session_dir:
            checkpoint_path = self._session_dir / "checkpoint.json"
            with open(checkpoint_path, 'w', encoding='utf-8') as f:
                json.dump(self._session.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info(f"Checkpoint saved: {checkpoint_path}")

        self._set_state(LUTWorkflowState.SUSPENDED)
        return True

    def resume(self, session_dir: Path) -> LUTWorkflowSession:
        """
        从 checkpoint 恢复工作流

        Args:
            session_dir: session 目录路径

        Returns:
            LUTWorkflowSession: 恢复的 session
        """
        checkpoint_path = session_dir / "checkpoint.json"
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"No checkpoint found: {checkpoint_path}")

        with open(checkpoint_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self._session = LUTWorkflowSession()
        self._session.from_dict(data)
        self._session_dir = session_dir

        # 更新 config
        self._config = self._session.config

        self._set_state(LUTWorkflowState.SUSPENDED)
        return self._session

    def cancel(self) -> bool:
        """取消工作流"""
        self._cancelled = True

        # 终止正在运行的进程
        if self._current_process:
            try:
                self._current_process.terminate()
                self._current_process.wait(timeout=5)
            except Exception:
                self._current_process.kill()

        self._set_state(LUTWorkflowState.CANCELLED)
        return True

    def get_source_icc_path(self) -> str:
        """
        获取源色彩空间 ICC 文件路径。

        Returns:
            str: ArgyllCMS/ref 目录中的 ICC 文件路径
        """
        definition = self._config.get_source_definition()
        icc_name = definition.argyll_icc_name

        # 检测 ArgyllCMS ref 目录
        ref_dir = self._find_argyll_ref_dir()

        if ref_dir:
            icc_path = os.path.join(ref_dir, icc_name)
            if os.path.exists(icc_path):
                return icc_path

        # 如果找不到 ref 目录，返回预设名称（collink 可能直接支持）
        return definition.preset.value

    def _find_argyll_ref_dir(self) -> Optional[str]:
        """
        查找 ArgyllCMS ref 目录。

        检测顺序：
        1. PyInstaller 打包环境（sys._MEIPASS）
        2. 已设置的 ArgyllCMS bin 目录
        3. 项目源码目录

        Returns:
            Optional[str]: ref 目录路径，找不到时返回 None
        """
        import sys

        # PyInstaller 打包环境
        if hasattr(sys, '_MEIPASS'):
            pyinstaller_ref = Path(sys._MEIPASS) / "ArgyllCMS" / "ref"
            if pyinstaller_ref.exists():
                return str(pyinstaller_ref)

        # 已设置的 ArgyllCMS bin 目录
        if self._config.argyll_path:
            bin_dir = Path(self._config.argyll_path)
            # ref 目录通常在 bin 的同级或上级
            possible_ref_dirs = [
                bin_dir / "ref",
                bin_dir.parent / "ref",
                bin_dir.parent.parent / "ref",
            ]
            for ref_dir in possible_ref_dirs:
                if ref_dir.exists():
                    return str(ref_dir)

        # 项目源码目录
        project_root = Path(__file__).parent.parent.parent
        project_ref = project_root / "ArgyllCMS" / "ref"
        if project_ref.exists():
            return str(project_ref)

        return None

    def build_collink_command(self) -> List[str]:
        """
        构建 collink 命令参数。

        Returns:
            List[str]: collink 命令参数列表
        """
        # 获取源 ICC 路径
        source_icc = self.get_source_icc_path()

        # 创建 CollinkParams
        params = CollinkParams(
            source_space=source_icc,
            target_icc_path=self._config.target_icc_path,
            output_path=self._config.output_path,
            lut_size=self._config.lut_spec.size.value,
            intent=self._config.intent,
            use_bpc=self._config.use_bpc,
            verbose=True,
        )

        # 使用 CollinkParams.to_command_args() 生成参数
        args = params.to_command_args()

        # 获取 collink 可执行文件路径
        import platform
        system = platform.system()
        collink_name = "collink.exe" if system == "Windows" else "collink"

        if self._config.argyll_path:
            collink_path = str(Path(self._config.argyll_path) / collink_name)
        else:
            collink_path = collink_name

        return [collink_path] + args

    def generate(
        self,
        measurement_count: int = 0,
        measurement_path: str = "",
        skip_density_check: bool = False,
    ) -> Tuple[bool, LUTGenerationReport]:
        """
        执行 LUT 生成工作流。

        流程：
        1. 检查测量点密度
        2. 验证配置参数
        3. 生成 LUT (collink)
        4. 验证 LUT 格式
        5. 自动运行验证色块集
        6. 生成 manifest

        Args:
            measurement_count: 测量点数（用于密度校验）
            measurement_path: 测量数据路径（用于 hash 计算）
            skip_density_check: 是否跳过密度校验

        Returns:
            Tuple[bool, LUTGenerationReport]: (是否成功, 生成报告)
        """
        # 开始计时
        start_time = time.time()

        # 创建 session（如果尚未创建）
        if self._state == LUTWorkflowState.IDLE:
            self.start(measurement_count, measurement_path)

        # 创建报告对象
        definition = self._config.get_source_definition()
        self._report = LUTGenerationReport(
            source_space_name=definition.name,
            source_primaries=definition.primaries_name,
            source_white_point=definition.white_point,
            source_transfer_function=definition.transfer_function.value,
            target_icc_path=self._config.target_icc_path,
            target_icc_name=os.path.basename(self._config.target_icc_path),
            target_space=self._config.target_space.value,
            intent=self._config.intent.value,
            use_bpc=self._config.use_bpc,
            lut_type=self._config.lut_type.value,
            lut_size=self._config.lut_spec.size.value,
            lut_format=self._config.lut_spec.format.value,
            interpolation=self._config.lut_spec.interpolation.value,
            output_path=self._config.output_path,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            measurement_count=measurement_count,
        )

        # 计算测量数据 hash
        if measurement_path and os.path.exists(measurement_path):
            self._report.measurement_hash = compute_file_hash(Path(measurement_path))
            if self._session:
                self._session.measurement_hash = self._report.measurement_hash

        try:
            # 1. 检查测量点密度（必须步骤）
            if not skip_density_check and measurement_count > 0:
                self._set_state(LUTWorkflowState.CHECKING_DENSITY)
                self._notify_progress(0, 100, "正在检查测量点密度...")

                density_result = check_measurement_density(
                    measurement_count,
                    self._config.lut_spec,
                    strict=False  # 非严格模式，允许继续
                )
                self._report.density_check = density_result.to_dict()

                if not density_result.sufficient:
                    self._notify_status(density_result.recommendation)
                    # 记录但不阻断（用户可选择继续）
                    if self._session:
                        self._session.last_error = density_result.recommendation

                self._notify_progress(3, 100,
                    f"测量点密度: {measurement_count}/{density_result.required_count}")

            # 2. 验证配置
            self._set_state(LUTWorkflowState.VALIDATING_CONFIG)
            self._notify_progress(5, 100, "正在验证配置参数...")

            valid, error = self._config.validate()
            if not valid and not error.startswith("警告"):
                self._report.error_message = error
                self._report.success = False
                self._set_state(LUTWorkflowState.FAILED)
                return (False, self._report)

            # 自动处理 BPC + intent 互斥
            if self._config.intent == RenderingIntent.PERCEPTUAL and self._config.use_bpc:
                self._notify_status("感知意图不支持 BPC，已自动禁用")
                self._config.use_bpc = False
                self._report.use_bpc = False

            # 3. 检查源 ICC 文件
            self._notify_progress(7, 100, "正在检查源色彩空间 ICC...")
            source_icc = self.get_source_icc_path()
            self._notify_status(f"源色彩空间 ICC: {source_icc}")

            # 4. 构建 collink 命令
            cmd = self.build_collink_command()
            self._report.collink_command = " ".join(cmd)
            self._notify_status(f"执行命令: {' '.join(cmd)}")

            # 5. 执行 collink
            self._set_state(LUTWorkflowState.GENERATING_LUT)
            self._notify_progress(10, 100, "正在生成 LUT...")

            success = self._execute_collink(cmd)
            if not success:
                self._report.success = False
                self._set_state(LUTWorkflowState.FAILED)
                return (False, self._report)

            # 6. 验证生成的 LUT 格式
            self._set_state(LUTWorkflowState.VALIDATING_LUT)
            self._notify_progress(85, 100, "正在验证 LUT 格式...")

            valid_lut, lut_error = self._validate_cube_file(self._config.output_path)
            if not valid_lut:
                self._report.error_message = lut_error
                self._report.success = False
                self._set_state(LUTWorkflowState.FAILED)
                return (False, self._report)

            # 7. 自动运行验证（如果启用）
            if self._config.auto_validate:
                self._set_state(LUTWorkflowState.RUNNING_VALIDATION)
                self._notify_progress(90, 100, "正在准备验证色块集...")

                # 生成验证色块
                validation_patches = self._generate_validation_patches()
                self._notify_status(f"生成 {len(validation_patches)} 个验证色块")

                # 请求外部执行验证测量
                if self._on_validation_request and validation_patches:
                    self._notify_progress(92, 100, "等待验证测量...")
                    self._on_validation_request(validation_patches)
                    # 验证结果将在 provide_validation_data() 中提供

            # 8. 生成 manifest
            self._notify_progress(95, 100, "正在生成 manifest...")
            self._save_manifest()

            # 9. 完成
            self._set_state(LUTWorkflowState.COMPLETED)
            self._notify_progress(100, 100, "LUT 生成完成")

            # 计算耗时
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._report.generation_time_ms = elapsed_ms

            # 检查性能上限
            if elapsed_ms > self.MAX_GENERATION_TIME_MS:
                self._notify_status(f"警告: 生成时间 {elapsed_ms}ms 超过上限 {self.MAX_GENERATION_TIME_MS}ms")

            # 获取文件大小
            if os.path.exists(self._config.output_path):
                self._report.file_size_bytes = os.path.getsize(self._config.output_path)
                if self._session:
                    self._session.lut_file = self._config.output_path

            # 设置 manifest 路径
            if self._session_dir:
                self._report.manifest_path = str(self._session_dir / "manifest.json")

            # 更新 session
            if self._session:
                self._session.completed_at = datetime.now()

            self._report.success = True

            # 完成回调
            if self._on_completed:
                self._on_completed(self._report)

            return (True, self._report)

        except Exception as e:
            self._report.error_message = str(e)
            self._report.success = False
            self._set_state(LUTWorkflowState.FAILED)
            if self._session:
                self._session.last_error = str(e)
                self._session.recoverable = False
            logger.exception("LUT 生成失败")
            return (False, self._report)

    def provide_validation_data(
        self,
        measurements: List[Dict[str, Any]],
        delta_e_values: Optional[List[float]] = None,
    ) -> bool:
        """
        提供验证测量数据

        Args:
            measurements: 验证测量数据列表
            delta_e_values: Delta E 值列表（可选，自动计算）

        Returns:
            bool: 是否成功处理
        """
        if self._state != LUTWorkflowState.RUNNING_VALIDATION:
            logger.warning(f"无法在状态 {self._state.value} 接收验证数据")
            return False

        if not self._report:
            return False

        # 计算 Delta E 统计（如果提供）
        if delta_e_values:
            avg = sum(delta_e_values) / len(delta_e_values)
            max_val = max(delta_e_values)
            sorted_values = sorted(delta_e_values)
            idx_95 = int(len(sorted_values) * 0.95)
            delta_e_95 = sorted_values[min(idx_95, len(sorted_values) - 1)]

            self._report.validation_result = LUTValidationResult(
                validated=True,
                patch_count=len(measurements),
                delta_e_avg=avg,
                delta_e_max=max_val,
                delta_e_95=delta_e_95,
                passed=avg < 3.0,  # 合格阈值
                details={"measurements": measurements[:10]},  # 只保留前 10 个
            )
        else:
            self._report.validation_result = LUTValidationResult(
                validated=True,
                patch_count=len(measurements),
            )

        # 更新 session
        if self._session:
            self._session.validation_done = True
            self._session.validation_results = self._report.validation_result.to_dict()

        return True

    def _generate_validation_patches(self) -> List[Tuple[int, int, int, str]]:
        """
        生成验证色块集

        Returns:
            List[Tuple[int, int, int, str]]: RGB + name 色块列表
        """
        from src.workflows.validation_workflow import (
            VerificationPatchGenerator,
            VerificationPatchConfig,
        )

        config = VerificationPatchConfig(
            count=self._config.validation_patch_count,
            include_grayscale=True,
            include_primary_secondary=True,
            include_skin_tones=True,
        )

        generator = VerificationPatchGenerator(config)
        patches = generator.generate(target_gamut=self._config.target_space.value)

        return patches

    def _save_manifest(self) -> None:
        """保存 manifest 到 session 目录"""
        if not self._session_dir or not self._session:
            return

        manifest = ArtifactManifest()
        manifest.session_id = self._session.session_id
        manifest.created_at = datetime.now().isoformat()
        manifest.storage_type = "lut_sessions"

        # 设置 workflow 信息
        manifest.set_workflow_info(
            mode=f"lut_{self._config.lut_type.value}",
            target=self._config.target_space.value,
            status=self._state.value,
        )

        # 添加 LUT 文件条目
        if os.path.exists(self._config.output_path):
            lut_entry = ManifestEntry(
                type="lut",
                filename=os.path.basename(self._config.output_path),
                sha256=compute_file_hash(Path(self._config.output_path)),
                size_bytes=os.path.getsize(self._config.output_path),
                generated_at=datetime.now().isoformat(),
                generated_by="collink",
                parameters={
                    "lut_type": self._config.lut_type.value,
                    "size": self._config.lut_spec.size.value,
                    "interpolation": self._config.lut_spec.interpolation.value,
                    "source_space": self._config.source_space.value,
                    "target_space": self._config.target_space.value,
                    "intent": self._config.intent.value,
                    "use_bpc": self._config.use_bpc,
                },
            )
            manifest.add_file(lut_entry)

        # 添加 ICC 文件条目
        if os.path.exists(self._config.target_icc_path):
            icc_entry = ManifestEntry(
                type="icc",
                filename=os.path.basename(self._config.target_icc_path),
                sha256=compute_file_hash(Path(self._config.target_icc_path)),
                size_bytes=os.path.getsize(self._config.target_icc_path),
                generated_at=datetime.now().isoformat(),
                generated_by="colprof",
            )
            manifest.add_file(icc_entry)

        # 添加测量数据信息
        manifest.workflow["measurement"] = {
            "count": self._session.measurement_count,
            "hash": self._session.measurement_hash,
            "density_check": self._report.density_check if self._report else {},
        }

        # 添加验证结果
        if self._report and self._report.validation_result.validated:
            manifest.workflow["validation"] = self._report.validation_result.to_dict()

        # 保存 manifest
        manifest_path = save_manifest(manifest, self._session_dir)
        self._session.manifest_file = str(manifest_path)

    def _execute_collink(self, cmd: List[str]) -> bool:
        """
        执行 collink 命令。

        Args:
            cmd: collink 命令参数列表

        Returns:
            bool: 是否成功
        """
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # 实时读取输出
            stdout_lines = []
            stderr_lines = []

            while True:
                # 读取 stdout
                stdout_line = process.stdout.readline()
                if stdout_line:
                    stdout_lines.append(stdout_line)
                    stripped = stdout_line.strip()

                    # 过滤 TTY 错误
                    if "tcgetattr failed" not in stripped and "tcsetattr failed" not in stripped:
                        if stripped:
                            self._notify_status(f"[collink] {stripped}")

                            # 解析进度
                            progress_match = re.search(r'(\d+)%\s*(done|complete)', stripped, re.IGNORECASE)
                            if progress_match:
                                progress_pct = int(progress_match.group(1))
                                self._notify_progress(10 + progress_pct * 0.8, 100, f"计算进度: {progress_pct}%")

                # 读取 stderr
                stderr_line = process.stderr.readline()
                if stderr_line:
                    stderr_lines.append(stderr_line)

                # 检查进程是否结束
                if process.poll() is not None:
                    # 读取剩余输出
                    remaining_stdout = process.stdout.read()
                    remaining_stderr = process.stderr.read()
                    if remaining_stdout:
                        stdout_lines.append(remaining_stdout)
                    if remaining_stderr:
                        stderr_lines.append(remaining_stderr)
                    break

                time.sleep(0.1)

            # 合并输出
            full_output = "".join(stdout_lines + stderr_lines)

            # 检查返回码
            if process.returncode == 0:
                # 检查文件是否生成
                if os.path.exists(self._config.output_path):
                    return True
                else:
                    self._report.error_message = f"collink 执行成功但未生成文件: {self._config.output_path}"
                    return False
            else:
                # 解析错误消息
                clean_output = self._clean_collink_output(full_output)
                error_mapping = map_error_to_suggestion(clean_output)
                self._report.error_message = error_mapping.user_message
                self._notify_status(f"collink 失败: {clean_output}")
                return False

        except FileNotFoundError:
            self._report.error_message = "找不到 collink 命令，请确保 ArgyllCMS 已正确安装"
            return False
        except subprocess.TimeoutExpired:
            process.kill()
            self._report.error_message = "collink 执行超时"
            return False
        except Exception as e:
            self._report.error_message = f"执行 collink 时出错: {str(e)}"
            return False

    def _clean_collink_output(self, output: str) -> str:
        """清理 collink 输出，移除 TTY 错误"""
        clean_lines = []
        for line in output.splitlines():
            if "tcgetattr failed" not in line and "tcsetattr failed" not in line and line.strip():
                clean_lines.append(line)
        return "\n".join(clean_lines)

    def _validate_cube_file(self, path: str) -> Tuple[bool, str]:
        """
        验证生成的 .cube 文件格式。

        验证内容：
        1. 文件存在
        2. 文件头包含 TITLE 和 LUT_3D_SIZE
        3. LUT 尺寸与配置一致
        4. 数据行数正确（size^3 个数据点）

        Args:
            path: .cube 文件路径

        Returns:
            Tuple[bool, str]: (是否有效, 错误消息)
        """
        if not os.path.exists(path):
            return (False, f"LUT 文件不存在: {path}")

        try:
            with open(path, 'r') as f:
                lines = f.readlines()

            # 解析文件头
            found_title = False
            found_size = False
            lut_size = 0
            data_lines = 0

            for line in lines:
                line = line.strip()

                # TITLE 行
                if line.startswith("TITLE"):
                    found_title = True
                    continue

                # LUT_3D_SIZE 行
                if line.startswith("LUT_3D_SIZE"):
                    found_size = True
                    size_match = re.search(r'LUT_3D_SIZE\s+(\d+)', line)
                    if size_match:
                        lut_size = int(size_match.group(1))
                    continue

                # 数据行（非注释、非空行）
                if line and not line.startswith("#"):
                    # 数据行格式: R G B
                    parts = line.split()
                    if len(parts) == 3:
                        try:
                            float(parts[0])
                            float(parts[1])
                            float(parts[2])
                            data_lines += 1
                        except ValueError:
                            pass

            # 验证文件头
            if not found_title:
                return (False, "LUT 文件缺少 TITLE 行")

            if not found_size:
                return (False, "LUT 文件缺少 LUT_3D_SIZE 行")

            # 验证尺寸
            expected_size = self._config.lut_spec.size.value
            if lut_size != expected_size:
                return (False, f"LUT 尺寸不匹配: 期望 {expected_size}, 实际 {lut_size}")

            # 验证数据行数
            expected_data_count = lut_size ** 3
            # 允许一定的数据行数误差（有些 LUT 可能有额外的边界数据）
            if data_lines < expected_data_count * 0.95:
                return (False, f"数据行数不足: 期望至少 {expected_data_count * 0.95:.0f}, 实际 {data_lines}")

            return (True, "")

        except Exception as e:
            return (False, f"读取 LUT 文件失败: {str(e)}")


# ==============================================================================
# 辅助函数
# ==============================================================================

def get_source_space_list() -> List[Dict[str, str]]:
    """
    获取可用的源色彩空间列表。

    Returns:
        List[Dict]: 源色彩空间列表，每个元素包含：
            - 'preset': 预设名称（用于配置）
            - 'name': 显示名称
            - 'description': 描述
    """
    return [
        {
            "preset": preset.value,
            "name": definition.name,
            "description": definition.description,
        }
        for preset, definition in SOURCE_SPACE_DEFINITIONS.items()
    ]


def get_source_space_by_name(name: str) -> Optional[SourceSpacePreset]:
    """
    根据名称获取源色彩空间预设。

    Args:
        name: 源色彩空间名称（如 "Rec709", "sRGB", "DisplayP3"）

    Returns:
        Optional[SourceSpacePreset]: 对应的预设，找不到时返回 None
    """
    # 直接匹配
    for preset in SourceSpacePreset:
        if preset.value == name:
            return preset

    # 名称模糊匹配
    name_lower = name.lower().replace("-", "").replace(" ", "").replace(".", "")
    for preset in SourceSpacePreset:
        preset_lower = preset.value.lower().replace("-", "").replace("_", "")
        if preset_lower == name_lower or preset_lower.startswith(name_lower):
            return preset

    # 使用定义的 primaries_name 匹配
    for preset, definition in SOURCE_SPACE_DEFINITIONS.items():
        if definition.primaries_name.lower() == name_lower:
            return preset

    return None


def validate_intent_bpc_combination(intent: RenderingIntent, use_bpc: bool) -> Tuple[bool, str]:
    """
    验证渲染意图和 BPC 参数组合。

    Args:
        intent: 渲染意图
        use_bpc: 是否启用黑场补偿

    Returns:
        Tuple[bool, str]: (是否有效, 建议消息)
    """
    if intent == RenderingIntent.PERCEPTUAL:
        if use_bpc:
            return (False, "感知意图 (Perceptual) 不支持 BPC，感知意图已包含黑场映射，叠加会冲突")
        return (True, "")

    if intent == RenderingIntent.ABSOLUTE_COLORIMETRIC:
        if use_bpc:
            return (True, "警告: 绝对色度匹配通常不需要 BPC")
        return (True, "")

    if intent == RenderingIntent.RELATIVE_COLORIMETRIC:
        if use_bpc:
            return (True, "推荐: 相对色度匹配 + BPC 可防止暗部死黑")
        return (True, "警告: 相对色度匹配建议启用 BPC 以防止暗部死黑")

    # 饱和意图
    return (True, "")
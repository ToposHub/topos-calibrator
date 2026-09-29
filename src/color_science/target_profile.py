"""
统一目标 Profile 定义 - TargetProfile 数据结构

所有 ICC/LUT/Validation workflow 使用统一的目标模型，禁止各模块硬编码。

参考标准：
    - IEC 61966-2-1 - sRGB
    - ITU-R BT.709 - Rec.709
    - ITU-R BT.1886 - HD Gamma
    - SMPTE RP 431-2 - DCI-P3 / Display P3
    - ITU-R BT.2020 / BT.2100 - Rec.2020 / HDR
    - SMPTE ST 2084 - PQ EOTF
    - ITU-R BT.2100 - HLG OETF
    - CIE 15:2004 - 色度学
    - CIEDE2000 - 色差公式

核心设计原则：
    1. 所有 workflow 必须引用统一 TargetProfile，不允许硬编码 D65/gamma
    2. TargetProfile 包含完整的色彩空间、传递函数、白点定义
    3. 提供 SDR/Wide/HDR 三大类预设
    4. 所有数值转换必须有容差验证

Usage:
    >>> from src.color_science import TargetProfile, PRESET_TARGET_PROFILES
    >>> profile = PRESET_TARGET_PROFILES["sRGB"]
    >>> profile.white_point_xy  # (0.31271, 0.32902)
    >>> profile.transfer_function.name  # "sRGB"
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any

from .spaces import (
    WHITE_POINTS,
    COLOR_SPACES,
    get_white_point_xy,
    get_white_point_xyz,
    normalize_color_space_name,
    rgb_to_xyz,
    xyz_to_lab,
)
from .transfer import (
    TRANSFER_FUNCTIONS,
    apply_eotf,
    apply_oetf,
    eotf_gamma,
    eotf_srgb,
    eotf_bt1886,
    eotf_pq,
    eotf_hlg,
    oetf_gamma,
    oetf_srgb,
    eotf_bt1886_inverse,
    eotf_pq_inverse,
    eotf_hlg_inverse,
)
from .colorimetry import (
    delta_e_ciede2000,
    delta_e_cie94,
    delta_e_cie76,
    cct_duv_from_xy,
)


# ==============================================================================
# 色彩空间类别枚举
# ==============================================================================

class ColorSpaceCategory(Enum):
    """
    色彩空间类别

    - SDR: 标准 SDR 空间 (sRGB, Rec.709)
    - WIDE_GAMUT: 宽色域空间 (Display P3, Adobe RGB, Rec.2020)
    - HDR: HDR 空间 (PQ, HLG)
    """
    SDR = "sdr"
    WIDE_GAMUT = "wide_gamut"
    HDR = "hdr"


class TransferFunctionType(Enum):
    """
    传递函数类型

    - GAMMA_22: 纯 Gamma 2.2
    - GAMMA_24: 纯 Gamma 2.4
    - SRGB: sRGB TRC (分段曲线)
    - BT1886: BT.1886 Gamma 2.4 (带黑场提升)
    - PQ: SMPTE ST 2084 PQ EOTF
    - HLG: Hybrid Log-Gamma
    - LINEAR: 线性
    """
    GAMMA_22 = "gamma22"
    GAMMA_24 = "gamma24"
    SRGB = "sRGB"
    BT1886 = "BT1886"
    PQ = "PQ"
    HLG = "HLG"
    LINEAR = "linear"


class DeltaEMethod(Enum):
    """
    Delta E 计算方法

    - CIE76: CIE Delta E 1976 (简单欧氏距离)
    - CIE94: CIE Delta E 1994
    - CIEDE2000: CIEDE2000 (最精确，默认报告使用)
    """
    CIE76 = "cie76"
    CIE94 = "cie94"
    CIEDE2000 = "ciede2000"


class WhitePointType(Enum):
    """
    白点类型

    - D65: CIE D65 标准光源 (sRGB/Rec.709/Rec.2020 标准)
    - D50: CIE D50 标准光源 (印刷/摄影标准)
    - D60: CIE D60 标准光源 (DCI-P3 影院)
    - DCI: DCI 白点 (~6300K)
    - CUSTOM: 自定义 xy 坐标
    """
    D65 = "D65"
    D50 = "D50"
    D60 = "D60"
    DCI = "DCI"
    CUSTOM = "custom"


# ==============================================================================
# 传递函数定义
# ==============================================================================

@dataclass
class TransferFunctionDefinition:
    """
    传递函数完整定义

    包含 EOTF 和 OETF 函数、参数和描述。
    """
    name: str
    type: TransferFunctionType
    gamma: Optional[float] = None  # 对于 Gamma 曲线
    description: str = ""

    # HDR 特定参数
    peak_luminance: Optional[float] = None  # PQ 默认 10000, HLG 可配置
    min_luminance: Optional[float] = None   # 黑场亮度 (cd/m²)

    def get_eotf_params(self) -> Dict[str, Any]:
        """获取 EOTF 参数"""
        params = {}
        if self.gamma is not None:
            params["gamma"] = self.gamma
        if self.peak_luminance is not None:
            params["L_max"] = self.peak_luminance  # PQ
            params["Lw"] = self.peak_luminance  # HLG/BT.1886
        if self.min_luminance is not None:
            params["Lb"] = self.min_luminance
        return params

    def apply_eotf(self, V: float, **override_params) -> float:
        """
        应用 EOTF（码值到亮度）

        Args:
            V: 码值 (0-1)
            **override_params: 参数覆盖

        Returns:
            float: 亮度 (cd/m² 或归一化)
        """
        params = self.get_eotf_params()
        params.update(override_params)

        if self.type == TransferFunctionType.GAMMA_22:
            return eotf_gamma(V, 2.2)
        elif self.type == TransferFunctionType.GAMMA_24:
            return eotf_gamma(V, 2.4)
        elif self.type == TransferFunctionType.SRGB:
            return eotf_srgb(V)
        elif self.type == TransferFunctionType.BT1886:
            Lw = params.get("Lw", 100.0)
            Lb = params.get("Lb", 0.0)
            gamma = params.get("gamma", 2.4)
            return eotf_bt1886(V, Lw=Lw, Lb=Lb, gamma=gamma)
        elif self.type == TransferFunctionType.PQ:
            L_max = params.get("L_max", 10000.0)
            return eotf_pq(V, L_max=L_max)
        elif self.type == TransferFunctionType.HLG:
            Lw = params.get("Lw", 1000.0)
            Lb = params.get("Lb", 0.0)
            return eotf_hlg(V, Lw=Lw, Lb=Lb)
        elif self.type == TransferFunctionType.LINEAR:
            return V
        else:
            raise ValueError(f"未知的传递函数类型: {self.type}")

    def apply_oetf(self, L: float, **override_params) -> float:
        """
        应用 OETF（亮度到码值）

        Args:
            L: 亮度 (cd/m² 或归一化)
            **override_params: 参数覆盖

        Returns:
            float: 码值 (0-1)
        """
        params = self.get_eotf_params()
        params.update(override_params)

        if self.type == TransferFunctionType.GAMMA_22:
            return oetf_gamma(L, 2.2)
        elif self.type == TransferFunctionType.GAMMA_24:
            return oetf_gamma(L, 2.4)
        elif self.type == TransferFunctionType.SRGB:
            return oetf_srgb(L)
        elif self.type == TransferFunctionType.BT1886:
            Lw = params.get("Lw", 100.0)
            Lb = params.get("Lb", 0.0)
            gamma = params.get("gamma", 2.4)
            return eotf_bt1886_inverse(L, Lw=Lw, Lb=Lb, gamma=gamma)
        elif self.type == TransferFunctionType.PQ:
            L_max = params.get("L_max", 10000.0)
            return eotf_pq_inverse(L, L_max=L_max)
        elif self.type == TransferFunctionType.HLG:
            Lw = params.get("Lw", 1000.0)
            Lb = params.get("Lb", 0.0)
            return eotf_hlg_inverse(L, Lw=Lw, Lb=Lb)
        elif self.type == TransferFunctionType.LINEAR:
            return L
        else:
            raise ValueError(f"未知的传递函数类型: {self.type}")


# 预设传递函数定义
TRANSFER_FUNCTION_DEFINITIONS: Dict[TransferFunctionType, TransferFunctionDefinition] = {
    TransferFunctionType.GAMMA_22: TransferFunctionDefinition(
        name="Gamma 2.2",
        type=TransferFunctionType.GAMMA_22,
        gamma=2.2,
        description="纯 Gamma 2.2 曲线，常用于计算机显示器",
    ),
    TransferFunctionType.GAMMA_24: TransferFunctionDefinition(
        name="Gamma 2.4",
        type=TransferFunctionType.GAMMA_24,
        gamma=2.4,
        description="纯 Gamma 2.4 曲线，视频/电影常用",
    ),
    TransferFunctionType.SRGB: TransferFunctionDefinition(
        name="sRGB TRC",
        type=TransferFunctionType.SRGB,
        description="sRGB TRC (IEC 61966-2-1)，分段 Gamma 曲线",
    ),
    TransferFunctionType.BT1886: TransferFunctionDefinition(
        name="BT.1886",
        type=TransferFunctionType.BT1886,
        gamma=2.4,
        peak_luminance=100.0,  # 默认 SDR 白场
        min_luminance=0.0,
        description="ITU-R BT.1886 Gamma 2.4，带黑场提升",
    ),
    TransferFunctionType.PQ: TransferFunctionDefinition(
        name="PQ ST 2084",
        type=TransferFunctionType.PQ,
        peak_luminance=10000.0,  # PQ 最大亮度
        description="SMPTE ST 2084 PQ EOTF，HDR 标准",
    ),
    TransferFunctionType.HLG: TransferFunctionDefinition(
        name="HLG",
        type=TransferFunctionType.HLG,
        peak_luminance=1000.0,  # HLG 默认峰值
        description="ITU-R BT.2100 Hybrid Log-Gamma，HDR 广播标准",
    ),
    TransferFunctionType.LINEAR: TransferFunctionDefinition(
        name="Linear",
        type=TransferFunctionType.LINEAR,
        description="线性传递函数",
    ),
}


# ==============================================================================
# 白点定义
# ==============================================================================

@dataclass
class WhitePointDefinition:
    """
    白点完整定义

    包含名称、xy 坐标、CCT 描述。
    """
    name: str
    type: WhitePointType
    xy: Tuple[float, float]  # (x, y)
    cct_approx: float  # 近似 CCT (K)
    description: str = ""

    def get_xyz(self) -> Tuple[float, float, float]:
        """获取 XYZ 值 (Y=100)"""
        x, y = self.xy
        X = (x / y) * 100.0
        Y = 100.0
        Z = ((1 - x - y) / y) * 100.0
        return (X, Y, Z)


# 预设白点定义
WHITE_POINT_DEFINITIONS: Dict[WhitePointType, WhitePointDefinition] = {
    WhitePointType.D65: WhitePointDefinition(
        name="D65",
        type=WhitePointType.D65,
        xy=(0.31271, 0.32902),
        cct_approx=6500,
        description="CIE D65 标准光源 (6500K)，sRGB/Rec.709/Rec.2020 标准",
    ),
    WhitePointType.D50: WhitePointDefinition(
        name="D50",
        type=WhitePointType.D50,
        xy=(0.34567, 0.35850),
        cct_approx=5000,
        description="CIE D50 标准光源 (5000K)，印刷/摄影标准",
    ),
    WhitePointType.D60: WhitePointDefinition(
        name="D60",
        type=WhitePointType.D60,
        xy=(0.32168, 0.33767),
        cct_approx=6000,
        description="CIE D60 标准光源 (6000K)",
    ),
    WhitePointType.DCI: WhitePointDefinition(
        name="DCI",
        type=WhitePointType.DCI,
        xy=(0.3140, 0.3510),
        cct_approx=6300,
        description="DCI 白点 (~6300K)，影院投影标准",
    ),
}


# ==============================================================================
# TargetProfile - 统一目标定义
# ==============================================================================

@dataclass
class TargetProfile:
    """
    统一目标 Profile - 所有 ICC/LUT/Validation workflow 使用

    **禁止硬编码**: 所有 workflow 必须引用此数据结构。

    Attributes:
        name: Profile 名称
        color_space_name: 色彩空间名称 ("sRGB", "Rec709", "DisplayP3", "Rec2020" 等)
        category: 色彩空间类别 (SDR/WIDE_GAMUT/HDR)
        transfer_function: 传递函数定义
        white_point: 白点定义
        custom_white_xy: 自定义白点 xy (当 white_point 为 CUSTOM 时使用)

        peak_luminance: 峰值亮度 (cd/m²)，SDR 默认 100，HDR 可配置
        min_luminance: 黑场亮度 (cd/m²)，默认 0

        delta_e_method: Delta E 计算方法 (默认 CIEDE2000)
        use_cct_duv: 是否使用 CCT/Duv 报告灰阶/白点偏差

        description: 详细描述

    Usage:
        >>> profile = TargetProfile.srgb()
        >>> profile.white_point_xy  # D65
        >>> profile.transfer_function.type  # sRGB TRC

        >>> profile = TargetProfile.hdr_pq(peak_luminance=1000)
        >>> profile.peak_luminance  # 1000 cd/m²
    """
    name: str
    color_space_name: str
    category: ColorSpaceCategory
    transfer_function: TransferFunctionDefinition
    white_point: WhitePointDefinition
    custom_white_xy: Optional[Tuple[float, float]] = None

    # 亮度参数
    peak_luminance: float = 100.0  # cd/m²
    min_luminance: float = 0.0     # cd/m²

    # Delta E 计算配置
    delta_e_method: DeltaEMethod = DeltaEMethod.CIEDE2000
    use_cct_duv: bool = True

    description: str = ""

    # ========== 属性访问 ==========

    @property
    def white_point_xy(self) -> Tuple[float, float]:
        """获取白点 xy 坐标"""
        if self.white_point.type == WhitePointType.CUSTOM and self.custom_white_xy:
            return self.custom_white_xy
        return self.white_point.xy

    @property
    def white_point_xyz(self) -> Tuple[float, float, float]:
        """获取白点 XYZ (Y=100)"""
        x, y = self.white_point_xy
        X = (x / y) * 100.0
        Y = 100.0
        Z = ((1 - x - y) / y) * 100.0
        return (X, Y, Z)

    @property
    def primaries(self) -> Dict[str, Tuple[float, float]]:
        """获取 primaries xy 坐标"""
        cs_name = normalize_color_space_name(self.color_space_name)
        cs = COLOR_SPACES[cs_name]
        return {
            "red": cs["red"],
            "green": cs["green"],
            "blue": cs["blue"],
        }

    @property
    def is_hdr(self) -> bool:
        """是否为 HDR profile"""
        return self.category == ColorSpaceCategory.HDR

    @property
    def is_sdr(self) -> bool:
        """是否为 SDR profile"""
        return self.category == ColorSpaceCategory.SDR

    @property
    def is_wide_gamut(self) -> bool:
        """是否为宽色域 profile"""
        return self.category == ColorSpaceCategory.WIDE_GAMUT

    # ========== 色彩计算 ==========

    def rgb_to_target_xyz(
        self,
        r: float, g: float, b: float,
        linear: bool = False
    ) -> Tuple[float, float, float]:
        """
        RGB 到目标 XYZ 转换

        Args:
            r, g, b: RGB 值 (0-1)
            linear: RGB 是否已经是线性值

        Returns:
            Tuple[float, float, float]: XYZ (Y 范围 0-100)
        """
        # 如果非线性，先线性化
        if not linear:
            r_lin = self.transfer_function.apply_eotf(r)
            g_lin = self.transfer_function.apply_eotf(g)
            b_lin = self.transfer_function.apply_eotf(b)
        else:
            r_lin, g_lin, b_lin = r, g, b

        # 使用色彩空间矩阵转换
        cs_name = normalize_color_space_name(self.color_space_name)
        return rgb_to_xyz(r_lin, g_lin, b_lin, cs_name, linear=True)

    def rgb_to_target_lab(
        self,
        r: float, g: float, b: float,
        linear: bool = False
    ) -> Tuple[float, float, float]:
        """
        RGB 到目标 Lab 转换

        Args:
            r, g, b: RGB 值 (0-1)
            linear: RGB 是否已经是线性值

        Returns:
            Tuple[float, float, float]: (L*, a*, b*)
        """
        X, Y, Z = self.rgb_to_target_xyz(r, g, b, linear)
        return xyz_to_lab(X, Y, Z, self.white_point.type.value)

    def calculate_delta_e(
        self,
        Lab1: Tuple[float, float, float],
        Lab2: Tuple[float, float, float]
    ) -> float:
        """
        使用配置的方法计算 Delta E

        Args:
            Lab1, Lab2: 两个颜色的 Lab 值

        Returns:
            float: Delta E 值
        """
        if self.delta_e_method == DeltaEMethod.CIE76:
            return delta_e_cie76(Lab1, Lab2)
        elif self.delta_e_method == DeltaEMethod.CIE94:
            return delta_e_cie94(Lab1, Lab2)
        else:  # CIEDE2000 (默认)
            return delta_e_ciede2000(Lab1, Lab2)

    def calculate_cct_duv(
        self,
        x: float, y: float
    ) -> Tuple[float, float]:
        """
        计算 CCT 和 Duv

        Args:
            x, y: xy 坐标

        Returns:
            Tuple[float, float]: (CCT, Duv)
        """
        return cct_duv_from_xy(x, y)

    # ========== 验证 ==========

    def validate(self) -> Tuple[bool, List[str]]:
        """
        验证 TargetProfile 参数有效性

        Returns:
            Tuple[bool, List[str]]: (是否有效, 错误消息列表)
        """
        errors = []

        # 验证色彩空间
        try:
            normalize_color_space_name(self.color_space_name)
        except KeyError:
            errors.append(f"未知的色彩空间: {self.color_space_name}")

        # 验证白点
        if self.white_point.type == WhitePointType.CUSTOM:
            if not self.custom_white_xy:
                errors.append("自定义白点需要指定 custom_white_xy")
            else:
                x, y = self.custom_white_xy
                if not (0 <= x <= 1 and 0 <= y <= 1):
                    errors.append(f"自定义白点 xy 超出范围: ({x}, {y})")
                if x + y > 1:
                    errors.append(f"自定义白点 x+y > 1: {x + y}")

        # 验证传递函数
        if self.transfer_function.type not in TRANSFER_FUNCTION_DEFINITIONS:
            errors.append(f"未知的传递函数类型: {self.transfer_function.type}")

        # 验证 HDR 参数
        if self.is_hdr:
            if self.peak_luminance <= 0:
                errors.append(f"HDR peak luminance 必须 > 0: {self.peak_luminance}")
            if self.peak_luminance > 10000:
                errors.append(f"HDR peak luminance 超过 PQ 最大值 10000: {self.peak_luminance}")
            if self.min_luminance < 0:
                errors.append(f"min_luminance 不能为负: {self.min_luminance}")
            if self.min_luminance >= self.peak_luminance:
                errors.append(f"min_luminance 必须 < peak_luminance")

        # 验证亮度参数
        if self.peak_luminance <= 0:
            errors.append(f"peak_luminance 必须 > 0: {self.peak_luminance}")

        return (len(errors) == 0, errors)

    # ========== 工厂方法 - 预设 Profile ==========

    @classmethod
    def srgb(cls) -> 'TargetProfile':
        """创建 sRGB TargetProfile"""
        return cls(
            name="sRGB",
            color_space_name="sRGB",
            category=ColorSpaceCategory.SDR,
            transfer_function=TRANSFER_FUNCTION_DEFINITIONS[TransferFunctionType.SRGB],
            white_point=WHITE_POINT_DEFINITIONS[WhitePointType.D65],
            peak_luminance=100.0,
            min_luminance=0.0,
            delta_e_method=DeltaEMethod.CIEDE2000,
            use_cct_duv=True,
            description="sRGB (IEC 61966-2-1)，计算机显示器和网页标准",
        )

    @classmethod
    def rec709(cls) -> 'TargetProfile':
        """创建 Rec.709 TargetProfile"""
        return cls(
            name="Rec.709",
            color_space_name="Rec709",
            category=ColorSpaceCategory.SDR,
            transfer_function=TRANSFER_FUNCTION_DEFINITIONS[TransferFunctionType.BT1886],
            white_point=WHITE_POINT_DEFINITIONS[WhitePointType.D65],
            peak_luminance=100.0,
            min_luminance=0.0,
            delta_e_method=DeltaEMethod.CIEDE2000,
            use_cct_duv=True,
            description="Rec.709 (BT.709) + BT.1886 Gamma 2.4，HD 视频标准",
        )

    @classmethod
    def rec709_gamma22(cls) -> 'TargetProfile':
        """创建 Rec.709 Gamma 2.2 TargetProfile"""
        return cls(
            name="Rec.709 Gamma 2.2",
            color_space_name="Rec709",
            category=ColorSpaceCategory.SDR,
            transfer_function=TRANSFER_FUNCTION_DEFINITIONS[TransferFunctionType.GAMMA_22],
            white_point=WHITE_POINT_DEFINITIONS[WhitePointType.D65],
            peak_luminance=100.0,
            min_luminance=0.0,
            delta_e_method=DeltaEMethod.CIEDE2000,
            use_cct_duv=True,
            description="Rec.709 + Gamma 2.2，简化校准标准",
        )

    @classmethod
    def gamma_24(cls) -> 'TargetProfile':
        """创建 Gamma 2.4 TargetProfile"""
        return cls(
            name="Gamma 2.4",
            color_space_name="sRGB",  # 使用 sRGB primaries
            category=ColorSpaceCategory.SDR,
            transfer_function=TRANSFER_FUNCTION_DEFINITIONS[TransferFunctionType.GAMMA_24],
            white_point=WHITE_POINT_DEFINITIONS[WhitePointType.D65],
            peak_luminance=100.0,
            min_luminance=0.0,
            delta_e_method=DeltaEMethod.CIEDE2000,
            use_cct_duv=True,
            description="Gamma 2.4 曲线，视频/电影常用",
        )

    @classmethod
    def display_p3(cls) -> 'TargetProfile':
        """创建 Display P3 TargetProfile"""
        return cls(
            name="Display P3",
            color_space_name="DisplayP3",
            category=ColorSpaceCategory.WIDE_GAMUT,
            transfer_function=TRANSFER_FUNCTION_DEFINITIONS[TransferFunctionType.GAMMA_22],
            white_point=WHITE_POINT_DEFINITIONS[WhitePointType.D65],
            peak_luminance=100.0,
            min_luminance=0.0,
            delta_e_method=DeltaEMethod.CIEDE2000,
            use_cct_duv=True,
            description="Display P3 (P3-D65)，Apple 广色域显示器标准",
        )

    @classmethod
    def dci_p3(cls) -> 'TargetProfile':
        """创建 DCI-P3 TargetProfile (影院标准)"""
        return cls(
            name="DCI-P3",
            color_space_name="DCI_P3",
            category=ColorSpaceCategory.WIDE_GAMUT,
            transfer_function=TransferFunctionDefinition(
                name="Gamma 2.6",
                type=TransferFunctionType.GAMMA_24,  # 使用 gamma 参数
                gamma=2.6,
                description="DCI-P3 Gamma 2.6",
            ),
            white_point=WHITE_POINT_DEFINITIONS[WhitePointType.DCI],
            peak_luminance=48.0,  # 影院标准
            min_luminance=0.0,
            delta_e_method=DeltaEMethod.CIEDE2000,
            use_cct_duv=True,
            description="DCI-P3 (SMPTE RP 431-2)，影院投影标准，D60 白点",
        )

    @classmethod
    def adobe_rgb(cls) -> 'TargetProfile':
        """创建 Adobe RGB TargetProfile"""
        return cls(
            name="Adobe RGB",
            color_space_name="AdobeRGB",
            category=ColorSpaceCategory.WIDE_GAMUT,
            transfer_function=TRANSFER_FUNCTION_DEFINITIONS[TransferFunctionType.GAMMA_22],
            white_point=WHITE_POINT_DEFINITIONS[WhitePointType.D65],
            peak_luminance=100.0,
            min_luminance=0.0,
            delta_e_method=DeltaEMethod.CIEDE2000,
            use_cct_duv=True,
            description="Adobe RGB (1998)，摄影/印刷广色域",
        )

    @classmethod
    def rec2020(cls) -> 'TargetProfile':
        """创建 Rec.2020 SDR TargetProfile"""
        return cls(
            name="Rec.2020 SDR",
            color_space_name="Rec2020",
            category=ColorSpaceCategory.WIDE_GAMUT,
            transfer_function=TRANSFER_FUNCTION_DEFINITIONS[TransferFunctionType.BT1886],
            white_point=WHITE_POINT_DEFINITIONS[WhitePointType.D65],
            peak_luminance=100.0,
            min_luminance=0.0,
            delta_e_method=DeltaEMethod.CIEDE2000,
            use_cct_duv=True,
            description="Rec.2020 (BT.2020) + BT.1886，UHD/4K/8K SDR 标准",
        )

    @classmethod
    def hdr_pq(cls, peak_luminance: float = 1000.0) -> 'TargetProfile':
        """
        创建 HDR PQ TargetProfile

        Args:
            peak_luminance: 峰值亮度 (cd/m²)，可配置 (如 400, 600, 1000, 2000, 4000)

        Returns:
            TargetProfile: HDR PQ Profile
        """
        return cls(
            name=f"HDR PQ {peak_luminance} cd/m²",
            color_space_name="Rec2020",
            category=ColorSpaceCategory.HDR,
            transfer_function=TransferFunctionDefinition(
                name="PQ",
                type=TransferFunctionType.PQ,
                peak_luminance=peak_luminance,
                description=f"SMPTE ST 2084 PQ，峰值亮度 {peak_luminance} cd/m²",
            ),
            white_point=WHITE_POINT_DEFINITIONS[WhitePointType.D65],
            peak_luminance=peak_luminance,
            min_luminance=0.0,
            delta_e_method=DeltaEMethod.CIEDE2000,
            use_cct_duv=True,
            description=f"Rec.2020 + PQ (BT.2100)，HDR 标准，峰值 {peak_luminance} cd/m²",
        )

    @classmethod
    def hdr_hlg(cls, peak_luminance: float = 1000.0) -> 'TargetProfile':
        """
        创建 HDR HLG TargetProfile

        Args:
            peak_luminance: 显示峰值亮度 (cd/m²)，可配置

        Returns:
            TargetProfile: HDR HLG Profile
        """
        return cls(
            name=f"HDR HLG {peak_luminance} cd/m²",
            color_space_name="Rec2020",
            category=ColorSpaceCategory.HDR,
            transfer_function=TransferFunctionDefinition(
                name="HLG",
                type=TransferFunctionType.HLG,
                peak_luminance=peak_luminance,
                description=f"Hybrid Log-Gamma，峰值亮度 {peak_luminance} cd/m²",
            ),
            white_point=WHITE_POINT_DEFINITIONS[WhitePointType.D65],
            peak_luminance=peak_luminance,
            min_luminance=0.0,
            delta_e_method=DeltaEMethod.CIEDE2000,
            use_cct_duv=True,
            description=f"Rec.2020 + HLG (BT.2100)，HDR 广播标准，峰值 {peak_luminance} cd/m²",
        )

    @classmethod
    def custom(
        cls,
        name: str,
        color_space_name: str,
        transfer_type: TransferFunctionType,
        white_point_type: WhitePointType = WhitePointType.D65,
        custom_white_xy: Optional[Tuple[float, float]] = None,
        peak_luminance: float = 100.0,
        min_luminance: float = 0.0,
        gamma: Optional[float] = None,
        delta_e_method: DeltaEMethod = DeltaEMethod.CIEDE2000,
        description: str = ""
    ) -> 'TargetProfile':
        """
        创建自定义 TargetProfile

        Args:
            name: Profile 名称
            color_space_name: 色彩空间名称
            transfer_type: 传递函数类型
            white_point_type: 白点类型
            custom_white_xy: 自定义白点 xy (当 white_point_type 为 CUSTOM)
            peak_luminance: 峰值亮度
            min_luminance: 黑场亮度
            gamma: Gamma 值 (对于 Gamma 曲线)
            delta_e_method: Delta E 方法
            description: 描述

        Returns:
            TargetProfile: 自定义 Profile
        """
        # 确定类别
        if transfer_type in (TransferFunctionType.PQ, TransferFunctionType.HLG):
            category = ColorSpaceCategory.HDR
        elif color_space_name.lower() in ("displayp3", "dci_p3", "adobergb", "rec2020"):
            category = ColorSpaceCategory.WIDE_GAMUT
        else:
            category = ColorSpaceCategory.SDR

        # 获取白点定义
        if white_point_type == WhitePointType.CUSTOM:
            white_point = WhitePointDefinition(
                name="Custom",
                type=WhitePointType.CUSTOM,
                xy=custom_white_xy or (0.33, 0.33),
                cct_approx=5000,
                description="自定义白点",
            )
        else:
            white_point = WHITE_POINT_DEFINITIONS[white_point_type]

        # 构建传递函数定义
        tf_def = TransferFunctionDefinition(
            name=transfer_type.value,
            type=transfer_type,
            gamma=gamma,
            peak_luminance=peak_luminance if transfer_type in (TransferFunctionType.PQ, TransferFunctionType.HLG) else None,
            min_luminance=min_luminance,
            description=description,
        )

        return cls(
            name=name,
            color_space_name=color_space_name,
            category=category,
            transfer_function=tf_def,
            white_point=white_point,
            custom_white_xy=custom_white_xy,
            peak_luminance=peak_luminance,
            min_luminance=min_luminance,
            delta_e_method=delta_e_method,
            use_cct_duv=True,
            description=description,
        )

    # ========== 序列化 ==========

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "name": self.name,
            "color_space_name": self.color_space_name,
            "category": self.category.value,
            "transfer_function": {
                "name": self.transfer_function.name,
                "type": self.transfer_function.type.value,
                "gamma": self.transfer_function.gamma,
                "peak_luminance": self.transfer_function.peak_luminance,
                "min_luminance": self.transfer_function.min_luminance,
                "description": self.transfer_function.description,
            },
            "white_point": {
                "name": self.white_point.name,
                "type": self.white_point.type.value,
                "xy": list(self.white_point.xy),
                "cct_approx": self.white_point.cct_approx,
                "description": self.white_point.description,
            },
            "custom_white_xy": list(self.custom_white_xy) if self.custom_white_xy else None,
            "peak_luminance": self.peak_luminance,
            "min_luminance": self.min_luminance,
            "delta_e_method": self.delta_e_method.value,
            "use_cct_duv": self.use_cct_duv,
            "description": self.description,
            "primaries": {
                k: list(v) for k, v in self.primaries.items()
            },
            "is_hdr": self.is_hdr,
            "is_sdr": self.is_sdr,
            "is_wide_gamut": self.is_wide_gamut,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TargetProfile':
        """从字典加载"""
        tf_data = data.get("transfer_function", {})
        transfer_function = TransferFunctionDefinition(
            name=tf_data.get("name", ""),
            type=TransferFunctionType(tf_data.get("type", "sRGB")),
            gamma=tf_data.get("gamma"),
            peak_luminance=tf_data.get("peak_luminance"),
            min_luminance=tf_data.get("min_luminance"),
            description=tf_data.get("description", ""),
        )

        wp_data = data.get("white_point", {})
        white_point_type = WhitePointType(wp_data.get("type", "D65"))
        if white_point_type == WhitePointType.CUSTOM:
            white_point = WhitePointDefinition(
                name=wp_data.get("name", "Custom"),
                type=WhitePointType.CUSTOM,
                xy=tuple(wp_data.get("xy", [0.33, 0.33])),
                cct_approx=wp_data.get("cct_approx", 5000),
                description=wp_data.get("description", ""),
            )
        else:
            white_point = WHITE_POINT_DEFINITIONS[white_point_type]

        return cls(
            name=data.get("name", ""),
            color_space_name=data.get("color_space_name", "sRGB"),
            category=ColorSpaceCategory(data.get("category", "sdr")),
            transfer_function=transfer_function,
            white_point=white_point,
            custom_white_xy=tuple(data.get("custom_white_xy")) if data.get("custom_white_xy") else None,
            peak_luminance=data.get("peak_luminance", 100.0),
            min_luminance=data.get("min_luminance", 0.0),
            delta_e_method=DeltaEMethod(data.get("delta_e_method", "ciede2000")),
            use_cct_duv=data.get("use_cct_duv", True),
            description=data.get("description", ""),
        )


# ==============================================================================
# 预设 TargetProfile
# ==============================================================================

# 预设 Profile 字典 - 所有 workflow 使用此字典
PRESET_TARGET_PROFILES: Dict[str, TargetProfile] = {
    # SDR 标准
    "sRGB": TargetProfile.srgb(),
    "Rec.709": TargetProfile.rec709(),
    "Rec.709 Gamma 2.2": TargetProfile.rec709_gamma22(),
    "Gamma 2.2": TargetProfile.srgb(),  # 别名
    "Gamma 2.4": TargetProfile.gamma_24(),
    "BT.1886": TargetProfile.rec709(),  # 别名

    # 宽色域
    "Display P3": TargetProfile.display_p3(),
    "P3-D65": TargetProfile.display_p3(),  # 别名
    "DCI-P3": TargetProfile.dci_p3(),
    "Adobe RGB": TargetProfile.adobe_rgb(),
    "Rec.2020": TargetProfile.rec2020(),

    # HDR
    "HDR PQ 100": TargetProfile.hdr_pq(100.0),
    "HDR PQ 400": TargetProfile.hdr_pq(400.0),
    "HDR PQ 1000": TargetProfile.hdr_pq(1000.0),
    "HDR PQ 2000": TargetProfile.hdr_pq(2000.0),
    "HDR PQ 4000": TargetProfile.hdr_pq(4000.0),
    "HDR HLG 100": TargetProfile.hdr_hlg(100.0),
    "HDR HLG 1000": TargetProfile.hdr_hlg(1000.0),
    "HDR HLG 2000": TargetProfile.hdr_hlg(2000.0),
}


def get_target_profile(name: str) -> TargetProfile:
    """
    获取预设 TargetProfile

    Args:
        name: 预设名称

    Returns:
        TargetProfile: 预设 Profile

    Raises:
        KeyError: 未知的预设名称
    """
    if name in PRESET_TARGET_PROFILES:
        return PRESET_TARGET_PROFILES[name]

    # 尝试匹配常见别名
    aliases = {
        "rec709": "Rec.709",
        "rec.709": "Rec.709",
        "Rec709": "Rec.709",
        "p3": "Display P3",
        "P3": "Display P3",
        "p3-d65": "Display P3",
        "DisplayP3": "Display P3",
        "dci-p3": "DCI-P3",
        "DCIP3": "DCI-P3",
        "dci_p3": "DCI-P3",
        "adobergb": "Adobe RGB",
        "AdobeRGB": "Adobe RGB",
        "adobe rgb": "Adobe RGB",
        "rec2020": "Rec.2020",
        "Rec2020": "Rec.2020",
        "rec.2020": "Rec.2020",
        "pq": "HDR PQ 1000",
        "PQ": "HDR PQ 1000",
        "hlg": "HDR HLG 1000",
        "HLG": "HDR HLG 1000",
    }

    if name.lower() in aliases:
        return PRESET_TARGET_PROFILES[aliases[name.lower()]]

    raise KeyError(f"未知的 TargetProfile 预设: {name}. 支持的预设: {list(PRESET_TARGET_PROFILES.keys())}")


def list_target_profile_names() -> List[str]:
    """
    列出所有预设 TargetProfile 名称

    Returns:
        List[str]: 预设名称列表
    """
    return list(PRESET_TARGET_PROFILES.keys())


# ==============================================================================
# 数值容差测试辅助函数
# ==============================================================================

def assert_color_value_tolerance(
    actual: float,
    expected: float,
    tolerance: float,
    name: str = "value"
) -> Tuple[bool, str]:
    """
    数值容差验证

    Args:
        actual: 实测值
        expected: 期望值
        tolerance: 容差
        name: 值名称

    Returns:
        Tuple[bool, str]: (是否通过, 错误消息)
    """
    error = abs(actual - expected)
    if error <= tolerance:
        return (True, "")
    else:
        return (False, f"{name}: 实测 {actual:.6f}, 期望 {expected:.6f}, 误差 {error:.6f} > 容差 {tolerance}")


def assert_xyz_tolerance(
    actual_xyz: Tuple[float, float, float],
    expected_xyz: Tuple[float, float, float],
    tolerance: float = 0.01,
    name: str = "XYZ"
) -> Tuple[bool, List[str]]:
    """
    XYZ 容差验证

    Args:
        actual_xyz: 实测 XYZ
        expected_xyz: 期望 XYZ
        tolerance: 容差 (相对或绝对)
        name: 值名称

    Returns:
        Tuple[bool, List[str]]: (是否全部通过, 错误消息列表)
    """
    errors = []
    passed = True

    for i, (label, actual, expected) in enumerate(zip(["X", "Y", "Z"], actual_xyz, expected_xyz)):
        ok, msg = assert_color_value_tolerance(actual, expected, tolerance, f"{name}.{label}")
        if not ok:
            passed = False
            errors.append(msg)

    return (passed, errors)


def assert_lab_tolerance(
    actual_lab: Tuple[float, float, float],
    expected_lab: Tuple[float, float, float],
    tolerance: float = 0.5,
    name: str = "Lab"
) -> Tuple[bool, List[str]]:
    """
    Lab 容差验证

    Args:
        actual_lab: 实测 Lab
        expected_lab: 期望 Lab
        tolerance: 容差
        name: 值名称

    Returns:
        Tuple[bool, List[str]]: (是否全部通过, 错误消息列表)
    """
    errors = []
    passed = True

    for i, (label, actual, expected) in enumerate(zip(["L", "a", "b"], actual_lab, expected_lab)):
        ok, msg = assert_color_value_tolerance(actual, expected, tolerance, f"{name}.{label}")
        if not ok:
            passed = False
            errors.append(msg)

    return (passed, errors)


def assert_rgb_tolerance(
    actual_rgb: Tuple[float, float, float],
    expected_rgb: Tuple[float, float, float],
    tolerance: float = 0.001,
    name: str = "RGB"
) -> Tuple[bool, List[str]]:
    """
    RGB 容差验证 (0-1 范围)

    Args:
        actual_rgb: 实测 RGB
        expected_rgb: 期望 RGB
        tolerance: 容差
        name: 值名称

    Returns:
        Tuple[bool, List[str]]: (是否全部通过, 错误消息列表)
    """
    errors = []
    passed = True

    for i, (label, actual, expected) in enumerate(zip(["R", "G", "B"], actual_rgb, expected_rgb)):
        ok, msg = assert_color_value_tolerance(actual, expected, tolerance, f"{name}.{label}")
        if not ok:
            passed = False
            errors.append(msg)

    return (passed, errors)


def assert_delta_e_tolerance(
    actual_delta_e: float,
    max_allowed: float,
    name: str = "Delta E"
) -> Tuple[bool, str]:
    """
    Delta E 容差验证

    Args:
        actual_delta_e: 实测 Delta E
        max_allowed: 最大允许值
        name: 值名称

    Returns:
        Tuple[bool, str]: (是否通过, 错误消息)
    """
    if actual_delta_e <= max_allowed:
        return (True, "")
    else:
        return (False, f"{name}: {actual_delta_e:.4f} > 最大允许 {max_allowed}")


def assert_white_point_tolerance(
    actual_xy: Tuple[float, float],
    expected_xy: Tuple[float, float],
    xy_tolerance: float = 0.001,
    name: str = "White Point"
) -> Tuple[bool, List[str]]:
    """
    白点 xy 容差验证

    Args:
        actual_xy: 实测 xy
        expected_xy: 期望 xy
        xy_tolerance: xy 容差
        name: 值名称

    Returns:
        Tuple[bool, List[str]]: (是否全部通过, 错误消息列表)
    """
    errors = []
    passed = True

    for i, (label, actual, expected) in enumerate(zip(["x", "y"], actual_xy, expected_xy)):
        ok, msg = assert_color_value_tolerance(actual, expected, xy_tolerance, f"{name}.{label}")
        if not ok:
            passed = False
            errors.append(msg)

    return (passed, errors)
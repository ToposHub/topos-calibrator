"""
传递函数（EOTF/OETF）- Gamma/sRGB/BT.1886/PQ/HLG/Log 曲线

参考标准：
    - IEC 61966-2-1 - sRGB TRC
    - ITU-R BT.1886 - Gamma for HD TV
    - SMPTE ST 2084 - PQ (Perceptual Quantizer)
    - ITU-R BT.2100-2 - HLG (Hybrid Log-Gamma)
    - ITU-R BT.709 - OETF for HD

术语说明：
    - EOTF (Electro-Optical Transfer Function): 电信号到光信号的转换
      - 输入：码值 (code value, 0-1)
      - 输出：亮度 (cd/m² 或归一化)
    
    - OETF (Opto-Electrical Transfer Function): 光信号到电信号的转换
      - 输入：亮度 (cd/m² 或归一化)
      - 输出：码值 (0-1)
"""

import math
from typing import Tuple, Dict, Optional, Callable, Union

# ==============================================================================
# 传递函数名称定义
# ==============================================================================

TRANSFER_FUNCTIONS: Dict[str, Dict] = {
    "gamma2.2": {
        "type": "gamma",
        "gamma": 2.2,
        "description": "纯 Gamma 2.2 曲线",
    },
    "gamma2.4": {
        "type": "gamma",
        "gamma": 2.4,
        "description": "纯 Gamma 2.4 曲线（电影/视频常用）",
    },
    "sRGB": {
        "type": "piecewise",
        "description": "sRGB TRC (IEC 61966-2-1)",
    },
    "BT.1886": {
        "type": "gamma_with_black_lift",
        "gamma": 2.4,
        "description": "ITU-R BT.1886 (HD Gamma)",
    },
    "BT.709": {
        "type": "piecewise_oetf",
        "description": "ITU-R BT.709 OETF",
    },
    "PQ": {
        "type": "hdr",
        "description": "SMPTE ST 2084 PQ (HDR)",
    },
    "HLG": {
        "type": "hdr_hybrid",
        "description": "ITU-R BT.2100 HLG",
    },
}


# ==============================================================================
# 纯 Gamma EOTF/OETF
# ==============================================================================

def eotf_gamma(V: float, gamma: float = 2.2) -> float:
    """
    纯 Gamma EOTF（电-光转换）
    
    L = V^gamma
    
    Args:
        V: 码值（0-1 范围）
        gamma: Gamma 值（通常 2.2 或 2.4）
        
    Returns:
        float: 归一化亮度（0-1）
    """
    if V < 0:
        return 0.0
    return math.pow(V, gamma)


def oetf_gamma(L: float, gamma: float = 2.2) -> float:
    """
    纯 Gamma OETF（光-电转换）
    
    V = L^(1/gamma)
    
    Args:
        L: 归一化亮度（0-1）
        gamma: Gamma 值
        
    Returns:
        float: 码值（0-1）
    """
    if L < 0:
        return 0.0
    return math.pow(L, 1.0 / gamma)


# ==============================================================================
# sRGB EOTF/OETF
# ==============================================================================

def eotf_srgb(V: float) -> float:
    """
    sRGB EOTF（反 Gamma）
    
    根据 IEC 61966-2-1 标准：
    - V <= 0.04045: L = V / 12.92
    - V > 0.04045: L = ((V + 0.055) / 1.055)^2.4
    
    Args:
        V: 码值（0-1 范围）
        
    Returns:
        float: 线性亮度（0-1）
    """
    if V <= 0.04045:
        return V / 12.92
    else:
        return math.pow((V + 0.055) / 1.055, 2.4)


def oetf_srgb(L: float) -> float:
    """
    sRGB OETF（Gamma 校正）
    
    根据 IEC 61966-2-1 标准：
    - L <= 0.0031308: V = 12.92 * L
    - L > 0.0031308: V = 1.055 * L^(1/2.4) - 0.055
    
    Args:
        L: 线性亮度（0-1）
        
    Returns:
        float: 码值（0-1）
    """
    if L <= 0.0031308:
        return 12.92 * L
    else:
        return 1.055 * math.pow(L, 1.0 / 2.4) - 0.055


# ==============================================================================
# BT.1886 EOTF
# ==============================================================================

def eotf_bt1886(
    V: float,
    Lw: float = 100.0,
    Lb: float = 0.0,
    gamma: float = 2.4
) -> float:
    """
    BT.1886 EOTF（带黑场提升的 Gamma）
    
    根据 ITU-R BT.1886 标准：
    L = (Lw - Lb) * V^gamma + Lb
    
    参数：
    - Lw: 白场亮度 (cd/m²)
    - Lb: 黑场亮度 (cd/m²)
    - gamma: 通常固定为 2.4
    
    Args:
        V: 码值（0-1）
        Lw: 白场亮度 (cd/m²)
        Lb: 黑场亮度 (cd/m²)
        gamma: Gamma 值（标准为 2.4）
        
    Returns:
        float: 亮度 (cd/m²)
    """
    return (Lw - Lb) * math.pow(V, gamma) + Lb


def eotf_bt1886_inverse(
    L: float,
    Lw: float = 100.0,
    Lb: float = 0.0,
    gamma: float = 2.4
) -> float:
    """
    BT.1886 反 EOTF（亮度到码值）
    
    V = ((L - Lb) / (Lw - Lb))^(1/gamma)
    
    Args:
        L: 亮度 (cd/m²)
        Lw: 白场亮度 (cd/m²)
        Lb: 黑场亮度 (cd/m²)
        gamma: Gamma 值
        
    Returns:
        float: 码值（0-1）
    """
    if Lw == Lb:
        return 0.0
    
    L_normalized = (L - Lb) / (Lw - Lb)
    
    if L_normalized <= 0:
        return 0.0
    
    return math.pow(L_normalized, 1.0 / gamma)


# ==============================================================================
# BT.709 OETF
# ==============================================================================

def oetf_bt709(L: float) -> float:
    """
    BT.709 OETF（HD 视频）
    
    根据 ITU-R BT.709 标准：
    - L <= 0.018: V = 4.5 * L
    - L > 0.018: V = 1.099 * L^0.45 - 0.099
    
    Args:
        L: 场景线性亮度（0-1）
        
    Returns:
        float: 码值（0-1）
    """
    if L <= 0.018:
        return 4.5 * L
    else:
        return 1.099 * math.pow(L, 0.45) - 0.099


def eotf_bt709(V: float) -> float:
    """
    BT.709 反 OETF（近似）
    
    注意：BT.709 定义的是 OETF，其逆函数是 BT.1886。
    这里提供的是 OETF 的数学逆函数，用于特定场景。
    
    Args:
        V: 码值（0-1）
        
    Returns:
        float: 场景线性亮度（0-1）
    """
    # BT.709 OETF 的逆函数
    # V <= 0.081 (4.5 * 0.018): L = V / 4.5
    # V > 0.081: L = ((V + 0.099) / 1.099)^(1/0.45)
    
    threshold = 4.5 * 0.018  # 0.081
    
    if V <= threshold:
        return V / 4.5
    else:
        return math.pow((V + 0.099) / 1.099, 1.0 / 0.45)


# ==============================================================================
# PQ ST 2084 EOTF/OETF
# ==============================================================================

# PQ 常量（SMPTE ST 2084）
# 标准 m1 = 2610/16384 ≈ 0.1593，用于指数 1/m1 ≈ 6.27
PQ_M1 = 2610.0 / 16384.0  # 约 0.1593017578125
PQ_M2 = 2523.0 / 4096.0 * 128  # 约 78.84375
PQ_C1 = 3424.0 / 4096.0  # 约 0.8359375
PQ_C2 = 2413.0 / 4096.0 * 32  # 约 18.8515625
PQ_C3 = 2392.0 / 4096.0 * 32  # 约 18.6875


def eotf_pq(V: float, L_max: float = 10000.0) -> float:
    """
    PQ EOTF（SMPTE ST 2084）

    将码值转换为亮度，最大亮度 10000 cd/m²

    标准公式：
    L = L_max * ((max(V^(1/m2) - c1, 0)) / (c2 - c3 * V^(1/m2)))^(1/m1)

    Args:
        V: 码值（0-1）
        L_max: 最大亮度（默认 10000 cd/m²）

    Returns:
        float: 亮度 (cd/m²)
    """
    if V <= 0:
        return 0.0

    # V^(1/m2)
    Vp = math.pow(V, 1.0 / PQ_M2)

    # max(V^(1/m2) - c1, 0)
    numerator = max(Vp - PQ_C1, 0.0)

    # c2 - c3 * V^(1/m2)
    denominator = PQ_C2 - PQ_C3 * Vp

    if denominator <= 0:
        return L_max

    ratio = numerator / denominator
    if ratio <= 0:
        return 0.0

    # ^(1/m1)
    L_normalized = math.pow(ratio, 1.0 / PQ_M1)

    return L_max * L_normalized


# PQ 的 c4（之前漏定义）
PQ_C4 = PQ_C3  # 根据 ST 2084，c4 = c3 = 2392/4096 * 32 ≈ 18.6875


def eotf_pq_inverse(L: float, L_max: float = 10000.0) -> float:
    """
    PQ 反 EOTF（亮度到码值）
    
    公式：
    V = ((c1 + c2 * L_n^m1) / (1 + c3 * L_n^m1))^m2
    
    Args:
        L: 亮度 (cd/m²)
        L_max: 最大亮度
        
    Returns:
        float: 码值（0-1）
    """
    if L <= 0:
        return 0.0
    
    L_normalized = L / L_max
    
    # L_n^m1
    Lp = math.pow(L_normalized, PQ_M1)
    
    # (c1 + c2 * Lp) / (1 + c3 * Lp)
    numerator = PQ_C1 + PQ_C2 * Lp
    denominator = 1.0 + PQ_C3 * Lp
    
    V = math.pow(numerator / denominator, PQ_M2)
    
    return V


# 别名
oetf_pq_inverse = eotf_pq_inverse


# ==============================================================================
# HLG EOTF/OETF
# ==============================================================================

# HLG 常量（ITU-R BT.2100-2）
HLG_A = 0.17883277
HLG_B = 0.28466892
HLG_C = 0.55991073

# HLG 参考白点（默认 75% HDR 信号 = 203 cd/m²）
HLG_REF_WHITE = 203.0  # cd/m²


def oetf_hlg(L: float) -> float:
    """
    HLG OETF（场景参考）
    
    根据 ITU-R BT.2100-2：
    - L <= 1: V = 0.5 * sqrt(L)
    - L > 1: V = A * ln(L - B) + C
    
    Args:
        L: 场景亮度（相对于参考白归一化）
        
    Returns:
        float: 码值（0-1）
    """
    if L <= 0:
        return 0.0
    
    if L <= 1.0:
        return 0.5 * math.sqrt(L)
    else:
        return HLG_A * math.log(L - HLG_B) + HLG_C


def eotf_hlg(V: float, Lw: float = 1000.0, Lb: float = 0.0) -> float:
    """
    HLG EOTF（显示参考）

    根据 ITU-R BT.2100-2，OETF inverse：
    - V <= 0.5: L_scene = V^2 / 3
    - V > 0.5: L_scene = (exp((V - C) / A) + B) / 12

    然后应用系统 Gamma：
    L_display = L_scene^gamma_sys * Lw

    Args:
        V: 码值（0-1）
        Lw: 显示器峰值亮度 (cd/m²)
        Lb: 显示器黑场亮度 (cd/m²)

    Returns:
        float: 显示亮度 (cd/m²)
    """
    if V <= 0:
        return Lb

    # OETF 的逆函数（场景参考）
    if V <= 0.5:
        L_scene = V * V / 3.0
    else:
        L_scene = (math.exp((V - HLG_C) / HLG_A) + HLG_B) / 12.0

    # 系统 Gamma（与峰值亮度相关）
    # gamma_sys = 1.2 + 0.42 * log10(Lw / 1000)
    # 对于 Lw = 1000, gamma_sys = 1.2
    gamma_sys = 1.2 + 0.42 * math.log10(Lw / 1000.0)

    # 应用系统 Gamma
    L_display = math.pow(L_scene, gamma_sys) * Lw + Lb

    return L_display


def eotf_hlg_inverse(L: float, Lw: float = 1000.0, Lb: float = 0.0) -> float:
    """
    HLG 反 EOTF（亮度到码值）

    Args:
        L: 显示亮度 (cd/m²)
        Lw: 显示器峰值亮度 (cd/m²)
        Lb: 显示器黑场亮度 (cd/m²)

    Returns:
        float: 码值（0-1）
    """
    if L <= Lb:
        return 0.0

    if Lw == Lb:
        return 0.0

    gamma_sys = 1.2 + 0.42 * math.log10(Lw / 1000.0)

    # 反系统 Gamma
    L_scene = math.pow((L - Lb) / Lw, 1.0 / gamma_sys)

    # OETF inverse 的逆（即 OETF）
    # L_scene <= 1/12 时 V <= 0.5
    if L_scene <= 1.0 / 12.0:
        return math.sqrt(3.0 * L_scene)
    else:
        return HLG_A * math.log(12.0 * L_scene - HLG_B) + HLG_C


# ==============================================================================
# 通用接口
# ==============================================================================

def apply_eotf(
    V: float,
    curve: str,
    **kwargs
) -> float:
    """
    应用 EOTF（码值到亮度）
    
    Args:
        V: 码值（0-1）
        curve: 曲线名称 ("gamma2.2", "sRGB", "BT.1886", "PQ", "HLG")
        **kwargs: 曲线特定参数
        
    Returns:
        float: 亮度值（单位取决于曲线）
    """
    if curve == "gamma2.2":
        return eotf_gamma(V, 2.2)
    elif curve == "gamma2.4":
        return eotf_gamma(V, 2.4)
    elif curve.startswith("gamma"):
        gamma = float(curve.replace("gamma", ""))
        return eotf_gamma(V, gamma)
    elif curve == "sRGB":
        return eotf_srgb(V)
    elif curve == "BT.1886":
        return eotf_bt1886(V, kwargs.get("Lw", 100.0), kwargs.get("Lb", 0.0))
    elif curve == "PQ":
        return eotf_pq(V, kwargs.get("L_max", 10000.0))
    elif curve == "HLG":
        return eotf_hlg(V, kwargs.get("Lw", 1000.0), kwargs.get("Lb", 0.0))
    else:
        raise ValueError(f"未知的传递函数: {curve}")


def apply_oetf(
    L: float,
    curve: str,
    **kwargs
) -> float:
    """
    应用 OETF（亮度到码值）
    
    Args:
        L: 亮度值
        curve: 曲线名称
        **kwargs: 曲线特定参数
        
    Returns:
        float: 码值（0-1）
    """
    if curve == "gamma2.2":
        return oetf_gamma(L, 2.2)
    elif curve == "gamma2.4":
        return oetf_gamma(L, 2.4)
    elif curve.startswith("gamma"):
        gamma = float(curve.replace("gamma", ""))
        return oetf_gamma(L, gamma)
    elif curve == "sRGB":
        return oetf_srgb(L)
    elif curve == "BT.1886":
        return eotf_bt1886_inverse(L, kwargs.get("Lw", 100.0), kwargs.get("Lb", 0.0))
    elif curve == "PQ":
        return eotf_pq_inverse(L, kwargs.get("L_max", 10000.0))
    elif curve == "HLG":
        return eotf_hlg_inverse(L, kwargs.get("Lw", 1000.0), kwargs.get("Lb", 0.0))
    elif curve == "BT.709":
        return oetf_bt709(L)
    else:
        raise ValueError(f"未知的传递函数: {curve}")


# ==============================================================================
# Gamma 测量辅助函数
# ==============================================================================

def calculate_gamma_from_measurements(
    measurements: list,
    Lw: float,
    Lb: float = 0.0
) -> Tuple[float, float, float, list]:
    """
    从灰阶测量数据计算 Gamma 值
    
    Args:
        measurements: 灰阶测量数据列表
            [{"input": float, "Y": float}, ...]
        Lw: 白场亮度 (cd/m²)
        Lb: 黑场亮度 (cd/m²)
        
    Returns:
        Tuple[float, float, float, list]:
            - 平均 Gamma
            - Gamma 标准差
            - 最大 Gamma 偏差
            - 每个点的 Gamma 值列表
    """
    if len(measurements) < 2:
        return (0.0, 0.0, 0.0, [])
    
    gamma_values = []
    point_errors = []
    
    for m in measurements:
        V = m["input"]  # 输入码值（0-1）
        Y = m["Y"]  # 测量亮度
        
        # 计算该点的 Gamma
        if V > 0 and Y > Lb:
            Y_normalized = (Y - Lb) / (Lw - Lb)
            if Y_normalized > 0:
                gamma = math.log(Y_normalized) / math.log(V)
                if 1.0 <= gamma <= 4.0:
                    gamma_values.append(gamma)
                    
                    # 计算与纯 Gamma 曲线的误差
                    expected_Y = (Lw - Lb) * math.pow(V, gamma) + Lb
                    error = abs(Y - expected_Y)
                    point_errors.append(error)
    
    if len(gamma_values) == 0:
        return (0.0, 0.0, 0.0, [])
    
    # 统计
    mean_gamma = sum(gamma_values) / len(gamma_values)
    variance = sum((g - mean_gamma) ** 2 for g in gamma_values) / len(gamma_values)
    std_gamma = math.sqrt(variance)
    max_deviation = max(abs(g - mean_gamma) for g in gamma_values)
    
    return (mean_gamma, std_gamma, max_deviation, gamma_values)


def calculate_eotf_errors(
    measurements: list,
    curve: str,
    **kwargs
) -> Dict:
    """
    计算测量数据与目标曲线的误差

    Args:
        measurements: 灰阶测量数据
            [{"input": float, "Y": float, "patchName": str}, ...]
        curve: 目标曲线名称
        **kwargs: 曲线参数 (Lw, Lb, L_max 等)

    Returns:
        Dict: 误差统计
            - mean_error: 平均误差 (cd/m²)
            - max_error: 最大误差 (cd/m²)
            - max_error_point: 最大误差点的输入值
            - max_error_patch: 最大误差点的 patch 名称
            - dark_error: 暗部平均误差（L < 20 cd/m²）
            - bright_error: 亮部平均误差（L >= 20 cd/m²）
            - mean_relative_error: 平均相对误差 (%)
            - gamma_estimate: 从测量数据估算的 Gamma 值
            - points: 每点误差详情
    """
    if not measurements:
        return {
            "mean_error": 0.0,
            "max_error": 0.0,
            "max_error_point": None,
            "max_error_patch": None,
            "dark_error": 0.0,
            "bright_error": 0.0,
            "mean_relative_error": 0.0,
            "gamma_estimate": None,
            "points": [],
        }

    points = []
    total_error = 0.0
    max_error = 0.0
    max_error_point = None
    max_error_patch = None
    dark_errors = []
    bright_errors = []
    total_relative_error = 0.0
    gamma_values = []

    for m in measurements:
        V = m.get("input", 0.0)
        Y_measured = m.get("Y", 0.0)
        patch_name = m.get("patchName", "")

        # 计算目标亮度
        Y_target = apply_eotf(V, curve, **kwargs)

        error = abs(Y_measured - Y_target)
        relative_error = (error / Y_target * 100) if Y_target > 0 else 0.0

        points.append({
            "input": V,
            "patch_name": patch_name,
            "measured": Y_measured,
            "target": Y_target,
            "error": error,
            "relative_error": relative_error,
        })

        total_error += error
        total_relative_error += relative_error

        if error > max_error:
            max_error = error
            max_error_point = V
            max_error_patch = patch_name

        # 暗部/亮部误差分类（目标亮度 < 20 cd/m² 为暗部）
        if Y_target < 20:
            dark_errors.append(error)
        else:
            bright_errors.append(error)

        # 计算 Gamma（仅对合理的测量点）
        Lw = kwargs.get("Lw", 100.0)
        Lb = kwargs.get("Lb", 0.0)
        if V > 0.01 and Y_measured > Lb and Y_measured < Lw:
            Y_normalized = (Y_measured - Lb) / (Lw - Lb)
            if Y_normalized > 0 and Y_normalized < 1:
                gamma = math.log(Y_normalized) / math.log(V)
                if 1.0 <= gamma <= 4.0:
                    gamma_values.append(gamma)

    # 计算平均 Gamma
    gamma_estimate = None
    if gamma_values:
        gamma_estimate = sum(gamma_values) / len(gamma_values)

    return {
        "mean_error": total_error / len(measurements),
        "max_error": max_error,
        "max_error_point": max_error_point,
        "max_error_patch": max_error_patch,
        "dark_error": sum(dark_errors) / len(dark_errors) if dark_errors else 0.0,
        "bright_error": sum(bright_errors) / len(bright_errors) if bright_errors else 0.0,
        "mean_relative_error": total_relative_error / len(measurements),
        "gamma_estimate": gamma_estimate,
        "points": points,
    }


# ==============================================================================
# 黑场/白场识别辅助函数
# ==============================================================================

def identify_black_patch(measurements: list) -> Tuple[Optional[Dict], float]:
    """
    正确识别黑场测量点

    黑场识别规则：
    1. patchName == "0%" 或 "black" 或 "黑" 或 "Black"
    2. 如果没有明确标识，取 Y 值最小的点

    Args:
        measurements: 灰阶测量数据列表
            [{"patchName": str, "Y": float, "input": float, ...}, ...]

    Returns:
        Tuple[Optional[Dict], float]: (黑场数据点, 黑场亮度 Y)
    """
    if not measurements:
        return (None, 0.0)

    # 优先查找明确标识的黑场（精确匹配）
    black_exact_keywords = ["0%", "black", "黑", "Black", "Black level"]

    for m in measurements:
        patch_name = m.get("patchName", "").strip()
        patch_name_lower = patch_name.lower()

        # 精确匹配或包含关键词
        for keyword in black_exact_keywords:
            if patch_name == keyword or patch_name_lower == keyword.lower():
                return (m, m.get("Y", 0.0))

        # 特别检查：patchName 以 "0" 结尾或开头
        if patch_name_lower in ["0", "0%"]:
            return (m, m.get("Y", 0.0))

    # 如果没有明确标识，取 Y 值最小的点
    min_Y = float("inf")
    black_point = None

    for m in measurements:
        Y = m.get("Y", 0.0)
        if Y < min_Y:
            min_Y = Y
            black_point = m

    return (black_point, min_Y if black_point else 0.0)


def identify_white_patch(measurements: list, gamut_data: Dict = None) -> Tuple[Optional[Dict], float]:
    """
    正确识别白场测量点

    白场识别规则：
    1. 优先使用 gamut_data 中的白色数据
    2. patchName == "100%" 或 "white" 或 "白" 或 "White"
    3. 如果没有明确标识，取 Y 值最大的点

    Args:
        measurements: 灰阶测量数据列表
        gamut_data: 色域测量数据（包含 white）

    Returns:
        Tuple[Optional[Dict], float]: (白场数据点, 白场亮度 Y)
    """
    # 优先使用色域测量中的白场
    if gamut_data:
        white_data = gamut_data.get("white") or gamut_data.get("白")
        if white_data:
            Y = white_data.get("Y", 0.0)
            if isinstance(white_data.get("xyY"), (list, tuple)) and len(white_data.get("xyY")) >= 3:
                Y = white_data["xyY"][2]
            if Y > 0:
                return (white_data, Y)

    if not measurements:
        return (None, 100.0)

    # 查找明确标识的白场
    white_keywords = ["100%", "white", "白", "White", "100"]

    for m in measurements:
        patch_name = m.get("patchName", "").lower().strip()
        for keyword in white_keywords:
            if keyword.lower() in patch_name or patch_name == keyword.lower():
                return (m, m.get("Y", 100.0))

    # 如果没有明确标识，取 Y 值最大的点
    max_Y = 0.0
    white_point = None

    for m in measurements:
        Y = m.get("Y", 0.0)
        if Y > max_Y:
            max_Y = Y
            white_point = m

    return (white_point, max_Y if white_point else 100.0)


def prepare_measurements_for_eotf(
    raw_measurements: list,
    gamut_data: Dict = None
) -> Tuple[list, float, float]:
    """
    准备测量数据用于 EOTF 分析

    自动识别黑场和白场，规范化输入值，返回处理后的数据

    Args:
        raw_measurements: 原始灰阶测量数据
        gamut_data: 色域测量数据（用于获取白场）

    Returns:
        Tuple[list, float, float]: 
            - 处理后的测量数据（每点包含 input, Y, patchName）
            - 黑场亮度 Lb
            - 白场亮度 Lw
    """
    if not raw_measurements:
        return ([], 0.0, 100.0)

    # 识别黑场和白场
    black_point, Lb = identify_black_patch(raw_measurements)
    white_point, Lw = identify_white_patch(raw_measurements, gamut_data)

    processed = []

    for m in raw_measurements:
        patch_name = m.get("patchName", "")

        # 解析输入值（码值 0-1）
        input_val = m.get("input", None)

        if input_val is None:
            # 从 patchName 解析百分比
            if "%" in patch_name:
                try:
                    percent = float(patch_name.replace("%", "").strip())
                    input_val = percent / 100.0
                except ValueError:
                    input_val = None

            # 如果无法从 patchName 解析，从 RGB 估算
            if input_val is None:
                rgb = m.get("rgb", m.get("RGB", {}))
                if isinstance(rgb, dict):
                    r = rgb.get("r", rgb.get("R", 128))
                    g = rgb.get("g", rgb.get("G", 128))
                    b = rgb.get("b", rgb.get("B", 128))
                elif isinstance(rgb, (list, tuple)) and len(rgb) >= 3:
                    r, g, b = rgb[0], rgb[1], rgb[2]
                else:
                    r, g, b = 128, 128, 128

                # 灰阶时 R=G=B，取平均值
                input_val = ((r + g + b) / 3.0) / 255.0

        Y = m.get("Y", 0.0)

        processed.append({
            "input": input_val,
            "Y": Y,
            "patchName": patch_name,
        })

    return (processed, Lb, Lw)


def calculate_bt1886_with_measured_black(
    measurements: list,
    gamut_data: Dict = None,
    gamma: float = 2.4
) -> Dict:
    """
    使用实测黑场和白场计算 BT.1886 曲线误差

    这是正确实现 BT.1886 的方式：
    - Lw = 实测白场亮度
    - Lb = 实测黑场亮度（而非假设为 0）

    Args:
        measurements: 灰阶测量数据
        gamut_data: 色域测量数据
        gamma: Gamma 值（BT.1886 标准为 2.4）

    Returns:
        Dict: 包含曲线参数和误差统计
    """
    # 准备数据并识别黑场白场
    processed, Lb, Lw = prepare_measurements_for_eotf(measurements, gamut_data)

    if Lw <= Lb:
        return {
            "error": "白场亮度必须大于黑场亮度",
            "Lw": Lw,
            "Lb": Lb,
            "gamma": gamma,
        }

    # 计算与 BT.1886 曲线的误差
    errors = calculate_eotf_errors(processed, "BT.1886", Lw=Lw, Lb=Lb, gamma=gamma)

    return {
        "Lw": Lw,
        "Lb": Lb,
        "gamma": gamma,
        "curve_params": {
            "Lw": Lw,
            "Lb": Lb,
            "gamma": gamma,
        },
        "errors": errors,
        "points": processed,
    }


def generate_target_curve_data(
    curve: str,
    num_points: int = 51,
    **kwargs
) -> list:
    """
    生成目标曲线数据用于图表显示

    Args:
        curve: 曲线名称 ("gamma2.2", "sRGB", "BT.1886", "PQ", "HLG")
        num_points: 采样点数量
        **kwargs: 曲线参数 (Lw, Lb, L_max 等)

    Returns:
        list: [{"input": float, "target": float}, ...]
    """
    data = []
    step = 1.0 / (num_points - 1)

    for i in range(num_points):
        V = i * step
        Y = apply_eotf(V, curve, **kwargs)
        data.append({
            "input": V,
            "input_percent": V * 100,
            "target": Y,
        })

    return data
"""
色度学计算 - Chromatic Adaptation、Delta E、CCT/Duv

参考标准：
    - CIE 15:2004 - 色度学
    - CIE 116-1995 - CIEDE94
    - CIE 142-2001 - CIEDE2000
    - McCamy (1992) - CCT 近似公式
    - Robertson (1968) - CCT 等温线方法

本模块实现：
    - Bradford 和 CAT02 chromatic adaptation 变换
    - CIE Delta E 1976, 1994, 2000 计算
    - CCT（相关色温）和 Duv 计算
"""

import math
from typing import Tuple, Dict, Optional, List

from .spaces import (
    xyz_to_lab,
    lab_to_xyz,
    get_white_point_xyz,
    xyY_to_xyz,
    ILLUMINANTS,
)


# ==============================================================================
# Chromatic Adaptation 矩阵
# ==============================================================================

# Bradford 变换矩阵（用于白点适配）
# 来源：CIE TC1-32 白点适配研究
# 将 XYZ 转换到 Bradford cone response domain
BRADFORD_MATRIX: List[List[float]] = [
    [0.8951, 0.2664, -0.1614],
    [-0.7502, 1.7135, 0.0367],
    [0.0389, -0.0685, 1.0296],
]

# Bradford 逆矩阵
BRADFORD_MATRIX_INV: List[List[float]] = [
    [0.9869929, -0.1470543, 0.1599627],
    [0.4323053, 0.5183603, 0.0492912],
    [-0.0085287, 0.0400428, 0.9684867],
]

# CAT02 变换矩阵（CIE CAM02 标准）
CAT02_MATRIX: List[List[float]] = [
    [0.7328, 0.4296, -0.1624],
    [-0.7036, 1.6975, 0.0061],
    [0.0030, 0.0136, 0.9834],
]

# CAT02 逆矩阵
CAT02_MATRIX_INV: List[List[float]] = [
    [1.0961238, -0.2796302, 0.1568078],
    [-0.4552926, 0.8430043, 0.1165244],
    [0.0036558, -0.0105481, 1.0172170],
]


# ==============================================================================
# Chromatic Adaptation 函数
# ==============================================================================

def matrix_multiply(m: List[List[float]], v: List[float]) -> List[float]:
    """
    矩阵乘向量
    
    Args:
        m: 3x3 矩阵
        v: 3 维向量
        
    Returns:
        List[float]: 结果向量
    """
    return [
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    ]


def chromatic_adaptation(
    X: float, Y: float, Z: float,
    source_white: str,
    target_white: str,
    method: str = "bradford"
) -> Tuple[float, float, float]:
    """
    Chromatic Adaptation（白点适配）
    
    将 XYZ 从 source_white 适配到 target_white
    
    Args:
        X, Y, Z: 源 XYZ 值（Y 范围 0-100）
        source_white: 源白点名称
        target_white: 目标白点名称
        method: 变换方法 ("bradford" 或 "cat02")
        
    Returns:
        Tuple[float, float, float]: 适配后的 XYZ
    """
    # 获取白点 XYZ
    Xs, Ys, Zs = get_white_point_xyz(source_white)
    Xt, Yt, Zt = get_white_point_xyz(target_white)
    
    # 选择变换矩阵
    if method.lower() == "bradford":
        M = BRADFORD_MATRIX
        M_inv = BRADFORD_MATRIX_INV
    elif method.lower() == "cat02":
        M = CAT02_MATRIX
        M_inv = CAT02_MATRIX_INV
    else:
        raise ValueError(f"未知的白点适配方法: {method}")
    
    # 转换到 cone response domain
    rgb_source = matrix_multiply(M, [Xs, Ys, Zs])
    rgb_target = matrix_multiply(M, [Xt, Yt, Zt])
    
    # 计算增益
    # D = 1.0（完全适配）
    D = 1.0
    
    # 增益因子
    gain = [
        D * (rgb_target[i] / rgb_source[i]) + (1 - D)
        for i in range(3)
    ]
    
    # 转换输入 XYZ 到 cone domain
    rgb_input = matrix_multiply(M, [X, Y, Z])
    
    # 应用增益
    rgb_adapted = [rgb_input[i] * gain[i] for i in range(3)]
    
    # 转换回 XYZ
    xyz_adapted = matrix_multiply(M_inv, rgb_adapted)
    
    return (xyz_adapted[0], xyz_adapted[1], xyz_adapted[2])


def adapt_to_white_point(
    L: float, a: float, b: float,
    source_white: str,
    target_white: str,
    method: str = "bradford"
) -> Tuple[float, float, float]:
    """
    Lab 值白点适配
    
    先转换到 XYZ，做白点适配，再转换回 Lab
    
    Args:
        L, a, b: 源 Lab 值
        source_white: 源白点
        target_white: 目标白点
        method: 变换方法
        
    Returns:
        Tuple[float, float, float]: 适配后的 Lab
    """
    # Lab -> XYZ（使用源白点）
    X, Y, Z = lab_to_xyz(L, a, b, source_white)
    
    # 白点适配
    X_adapted, Y_adapted, Z_adapted = chromatic_adaptation(
        X, Y, Z, source_white, target_white, method
    )
    
    # XYZ -> Lab（使用目标白点）
    return xyz_to_lab(X_adapted, Y_adapted, Z_adapted, target_white)


# ==============================================================================
# Delta E 计算
# ==============================================================================

def delta_e_cie76(
    Lab1: Tuple[float, float, float],
    Lab2: Tuple[float, float, float]
) -> float:
    """
    CIE Delta E 1976（简单欧氏距离）
    
    ΔE_76 = sqrt((L2-L1)^2 + (a2-a1)^2 + (b2-b1)^2)
    
    Args:
        Lab1: 第一个颜色的 (L*, a*, b*)
        Lab2: 第二个颜色的 (L*, a*, b*)
        
    Returns:
        float: Delta E 1976 值
    """
    L1, a1, b1 = Lab1
    L2, a2, b2 = Lab2
    
    return math.sqrt(
        (L2 - L1) ** 2 +
        (a2 - a1) ** 2 +
        (b2 - b1) ** 2
    )


def delta_e_cie94(
    Lab1: Tuple[float, float, float],
    Lab2: Tuple[float, float, float],
    kL: float = 1.0,
    kC: float = 1.0,
    kH: float = 1.0,
    application: str = "graphic_arts"
) -> float:
    """
    CIE Delta E 1994
    
    改进的色差公式，考虑 C* 和 h 的权重
    
    参数设置：
    - graphic_arts: kL=1, kC=1, kH=1
    - textiles: kL=2, kC=1, kH=1
    
    Args:
        Lab1, Lab2: 两个颜色的 Lab 值
        kL, kC, kH: 权重因子
        application: 应用类型
        
    Returns:
        float: Delta E 1994 值
    """
    L1, a1, b1 = Lab1
    L2, a2, b2 = Lab2
    
    # 计算 C* 和 ΔC*
    C1 = math.sqrt(a1 ** 2 + b1 ** 2)
    C2 = math.sqrt(a2 ** 2 + b2 ** 2)
    C_avg = (C1 + C2) / 2
    
    delta_L = L2 - L1
    delta_C = C2 - C1
    
    # 计算 Δa* 和 Δb*（校正后）
    delta_a = a2 - a1
    delta_b = b2 - b1
    
    # 计算 ΔH*
    delta_H_sq = delta_a ** 2 + delta_b ** 2 - delta_C ** 2
    delta_H = math.sqrt(max(0, delta_H_sq))
    
    # 权重因子
    S_L = 1.0
    S_C = 1.0 + 0.045 * C_avg
    S_H = 1.0 + 0.015 * C_avg
    
    # 计算 Delta E 1994
    delta_E = math.sqrt(
        (delta_L / (kL * S_L)) ** 2 +
        (delta_C / (kC * S_C)) ** 2 +
        (delta_H / (kH * S_H)) ** 2
    )
    
    return delta_E


def delta_e_ciede2000(
    Lab1: Tuple[float, float, float],
    Lab2: Tuple[float, float, float],
    kL: float = 1.0,
    kC: float = 1.0,
    kH: float = 1.0
) -> float:
    """
    CIE Delta E 2000 (CIEDE2000)
    
    最精确的色差公式，考虑：
    - C* 的权重变化
    - hue 角度的影响
    - 中性色区域的改进
    
    参考：Sharma, Wu, Dalal (2005) "The CIEDE2000 Color-Difference Formula"
    
    Args:
        Lab1, Lab2: 两个颜色的 Lab 值
        kL, kC, kH: 权重因子（默认 1.0）
        
    Returns:
        float: Delta E 2000 值
    """
    L1, a1, b1 = Lab1
    L2, a2, b2 = Lab2
    
    # ========== Step 1: 计算 C*_i 和 h_i ==========
    C1 = math.sqrt(a1 ** 2 + b1 ** 2)
    C2 = math.sqrt(a2 ** 2 + b2 ** 2)
    C_avg = (C1 + C2) / 2
    
    # G 因子（C* 相关的 a' 调整）
    G = 0.5 * (1 - math.sqrt(C_avg ** 7 / (C_avg ** 7 + 25 ** 7)))
    
    # 计算 a'_i
    a1_prime = a1 * (1 + G)
    a2_prime = a2 * (1 + G)
    
    # 计算 C'_i
    C1_prime = math.sqrt(a1_prime ** 2 + b1 ** 2)
    C2_prime = math.sqrt(a2_prime ** 2 + b2 ** 2)
    
    # 计算 h'_i
    def calc_h_prime(a_prime: float, b: float) -> float:
        if a_prime == 0 and b == 0:
            return 0.0
        h = math.degrees(math.atan2(b, a_prime))
        if h < 0:
            h += 360
        return h
    
    h1_prime = calc_h_prime(a1_prime, b1)
    h2_prime = calc_h_prime(a2_prime, b2)
    
    # ========== Step 2: 计算 ΔL', ΔC', ΔH' ==========
    delta_L_prime = L2 - L1
    delta_C_prime = C2_prime - C1_prime
    
    # 计算 Δh'
    if C1_prime * C2_prime == 0:
        delta_h_prime = 0.0
    else:
        diff = h2_prime - h1_prime
        if abs(diff) <= 180:
            delta_h_prime = diff
        elif diff > 180:
            delta_h_prime = diff - 360
        else:
            delta_h_prime = diff + 360
    
    # 计算 ΔH'
    delta_H_prime = 2 * math.sqrt(C1_prime * C2_prime) * math.sin(math.radians(delta_h_prime / 2))
    
    # ========== Step 3: 计算 CIEDE2000 ==========
    L_prime_avg = (L1 + L2) / 2
    C_prime_avg = (C1_prime + C2_prime) / 2
    
    # 计算 h'_avg
    if C1_prime * C2_prime == 0:
        h_prime_avg = h1_prime + h2_prime
    else:
        if abs(h1_prime - h2_prime) <= 180:
            h_prime_avg = (h1_prime + h2_prime) / 2
        else:
            if h1_prime + h2_prime < 360:
                h_prime_avg = (h1_prime + h2_prime + 360) / 2
            else:
                h_prime_avg = (h1_prime + h2_prime - 360) / 2
    
    # T 因子
    T = (
        1 - 0.17 * math.cos(math.radians(h_prime_avg - 30))
        + 0.24 * math.cos(math.radians(2 * h_prime_avg))
        + 0.32 * math.cos(math.radians(3 * h_prime_avg + 6))
        - 0.20 * math.cos(math.radians(4 * h_prime_avg - 63))
    )
    
    # SL, SC, SH 权重因子
    S_L = 1 + (0.015 * (L_prime_avg - 50) ** 2) / math.sqrt(20 + (L_prime_avg - 50) ** 2)
    S_C = 1 + 0.045 * C_prime_avg
    S_H = 1 + 0.015 * C_prime_avg * T
    
    # RT（旋转项）
    delta_theta = 30 * math.exp(-((h_prime_avg - 275) / 25) ** 2)
    R_C = 2 * math.sqrt(C_prime_avg ** 7 / (C_prime_avg ** 7 + 25 ** 7))
    R_T = -math.sin(math.radians(2 * delta_theta)) * R_C
    
    # 计算 Delta E 2000
    delta_E = math.sqrt(
        (delta_L_prime / (kL * S_L)) ** 2 +
        (delta_C_prime / (kC * S_C)) ** 2 +
        (delta_H_prime / (kH * S_H)) ** 2 +
        R_T * (delta_C_prime / (kC * S_C)) * (delta_H_prime / (kH * S_H))
    )
    
    return delta_E


def delta_e_from_xyY(
    xyY1: Tuple[float, float, float],
    xyY2: Tuple[float, float, float],
    white_point: str = "D65",
    method: str = "ciede2000",
    adapt: bool = True,
    source_white1: Optional[str] = None,
    source_white2: Optional[str] = None
) -> float:
    """
    从 xyY 计算 Delta E
    
    Args:
        xyY1: 第一个颜色的 (x, y, Y)
        xyY2: 第二个颜色的 (x, y, Y)
        white_point: 计算 Lab 使用的参考白点
        method: Delta E 方法 ("cie76", "cie94", "ciede2000")
        adapt: 是否做白点适配
        source_white1, source_white2: 各颜色的源白点（用于适配）
        
    Returns:
        float: Delta E 值
    """
    x1, y1, Y1 = xyY1
    x2, y2, Y2 = xyY2
    
    # xyY -> XYZ
    X1, Y1_xyz, Z1 = xyY_to_xyz(x1, y1, Y1)
    X2, Y2_xyz, Z2 = xyY_to_xyz(x2, y2, Y2)
    
    # 白点适配（如果需要）
    if adapt and source_white1 and source_white2:
        if source_white1 != white_point:
            X1, Y1_xyz, Z1 = chromatic_adaptation(X1, Y1_xyz, Z1, source_white1, white_point)
        if source_white2 != white_point:
            X2, Y2_xyz, Z2 = chromatic_adaptation(X2, Y2_xyz, Z2, source_white2, white_point)
    
    # XYZ -> Lab
    Lab1 = xyz_to_lab(X1, Y1_xyz, Z1, white_point)
    Lab2 = xyz_to_lab(X2, Y2_xyz, Z2, white_point)
    
    # 计算 Delta E
    if method == "cie76":
        return delta_e_cie76(Lab1, Lab2)
    elif method == "cie94":
        return delta_e_cie94(Lab1, Lab2)
    elif method == "ciede2000":
        return delta_e_ciede2000(Lab1, Lab2)
    elif method == "itp":
        # HDR 色差：BT.2124 ΔE ITP（基于 PQ 绝对亮度）
        return delta_e_itp(
            (X1, Y1_xyz, Z1), (X2, Y2_xyz, Z2)
        )
    else:
        raise ValueError(f"未知的 Delta E 方法: {method}")


# ==============================================================================
# ΔE ITP (ITU-R BT.2124) - HDR 色差度量
# ==============================================================================

# BT.2124 Annex 2 Conversion 1: CIE XYZ(绝对亮度) → BT.2100 显示参考线性 RGB
_ITP_XYZ_TO_RGB = [
    [1.716651187971268, -0.355670783776392, -0.253366281373660],
    [-0.666684351832489, 1.616481236634939, 0.015768545813911],
    [0.017639857445311, -0.042770613257809, 0.942103121235474],
]

# BT.2100 Table 7: 线性 RGB → LMS
_ITP_RGB_TO_LMS = [
    [1688.0, 2146.0, 262.0],
    [683.0, 2951.0, 462.0],
    [99.0, 309.0, 3688.0],
]
_ITP_LMS_DIV = 4096.0

# BT.2100 Table 7: L'M'S' → CT/CP（再经 ITP 缩放 T=0.5·CT, P=CP）
_ITP_LMSP_TO_CT = [6610.0, -13613.0, 7003.0]
_ITP_LMSP_TO_CP = [17933.0, -17390.0, -543.0]

# BT.2124 Step 5: ΔE_ITP 缩放因子（1 ΔE_ITP ≈ 1 JND）
_ITP_SCALE = 720.0


def xyz_to_itp(X: float, Y: float, Z: float) -> Tuple[float, float, float]:
    """
    绝对 XYZ (cd/m²) → ITP 色空间（ITU-R BT.2124 / BT.2100 ICTCP 派生）

    流程（BT.2124 Annex 1）：
        XYZ --Annex2--> 显示参考线性 RGB --Table7--> LMS
        --PQ 逆 EOTF(L_max=10000)--> L'M'S' --Table7--> ICTP --Step4--> ITP

    Args:
        X, Y, Z: 绝对三刺激值（Y 单位 cd/m²）

    Returns:
        (I, T, P) 坐标
    """
    from .transfer import eotf_pq_inverse

    # XYZ → 线性 RGB
    R = (_ITP_XYZ_TO_RGB[0][0] * X + _ITP_XYZ_TO_RGB[0][1] * Y + _ITP_XYZ_TO_RGB[0][2] * Z)
    G = (_ITP_XYZ_TO_RGB[1][0] * X + _ITP_XYZ_TO_RGB[1][1] * Y + _ITP_XYZ_TO_RGB[1][2] * Z)
    B = (_ITP_XYZ_TO_RGB[2][0] * X + _ITP_XYZ_TO_RGB[2][1] * Y + _ITP_XYZ_TO_RGB[2][2] * Z)

    # RGB → LMS
    L = (_ITP_RGB_TO_LMS[0][0] * R + _ITP_RGB_TO_LMS[0][1] * G + _ITP_RGB_TO_LMS[0][2] * B) / _ITP_LMS_DIV
    M = (_ITP_RGB_TO_LMS[1][0] * R + _ITP_RGB_TO_LMS[1][1] * G + _ITP_RGB_TO_LMS[1][2] * B) / _ITP_LMS_DIV
    S = (_ITP_RGB_TO_LMS[2][0] * R + _ITP_RGB_TO_LMS[2][1] * G + _ITP_RGB_TO_LMS[2][2] * B) / _ITP_LMS_DIV

    # LMS → L'M'S'（PQ 逆 EOTF，L_max=10000）
    Lp = eotf_pq_inverse(max(L, 0.0))
    Mp = eotf_pq_inverse(max(M, 0.0))
    Sp = eotf_pq_inverse(max(S, 0.0))

    # L'M'S' → ICTP → ITP
    I = 0.5 * Lp + 0.5 * Mp
    CT = (_ITP_LMSP_TO_CT[0] * Lp + _ITP_LMSP_TO_CT[1] * Mp + _ITP_LMSP_TO_CT[2] * Sp) / _ITP_LMS_DIV
    CP = (_ITP_LMSP_TO_CP[0] * Lp + _ITP_LMSP_TO_CP[1] * Mp + _ITP_LMSP_TO_CP[2] * Sp) / _ITP_LMS_DIV

    return (I, 0.5 * CT, CP)


def delta_e_itp(
    XYZ1: Tuple[float, float, float],
    XYZ2: Tuple[float, float, float],
) -> float:
    """
    BT.2124 ΔE ITP —— HDR 专用色差（1 ΔE_ITP ≈ 1 最小可觉色差 JND）

    ΔE_ITP = 720 * sqrt(ΔI² + ΔT² + ΔP²)

    Args:
        XYZ1, XYZ2: 两个颜色的绝对 XYZ（Y 单位 cd/m²）

    Returns:
        float: ΔE ITP 值
    """
    I1, T1, P1 = xyz_to_itp(*XYZ1)
    I2, T2, P2 = xyz_to_itp(*XYZ2)

    return _ITP_SCALE * math.sqrt(
        (I2 - I1) ** 2 + (T2 - T1) ** 2 + (P2 - P1) ** 2
    )


def delta_e_itp_components(
    XYZ1: Tuple[float, float, float],
    XYZ2: Tuple[float, float, float],
) -> Dict[str, float]:
    """
    BT.2124 ΔE ITP 分解：亮度分量 ΔE_I 与色度分量 ΔE_CT

    ΔE_I  = 720 * |ΔI|         （亮度误差）
    ΔE_CT = 720 * sqrt(ΔT²+ΔP²)（色度误差）
    总 ΔE_ITP = sqrt(ΔE_I² + ΔE_CT²)

    Args:
        XYZ1, XYZ2: 两个颜色的绝对 XYZ（Y 单位 cd/m²）

    Returns:
        {"itp": 总, "i": 亮度分量, "ct": 色度分量}
    """
    I1, T1, P1 = xyz_to_itp(*XYZ1)
    I2, T2, P2 = xyz_to_itp(*XYZ2)

    d_I = _ITP_SCALE * abs(I2 - I1)
    d_CT = _ITP_SCALE * math.sqrt((T2 - T1) ** 2 + (P2 - P1) ** 2)

    return {
        "itp": math.sqrt(d_I ** 2 + d_CT ** 2),
        "i": d_I,
        "ct": d_CT,
    }


def delta_e_itp_from_xyY(
    xyY1: Tuple[float, float, float],
    xyY2: Tuple[float, float, float],
) -> Dict[str, float]:
    """
    从 xyY（Y 为绝对亮度 cd/m²）计算 ΔE ITP 及其分量

    Args:
        xyY1, xyY2: 两个颜色的 (x, y, Y)

    Returns:
        {"itp": 总, "i": 亮度分量, "ct": 色度分量}
    """
    XYZ1 = xyY_to_xyz(*xyY1)
    XYZ2 = xyY_to_xyz(*xyY2)
    return delta_e_itp_components(XYZ1, XYZ2)


# ==============================================================================
# Lab <-> LCH 转换
# ==============================================================================

def lab_to_lch(L: float, a: float, b: float) -> Tuple[float, float, float]:
    """
    Lab 到 LCH（亮度-色度-色调）
    
    Args:
        L, a, b: Lab 值
        
    Returns:
        Tuple[float, float, float]: (L, C, h) - L*, C*, hue angle (度)
    """
    C = math.sqrt(a ** 2 + b ** 2)
    
    if a == 0 and b == 0:
        h = 0.0
    else:
        h = math.degrees(math.atan2(b, a))
        if h < 0:
            h += 360
    
    return (L, C, h)


def lch_to_lab(L: float, C: float, h: float) -> Tuple[float, float, float]:
    """
    LCH 到 Lab
    
    Args:
        L, C, h: LCH 值（h 为角度）
        
    Returns:
        Tuple[float, float, float]: (L, a, b)
    """
    a = C * math.cos(math.radians(h))
    b = C * math.sin(math.radians(h))
    
    return (L, a, b)


# ==============================================================================
# CCT（相关色温）和 Duv 计算
# ==============================================================================

# Planckian 轨迹的等温线数据（Robertson 方法）
# 格式：(T(K), u, v) - 黑体轨迹上的点
ROBERTSON_ISOTHERMS: List[Tuple[float, float, float]] = [
    # 低色温到高色温
    (1000, 0.3604, 0.3548),
    (1500, 0.3384, 0.3568),
    (2000, 0.3228, 0.3578),
    (2500, 0.3106, 0.3576),
    (3000, 0.3010, 0.3564),
    (3500, 0.2932, 0.3550),
    (4000, 0.2868, 0.3534),
    (4500, 0.2814, 0.3516),
    (5000, 0.2768, 0.3498),
    (5500, 0.2730, 0.3478),
    (6000, 0.2698, 0.3458),
    (6500, 0.2670, 0.3436),
    (7000, 0.2646, 0.3416),
    (7500, 0.2626, 0.3396),
    (8000, 0.2608, 0.3376),
    (9000, 0.2580, 0.3340),
    (10000, 0.2556, 0.3308),
    (15000, 0.2494, 0.3224),
    (20000, 0.2464, 0.3170),
    (25000, 0.2444, 0.3134),
    (30000, 0.2432, 0.3108),
    (40000, 0.2418, 0.3080),
    (50000, 0.2410, 0.3064),
    (100000, 0.2394, 0.3028),
]


def xy_to_uv_1976(x: float, y: float) -> Tuple[float, float]:
    """
    CIE xy 到 CIE 1976 u'v'

    u' = 4x / (-2x + 12y + 3)
    v' = 9y / (-2x + 12y + 3)

    Args:
        x, y: CIE xy 坐标

    Returns:
        Tuple[float, float]: (u', v')
    """
    denominator = -2.0 * x + 12.0 * y + 3.0
    if denominator == 0:
        return (0.0, 0.0)

    u = 4.0 * x / denominator
    v = 9.0 * y / denominator

    return (u, v)


def xy_to_uv_1960(x: float, y: float) -> Tuple[float, float]:
    """
    CIE xy 到 CIE 1960 uv

    Robertson 等温线方法使用此坐标系

    u = 4x / (-2x + 12y + 3)
    v = 6y / (-2x + 12y + 3)

    注意：CIE 1960 uv 和 CIE 1976 u'v' 的关系：
    - u' = u (相同)
    - v' = 1.5v

    Args:
        x, y: CIE xy 坐标

    Returns:
        Tuple[float, float]: (u, v) - CIE 1960 坐标
    """
    denominator = -2.0 * x + 12.0 * y + 3.0
    if denominator == 0:
        return (0.0, 0.0)

    u = 4.0 * x / denominator
    v = 6.0 * y / denominator  # CIE 1960 使用 6y 而不是 9y

    return (u, v)


def uv_1960_to_uv_1976(u: float, v: float) -> Tuple[float, float]:
    """
    CIE 1960 uv 到 CIE 1976 u'v'

    u' = u
    v' = 1.5v

    Args:
        u, v: CIE 1960 uv 坐标

    Returns:
        Tuple[float, float]: (u', v') - CIE 1976 坐标
    """
    return (u, 1.5 * v)


def uv_1976_to_uv_1960(u: float, v: float) -> Tuple[float, float]:
    """
    CIE 1976 u'v' 到 CIE 1960 uv

    u = u'
    v = v' / 1.5

    Args:
        u, v: CIE 1976 u'v' 坐标

    Returns:
        Tuple[float, float]: (u, v) - CIE 1960 坐标
    """
    return (u, v / 1.5)


def uv_to_xy_1976(u: float, v: float) -> Tuple[float, float]:
    """
    CIE 1976 u'v' 到 CIE xy

    Args:
        u, v: CIE 1976 u'v' 坐标

    Returns:
        Tuple[float, float]: (x, y)

    公式推导：
        从 xy 到 u'v':
        u' = 4x / (-2x + 12y + 3)
        v' = 9y / (-2x + 12y + 3)

        设 D = -2x + 12y + 3，则 u' = 4x/D, v' = 9y/D
        解出 D = 18 / (6 + 3u' - 8v')
        因此 x = 9u'/[2(6 + 3u' - 8v')], y = 2v'/(6 + 3u' - 8v')
    """
    denominator = 6.0 + 3.0 * u - 8.0 * v
    if denominator == 0:
        return (0.0, 0.0)

    x = 9.0 * u / (2.0 * denominator)
    y = 2.0 * v / denominator

    return (x, y)


def xy_to_cct_mccamy(x: float, y: float) -> float:
    """
    McCamy 近似公式计算 CCT
    
    适用于 D 系列光源附近的色温估计
    
    CCT = 449n^3 + 3525n^2 + 6823.3n + 5520.33
    n = (x - 0.3320) / (0.1858 - y)
    
    Args:
        x, y: CIE xy 坐标
        
    Returns:
        float: 相关色温 (K)
    """
    n = (x - 0.3320) / (0.1858 - y)
    
    cct = 449.0 * n ** 3 + 3525.0 * n ** 2 + 6823.3 * n + 5520.33
    
    # 限制范围
    return max(1000.0, min(40000.0, cct))


def xy_to_cct_robertson(x: float, y: float) -> float:
    """
    Robertson 等温线方法计算 CCT

    真正的 Robertson 方法：使用等温线斜率进行精确插值
    使用 CIE 1960 uv 色度坐标（Robertson 等温线数据的标准坐标系）

    参考：Robertson (1968) "Computation of Correlated Color Temperature
    and Distribution Temperature"

    Args:
        x, y: CIE xy 坐标

    Returns:
        float: 相关色温 (K)
    """
    # 使用 CIE 1960 uv 坐标（Robertson 等温线数据的坐标系）
    u, v = xy_to_uv_1960(x, y)

    # Robertson 等温线方法
    # 每条等温线有一个斜率（m_i）和一个位置（u_i, v_i）
    # 在两条等温线之间进行线性插值

    best_T = 6500.0

    for i in range(1, len(ROBERTSON_ISOTHERMS)):
        T1, u1, v1 = ROBERTSON_ISOTHERMS[i - 1]
        T2, u2, v2 = ROBERTSON_ISOTHERMS[i]

        # 等温线斜率（垂直于轨迹）
        # 轨迹方向：(u2-u1, v2-v1)
        # 等温线方向（垂直）：需要计算斜率
        if v2 - v1 == 0:
            continue

        # 等温线斜率 m = -(u2-u1)/(v2-v1)
        m = -(u2 - u1) / (v2 - v1)

        # 计算到两条等温线的距离（带符号）
        # 使用点-线距离公式：d = (v - v1) - m*(u - u1)
        d1 = (v - v1) - m * (u - u1)
        d2 = (v - v2) - m * (u - u2)

        # 如果测试点在这两条等温线之间，进行插值
        if d1 * d2 <= 0:
            # 线性插值 CCT
            if abs(d1) + abs(d2) > 0:
                t = abs(d2) / (abs(d1) + abs(d2))
                best_T = T1 + t * (T2 - T1)
            break

    return best_T


def xy_to_cct_robertson_duv(x: float, y: float) -> Tuple[float, float]:
    """
    Robertson 等温线方法计算 CCT 和 Duv（精确版）

    使用 CIE 1960 uv 坐标进行计算，然后转换 Duv 到 CIE 1976 u'v' 坐标

    Args:
        x, y: CIE xy 坐标

    Returns:
        Tuple[float, float]: (CCT, Duv)
    """
    # 使用 CIE 1960 uv 坐标
    u, v = xy_to_uv_1960(x, y)

    best_T = 6500.0
    best_duv_1960 = 0.0  # CIE 1960 坐标系中的 Duv

    for i in range(1, len(ROBERTSON_ISOTHERMS)):
        T1, u1, v1 = ROBERTSON_ISOTHERMS[i - 1]
        T2, u2, v2 = ROBERTSON_ISOTHERMS[i]

        if v2 - v1 == 0:
            continue

        # 等温线斜率（垂直于轨迹）
        m = -(u2 - u1) / (v2 - v1)

        # 计算到等温线的距离
        d1 = (v - v1) - m * (u - u1)
        d2 = (v - v2) - m * (u - u2)

        if d1 * d2 <= 0:
            if abs(d1) + abs(d2) > 0:
                t = abs(d2) / (abs(d1) + abs(d2))
                best_T = T1 + t * (T2 - T1)

                # Duv 计算（CIE 1960 坐标系）
                best_duv_1960 = d1 / math.sqrt(1 + m ** 2)

            break

    # 转换 Duv 到 CIE 1976 坐标系
    # Duv_1976 = 1.5 * Duv_1960
    best_duv = 1.5 * best_duv_1960

    return (best_T, best_duv)


def cct_to_xy(cct: float) -> Tuple[float, float]:
    """
    从 CCT 计算 Planckian 轨迹上的 xy 坐标
    
    使用黑体辐射公式
    
    Args:
        cct: 相关色温 (K)
        
    Returns:
        Tuple[float, float]: (x, y) 坐标
    """
    # Planck 辐射公式的近似（用于计算 xy）
    # 基于 Kang et al. 的近似公式
    
    if cct < 1667:
        cct = 1667
    elif cct > 25000:
        cct = 25000
    
    if cct <= 4000:
        # 低色温区间
        x = -0.2661239e9 / cct ** 3 - 0.2343589e6 / cct ** 2 + 0.8776956e3 / cct + 0.179910
    else:
        # 高色温区间
        x = -3.0258469e9 / cct ** 3 + 2.1070379e6 / cct ** 2 + 0.2226347e3 / cct + 0.240390
    
    if cct <= 2222:
        y = -1.1063814 * x ** 3 - 1.34811020 * x ** 2 + 2.18555832 * x - 0.20219683
    elif cct <= 4000:
        y = -0.9549476 * x ** 3 - 1.37418593 * x ** 2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x ** 3 - 5.87338670 * x ** 2 + 3.75112997 * x - 0.37001483
    
    return (x, y)


def calculate_duv(x: float, y: float, cct: Optional[float] = None) -> float:
    """
    计算 Duv（到 Planckian 轨迹的距离）
    
    Duv 表示颜色偏离等温线的程度：
    - 正值：偏黄（高于 Planckian 轨迹）
    - 负值：偏蓝（低于 Planckian 轨迹）
    
    Args:
        x, y: CIE xy 坐标
        cct: 相关色温（如果未提供，会自动计算）
        
    Returns:
        float: Duv 值（正或负）
    """
    # 计算 CCT
    if cct is None:
        cct = xy_to_cct_robertson(x, y)
    
    # Planckian 轨迹上对应 CCT 的 xy
    x_planck, y_planck = cct_to_xy(cct)
    
    # 转换到 u'v'
    u, v = xy_to_uv_1976(x, y)
    u_planck, v_planck = xy_to_uv_1976(x_planck, y_planck)
    
    # 计算 Duv
    # Duv 是从测试点到 Planckian 轨迹的垂直距离
    # 需要确定方向（正或负）
    
    # 等温线方向（垂直于轨迹）
    # 在轨迹点附近的等温线
    for T, Ti_u, Ti_v in ROBERTSON_ISOTHERMS:
        if abs(T - cct) < 500:
            # 计算等温线方向
            u_ref, v_ref = Ti_u, Ti_v
            break
    
    # 使用简化的 Duv 计算
    # Duv ≈ sqrt((u-u_p)^2 + (v-v_p)^2) * sign(v - v_p)
    distance = math.sqrt((u - u_planck) ** 2 + (v - v_planck) ** 2)
    
    # 方向：v > v_planck 为正（偏黄）
    sign = 1.0 if v > v_planck else -1.0
    
    return sign * distance


def cct_duv_from_xy(x: float, y: float) -> Tuple[float, float]:
    """
    从 xy 计算 CCT 和 Duv

    使用 McCamy 近似计算 CCT，使用 Planckian 轨迹距离计算 Duv

    Args:
        x, y: CIE xy 坐标

    Returns:
        Tuple[float, float]: (CCT, Duv)
    """
    # 使用 McCamy 近似计算 CCT（对 D 系列光源准确）
    cct = xy_to_cct_mccamy(x, y)

    # 计算 Duv（使用 Planckian 轨迹距离）
    duv = calculate_duv(x, y, cct)

    return (cct, duv)


# ==============================================================================
# 白点偏差计算
# ==============================================================================

def calculate_white_point_error(
    measured_x: float, measured_y: float,
    target_x: float, target_y: float
) -> Dict:
    """
    计算白点偏差
    
    Args:
        measured_x, measured_y: 测量白点
        target_x, target_y: 目标白点
        
    Returns:
        Dict: 偏差信息
            - delta_uv: u'v' 色差
            - delta_xy: xy 距离
            - delta_E: Delta E (CIEDE2000, Y=100)
            - cct_measured: 测量 CCT
            - cct_target: 目标 CCT
            - duv_measured: 测量 Duv
            - direction: 偏移方向描述
    """
    # u'v' 计算
    u_m, v_m = xy_to_uv_1976(measured_x, measured_y)
    u_t, v_t = xy_to_uv_1976(target_x, target_y)
    
    delta_u = u_m - u_t
    delta_v = v_m - v_t
    delta_uv = math.sqrt(delta_u ** 2 + delta_v ** 2)
    
    # Delta E (Y = 100)
    delta_E = delta_e_from_xyY(
        (measured_x, measured_y, 100.0),
        (target_x, target_y, 100.0),
        method="ciede2000",
        adapt=False
    )
    
    # CCT 和 Duv
    cct_measured, duv_measured = cct_duv_from_xy(measured_x, measured_y)
    cct_target, duv_target = cct_duv_from_xy(target_x, target_y)
    
    # 偏移方向
    if abs(delta_v) > 0.005:
        if delta_v > 0:
            direction = "偏黄/偏绿" if delta_u > 0 else "偏黄/偏红"
        else:
            direction = "偏蓝/偏紫" if delta_u < 0 else "偏蓝/偏绿"
    else:
        direction = "中性偏移"
    
    return {
        "delta_uv": delta_uv,
        "delta_xy": math.sqrt((measured_x - target_x) ** 2 + (measured_y - target_y) ** 2),
        "delta_E": delta_E,
        "cct_measured": cct_measured,
        "cct_target": cct_target,
        "cct_offset": cct_measured - cct_target,
        "duv_measured": duv_measured,
        "duv_target": duv_target,
        "duv_offset": duv_measured - duv_target,
        "direction": direction,
    }
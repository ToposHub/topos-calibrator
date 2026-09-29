"""
色彩空间定义与转换 - RGB色彩空间、白点、转换矩阵

参考标准：
    - CIE 15:2004 - 色度学
    - IEC 61966-2-1:1999 - sRGB
    - SMPTE RP 431-2 - DCI-P3
    - BT.2020/BT.2100 - Rec.2020
    - Bruce Lindbloom (http://www.brucelindbloom.com)

本模块使用 2° 标准观察者（CIE 1931）数据。
"""

import math
from typing import Tuple, Dict, Optional, List

# ==============================================================================
# 白点与光源定义
# ==============================================================================

# CIE 标准光源（2° 标准观察者）
# XYZ 值已归一化至 Y = 100
ILLUMINANTS: Dict[str, Tuple[float, float, float]] = {
    # 标准光源 A（钨丝灯，约 2856K）
    "A": (109.850, 100.000, 35.585),
    
    # 标准光源 B（直射阳光，约 4874K）- 已废弃
    "B": (99.0927, 100.000, 85.313),
    
    # 标准光源 C（平均日光，约 6774K）
    "C": (98.074, 100.000, 118.232),
    
    # D50（地平线光，5000K）- 摄影标准
    "D50": (96.422, 100.000, 82.521),
    
    # D55（中午日光，5500K）
    "D55": (95.682, 100.000, 92.149),
    
    # D60（6000K）
    "D60": (95.026, 100.000, 100.874),
    
    # D65（平均日光，6500K）- sRGB/Rec.709/Rec.2020 标准
    "D65": (95.047, 100.000, 108.883),
    
    # D75（北方日光，7500K）
    "D75": (94.972, 100.000, 122.638),
    
    # E（等能光源）
    "E": (100.000, 100.000, 100.000),
    
    # F系列荧光灯
    "F2": (99.186, 100.000, 67.393),   # 冷白荧光
    "F7": (95.044, 100.000, 108.755),  # D65模拟器
    "F11": (100.966, 100.000, 64.370), # TL84
}

# 白点的 CIE xy 坐标（从 XYZ 计算）
WHITE_POINTS: Dict[str, Tuple[float, float]] = {
    "A": (0.44757, 0.40745),
    "B": (0.34842, 0.35161),
    "C": (0.31006, 0.31616),
    "D50": (0.34567, 0.35850),
    "D55": (0.33242, 0.34743),
    "D60": (0.32168, 0.33767),
    "D65": (0.31271, 0.32902),
    "D75": (0.29902, 0.31483),
    "E": (0.33333, 0.33333),
    "F2": (0.37207, 0.37450),  # 从 ILLUMINANTS["F2"] XYZ 值计算
    "F7": (0.31285, 0.32918),
    "F11": (0.38054, 0.37691),
}


def get_white_point_xyz(name: str) -> Tuple[float, float, float]:
    """
    获取白点的 XYZ 三刺激值
    
    Args:
        name: 白点名称（如 "D65", "D50"）
        
    Returns:
        Tuple[float, float, float]: (X, Y, Z) 值，Y = 100
        
    Raises:
        KeyError: 如果白点名称未知
    """
    if name not in ILLUMINANTS:
        raise KeyError(f"未知的白点名称: {name}. 支持的白点: {list(ILLUMINANTS.keys())}")
    return ILLUMINANTS[name]


def get_white_point_xy(name: str) -> Tuple[float, float]:
    """
    获取白点的 CIE xy 坐标
    
    Args:
        name: 白点名称
        
    Returns:
        Tuple[float, float]: (x, y) 坐标
    """
    if name not in WHITE_POINTS:
        raise KeyError(f"未知的白点名称: {name}")
    return WHITE_POINTS[name]


# ==============================================================================
# 色彩空间定义
# ==============================================================================

# 各色彩空间的 primaries（CIE xy 坐标）
COLOR_SPACES: Dict[str, Dict] = {
    "sRGB": {
        "red": (0.6400, 0.3300),
        "green": (0.3000, 0.6000),
        "blue": (0.1500, 0.0600),
        "white": "D65",
        "description": "sRGB (IEC 61966-2-1)",
        "category": "基础",
    },
    "Rec709": {
        "red": (0.6400, 0.3300),
        "green": (0.3000, 0.6000),
        "blue": (0.1500, 0.0600),
        "white": "D65",
        "description": "Rec.709 (BT.709) - HD视频标准",
        "category": "基础",
    },
    "DCI_P3": {
        "red": (0.6800, 0.3200),
        "green": (0.2650, 0.6900),
        "blue": (0.1500, 0.0600),
        "white": "DCI",  # DCI 白点 (~6300K)
        "description": "DCI-P3 (SMPTE RP 431-2)",
        "category": "宽色域",
    },
    "DisplayP3": {
        "red": (0.6800, 0.3200),
        "green": (0.2650, 0.6900),
        "blue": (0.1500, 0.0600),
        "white": "D65",
        "description": "Display P3 - Apple/DCI-P3 D65版本",
        "category": "宽色域",
    },
    "AdobeRGB": {
        "red": (0.6400, 0.3300),
        "green": (0.2100, 0.7100),
        "blue": (0.1500, 0.0600),
        "white": "D65",
        "description": "Adobe RGB (1998)",
        "category": "宽色域",
    },
    "Rec2020": {
        "red": (0.7080, 0.2920),
        "green": (0.1700, 0.7970),
        "blue": (0.1310, 0.0460),
        "white": "D65",
        "description": "Rec.2020 (BT.2020) - UHD/4K/8K",
        "category": "宽色域",
    },
    "ProPhotoRGB": {
        "red": (0.7347, 0.2653),
        "green": (0.1596, 0.8404),
        "blue": (0.0366, 0.0001),
        "white": "D50",
        "description": "ProPhoto RGB (ROMM)",
        "category": "专业",
    },
}

# 色彩空间别名（兼容不同命名风格）
COLOR_SPACE_ALIASES = {
    "DCI-P3": "DCI_P3",         # 连字符 -> 下划线
    "Display P3": "DisplayP3",  # 空格 -> 无空格
    "DisplayP3": "DisplayP3",   # 保持不变
    "Adobe RGB": "AdobeRGB",    # 空格 -> 无空格
    "ProPhoto RGB": "ProPhotoRGB",
    "Rec.709": "Rec709",
    "Rec.2020": "Rec2020",
    "Rec709": "Rec709",
    "Rec2020": "Rec2020",
}

def normalize_color_space_name(name: str) -> str:
    """
    标准化色彩空间名称

    Args:
        name: 用户输入的色彩空间名称（可能有不同命名风格）

    Returns:
        COLOR_SPACES 中使用的标准名称
    """
    if name in COLOR_SPACES:
        return name
    if name in COLOR_SPACE_ALIASES:
        return COLOR_SPACE_ALIASES[name]
    raise KeyError(f"未知的色彩空间: {name}")

# DCI 白点（SMPTE RP 431-2）
ILLUMINANTS["DCI"] = (89.459, 100.000, 95.442)  # 从 DCI xy (0.3140, 0.3510) 计算
WHITE_POINTS["DCI"] = (0.3140, 0.3510)


# ==============================================================================
# RGB 到 XYZ 转换矩阵
# ==============================================================================

def compute_rgb_to_xyz_matrix(
    rx: float, ry: float,
    gx: float, gy: float,
    bx: float, by: float,
    wx: float, wy: float
) -> Tuple[List[List[float]], List[List[float]]]:
    """
    根 primaries 和白点计算 RGB <-> XYZ 转换矩阵
    
    使用标准方法（参见 Bruce Lindbloom 网站）
    
    Args:
        rx, ry: 红色 primary 的 xy 坐标
        gx, gy: 绿色 primary 的 xy 坐标
        bx, by: 蓝色 primary 的 xy 坐标
        wx, wy: 白点的 xy 坐标
        
    Returns:
        Tuple[List[List[float]], List[List[float]]]: (RGB->XYZ 矩阵, XYZ->RGB 矩阵)
    """
    # 将 xy 转换为 XYZ（Y=1）
    def xy_to_xyz_row(x: float, y: float) -> Tuple[float, float, float]:
        if y == 0:
            return (0.0, 0.0, 0.0)
        X = x / y
        Y = 1.0
        Z = (1.0 - x - y) / y
        return (X, Y, Z)
    
    # primaries 的 XYZ 值
    R = xy_to_xyz_row(rx, ry)
    G = xy_to_xyz_row(gx, gy)
    B = xy_to_xyz_row(bx, by)
    W = xy_to_xyz_row(wx, wy)  # 白点 XYZ
    
    # 构建 primaries 矩阵
    # [Xr Xg Xb]
    # [Yr Yg Yb]
    # [Zr Zg Zb]
    M = [
        [R[0], G[0], B[0]],
        [R[1], G[1], B[1]],
        [R[2], G[2], B[2]],
    ]
    
    # 求逆矩阵
    def matrix_inverse(m: List[List[float]]) -> List[List[float]]:
        det = m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) \
              - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) \
              + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
        
        if det == 0:
            raise ValueError("矩阵行列式为零，无法求逆")
        
        inv_det = 1.0 / det
        
        return [
            [
                (m[1][1] * m[2][2] - m[1][2] * m[2][1]) * inv_det,
                (m[0][2] * m[2][1] - m[0][1] * m[2][2]) * inv_det,
                (m[0][1] * m[1][2] - m[0][2] * m[1][1]) * inv_det,
            ],
            [
                (m[1][2] * m[2][0] - m[1][0] * m[2][2]) * inv_det,
                (m[0][0] * m[2][2] - m[0][2] * m[2][0]) * inv_det,
                (m[0][2] * m[1][0] - m[0][0] * m[1][2]) * inv_det,
            ],
            [
                (m[1][0] * m[2][1] - m[1][1] * m[2][0]) * inv_det,
                (m[0][1] * m[2][0] - m[0][0] * m[2][1]) * inv_det,
                (m[0][0] * m[1][1] - m[0][1] * m[1][0]) * inv_det,
            ],
        ]
    
    M_inv = matrix_inverse(M)
    
    # 计算 S（白点的 RGB 值）
    # W = M * S => S = M_inv * W
    S = [
        M_inv[0][0] * W[0] + M_inv[0][1] * W[1] + M_inv[0][2] * W[2],
        M_inv[1][0] * W[0] + M_inv[1][1] * W[1] + M_inv[1][2] * W[2],
        M_inv[2][0] * W[0] + M_inv[2][1] * W[1] + M_inv[2][2] * W[2],
    ]
    
    # 构建 RGB -> XYZ 矩阵（乘以 S）
    RGB_to_XYZ = [
        [R[0] * S[0], G[0] * S[1], B[0] * S[2]],
        [R[1] * S[0], G[1] * S[1], B[1] * S[2]],
        [R[2] * S[0], G[2] * S[1], B[2] * S[2]],
    ]
    
    # XYZ -> RGB 矩阵（RGB_to_XYZ 的逆）
    XYZ_to_RGB = matrix_inverse(RGB_to_XYZ)
    
    return RGB_to_XYZ, XYZ_to_RGB


# 预计算的 sRGB 转换矩阵（D65 白点）
# 来源：IEC 61966-2-1 / Bruce Lindbloom
RGB_TO_XYZ_MATRIX: Dict[str, List[List[float]]] = {}
XYZ_TO_RGB_MATRIX: Dict[str, List[List[float]]] = {}

# sRGB / Rec.709 (D65)
# 精确矩阵，经 Bruce Lindbloom 验证
RGB_TO_XYZ_MATRIX["sRGB"] = [
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
]

XYZ_TO_RGB_MATRIX["sRGB"] = [
    [3.2404542, -1.5371385, -0.4985314],
    [-0.9692660, 1.8760108, 0.0415560],
    [0.0556434, -0.2040259, 1.0572252],
]

# Rec.709 与 sRGB primaries 相同，使用相同矩阵
RGB_TO_XYZ_MATRIX["Rec709"] = RGB_TO_XYZ_MATRIX["sRGB"]
XYZ_TO_RGB_MATRIX["Rec709"] = XYZ_TO_RGB_MATRIX["sRGB"]

# Display P3 (D65)
RGB_TO_XYZ_MATRIX["DisplayP3"] = [
    [0.4865709, 0.2656677, 0.1982174],
    [0.2289746, 0.6917385, 0.0792869],
    [0.0000000, 0.0451134, 1.0439442],
]

XYZ_TO_RGB_MATRIX["DisplayP3"] = [
    [2.4934969, -0.9313836, -0.4027108],
    [-0.8294867, 1.7626641, 0.0606215],
    [0.0358458, -0.0761724, 0.9568845],
]

# Rec.2020 (D65)
RGB_TO_XYZ_MATRIX["Rec2020"] = [
    [0.6369580, 0.1446169, 0.1688810],
    [0.2627002, 0.6779981, 0.0593017],
    [0.0000000, 0.0280727, 1.0609851],
]

XYZ_TO_RGB_MATRIX["Rec2020"] = [
    [1.7166512, -0.3556701, -0.2533662],
    [-0.6666844, 1.3647445, 0.0119182],
    [0.0176398, -0.0477106, 0.9977353],
]

# Adobe RGB (1998) (D65)
RGB_TO_XYZ_MATRIX["AdobeRGB"] = [
    [0.5767309, 0.1855540, 0.1881852],
    [0.2973769, 0.6273491, 0.0752741],
    [0.0270343, 0.0706872, 0.9911085],
]

XYZ_TO_RGB_MATRIX["AdobeRGB"] = [
    [2.0413690, -0.5649464, -0.3446944],
    [-0.9692660, 1.8760108, 0.0415560],
    [0.0134474, -0.1183897, 1.0154096],
]


# ==============================================================================
# 基础转换函数
# ==============================================================================

def xyY_to_xyz(x: float, y: float, Y: float) -> Tuple[float, float, float]:
    """
    CIE xyY 到 XYZ 转换
    
    Args:
        x: CIE x 坐标
        y: CIE y 坐标
        Y: 亮度（0-100 范围）
        
    Returns:
        Tuple[float, float, float]: (X, Y, Z) 三刺激值
    """
    if y == 0:
        return (0.0, Y, 0.0)
    
    X = (x * Y) / y
    Z = ((1.0 - x - y) * Y) / y
    
    return (X, Y, Z)


def xyz_to_xyY(X: float, Y: float, Z: float) -> Tuple[float, float, float]:
    """
    XYZ 到 CIE xyY 转换
    
    Args:
        X, Y, Z: 三刺激值
        
    Returns:
        Tuple[float, float, float]: (x, y, Y) 坐标
    """
    total = X + Y + Z
    if total == 0:
        return (0.0, 0.0, Y)
    
    x = X / total
    y = Y / total
    
    return (x, y, Y)


def xyz_to_lab(
    X: float, Y: float, Z: float,
    white_point: str = "D65"
) -> Tuple[float, float, float]:
    """
    XYZ 到 CIE L*a*b* 转换
    
    使用 CIE 1976 公式
    
    Args:
        X, Y, Z: 三刺激值（Y 范围通常 0-100）
        white_point: 参考白点名称
        
    Returns:
        Tuple[float, float, float]: (L*, a*, b*) 值
        L*: 0-100（亮度）
        a*: 绿(-)到红(+)
        b*: 蓝(-)到黄(+)
    """
    # 获取参考白点
    Xn, Yn, Zn = get_white_point_xyz(white_point)
    
    # 归一化
    xr = X / Xn
    yr = Y / Yn
    zr = Z / Zn
    
    # f 函数（CIE 1976）
    delta = 6.0 / 29.0  # 约 0.2069
    delta3 = delta ** 3  # 约 0.008856
    
    def f(t: float) -> float:
        if t > delta3:
            return math.pow(t, 1.0 / 3.0)
        else:
            return t / (3.0 * delta * delta) + 4.0 / 29.0
    
    fx = f(xr)
    fy = f(yr)
    fz = f(zr)
    
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    
    return (L, a, b)


def lab_to_xyz(
    L: float, a: float, b: float,
    white_point: str = "D65"
) -> Tuple[float, float, float]:
    """
    CIE L*a*b* 到 XYZ 转换（逆转换）
    
    Args:
        L, a, b: Lab 值
        white_point: 参考白点名称
        
    Returns:
        Tuple[float, float, float]: (X, Y, Z) 三刺激值
    """
    Xn, Yn, Zn = get_white_point_xyz(white_point)
    
    # 逆 f 函数
    delta = 6.0 / 29.0
    
    def f_inv(t: float) -> float:
        if t > delta:
            return t ** 3
        else:
            return 3.0 * delta * delta * (t - 4.0 / 29.0)
    
    fy = (L + 16.0) / 116.0
    fx = a / 500.0 + fy
    fz = fy - b / 200.0
    
    X = Xn * f_inv(fx)
    Y = Yn * f_inv(fy)
    Z = Zn * f_inv(fz)
    
    return (X, Y, Z)


def rgb_to_xyz(
    r: float, g: float, b: float,
    color_space: str = "sRGB",
    linear: bool = True  # 如果为 False，RGB 已为线性值
) -> Tuple[float, float, float]:
    """
    RGB 到 XYZ 转换
    
    Args:
        r, g, b: RGB 值（0-1 范围）
        color_space: 色彩空间名称
        linear: RGB 是否已经是线性值
        
    Returns:
        Tuple[float, float, float]: XYZ 值（Y 范围 0-100）
    """
    if color_space not in RGB_TO_XYZ_MATRIX:
        raise KeyError(f"未知的色彩空间: {color_space}")
    
    # 如果不是线性，需要先线性化
    if not linear:
        # 根据色彩空间选择对应的线性化函数
        if color_space in ("sRGB", "Rec709"):
            r_lin = srgb_linearize(r)
            g_lin = srgb_linearize(g)
            b_lin = srgb_linearize(b)
        else:
            # 简单幂函数（纯 Gamma）
            raise ValueError(f"色彩空间 {color_space} 需要 Gamma 参数，请使用 transfer 模块")
    else:
        r_lin, g_lin, b_lin = r, g, b
    
    # 应用转换矩阵
    M = RGB_TO_XYZ_MATRIX[color_space]
    
    X = M[0][0] * r_lin + M[0][1] * g_lin + M[0][2] * b_lin
    Y = M[1][0] * r_lin + M[1][1] * g_lin + M[1][2] * b_lin
    Z = M[2][0] * r_lin + M[2][1] * g_lin + M[2][2] * b_lin
    
    # 缩放到 Y = 100 范围
    # 矩阵设计使得 (1, 1, 1) RGB -> D65 白点 (95.047, 100, 108.883)
    # 所以 Y 已经是正确范围
    
    return (X * 100.0, Y * 100.0, Z * 100.0)


def xyz_to_rgb(
    X: float, Y: float, Z: float,
    color_space: str = "sRGB",
    apply_gamma: bool = True
) -> Tuple[float, float, float]:
    """
    XYZ 到 RGB 转换
    
    Args:
        X, Y, Z: XYZ 值（Y 范围 0-100）
        color_space: 色彩空间名称
        apply_gamma: 是否应用 Gamma 校正
        
    Returns:
        Tuple[float, float, float]: RGB 值（0-1 范围）
    """
    if color_space not in XYZ_TO_RGB_MATRIX:
        raise KeyError(f"未知的色彩空间: {color_space}")
    
    M = XYZ_TO_RGB_MATRIX[color_space]
    
    # 归一化 XYZ 到 Y = 1 范围
    X_norm = X / 100.0
    Y_norm = Y / 100.0
    Z_norm = Z / 100.0
    
    # 应用转换矩阵
    r_lin = M[0][0] * X_norm + M[0][1] * Y_norm + M[0][2] * Z_norm
    g_lin = M[0][0] * X_norm + M[0][1] * Y_norm + M[0][2] * Z_norm  # Bug fix
    g_lin = M[1][0] * X_norm + M[1][1] * Y_norm + M[1][2] * Z_norm  # Correct
    b_lin = M[2][0] * X_norm + M[2][1] * Y_norm + M[2][2] * Z_norm
    
    # 应用 Gamma 校正
    if apply_gamma:
        if color_space in ("sRGB", "Rec709"):
            r = srgb_gamma_correct(r_lin)
            g = srgb_gamma_correct(g_lin)
            b = srgb_gamma_correct(b_lin)
        else:
            raise ValueError(f"色彩空间 {color_space} 需要 Gamma 参数")
    else:
        r, g, b = r_lin, g_lin, b_lin
    
    return (r, g, b)


def rgb_to_lab(
    r: float, g: float, b: float,
    color_space: str = "sRGB",
    white_point: str = "D65",
    linear: bool = False
) -> Tuple[float, float, float]:
    """
    RGB 直接转换到 Lab
    
    Args:
        r, g, b: RGB 值（0-1 范围）
        color_space: 色彩空间名称
        white_point: 参考白点
        linear: RGB 是否已经是线性值
        
    Returns:
        Tuple[float, float, float]: (L*, a*, b*) 值
    """
    X, Y, Z = rgb_to_xyz(r, g, b, color_space, linear)
    return xyz_to_lab(X, Y, Z, white_point)


def lab_to_rgb(
    L: float, a: float, b: float,
    color_space: str = "sRGB",
    white_point: str = "D65"
) -> Tuple[float, float, float]:
    """
    Lab 直接转换到 RGB
    
    Args:
        L, a, b: Lab 值
        color_space: 色彩空间名称
        white_point: 参考白点
        
    Returns:
        Tuple[float, float, float]: RGB 值（0-1 范围）
    """
    X, Y, Z = lab_to_xyz(L, a, b, white_point)
    return xyz_to_rgb(X, Y, Z, color_space)


# ==============================================================================
# sRGB 特定函数
# ==============================================================================

def srgb_linearize(c: float) -> float:
    """
    sRGB 反 Gamma（线性化）
    
    根据 IEC 61966-2-1 标准
    
    Args:
        c: sRGB 值（0-1 范围）
        
    Returns:
        float: 线性 RGB 值
    """
    if c <= 0.04045:
        return c / 12.92
    else:
        return math.pow((c + 0.055) / 1.055, 2.4)


def srgb_gamma_correct(c: float) -> float:
    """
    sRGB Gamma 校正
    
    根据 IEC 61966-2-1 标准
    
    Args:
        c: 线性 RGB 值（0-1 范围）
        
    Returns:
        float: sRGB 值
    """
    if c <= 0.0031308:
        return 12.92 * c
    else:
        return 1.055 * math.pow(c, 1.0 / 2.4) - 0.055


def srgb_to_xyz(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """
    8-bit sRGB 到 XYZ（便捷函数）
    
    Args:
        r, g, b: 0-255 范围的 RGB 值
        
    Returns:
        Tuple[float, float, float]: XYZ 值（Y 范围 0-100）
    """
    # 量化到 0-1
    r_norm = r / 255.0
    g_norm = g / 255.0
    b_norm = b / 255.0
    
    return rgb_to_xyz(r_norm, g_norm, b_norm, "sRGB", linear=False)


def xyz_to_srgb(X: float, Y: float, Z: float) -> Tuple[int, int, int]:
    """
    XYZ 到 8-bit sRGB（便捷函数）
    
    Args:
        X, Y, Z: XYZ 值（Y 范围 0-100）
        
    Returns:
        Tuple[int, int, int]: 0-255 范围的 RGB 值
    """
    r, g, b = xyz_to_rgb(X, Y, Z, "sRGB", apply_gamma=True)
    
    # 裁剪并量化
    r_int = max(0, min(255, round(r * 255)))
    g_int = max(0, min(255, round(g * 255)))
    b_int = max(0, min(255, round(b * 255)))
    
    return (r_int, g_int, b_int)


# ==============================================================================
# 辅助函数
# ==============================================================================

def rgb8_to_float(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """
    8-bit RGB 到 0-1 浮点值
    
    Args:
        r, g, b: 0-255 范围的 RGB 值
        
    Returns:
        Tuple[float, float, float]: 0-1 范围的 RGB 值
    """
    return (r / 255.0, g / 255.0, b / 255.0)


def float_to_rgb8(r: float, g: float, b: float) -> Tuple[int, int, int]:
    """
    0-1 浮点 RGB 到 8-bit
    
    Args:
        r, g, b: 0-1 范围的 RGB 值
        
    Returns:
        Tuple[int, int, int]: 0-255 范围的 RGB 值
    """
    return (
        max(0, min(255, round(r * 255))),
        max(0, min(255, round(g * 255))),
        max(0, min(255, round(b * 255))),
    )
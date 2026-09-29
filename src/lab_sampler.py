"""
CIELAB 色块采样模块

⚠️ DEPRECATED: 本模块已被废弃，请使用 src/color_science/gamut_sampling.py 中的 GamutSampler。

废弃原因：
    1. XYZ 缩放错误：srgb_to_xyz() 中存在非标准缩放（已在下方修复）
    2. Lab→RGB 转换后裁剪导致重复色块
    3. Lab 边界使用近似公式而非精确计算

推荐替代：
    from src.color_science.gamut_sampling import GamutSampler, SamplingStrategy
    
    sampler = GamutSampler(SamplingStrategy.ICC_STANDARD)
    patches = sampler.generate_patches(500)
    rgb_list = sampler.get_rgb_list()  # 无重复，覆盖率好

本模块保留用于向后兼容，但会在调用时发出警告。
"""

import math
from typing import List, Tuple, Dict, Optional
import warnings


# ========== D65 白点参考值 ==========
D65_X = 0.95047
D65_Y = 1.00000
D65_Z = 1.08883

# ========== sRGB 色域边界（用于判断颜色是否在色域内） ==========
# sRGB 的 Lab 边界值（近似）
SRGB_LAB_MIN_L = 0
SRGB_LAB_MAX_L = 100


def srgb_to_xyz(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """
    sRGB 到 XYZ 色彩空间转换

    ⚠️ 已修复：删除了错误的 XYZ 缩放行。

    Args:
        r, g, b: 0-255 范围的 RGB 值

    Returns:
        Tuple[float, float, float]: XYZ 三刺激值（Y 范围 0-1）
    """
    # 1. 量化到 0-1 范围
    r_lin = r / 255.0
    g_lin = g / 255.0
    b_lin = b / 255.0

    # 2. 反 gamma 校正（sRGB 的 gamma 约为 2.2，但使用精确公式）
    def inv_gamma(c: float) -> float:
        """sRGB 反 gamma 校正"""
        if c <= 0.04045:
            return c / 12.92
        else:
            return math.pow((c + 0.055) / 1.055, 2.4)

    r_lin = inv_gamma(r_lin)
    g_lin = inv_gamma(g_lin)
    b_lin = inv_gamma(b_lin)

    # 3. 线性 RGB 到 XYZ 转换矩阵（D65 参考）
    # 这是标准的 sRGB 到 XYZ 矩阵（Bruce Lindbloom 验证）
    X = 0.4124564 * r_lin + 0.3575761 * g_lin + 0.1804375 * b_lin
    Y = 0.2126729 * r_lin + 0.7151522 * g_lin + 0.0721750 * b_lin
    Z = 0.0193339 * r_lin + 0.1191920 * g_lin + 0.9503041 * b_lin

    # [已删除错误的缩放行] X = X * D65_X / 0.4124564
    # 标准矩阵已正确缩放，无需额外处理

    return (X, Y, Z)


def xyz_to_lab(X: float, Y: float, Z: float) -> Tuple[float, float, float]:
    """
    XYZ 到 CIELAB 色彩空间转换

    Args:
        X, Y, Z: XYZ 三刺激值

    Returns:
        Tuple[float, float, float]: L*, a*, b* 值
        L*: 0-100（亮度）
        a*: 大约 -128 到 128（绿到红）
        b*: 大约 -128 到 128（蓝到黄）
    """
    # 相对于 D65 白点
    X_ref = X / D65_X
    Y_ref = Y / D65_Y
    Z_ref = Z / D65_Z

    # f 函数
    def f(t: float) -> float:
        """LAB 转换函数"""
        delta = 6.0 / 29.0
        if t > delta ** 3:
            return math.pow(t, 1.0 / 3.0)
        else:
            return t / (3.0 * delta ** 2) + 4.0 / 29.0

    fx = f(X_ref)
    fy = f(Y_ref)
    fz = f(Z_ref)

    # 计算 L*, a*, b*
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)

    return (L, a, b)


def lab_to_xyz(L: float, a: float, b: float) -> Tuple[float, float, float]:
    """
    CIELAB 到 XYZ 色彩空间逆转换

    Args:
        L, a, b: CIELAB 值

    Returns:
        Tuple[float, float, float]: XYZ 三刺激值
    """
    # 逆 f 函数
    def f_inv(t: float) -> float:
        """LAB 逆转换函数"""
        delta = 6.0 / 29.0
        if t > delta:
            return t ** 3
        else:
            return 3.0 * delta ** 2 * (t - 4.0 / 29.0)

    fy = (L + 16.0) / 116.0
    fx = a / 500.0 + fy
    fz = fy - b / 200.0

    X = D65_X * f_inv(fx)
    Y = D65_Y * f_inv(fy)
    Z = D65_Z * f_inv(fz)

    return (X, Y, Z)


def xyz_to_srgb(X: float, Y: float, Z: float) -> Tuple[int, int, int]:
    """
    XYZ 到 sRGB 色彩空间逆转换

    Args:
        X, Y, Z: XYZ 三刺激值

    Returns:
        Tuple[int, int, int]: 0-255 范围的 RGB 值
    """
    # 1. XYZ 到线性 RGB 转换矩阵（逆矩阵）
    # 标准的 XYZ 到 sRGB 转换矩阵（已考虑 D65 参考）
    r_lin = 3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z
    g_lin = -0.9692660 * X + 1.8760108 * Y + 0.0415560 * Z
    b_lin = 0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z

    # 2. Gamma 校正
    def gamma(c: float) -> float:
        """sRGB gamma 校正"""
        if c <= 0.0031308:
            return 12.92 * c
        else:
            return 1.055 * math.pow(c, 1.0 / 2.4) - 0.055

    r = gamma(max(0, min(1, r_lin)))
    g = gamma(max(0, min(1, g_lin)))
    b = gamma(max(0, min(1, b_lin)))

    # 3. 量化到 0-255 范围
    r_int = round(r * 255)
    g_int = round(g * 255)
    b_int = round(b * 255)

    return (r_int, g_int, b_int)


def rgb_to_lab(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """
    RGB 到 LAB 直接转换（便捷函数）

    Args:
        r, g, b: 0-255 范围的 RGB 值

    Returns:
        Tuple[float, float, float]: L*, a*, b* 值
    """
    X, Y, Z = srgb_to_xyz(r, g, b)
    return xyz_to_lab(X, Y, Z)


def lab_to_rgb(L: float, a: float, b: float) -> Tuple[int, int, int]:
    """
    LAB 到 RGB 直接转换（便捷函数）

    Args:
        L, a, b: CIELAB 值

    Returns:
        Tuple[int, int, int]: 0-255 范围的 RGB 值
    """
    X, Y, Z = lab_to_xyz(L, a, b)
    return xyz_to_srgb(X, Y, Z)


def is_in_srgb_gamut(r: int, g: int, b: int) -> bool:
    """
    判断 RGB 值是否在有效范围内（0-255）

    注意：由于我们使用的是 sRGB 色域，所有生成的 RGB 值都会被裁剪到 0-255。
    此函数用于检测是否有颜色被裁剪（超出范围）。

    Args:
        r, g, b: RGB 值

    Returns:
        bool: 是否在有效范围内
    """
    return 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255


def get_srgb_lab_bounds(L: float) -> Tuple[float, float, float, float]:
    """
    计算给定 L* 值下，sRGB 色域的 a* 和 b* 边界

    这是近似计算，用于确定采样范围。

    Args:
        L: 亮度值 (0-100)

    Returns:
        Tuple[float, float, float, float]: (a_min, a_max, b_min, b_max)
    """
    # 在不同亮度下，色域边界不同
    # 低亮度时，色域范围较小（暗部颜色饱和度有限）
    # 高亮度时，色域范围较大

    # 简化模型：色域半径随亮度变化
    # L* < 10: 暗部，色域范围很小
    # L* = 50: 中间亮度，色域范围最大
    # L* > 90: 高亮度，色域范围减小（接近白）

    if L < 10:
        # 暗部：色域范围很小
        radius = L * 2.0  # 线性增长
    elif L < 50:
        # 中间亮度：色域范围扩大
        radius = 20 + (L - 10) * 1.5
    elif L < 90:
        # 高亮度：色域范围保持较大但开始收缩
        radius = 80 - (L - 50) * 0.5
    else:
        # 接近白：色域范围急剧收缩
        radius = 60 - (L - 90) * 5.0

    radius = max(0, min(128, radius))

    return (-radius, radius, -radius, radius)


class LABSampler:
    """
    CIELAB 空间离散采样器

    ⚠️ DEPRECATED: 请使用 src.color_science.gamut_sampling.GamutSampler

    本类存在以下问题：
        1. Lab→RGB 转换时裁剪会导致重复色块
        2. get_srgb_lab_bounds() 使用近似公式而非精确计算
        3. XYZ 缩放问题（已在 srgb_to_xyz 中修复）

    推荐替代：
        from src.color_science.gamut_sampling import GamutSampler, SamplingStrategy
        sampler = GamutSampler(SamplingStrategy.ICC_STANDARD)

    实现智能采样策略，确保：
        1. 暗部细节覆盖
        2. 灰阶过渡覆盖
        3. 高饱和边界覆盖
    """

    def __init__(self, target_gamut: str = "sRGB"):
        """
        初始化采样器

        ⚠️ DEPRECATED: 请使用 GamutSampler

        Args:
            target_gamut: 目标色域（sRGB, DCI-P3, Rec2020 等）
                         目前仅支持 sRGB，后续可扩展
        """
        warnings.warn(
            "LABSampler 已废弃，请使用 src.color_science.gamut_sampling.GamutSampler。"
            "新采样器修复了重复色块问题，并提供更精确的色域边界计算。",
            DeprecationWarning,
            stacklevel=2
        )

        self.target_gamut = target_gamut

        # 采样密度配置
        # 不同区域的采样密度权重
        self.dark_region_weight = 2.0     # 暗部密度权重（L* < 20）
        self.gray_axis_weight = 1.5       # 灰阶轴密度权重
        self.saturation_edge_weight = 1.5  # 高饱和边界密度权重
        self.mid_tone_weight = 1.0        # 中间调密度权重

        # 基础色块（不参与采样，避免重复）
        self._basic_patches = [
            (255, 0, 0),    # 红
            (0, 255, 0),    # 绿
            (0, 0, 255),    # 蓝
            (255, 255, 255),  # 白
            (0, 0, 0),      # 黑
        ]

        # 灰阶色块（不参与采样）- 10%-90%共9个
        self._gray_patches = [
            (25, 25, 25),    # 10%
            (51, 51, 51),    # 20%
            (76, 76, 76),    # 30%
            (102, 102, 102), # 40%
            (128, 128, 128), # 50%
            (153, 153, 153), # 60%
            (179, 179, 179), # 70%
            (204, 204, 204), # 80%
            (230, 230, 230), # 90%
        ]

    def generate_patches(self, count: int) -> List[Dict]:
        """
        生成指定数量的采样色块

        使用 CIELAB 空间离散采样，确保：
            1. 暗部细节覆盖
            2. 灰阶过渡覆盖
            3. 高饱和边界覆盖

        Args:
            count: 需要生成的色块数量

        Returns:
            List[Dict]: 色块列表，每个元素包含 {"name": str, "rgb": [r, g, b]}
        """
        if count <= 0:
            return []

        patches = []
        seen_rgb = set()  # 用于去重

        # ========== 第一阶段：灰阶轴采样 ==========
        # 灰阶是显示器校正最关键的区域
        gray_count = int(count * 0.30)  # 30% 分配给灰阶
        gray_patches = self._generate_gray_axis_patches(gray_count)

        for i, (r, g, b) in enumerate(gray_patches):
            rgb_tuple = (r, g, b)
            if rgb_tuple in seen_rgb:
                continue
            if rgb_tuple in self._basic_patches or rgb_tuple in self._gray_patches:
                continue

            # 转换为 LAB 计算亮度百分比作为名称
            L, a, b_lab = rgb_to_lab(r, g, b)
            percent = int(L)
            name = f"灰{percent}%"

            patches.append({"name": name, "rgb": [r, g, b]})
            seen_rgb.add(rgb_tuple)

        # ========== 第二阶段：暗部细节采样 ==========
        # L* < 20 的区域，增加采样密度
        dark_count = int(count * 0.25)  # 25% 分配给暗部
        dark_patches = self._generate_dark_region_patches(dark_count)

        for i, (r, g, b) in enumerate(dark_patches):
            rgb_tuple = (r, g, b)
            if rgb_tuple in seen_rgb:
                continue
            if rgb_tuple in self._basic_patches or rgb_tuple in self._gray_patches:
                continue

            name = f"暗{i + 1}"
            patches.append({"name": name, "rgb": [r, g, b]})
            seen_rgb.add(rgb_tuple)

        # ========== 第三阶段：高饱和边界采样 ==========
        # 在色域边界增加采样
        saturation_count = int(count * 0.25)  # 25% 分配给高饱和
        saturation_patches = self._generate_saturation_edge_patches(saturation_count)

        for i, (r, g, b) in enumerate(saturation_patches):
            rgb_tuple = (r, g, b)
            if rgb_tuple in seen_rgb:
                continue
            if rgb_tuple in self._basic_patches or rgb_tuple in self._gray_patches:
                continue

            name = f"饱和{i + 1}"
            patches.append({"name": name, "rgb": [r, g, b]})
            seen_rgb.add(rgb_tuple)

        # ========== 第四阶段：中间调均匀采样 ==========
        # 剩余部分在 LAB 空间均匀采样
        remaining = count - len(patches)
        if remaining > 0:
            mid_patches = self._generate_mid_tone_patches(remaining * 2)  # 多生成一些以补充去重

            for i, (r, g, b) in enumerate(mid_patches):
                if len(patches) >= count:
                    break

                rgb_tuple = (r, g, b)
                if rgb_tuple in seen_rgb:
                    continue
                if rgb_tuple in self._basic_patches or rgb_tuple in self._gray_patches:
                    continue

                name = f"采样{i + 1}"
                patches.append({"name": name, "rgb": [r, g, b]})
                seen_rgb.add(rgb_tuple)

        # ========== 补充采样（如果数量不足） ==========
        # 使用 RGB 均匀采样补充
        while len(patches) < count:
            # 生成随机或均匀分布的 RGB 值
            step = 8  # 使用较小的步长
            for r in range(0, 256, step):
                for g in range(0, 256, step):
                    for b in range(0, 256, step):
                        if len(patches) >= count:
                            break

                        rgb_tuple = (r, g, b)
                        if rgb_tuple in seen_rgb:
                            continue
                        if rgb_tuple in self._basic_patches or rgb_tuple in self._gray_patches:
                            continue

                        name = f"补充{len(patches) + 1}"
                        patches.append({"name": name, "rgb": [r, g, b]})
                        seen_rgb.add(rgb_tuple)

                    if len(patches) >= count:
                        break

                if len(patches) >= count:
                    break

            # 如果还不够，减小步长继续
            if len(patches) < count:
                step = max(1, step // 2)
                if step == 1:
                    break  # 已经是最小步长，无法继续

        return patches[:count]  # 截取到目标数量

    def _generate_gray_axis_patches(self, count: int) -> List[Tuple[int, int, int]]:
        """
        生成灰阶轴上的采样点

        灰阶轴是最关键的校正区域，需要精细采样。

        Args:
            count: 分配给灰阶的色块数量

        Returns:
            List[Tuple[int, int, int]]: RGB 值列表
        """
        patches = []

        # 灰阶采样密度配置
        # 暗部（L* < 20）需要更多采样点
        # 中间调（L* 20-80）中等密度
        # 高亮（L* > 80）较少采样点

        # 计算每个区域的采样数量
        dark_gray_count = int(count * 0.4)    # 暗部灰阶 40%
        mid_gray_count = int(count * 0.5)     # 中间灰阶 50%
        high_gray_count = count - dark_gray_count - mid_gray_count  # 高亮灰阶 10%

        # 暗部灰阶（L* 0-20）
        # 使用更精细的步长
        dark_L_values = self._generate_L_steps(0, 20, dark_gray_count)
        for L in dark_L_values:
            r, g, b = lab_to_rgb(L, 0, 0)
            patches.append((r, g, b))

        # 中间灰阶（L* 20-80）
        mid_L_values = self._generate_L_steps(20, 80, mid_gray_count)
        for L in mid_L_values:
            r, g, b = lab_to_rgb(L, 0, 0)
            patches.append((r, g, b))

        # 高亮灰阶（L* 80-100）
        high_L_values = self._generate_L_steps(80, 100, high_gray_count)
        for L in high_L_values:
            r, g, b = lab_to_rgb(L, 0, 0)
            patches.append((r, g, b))

        return patches

    def _generate_dark_region_patches(self, count: int) -> List[Tuple[int, int, int]]:
        """
        生成暗部区域的采样点（L* < 20）

        暗部是显示器校正的难点，需要：
            1. 低亮度下的色彩偏移检测
            2. 黑场附近的细节保留
            3. 低亮度下的色度准确性

        Args:
            count: 分配给暗部的色块数量

        Returns:
            List[Tuple[int, int, int]]: RGB 值列表
        """
        patches = []

        # 暗部采样策略：
        # 1. 固定几个低 L* 值（如 5, 10, 15）
        # 2. 在每个 L* 平面上进行圆形采样
        # 3. 半径较小（暗部饱和度有限）

        L_planes = [5, 10, 15, 20]

        # 分配每个平面的采样数量
        per_plane = count // len(L_planes)

        for L in L_planes:
            # 获取该亮度下的色域边界
            a_min, a_max, b_min, b_max = get_srgb_lab_bounds(L)

            # 圆形采样：不同半径和角度
            # 半径从 10% 到 100% 的色域边界
            radii = [0.3, 0.6, 0.9]  # 三个半径层次
            angles_per_radius = per_plane // len(radii)

            for radius_factor in radii:
                radius = radius_factor * min(a_max, b_max)

                # 角度采样
                angle_step = 360.0 / angles_per_radius if angles_per_radius > 0 else 60

                for angle_idx in range(angles_per_radius):
                    angle = angle_idx * angle_step

                    # 计算 a*, b*
                    a = radius * math.cos(math.radians(angle))
                    b_lab = radius * math.sin(math.radians(angle))

                    # 转换为 RGB
                    r, g, b_rgb = lab_to_rgb(L, a, b_lab)
                    patches.append((r, g, b_rgb))

        return patches

    def _generate_saturation_edge_patches(self, count: int) -> List[Tuple[int, int, int]]:
        """
        生成高饱和边界区域的采样点

        高饱和边界用于检测：
            1. 色域边界准确性
            2. 原色饱和度
            3. 色域覆盖率

        Args:
            count: 分配给高饱和的色块数量

        Returns:
            List[Tuple[int, int, int]]: RGB 值列表
        """
        patches = []

        # 高饱和采样策略：
        # 1. 在不同 L* 平面上采样边界
        # 2. 重点采样 RGB 原色附近

        # 选择几个关键亮度平面
        L_planes = [30, 50, 70]

        per_plane = count // len(L_planes)

        for L in L_planes:
            # 获取色域边界
            a_min, a_max, b_min, b_max = get_srgb_lab_bounds(L)

            # 边界采样：使用最大半径
            radius = min(a_max, b_max) * 0.95  # 接近边界

            # 角度采样（覆盖整个色域边界）
            angle_count = per_plane
            angle_step = 360.0 / angle_count if angle_count > 0 else 30

            for angle_idx in range(angle_count):
                angle = angle_idx * angle_step

                a = radius * math.cos(math.radians(angle))
                b_lab = radius * math.sin(math.radians(angle))

                r, g, b_rgb = lab_to_rgb(L, a, b_lab)
                patches.append((r, g, b_rgb))

        # 添加 RGB 原色附近的高饱和点
        # 红: a* 正方向最大
        # 绿: a* 负方向较大
        # 蓝: b* 负方向最大
        # 黄: b* 正方向最大

        primary_count = count // 5  # 每个原色分配的采样数

        # 红色附近（a* > 0）
        for i in range(primary_count):
            L = 40 + i * 10  # 从 40 到更高亮度
            a = 80 - i * 5   # 高饱和递减
            b_lab = 0
            r, g, b_rgb = lab_to_rgb(L, a, b_lab)
            patches.append((r, g, b_rgb))

        # 绿色附近（a* < 0）
        for i in range(primary_count):
            L = 50 + i * 8
            a = -70 + i * 3
            b_lab = 10
            r, g, b_rgb = lab_to_rgb(L, a, b_lab)
            patches.append((r, g, b_rgb))

        # 蓝色附近（b* < 0）
        for i in range(primary_count):
            L = 20 + i * 10
            a = 20 - i * 2
            b_lab = -80 + i * 5
            r, g, b_rgb = lab_to_rgb(L, a, b_lab)
            patches.append((r, g, b_rgb))

        # 黄色附近（b* > 0）
        for i in range(primary_count):
            L = 80 - i * 5
            a = 10
            b_lab = 80 - i * 5
            r, g, b_rgb = lab_to_rgb(L, a, b_lab)
            patches.append((r, g, b_rgb))

        # 青/紫附近
        for i in range(primary_count):
            L = 50 + i * 5
            a = -40 + i * 8   # 从青到紫
            b_lab = -30 + i * 6
            r, g, b_rgb = lab_to_rgb(L, a, b_lab)
            patches.append((r, g, b_rgb))

        return patches

    def _generate_mid_tone_patches(self, count: int) -> List[Tuple[int, int, int]]:
        """
        生成中间调区域的均匀采样点

        使用准蒙特卡洛方法在 LAB 空间均匀采样。

        Args:
            count: 分配给中间调的色块数量

        Returns:
            List[Tuple[int, int, int]]: RGB 值列表
        """
        patches = []

        # 使用网格采样法
        # 在 L*, a*, b* 三个维度上均匀分布

        # 计算每个维度的采样点数
        dim_count = int(math.pow(count, 1/3)) + 1

        # L* 范围：20-80（中间调）
        L_values = self._generate_L_steps(20, 80, dim_count)

        # a* 和 b* 范围：使用中等色域边界
        a_step = 40 / dim_count if dim_count > 0 else 20
        b_step = 40 / dim_count if dim_count > 0 else 20

        generated = 0
        for L in L_values:
            a_min, a_max, b_min, b_max = get_srgb_lab_bounds(L)

            # 在色域范围内均匀采样
            a_values = [a_min + i * (a_max - a_min) / dim_count for i in range(dim_count)]
            b_values = [b_min + i * (b_max - b_min) / dim_count for i in range(dim_count)]

            for a in a_values:
                for b_lab in b_values:
                    if generated >= count:
                        break

                    r, g, b_rgb = lab_to_rgb(L, a, b_lab)
                    patches.append((r, g, b_rgb))
                    generated += 1

                if generated >= count:
                    break

            if generated >= count:
                break

        return patches

    def _generate_L_steps(self, L_min: float, L_max: float, count: int) -> List[float]:
        """
        生成 L* 值的采样步长

        使用加权步长，暗部更精细。

        Args:
            L_min: 最小 L* 值
            L_max: 最大 L* 值
            count: 采样点数量

        Returns:
            List[float]: L* 值列表
        """
        if count <= 0:
            return []

        if count == 1:
            return [(L_min + L_max) / 2]

        # 简化版：均匀分布
        step = (L_max - L_min) / (count - 1)
        return [L_min + i * step for i in range(count)]

    def generate_custom_patches(self, count: int, focus_areas: Optional[List[str]] = None) -> List[Dict]:
        """
        生成自定义采样色块

        允许用户指定重点关注的区域。

        Args:
            count: 需要生成的色块数量
            focus_areas: 重点区域列表
                - "dark": 暗部细节
                - "gray": 灰阶过渡
                - "saturation": 高饱和边界
                - "mid": 中间调

        Returns:
            List[Dict]: 色块列表
        """
        if focus_areas is None or len(focus_areas) == 0:
            # 默认均衡分配
            return self.generate_patches(count)

        patches = []
        seen_rgb = set()  # 用于去重

        # 根据重点区域分配数量
        area_count = len(focus_areas)
        per_area = count // area_count

        for area in focus_areas:
            if area == "dark":
                area_patches = self._generate_dark_region_patches(per_area)
                for i, (r, g, b) in enumerate(area_patches):
                    rgb_tuple = (r, g, b)
                    if rgb_tuple in seen_rgb:
                        continue
                    if rgb_tuple in self._basic_patches or rgb_tuple in self._gray_patches:
                        continue
                    patches.append({"name": f"暗{i + 1}", "rgb": [r, g, b]})
                    seen_rgb.add(rgb_tuple)

            elif area == "gray":
                area_patches = self._generate_gray_axis_patches(per_area)
                for i, (r, g, b) in enumerate(area_patches):
                    rgb_tuple = (r, g, b)
                    if rgb_tuple in seen_rgb:
                        continue
                    if rgb_tuple in self._basic_patches or rgb_tuple in self._gray_patches:
                        continue
                    L, _, _ = rgb_to_lab(r, g, b)
                    patches.append({"name": f"灰{int(L)}%", "rgb": [r, g, b]})
                    seen_rgb.add(rgb_tuple)

            elif area == "saturation":
                area_patches = self._generate_saturation_edge_patches(per_area)
                for i, (r, g, b) in enumerate(area_patches):
                    rgb_tuple = (r, g, b)
                    if rgb_tuple in seen_rgb:
                        continue
                    if rgb_tuple in self._basic_patches or rgb_tuple in self._gray_patches:
                        continue
                    patches.append({"name": f"饱和{i + 1}", "rgb": [r, g, b]})
                    seen_rgb.add(rgb_tuple)

            elif area == "mid":
                area_patches = self._generate_mid_tone_patches(per_area)
                for i, (r, g, b) in enumerate(area_patches):
                    rgb_tuple = (r, g, b)
                    if rgb_tuple in seen_rgb:
                        continue
                    if rgb_tuple in self._basic_patches or rgb_tuple in self._gray_patches:
                        continue
                    patches.append({"name": f"中间{i + 1}", "rgb": [r, g, b]})
                    seen_rgb.add(rgb_tuple)

        return patches[:count]  # 截取到目标数量


# ========== 测试与调试 ==========

def test_sampler():
    """测试采样器"""
    sampler = LABSampler()

    print("测试 1500 色块采样...")
    patches_1500 = sampler.generate_patches(1500)
    print(f"生成 {len(patches_1500)} 个色块")

    print("\n测试 2000 色块采样...")
    patches_2000 = sampler.generate_patches(2000)
    print(f"生成 {len(patches_2000)} 个色块")

    print("\n测试 3000 色块采样...")
    patches_3000 = sampler.generate_patches(3000)
    print(f"生成 {len(patches_3000)} 个色块")

    # 分析采样分布
    print("\n分析 1500 色块的亮度分布...")
    L_values = [rgb_to_lab(p["rgb"][0], p["rgb"][1], p["rgb"][2])[0] for p in patches_1500]

    dark_count = sum(1 for L in L_values if L < 20)
    mid_count = sum(1 for L in L_values if 20 <= L < 80)
    high_count = sum(1 for L in L_values if L >= 80)

    print(f"  暗部 (L < 20): {dark_count} 个 ({dark_count/len(L_values)*100:.1f}%)")
    print(f"  中间 (L 20-80): {mid_count} 个 ({mid_count/len(L_values)*100:.1f}%)")
    print(f"  高亮 (L >= 80): {high_count} 个 ({high_count/len(L_values)*100:.1f}%)")


if __name__ == "__main__":
    test_sampler()
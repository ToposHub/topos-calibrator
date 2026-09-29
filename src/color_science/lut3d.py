"""
3D LUT 核心算法 - 专业色彩校准 LUT 生成与应用

本模块实现：
    - LUT3D 核心类：支持 17/21/33/65 grid
    - Interpolation: trilinear, tetrahedral
    - Smoothing/regularization: LUT 数据平滑
    - Neutral axis preservation: 中性轴保护
    - Black/white point protection: 黑白场保护
    - Gamut mapping: clipping 和 perceptual
    - CUBE export: .cube 文件导出（第一优先级）
    - LUT application: 供 ValidationWorkflow 使用
    - Synthetic display model: 测试 fixture

参考标准：
    - Adobe CUBE format specification
    - SMPTE RP 177 - Gamut Mapping
    - ICC v4 specification - Perceptual Intent
    - OpenColorIO LUT implementation
"""

import math
import numpy as np
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
    TYPE_CHECKING,
)

from .colorimetry import (
    delta_e_ciede2000,
    delta_e_cie76,
    lab_to_lch,
    lch_to_lab,
    chromatic_adaptation,
)
from .spaces import (
    rgb_to_xyz,
    xyz_to_rgb,
    xyz_to_lab,
    lab_to_xyz,
    rgb_to_lab,
    lab_to_rgb,
    get_white_point_xyz,
    get_white_point_xy,
    WHITE_POINTS,
    COLOR_SPACES,
    RGB_TO_XYZ_MATRIX,
    XYZ_TO_RGB_MATRIX,
)
from .transfer import (
    eotf_gamma,
    oetf_gamma,
    eotf_srgb,
    oetf_srgb,
    eotf_bt1886,
    eotf_bt1886_inverse,
    apply_eotf,
    apply_oetf,
)


# ==============================================================================
# 类型定义
# ==============================================================================

class GamutMappingStrategy(Enum):
    """
    Gamut mapping 策略

    - CLIP: 简单裁剪（色域外颜色映射到边界）
    - PERCEPTUAL: 感知映射（保持视觉连续性，压缩色域）
    """
    CLIP = "clip"
    PERCEPTUAL = "perceptual"


class SmoothingMethod(Enum):
    """
    LUT smoothing 方法

    - NONE: 无平滑
    - GAUSSIAN: Gaussian blur
    - MEDIAN: Median filter
    - REGULARIZATION: Tikhonov regularization
    """
    NONE = "none"
    GAUSSIAN = "gaussian"
    MEDIAN = "median"
    REGULARIZATION = "regularization"


@dataclass
class LUT3DSpec:
    """
    3D LUT 规格定义

    Attributes:
        grid_size: Grid 尺寸 (17, 21, 33, 65)
        domain_min: 输入域最小值（默认 0.0）
        domain_max: 输入域最大值（默认 1.0）
        interpolation: 插值方法
        gamut_mapping: Gamut mapping 策略
        preserve_neutral_axis: 是否保护中性轴
        protect_black_white: 是否保护黑白场
        smoothing: 平滑方法
        smoothing_strength: 平滑强度（0.0-1.0）
    """
    grid_size: int = 33
    domain_min: float = 0.0
    domain_max: float = 1.0
    interpolation: str = "trilinear"  # "trilinear" or "tetrahedral"
    gamut_mapping: GamutMappingStrategy = GamutMappingStrategy.CLIP
    preserve_neutral_axis: bool = True
    protect_black_white: bool = True
    smoothing: SmoothingMethod = SmoothingMethod.NONE
    smoothing_strength: float = 0.0

    def __post_init__(self):
        """验证参数"""
        valid_sizes = [17, 21, 33, 65]
        if self.grid_size not in valid_sizes:
            raise ValueError(f"Invalid grid size: {self.grid_size}. Valid: {valid_sizes}")

        if self.interpolation not in ["trilinear", "tetrahedral"]:
            raise ValueError(f"Invalid interpolation: {self.interpolation}")

        if self.smoothing_strength < 0.0 or self.smoothing_strength > 1.0:
            raise ValueError(f"smoothing_strength must be in [0.0, 1.0]")


@dataclass
class BlackWhitePoint:
    """
    黑白场定义

    Attributes:
        black_rgb: 黑场 RGB (默认 [0, 0, 0])
        white_rgb: 白场 RGB (默认 [1, 1, 1])
        black_output: 黑场输出 RGB（保护）
        white_output: 白场输出 RGB（保护）
        black_tolerance: 黑场保护容差
        white_tolerance: 白场保护容差
    """
    black_rgb: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    white_rgb: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    black_output: Optional[Tuple[float, float, float]] = None
    white_output: Optional[Tuple[float, float, float]] = None
    black_tolerance: float = 0.01
    white_tolerance: float = 0.01


# ==============================================================================
# LUT3D 核心类
# ==============================================================================

class LUT3D:
    """
    3D LUT 核心类

    支持功能：
        - Grid 尺寸：17/21/33/65
        - 插值：trilinear, tetrahedral
        - 平滑：Gaussian, Median, Regularization
        - 中性轴保护
        - 黑白场保护
        - Gamut mapping
        - CUBE 导出
        - LUT 应用

    使用示例：
        >>> lut = LUT3D(grid_size=33)
        >>> lut.set_identity()  # 创建 identity LUT
        >>> lut.apply_to_rgb(0.5, 0.5, 0.5)  # 应用 LUT
        >>> lut.save_cube("output.cube")  # 导出
    """

    def __init__(
        self,
        spec: Optional[LUT3DSpec] = None,
        data: Optional[np.ndarray] = None,
    ):
        """
        初始化 3D LUT

        Args:
            spec: LUT 规格定义
            data: LUT 数据（numpy array，shape 为 [grid_size^3, 3] 或 [grid_size, grid_size, grid_size, 3]）
        """
        self.spec = spec or LUT3DSpec()
        self.grid_size = self.spec.grid_size

        # LUT 数据存储
        # Shape: [grid_size, grid_size, grid_size, 3]
        # 索引顺序：R -> G -> B（CUBE 格式标准）
        if data is not None:
            self._data = self._normalize_data(data)
        else:
            self._data = np.zeros((self.grid_size, self.grid_size, self.grid_size, 3), dtype=np.float32)

        # 黑白场保护
        self.bw_point: Optional[BlackWhitePoint] = None

        # 元数据
        self.title: str = ""
        self.source_space: str = ""
        self.target_space: str = ""

    def _normalize_data(self, data: np.ndarray) -> np.ndarray:
        """
        规范化 LUT 数据格式

        Args:
            data: 输入数据

        Returns:
            np.ndarray: 规范化的数据 [grid_size, grid_size, grid_size, 3]
        """
        if data.shape == (self.grid_size, self.grid_size, self.grid_size, 3):
            return data.astype(np.float32)

        # 如果是 flat 格式 [grid_size^3, 3]
        if data.shape == (self.grid_size ** 3, 3):
            reshaped = data.reshape((self.grid_size, self.grid_size, self.grid_size, 3))
            return reshaped.astype(np.float32)

        raise ValueError(f"Invalid LUT data shape: {data.shape}")

    @property
    def data(self) -> np.ndarray:
        """获取 LUT 数据"""
        return self._data

    def set_data(self, data: np.ndarray) -> None:
        """设置 LUT 数据"""
        self._data = self._normalize_data(data)

    def set_identity(self) -> None:
        """
        设置 identity LUT

        Identity LUT：输出 = 输入
        用于验证和测试
        """
        for r in range(self.grid_size):
            for g in range(self.grid_size):
                for b in range(self.grid_size):
                    # 输入值
                    ri = r / (self.grid_size - 1)
                    gi = g / (self.grid_size - 1)
                    bi = b / (self.grid_size - 1)

                    # 输出值 = 输入值
                    self._data[r, g, b] = [ri, gi, bi]

    def get_grid_rgb(self, r: int, g: int, b: int) -> Tuple[float, float, float]:
        """
        获取指定 grid 点的 RGB 输入值

        Args:
            r, g, b: Grid 索引

        Returns:
            Tuple[float, float, float]: RGB 输入值 (0-1)
        """
        ri = r / (self.grid_size - 1)
        gi = g / (self.grid_size - 1)
        bi = b / (self.grid_size - 1)
        return (ri, gi, bi)

    def get_output(self, r: int, g: int, b: int) -> Tuple[float, float, float]:
        """
        获取指定 grid 点的 RGB 输出值

        Args:
            r, g, b: Grid 索引

        Returns:
            Tuple[float, float, float]: RGB 输出值 (0-1)
        """
        return tuple(self._data[r, g, b])

    def set_output(self, r: int, g: int, b: int, output: Tuple[float, float, float]) -> None:
        """
        设置指定 grid 点的 RGB 输出值

        Args:
            r, g, b: Grid 索引
            output: RGB 输出值
        """
        self._data[r, g, b] = output

    # ==========================================================================
    # 插值方法
    # ==========================================================================

    def apply_to_rgb(
        self,
        r: float,
        g: float,
        b: float,
        method: Optional[str] = None,
    ) -> Tuple[float, float, float]:
        """
        应用 LUT 到 RGB 值

        Args:
            r, g, b: 输入 RGB (0-1)
            method: 插值方法（默认使用 spec.interpolation）

        Returns:
            Tuple[float, float, float]: 输出 RGB (0-1)
        """
        method = method or self.spec.interpolation

        # Clamp 输入到 [0, 1]
        r = max(0.0, min(1.0, r))
        g = max(0.0, min(1.0, g))
        b = max(0.0, min(1.0, b))

        if method == "trilinear":
            return self._interpolate_trilinear(r, g, b)
        elif method == "tetrahedral":
            return self._interpolate_tetrahedral(r, g, b)
        else:
            raise ValueError(f"Unknown interpolation method: {method}")

    def _interpolate_trilinear(
        self,
        r: float,
        g: float,
        b: float,
    ) -> Tuple[float, float, float]:
        """
        三线性插值

        在 3D grid 的 8 个邻近点之间进行线性插值

        Args:
            r, g, b: 输入 RGB (0-1)

        Returns:
            Tuple[float, float, float]: 输出 RGB
        """
        gs = self.grid_size - 1

        # 计算索引和权重
        rf = r * gs
        gf = g * gs
        bf = b * gs

        r0 = int(rf)
        g0 = int(gf)
        b0 = int(bf)

        r0 = min(r0, gs - 1)
        g0 = min(g0, gs - 1)
        b0 = min(b0, gs - 1)

        r1 = r0 + 1
        g1 = g0 + 1
        b1 = b0 + 1

        r1 = min(r1, gs)
        g1 = min(g1, gs)
        b1 = min(b1, gs)

        # 权重
        dr = rf - r0
        dg = gf - g0
        db = bf - b0

        # 8 个邻近点
        # 000, 100, 010, 110, 001, 101, 011, 111
        c000 = self._data[r0, g0, b0]
        c100 = self._data[r1, g0, b0]
        c010 = self._data[r0, g1, b0]
        c110 = self._data[r1, g1, b0]
        c001 = self._data[r0, g0, b1]
        c101 = self._data[r1, g0, b1]
        c011 = self._data[r0, g1, b1]
        c111 = self._data[r1, g1, b1]

        # 三线性插值公式
        # 先沿 R 轴插值
        c00 = c000 * (1 - dr) + c100 * dr
        c01 = c001 * (1 - dr) + c101 * dr
        c10 = c010 * (1 - dr) + c110 * dr
        c11 = c011 * (1 - dr) + c111 * dr

        # 再沿 G 轴插值
        c0 = c00 * (1 - dg) + c10 * dg
        c1 = c01 * (1 - dg) + c11 * dg

        # 最后沿 B 轴插值
        result = c0 * (1 - db) + c1 * db

        return tuple(result)

    def _interpolate_tetrahedral(
        self,
        r: float,
        g: float,
        b: float,
    ) -> Tuple[float, float, float]:
        """
        四面体插值

        比 trilinear 更精确，使用 4 个点而非 8 个

        参考：Kasson & Plouffe (1992) "An Analysis of Selected Computer
        Interpolation Methods"

        Args:
            r, g, b: 输入 RGB (0-1)

        Returns:
            Tuple[float, float, float]: 输出 RGB
        """
        gs = self.grid_size - 1

        # 计算索引和权重
        rf = r * gs
        gf = g * gs
        bf = b * gs

        r0 = int(rf)
        g0 = int(gf)
        b0 = int(bf)

        r0 = min(r0, gs - 1)
        g0 = min(g0, gs - 1)
        b0 = min(b0, gs - 1)

        r1 = r0 + 1
        g1 = g0 + 1
        b1 = b0 + 1

        r1 = min(r1, gs)
        g1 = min(g1, gs)
        b1 = min(b1, gs)

        # 权重（归一化）
        dr = rf - r0
        dg = gf - g0
        db = bf - b0

        # 确定四面体类型（根据 dr, dg, db 的相对大小）
        # 将 cube 分割为 6 个四面体

        c000 = self._data[r0, g0, b0]
        c100 = self._data[r1, g0, b0]
        c010 = self._data[r0, g1, b0]
        c110 = self._data[r1, g1, b0]
        c001 = self._data[r0, g0, b1]
        c101 = self._data[r1, g0, b1]
        c011 = self._data[r0, g1, b1]
        c111 = self._data[r1, g1, b1]

        # 四面体分割
        # 参考：OpenColorIO tetrahedral interpolation
        if dr >= dg:
            if dg >= db:
                # Tetrahedron 1: 000 -> 100 -> 110 -> 111
                result = (
                    c000 +
                    dr * (c100 - c000) +
                    dg * (c110 - c100) +
                    db * (c111 - c110)
                )
            elif dr >= db:
                # Tetrahedron 2: 000 -> 100 -> 101 -> 111
                result = (
                    c000 +
                    dr * (c100 - c000) +
                    db * (c101 - c100) +
                    dg * (c111 - c101)
                )
            else:
                # Tetrahedron 3: 000 -> 001 -> 101 -> 111
                result = (
                    c000 +
                    db * (c001 - c000) +
                    dr * (c101 - c001) +
                    dg * (c111 - c101)
                )
        else:
            if db >= dg:
                # Tetrahedron 4: 000 -> 001 -> 011 -> 111
                result = (
                    c000 +
                    db * (c001 - c000) +
                    dg * (c011 - c001) +
                    dr * (c111 - c011)
                )
            elif db >= dr:
                # Tetrahedron 5: 000 -> 010 -> 011 -> 111
                result = (
                    c000 +
                    dg * (c010 - c000) +
                    db * (c011 - c010) +
                    dr * (c111 - c011)
                )
            else:
                # Tetrahedron 6: 000 -> 010 -> 110 -> 111
                result = (
                    c000 +
                    dg * (c010 - c000) +
                    dr * (c110 - c010) +
                    db * (c111 - c110)
                )

        return tuple(result)

    # ==========================================================================
    # 平滑/正则化
    # ==========================================================================

    def apply_smoothing(
        self,
        method: Optional[SmoothingMethod] = None,
        strength: Optional[float] = None,
    ) -> None:
        """
        应用平滑滤波

        Args:
            method: 平滑方法
            strength: 平滑强度 (0-1)
        """
        method = method or self.spec.smoothing
        strength = strength or self.spec.smoothing_strength

        if method == SmoothingMethod.NONE or strength == 0.0:
            return

        if method == SmoothingMethod.GAUSSIAN:
            self._apply_gaussian_smoothing(strength)
        elif method == SmoothingMethod.MEDIAN:
            self._apply_median_smoothing(strength)
        elif method == SmoothingMethod.REGULARIZATION:
            self._apply_regularization(strength)

    def _apply_gaussian_smoothing(self, strength: float) -> None:
        """
        Gaussian 滤波平滑

        使用 3D Gaussian kernel

        Args:
            strength: 平滑强度 (0-1)，影响 kernel sigma
        """
        # Sigma 根据 strength 计算
        sigma = strength * 2.0  # 最大 sigma = 2.0

        # 生成 3D Gaussian kernel
        kernel_size = 3
        kernel = self._generate_gaussian_kernel_3d(kernel_size, sigma)

        # 应用卷积
        smoothed = self._convolve_3d(self._data, kernel)

        # 保护黑白场和中性轴后再赋值
        self._data = self._apply_protection(smoothed)

    def _generate_gaussian_kernel_3d(self, size: int, sigma: float) -> np.ndarray:
        """
        生成 3D Gaussian kernel

        Args:
            size: Kernel 尺寸（通常 3）
            sigma: Sigma 值

        Returns:
            np.ndarray: 3D Gaussian kernel
        """
        center = size // 2
        kernel = np.zeros((size, size, size), dtype=np.float32)

        for i in range(size):
            for j in range(size):
                for k in range(size):
                    d = math.sqrt((i - center) ** 2 + (j - center) ** 2 + (k - center) ** 2)
                    kernel[i, j, k] = math.exp(-(d ** 2) / (2 * sigma ** 2))

        # 归一化
        kernel /= kernel.sum()

        return kernel

    def _convolve_3d(self, data: np.ndarray, kernel: np.ndarray) -> np.ndarray:
        """
        3D 卷积

        Args:
            data: LUT 数据 [gs, gs, gs, 3]
            kernel: 3D kernel [k, k, k]

        Returns:
            np.ndarray: 卷积结果
        """
        gs = self.grid_size
        result = np.zeros_like(data)
        ks = kernel.shape[0]
        kc = ks // 2

        # 对每个通道分别卷积
        for c in range(3):
            for r in range(gs):
                for g in range(gs):
                    for b in range(gs):
                        value = 0.0
                        for ki in range(ks):
                            for kj in range(ks):
                                for kk in range(ks):
                                    ri = r + ki - kc
                                    gi = g + kj - kc
                                    bi = b + kk - kc

                                    # 边界处理：镜像
                                    ri = max(0, min(gs - 1, ri))
                                    gi = max(0, min(gs - 1, gi))
                                    bi = max(0, min(gs - 1, bi))

                                    value += data[ri, gi, bi, c] * kernel[ki, kj, kk]

                        result[r, g, b, c] = value

        return result

    def _apply_median_smoothing(self, strength: float) -> None:
        """
        Median 滤波平滑

        Args:
            strength: 平滑强度，影响窗口大小
        """
        # 窯大小根据 strength 计算
        window_size = 3 if strength < 0.5 else 5

        gs = self.grid_size
        result = np.zeros_like(self._data)
        wc = window_size // 2

        for c in range(3):
            for r in range(gs):
                for g in range(gs):
                    for b in range(gs):
                        # 收集窗口内的值
                        values = []
                        for wi in range(window_size):
                            for wj in range(window_size):
                                for wk in range(window_size):
                                    ri = r + wi - wc
                                    gi = g + wj - wc
                                    bi = b + wk - wc

                                    ri = max(0, min(gs - 1, ri))
                                    gi = max(0, min(gs - 1, gi))
                                    bi = max(0, min(gs - 1, bi))

                                    values.append(self._data[ri, gi, bi, c])

                        result[r, g, b, c] = np.median(values)

        self._data = self._apply_protection(result)

    def _apply_regularization(self, strength: float) -> None:
        """
        Tikhonov 正则化

        平滑 LUT 同时最小化与原始数据的偏差

        Args:
            strength: 正则化参数 lambda
        """
        # 简化实现：使用相邻点平均
        lambda_val = strength

        gs = self.grid_size
        result = np.zeros_like(self._data)

        for r in range(gs):
            for g in range(gs):
                for b in range(gs):
                    # 当前值
                    current = self._data[r, g, b]

                    # 相邻点平均
                    neighbors_sum = np.zeros(3)
                    neighbors_count = 0

                    for dr in [-1, 0, 1]:
                        for dg in [-1, 0, 1]:
                            for db in [-1, 0, 1]:
                                if dr == 0 and dg == 0 and db == 0:
                                    continue

                                ri = r + dr
                                gi = g + dg
                                bi = b + db

                                if 0 <= ri < gs and 0 <= gi < gs and 0 <= bi < gs:
                                    neighbors_sum += self._data[ri, gi, bi]
                                    neighbors_count += 1

                    if neighbors_count > 0:
                        neighbors_avg = neighbors_sum / neighbors_count
                        # 正则化：current + lambda * (neighbors_avg - current)
                        result[r, g, b] = current + lambda_val * (neighbors_avg - current)
                    else:
                        result[r, g, b] = current

        self._data = self._apply_protection(result)

    # ==========================================================================
    # 保护机制
    # ==========================================================================

    def set_black_white_point(
        self,
        black_rgb: Tuple[float, float, float] = (0.0, 0.0, 0.0),
        white_rgb: Tuple[float, float, float] = (1.0, 1.0, 1.0),
        black_output: Optional[Tuple[float, float, float]] = None,
        white_output: Optional[Tuple[float, float, float]] = None,
    ) -> None:
        """
        设置黑白场保护

        Args:
            black_rgb: 黑场输入 RGB
            white_rgb: 白场输入 RGB
            black_output: 黑场输出 RGB（默认为 black_rgb）
            white_output: 白场输出 RGB（默认为 white_rgb）
        """
        self.bw_point = BlackWhitePoint(
            black_rgb=black_rgb,
            white_rgb=white_rgb,
            black_output=black_output or black_rgb,
            white_output=white_output or white_rgb,
        )

    def _apply_protection(self, data: np.ndarray) -> np.ndarray:
        """
        应用保护机制：中性轴、黑白场

        Args:
            data: 待保护的数据

        Returns:
            np.ndarray: 保护后的数据
        """
        result = data.copy()

        # 中性轴保护
        if self.spec.preserve_neutral_axis:
            result = self._protect_neutral_axis(result)

        # 黑白场保护
        if self.spec.protect_black_white and self.bw_point:
            result = self._protect_black_white(result)

        return result

    def _protect_neutral_axis(self, data: np.ndarray) -> np.ndarray:
        """
        保护中性轴（R=G=B 的灰色）

        中性轴上的点必须保持中性：
        - 输入 [x, x, x] -> 输出 [y, y, y]

        Args:
            data: LUT 数据

        Returns:
            np.ndarray: 保护中性轴后的数据
        """
        gs = self.grid_size

        for i in range(gs):
            # 中性轴上的 grid 点：[i, i, i]
            # 输入：ri = gi = bi = i/(gs-1)
            rgb_in = i / (gs - 1)

            # 获取当前输出
            r_out = data[i, i, i, 0]
            g_out = data[i, i, i, 1]
            b_out = data[i, i, i, 2]

            # 计算平均值（保持中性）
            avg = (r_out + g_out + b_out) / 3.0

            # 强制中性
            data[i, i, i] = [avg, avg, avg]

        return data

    def _protect_black_white(self, data: np.ndarray) -> np.ndarray:
        """
        保护黑白场

        黑场和白场附近的点强制输出为指定的值

        Args:
            data: LUT 数据

        Returns:
            np.ndarray: 保护黑白场后的数据
        """
        if not self.bw_point:
            return data

        gs = self.grid_size

        # 黑场保护
        black_idx = int(self.bw_point.black_rgb[0] * (gs - 1))
        black_tol_idx = int(self.bw_point.black_tolerance * (gs - 1))

        for r in range(max(0, black_idx - black_tol_idx), min(gs, black_idx + black_tol_idx + 1)):
            for g in range(max(0, black_idx - black_tol_idx), min(gs, black_idx + black_tol_idx + 1)):
                for b in range(max(0, black_idx - black_tol_idx), min(gs, black_idx + black_tol_idx + 1)):
                    # 计算距离
                    dist = math.sqrt((r - black_idx) ** 2 + (g - black_idx) ** 2 + (b - black_idx) ** 2)
                    if dist <= black_tol_idx:
                        # 越近权重越高
                        weight = 1.0 - dist / (black_tol_idx + 1)
                        data[r, g, b] = (
                            weight * self.bw_point.black_output[0] + (1 - weight) * data[r, g, b, 0],
                            weight * self.bw_point.black_output[1] + (1 - weight) * data[r, g, b, 1],
                            weight * self.bw_point.black_output[2] + (1 - weight) * data[r, g, b, 2],
                        )

        # 白场保护
        white_idx = int(self.bw_point.white_rgb[0] * (gs - 1))
        white_tol_idx = int(self.bw_point.white_tolerance * (gs - 1))

        for r in range(max(0, white_idx - white_tol_idx), min(gs, white_idx + white_tol_idx + 1)):
            for g in range(max(0, white_idx - white_tol_idx), min(gs, white_idx + white_tol_idx + 1)):
                for b in range(max(0, white_idx - white_tol_idx), min(gs, white_idx + white_tol_idx + 1)):
                    dist = math.sqrt((r - white_idx) ** 2 + (g - white_idx) ** 2 + (b - white_idx) ** 2)
                    if dist <= white_tol_idx:
                        weight = 1.0 - dist / (white_tol_idx + 1)
                        data[r, g, b] = (
                            weight * self.bw_point.white_output[0] + (1 - weight) * data[r, g, b, 0],
                            weight * self.bw_point.white_output[1] + (1 - weight) * data[r, g, b, 1],
                            weight * self.bw_point.white_output[2] + (1 - weight) * data[r, g, b, 2],
                        )

        return data

    # ==========================================================================
    # Gamut Mapping
    # ==========================================================================

    def apply_gamut_mapping(
        self,
        strategy: Optional[GamutMappingStrategy] = None,
        target_gamut: Optional[str] = None,
    ) -> None:
        """
        应用 Gamut mapping

        Args:
            strategy: Mapping 策略
            target_gamut: 目标色域名称
        """
        strategy = strategy or self.spec.gamut_mapping

        if strategy == GamutMappingStrategy.CLIP:
            self._apply_gamut_clip(target_gamut)
        elif strategy == GamutMappingStrategy.PERCEPTUAL:
            self._apply_perceptual_gamut_mapping(target_gamut)

    def _apply_gamut_clip(self, target_gamut: Optional[str] = None) -> None:
        """
        简单裁剪 Gamut mapping

        将所有输出 RGB 裁剪到 [0, 1] 范围

        Args:
            target_gamut: 目标色域（目前只支持简单裁剪）
        """
        gs = self.grid_size

        for r in range(gs):
            for g in range(gs):
                for b in range(gs):
                    # 裁剪到 [0, 1]
                    self._data[r, g, b] = np.clip(self._data[r, g, b], 0.0, 1.0)

    def _apply_perceptual_gamut_mapping(
        self,
        target_gamut: Optional[str] = None,
        compression_factor: float = 0.8,
    ) -> None:
        """
        感知 Gamut mapping

        使用 ICC perceptual intent 类似的方法：
        - 识别色域外颜色
        - 压缩色域边界
        - 保持视觉连续性

        参考：ICC v4 Perceptual Intent

        Args:
            target_gamut: 目标色域名称
            compression_factor: 压缩因子 (0-1)
        """
        # 获取目标色域范围
        if target_gamut and target_gamut in COLOR_SPACES:
            # 使用目标色域的 primaries 计算有效范围
            # 这里简化为 [0, 1] 范围
            pass

        gs = self.grid_size

        # 计算每个 grid 点的色域状态
        for r in range(gs):
            for g in range(gs):
                for b in range(gs):
                    rgb_out = self._data[r, g, b]

                    # 检查是否在色域外
                    is_out_of_gamut = any(c < 0 or c > 1 for c in rgb_out)

                    if is_out_of_gamut:
                        # 转换到 Lab
                        # 注意：需要先转换到线性 RGB
                        rgb_linear = [eotf_srgb(c) if c > 0 else 0 for c in rgb_out]
                        X, Y, Z = rgb_to_xyz(rgb_linear[0], rgb_linear[1], rgb_linear[2], "sRGB", linear=True)
                        Lab = xyz_to_lab(X, Y, Z, "D65")

                        # 计算 LCH
                        L, C, H = lab_to_lch(Lab[0], Lab[1], Lab[2])

                        # 压缩色度（保持亮度和色调）
                        C_compressed = C * compression_factor

                        # 转换回 RGB
                        Lab_compressed = lch_to_lab(L, C_compressed, H)
                        X_c, Y_c, Z_c = lab_to_xyz(Lab_compressed[0], Lab_compressed[1], Lab_compressed[2], "D65")
                        rgb_linear_c = xyz_to_rgb(X_c, Y_c, Z_c, "sRGB", apply_gamma=False)

                        # 转换回非线性 RGB
                        rgb_out_c = [oetf_srgb(max(0, min(1, c))) for c in rgb_linear_c]

                        # 再次裁剪确保在范围内
                        self._data[r, g, b] = np.clip(rgb_out_c, 0.0, 1.0)

    # ==========================================================================
    # CUBE 导出
    # ==========================================================================

    def save_cube(self, filepath: str, title: Optional[str] = None) -> None:
        """
        导出为 CUBE 格式

        CUBE 格式规范：
        - TITLE: LUT 标题
        - LUT_3D_SIZE: Grid 尺寸
        - DOMAIN_MIN/MAX: 输入范围
        - 数据顺序：B -> G -> R（CUBE 标准）

        Args:
            filepath: 输出文件路径
            title: LUT 标题
        """
        title = title or self.title or "Generated LUT"

        with open(filepath, 'w', encoding='utf-8') as f:
            # 写入标题
            f.write(f'TITLE "{title}"\n')

            # 写入尺寸
            f.write(f'LUT_3D_SIZE {self.grid_size}\n')

            # 写入域范围
            f.write(f'DOMAIN_MIN {self.spec.domain_min:.6f} {self.spec.domain_min:.6f} {self.spec.domain_min:.6f}\n')
            f.write(f'DOMAIN_MAX {self.spec.domain_max:.6f} {self.spec.domain_max:.6f} {self.spec.domain_max:.6f}\n')

            # 写入元数据（可选）
            if self.source_space:
                f.write(f'# Source: {self.source_space}\n')
            if self.target_space:
                f.write(f'# Target: {self.target_space}\n')

            f.write('\n')

            # 写入数据
            # CUBE 格式顺序：B -> G -> R
            # 即先遍历 B，再 G，最后 R
            for b in range(self.grid_size):
                for g in range(self.grid_size):
                    for r in range(self.grid_size):
                        rgb_out = self._data[r, g, b]
                        f.write(f'{rgb_out[0]:.6f} {rgb_out[1]:.6f} {rgb_out[2]:.6f}\n')

    def load_cube(self, filepath: str) -> None:
        """
        从 CUBE 格式加载

        Args:
            filepath: CUBE 文件路径
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 解析头部
        grid_size = None
        domain_min = 0.0
        domain_max = 1.0
        title = ""

        data_start_idx = 0
        for i, line in enumerate(lines):
            line = line.strip()

            if line.startswith('TITLE'):
                # TITLE "xxx"
                title = line.split('"')[1] if '"' in line else line.split()[-1]
                self.title = title

            elif line.startswith('LUT_3D_SIZE'):
                grid_size = int(line.split()[-1])
                self.grid_size = grid_size
                self.spec.grid_size = grid_size

            elif line.startswith('DOMAIN_MIN'):
                parts = line.split()
                domain_min = float(parts[1])

            elif line.startswith('DOMAIN_MAX'):
                parts = line.split()
                domain_max = float(parts[1])

            elif line.startswith('#'):
                # 注释，跳过
                continue

            elif not line or line.isspace():
                # 空行，跳过
                continue

            else:
                # 数据开始
                data_start_idx = i
                break

        if grid_size is None:
            raise ValueError("Missing LUT_3D_SIZE in CUBE file")

        # 初始化数据
        self._data = np.zeros((grid_size, grid_size, grid_size, 3), dtype=np.float32)

        # 读取数据
        # CUBE 格式顺序：B -> G -> R
        data_lines = lines[data_start_idx:]
        expected_count = grid_size ** 3

        if len(data_lines) < expected_count:
            raise ValueError(f"Not enough data lines: {len(data_lines)} < {expected_count}")

        idx = 0
        for b in range(grid_size):
            for g in range(grid_size):
                for r in range(grid_size):
                    line = data_lines[idx].strip()
                    parts = line.split()

                    if len(parts) >= 3:
                        self._data[r, g, b] = [float(parts[0]), float(parts[1]), float(parts[2])]

                    idx += 1

        # 更新 spec
        self.spec.domain_min = domain_min
        self.spec.domain_max = domain_max

    # ==========================================================================
    # Validation 支持
    # ==========================================================================

    def apply_to_rgb_batch(
        self,
        rgb_values: List[Tuple[float, float, float]],
        method: Optional[str] = None,
    ) -> List[Tuple[float, float, float]]:
        """
        批量应用 LUT

        供 ValidationWorkflow 使用

        Args:
            rgb_values: RGB 输入值列表 (0-1)
            method: 插值方法

        Returns:
            List[Tuple[float, float, float]]: RGB 输出值列表
        """
        return [self.apply_to_rgb(r, g, b, method) for r, g, b in rgb_values]

    def compute_identity_error(self) -> Dict[str, float]:
        """
        计算 identity LUT 误差

        用于验证：identity LUT 应用后误差应接近 0

        Returns:
            Dict[str, float]: 误差统计
                - max_error: 最大误差
                - mean_error: 平均误差
                - neutral_axis_error: 中性轴误差
        """
        gs = self.grid_size
        errors = []
        neutral_errors = []

        for r in range(gs):
            for g in range(gs):
                for b in range(gs):
                    ri = r / (gs - 1)
                    gi = g / (gs - 1)
                    bi = b / (gs - 1)

                    # 应用 LUT
                    ro, go, bo = self.apply_to_rgb(ri, gi, bi)

                    # 计算 identity 误差
                    error = math.sqrt((ro - ri) ** 2 + (go - gi) ** 2 + (bo - bi) ** 2)
                    errors.append(error)

                    # 中性轴检查
                    if r == g == b:
                        neutral_errors.append(error)

        return {
            "max_error": max(errors),
            "mean_error": sum(errors) / len(errors),
            "neutral_axis_error": sum(neutral_errors) / len(neutral_errors) if neutral_errors else 0.0,
            "num_points": len(errors),
        }


# ==============================================================================
# Synthetic Display Model
# ==============================================================================

@dataclass
class SyntheticDisplaySpec:
    """
    Synthetic display 规格定义

    用于生成测试 fixture：
        - identity: 无偏差
        - gamma_deviation: Gamma 偏差
        - gamut_deviation: Gamut matrix 偏差
        - nonlinearity: 非线性偏差

    Attributes:
        name: Display 名称
        gamma: 目标 Gamma
        gamma_deviation: Gamma 偏差值
        gamut_matrix: Gamut 变换矩阵 (3x3)
        nonlinearity_strength: 非线性强度
        white_point: 白点名称
        color_space: 色彩空间
    """
    name: str = "Identity"
    gamma: float = 2.4
    gamma_deviation: float = 0.0
    gamut_matrix: Optional[List[List[float]]] = None
    nonlinearity_strength: float = 0.0
    white_point: str = "D65"
    color_space: str = "Rec709"


class SyntheticDisplayModel:
    """
    Synthetic Display Model

    用于生成测试 fixture 和验证 LUT 效果

    使用示例：
        >>> # Identity display
        >>> model = SyntheticDisplayModel()
        >>> model.generate_lut_identity()
        >>> lut = model.create_correction_lut()

        >>> # Gamma 偏差 display
        >>> spec = SyntheticDisplaySpec(gamma_deviation=0.2)
        >>> model = SyntheticDisplayModel(spec)
        >>> lut = model.create_correction_lut()
    """

    def __init__(self, spec: Optional[SyntheticDisplaySpec] = None):
        """
        初始化 Synthetic Display

        Args:
            spec: Display 规格定义
        """
        self.spec = spec or SyntheticDisplaySpec()
        self._target_gamma = self.spec.gamma

        # 生成偏差 Gamma（如果有）
        if self.spec.gamma_deviation != 0:
            self._display_gamma = self.spec.gamma + self.spec.gamma_deviation
        else:
            self._display_gamma = self.spec.gamma

    def simulate_display_output(
        self,
        r: float,
        g: float,
        b: float,
    ) -> Tuple[float, float, float]:
        """
        模拟 display 输出

        应用偏差变换：
            1. Gamma 偏差
            2. Gamut matrix 偏差
            3. 非线性偏差

        Args:
            r, g, b: 输入 RGB (0-1)

        Returns:
            Tuple[float, float, float]: 输出 RGB
        """
        # 1. Gamma 偏差
        r_out = self._apply_gamma_deviation(r)
        g_out = self._apply_gamma_deviation(g)
        b_out = self._apply_gamma_deviation(b)

        # 2. Gamut matrix 偏差
        if self.spec.gamut_matrix:
            r_out, g_out, b_out = self._apply_gamut_deviation(r_out, g_out, b_out)

        # 3. 非线性偏差
        if self.spec.nonlinearity_strength > 0:
            r_out, g_out, b_out = self._apply_nonlinearity(r_out, g_out, b_out)

        return (r_out, g_out, b_out)

    def _apply_gamma_deviation(self, v: float) -> float:
        """
        应用 Gamma 偏差

        Args:
            v: 输入值 (0-1)

        Returns:
            float: 偏差后的输出值
        """
        if v <= 0:
            return 0.0

        # 模拟：display 使用偏差 Gamma，但期望是目标 Gamma
        # 输入 -> 显示 Gamma -> 输出
        return math.pow(v, self._display_gamma)

    def _apply_gamut_deviation(
        self,
        r: float,
        g: float,
        b: float,
    ) -> Tuple[float, float, float]:
        """
        应用 Gamut matrix 偏差

        Args:
            r, g, b: RGB 值

        Returns:
            Tuple[float, float, float]: 偏差后的 RGB
        """
        if not self.spec.gamut_matrix:
            return (r, g, b)

        M = self.spec.gamut_matrix

        ro = M[0][0] * r + M[0][1] * g + M[0][2] * b
        go = M[1][0] * r + M[1][1] * g + M[1][2] * b
        bo = M[2][0] * r + M[2][1] * g + M[2][2] * b

        return (ro, go, bo)

    def _apply_nonlinearity(
        self,
        r: float,
        g: float,
        b: float,
    ) -> Tuple[float, float, float]:
        """
        应用非线性偏差

        模拟 display 的非线性响应

        Args:
            r, g, b: RGB 值

        Returns:
            Tuple[float, float, float]: 偏差后的 RGB
        """
        strength = self.spec.nonlinearity_strength

        # 非线性：在中等亮度区域产生偏差
        # 例如：二次项偏差
        def apply_nonlin(v: float) -> float:
            # 在 0.5 附近产生最大偏差
            deviation = strength * (v - 0.5) ** 2 * 0.5
            return v + deviation * (1 - v)  # 在边界减小偏差

        return (apply_nonlin(r), apply_nonlin(g), apply_nonlin(b))

    def create_correction_lut(
        self,
        grid_size: int = 33,
    ) -> LUT3D:
        """
        创建校正 LUT

        将 display 输出映射回目标值

        Args:
            grid_size: LUT 尺寸

        Returns:
            LUT3D: 校正 LUT
        """
        lut = LUT3D(LUT3DSpec(grid_size=grid_size))

        # 为每个 grid 点计算校正
        for r in range(grid_size):
            for g in range(grid_size):
                for b in range(grid_size):
                    ri = r / (grid_size - 1)
                    gi = g / (grid_size - 1)
                    bi = b / (grid_size - 1)

                    # 目标：输入值
                    # Display 输出：simulate_display_output(ri, gi, bi)
                    # 我们需要逆向映射

                    # 方法：找到 display 输出等于 ri, gi, bi 的输入值
                    # 即 solve simulate_display_output(r_in) = ri

                    # 逆向 Gamma
                    ri_corrected = self._invert_gamma_deviation(ri)
                    gi_corrected = self._invert_gamma_deviation(gi)
                    bi_corrected = self._invert_gamma_deviation(bi)

                    # 逆向 Gamut matrix
                    if self.spec.gamut_matrix:
                        ri_corrected, gi_corrected, bi_corrected = self._invert_gamut_deviation(
                            ri_corrected, gi_corrected, bi_corrected
                        )

                    # 逆向非线性
                    if self.spec.nonlinearity_strength > 0:
                        ri_corrected, gi_corrected, bi_corrected = self._invert_nonlinearity(
                            ri_corrected, gi_corrected, bi_corrected
                        )

                    lut.set_output(r, g, b, (ri_corrected, gi_corrected, bi_corrected))

        return lut

    def _invert_gamma_deviation(self, v: float) -> float:
        """
        逆向 Gamma 偏差

        Args:
            v: 输出值

        Returns:
            float: 输入值（校正后的）
        """
        if v <= 0:
            return 0.0

        # 显示 Gamma: v_out = v_in^gamma_display
        # 逆向: v_in = v_out^(1/gamma_display)
        # 校正 Gamma: v_correct = v_out^(gamma_target/gamma_display)
        return math.pow(v, self._target_gamma / self._display_gamma)

    def _invert_gamut_deviation(
        self,
        r: float,
        g: float,
        b: float,
    ) -> Tuple[float, float, float]:
        """
        逆向 Gamut matrix 偏差

        Args:
            r, g, b: RGB 值

        Returns:
            Tuple[float, float, float]: 校正后的 RGB
        """
        if not self.spec.gamut_matrix:
            return (r, g, b)

        # 计算逆矩阵
        M = self.spec.gamut_matrix

        # 3x3 矩阵求逆
        det = (
            M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1]) -
            M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0]) +
            M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0])
        )

        if abs(det) < 1e-10:
            # 矩阵接近奇异，使用原始值
            return (r, g, b)

        inv_det = 1.0 / det

        M_inv = [
            [
                (M[1][1] * M[2][2] - M[1][2] * M[2][1]) * inv_det,
                (M[0][2] * M[2][1] - M[0][1] * M[2][2]) * inv_det,
                (M[0][1] * M[1][2] - M[0][2] * M[1][1]) * inv_det,
            ],
            [
                (M[1][2] * M[2][0] - M[1][0] * M[2][2]) * inv_det,
                (M[0][0] * M[2][2] - M[0][2] * M[2][0]) * inv_det,
                (M[0][2] * M[1][0] - M[0][0] * M[1][2]) * inv_det,
            ],
            [
                (M[1][0] * M[2][1] - M[1][1] * M[2][0]) * inv_det,
                (M[0][1] * M[2][0] - M[0][0] * M[2][1]) * inv_det,
                (M[0][0] * M[1][1] - M[0][1] * M[1][0]) * inv_det,
            ],
        ]

        ro = M_inv[0][0] * r + M_inv[0][1] * g + M_inv[0][2] * b
        go = M_inv[1][0] * r + M_inv[1][1] * g + M_inv[1][2] * b
        bo = M_inv[2][0] * r + M_inv[2][1] * g + M_inv[2][2] * b

        return (ro, go, bo)

    def _invert_nonlinearity(
        self,
        r: float,
        g: float,
        b: float,
    ) -> Tuple[float, float, float]:
        """
        逆向非线性偏差

        Args:
            r, g, b: RGB 值

        Returns:
            Tuple[float, float, float]: 校正后的 RGB
        """
        strength = self.spec.nonlinearity_strength

        if strength == 0:
            return (r, g, b)

        # 使用 Newton-Raphson 方法求解逆向
        def invert_nonlin(v_out: float) -> float:
            # 目标：找到 v_in 使得 apply_nonlin(v_in) = v_out
            # f(v) = v + strength * (v - 0.5)^2 * 0.5 * (1 - v) - v_out

            v = v_out  # 初始估计

            for _ in range(10):  # Newton-Raphson iterations
                # f(v)
                f = v + strength * (v - 0.5) ** 2 * 0.5 * (1 - v) - v_out

                # f'(v)
                f_prime = 1 + strength * 0.5 * (
                    2 * (v - 0.5) * (1 - v) - (v - 0.5) ** 2
                )

                if abs(f_prime) < 1e-10:
                    break

                v_new = v - f / f_prime

                if abs(v_new - v) < 1e-6:
                    break

                v = max(0.0, min(1.0, v_new))

            return v

        return (invert_nonlin(r), invert_nonlin(g), invert_nonlin(b))

    def measure_delta_e_reduction(
        self,
        test_rgb: List[Tuple[float, float, float]],
        lut: Optional[LUT3D] = None,
    ) -> Dict[str, float]:
        """
        测量 Delta E 降低效果

        Args:
            test_rgb: 测试 RGB 值列表
            lut: 校正 LUT（可选）

        Returns:
            Dict[str, float]: Delta E 统计
                - before_avg: 校正前平均 Delta E
                - before_max: 校正前最大 Delta E
                - after_avg: 校正后平均 Delta E（如果有 LUT）
                - after_max: 校正后最大 Delta E
                - reduction: Delta E 降低百分比
        """
        before_delta_e = []
        after_delta_e = []

        for ri, gi, bi in test_rgb:
            # 目标 Lab（期望值）
            # 使用目标 Gamma 计算
            r_target = math.pow(ri, self._target_gamma) if ri > 0 else 0
            g_target = math.pow(gi, self._target_gamma) if gi > 0 else 0
            b_target = math.pow(bi, self._target_gamma) if bi > 0 else 0

            X_t, Y_t, Z_t = rgb_to_xyz(r_target, g_target, b_target, "sRGB", linear=True)
            Lab_target = xyz_to_lab(X_t * 100, Y_t * 100, Z_t * 100, "D65")

            # Display 输出（偏差）
            ro, go, bo = self.simulate_display_output(ri, gi, bi)

            X_d, Y_d, Z_d = rgb_to_xyz(ro, go, bo, "sRGB", linear=True)
            Lab_display = xyz_to_lab(X_d * 100, Y_d * 100, Z_d * 100, "D65")

            # 校正前 Delta E
            de_before = delta_e_ciede2000(Lab_target, Lab_display)
            before_delta_e.append(de_before)

            # 如果有 LUT，计算校正后 Delta E
            if lut:
                # 应用 LUT 到输入值
                r_lut, g_lut, b_lut = lut.apply_to_rgb(ri, gi, bi)

                # LUT 输出经过 display
                ro_corr, go_corr, bo_corr = self.simulate_display_output(r_lut, g_lut, b_lut)

                X_c, Y_c, Z_c = rgb_to_xyz(ro_corr, go_corr, bo_corr, "sRGB", linear=True)
                Lab_corrected = xyz_to_lab(X_c * 100, Y_c * 100, Z_c * 100, "D65")

                de_after = delta_e_ciede2000(Lab_target, Lab_corrected)
                after_delta_e.append(de_after)

        result = {
            "before_avg": sum(before_delta_e) / len(before_delta_e),
            "before_max": max(before_delta_e),
        }

        if lut and after_delta_e:
            result["after_avg"] = sum(after_delta_e) / len(after_delta_e)
            result["after_max"] = max(after_delta_e)
            result["reduction"] = (result["before_avg"] - result["after_avg"]) / result["before_avg"] * 100

        return result


# ==============================================================================
# Fixture 生成函数
# ==============================================================================

def create_identity_display_fixture() -> Tuple[LUT3D, SyntheticDisplayModel]:
    """
    创建 identity display fixture

    无偏差的 display，用于验证 identity LUT

    Returns:
        Tuple[LUT3D, SyntheticDisplayModel]: (identity LUT, display model)
    """
    spec = SyntheticDisplaySpec(
        name="Identity",
        gamma=2.4,
        gamma_deviation=0.0,
        gamut_matrix=None,
        nonlinearity_strength=0.0,
    )

    model = SyntheticDisplayModel(spec)

    # 创建 identity LUT
    lut = LUT3D(LUT3DSpec(grid_size=33))
    lut.set_identity()

    return (lut, model)


def create_gamma_deviation_fixture(
    gamma_deviation: float = 0.2,
) -> Tuple[LUT3D, SyntheticDisplayModel]:
    """
    创建 Gamma 偏差 display fixture

    Args:
        gamma_deviation: Gamma 偏差值（正值为偏亮，负值为偏暗）

    Returns:
        Tuple[LUT3D, SyntheticDisplayModel]: (校正 LUT, display model)
    """
    spec = SyntheticDisplaySpec(
        name=f"Gamma Deviation {gamma_deviation:+.1f}",
        gamma=2.4,
        gamma_deviation=gamma_deviation,
        gamut_matrix=None,
        nonlinearity_strength=0.0,
    )

    model = SyntheticDisplayModel(spec)
    lut = model.create_correction_lut(grid_size=33)

    return (lut, model)


def create_gamut_deviation_fixture(
    deviation_type: str = "saturation_shift",
) -> Tuple[LUT3D, SyntheticDisplayModel]:
    """
    创建 Gamut matrix 偏差 display fixture

    Args:
        deviation_type: 偏差类型
            - "saturation_shift": 色度偏差
            - "hue_shift": 色调偏差
            - "primary_shift": primaries 偏差

    Returns:
        Tuple[LUT3D, SyntheticDisplayModel]: (校正 LUT, display model)
    """
    # 定义偏差矩阵
    if deviation_type == "saturation_shift":
        # 色度增加约 10%
        gamut_matrix = [
            [1.10, -0.05, -0.05],
            [-0.05, 1.10, -0.05],
            [-0.05, -0.05, 1.10],
        ]
    elif deviation_type == "hue_shift":
        # 轻微色调偏移
        gamut_matrix = [
            [1.0, 0.05, -0.05],
            [-0.05, 1.0, 0.05],
            [0.05, -0.05, 1.0],
        ]
    elif deviation_type == "primary_shift":
        # primaries 偏移（模拟色域偏差）
        gamut_matrix = [
            [0.95, 0.03, 0.02],
            [0.02, 0.95, 0.03],
            [0.03, 0.02, 0.95],
        ]
    else:
        gamut_matrix = None

    spec = SyntheticDisplaySpec(
        name=f"Gamut {deviation_type}",
        gamma=2.4,
        gamma_deviation=0.0,
        gamut_matrix=gamut_matrix,
        nonlinearity_strength=0.0,
    )

    model = SyntheticDisplayModel(spec)
    lut = model.create_correction_lut(grid_size=33)

    return (lut, model)


def create_nonlinearity_fixture(
    strength: float = 0.1,
) -> Tuple[LUT3D, SyntheticDisplayModel]:
    """
    创建非线性偏差 display fixture

    Args:
        strength: 非线性强度 (0-1)

    Returns:
        Tuple[LUT3D, SyntheticDisplayModel]: (校正 LUT, display model)
    """
    spec = SyntheticDisplaySpec(
        name=f"Nonlinearity {strength:.1f}",
        gamma=2.4,
        gamma_deviation=0.0,
        gamut_matrix=None,
        nonlinearity_strength=strength,
    )

    model = SyntheticDisplayModel(spec)
    lut = model.create_correction_lut(grid_size=33)

    return (lut, model)


# ==============================================================================
# 性能测试
# ==============================================================================

def benchmark_lut_performance(
    lut: LUT3D,
    num_samples: int = 10000,
) -> Dict[str, float]:
    """
    LUT 性能基准测试

    Args:
        lut: 待测试的 LUT
        num_samples: 测试样本数

    Returns:
        Dict[str, float]: 性能统计
            - trilinear_time_ms: trilinear 插值耗时
            - tetrahedral_time_ms: tetrahedral 插值耗时
            - trilinear_per_sample_us: 单样本耗时（微秒）
            - tetrahedral_per_sample_us: 单样本耗时
            - samples_per_second: 每秒处理样本数
    """
    import time

    # 生成随机测试样本
    np.random.seed(42)
    test_rgb = np.random.rand(num_samples, 3).astype(np.float32)

    # Trilinear 测试
    start = time.time()
    for i in range(num_samples):
        lut.apply_to_rgb(test_rgb[i, 0], test_rgb[i, 1], test_rgb[i, 2], "trilinear")
    trilinear_time = time.time() - start

    # Tetrahedral 测试
    start = time.time()
    for i in range(num_samples):
        lut.apply_to_rgb(test_rgb[i, 0], test_rgb[i, 1], test_rgb[i, 2], "tetrahedral")
    tetrahedral_time = time.time() - start

    return {
        "trilinear_time_ms": trilinear_time * 1000,
        "tetrahedral_time_ms": tetrahedral_time * 1000,
        "trilinear_per_sample_us": trilinear_time * 1000000 / num_samples,
        "tetrahedral_per_sample_us": tetrahedral_time * 1000000 / num_samples,
        "trilinear_samples_per_second": num_samples / trilinear_time,
        "tetrahedral_samples_per_second": num_samples / tetrahedral_time,
        "num_samples": num_samples,
        "grid_size": lut.grid_size,
    }
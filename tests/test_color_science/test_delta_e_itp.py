"""
ΔE ITP (ITU-R BT.2124) 测试 (P3 集成)

验证 HDR 色差计算：
    - 规范 Annex 4 算例锚点（XYZ [36,15,190] → ITP [0.3568, 0.1321, -0.1629]）
    - 恒等性 / 对称性 / 分量分解
    - 亮度/色度分量的物理意义
    - delta_e_from_xyY 的 "itp" 方法集成
"""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.color_science import (
    delta_e_itp,
    delta_e_itp_components,
    delta_e_itp_from_xyY,
    xyz_to_itp,
)
from src.color_science.colorimetry import delta_e_from_xyY


D65_WHITE_XYZ = (95.047, 100.0, 108.883)

# BT.2124 Annex 4 算例
SPEC_MEASURED_XYZ = (36.0, 15.0, 190.0)
SPEC_MEASURED_ITP = (0.3568, 0.1321, -0.1629)
SPEC_REFERENCE_ITP = (0.3554, 0.1346, -0.1613)  # 58% PQ BT.709 蓝
SPEC_DELTA_E = 2.363


class TestSpecAnchor:
    """BT.2124 Annex 4 规范算例（权威锚点）"""

    def test_xyz_to_itp_matches_spec(self):
        I, T, P = xyz_to_itp(*SPEC_MEASURED_XYZ)
        assert I == pytest.approx(SPEC_MEASURED_ITP[0], abs=5e-5)
        assert T == pytest.approx(SPEC_MEASURED_ITP[1], abs=5e-5)
        assert P == pytest.approx(SPEC_MEASURED_ITP[2], abs=5e-5)

    def test_delta_e_matches_spec(self):
        """ΔE 与规范算例一致（容差吸收规范示例的 4 位小数舍入）"""
        I, T, P = xyz_to_itp(*SPEC_MEASURED_XYZ)
        de = 720.0 * math.sqrt(
            (I - SPEC_REFERENCE_ITP[0]) ** 2
            + (T - SPEC_REFERENCE_ITP[1]) ** 2
            + (P - SPEC_REFERENCE_ITP[2]) ** 2
        )
        assert de == pytest.approx(SPEC_DELTA_E, abs=0.05)


class TestXyzToItp:
    """XYZ → ITP 变换"""

    def test_black_is_origin(self):
        I, T, P = xyz_to_itp(0.0, 0.0, 0.0)
        assert I == 0.0
        assert T == 0.0
        assert P == 0.0

    def test_d65_white_neutral_chromaticity(self):
        """D65 白在 ITP 中色度坐标应接近零（残差源于 ASTM 白点与 BT.2020 精确白点的微小差异）"""
        I, T, P = xyz_to_itp(*D65_WHITE_XYZ)
        assert abs(T) < 1e-4
        assert abs(P) < 1e-4

    def test_monotonic_luminance(self):
        """亮度单调递增 → I 单调递增"""
        prev = -1.0
        for Y in [1.0, 10.0, 100.0, 1000.0, 10000.0]:
            scale = Y / 100.0
            I, _, _ = xyz_to_itp(95.047 * scale, Y, 108.883 * scale)
            assert I > prev
            prev = I


class TestDeltaEITP:
    """ΔE ITP 基本性质"""

    def test_identity(self):
        assert delta_e_itp(D65_WHITE_XYZ, D65_WHITE_XYZ) == 0.0

    def test_symmetry(self):
        xyz2 = (95.5, 100.5, 108.0)
        d1 = delta_e_itp(D65_WHITE_XYZ, xyz2)
        d2 = delta_e_itp(xyz2, D65_WHITE_XYZ)
        assert d1 == pytest.approx(d2)

    def test_components_pythagorean(self):
        """总 ITP 应满足 sqrt(I² + CT²)"""
        xyz2 = (90.0, 105.0, 100.0)
        total = delta_e_itp(D65_WHITE_XYZ, xyz2)
        comp = delta_e_itp_components(D65_WHITE_XYZ, xyz2)
        assert total == pytest.approx(comp["itp"])
        assert total == pytest.approx(math.hypot(comp["i"], comp["ct"]), rel=1e-6)

    def test_pure_luminance_difference_dominates_i(self):
        """纯亮度差 → 亮度分量占主导"""
        comp = delta_e_itp_components(
            (95.047, 100.0, 108.883),
            (95.047 * 1.1, 110.0, 108.883 * 1.1),
        )
        assert comp["i"] > comp["ct"]

    def test_pure_chromaticity_difference_dominates_ct(self):
        """同亮度不同色温 → 色度分量占主导"""
        d65 = (95.047, 100.0, 108.883)
        d60 = (96.07, 100.0, 81.45)  # 近似 D60 归一化到 Y=100
        comp = delta_e_itp_components(d65, d60)
        assert comp["ct"] > comp["i"]

    def test_sdr_imperceptible(self):
        """0.5 nit 亮度差在 100 nit 处应远小于 1 ΔE ITP（1 JND）"""
        comp = delta_e_itp_components(
            (95.047, 100.0, 108.883),
            (95.047 * 1.005, 100.5, 108.883 * 1.005),
        )
        assert comp["itp"] < 1.0


class TestDeltaEITPFromXyY:
    """xyY 便捷接口"""

    def test_identity(self):
        r = delta_e_itp_from_xyY((0.3127, 0.3290, 100.0), (0.3127, 0.3290, 100.0))
        assert r["itp"] == 0.0

    def test_hdr_scale(self):
        """HDR 高亮区的色差可被量化"""
        r = delta_e_itp_from_xyY(
            (0.3127, 0.3290, 1000.0), (0.3127, 0.3290, 1100.0)
        )
        assert r["itp"] > 0

    def test_method_integration(self):
        """delta_e_from_xyY 支持 method='itp'"""
        d = delta_e_from_xyY(
            (0.3127, 0.3290, 100.0),
            (0.3127, 0.3290, 100.0),
            method="itp",
        )
        assert d == 0.0


class TestScalingFactor:
    """720 缩放因子与 JND 标度"""

    def test_hdr_mid_range_sensitivity(self):
        """500 nit 与 505 nit（1% 差异）应处于可察觉边缘（0.1-5）"""
        comp = delta_e_itp_components(
            (0.4124 * 500, 500, 0.4558 * 500),
            (0.4124 * 505, 505, 0.4558 * 505),
        )
        assert 0.1 < comp["itp"] < 5.0

"""
色彩空间转换测试
"""

import pytest
import json
import math
import os

# 获取测试数据目录
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "color_science")


def load_test_data(filename):
    """加载测试数据文件"""
    filepath = os.path.join(FIXTURES_DIR, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# 导入被测模块
from src.color_science.spaces import (
    srgb_to_xyz,
    xyz_to_srgb,
    xyz_to_lab,
    lab_to_xyz,
    rgb_to_lab,
    lab_to_rgb,
    xyY_to_xyz,
    xyz_to_xyY,
    get_white_point_xyz,
    WHITE_POINTS,
    ILLUMINANTS,
    COLOR_SPACES,
    srgb_linearize,
    srgb_gamma_correct,
)


class TestWhitePoints:
    """白点定义测试"""
    
    def test_d65_xyz(self):
        """D65 XYZ 值验证"""
        X, Y, Z = get_white_point_xyz("D65")
        assert abs(X - 95.047) < 0.001
        assert abs(Y - 100.0) < 0.001
        assert abs(Z - 108.883) < 0.001
    
    def test_d50_xyz(self):
        """D50 XYZ 值验证"""
        X, Y, Z = get_white_point_xyz("D50")
        assert abs(X - 96.422) < 0.001
        assert abs(Y - 100.0) < 0.001
        assert abs(Z - 82.521) < 0.001
    
    def test_white_point_xy_consistency(self):
        """白点 xy 与 XYZ 一致性验证"""
        for name, (x, y) in WHITE_POINTS.items():
            X, Y, Z = ILLUMINANTS[name]
            # 从 XYZ 计算 xy
            x_calc = X / (X + Y + Z)
            y_calc = Y / (X + Y + Z)
            assert abs(x - x_calc) < 0.001, f"{name}: x mismatch"
            assert abs(y - y_calc) < 0.001, f"{name}: y mismatch"


class TestSRGBConversion:
    """sRGB 转换测试"""
    
    @pytest.fixture
    def test_vectors(self):
        return load_test_data("srgb_xyz_test_vectors.json")
    
    def test_srgb_to_xyz_primary_colors(self, test_vectors):
        """RGB primaries 到 XYZ 转换"""
        for tv in test_vectors["test_vectors"]:
            rgb = tv["rgb"]
            expected_xyz = tv["xyz"]
            tolerance = tv["tolerance_xyz"]
            
            X, Y, Z = srgb_to_xyz(rgb[0], rgb[1], rgb[2])
            
            assert abs(X - expected_xyz[0]) < tolerance, \
                f"{tv['name']}: X mismatch (got {X}, expected {expected_xyz[0]})"
            assert abs(Y - expected_xyz[1]) < tolerance, \
                f"{tv['name']}: Y mismatch (got {Y}, expected {expected_xyz[1]})"
            assert abs(Z - expected_xyz[2]) < tolerance, \
                f"{tv['name']}: Z mismatch (got {Z}, expected {expected_xyz[2]})"
    
    def test_xyz_to_lab_primary_colors(self, test_vectors):
        """XYZ 到 Lab 转换"""
        for tv in test_vectors["test_vectors"]:
            rgb = tv["rgb"]
            expected_lab = tv["lab"]
            tolerance = tv["tolerance_lab"]
            
            X, Y, Z = srgb_to_xyz(rgb[0], rgb[1], rgb[2])
            L, a, b = xyz_to_lab(X, Y, Z)
            
            assert abs(L - expected_lab[0]) < tolerance, \
                f"{tv['name']}: L mismatch (got {L}, expected {expected_lab[0]})"
            assert abs(a - expected_lab[1]) < tolerance, \
                f"{tv['name']}: a mismatch (got {a}, expected {expected_lab[1]})"
            assert abs(b - expected_lab[2]) < tolerance, \
                f"{tv['name']}: b mismatch (got {b}, expected {expected_lab[2]})"
    
    def test_rgb_to_lab_roundtrip(self, test_vectors):
        """RGB -> Lab -> RGB roundtrip"""
        for tv in test_vectors["test_vectors"]:
            rgb_in = tv["rgb"]
            max_diff = test_vectors["roundtrip_test"]["max_rgb_diff"]
            
            # RGB -> Lab
            L, a, b = rgb_to_lab(rgb_in[0], rgb_in[1], rgb_in[2])
            
            # Lab -> RGB
            rgb_out = lab_to_rgb(L, a, b)
            
            # 检查 RGB 差异
            for i in range(3):
                diff = abs(rgb_in[i] - rgb_out[i])
                assert diff <= max_diff, \
                    f"{tv['name']}: RGB[{i}] roundtrip diff {diff} > {max_diff}"
    
    def test_white_point_roundtrip(self):
        """D65 白点 roundtrip"""
        # D65 白点的 XYZ
        X, Y, Z = get_white_point_xyz("D65")
        
        # XYZ -> Lab -> XYZ
        L, a, b = xyz_to_lab(X, Y, Z)
        X_out, Y_out, Z_out = lab_to_xyz(L, a, b)
        
        assert abs(L - 100.0) < 0.01
        assert abs(a) < 0.01
        assert abs(b) < 0.01
        assert abs(X_out - X) < 0.1
        assert abs(Y_out - Y) < 0.1
        assert abs(Z_out - Z) < 0.1


class TestSRGBGamma:
    """sRGB Gamma 曲线测试"""
    
    def test_linearize_below_threshold(self):
        """低于阈值线性化"""
        for V in [0.0, 0.01, 0.02, 0.04045]:
            L = srgb_linearize(V)
            expected = V / 12.92
            assert abs(L - expected) < 0.001
    
    def test_linearize_above_threshold(self):
        """高于阈值线性化"""
        for V in [0.05, 0.5, 1.0]:
            L = srgb_linearize(V)
            expected = ((V + 0.055) / 1.055) ** 2.4
            assert abs(L - expected) < 0.001
    
    def test_gamma_correct_below_threshold(self):
        """低于阈值 Gamma 校正"""
        for L in [0.0, 0.001, 0.0031308]:
            V = srgb_gamma_correct(L)
            expected = 12.92 * L
            assert abs(V - expected) < 0.001
    
    def test_gamma_correct_above_threshold(self):
        """高于阈值 Gamma 校正"""
        for L in [0.01, 0.5, 1.0]:
            V = srgb_gamma_correct(L)
            expected = 1.055 * (L ** (1/2.4)) - 0.055
            assert abs(V - expected) < 0.001
    
    def test_gamma_roundtrip(self):
        """Gamma roundtrip"""
        for V in [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]:
            L = srgb_linearize(V)
            V_out = srgb_gamma_correct(L)
            assert abs(V_out - V) < 0.001


class TestXYyConversion:
    """xyY 转换测试"""
    
    def test_xyY_to_xyz_d65(self):
        """D65 xyY 到 XYZ"""
        x, y = WHITE_POINTS["D65"]
        Y = 100.0
        
        X, Y_out, Z = xyY_to_xyz(x, y, Y)
        
        assert abs(X - 95.047) < 0.1
        assert abs(Y_out - 100.0) < 0.01
        assert abs(Z - 108.883) < 0.1
    
    def test_xyz_to_xyY_roundtrip(self):
        """XYZ <-> xyY roundtrip"""
        test_cases = [
            (95.047, 100.0, 108.883),  # D65
            (96.422, 100.0, 82.521),   # D50
            (50.0, 60.0, 70.0),         # 随机颜色
        ]
        
        for X, Y, Z in test_cases:
            x, y, Y_out = xyz_to_xyY(X, Y, Z)
            X_out, Y_final, Z_out = xyY_to_xyz(x, y, Y_out)
            
            assert abs(X_out - X) < 0.01
            assert abs(Y_final - Y) < 0.01
            assert abs(Z_out - Z) < 0.01


class TestColorSpaces:
    """色彩空间定义测试"""
    
    def test_srgb_primaries(self):
        """sRGB primaries 验证"""
        cs = COLOR_SPACES["sRGB"]
        
        # 红色
        assert abs(cs["red"][0] - 0.64) < 0.001
        assert abs(cs["red"][1] - 0.33) < 0.001
        
        # 绿色
        assert abs(cs["green"][0] - 0.30) < 0.001
        assert abs(cs["green"][1] - 0.60) < 0.001
        
        # 蓝色
        assert abs(cs["blue"][0] - 0.15) < 0.001
        assert abs(cs["blue"][1] - 0.06) < 0.001
        
        # 白点
        assert cs["white"] == "D65"
    
    def test_rec2020_primaries(self):
        """Rec.2020 primaries 验证"""
        cs = COLOR_SPACES["Rec2020"]
        
        assert abs(cs["red"][0] - 0.708) < 0.001
        assert abs(cs["green"][1] - 0.797) < 0.001
        assert abs(cs["blue"][1] - 0.046) < 0.001  # y 值
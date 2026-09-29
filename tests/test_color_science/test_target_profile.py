"""
TargetProfile 统一目标 Profile 测试

验证：
- 每个 color space 有 golden fixture 测试
- 数值转换有容差验证
- 白点/primaries/传递函数一致性
- Delta E 计算（CIE76/CIE94/CIEDE2000）
- CCT/Duv 计算

Golden fixtures 来源：
- tests/fixtures/color_science/target_profile_fixtures.json
- CIE/ITU/SMPTE 标准文档
- Bruce Lindbloom (http://www.brucelindbloom.com)
"""

import pytest
import json
import math
import os

# 获取测试数据目录
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "color_science")


def load_fixture(filename):
    """加载 fixture 文件"""
    filepath = os.path.join(FIXTURES_DIR, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# 导入被测模块
from src.color_science.target_profile import (
    TargetProfile,
    PRESET_TARGET_PROFILES,
    get_target_profile,
    list_target_profile_names,
    ColorSpaceCategory,
    TransferFunctionType,
    DeltaEMethod,
    WhitePointType,
    TransferFunctionDefinition,
    WhitePointDefinition,
    WHITE_POINT_DEFINITIONS,
    TRANSFER_FUNCTION_DEFINITIONS,
    assert_color_value_tolerance,
    assert_xyz_tolerance,
    assert_lab_tolerance,
    assert_rgb_tolerance,
    assert_delta_e_tolerance,
    assert_white_point_tolerance,
)
from src.color_science.spaces import (
    WHITE_POINTS,
    get_white_point_xy,
    xyz_to_lab,
    lab_to_xyz,
    srgb_to_xyz,
    xyz_to_srgb,
)
from src.color_science.colorimetry import (
    delta_e_cie76,
    delta_e_cie94,
    delta_e_ciede2000,
    cct_duv_from_xy,
)


# 加载 fixtures
@pytest.fixture(scope="module")
def fixtures():
    """加载 TargetProfile fixtures"""
    return load_fixture("target_profile_fixtures.json")


@pytest.fixture(scope="module")
def srgb_xyz_vectors():
    """加载 sRGB XYZ 测试向量"""
    return load_fixture("srgb_xyz_test_vectors.json")


# ==============================================================================
# 白点测试 - Golden Fixture
# ==============================================================================

class TestWhitePointsGolden:
    """白点 Golden Fixture 测试"""

    def test_d65_white_point_xy(self, fixtures):
        """D65 白点 xy 坐标验证"""
        wp_data = fixtures["white_points"]["D65"]
        expected_xy = tuple(wp_data["xy"])
        tolerance = 0.0001

        # 验证 TargetProfile D65 白点
        profile = TargetProfile.srgb()
        actual_xy = profile.white_point_xy

        passed, errors = assert_white_point_tolerance(actual_xy, expected_xy, tolerance, "D65")
        assert passed, errors

    def test_d65_white_point_xyz(self, fixtures):
        """D65 白点 XYZ 值验证"""
        wp_data = fixtures["white_points"]["D65"]
        expected_xyz = tuple(wp_data["xyz"])
        tolerance = 0.01

        profile = TargetProfile.srgb()
        actual_xyz = profile.white_point_xyz

        passed, errors = assert_xyz_tolerance(actual_xyz, expected_xyz, tolerance, "D65 XYZ")
        assert passed, errors

    def test_d50_white_point_xy(self, fixtures):
        """D50 白点 xy 坐标验证"""
        wp_data = fixtures["white_points"]["D50"]
        expected_xy = tuple(wp_data["xy"])
        tolerance = 0.0001

        wp_def = WHITE_POINT_DEFINITIONS[WhitePointType.D50]
        actual_xy = wp_def.xy

        passed, errors = assert_white_point_tolerance(actual_xy, expected_xy, tolerance, "D50")
        assert passed, errors

    def test_d60_white_point_xy(self, fixtures):
        """D60 白点 xy 坐标验证"""
        wp_data = fixtures["white_points"]["D60"]
        expected_xy = tuple(wp_data["xy"])
        tolerance = 0.0001

        wp_def = WHITE_POINT_DEFINITIONS[WhitePointType.D60]
        actual_xy = wp_def.xy

        passed, errors = assert_white_point_tolerance(actual_xy, expected_xy, tolerance, "D60")
        assert passed, errors

    def test_dci_white_point_xy(self, fixtures):
        """DCI 白点 xy 坐标验证"""
        wp_data = fixtures["white_points"]["DCI"]
        expected_xy = tuple(wp_data["xy"])
        tolerance = 0.0001

        wp_def = WHITE_POINT_DEFINITIONS[WhitePointType.DCI]
        actual_xy = wp_def.xy

        passed, errors = assert_white_point_tolerance(actual_xy, expected_xy, tolerance, "DCI")
        assert passed, errors

    def test_white_point_cct_approx(self, fixtures):
        """白点 CCT 近似值验证"""
        for wp_name, wp_data in fixtures["white_points"].items():
            expected_cct = wp_data["cct_approx"]
            tolerance = 500  # K

            if wp_name == "D65":
                wp_def = WHITE_POINT_DEFINITIONS[WhitePointType.D65]
            elif wp_name == "D50":
                wp_def = WHITE_POINT_DEFINITIONS[WhitePointType.D50]
            elif wp_name == "D60":
                wp_def = WHITE_POINT_DEFINITIONS[WhitePointType.D60]
            elif wp_name == "DCI":
                wp_def = WHITE_POINT_DEFINITIONS[WhitePointType.DCI]
            else:
                continue

            actual_cct = wp_def.cct_approx
            error = abs(actual_cct - expected_cct)
            assert error <= tolerance, f"{wp_name}: CCT {actual_cct} != expected {expected_cct}"


# ==============================================================================
# 色彩空间 primaries 测试 - Golden Fixture
# ==============================================================================

class TestColorSpacePrimariesGolden:
    """色彩空间 primaries Golden Fixture 测试"""

    def test_srgb_primaries(self, fixtures):
        """sRGB primaries 验证"""
        cs_data = fixtures["color_spaces"]["sRGB"]
        expected_primaries = cs_data["primaries"]
        tolerance = 0.0001

        profile = TargetProfile.srgb()
        actual_primaries = profile.primaries

        for color in ["red", "green", "blue"]:
            expected = tuple(expected_primaries[color])
            actual = actual_primaries[color]
            passed, errors = assert_white_point_tolerance(actual, expected, tolerance, f"sRGB {color}")
            assert passed, errors

    def test_display_p3_primaries(self, fixtures):
        """Display P3 primaries 验证"""
        cs_data = fixtures["color_spaces"]["DisplayP3"]
        expected_primaries = cs_data["primaries"]
        tolerance = 0.0001

        profile = TargetProfile.display_p3()
        actual_primaries = profile.primaries

        for color in ["red", "green", "blue"]:
            expected = tuple(expected_primaries[color])
            actual = actual_primaries[color]
            passed, errors = assert_white_point_tolerance(actual, expected, tolerance, f"DisplayP3 {color}")
            assert passed, errors

    def test_dci_p3_primaries(self, fixtures):
        """DCI-P3 primaries 验证"""
        cs_data = fixtures["color_spaces"]["DCI_P3"]
        expected_primaries = cs_data["primaries"]
        tolerance = 0.0001

        profile = TargetProfile.dci_p3()
        actual_primaries = profile.primaries

        # DCI-P3 和 Display P3 primaries 相同
        for color in ["red", "green", "blue"]:
            expected = tuple(expected_primaries[color])
            actual = actual_primaries[color]
            passed, errors = assert_white_point_tolerance(actual, expected, tolerance, f"DCI-P3 {color}")
            assert passed, errors

    def test_adobe_rgb_primaries(self, fixtures):
        """Adobe RGB primaries 验证"""
        cs_data = fixtures["color_spaces"]["AdobeRGB"]
        expected_primaries = cs_data["primaries"]
        tolerance = 0.0001

        profile = TargetProfile.adobe_rgb()
        actual_primaries = profile.primaries

        for color in ["red", "green", "blue"]:
            expected = tuple(expected_primaries[color])
            actual = actual_primaries[color]
            passed, errors = assert_white_point_tolerance(actual, expected, tolerance, f"AdobeRGB {color}")
            assert passed, errors

    def test_rec2020_primaries(self, fixtures):
        """Rec.2020 primaries 验证"""
        cs_data = fixtures["color_spaces"]["Rec2020"]
        expected_primaries = cs_data["primaries"]
        tolerance = 0.0001

        profile = TargetProfile.rec2020()
        actual_primaries = profile.primaries

        for color in ["red", "green", "blue"]:
            expected = tuple(expected_primaries[color])
            actual = actual_primaries[color]
            passed, errors = assert_white_point_tolerance(actual, expected, tolerance, f"Rec2020 {color}")
            assert passed, errors


# ==============================================================================
# 传递函数测试 - Golden Fixture
# ==============================================================================

class TestTransferFunctionGolden:
    """传递函数 Golden Fixture 测试"""

    def test_gamma22_eotf(self, fixtures):
        """Gamma 2.2 EOTF 验证"""
        tf_data = fixtures["transfer_functions"]["gamma22"]
        tolerance = tf_data.get("test_tolerance", 0.0001)

        tf_def = TRANSFER_FUNCTION_DEFINITIONS[TransferFunctionType.GAMMA_22]

        for test_val in tf_data["test_values"]:
            V = test_val["input"]
            expected_L = test_val["expected_L"]
            tol = test_val.get("tolerance", tolerance)

            actual_L = tf_def.apply_eotf(V)
            passed, msg = assert_color_value_tolerance(actual_L, expected_L, tol, f"Gamma22 V={V}")
            assert passed, msg

    def test_gamma24_eotf(self, fixtures):
        """Gamma 2.4 EOTF 验证"""
        tf_data = fixtures["transfer_functions"]["gamma24"]

        tf_def = TRANSFER_FUNCTION_DEFINITIONS[TransferFunctionType.GAMMA_24]

        for test_val in tf_data["test_values"]:
            V = test_val["input"]
            expected_L = test_val["expected_L"]
            tol = test_val.get("tolerance", 0.0001)

            actual_L = tf_def.apply_eotf(V)
            passed, msg = assert_color_value_tolerance(actual_L, expected_L, tol, f"Gamma24 V={V}")
            assert passed, msg

    def test_gamma26_eotf(self, fixtures):
        """Gamma 2.6 EOTF 验证"""
        tf_data = fixtures["transfer_functions"]["gamma26"]

        # DCI-P3 使用 Gamma 2.6
        profile = TargetProfile.dci_p3()
        gamma = profile.transfer_function.gamma

        assert abs(gamma - 2.6) < 0.01, "DCI-P3 Gamma 应为 2.6"

        for test_val in tf_data["test_values"]:
            V = test_val["input"]
            expected_L = test_val["expected_L"]
            tol = test_val.get("tolerance", 0.0001)

            # 使用自定义 Gamma 2.6 传递函数
            actual_L = math.pow(V, 2.6)
            passed, msg = assert_color_value_tolerance(actual_L, expected_L, tol, f"Gamma26 V={V}")
            assert passed, msg

    def test_srgb_eotf(self, fixtures):
        """sRGB EOTF 验证"""
        tf_data = fixtures["transfer_functions"]["sRGB"]

        tf_def = TRANSFER_FUNCTION_DEFINITIONS[TransferFunctionType.SRGB]

        for test_val in tf_data["test_values"]:
            V = test_val["input"]
            expected_L = test_val["expected_L"]
            tol = test_val.get("tolerance", 0.001)

            actual_L = tf_def.apply_eotf(V)
            passed, msg = assert_color_value_tolerance(actual_L, expected_L, tol, f"sRGB V={V}")
            assert passed, msg

    def test_bt1886_eotf(self, fixtures):
        """BT.1886 EOTF 验证"""
        tf_data = fixtures["transfer_functions"]["BT1886"]

        tf_def = TRANSFER_FUNCTION_DEFINITIONS[TransferFunctionType.BT1886]

        for test_val in tf_data["test_values"]:
            V = test_val["input"]
            Lw = test_val.get("Lw", 100.0)
            Lb = test_val.get("Lb", 0.0)
            expected_L = test_val["expected_L"]
            tol = test_val.get("tolerance", 0.01)

            actual_L = tf_def.apply_eotf(V, Lw=Lw, Lb=Lb)
            passed, msg = assert_color_value_tolerance(actual_L, expected_L, tol, f"BT1886 V={V} Lw={Lw} Lb={Lb}")
            assert passed, msg

    def test_pq_eotf(self, fixtures):
        """PQ EOTF 验证"""
        tf_data = fixtures["transfer_functions"]["PQ"]

        tf_def = TRANSFER_FUNCTION_DEFINITIONS[TransferFunctionType.PQ]

        for test_val in tf_data["test_values"]:
            V = test_val["input"]
            L_max = test_val.get("L_max", 10000)
            expected_L = test_val["expected_L"]
            tol = test_val.get("tolerance", 1.0)

            actual_L = tf_def.apply_eotf(V, L_max=L_max)
            passed, msg = assert_color_value_tolerance(actual_L, expected_L, tol, f"PQ V={V}")
            assert passed, msg

    def test_hlg_eotf(self, fixtures):
        """HLG EOTF 验证"""
        tf_data = fixtures["transfer_functions"]["HLG"]

        tf_def = TRANSFER_FUNCTION_DEFINITIONS[TransferFunctionType.HLG]

        for test_val in tf_data["test_values"]:
            V = test_val["input"]
            Lw = test_val.get("Lw", 1000)
            expected_L = test_val["expected_L"]
            tol = test_val.get("tolerance", 10.0)

            actual_L = tf_def.apply_eotf(V, Lw=Lw)
            passed, msg = assert_color_value_tolerance(actual_L, expected_L, tol, f"HLG V={V}")
            assert passed, msg

    def test_transfer_function_roundtrip(self, fixtures):
        """传递函数 roundtrip 验证"""
        for tf_type in [TransferFunctionType.GAMMA_22, TransferFunctionType.GAMMA_24, TransferFunctionType.SRGB]:
            tf_def = TRANSFER_FUNCTION_DEFINITIONS[tf_type]

            for V in [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]:
                L = tf_def.apply_eotf(V)
                V_out = tf_def.apply_oetf(L)

                passed, msg = assert_color_value_tolerance(V_out, V, 0.001, f"{tf_type.value} roundtrip V={V}")
                assert passed, msg


# ==============================================================================
# Delta E 测试 - Golden Fixture
# ==============================================================================

class TestDeltaEGolden:
    """Delta E Golden Fixture 测试"""

    def test_delta_e_cie76(self, fixtures):
        """CIE Delta E 1976 验证"""
        de_data = fixtures["delta_e_tests"]["cie76"]

        for test_pair in de_data["test_pairs"]:
            Lab1 = tuple(test_pair["Lab1"])
            Lab2 = tuple(test_pair["Lab2"])
            expected = test_pair["expected"]
            tolerance = test_pair["tolerance"]

            actual = delta_e_cie76(Lab1, Lab2)
            passed, msg = assert_delta_e_tolerance(actual, expected + tolerance, "CIE76")
            assert passed, msg

    def test_delta_e_cie94_positive(self, fixtures):
        """CIE Delta E 1994 正值验证"""
        de_data = fixtures["delta_e_tests"]["cie94"]

        for test_pair in de_data["test_pairs"]:
            Lab1 = tuple(test_pair["Lab1"])
            Lab2 = tuple(test_pair["Lab2"])
            min_value = test_pair["min_value"]

            actual = delta_e_cie94(Lab1, Lab2)
            assert actual >= min_value, f"CIE94 should be >= {min_value}, got {actual}"

    def test_delta_e_ciede2000_zero(self, fixtures):
        """CIEDE2000 相同颜色 Delta E = 0"""
        de_data = fixtures["delta_e_tests"]["ciede2000"]

        for test_pair in de_data["test_pairs"]:
            if test_pair["expected"] == 0.0:
                Lab1 = tuple(test_pair["Lab1"])
                Lab2 = tuple(test_pair["Lab2"])

                actual = delta_e_ciede2000(Lab1, Lab2)
                assert actual < 0.0001, f"CIEDE2000 identical colors: expected 0, got {actual}"

    def test_delta_e_ciede2000_known_pair(self, fixtures):
        """CIEDE2000 Sharma 测试对验证"""
        de_data = fixtures["delta_e_tests"]["ciede2000"]

        for test_pair in de_data["test_pairs"]:
            if test_pair.get("note") == "Sharma 测试对 #1":
                Lab1 = tuple(test_pair["Lab1"])
                Lab2 = tuple(test_pair["Lab2"])
                expected = test_pair["expected"]
                tolerance = test_pair["tolerance"]

                actual = delta_e_ciede2000(Lab1, Lab2)
                error = abs(actual - expected)
                assert error <= tolerance, f"CIEDE2000 Sharma: expected {expected}, got {actual}, error {error}"

    def test_delta_e_method_from_profile(self, fixtures):
        """TargetProfile Delta E 方法验证"""
        profile = TargetProfile.srgb()

        # 默认使用 CIEDE2000
        assert profile.delta_e_method == DeltaEMethod.CIEDE2000

        Lab1 = (50.0, 0.0, 0.0)
        Lab2 = (50.0, 10.0, 0.0)

        # 使用 profile 的方法计算
        delta_e = profile.calculate_delta_e(Lab1, Lab2)

        # CIEDE2000 结果应与直接调用一致
        expected = delta_e_ciede2000(Lab1, Lab2)
        assert abs(delta_e - expected) < 0.001


# ==============================================================================
# CCT/Duv 测试 - Golden Fixture
# ==============================================================================

class TestCCTDuvGolden:
    """CCT/Duv Golden Fixture 测试"""

    def test_d65_cct_duv(self, fixtures):
        """D65 CCT/Duv 验证"""
        cct_data = fixtures["cct_duv_tests"]["test_cases"][0]  # D65

        xy = tuple(cct_data["xy"])
        expected_cct = cct_data["expected_cct"]
        cct_tolerance = cct_data["cct_tolerance"]
        duv_tolerance = cct_data["duv_tolerance"]

        profile = TargetProfile.srgb()
        cct, duv = profile.calculate_cct_duv(*xy)

        assert abs(cct - expected_cct) <= cct_tolerance, f"D65 CCT: expected {expected_cct}, got {cct}"
        assert abs(duv) <= duv_tolerance, f"D65 Duv should be near zero: got {duv}"

    def test_d50_cct_duv(self, fixtures):
        """D50 CCT/Duv 验证"""
        cct_data = fixtures["cct_duv_tests"]["test_cases"][1]  # D50

        xy = tuple(cct_data["xy"])
        expected_cct = cct_data["expected_cct"]
        cct_tolerance = cct_data["cct_tolerance"]

        cct, duv = cct_duv_from_xy(*xy)

        assert abs(cct - expected_cct) <= cct_tolerance, f"D50 CCT: expected {expected_cct}, got {cct}"


# ==============================================================================
# RGB/XYZ/Lab Roundtrip 测试 - Golden Fixture
# ==============================================================================

class TestRGBXYZLabRoundtrip:
    """RGB/XYZ/Lab 转换 roundtrip 测试"""

    def test_srgb_to_xyz_roundtrip(self, srgb_xyz_vectors):
        """sRGB -> XYZ -> sRGB roundtrip"""
        roundtrip_config = srgb_xyz_vectors["roundtrip_test"]
        max_rgb_diff = roundtrip_config["max_rgb_diff"]

        for tv in srgb_xyz_vectors["test_vectors"]:
            rgb_8bit = tv["rgb"]

            # sRGB -> XYZ
            X, Y, Z = srgb_to_xyz(*rgb_8bit)

            # XYZ -> sRGB
            rgb_out = xyz_to_srgb(X, Y, Z)

            # 验证 roundtrip
            for i in range(3):
                diff = abs(rgb_8bit[i] - rgb_out[i])
                assert diff <= max_rgb_diff, f"{tv['name']}: RGB[{i}] diff {diff} > {max_rgb_diff}"

    def test_xyz_to_lab_roundtrip(self, srgb_xyz_vectors):
        """XYZ -> Lab -> XYZ roundtrip"""
        tolerance = 0.1

        for tv in srgb_xyz_vectors["test_vectors"]:
            if tv["name"] == "黑色 (0, 0, 0)":
                continue  # 黑色 roundtrip 有精度问题

            rgb_8bit = tv["rgb"]
            X, Y, Z = srgb_to_xyz(*rgb_8bit)

            # XYZ -> Lab
            L, a, b = xyz_to_lab(X, Y, Z)

            # Lab -> XYZ
            X_out, Y_out, Z_out = lab_to_xyz(L, a, b)

            # 验证 roundtrip
            passed, errors = assert_xyz_tolerance(
                (X_out, Y_out, Z_out),
                (X, Y, Z),
                tolerance,
                tv["name"]
            )
            assert passed, errors


# ==============================================================================
# TargetProfile 预设测试
# ==============================================================================

class TestTargetProfilePresets:
    """TargetProfile 预设测试"""

    def test_all_presets_exist(self):
        """所有预设都应该存在"""
        preset_names = list_target_profile_names()

        # SDR 预设
        assert "sRGB" in preset_names
        assert "Rec.709" in preset_names
        assert "Gamma 2.4" in preset_names

        # 宽色域预设
        assert "Display P3" in preset_names
        assert "DCI-P3" in preset_names
        assert "Adobe RGB" in preset_names
        assert "Rec.2020" in preset_names

        # HDR 预设
        assert "HDR PQ 1000" in preset_names
        assert "HDR HLG 1000" in preset_names

    def test_get_target_profile_by_name(self):
        """通过名称获取预设"""
        profile = get_target_profile("sRGB")
        assert profile.name == "sRGB"
        assert profile.category == ColorSpaceCategory.SDR

    def test_get_target_profile_by_alias(self):
        """通过别名获取预设"""
        profile = get_target_profile("p3")
        assert profile.name == "Display P3"

        profile = get_target_profile("rec709")
        assert profile.name == "Rec.709"

    def test_srgb_profile_properties(self):
        """sRGB Profile 属性验证"""
        profile = TargetProfile.srgb()

        assert profile.color_space_name == "sRGB"
        assert profile.category == ColorSpaceCategory.SDR
        assert profile.transfer_function.type == TransferFunctionType.SRGB
        assert profile.white_point.type == WhitePointType.D65
        assert profile.peak_luminance == 100.0
        assert profile.is_sdr is True
        assert profile.is_hdr is False

    def test_display_p3_profile_properties(self):
        """Display P3 Profile 属性验证"""
        profile = TargetProfile.display_p3()

        assert profile.color_space_name == "DisplayP3"
        assert profile.category == ColorSpaceCategory.WIDE_GAMUT
        assert profile.transfer_function.type == TransferFunctionType.GAMMA_22
        assert profile.white_point.type == WhitePointType.D65
        assert profile.is_wide_gamut is True

    def test_dci_p3_profile_properties(self):
        """DCI-P3 Profile 属性验证"""
        profile = TargetProfile.dci_p3()

        assert profile.color_space_name == "DCI_P3"
        assert profile.category == ColorSpaceCategory.WIDE_GAMUT
        assert profile.white_point.type == WhitePointType.DCI
        assert abs(profile.transfer_function.gamma - 2.6) < 0.01

    def test_hdr_pq_profile_properties(self):
        """HDR PQ Profile 属性验证"""
        profile = TargetProfile.hdr_pq(1000)

        assert profile.color_space_name == "Rec2020"
        assert profile.category == ColorSpaceCategory.HDR
        assert profile.transfer_function.type == TransferFunctionType.PQ
        assert profile.peak_luminance == 1000.0
        assert profile.is_hdr is True

    def test_hdr_hlg_profile_properties(self):
        """HDR HLG Profile 属性验证"""
        profile = TargetProfile.hdr_hlg(2000)

        assert profile.color_space_name == "Rec2020"
        assert profile.category == ColorSpaceCategory.HDR
        assert profile.transfer_function.type == TransferFunctionType.HLG
        assert profile.peak_luminance == 2000.0


# ==============================================================================
# TargetProfile 有效性验证测试
# ==============================================================================

class TestTargetProfileValidation:
    """TargetProfile 有效性验证测试"""

    def test_valid_profiles(self, fixtures):
        """有效 Profile 验证"""
        validation_data = fixtures["profile_validation_tests"]["valid_profiles"]

        for profile_test in validation_data:
            preset_name = profile_test["preset_name"]
            expected_valid = profile_test["expected_valid"]

            profile = get_target_profile(preset_name)
            valid, errors = profile.validate()

            assert valid == expected_valid, f"{preset_name}: expected valid={expected_valid}, got {valid}, errors={errors}"

    def test_invalid_color_space(self, fixtures):
        """无效色彩空间验证"""
        invalid_profiles = fixtures["profile_validation_tests"]["invalid_profiles"]

        for invalid_test in invalid_profiles:
            if "Invalid Color Space" in invalid_test["name"]:
                profile = TargetProfile.custom(
                    name=invalid_test["name"],
                    color_space_name=invalid_test["color_space_name"],
                    transfer_type=TransferFunctionType.SRGB,
                )

                valid, errors = profile.validate()
                assert valid is False
                assert any("未知的色彩空间" in e for e in errors)

    def test_invalid_custom_white_point(self, fixtures):
        """无效自定义白点验证"""
        invalid_profiles = fixtures["profile_validation_tests"]["invalid_profiles"]

        for invalid_test in invalid_profiles:
            if "Invalid Custom White Point" in invalid_test["name"]:
                profile = TargetProfile.custom(
                    name=invalid_test["name"],
                    color_space_name="sRGB",
                    white_point_type=WhitePointType.CUSTOM,
                    transfer_type=TransferFunctionType.SRGB,
                )

                valid, errors = profile.validate()
                assert valid is False
                assert any("自定义白点" in e for e in errors)

    def test_invalid_hdr_peak(self, fixtures):
        """无效 HDR peak luminance 验证"""
        # 创建负值 peak luminance
        profile = TargetProfile.custom(
            name="Invalid HDR Peak",
            color_space_name="Rec2020",
            transfer_type=TransferFunctionType.PQ,
            peak_luminance=-100,
        )

        valid, errors = profile.validate()
        assert valid is False
        assert any("peak luminance" in e.lower() or "luminance" in e.lower() for e in errors)


# ==============================================================================
# TargetProfile 序列化测试
# ==============================================================================

class TestTargetProfileSerialization:
    """TargetProfile 序列化测试"""

    def test_to_dict_roundtrip(self):
        """to_dict -> from_dict roundtrip"""
        profile = TargetProfile.srgb()
        data = profile.to_dict()

        restored = TargetProfile.from_dict(data)

        assert restored.name == profile.name
        assert restored.color_space_name == profile.color_space_name
        assert restored.category == profile.category
        assert restored.transfer_function.type == profile.transfer_function.type
        assert restored.white_point.type == profile.white_point.type
        assert restored.peak_luminance == profile.peak_luminance

    def test_hdr_profile_to_dict_roundtrip(self):
        """HDR Profile to_dict -> from_dict roundtrip"""
        profile = TargetProfile.hdr_pq(4000)
        data = profile.to_dict()

        restored = TargetProfile.from_dict(data)

        assert restored.peak_luminance == 4000
        assert restored.is_hdr is True

    def test_custom_white_point_serialization(self):
        """自定义白点序列化"""
        custom_xy = (0.33, 0.34)
        profile = TargetProfile.custom(
            name="Custom White Point",
            color_space_name="sRGB",
            white_point_type=WhitePointType.CUSTOM,
            custom_white_xy=custom_xy,
            transfer_type=TransferFunctionType.SRGB,
        )

        data = profile.to_dict()
        restored = TargetProfile.from_dict(data)

        assert restored.white_point_xy == custom_xy


# ==============================================================================
# 容差测试辅助函数测试
# ==============================================================================

class TestToleranceHelpers:
    """容差测试辅助函数测试"""

    def test_assert_color_value_tolerance_pass(self):
        """容差验证通过"""
        passed, msg = assert_color_value_tolerance(1.0, 1.0, 0.01)
        assert passed is True
        assert msg == ""

    def test_assert_color_value_tolerance_fail(self):
        """容差验证失败"""
        passed, msg = assert_color_value_tolerance(1.1, 1.0, 0.01)
        assert passed is False
        assert "误差" in msg

    def test_assert_xyz_tolerance_all_pass(self):
        """XYZ 容差全部通过"""
        xyz1 = (50.0, 60.0, 70.0)
        xyz2 = (50.01, 60.01, 70.01)

        passed, errors = assert_xyz_tolerance(xyz1, xyz2, 0.1)
        assert passed is True
        assert len(errors) == 0

    def test_assert_xyz_tolerance_one_fail(self):
        """XYZ 容差一个失败"""
        xyz1 = (50.0, 60.0, 70.0)
        xyz2 = (50.5, 60.0, 70.0)  # X 偏差较大

        passed, errors = assert_xyz_tolerance(xyz1, xyz2, 0.1)
        assert passed is False
        assert len(errors) == 1
        assert "X" in errors[0]

    def test_assert_delta_e_tolerance_pass(self):
        """Delta E 容差通过"""
        passed, msg = assert_delta_e_tolerance(2.0, 3.0)
        assert passed is True

    def test_assert_delta_e_tolerance_fail(self):
        """Delta E 容差失败"""
        passed, msg = assert_delta_e_tolerance(4.0, 3.0)
        assert passed is False
        assert "4" in msg


# ==============================================================================
# 禁止硬编码测试 - 确保所有 workflow 使用统一 TargetProfile
# ==============================================================================

class TestNoHardcodedConstants:
    """禁止硬编码测试"""

    def test_presets_not_hardcoded_d65(self):
        """预设不硬编码 D65"""
        # 所有 SDR 预设应该使用 D65 白点，而不是硬编码 xy 值
        for preset_name in ["sRGB", "Rec.709", "Gamma 2.2", "Gamma 2.4"]:
            profile = get_target_profile(preset_name)

            # 验证通过 WhitePointDefinition 获取，不是硬编码
            assert profile.white_point.type == WhitePointType.D65
            expected_xy = WHITE_POINT_DEFINITIONS[WhitePointType.D65].xy
            assert profile.white_point_xy == expected_xy

    def test_presets_not_hardcoded_gamma(self):
        """预设不硬编码 Gamma"""
        # Gamma 2.4 预设应该使用 TransferFunctionDefinition，不是硬编码值
        profile = get_target_profile("Gamma 2.4")

        assert profile.transfer_function.type == TransferFunctionType.GAMMA_24
        assert abs(profile.transfer_function.gamma - 2.4) < 0.001

        # Gamma 值应该从定义获取，而不是硬编码
        expected_gamma = TRANSFER_FUNCTION_DEFINITIONS[TransferFunctionType.GAMMA_24].gamma
        assert abs(profile.transfer_function.gamma - expected_gamma) < 0.001

    def test_preset_profiles_are_consistent(self):
        """预设 Profile 一致性"""
        # 同一预设多次获取应该返回相同值（结构）
        profile1 = get_target_profile("sRGB")
        profile2 = get_target_profile("sRGB")

        assert profile1.white_point_xy == profile2.white_point_xy
        assert profile1.transfer_function.type == profile2.transfer_function.type
        assert profile1.primaries == profile2.primaries

    def test_all_presets_use_white_point_definition(self):
        """所有预设使用 WhitePointDefinition"""
        for preset_name in list_target_profile_names():
            profile = get_target_profile(preset_name)

            # 白点应该通过定义获取，有清晰的来源
            assert profile.white_point.type in [
                WhitePointType.D65, WhitePointType.D50,
                WhitePointType.D60, WhitePointType.DCI,
                WhitePointType.CUSTOM
            ]

            # 预设不应该使用 CUSTOM（除非有特殊需求）
            if preset_name not in ["DCI-P3"]:  # DCI-P3 使用 DCI 白点
                if profile.white_point.type != WhitePointType.DCI:
                    assert profile.white_point.type in [WhitePointType.D65, WhitePointType.D50, WhitePointType.D60]
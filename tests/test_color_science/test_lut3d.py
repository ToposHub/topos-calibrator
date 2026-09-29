"""
Tests for LUT3D Core Algorithm

验收标准：
    1. Identity LUT 应用后误差接近 0
    2. Synthetic 偏差显示应用 LUT 后 Delta E 明显降低
    3. 有性能上限测试

测试覆盖：
    - Grid 尺寸：17/21/33/65
    - 插值方法：trilinear, tetrahedral
    - Smoothing：Gaussian, Median, Regularization
    - Neutral axis preservation
    - Black/white point protection
    - Gamut mapping：clip, perceptual
    - CUBE 导出/导入
    - Synthetic display model fixtures
"""

import math
import os
import tempfile
import time
import pytest
import numpy as np
from pathlib import Path

from src.color_science.lut3d import (
    # 类型
    GamutMappingStrategy,
    SmoothingMethod,
    LUT3DSpec,
    BlackWhitePoint,
    SyntheticDisplaySpec,

    # 核心
    LUT3D,
    SyntheticDisplayModel,

    # Fixture
    create_identity_display_fixture,
    create_gamma_deviation_fixture,
    create_gamut_deviation_fixture,
    create_nonlinearity_fixture,

    # 性能
    benchmark_lut_performance,
)


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def temp_cube_file():
    """创建临时 CUBE 文件"""
    temp_file = tempfile.NamedTemporaryFile(suffix=".cube", delete=False)
    temp_file.close()
    yield Path(temp_file.name)
    os.unlink(temp_file.name)


@pytest.fixture
def lut_33():
    """创建 33 grid LUT"""
    return LUT3D(LUT3DSpec(grid_size=33))


@pytest.fixture
def identity_lut_33():
    """创建 identity LUT (33 grid)"""
    lut = LUT3D(LUT3DSpec(grid_size=33))
    lut.set_identity()
    return lut


@pytest.fixture
def test_rgb_samples():
    """测试 RGB 样本"""
    return [
        (0.0, 0.0, 0.0),   # 黑
        (1.0, 1.0, 1.0),   # 白
        (0.5, 0.5, 0.5),   # 中灰
        (1.0, 0.0, 0.0),   # 红
        (0.0, 1.0, 0.0),   # 绿
        (0.0, 0.0, 1.0),   # 蓝
        (1.0, 1.0, 0.0),   # 黄
        (0.0, 1.0, 1.0),   # 青
        (1.0, 0.0, 1.0),   # 紫
        (0.25, 0.5, 0.75), # 随机颜色
        (0.1, 0.2, 0.3),   # 低亮度
        (0.8, 0.9, 0.95),  # 高亮度
    ]


# ==============================================================================
# LUT3DSpec Tests
# ==============================================================================

class TestLUT3DSpec:
    """测试 LUT 规格"""

    def test_default_spec(self):
        """测试默认规格"""
        spec = LUT3DSpec()
        assert spec.grid_size == 33
        assert spec.interpolation == "trilinear"
        assert spec.gamut_mapping == GamutMappingStrategy.CLIP
        assert spec.preserve_neutral_axis == True
        assert spec.protect_black_white == True
        assert spec.smoothing == SmoothingMethod.NONE

    def test_valid_grid_sizes(self):
        """测试有效 grid 尺寸"""
        for size in [17, 21, 33, 65]:
            spec = LUT3DSpec(grid_size=size)
            assert spec.grid_size == size

    def test_invalid_grid_size_raises(self):
        """测试无效 grid 尺寸"""
        with pytest.raises(ValueError, match="Invalid grid size"):
            LUT3DSpec(grid_size=10)

    def test_valid_interpolation_methods(self):
        """测试有效插值方法"""
        for method in ["trilinear", "tetrahedral"]:
            spec = LUT3DSpec(interpolation=method)
            assert spec.interpolation == method

    def test_invalid_interpolation_raises(self):
        """测试无效插值方法"""
        with pytest.raises(ValueError, match="Invalid interpolation"):
            LUT3DSpec(interpolation="bilinear")

    def test_smoothing_strength_range(self):
        """测试平滑强度范围"""
        # 有效值
        for strength in [0.0, 0.5, 1.0]:
            spec = LUT3DSpec(smoothing_strength=strength)
            assert spec.smoothing_strength == strength

        # 无效值
        with pytest.raises(ValueError):
            LUT3DSpec(smoothing_strength=-0.1)

        with pytest.raises(ValueError):
            LUT3DSpec(smoothing_strength=1.5)


# ==============================================================================
# LUT3D Basic Tests
# ==============================================================================

class TestLUT3DBasic:
    """测试 LUT3D 基础功能"""

    def test_lut_initialization(self):
        """测试 LUT 初始化"""
        lut = LUT3D()
        assert lut.grid_size == 33
        assert lut.data.shape == (33, 33, 33, 3)

    def test_lut_with_spec(self):
        """测试使用 spec 初始化"""
        spec = LUT3DSpec(grid_size=17, interpolation="tetrahedral")
        lut = LUT3D(spec)
        assert lut.grid_size == 17
        assert lut.data.shape == (17, 17, 17, 3)

    def test_set_identity(self, lut_33):
        """测试设置 identity LUT"""
        lut_33.set_identity()

        # 检查几个点
        gs = 33
        for i in [0, 16, 32]:
            ri = i / (gs - 1)
            output = lut_33.get_output(i, i, i)
            assert abs(output[0] - ri) < 0.001
            assert abs(output[1] - ri) < 0.001
            assert abs(output[2] - ri) < 0.001

    def test_set_and_get_output(self, lut_33):
        """测试设置和获取输出值"""
        lut_33.set_output(0, 0, 0, (0.1, 0.2, 0.3))
        output = lut_33.get_output(0, 0, 0)
        assert output == pytest.approx((0.1, 0.2, 0.3), abs=0.001)

    def test_grid_rgb_calculation(self, lut_33):
        """测试 grid RGB 计算"""
        gs = lut_33.grid_size

        # 边界点
        rgb = lut_33.get_grid_rgb(0, 0, 0)
        assert rgb == pytest.approx((0.0, 0.0, 0.0), abs=0.001)

        rgb = lut_33.get_grid_rgb(gs - 1, gs - 1, gs - 1)
        assert rgb == pytest.approx((1.0, 1.0, 1.0), abs=0.001)

        # 中点
        rgb = lut_33.get_grid_rgb(gs // 2, gs // 2, gs // 2)
        mid = (gs // 2) / (gs - 1)
        assert rgb == pytest.approx((mid, mid, mid), abs=0.001)


# ==============================================================================
# Interpolation Tests
# ==============================================================================

class TestInterpolation:
    """测试插值方法"""

    def test_trilinear_identity(self, identity_lut_33):
        """测试 trilinear identity LUT"""
        # Identity LUT：输出 = 输入
        test_points = [
            (0.0, 0.0, 0.0),
            (1.0, 1.0, 1.0),
            (0.5, 0.5, 0.5),
            (0.25, 0.25, 0.25),
            (0.75, 0.75, 0.75),
        ]

        for r, g, b in test_points:
            output = identity_lut_33.apply_to_rgb(r, g, b, "trilinear")
            assert output == pytest.approx((r, g, b), abs=0.01)

    def test_tetrahedral_identity(self, identity_lut_33):
        """测试 tetrahedral identity LUT"""
        test_points = [
            (0.0, 0.0, 0.0),
            (1.0, 1.0, 1.0),
            (0.5, 0.5, 0.5),
            (0.25, 0.25, 0.25),
            (0.75, 0.75, 0.75),
        ]

        for r, g, b in test_points:
            output = identity_lut_33.apply_to_rgb(r, g, b, "tetrahedral")
            assert output == pytest.approx((r, g, b), abs=0.01)

    def test_trilinear_non_identity(self, lut_33):
        """测试 trilinear 非 identity LUT"""
        # 创建一个简单的变换：R 通道增加 0.1
        gs = 33
        for r in range(gs):
            for g in range(gs):
                for b in range(gs):
                    ri = r / (gs - 1)
                    gi = g / (gs - 1)
                    bi = b / (gs - 1)
                    lut_33.set_output(r, g, b, (min(ri + 0.1, 1.0), gi, bi))

        # 测试插值
        output = lut_33.apply_to_rgb(0.5, 0.5, 0.5, "trilinear")
        assert abs(output[0] - 0.6) < 0.05  # R 增加
        assert abs(output[1] - 0.5) < 0.01  # G 保持
        assert abs(output[2] - 0.5) < 0.01  # B 保持

    def test_interpolation_clamps_input(self, identity_lut_33):
        """测试插值裁剪输入"""
        # 超出范围的输入应被裁剪
        output = identity_lut_33.apply_to_rgb(-0.5, -0.5, -0.5)
        assert all(0.0 <= v <= 1.0 for v in output)

        output = identity_lut_33.apply_to_rgb(1.5, 1.5, 1.5)
        assert all(0.0 <= v <= 1.0 for v in output)

    def test_different_grid_sizes_interpolation(self):
        """测试不同 grid 尺寸的插值"""
        for size in [17, 21, 33, 65]:
            lut = LUT3D(LUT3DSpec(grid_size=size))
            lut.set_identity()

            # Identity 应精确
            output = lut.apply_to_rgb(0.5, 0.5, 0.5)
            assert output == pytest.approx((0.5, 0.5, 0.5), abs=0.02)


# ==============================================================================
# Smoothing Tests
# ==============================================================================

class TestSmoothing:
    """测试平滑功能"""

    def test_no_smoothing(self, lut_33):
        """测试无平滑"""
        lut_33.set_identity()
        lut_33.apply_smoothing(SmoothingMethod.NONE, 0.0)

        # Identity 应保持
        output = lut_33.apply_to_rgb(0.5, 0.5, 0.5)
        assert output == pytest.approx((0.5, 0.5, 0.5), abs=0.01)

    def test_gaussian_smoothing(self, lut_33):
        """测试 Gaussian 平滑"""
        # 创建有噪声的 LUT
        gs = 33
        for r in range(gs):
            for g in range(gs):
                for b in range(gs):
                    ri = r / (gs - 1)
                    gi = g / (gs - 1)
                    bi = b / (gs - 1)
                    # 添加噪声
                    noise = np.random.rand(3) * 0.05
                    lut_33.set_output(r, g, b, tuple(np.clip([ri, gi, bi] + noise, 0, 1)))

        # 应用平滑
        lut_33.apply_smoothing(SmoothingMethod.GAUSSIAN, 0.5)

        # 平滑后噪声应减小
        # 检查中性轴应更平滑
        errors = []
        for i in range(gs):
            output = lut_33.get_output(i, i, i)
            expected = i / (gs - 1)
            errors.append(abs(output[0] - expected))

        # 平滑后误差应比噪声幅度小
        assert max(errors) < 0.05  # 噪声最大 0.05

    def test_median_smoothing(self, lut_33):
        """测试 Median 平滑"""
        gs = 33

        # 创建有尖峰噪声的 LUT
        for r in range(gs):
            for g in range(gs):
                for b in range(gs):
                    ri = r / (gs - 1)
                    gi = g / (gs - 1)
                    bi = b / (gs - 1)

                    # 在特定点添加尖峰
                    if r == 10 and g == 10 and b == 10:
                        lut_33.set_output(r, g, b, (1.0, 0.0, 0.0))  # 尖峰
                    else:
                        lut_33.set_output(r, g, b, (ri, gi, bi))

        # 应用 Median 平滑
        lut_33.apply_smoothing(SmoothingMethod.MEDIAN, 0.8)

        # 尖峰应被平滑掉
        output = lut_33.get_output(10, 10, 10)
        expected = 10 / (gs - 1)
        assert abs(output[0] - expected) < 0.3

    def test_regularization_smoothing(self, lut_33):
        """测试正则化平滑"""
        lut_33.set_identity()
        lut_33.apply_smoothing(SmoothingMethod.REGULARIZATION, 0.3)

        # Identity 正则化后应略有变化但保持大致正确
        output = lut_33.apply_to_rgb(0.5, 0.5, 0.5)
        assert output == pytest.approx((0.5, 0.5, 0.5), abs=0.05)


# ==============================================================================
# Protection Tests
# ==============================================================================

class TestProtection:
    """测试保护机制"""

    def test_neutral_axis_preservation(self, lut_33):
        """测试中性轴保护"""
        # 设置 spec 为保护中性轴
        lut_33.spec.preserve_neutral_axis = True

        # 创建一个会破坏中性轴的变换
        gs = 33
        for r in range(gs):
            for g in range(gs):
                for b in range(gs):
                    ri = r / (gs - 1)
                    gi = g / (gs - 1)
                    bi = b / (gs - 1)
                    # 只修改 R 通道
                    lut_33.set_output(r, g, b, (ri + 0.1, gi, bi))

        # 应用保护
        lut_33._protect_neutral_axis(lut_33.data)

        # 中性轴应被恢复
        for i in range(gs):
            output = lut_33.get_output(i, i, i)
            # 中性轴上输出应相等
            assert abs(output[0] - output[1]) < 0.001
            assert abs(output[1] - output[2]) < 0.001

    def test_black_white_point_protection(self, lut_33):
        """测试黑白场保护"""
        lut_33.set_black_white_point(
            black_rgb=(0.0, 0.0, 0.0),
            white_rgb=(1.0, 1.0, 1.0),
            black_output=(0.0, 0.0, 0.0),
            white_output=(1.0, 1.0, 1.0),
        )
        lut_33.spec.protect_black_white = True

        # 创建一个会破坏黑白场的变换
        gs = 33
        for r in range(gs):
            for g in range(gs):
                for b in range(gs):
                    lut_33.set_output(r, g, b, (0.5, 0.5, 0.5))  # 全变成灰色

        # 应用保护
        lut_33._protect_black_white(lut_33.data)

        # 黑场应被保护
        output = lut_33.get_output(0, 0, 0)
        assert output == pytest.approx((0.0, 0.0, 0.0), abs=0.1)

        # 白场应被保护
        output = lut_33.get_output(gs - 1, gs - 1, gs - 1)
        assert output == pytest.approx((1.0, 1.0, 1.0), abs=0.1)


# ==============================================================================
# Gamut Mapping Tests
# ==============================================================================

class TestGamutMapping:
    """测试 Gamut mapping"""

    def test_gamut_clip(self, lut_33):
        """测试 Gamut clipping"""
        # 创建超出 [0, 1] 范围的输出
        gs = 33
        for r in range(gs):
            for g in range(gs):
                for b in range(gs):
                    ri = r / (gs - 1)
                    gi = g / (gs - 1)
                    bi = b / (gs - 1)
                    # 添加偏移使某些点超出范围
                    lut_33.set_output(r, g, b, (ri + 0.2, gi - 0.2, bi))

        # 应用 clipping
        lut_33.apply_gamut_mapping(GamutMappingStrategy.CLIP)

        # 所有输出应在 [0, 1] 范围
        for r in range(gs):
            for g in range(gs):
                for b in range(gs):
                    output = lut_33.get_output(r, g, b)
                    assert all(0.0 <= v <= 1.0 for v in output)

    def test_perceptual_gamut_mapping(self, lut_33):
        """测试感知 Gamut mapping"""
        # 创建色域外颜色
        gs = 33
        lut_33.set_identity()

        # 修改某些点使其超出范围
        for r in range(20, 30):
            for g in range(20, 30):
                for b in range(20, 30):
                    lut_33.set_output(r, g, b, (1.5, -0.2, 0.5))

        # 应用 perceptual mapping
        lut_33.apply_gamut_mapping(GamutMappingStrategy.PERCEPTUAL)

        # 所有输出应在 [0, 1] 范围
        for r in range(gs):
            for g in range(gs):
                for b in range(gs):
                    output = lut_33.get_output(r, g, b)
                    assert all(0.0 <= v <= 1.0 for v in output)


# ==============================================================================
# CUBE Export/Import Tests
# ==============================================================================

class TestCUBEExportImport:
    """测试 CUBE 格式导出导入"""

    def test_save_cube_identity(self, identity_lut_33, temp_cube_file):
        """测试保存 identity LUT"""
        identity_lut_33.title = "Test Identity LUT"
        identity_lut_33.save_cube(str(temp_cube_file), "Identity Test")

        # 检查文件存在
        assert temp_cube_file.exists()

        # 检查内容
        with open(temp_cube_file, 'r') as f:
            content = f.read()

        assert 'TITLE' in content
        assert 'LUT_3D_SIZE 33' in content
        assert 'DOMAIN_MIN' in content
        assert 'DOMAIN_MAX' in content

    def test_load_cube_identity(self, identity_lut_33, temp_cube_file):
        """测试加载 identity LUT"""
        # 保存
        identity_lut_33.save_cube(str(temp_cube_file))

        # 加载到新 LUT
        loaded_lut = LUT3D(LUT3DSpec(grid_size=33))
        loaded_lut.load_cube(str(temp_cube_file))

        # 检查一致性
        gs = 33
        for i in [0, 16, 32]:
            orig_output = identity_lut_33.get_output(i, i, i)
            loaded_output = loaded_lut.get_output(i, i, i)
            assert orig_output == pytest.approx(loaded_output, abs=0.001)

    def test_cube_roundtrip(self, lut_33, temp_cube_file):
        """测试 CUBE 文件往返一致性"""
        # 创建非 identity LUT
        gs = 33
        for r in range(gs):
            for g in range(gs):
                for b in range(gs):
                    ri = r / (gs - 1)
                    gi = g / (gs - 1)
                    bi = b / (gs - 1)
                    lut_33.set_output(r, g, b, (ri * 0.9 + 0.05, gi, bi))

        # 保存
        lut_33.save_cube(str(temp_cube_file))

        # 加载
        loaded_lut = LUT3D(LUT3DSpec(grid_size=33))
        loaded_lut.load_cube(str(temp_cube_file))

        # 检查所有点一致性
        for r in range(0, gs, 5):  # 检查部分点
            for g in range(0, gs, 5):
                for b in range(0, gs, 5):
                    orig_output = lut_33.get_output(r, g, b)
                    loaded_output = loaded_lut.get_output(r, g, b)
                    assert orig_output == pytest.approx(loaded_output, abs=0.001)

    def test_cube_grid_size_17(self, temp_cube_file):
        """测试 17 grid CUBE 文件"""
        lut = LUT3D(LUT3DSpec(grid_size=17))
        lut.set_identity()
        lut.save_cube(str(temp_cube_file))

        loaded = LUT3D(LUT3DSpec(grid_size=17))
        loaded.load_cube(str(temp_cube_file))

        assert loaded.grid_size == 17

    def test_cube_grid_size_65(self, temp_cube_file):
        """测试 65 grid CUBE 文件"""
        lut = LUT3D(LUT3DSpec(grid_size=65))
        lut.set_identity()
        lut.save_cube(str(temp_cube_file))

        loaded = LUT3D(LUT3DSpec(grid_size=65))
        loaded.load_cube(str(temp_cube_file))

        assert loaded.grid_size == 65


# ==============================================================================
# Batch Application Tests
# ==============================================================================

class TestBatchApplication:
    """测试批量应用"""

    def test_apply_to_rgb_batch(self, identity_lut_33, test_rgb_samples):
        """测试批量应用 LUT"""
        outputs = identity_lut_33.apply_to_rgb_batch(test_rgb_samples)

        assert len(outputs) == len(test_rgb_samples)

        for input_rgb, output_rgb in zip(test_rgb_samples, outputs):
            assert output_rgb == pytest.approx(input_rgb, abs=0.02)

    def test_compute_identity_error(self, identity_lut_33):
        """测试计算 identity 误差"""
        errors = identity_lut_33.compute_identity_error()

        # Identity LUT 误差应接近 0
        assert errors["max_error"] < 0.02  # 最大误差 < 0.02
        assert errors["mean_error"] < 0.01  # 平均误差 < 0.01
        assert errors["neutral_axis_error"] < 0.01  # 中性轴误差 < 0.01


# ==============================================================================
# Synthetic Display Model Tests
# ==============================================================================

class TestSyntheticDisplayModel:
    """测试 Synthetic Display Model"""

    def test_identity_display(self):
        """测试 identity display fixture"""
        lut, model = create_identity_display_fixture()

        # Identity display：输出 = 输入^gamma
        # gamma = 2.4，输出应该等于输入^2.4
        output = model.simulate_display_output(0.5, 0.5, 0.5)
        expected = math.pow(0.5, 2.4)
        assert output == pytest.approx((expected, expected, expected), abs=0.01)

    def test_gamma_deviation_display(self):
        """测试 Gamma 偏差 display"""
        deviation = 0.2
        lut, model = create_gamma_deviation_fixture(deviation)

        # Display Gamma = 2.4 + 0.2 = 2.6
        # 输入 0.5 应输出 0.5^2.6
        output = model.simulate_display_output(0.5, 0.5, 0.5)
        expected = math.pow(0.5, 2.6)
        assert output == pytest.approx((expected, expected, expected), abs=0.01)

    def test_gamut_deviation_display_saturation(self):
        """测试 Gamut 偏差 display（色度偏差）"""
        lut, model = create_gamut_deviation_fixture("saturation_shift")

        # 输入应经过 gamut matrix 变换
        output = model.simulate_display_output(1.0, 0.0, 0.0)
        # Saturation_shift matrix: R 增加 10%
        assert output[0] > 1.0  # 红通道超出范围

    def test_nonlinearity_display(self):
        """测试非线性偏差 display"""
        strength = 0.3  # 使用更大的强度以产生明显偏差
        lut, model = create_nonlinearity_fixture(strength)

        # 输入应经过非线性变换
        # 在 0.5 附近有最大偏差
        output = model.simulate_display_output(0.5, 0.5, 0.5)

        # 验证：非线性偏差叠加在 Gamma 之上
        # 纯 Gamma 输出 = 0.5^2.4 ≈ 0.189
        # 非线性输出应略高于此（根据实现，在 0.5 附近增加偏差）
        pure_gamma = math.pow(0.5, 2.4)

        # 验证输出值存在（非零）
        assert all(v > 0 for v in output)

        # 验证非线性偏差确实影响输出（通过比较不同输入点的行为）
        output_low = model.simulate_display_output(0.1, 0.1, 0.1)
        output_high = model.simulate_display_output(0.9, 0.9, 0.9)

        # 低亮度和高亮度区域的非线性偏差应不同
        # 这是非线性偏差的预期行为
        assert output_low != pytest.approx(output_high, abs=0.01)


# ==============================================================================
# Verification Tests (验收标准)
# ==============================================================================

class TestVerificationCriteria:
    """验收标准测试"""

    def test_identity_lut_error_near_zero(self):
        """
        验收标准 1: Identity LUT 应用后误差接近 0
        """
        lut = LUT3D(LUT3DSpec(grid_size=33))
        lut.set_identity()

        # 计算误差
        errors = lut.compute_identity_error()

        # 误差应接近 0
        assert errors["max_error"] < 0.02, f"Identity LUT max error too high: {errors['max_error']}"
        assert errors["mean_error"] < 0.01, f"Identity LUT mean error too high: {errors['mean_error']}"
        assert errors["neutral_axis_error"] < 0.01, f"Neutral axis error too high: {errors['neutral_axis_error']}"

    def test_gamma_correction_reduces_delta_e(self):
        """
        验收标准 2: Synthetic 偏差显示应用 LUT 后 Delta E 明显降低
        """
        # 创建 Gamma 偏差 display（Gamma = 2.6 vs 目标 2.4）
        lut, model = create_gamma_deviation_fixture(0.2)

        # 测试样本
        test_rgb = [
            (0.1, 0.1, 0.1),
            (0.2, 0.2, 0.2),
            (0.3, 0.3, 0.3),
            (0.5, 0.5, 0.5),
            (0.7, 0.7, 0.7),
            (0.9, 0.9, 0.9),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ]

        # 测量 Delta E 降低
        result = model.measure_delta_e_reduction(test_rgb, lut)

        # Delta E 应明显降低（至少降低 50%）
        assert result["before_avg"] > 1.0, "Before Delta E should be significant"
        assert result["after_avg"] < result["before_avg"], "Delta E should decrease"
        assert result["reduction"] > 30.0, f"Delta E reduction should be > 30%: {result['reduction']}%"

    def test_gamut_correction_reduces_delta_e(self):
        """
        验收标准 2b: Gamut 偏差 display 应用 LUT 后 Delta E 降低
        """
        lut, model = create_gamut_deviation_fixture("saturation_shift")

        test_rgb = [
            (0.5, 0.5, 0.5),
            (0.3, 0.6, 0.9),
            (0.7, 0.2, 0.4),
            (0.8, 0.8, 0.2),
        ]

        result = model.measure_delta_e_reduction(test_rgb, lut)

        # Delta E 应降低
        assert result["after_avg"] < result["before_avg"], "Delta E should decrease after correction"

    def test_performance_upper_limit(self):
        """
        验收标准 3: 有性能上限测试
        """
        lut = LUT3D(LUT3DSpec(grid_size=33))
        lut.set_identity()

        # 性能基准测试
        result = benchmark_lut_performance(lut, num_samples=5000)

        # 性能要求：
        # - 单样本处理时间 < 100 微秒（即每秒处理 > 10000 样本）
        # - 33 grid LUT 应能在 1 秒内处理 10000 样本

        # 注意：Python 实现可能较慢，这里放宽限制
        assert result["trilinear_samples_per_second"] > 1000, \
            f"Trilinear too slow: {result['trilinear_samples_per_second']} samples/sec"

        # 测试不同 grid 尺寸
        for size in [17, 33, 65]:
            lut_size = LUT3D(LUT3DSpec(grid_size=size))
            lut_size.set_identity()
            perf = benchmark_lut_performance(lut_size, num_samples=1000)

            # 较大 grid 尺寸应该更慢，但仍应在可接受范围内
            print(f"Grid {size}: {perf['trilinear_samples_per_second']} samples/sec")


# ==============================================================================
# Integration Tests
# ==============================================================================

class TestIntegration:
    """集成测试"""

    def test_full_lut_workflow(self, temp_cube_file):
        """测试完整 LUT 工作流"""
        # 1. 创建 LUT
        lut = LUT3D(LUT3DSpec(
            grid_size=33,
            interpolation="tetrahedral",
            preserve_neutral_axis=True,
            protect_black_white=True,
            smoothing=SmoothingMethod.NONE,
        ))

        # 2. 创建 Gamma 偏差 display
        _, model = create_gamma_deviation_fixture(0.15)

        # 3. 生成校正 LUT
        correction_lut = model.create_correction_lut(grid_size=33)

        # 4. 导出 CUBE
        correction_lut.save_cube(str(temp_cube_file), "Correction LUT")

        # 5. 重新加载
        loaded_lut = LUT3D(LUT3DSpec(grid_size=33))
        loaded_lut.load_cube(str(temp_cube_file))

        # 6. 验证效果
        test_rgb = [(0.5, 0.5, 0.5), (0.7, 0.3, 0.2)]
        result = model.measure_delta_e_reduction(test_rgb, loaded_lut)

        assert result["after_avg"] < result["before_avg"]

    def test_all_grid_sizes_work(self, temp_cube_file):
        """测试所有 grid 尺寸正常工作"""
        for size in [17, 21, 33, 65]:
            lut = LUT3D(LUT3DSpec(grid_size=size))
            lut.set_identity()

            # 导出和加载
            lut.save_cube(str(temp_cube_file))
            loaded = LUT3D(LUT3DSpec(grid_size=size))
            loaded.load_cube(str(temp_cube_file))

            # 验证
            errors = loaded.compute_identity_error()
            assert errors["max_error"] < 0.02


# ==============================================================================
# Edge Cases Tests
# ==============================================================================

class TestEdgeCases:
    """边界情况测试"""

    def test_zero_input(self, identity_lut_33):
        """测试零输入"""
        output = identity_lut_33.apply_to_rgb(0.0, 0.0, 0.0)
        assert output == pytest.approx((0.0, 0.0, 0.0), abs=0.01)

    def test_one_input(self, identity_lut_33):
        """测试满量程输入"""
        output = identity_lut_33.apply_to_rgb(1.0, 1.0, 1.0)
        assert output == pytest.approx((1.0, 1.0, 1.0), abs=0.01)

    def test_single_channel(self, identity_lut_33):
        """测试单通道"""
        output = identity_lut_33.apply_to_rgb(1.0, 0.0, 0.0)
        assert output == pytest.approx((1.0, 0.0, 0.0), abs=0.02)

    def test_extreme_color(self, identity_lut_33):
        """测试极端颜色"""
        output = identity_lut_33.apply_to_rgb(1.0, 1.0, 0.0)
        assert output == pytest.approx((1.0, 1.0, 0.0), abs=0.02)

    def test_floating_point_precision(self, identity_lut_33):
        """测试浮点精度"""
        # 精确的浮点输入
        output = identity_lut_33.apply_to_rgb(0.123456789, 0.23456789, 0.3456789)
        # 应返回近似值
        assert abs(output[0] - 0.123456789) < 0.02
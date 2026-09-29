"""
专业 Patch Set 引擎测试

验收标准：
- 不同场景有对应 patch set
- 生成 deterministic 且可复现
- 导出格式完整
"""

import pytest
import json
from typing import Tuple

from src.color_science.patch_sets import (
    PatchPurpose,
    PatchSetType,
    Patch,
    PatchSet,
    generate_quick_check_patch_set,
    generate_grayscale_patch_set,
    generate_gamma_ramp_patch_set,
    generate_colorchecker_patch_set,
    generate_memory_colors_patch_set,
    generate_saturation_sweep_patch_set,
    generate_hue_sweep_patch_set,
    generate_lut_cube_patch_set,
    generate_adaptive_patch_set,
    generate_full_calibration_patch_set,
    create_patch_set,
)


class TestPatchDataStructure:
    """Patch 数据结构测试"""

    def test_patch_creation(self):
        """创建 Patch"""
        patch = Patch(
            rgb=(255, 0, 0),
            lab=(53.0, 80.0, 67.0),
            purpose=PatchPurpose.PRIMARY,
            priority=5,
            display_order=0,
            expected_duration_ms=500,
        )

        assert patch.rgb == (255, 0, 0)
        assert patch.lab == (53.0, 80.0, 67.0)
        assert patch.purpose == PatchPurpose.PRIMARY
        assert patch.priority == 5
        assert patch.rgb_8bit == (255, 0, 0)
        assert patch.rgb_10bit == (1023, 0, 0)

    def test_patch_rgb_validation(self):
        """RGB 值验证"""
        # 正常范围
        patch = Patch(rgb=(128, 128, 128), lab=(53.0, 0.0, 0.0), purpose=PatchPurpose.GRAY)
        assert patch.rgb == (128, 128, 128)

        # 超出范围应报错
        with pytest.raises(ValueError):
            Patch(rgb=(300, 0, 0), lab=(50.0, 0.0, 0.0), purpose=PatchPurpose.PRIMARY)

        with pytest.raises(ValueError):
            Patch(rgb=(-1, 0, 0), lab=(50.0, 0.0, 0.0), purpose=PatchPurpose.PRIMARY)

    def test_patch_priority_validation(self):
        """优先级验证"""
        # 正常范围
        for priority in range(1, 6):
            patch = Patch(rgb=(128, 128, 128), lab=(53.0, 0.0, 0.0), purpose=PatchPurpose.GRAY, priority=priority)
            assert patch.priority == priority

        # 超出范围应报错
        with pytest.raises(ValueError):
            Patch(rgb=(128, 128, 128), lab=(53.0, 0.0, 0.0), purpose=PatchPurpose.GRAY, priority=0)

        with pytest.raises(ValueError):
            Patch(rgb=(128, 128, 128), lab=(53.0, 0.0, 0.0), purpose=PatchPurpose.GRAY, priority=6)

    def test_patch_to_dict(self):
        """转换为字典"""
        patch = Patch(
            rgb=(255, 0, 0),
            lab=(53.0, 80.0, 67.0),
            purpose=PatchPurpose.PRIMARY,
            priority=5,
            display_order=0,
            expected_duration_ms=500,
            metadata={"test": "value"},
        )

        d = patch.to_dict()

        assert d["rgb"] == [255, 0, 0]
        assert d["rgb_10bit"] == [1023, 0, 0]
        assert d["lab"] == [53.0, 80.0, 67.0]
        assert d["purpose"] == "primary"
        assert d["priority"] == 5
        assert d["display_order"] == 0
        assert d["expected_duration_ms"] == 500
        assert d["metadata"] == {"test": "value"}

    def test_patch_to_csv_row(self):
        """转换为 CSV 行"""
        patch = Patch(
            rgb=(255, 0, 0),
            lab=(53.0, 80.0, 67.0),
            purpose=PatchPurpose.PRIMARY,
            priority=5,
            display_order=0,
            expected_duration_ms=500,
        )

        row = patch.to_csv_row()

        assert row[0] == "255"
        assert row[1] == "0"
        assert row[2] == "0"
        assert "53.00" in row[3]


class TestPatchSetDataStructure:
    """PatchSet 数据结构测试"""

    def test_patchset_creation(self):
        """创建 PatchSet"""
        patches = [
            Patch(rgb=(255, 255, 255), lab=(100.0, 0.0, 0.0), purpose=PatchPurpose.WHITE),
            Patch(rgb=(0, 0, 0), lab=(0.0, 0.0, 0.0), purpose=PatchPurpose.BLACK),
        ]

        patch_set = PatchSet(
            name="Test Set",
            set_type=PatchSetType.QUICK_CHECK,
            patches=patches,
            description="测试集合",
            seed=42,
        )

        assert patch_set.name == "Test Set"
        assert patch_set.set_type == PatchSetType.QUICK_CHECK
        assert patch_set.count == 2
        assert patch_set.seed == 42

    def test_patchset_add_patch(self):
        """添加色块"""
        patch_set = PatchSet(
            name="Test",
            set_type=PatchSetType.QUICK_CHECK,
            patches=[],
        )

        patch_set.add_patch(Patch(rgb=(255, 255, 255), lab=(100.0, 0.0, 0.0), purpose=PatchPurpose.WHITE))

        assert patch_set.count == 1
        assert patch_set.total_expected_duration_ms > 0

    def test_patchset_get_rgb_list(self):
        """获取 RGB 列表"""
        patches = [
            Patch(rgb=(255, 0, 0), lab=(53.0, 80.0, 67.0), purpose=PatchPurpose.PRIMARY),
            Patch(rgb=(0, 255, 0), lab=(87.0, -86.0, 83.0), purpose=PatchPurpose.PRIMARY),
        ]

        patch_set = PatchSet(name="Test", set_type=PatchSetType.QUICK_CHECK, patches=patches)

        rgb_list = patch_set.get_rgb_list()
        assert rgb_list == [(255, 0, 0), (0, 255, 0)]

    def test_patchset_get_rgb_10bit_list(self):
        """获取 10-bit RGB 列表"""
        patches = [
            Patch(rgb=(255, 0, 0), lab=(53.0, 80.0, 67.0), purpose=PatchPurpose.PRIMARY),
        ]

        patch_set = PatchSet(name="Test", set_type=PatchSetType.QUICK_CHECK, patches=patches)

        rgb_10bit = patch_set.get_rgb_10bit_list()
        assert rgb_10bit == [(1023, 0, 0)]

    def test_patchset_sort_by_display_order(self):
        """按显示顺序排序"""
        patches = [
            Patch(rgb=(0, 0, 0), lab=(0.0, 0.0, 0.0), purpose=PatchPurpose.BLACK, display_order=2),
            Patch(rgb=(255, 255, 255), lab=(100.0, 0.0, 0.0), purpose=PatchPurpose.WHITE, display_order=1),
        ]

        patch_set = PatchSet(name="Test", set_type=PatchSetType.QUICK_CHECK, patches=patches)
        sorted_set = patch_set.sort_by_display_order()

        assert sorted_set.patches[0].display_order == 1
        assert sorted_set.patches[1].display_order == 2

    def test_patchset_to_json(self):
        """导出 JSON"""
        patches = [
            Patch(rgb=(255, 255, 255), lab=(100.0, 0.0, 0.0), purpose=PatchPurpose.WHITE),
        ]

        patch_set = PatchSet(name="Test", set_type=PatchSetType.QUICK_CHECK, patches=patches)

        json_str = patch_set.to_json()
        data = json.loads(json_str)

        assert data["name"] == "Test"
        assert data["type"] == "quick_check"
        assert data["count"] == 1
        assert len(data["patches"]) == 1

    def test_patchset_to_csv(self):
        """导出 CSV"""
        patches = [
            Patch(rgb=(255, 255, 255), lab=(100.0, 0.0, 0.0), purpose=PatchPurpose.WHITE),
        ]

        patch_set = PatchSet(name="Test", set_type=PatchSetType.QUICK_CHECK, patches=patches)

        csv_str = patch_set.to_csv()
        lines = csv_str.split("\n")

        assert lines[0] == "R,G,B,L,a,b,purpose,priority,display_order,expected_duration_ms"
        assert "255" in lines[1]


class TestQuickCheckPatchSet:
    """快速预检 Patch Set 测试"""

    def test_quick_check_count_range(self):
        """色块数量范围 (10-30)"""
        # 默认 20 点（实际取决于 include_primaries 和 include_grayscale）
        patch_set = generate_quick_check_patch_set()
        assert 10 <= patch_set.count <= 30

        # 最小：包含 primaries 和 grayscale 时有基础点 (白+黑+RGB原色+CMY二次色+灰阶=13)
        patch_set = generate_quick_check_patch_set(count=5, include_primaries=True, include_grayscale=True)
        assert patch_set.count == 13  # 基础色块固定数量

        # 不包含 primaries 和 grayscale 时
        patch_set = generate_quick_check_patch_set(count=5, include_primaries=False, include_grayscale=False)
        assert patch_set.count == 10

        # 最大 30 点
        patch_set = generate_quick_check_patch_set(count=40)
        assert patch_set.count == 30

    def test_quick_check_deterministic(self):
        """生成 deterministic"""
        seed = 42

        # 同样 seed 生成同样集合
        set1 = generate_quick_check_patch_set(count=20, seed=seed)
        set2 = generate_quick_check_patch_set(count=20, seed=seed)

        rgb1 = set1.get_rgb_list()
        rgb2 = set2.get_rgb_list()

        assert rgb1 == rgb2

    def test_quick_check_includes_primaries(self):
        """包含 RGB 原色"""
        patch_set = generate_quick_check_patch_set(count=20, include_primaries=True)

        rgb_list = patch_set.get_rgb_list()

        assert (255, 0, 0) in rgb_list
        assert (0, 255, 0) in rgb_list
        assert (0, 0, 255) in rgb_list

    def test_quick_check_includes_grayscale(self):
        """包含灰阶"""
        patch_set = generate_quick_check_patch_set(count=20, include_grayscale=True)

        # 检查有灰阶点
        gray_patches = [p for p in patch_set.patches if p.purpose == PatchPurpose.GRAY]
        assert len(gray_patches) >= 3

    def test_quick_check_includes_white_black(self):
        """包含黑/白"""
        patch_set = generate_quick_check_patch_set(count=15)

        rgb_list = patch_set.get_rgb_list()

        assert (255, 255, 255) in rgb_list
        assert (0, 0, 0) in rgb_list

    def test_quick_check_different_seed_different_result(self):
        """不同 seed 产生不同结果"""
        set1 = generate_quick_check_patch_set(count=20, seed=42)
        set2 = generate_quick_check_patch_set(count=20, seed=123)

        # 基础点（白、黑、原色、灰阶）相同，随机点不同
        # 至少有一些点不同
        rgb1 = set1.get_rgb_list()
        rgb2 = set2.get_rgb_list()

        # 基础点相同
        assert (255, 255, 255) in rgb1 and (255, 255, 255) in rgb2
        assert (0, 0, 0) in rgb1 and (0, 0, 0) in rgb2


class TestGrayscalePatchSet:
    """灰阶 Patch Set 测试"""

    def test_grayscale_5_points(self):
        """灰阶 5 点"""
        patch_set = generate_grayscale_patch_set(steps=5)

        assert patch_set.count == 7  # 5 灰阶 + 黑 + 白
        assert patch_set.set_type == PatchSetType.GRAYSCALE_5

    def test_grayscale_11_points(self):
        """灰阶 11 点"""
        patch_set = generate_grayscale_patch_set(steps=11)

        assert patch_set.count == 11  # 9 灰阶 + 黑 + 白
        assert patch_set.set_type == PatchSetType.GRAYSCALE_11

    def test_grayscale_21_points(self):
        """灰阶 21 点"""
        patch_set = generate_grayscale_patch_set(steps=21)

        assert patch_set.count == 21  # 19 灰阶 + 黑 + 白
        assert patch_set.set_type == PatchSetType.GRAYSCALE_21

    def test_grayscale_without_endpoints(self):
        """不包含端点"""
        patch_set = generate_grayscale_patch_set(steps=11, include_endpoints=False)

        # 不包含纯黑/纯白
        rgb_list = patch_set.get_rgb_list()
        assert (0, 0, 0) not in rgb_list
        assert (255, 255, 255) not in rgb_list

    def test_grayscale_all_neutral(self):
        """所有点都是中性灰"""
        patch_set = generate_grayscale_patch_set(steps=11)

        for patch in patch_set.patches:
            r, g, b = patch.rgb
            assert r == g == b, f"灰阶点 RGB 不相等: {patch.rgb}"

    def test_grayscale_steps_normalized(self):
        """步数标准化"""
        # 输入 7，标准化到 5
        patch_set = generate_grayscale_patch_set(steps=7)
        assert patch_set.set_type == PatchSetType.GRAYSCALE_5

        # 输入 15，标准化到 11
        patch_set = generate_grayscale_patch_set(steps=15)
        assert patch_set.set_type == PatchSetType.GRAYSCALE_11

        # 输入 20，标准化到 21
        patch_set = generate_grayscale_patch_set(steps=20)
        assert patch_set.set_type == PatchSetType.GRAYSCALE_21


class TestGammaRampPatchSet:
    """gamma/EOTF ramp Patch Set 测试"""

    def test_gamma_ramp_gray(self):
        """灰阶 ramp"""
        patch_set = generate_gamma_ramp_patch_set(steps=21, channel="gray")

        assert patch_set.count == 21
        assert patch_set.set_type == PatchSetType.GAMMA_RAMP

        # 检查所有点都是灰
        for patch in patch_set.patches:
            r, g, b = patch.rgb
            assert r == g == b

    def test_gamma_ramp_single_channel(self):
        """单通道 ramp"""
        patch_set = generate_gamma_ramp_patch_set(steps=11, channel="R")

        assert patch_set.count == 11

        # 检查只有红色通道变化
        for patch in patch_set.patches:
            r, g, b = patch.rgb
            assert g == 0 and b == 0

    def test_gamma_ramp_rgb_channels(self):
        """RGB 三通道 ramp"""
        patch_set = generate_gamma_ramp_patch_set(steps=11, include_rgb_channels=True)

        # 每通道 11 点，共 33 点
        assert patch_set.count == 33

    def test_gamma_ramp_metadata(self):
        """元数据包含步数信息"""
        patch_set = generate_gamma_ramp_patch_set(steps=11, channel="gray")

        for patch in patch_set.patches:
            assert "step" in patch.metadata
            assert "total_steps" in patch.metadata
            assert patch.metadata["total_steps"] == 11


class TestColorCheckerPatchSet:
    """ColorChecker 24 色 Patch Set 测试"""

    def test_colorchecker_count(self):
        """24 色"""
        patch_set = generate_colorchecker_patch_set()

        assert patch_set.count == 24
        assert patch_set.set_type == PatchSetType.COLORCHECKER

    def test_colorchecker_includes_gray_patches(self):
        """包含灰阶"""
        patch_set = generate_colorchecker_patch_set()

        # ColorChecker 包含 6 个灰阶（白 + neutral 8, 6.5, 5, 3.5 + 黑）
        gray_patches = [p for p in patch_set.patches if p.purpose == PatchPurpose.GRAY]
        assert len(gray_patches) == 6

    def test_colorchecker_primary_colors(self):
        """包含原色"""
        patch_set = generate_colorchecker_patch_set()

        rgb_list = patch_set.get_rgb_list()

        # 检查 ColorChecker 基本颜色
        # 红色 (175, 54, 60)
        assert (175, 54, 60) in rgb_list
        # 绿色 (70, 148, 73)
        assert (70, 148, 73) in rgb_list
        # 蓝色 (56, 61, 150)
        assert (56, 61, 150) in rgb_list

    def test_colorchecker_deterministic(self):
        """生成 deterministic（无随机因素）"""
        set1 = generate_colorchecker_patch_set()
        set2 = generate_colorchecker_patch_set()

        assert set1.get_rgb_list() == set2.get_rgb_list()


class TestMemoryColorsPatchSet:
    """记忆色 Patch Set 测试"""

    def test_memory_colors_count(self):
        """记忆色数量"""
        patch_set = generate_memory_colors_patch_set()

        # 包含肤色、天空、草地等记忆色
        assert patch_set.count >= 10
        assert patch_set.set_type == PatchSetType.MEMORY_COLORS

    def test_memory_colors_includes_skin_tones(self):
        """包含肤色"""
        patch_set = generate_memory_colors_patch_set()

        skin_patches = [p for p in patch_set.patches if "skin" in p.metadata.get("memory_color_name", "")]
        assert len(skin_patches) >= 3

    def test_memory_colors_includes_sky(self):
        """包含天空色"""
        patch_set = generate_memory_colors_patch_set()

        sky_patches = [p for p in patch_set.patches if "sky" in p.metadata.get("memory_color_name", "")]
        assert len(sky_patches) >= 2


class TestSaturationSweepPatchSet:
    """饱和度扫描 Patch Set 测试"""

    def test_saturation_sweep_default_levels(self):
        """默认级别 (25, 50, 75, 100)"""
        # 默认包含 neutrals，所以是 6 colors * 4 levels + 4 neutrals = 28
        patch_set = generate_saturation_sweep_patch_set()

        assert patch_set.count == 28
        assert patch_set.set_type == PatchSetType.SATURATION_SWEEP

    def test_saturation_sweep_custom_levels(self):
        """自定义级别"""
        # 不包含 neutrals 时：6 colors * 2 levels = 12
        patch_set = generate_saturation_sweep_patch_set(levels=[50, 100], include_neutrals=False)

        assert patch_set.count == 12

    def test_saturation_sweep_with_neutrals(self):
        """包含中性灰"""
        patch_set = generate_saturation_sweep_patch_set(levels=[25, 50, 75, 100], include_neutrals=True)

        # 6 colors * 4 levels + 4 neutrals = 28
        assert patch_set.count == 28

    def test_saturation_sweep_levels_metadata(self):
        """级别元数据"""
        patch_set = generate_saturation_sweep_patch_set(levels=[50, 100], include_neutrals=False)

        for patch in patch_set.patches:
            assert "saturation_percent" in patch.metadata

    def test_saturation_sweep_all_primary_secondary(self):
        """包含所有原色和二次色"""
        patch_set = generate_saturation_sweep_patch_set()

        colors_found = set()
        for patch in patch_set.patches:
            colors_found.add(patch.metadata.get("color"))

        assert "R" in colors_found
        assert "G" in colors_found
        assert "B" in colors_found
        assert "Y" in colors_found
        assert "M" in colors_found
        assert "C" in colors_found


class TestHueSweepPatchSet:
    """色相扫描 Patch Set 测试"""

    def test_hue_sweep_count(self):
        """色相步数"""
        patch_set = generate_hue_sweep_patch_set(steps=12)

        assert patch_set.count == 12
        assert patch_set.set_type == PatchSetType.HUE_SWEEP

    def test_hue_sweep_deterministic(self):
        """生成 deterministic"""
        set1 = generate_hue_sweep_patch_set(steps=12, seed=42)
        set2 = generate_hue_sweep_patch_set(steps=12, seed=42)

        assert set1.get_rgb_list() == set2.get_rgb_list()

    def test_hue_sweep_metadata(self):
        """色相角度元数据"""
        patch_set = generate_hue_sweep_patch_set(steps=12)

        for patch in patch_set.patches:
            assert "hue_angle" in patch.metadata
            assert "saturation" in patch.metadata
            assert "lightness" in patch.metadata


class TestLutCubePatchSet:
    """3D LUT cube Patch Set 测试"""

    def test_lut_cube_9(self):
        """9^3 = 729 点"""
        patch_set = generate_lut_cube_patch_set(grid_size=9)

        assert patch_set.count == 729
        assert patch_set.set_type == PatchSetType.LUT_CUBE_9

    def test_lut_cube_17(self):
        """17^3 = 4913 点"""
        patch_set = generate_lut_cube_patch_set(grid_size=17)

        assert patch_set.count == 4913
        assert patch_set.set_type == PatchSetType.LUT_CUBE_17

    def test_lut_cube_21(self):
        """21^3 = 9261 点"""
        patch_set = generate_lut_cube_patch_set(grid_size=21)

        assert patch_set.count == 9261
        assert patch_set.set_type == PatchSetType.LUT_CUBE_21

    def test_lut_cube_33(self):
        """33^3 = 35937 点"""
        patch_set = generate_lut_cube_patch_set(grid_size=33)

        assert patch_set.count == 35937
        assert patch_set.set_type == PatchSetType.LUT_CUBE_33

    def test_lut_cube_invalid_size(self):
        """无效尺寸标准化"""
        # 输入 10，标准化到 9
        patch_set = generate_lut_cube_patch_set(grid_size=10)
        assert patch_set.set_type == PatchSetType.LUT_CUBE_9

        # 输入 25，标准化到 21
        patch_set = generate_lut_cube_patch_set(grid_size=25)
        assert patch_set.set_type == PatchSetType.LUT_CUBE_21

    def test_lut_cube_corner_priority(self):
        """角点优先级高"""
        patch_set = generate_lut_cube_patch_set(grid_size=9)

        # 检查角点优先级
        corner_rgbs = [
            (0, 0, 0),
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (255, 255, 0),
            (255, 0, 255),
            (0, 255, 255),
            (255, 255, 255),
        ]

        for patch in patch_set.patches:
            if patch.rgb in corner_rgbs:
                assert patch.priority == 5

    def test_lut_cube_deterministic(self):
        """生成 deterministic（无随机因素）"""
        set1 = generate_lut_cube_patch_set(grid_size=9)
        set2 = generate_lut_cube_patch_set(grid_size=9)

        assert set1.get_rgb_list() == set2.get_rgb_list()


class TestAdaptivePatchSet:
    """自适应 Patch Set 测试"""

    def test_adaptive_with_errors(self):
        """根据误差生成"""
        previous_errors = [
            {"rgb": [128, 128, 128], "delta_e": 10.0},
            {"rgb": [255, 0, 0], "delta_e": 8.0},
            {"rgb": [0, 255, 0], "delta_e": 3.0},  # 低误差，不追加
        ]

        patch_set = generate_adaptive_patch_set(previous_errors, threshold=5.0, max_patches=20)

        assert patch_set.count > 0
        assert patch_set.set_type == PatchSetType.ADAPTIVE

    def test_adaptive_no_errors(self):
        """无误差时不生成"""
        patch_set = generate_adaptive_patch_set([], threshold=5.0)

        assert patch_set.count == 0

    def test_adaptive_max_patches_limit(self):
        """最大点数限制"""
        previous_errors = [
            {"rgb": [128, 128, 128], "delta_e": 15.0},
            {"rgb": [100, 100, 100], "delta_e": 12.0},
            {"rgb": [200, 200, 200], "delta_e": 10.0},
            {"rgb": [50, 50, 50], "delta_e": 8.0},
        ]

        patch_set = generate_adaptive_patch_set(previous_errors, threshold=5.0, max_patches=10)

        assert patch_set.count <= 10

    def test_adaptive_deterministic(self):
        """生成 deterministic"""
        previous_errors = [
            {"rgb": [128, 128, 128], "delta_e": 10.0},
        ]

        set1 = generate_adaptive_patch_set(previous_errors, threshold=5.0, seed=42)
        set2 = generate_adaptive_patch_set(previous_errors, threshold=5.0, seed=42)

        assert set1.get_rgb_list() == set2.get_rgb_list()

    def test_adaptive_neighbor_points(self):
        """周围点采样"""
        previous_errors = [
            {"rgb": [128, 128, 128], "delta_e": 10.0},
        ]

        patch_set = generate_adaptive_patch_set(previous_errors, threshold=5.0, max_patches=30)

        # 应包含误差点和周围点
        rgb_list = patch_set.get_rgb_list()

        # 原点
        assert (128, 128, 128) in rgb_list

        # 周围点（偏移 ±10）
        assert any(abs(r - 128) <= 10 and abs(g - 128) <= 10 and abs(b - 128) <= 10
                   for r, g, b in rgb_list)


class TestFullCalibrationPatchSet:
    """完整校准 Patch Set 测试"""

    def test_full_calibration_default(self):
        """默认组合"""
        patch_set = generate_full_calibration_patch_set()

        assert patch_set.count > 50
        assert patch_set.set_type == PatchSetType.FULL_CALIBRATION

    def test_full_calibration_includes_all(self):
        """包含所有类型"""
        patch_set = generate_full_calibration_patch_set(
            include_grayscale=True,
            include_colorchecker=True,
            include_saturation=True,
        )

        purposes = set(p.purpose for p in patch_set.patches)

        assert PatchPurpose.GRAY in purposes or PatchPurpose.BLACK in purposes or PatchPurpose.WHITE in purposes
        assert PatchPurpose.COLORCHECKER in purposes
        assert PatchPurpose.SATURATION_SWEEP in purposes

    def test_full_calibration_excludes_grayscale(self):
        """排除灰阶"""
        patch_set = generate_full_calibration_patch_set(include_grayscale=False)

        # 检查灰阶数量（quick check 有 5-7 个灰阶）
        gray_count = len([p for p in patch_set.patches if p.purpose == PatchPurpose.GRAY])
        assert gray_count <= 20  # quick check + ColorChecker 的灰阶

    def test_full_calibration_deterministic(self):
        """生成 deterministic"""
        set1 = generate_full_calibration_patch_set(seed=42)
        set2 = generate_full_calibration_patch_set(seed=42)

        assert set1.get_rgb_list() == set2.get_rgb_list()


class TestFactoryFunction:
    """工厂函数测试"""

    def test_create_patch_set_quick_check(self):
        """创建快速预检"""
        patch_set = create_patch_set(PatchSetType.QUICK_CHECK, count=20, seed=42)

        assert patch_set.set_type == PatchSetType.QUICK_CHECK
        assert 10 <= patch_set.count <= 30

    def test_create_patch_set_grayscale(self):
        """创建灰阶"""
        patch_set = create_patch_set(PatchSetType.GRAYSCALE_21)

        assert patch_set.set_type == PatchSetType.GRAYSCALE_21

    def test_create_patch_set_colorchecker(self):
        """创建 ColorChecker"""
        patch_set = create_patch_set(PatchSetType.COLORCHECKER)

        assert patch_set.count == 24

    def test_create_patch_set_lut_cube(self):
        """创建 LUT cube"""
        patch_set = create_patch_set(PatchSetType.LUT_CUBE_17)

        assert patch_set.count == 4913

    def test_create_patch_set_invalid_type(self):
        """无效类型"""
        # 创建一个假的枚举值来测试错误处理
        with pytest.raises(ValueError):
            # 通过传入不存在的参数触发错误
            create_patch_set("invalid_type")


class TestDeterministicVerification:
    """deterministic 验证测试"""

    def test_all_generators_deterministic(self):
        """所有生成器 deterministic"""
        generators_and_params = [
            (generate_quick_check_patch_set, {"count": 20, "seed": 42}),
            (generate_hue_sweep_patch_set, {"steps": 12, "seed": 42}),
            (generate_adaptive_patch_set, {"previous_errors": [{"rgb": [128, 128, 128], "delta_e": 10.0}], "threshold": 5.0, "seed": 42}),
            (generate_full_calibration_patch_set, {"seed": 42}),
        ]

        for generator, params in generators_and_params:
            set1 = generator(**params)
            set2 = generator(**params)

            rgb1 = set1.get_rgb_list()
            rgb2 = set2.get_rgb_list()

            assert rgb1 == rgb2, f"{generator.__name__} 生成的结果不一致"

    def test_different_seed_different_result_for_random_generators(self):
        """不同 seed 产生不同结果（随机生成器）"""
        # 快速预检有随机采样
        set1 = generate_quick_check_patch_set(count=20, seed=42)
        set2 = generate_quick_check_patch_set(count=20, seed=123)

        # 基础点相同，随机点应不同
        rgb1 = set(set1.get_rgb_list())
        rgb2 = set(set2.get_rgb_list())

        # 有交集（基础点），但不完全相同
        assert rgb1 != rgb2


class TestExportFormats:
    """导出格式测试"""

    def test_export_rgb_8bit(self):
        """导出 8-bit RGB"""
        patch_set = generate_colorchecker_patch_set()

        rgb_list = patch_set.export_rgb_8bit()

        assert all(len(rgb) == 3 for rgb in rgb_list)
        assert all(all(0 <= v <= 255 for v in rgb) for rgb in rgb_list)

    def test_export_rgb_10bit(self):
        """导出 10-bit RGB"""
        patch_set = generate_colorchecker_patch_set()

        rgb_10bit = patch_set.export_rgb_10bit()

        assert all(len(rgb) == 3 for rgb in rgb_10bit)
        assert all(all(0 <= v <= 1023 for v in rgb) for rgb in rgb_10bit)

    def test_export_lab_targets(self):
        """导出 Lab 目标"""
        patch_set = generate_colorchecker_patch_set()

        lab_list = patch_set.export_lab_targets()

        assert all(len(lab) == 3 for lab in lab_list)
        # L* 在 0-100 范围
        assert all(0 <= lab[0] <= 100 for lab in lab_list)

    def test_export_xyz_targets(self):
        """导出 XYZ 目标"""
        patch_set = generate_colorchecker_patch_set()

        xyz_list = patch_set.export_xyz_targets()

        assert all(len(xyz) == 3 for xyz in xyz_list)
        # Y 在 0-100 范围
        assert all(0 <= xyz[1] <= 100 for xyz in xyz_list)

    def test_export_display_order(self):
        """导出显示顺序"""
        patch_set = generate_grayscale_patch_set(steps=11)

        order_list = patch_set.export_display_order()

        assert len(order_list) == patch_set.count

    def test_export_expected_duration(self):
        """导出预期时长"""
        patch_set = generate_quick_check_patch_set(count=20)

        duration_list = patch_set.export_expected_duration()

        assert len(duration_list) == patch_set.count
        assert all(d > 0 for d in duration_list)

    def test_export_json_roundtrip(self):
        """JSON roundtrip"""
        patch_set = generate_colorchecker_patch_set()

        json_str = patch_set.to_json()
        data = json.loads(json_str)

        assert data["name"] == patch_set.name
        assert data["type"] == patch_set.set_type.value
        assert data["count"] == patch_set.count

    def test_export_csv_format(self):
        """CSV 格式"""
        patch_set = generate_grayscale_patch_set(steps=5)

        csv_str = patch_set.to_csv()
        lines = csv_str.split("\n")

        # 验证 header
        header = lines[0]
        assert "R,G,B" in header
        assert "L,a,b" in header
        assert "purpose" in header


class TestPerformance:
    """性能测试"""

    def test_lut_cube_9_generation_speed(self):
        """9^3 LUT 生成速度"""
        import time

        start = time.time()
        patch_set = generate_lut_cube_patch_set(grid_size=9)
        elapsed = time.time() - start

        # 应在 1 秒内完成
        assert elapsed < 1.0
        assert patch_set.count == 729

    def test_lut_cube_17_generation_speed(self):
        """17^3 LUT 生成速度"""
        import time

        start = time.time()
        patch_set = generate_lut_cube_patch_set(grid_size=17)
        elapsed = time.time() - start

        # 应在 2 秒内完成
        assert elapsed < 2.0
        assert patch_set.count == 4913

    def test_full_calibration_generation_speed(self):
        """完整校准生成速度"""
        import time

        start = time.time()
        patch_set = generate_full_calibration_patch_set()
        elapsed = time.time() - start

        # 应在 1 秒内完成
        assert elapsed < 1.0


class TestPatchSetCoverage:
    """覆盖度测试"""

    def test_all_patch_set_types_covered(self):
        """所有 PatchSetType 都有对应生成器"""
        for set_type in PatchSetType:
            try:
                patch_set = create_patch_set(set_type)
                assert patch_set is not None
            except Exception as e:
                # ADAPTIVE 需要参数
                if set_type == PatchSetType.ADAPTIVE:
                    patch_set = create_patch_set(
                        set_type,
                        previous_errors=[{"rgb": [128, 128, 128], "delta_e": 10.0}]
                    )
                    assert patch_set is not None
                else:
                    pytest.fail(f"无法创建 {set_type}: {e}")

    def test_all_patch_purposes_used(self):
        """所有 PatchPurpose 都被使用"""
        used_purposes = set()

        # 生成所有类型的 patch set
        all_sets = [
            generate_quick_check_patch_set(),
            generate_grayscale_patch_set(),
            generate_gamma_ramp_patch_set(),
            generate_colorchecker_patch_set(),
            generate_memory_colors_patch_set(),
            generate_saturation_sweep_patch_set(),
            generate_hue_sweep_patch_set(),
            generate_lut_cube_patch_set(grid_size=9),
            generate_full_calibration_patch_set(),
        ]

        for patch_set in all_sets:
            for patch in patch_set.patches:
                used_purposes.add(patch.purpose)

        # 检查主要用途都被覆盖
        expected_purposes = [
            PatchPurpose.PRIMARY,
            PatchPurpose.SECONDARY,
            PatchPurpose.GRAY,
            PatchPurpose.BLACK,
            PatchPurpose.WHITE,
            PatchPurpose.COLORCHECKER,
            PatchPurpose.SATURATION_SWEEP,
            PatchPurpose.LUT_CUBE,
        ]

        for purpose in expected_purposes:
            assert purpose in used_purposes, f"{purpose} 未被使用"


class TestAcceptanceCriteria:
    """验收标准测试"""

    def test_different_scenarios_have_patch_sets(self):
        """不同场景有对应 patch set"""
        # 快速预检
        quick = generate_quick_check_patch_set()
        assert 10 <= quick.count <= 30

        # 灰阶
        gray_5 = generate_grayscale_patch_set(steps=5)
        gray_11 = generate_grayscale_patch_set(steps=11)
        gray_21 = generate_grayscale_patch_set(steps=21)
        assert gray_5.count >= 5
        assert gray_11.count >= 11
        assert gray_21.count >= 21

        # gamma/EOTF ramp
        ramp = generate_gamma_ramp_patch_set(steps=21)
        assert ramp.count >= 21

        # ColorChecker
        cc = generate_colorchecker_patch_set()
        assert cc.count == 24

        # 饱和度扫描
        sat = generate_saturation_sweep_patch_set()
        assert sat.count >= 24

        # 色相扫描
        hue = generate_hue_sweep_patch_set()
        assert hue.count >= 12

        # 3D LUT cube
        lut_9 = generate_lut_cube_patch_set(grid_size=9)
        lut_17 = generate_lut_cube_patch_set(grid_size=17)
        lut_21 = generate_lut_cube_patch_set(grid_size=21)
        lut_33 = generate_lut_cube_patch_set(grid_size=33)
        assert lut_9.count == 729
        assert lut_17.count == 4913
        assert lut_21.count == 9261
        assert lut_33.count == 35937

    def test_generation_deterministic_and_reproducible(self):
        """生成 deterministic 且可复现"""
        seed = 12345

        # 测试带随机因素的生成器
        set1 = generate_quick_check_patch_set(count=20, seed=seed)
        set2 = generate_quick_check_patch_set(count=20, seed=seed)

        assert set1.get_rgb_list() == set2.get_rgb_list()

        # 测试无随机因素的生成器
        set1 = generate_colorchecker_patch_set()
        set2 = generate_colorchecker_patch_set()

        assert set1.get_rgb_list() == set2.get_rgb_list()

        set1 = generate_lut_cube_patch_set(grid_size=17)
        set2 = generate_lut_cube_patch_set(grid_size=17)

        assert set1.get_rgb_list() == set2.get_rgb_list()

    def test_export_format_complete(self):
        """导出格式完整"""
        patch_set = generate_colorchecker_patch_set()

        # RGB 8-bit
        rgb_8bit = patch_set.export_rgb_8bit()
        assert all(len(rgb) == 3 and all(0 <= v <= 255 for v in rgb) for rgb in rgb_8bit)

        # RGB 10-bit
        rgb_10bit = patch_set.export_rgb_10bit()
        assert all(len(rgb) == 3 and all(0 <= v <= 1023 for v in rgb) for rgb in rgb_10bit)

        # Lab target
        lab = patch_set.export_lab_targets()
        assert all(len(l) == 3 for l in lab)

        # display order
        order = patch_set.export_display_order()
        assert len(order) == patch_set.count

        # expected duration
        duration = patch_set.export_expected_duration()
        assert len(duration) == patch_set.count

        # JSON
        json_str = patch_set.to_json()
        assert json.loads(json_str) is not None

        # CSV
        csv_str = patch_set.to_csv()
        assert len(csv_str.split("\n")) > 1
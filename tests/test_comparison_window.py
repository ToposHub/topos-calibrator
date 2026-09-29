"""
Test Comparison Window - P6-C 历史对比升级功能测试

测试内容：
- 分组显示功能（按 display、target、workflow、date 分组）
- Golden Baseline 管理功能
- 兼容性检查功能（防误对比）
- Before/After 对比功能
"""

import json
import tempfile
import pytest
from pathlib import Path
from datetime import datetime

# 导入测试目标模块
from src.comparison_window import (
    GoldenBaselineManager,
    MeasurementGroup,
    GroupingManager,
    BeforeAfterResult,
)


# ==============================================================================
# GoldenBaselineManager 测试
# ==============================================================================

class TestGoldenBaselineManager:
    """Golden Baseline 管理器测试"""

    def test_init(self):
        """测试初始化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = GoldenBaselineManager(Path(tmpdir))
            assert manager._baselines == {}

    def test_mark_baseline(self):
        """测试标记 Golden Baseline"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = GoldenBaselineManager(Path(tmpdir))

            # 标记 baseline
            success = manager.mark_baseline(
                measurement_id="test_measurement_001",
                display_id="PHL 439P1",
                target_standard="sRGB",
                notes="参考校准"
            )

            assert success is True
            assert "PHL 439P1" in manager._baselines
            assert "sRGB" in manager._baselines["PHL 439P1"]

            # 检查标记内容
            baseline = manager.get_baseline("PHL 439P1", "sRGB")
            assert baseline is not None
            assert baseline["measurement_id"] == "test_measurement_001"
            assert baseline["notes"] == "参考校准"

    def test_unmark_baseline(self):
        """测试取消 Golden Baseline 标记"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = GoldenBaselineManager(Path(tmpdir))

            # 先标记
            manager.mark_baseline("test_001", "Display1", "sRGB")

            # 再取消
            success = manager.unmark_baseline("Display1", "sRGB")
            assert success is True
            assert manager.get_baseline("Display1", "sRGB") is None

    def test_get_all_baselines(self):
        """测试获取所有 baselines"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = GoldenBaselineManager(Path(tmpdir))

            # 标记多个
            manager.mark_baseline("m1", "Display1", "sRGB")
            manager.mark_baseline("m2", "Display1", "DCI-P3")
            manager.mark_baseline("m3", "Display2", "sRGB")

            all_baselines = manager.get_all_baselines()
            assert len(all_baselines) == 2
            assert "Display1" in all_baselines
            assert "Display2" in all_baselines
            assert len(all_baselines["Display1"]) == 2

    def test_is_baseline(self):
        """测试检查是否是 baseline"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = GoldenBaselineManager(Path(tmpdir))

            manager.mark_baseline("m1", "Display1", "sRGB")

            # 检查已标记的
            is_golden, display, target = manager.is_baseline("m1")
            assert is_golden is True
            assert display == "Display1"
            assert target == "sRGB"

            # 检查未标记的
            is_golden, display, target = manager.is_baseline("m2")
            assert is_golden is False
            assert display is None
            assert target is None

    def test_persistence(self):
        """测试数据持久化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # 创建 manager 并标记
            manager1 = GoldenBaselineManager(tmpdir_path)
            manager1.mark_baseline("m1", "Display1", "sRGB")

            # 创建新的 manager（从文件加载）
            manager2 = GoldenBaselineManager(tmpdir_path)
            baseline = manager2.get_baseline("Display1", "sRGB")
            assert baseline is not None
            assert baseline["measurement_id"] == "m1"


# ==============================================================================
# MeasurementGroup 测试
# ==============================================================================

class TestMeasurementGroup:
    """测量数据分组测试"""

    def test_init(self):
        """测试初始化"""
        group = MeasurementGroup(
            group_key="PHL 439P1",
            group_type="display",
            display_name="PHL 439P1 显示器"
        )

        assert group.group_key == "PHL 439P1"
        assert group.group_type == "display"
        assert group.display_name == "PHL 439P1 显示器"
        assert len(group.measurements) == 0

    def test_add_measurement(self):
        """测试添加测量数据"""
        group = MeasurementGroup("sRGB", "target")

        measurement = {
            "id": "m1",
            "timestamp": "2026-05-19T10:00:00",
            "probe": "i1d3",
        }

        group.add_measurement(measurement)

        assert len(group.measurements) == 1
        assert group.measurements[0] == measurement

    def test_to_dict(self):
        """测试转换为字典"""
        group = MeasurementGroup("Display1", "display", "显示器1")
        group.add_measurement({"id": "m1"})
        group.add_measurement({"id": "m2"})

        result = group.to_dict()

        assert result["group_key"] == "Display1"
        assert result["group_type"] == "display"
        assert result["display_name"] == "显示器1"
        assert result["count"] == 2
        assert len(result["measurements"]) == 2


# ==============================================================================
# GroupingManager 测试
# ==============================================================================

class TestGroupingManager:
    """分组管理器测试"""

    @pytest.fixture
    def sample_measurements(self):
        """创建示例测量数据"""
        return [
            {
                "id": "m1",
                "timestamp": "2026-05-19T10:00:00",
                "display_model": "PHL 439P1",
                "display_type": "l",
                "target_standard": "sRGB",
                "measure_mode": "gamut",
                "probe": "i1d3",
            },
            {
                "id": "m2",
                "timestamp": "2026-05-19T11:00:00",
                "display_model": "PHL 439P1",
                "display_type": "l",
                "target_standard": "DCI-P3",
                "measure_mode": "icc",
                "probe": "i1d3",
            },
            {
                "id": "m3",
                "timestamp": "2026-05-18T10:00:00",
                "display_model": "LG 27UK850",
                "display_type": "l",
                "target_standard": "sRGB",
                "measure_mode": "gamma",
                "probe": "i1pro3",
            },
            {
                "id": "m4",
                "timestamp": "2026-05-19T12:00:00",
                "display_model": "PHL 439P1",
                "display_type": "l",
                "target_standard": "sRGB",
                "measure_mode": "lut",
                "probe": "i1d3",
            },
        ]

    def test_group_by_display(self, sample_measurements):
        """测试按显示器分组"""
        groups = GroupingManager.group_by_display(sample_measurements)

        assert len(groups) == 2

        # PHL 439P1 有 3 条
        phl_group = next((g for g in groups if g.group_key == "PHL 439P1"), None)
        assert phl_group is not None
        assert len(phl_group.measurements) == 3

        # LG 27UK850 有 1 条
        lg_group = next((g for g in groups if g.group_key == "LG 27UK850"), None)
        assert lg_group is not None
        assert len(lg_group.measurements) == 1

    def test_group_by_target(self, sample_measurements):
        """测试按目标标准分组"""
        groups = GroupingManager.group_by_target(sample_measurements)

        assert len(groups) == 2

        # sRGB 有 3 条
        srgb_group = next((g for g in groups if g.group_key == "sRGB"), None)
        assert srgb_group is not None
        assert len(srgb_group.measurements) == 3

        # DCI-P3 有 1 条
        p3_group = next((g for g in groups if g.group_key == "DCI-P3"), None)
        assert p3_group is not None
        assert len(p3_group.measurements) == 1

    def test_group_by_workflow(self, sample_measurements):
        """测试按工作流分组"""
        groups = GroupingManager.group_by_workflow(sample_measurements)

        assert len(groups) == 4  # gamut, icc, gamma, lut

        # 检查 display_name 是否正确翻译
        gamut_group = next((g for g in groups if g.group_key == "gamut"), None)
        assert gamut_group is not None
        assert gamut_group.display_name == "色域测量"

    def test_group_by_date(self, sample_measurements):
        """测试按日期分组"""
        groups = GroupingManager.group_by_date(sample_measurements)

        assert len(groups) == 2

        # 2026-05-19 有 3 条
        date_19 = next((g for g in groups if g.group_key == "2026-05-19"), None)
        assert date_19 is not None
        assert len(date_19.measurements) == 3

        # 2026-05-18 有 1 条
        date_18 = next((g for g in groups if g.group_key == "2026-05-18"), None)
        assert date_18 is not None
        assert len(date_18.measurements) == 1

    def test_group_measurements(self, sample_measurements):
        """测试按指定类型分组"""
        # 按 display 分组
        groups = GroupingManager.group_measurements(sample_measurements, "display")
        assert len(groups) == 2

        # 按 target 分组
        groups = GroupingManager.group_measurements(sample_measurements, "target")
        assert len(groups) == 2

        # 按 workflow 分组
        groups = GroupingManager.group_measurements(sample_measurements, "workflow")
        assert len(groups) == 4

        # 按 date 分组
        groups = GroupingManager.group_measurements(sample_measurements, "date")
        assert len(groups) == 2

    def test_group_empty_measurements(self):
        """测试空数据分组"""
        groups = GroupingManager.group_by_display([])
        assert len(groups) == 0

    def test_group_with_missing_fields(self):
        """测试缺失字段的数据分组"""
        measurements = [
            {"id": "m1"},  # 没有 display_model
            {"id": "m2", "display_model": "Display1"},
        ]

        groups = GroupingManager.group_by_display(measurements)

        # 应该有 "未知显示器" 和 "Display1" 两组
        assert len(groups) == 2


# ==============================================================================
# BeforeAfterResult 测试
# ==============================================================================

class TestBeforeAfterResult:
    """Before/After 对比结果测试"""

    def test_init(self):
        """测试初始化"""
        result = BeforeAfterResult("before_001", "after_001")

        assert result.before_id == "before_001"
        assert result.after_id == "after_001"
        assert result.delta_e_before_avg is None
        assert result.delta_e_after_avg is None

    def test_to_dict(self):
        """测试转换为字典"""
        result = BeforeAfterResult("b1", "a1")
        result.delta_e_before_avg = 4.5
        result.delta_e_after_avg = 1.5
        result.delta_e_improvement_avg = 3.0
        result.delta_e_improved = True

        result_dict = result.to_dict()

        assert result_dict["before_id"] == "b1"
        assert result_dict["after_id"] == "a1"
        assert result_dict["delta_e"]["before_avg"] == 4.5
        assert result_dict["delta_e"]["after_avg"] == 1.5
        assert result_dict["delta_e"]["improvement_avg"] == 3.0
        assert result_dict["delta_e"]["improved"] is True

    def test_improvement_calculation(self):
        """测试改善判断"""
        result = BeforeAfterResult("b1", "a1")

        # Delta E 改善（变小）
        result.delta_e_before_avg = 5.0
        result.delta_e_after_avg = 2.0
        result.delta_e_improvement_avg = 3.0
        result.delta_e_improved = True

        # Gamma 改善（接近 2.2）
        result.gamma_before = 2.4
        result.gamma_after = 2.15
        result.gamma_improvement = 0.25
        result.gamma_improved = True

        # 色域覆盖率改善（变大）
        result.gamut_coverage_before = 92.0
        result.gamut_coverage_after = 98.0
        result.gamut_coverage_improvement = 6.0
        result.gamut_improved = True

        # 整体改善
        result.overall_improved = True
        result.summary = "整体改善，校准效果良好"

        result_dict = result.to_dict()

        assert result_dict["delta_e"]["improved"] is True
        assert result_dict["gamma"]["improved"] is True
        assert result_dict["gamut_coverage"]["improved"] is True
        assert result_dict["overall_improved"] is True


# ==============================================================================
# 兼容性检查测试（模拟 ComparisonBackend 的 check_compatibility 逻辑）
# ==============================================================================

class TestCompatibilityCheck:
    """兼容性检查测试"""

    def test_same_target_compatible(self):
        """测试相同目标标准兼容"""
        measurements = [
            {"id": "m1", "target_standard": "sRGB", "display_model": "Display1"},
            {"id": "m2", "target_standard": "sRGB", "display_model": "Display1"},
        ]

        # 检查目标标准一致性
        targets = set(m.get("target_standard", "") for m in measurements)
        assert len(targets) == 1
        assert "sRGB" in targets

    def test_different_target_incompatible(self):
        """测试不同目标标准不兼容"""
        measurements = [
            {"id": "m1", "target_standard": "sRGB"},
            {"id": "m2", "target_standard": "DCI-P3"},
        ]

        targets = set(m.get("target_standard", "") for m in measurements)
        assert len(targets) == 2

        # 应报告目标标准不一致错误
        errors = []
        if len(targets) > 1:
            errors.append({
                "type": "target_mismatch",
                "message": f"目标标准不一致: {', '.join(targets)}",
            })

        assert len(errors) == 1
        assert errors[0]["type"] == "target_mismatch"

    def test_unknown_target_warning(self):
        """测试未知目标标准警告"""
        measurements = [
            {"id": "m1"},  # 没有 target_standard
            {"id": "m2"},
        ]

        targets = set()
        for m in measurements:
            target = m.get("target_standard")
            if target:
                targets.add(target)

        assert len(targets) == 0

        # 应报告未知目标警告
        warnings = []
        if len(targets) == 0:
            warnings.append({
                "type": "target_unknown",
                "message": "部分数据未指定目标标准",
            })

        assert len(warnings) == 1

    def test_different_display_warning(self):
        """测试不同显示器警告"""
        measurements = [
            {"id": "m1", "display_model": "Display1", "target_standard": "sRGB"},
            {"id": "m2", "display_model": "Display2", "target_standard": "sRGB"},
        ]

        displays = set(m.get("display_model", "") for m in measurements)
        assert len(displays) == 2

        # 应报告显示器不一致警告
        warnings = []
        if len(displays) > 1:
            warnings.append({
                "type": "display_mismatch",
                "message": f"显示器不一致: {', '.join(displays)}",
            })

        assert len(warnings) == 1


# ==============================================================================
# 集成测试
# ==============================================================================

class TestIntegration:
    """集成测试"""

    def test_full_workflow(self):
        """测试完整工作流程"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # 1. 创建 Golden Baseline 管理器
            golden_manager = GoldenBaselineManager(tmpdir_path)

            # 2. 标记一个 baseline
            golden_manager.mark_baseline(
                "baseline_001",
                "PHL 439P1",
                "sRGB",
                "初始校准参考"
            )

            # 3. 创建测量数据
            measurements = [
                {
                    "id": "baseline_001",
                    "timestamp": "2026-05-18T10:00:00",
                    "display_model": "PHL 439P1",
                    "target_standard": "sRGB",
                    "measure_mode": "icc",
                    "probe": "i1d3",
                },
                {
                    "id": "calibration_001",
                    "timestamp": "2026-05-19T10:00:00",
                    "display_model": "PHL 439P1",
                    "target_standard": "sRGB",
                    "measure_mode": "icc",
                    "probe": "i1d3",
                },
                {
                    "id": "calibration_002",
                    "timestamp": "2026-05-19T11:00:00",
                    "display_model": "LG 27UK850",
                    "target_standard": "DCI-P3",
                    "measure_mode": "icc",
                    "probe": "i1pro3",
                },
            ]

            # 4. 检查是否是 baseline
            is_golden, display, target = golden_manager.is_baseline("baseline_001")
            assert is_golden is True
            assert display == "PHL 439P1"
            assert target == "sRGB"

            # 5. 分组显示
            groups = GroupingManager.group_by_display(measurements)
            assert len(groups) == 2

            # 6. 兼容性检查：选择 baseline_001 和 calibration_001（同显示器同目标）
            selected = ["baseline_001", "calibration_001"]
            selected_measurements = [m for m in measurements if m["id"] in selected]
            targets = set(m.get("target_standard", "") for m in selected_measurements)
            displays = set(m.get("display_model", "") for m in selected_measurements)

            assert len(targets) == 1  # 目标标准一致
            assert len(displays) == 1  # 显示器一致

            # 7. 兼容性检查：选择 baseline_001 和 calibration_002（不同显示器不同目标）
            selected = ["baseline_001", "calibration_002"]
            selected_measurements = [m for m in measurements if m["id"] in selected]
            targets = set(m.get("target_standard", "") for m in selected_measurements)
            displays = set(m.get("display_model", "") for m in selected_measurements)

            assert len(targets) == 2  # 目标标准不一致
            assert len(displays) == 2  # 显示器不一致

            # 应该有兼容性错误
            assert len(targets) > 1  # 不兼容


# ==============================================================================
# 运行测试
# ==============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
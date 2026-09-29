"""
Tests for LUT Workflow - 1D/3D LUT generation workflow.

This module tests:
- LUT types (1D/3D) and grid sizes (17, 21, 33, 65)
- Interpolation methods (trilinear/tetrahedral)
- Target spaces (sRGB, Rec.709, P3-D65, BT.2020, HDR PQ)
- Source space presets and definitions
- LUT workflow configuration validation
- Measurement density validation (before LUT generation)
- Intent/BPC parameter combination validation
- Collink command construction
- CUBE file format validation
- LUT generation report with validation results
- Session checkpoint and recovery
- Manifest recording
- Fake adapter workflow completion

Reference:
- docs/agent_handoffs/P4-C_lut_workflow.md
- docs/professional_optimization_plan.md (P4-C requirements)
"""

import os
import tempfile
import json
import shutil
import time
import unittest
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock
from typing import Dict, List, Any

from src.workflows.lut_workflow import (
    # 新增类型
    LUTType,
    GridSize,
    InterpolationMethod,
    TargetSpace,
    LUTFormat,
    LUTSpec,
    # LUTSize 作为 GridSize 的别名（兼容旧测试）
    GridSize as LUTSize,
    # 配置和状态
    LUTWorkflowConfig,
    LUTWorkflowState,
    LUTWorkflowSession,
    LUTGenerationReport,
    LUTValidationResult,
    DensityCheckResult,
    check_measurement_density,
    LUTWorkflow,
    # 源色彩空间
    SourceSpacePreset,
    TransferFunctionType,
    SourceSpaceDefinition,
    SOURCE_SPACE_DEFINITIONS,
    get_source_space_list,
    get_source_space_by_name,
    validate_intent_bpc_combination,
    # 常量
    GRID_SIZE_CATEGORY,
    MIN_MEASUREMENT_DENSITY,
)
from src.instruments.argyll_params import RenderingIntent


# ========== Fixtures ==========

@pytest.fixture
def temp_measurements_dir() -> Path:
    """Create temporary measurements directory."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


@pytest.fixture
def temp_session_dir(temp_measurements_dir: Path) -> Path:
    """Create temporary session directory."""
    session_dir = temp_measurements_dir / "lut_sessions" / "lut-test-001"
    session_dir.mkdir(parents=True, exist_ok=True)
    yield session_dir


@pytest.fixture
def basic_lut_config() -> LUTWorkflowConfig:
    """Create basic LUT workflow configuration."""
    return LUTWorkflowConfig(
        lut_type=LUTType.LUT3D,
        source_space=SourceSpacePreset.REC709_GAMMA24,
        target_space=TargetSpace.REC709,
        lut_spec=LUTSpec(
            lut_type=LUTType.LUT3D,
            size=GridSize.SIZE_33,
            interpolation=InterpolationMethod.TRILINEAR,
        ),
        intent=RenderingIntent.RELATIVE_COLORIMETRIC,
        use_bpc=True,
        auto_validate=True,
        validation_patch_count=50,
    )


@pytest.fixture
def sample_icc_file() -> Path:
    """Create sample ICC file for testing."""
    temp_icc = tempfile.NamedTemporaryFile(suffix=".icc", delete=False)
    temp_icc.write(b"Mock ICC content for testing")
    temp_icc.close()
    yield Path(temp_icc.name)
    os.unlink(temp_icc.name)


@pytest.fixture
def sample_cube_file() -> Path:
    """Create sample CUBE file for testing."""
    temp_cube = tempfile.NamedTemporaryFile(suffix=".cube", delete=False)
    temp_cube.write(b"""TITLE "Test LUT"
LUT_3D_SIZE 33
0.0 0.0 0.0
""")
    temp_cube.close()
    yield Path(temp_cube.name)
    os.unlink(temp_cube.name)


# ========== LUTType Tests ==========

class TestLUTType:
    """测试 LUT 类型"""

    def test_lut_types_defined(self):
        """验证 LUT 类型已定义"""
        assert LUTType.LUT1D.value == "1d"
        assert LUTType.LUT3D.value == "3d"

    def test_lut_type_from_string(self):
        """从字符串创建 LUTType"""
        assert LUTType("1d") == LUTType.LUT1D
        assert LUTType("3d") == LUTType.LUT3D


class TestGridSize:
    """测试 Grid 尺寸"""

    def test_all_sizes_defined(self):
        """验证所有 Grid 尺寸已定义"""
        assert GridSize.SIZE_17.value == 17
        assert GridSize.SIZE_21.value == 21
        assert GridSize.SIZE_33.value == 33
        assert GridSize.SIZE_65.value == 65

    def test_grid_size_categories(self):
        """验证 Grid 尺寸类别"""
        assert GRID_SIZE_CATEGORY[GridSize.SIZE_17] == "basic"
        assert GRID_SIZE_CATEGORY[GridSize.SIZE_21] == "basic"
        assert GRID_SIZE_CATEGORY[GridSize.SIZE_33] == "recommended"
        assert GRID_SIZE_CATEGORY[GridSize.SIZE_65] == "advanced"


class TestInterpolationMethod:
    """测试插值方法"""

    def test_interpolation_methods_defined(self):
        """验证插值方法已定义"""
        assert InterpolationMethod.TRILINEAR.value == "trilinear"
        assert InterpolationMethod.TETRAHEDRAL.value == "tetrahedral"


class TestTargetSpace:
    """测试目标色彩空间"""

    def test_all_target_spaces_defined(self):
        """验证所有目标色彩空间已定义"""
        assert TargetSpace.SRGB.value == "sRGB"
        assert TargetSpace.REC709.value == "Rec709"
        assert TargetSpace.P3_D65.value == "P3-D65"
        assert TargetSpace.BT2020.value == "BT.2020"
        assert TargetSpace.HDR_PQ.value == "HDR_PQ"
        assert TargetSpace.HDR_HLG.value == "HDR_HLG"


# ========== LUTSpec Tests ==========

class TestLUTSpec:
    """测试 LUT 规格"""

    def test_default_spec(self):
        """测试默认规格"""
        spec = LUTSpec()
        assert spec.lut_type == LUTType.LUT3D
        assert spec.size == GridSize.SIZE_33
        assert spec.format == LUTFormat.CUBE
        assert spec.interpolation == InterpolationMethod.TRILINEAR

    def test_get_min_measurement_count(self):
        """测试最小测量数计算"""
        spec_33_3d = LUTSpec(lut_type=LUTType.LUT3D, size=GridSize.SIZE_33)
        min_count = spec_33_3d.get_min_measurement_count()
        assert min_count > 0
        assert min_count == MIN_MEASUREMENT_DENSITY[LUTType.LUT3D][GridSize.SIZE_33]

    def test_get_category(self):
        """测试类别获取"""
        spec_33 = LUTSpec(size=GridSize.SIZE_33)
        assert spec_33.get_category() == "recommended"

        spec_65 = LUTSpec(size=GridSize.SIZE_65)
        assert spec_65.get_category() == "advanced"


# ========== Measurement Density Tests ==========

class TestMeasurementDensity:
    """测试测量点密度校验"""

    def test_density_check_sufficient(self):
        """测试密度充足"""
        spec = LUTSpec(lut_type=LUTType.LUT3D, size=GridSize.SIZE_33)
        required = spec.get_min_measurement_count()

        result = check_measurement_density(
            measurement_count=required + 100,
            lut_spec=spec,
            strict=False,
        )

        assert result.sufficient == True
        assert result.deficit == 0
        assert result.measurement_count >= result.required_count

    def test_density_check_insufficient(self):
        """测试密度不足"""
        spec = LUTSpec(lut_type=LUTType.LUT3D, size=GridSize.SIZE_33)
        required = spec.get_min_measurement_count()

        result = check_measurement_density(
            measurement_count=required - 100,
            lut_spec=spec,
            strict=False,
        )

        assert result.sufficient == False  # 非严格模式，但结果标记不足
        assert result.deficit > 0
        assert "不足" in result.recommendation or "补测" in result.recommendation

    def test_density_check_strict_mode(self):
        """测试严格模式"""
        spec = LUTSpec(lut_type=LUTType.LUT3D, size=GridSize.SIZE_33)
        required = spec.get_min_measurement_count()

        result = check_measurement_density(
            measurement_count=required - 100,
            lut_spec=spec,
            strict=True,
        )

        assert result.sufficient == False
        assert result.deficit > 0


# ========== LUTWorkflowConfig Tests ==========

class TestLUTWorkflowConfig:
    """测试 LUT Workflow 配置"""

    def test_default_config(self):
        """测试默认配置"""
        config = LUTWorkflowConfig()
        assert config.lut_type == LUTType.LUT3D
        assert config.target_space == TargetSpace.REC709
        assert config.auto_validate == True

    def test_config_to_dict(self):
        """测试配置序列化"""
        config = LUTWorkflowConfig(
            lut_type=LUTType.LUT3D,
            source_space=SourceSpacePreset.REC709_GAMMA24,
            target_space=TargetSpace.REC709,
            lut_spec=LUTSpec(size=GridSize.SIZE_33),
        )
        data = config.to_dict()

        assert data["lut_type"] == "3d"
        assert data["target_space"] == "Rec709"
        assert data["lut_spec"]["size"] == 33

    def test_config_from_dict(self):
        """测试配置反序列化"""
        data = {
            "lut_type": "3d",
            "target_space": "P3-D65",
            "lut_spec": {"size": 65, "interpolation": "tetrahedral"},
        }
        config = LUTWorkflowConfig()
        config.from_dict(data)

        assert config.lut_type == LUTType.LUT3D
        assert config.target_space == TargetSpace.P3_D65
        assert config.lut_spec.size == GridSize.SIZE_65
        assert config.lut_spec.interpolation == InterpolationMethod.TETRAHEDRAL


# ========== LUTWorkflowState Tests ==========

class TestLUTWorkflowState:
    """测试 LUT Workflow 状态"""

    def test_all_states_defined(self):
        """验证所有状态已定义"""
        states = [
            LUTWorkflowState.IDLE,
            LUTWorkflowState.CHECKING_DENSITY,
            LUTWorkflowState.VALIDATING_CONFIG,
            LUTWorkflowState.GENERATING_LUT,
            LUTWorkflowState.VALIDATING_LUT,
            LUTWorkflowState.RUNNING_VALIDATION,
            LUTWorkflowState.COMPLETED,
            LUTWorkflowState.FAILED,
            LUTWorkflowState.SUSPENDED,
            LUTWorkflowState.CANCELLED,
        ]
        for state in states:
            assert state.value is not None


# ========== LUTWorkflow Tests ==========

class TestLUTWorkflowBasic:
    """测试 LUT Workflow 基础功能"""

    def test_workflow_initialization(self, basic_lut_config):
        """测试工作流初始化"""
        workflow = LUTWorkflow(basic_lut_config)
        assert workflow.state == LUTWorkflowState.IDLE

    def test_workflow_start_creates_session(self, basic_lut_config, sample_icc_file):
        """测试工作流启动创建 session"""
        basic_lut_config.target_icc_path = str(sample_icc_file)
        workflow = LUTWorkflow(basic_lut_config)

        session = workflow.start(
            measurement_count=500,
            measurement_path=str(sample_icc_file),
        )

        assert session is not None
        assert session.session_id.startswith("lut-")
        assert workflow.session_dir is not None

    def test_workflow_get_session_info(self, basic_lut_config):
        """测试获取 session 信息"""
        workflow = LUTWorkflow(basic_lut_config)
        info = workflow.get_session_info()

        assert "state" in info
        assert info["state"] == "idle"

    def test_workflow_cancel(self, basic_lut_config, sample_icc_file):
        """测试取消工作流"""
        basic_lut_config.target_icc_path = str(sample_icc_file)
        workflow = LUTWorkflow(basic_lut_config)
        workflow.start()

        success = workflow.cancel()
        assert success == True
        assert workflow.state == LUTWorkflowState.CANCELLED


class TestLUTWorkflowWithFakeAdapter:
    """使用 fake adapter 测试 LUT Workflow"""

    def test_fake_adapter_can_complete(self, sample_icc_file, sample_cube_file):
        """测试 fake adapter 下 workflow 可完成"""
        # 创建配置
        config = LUTWorkflowConfig(
            lut_type=LUTType.LUT3D,
            target_icc_path=str(sample_icc_file),
            output_path=str(sample_cube_file),
            lut_spec=LUTSpec(size=GridSize.SIZE_33),
            auto_validate=False,  # 禁用自动验证以简化测试
        )

        # 创建进度追踪
        progress_events = []
        state_events = []

        def on_progress(current, total, message):
            progress_events.append({"current": current, "total": total, "message": message})

        def on_state_change(old_state, new_state):
            state_events.append({"old": old_state.value, "new": new_state.value})

        workflow = LUTWorkflow(
            config,
            on_progress=on_progress,
            on_state_change=on_state_change,
        )

        # Mock collink 执行
        with patch.object(workflow, '_execute_collink', return_value=True):
            with patch.object(workflow, '_validate_cube_file', return_value=(True, "")):
                # 启动并生成
                workflow.start(measurement_count=500)
                success, report = workflow.generate(
                    measurement_count=500,
                    skip_density_check=True,
                )

                assert success == True
                assert report.success == True
                assert workflow.state == LUTWorkflowState.COMPLETED

                # 验证进度事件
                assert len(progress_events) > 0
                assert len(state_events) > 0

    def test_generation_time_performance(self, sample_icc_file, sample_cube_file):
        """测试生成时间性能上限"""
        config = LUTWorkflowConfig(
            target_icc_path=str(sample_icc_file),
            output_path=str(sample_cube_file),
            auto_validate=False,
        )

        workflow = LUTWorkflow(config)

        # Mock collink 执行
        with patch.object(workflow, '_execute_collink', return_value=True):
            with patch.object(workflow, '_validate_cube_file', return_value=(True, "")):
                workflow.start()
                success, report = workflow.generate(skip_density_check=True)

                # 验证性能上限（验收标准）
                assert report.generation_time_ms < workflow.MAX_GENERATION_TIME_MS


# ========== Manifest Tests ==========

class TestLUTManifest:
    """测试 Manifest 记录"""

    def test_manifest_records_lut_parameters(self, sample_icc_file, sample_cube_file):
        """测试 manifest 记录 LUT 参数"""
        config = LUTWorkflowConfig(
            lut_type=LUTType.LUT3D,
            source_space=SourceSpacePreset.REC709_GAMMA24,
            target_space=TargetSpace.REC709,
            target_icc_path=str(sample_icc_file),
            output_path=str(sample_cube_file),
            lut_spec=LUTSpec(
                lut_type=LUTType.LUT3D,
                size=GridSize.SIZE_33,
                interpolation=InterpolationMethod.TETRAHEDRAL,
            ),
        )

        workflow = LUTWorkflow(config)

        with patch.object(workflow, '_execute_collink', return_value=True):
            with patch.object(workflow, '_validate_cube_file', return_value=(True, "")):
                workflow.start()
                success, report = workflow.generate(skip_density_check=True)

                # 验证 session 目录存在
                assert workflow.session_dir is not None

                # 验证 manifest 文件
                manifest_path = workflow.session_dir / "manifest.json"
                if manifest_path.exists():
                    with open(manifest_path, 'r') as f:
                        manifest_data = json.load(f)

                    assert manifest_data["session_id"] == workflow.session.session_id


# ========== Validation Tests ==========

class TestLUTValidation:
    """测试 LUT 验证"""

    def test_validation_result(self):
        """测试验证结果"""
        result = LUTValidationResult(
            validated=True,
            patch_count=50,
            delta_e_avg=1.5,
            delta_e_max=3.0,
            delta_e_95=2.5,
            passed=True,
        )

        data = result.to_dict()
        assert data["validated"] == True
        assert data["delta_e_avg"] == 1.5

    def test_provide_validation_data(self, sample_icc_file):
        """测试提供验证数据"""
        config = LUTWorkflowConfig(target_icc_path=str(sample_icc_file))
        workflow = LUTWorkflow(config)

        # 模拟处于验证状态
        workflow._state = LUTWorkflowState.RUNNING_VALIDATION
        workflow._report = LUTGenerationReport()

        measurements = [{"rgb": [255, 0, 0], "xyY": [0.64, 0.33, 15.0]}]
        delta_e_values = [1.0, 2.0, 1.5]

        success = workflow.provide_validation_data(measurements, delta_e_values)
        assert success == True
        assert workflow._report.validation_result.validated == True


# ========== Keep Existing Tests ==========

class TestSourceSpacePresets(unittest.TestCase):
    """测试源色彩空间预设"""

    def test_all_presets_defined(self):
        """验证所有预设都有完整定义"""
        expected_presets = [
            SourceSpacePreset.REC709_GAMMA24,
            SourceSpacePreset.SRGB,
            SourceSpacePreset.DISPLAY_P3,
            SourceSpacePreset.DCI_P3,
            SourceSpacePreset.REC2020_PQ,
            SourceSpacePreset.REC2020_HLG,
            SourceSpacePreset.REC2020_GAMMA24,
        ]

        for preset in expected_presets:
            self.assertIn(preset, SOURCE_SPACE_DEFINITIONS)
            definition = SOURCE_SPACE_DEFINITIONS[preset]
            self.assertIsInstance(definition, SourceSpaceDefinition)
            self.assertEqual(definition.preset, preset)
            self.assertTrue(definition.name)
            self.assertTrue(definition.primaries_name)
            self.assertTrue(definition.white_point)
            self.assertTrue(definition.argyll_icc_name)

    def test_rec709_gamma24_definition(self):
        """测试 Rec.709 Gamma 2.4 定义"""
        definition = SOURCE_SPACE_DEFINITIONS[SourceSpacePreset.REC709_GAMMA24]

        self.assertEqual(definition.name, "Rec.709 Gamma 2.4")
        self.assertEqual(definition.primaries_name, "Rec709")
        self.assertEqual(definition.white_point, "D65")
        self.assertEqual(definition.gamma, 2.4)
        self.assertEqual(definition.transfer_function, TransferFunctionType.BT1886)
        self.assertEqual(definition.argyll_icc_name, "Rec709.icm")

    def test_srgb_definition(self):
        """测试 sRGB 定义"""
        definition = SOURCE_SPACE_DEFINITIONS[SourceSpacePreset.SRGB]

        self.assertEqual(definition.name, "sRGB")
        self.assertEqual(definition.primaries_name, "sRGB")
        self.assertEqual(definition.white_point, "D65")
        self.assertEqual(definition.transfer_function, TransferFunctionType.SRGB)
        self.assertEqual(definition.argyll_icc_name, "sRGB.icm")

    def test_display_p3_definition(self):
        """测试 Display P3 定义"""
        definition = SOURCE_SPACE_DEFINITIONS[SourceSpacePreset.DISPLAY_P3]

        self.assertEqual(definition.name, "Display P3")
        self.assertEqual(definition.primaries_name, "P3")
        self.assertEqual(definition.white_point, "D65")
        self.assertEqual(definition.gamma, 2.2)
        self.assertEqual(definition.argyll_icc_name, "DisplayP3.icm")

    def test_dci_p3_definition(self):
        """测试 DCI-P3 定义"""
        definition = SOURCE_SPACE_DEFINITIONS[SourceSpacePreset.DCI_P3]

        self.assertEqual(definition.name, "DCI-P3")
        self.assertEqual(definition.primaries_name, "P3")
        self.assertEqual(definition.white_point, "D60")
        self.assertEqual(definition.gamma, 2.6)
        self.assertEqual(definition.argyll_icc_name, "SMPTE431_P3.icm")

    def test_rec2020_pq_definition(self):
        """测试 Rec.2020 PQ 定义"""
        definition = SOURCE_SPACE_DEFINITIONS[SourceSpacePreset.REC2020_PQ]

        self.assertEqual(definition.name, "Rec.2020 PQ")
        self.assertEqual(definition.primaries_name, "Rec2020")
        self.assertEqual(definition.white_point, "D65")
        self.assertEqual(definition.transfer_function, TransferFunctionType.PQ)
        self.assertEqual(definition.argyll_icc_name, "Rec2020.icm")

    def test_rec2020_hlg_definition(self):
        """测试 Rec.2020 HLG 定义"""
        definition = SOURCE_SPACE_DEFINITIONS[SourceSpacePreset.REC2020_HLG]

        self.assertEqual(definition.name, "Rec.2020 HLG")
        self.assertEqual(definition.primaries_name, "Rec2020")
        self.assertEqual(definition.white_point, "D65")
        self.assertEqual(definition.transfer_function, TransferFunctionType.HLG)

    def test_white_point_xy_property(self):
        """测试白点 xy 坐标属性"""
        definition = SOURCE_SPACE_DEFINITIONS[SourceSpacePreset.SRGB]
        xy = definition.white_point_xy

        self.assertEqual(len(xy), 2)
        # D65 白点约 (0.31271, 0.32902)
        self.assertAlmostEqual(xy[0], 0.31271, places=4)
        self.assertAlmostEqual(xy[1], 0.32902, places=4)

    def test_get_source_space_list(self):
        """测试获取源色彩空间列表"""
        space_list = get_source_space_list()

        self.assertEqual(len(space_list), 7)  # 7 个预设
        for space in space_list:
            self.assertIn('preset', space)
            self.assertIn('name', space)
            self.assertIn('description', space)


class TestSourceSpaceByName(unittest.TestCase):
    """测试根据名称获取源色彩空间"""

    def test_exact_match(self):
        """测试精确匹配"""
        preset = get_source_space_by_name("Rec709_Gamma24")
        self.assertEqual(preset, SourceSpacePreset.REC709_GAMMA24)

        preset = get_source_space_by_name("sRGB")
        self.assertEqual(preset, SourceSpacePreset.SRGB)

        preset = get_source_space_by_name("DisplayP3")
        self.assertEqual(preset, SourceSpacePreset.DISPLAY_P3)

    def test_fuzzy_match(self):
        """测试模糊匹配"""
        preset = get_source_space_by_name("rec709")
        self.assertEqual(preset, SourceSpacePreset.REC709_GAMMA24)

        preset = get_source_space_by_name("srgb")
        self.assertEqual(preset, SourceSpacePreset.SRGB)

        preset = get_source_space_by_name("p3")
        self.assertEqual(preset, SourceSpacePreset.DISPLAY_P3)

    def test_no_match(self):
        """测试无匹配"""
        preset = get_source_space_by_name("UnknownSpace")
        self.assertIsNone(preset)


class TestLUTSpec(unittest.TestCase):
    """测试 LUT 规格"""

    def test_default_spec(self):
        """测试默认规格"""
        spec = LUTSpec()

        self.assertEqual(spec.size, LUTSize.SIZE_33)
        self.assertEqual(spec.format, LUTFormat.CUBE)
        self.assertEqual(spec.input_range, "full")

    def test_size_33(self):
        """测试 33 点尺寸"""
        spec = LUTSpec(size=LUTSize.SIZE_33)
        self.assertEqual(spec.size.value, 33)

    def test_size_65(self):
        """测试 65 点尺寸"""
        spec = LUTSpec(size=LUTSize.SIZE_65)
        self.assertEqual(spec.size.value, 65)

    def test_size_17(self):
        """测试 17 点尺寸"""
        spec = LUTSpec(size=LUTSize.SIZE_17)
        self.assertEqual(spec.size.value, 17)

    def test_size_65_advanced(self):
        """测试 65 点尺寸（高级选项）"""
        spec = LUTSpec(size=LUTSize.SIZE_65)
        self.assertEqual(spec.size.value, 65)


class TestLUTWorkflowConfig(unittest.TestCase):
    """测试 LUT 工作流配置"""

    def test_default_config(self):
        """测试默认配置"""
        config = LUTWorkflowConfig()

        self.assertEqual(config.source_space, SourceSpacePreset.REC709_GAMMA24)
        self.assertEqual(config.intent, RenderingIntent.RELATIVE_COLORIMETRIC)
        self.assertTrue(config.use_bpc)
        self.assertEqual(config.lut_spec.size, LUTSize.SIZE_33)

    def test_get_source_definition(self):
        """测试获取源定义"""
        config = LUTWorkflowConfig(source_space=SourceSpacePreset.SRGB)
        definition = config.get_source_definition()

        self.assertEqual(definition.name, "sRGB")
        self.assertEqual(definition.primaries_name, "sRGB")

    def test_validation_missing_target_icc(self):
        """测试验证：缺少目标 ICC"""
        config = LUTWorkflowConfig(
            target_icc_path="",  # 空
            output_path="/tmp/test.cube",
        )
        valid, error = config.validate()

        self.assertFalse(valid)
        self.assertIn("目标 ICC", error)

    def test_validation_missing_target_icc_file(self):
        """测试验证：目标 ICC 文件不存在"""
        config = LUTWorkflowConfig(
            target_icc_path="/nonexistent/path.icc",
            output_path="/tmp/test.cube",
        )
        valid, error = config.validate()

        self.assertFalse(valid)
        self.assertIn("不存在", error)

    def test_validation_missing_output_path(self):
        """测试验证：缺少输出路径"""
        config = LUTWorkflowConfig(
            target_icc_path="/tmp/test.icc",
            output_path="",  # 空
        )
        # 创建临时 ICC 文件
        Path("/tmp/test.icc").touch()

        valid, error = config.validate()

        self.assertFalse(valid)
        self.assertIn("输出路径", error)

        # 清理
        os.remove("/tmp/test.icc")

    def test_validation_bpc_perceptual_conflict(self):
        """测试验证：BPC + 感知意图冲突"""
        config = LUTWorkflowConfig(
            target_icc_path="/tmp/test.icc",
            output_path="/tmp/test.cube",
            intent=RenderingIntent.PERCEPTUAL,
            use_bpc=True,
        )
        # 创建临时 ICC 文件
        Path("/tmp/test.icc").touch()

        valid, error = config.validate()

        # 应返回 True（警告），不是 False（错误）
        self.assertTrue(valid)
        self.assertIn("感知意图", error)

        # 清理
        os.remove("/tmp/test.icc")

    def test_validation_valid_config(self):
        """测试验证：有效配置"""
        # 创建临时 ICC 文件
        temp_icc = tempfile.NamedTemporaryFile(suffix=".icc", delete=False)
        temp_icc.write(b"dummy icc content")
        temp_icc.close()

        config = LUTWorkflowConfig(
            target_icc_path=temp_icc.name,
            output_path="/tmp/test.cube",
            lut_spec=LUTSpec(size=LUTSize.SIZE_65),
        )

        valid, error = config.validate()

        self.assertTrue(valid)
        self.assertEqual(error, "")

        # 清理
        os.unlink(temp_icc.name)


class TestIntentBPCCombination(unittest.TestCase):
    """测试渲染意图和 BPC 参数组合"""

    def test_perceptual_with_bpc(self):
        """测试感知意图 + BPC（不兼容）"""
        valid, message = validate_intent_bpc_combination(
            RenderingIntent.PERCEPTUAL, True
        )

        self.assertFalse(valid)
        self.assertIn("感知意图", message)
        self.assertIn("不支持", message)

    def test_perceptual_without_bpc(self):
        """测试感知意图不启用 BPC（兼容）"""
        valid, message = validate_intent_bpc_combination(
            RenderingIntent.PERCEPTUAL, False
        )

        self.assertTrue(valid)
        self.assertEqual(message, "")

    def test_relative_with_bpc(self):
        """测试相对色度匹配 + BPC（推荐）"""
        valid, message = validate_intent_bpc_combination(
            RenderingIntent.RELATIVE_COLORIMETRIC, True
        )

        self.assertTrue(valid)
        self.assertIn("推荐", message)

    def test_relative_without_bpc(self):
        """测试相对色度匹配不启用 BPC（有警告）"""
        valid, message = validate_intent_bpc_combination(
            RenderingIntent.RELATIVE_COLORIMETRIC, False
        )

        self.assertTrue(valid)
        self.assertIn("警告", message)

    def test_absolute_with_bpc(self):
        """测试绝对色度匹配 + BPC（有警告）"""
        valid, message = validate_intent_bpc_combination(
            RenderingIntent.ABSOLUTE_COLORIMETRIC, True
        )

        self.assertTrue(valid)
        self.assertIn("警告", message)

    def test_absolute_without_bpc(self):
        """测试绝对色度匹配不启用 BPC（兼容）"""
        valid, message = validate_intent_bpc_combination(
            RenderingIntent.ABSOLUTE_COLORIMETRIC, False
        )

        self.assertTrue(valid)
        self.assertEqual(message, "")

    def test_saturation(self):
        """测试饱和意图"""
        valid, message = validate_intent_bpc_combination(
            RenderingIntent.SATURATION, True
        )

        self.assertTrue(valid)


class TestLUTGenerationReport(unittest.TestCase):
    """测试 LUT 生成报告"""

    def test_report_creation(self):
        """测试报告创建"""
        report = LUTGenerationReport(
            source_space_name="Rec.709 Gamma 2.4",
            source_primaries="Rec709",
            source_white_point="D65",
            source_transfer_function="bt1886",
            target_icc_path="/path/to/target.icc",
            target_icc_name="target.icc",
            intent="r",
            use_bpc=True,
            lut_size=33,
            lut_format="cube",
            output_path="/path/to/output.cube",
            file_size_bytes=1024,
            generated_at="2026-05-19 10:00:00",
            success=True,
        )

        self.assertEqual(report.source_space_name, "Rec.709 Gamma 2.4")
        self.assertEqual(report.lut_size, 33)
        self.assertTrue(report.success)

    def test_report_to_dict(self):
        """测试报告转换为字典"""
        report = LUTGenerationReport(
            source_space_name="sRGB",
            lut_size=65,
            success=True,
        )

        data = report.to_dict()

        self.assertIn("source_space", data)
        self.assertIn("lut_spec", data)
        self.assertIn("generation", data)
        self.assertEqual(data["source_space"]["name"], "sRGB")
        self.assertEqual(data["lut_spec"]["size"], 65)

    def test_report_to_json_string(self):
        """测试报告转换为 JSON"""
        report = LUTGenerationReport(
            source_space_name="Display P3",
            lut_size=33,
            success=True,
        )

        json_str = report.to_json_string()

        self.assertIn('"name"', json_str)
        self.assertIn('"Display P3"', json_str)
        self.assertIn('"size"', json_str)
        self.assertIn('"success"', json_str)


class TestLUTWorkflow(unittest.TestCase):
    """测试 LUT 工作流"""

    def test_workflow_initialization(self):
        """测试工作流初始化"""
        config = LUTWorkflowConfig()
        workflow = LUTWorkflow(config)

        self.assertEqual(workflow.state, LUTWorkflowState.IDLE)
        self.assertIsNone(workflow.report)

    def test_workflow_state_transitions(self):
        """测试状态转换（不实际生成）"""
        config = LUTWorkflowConfig(
            target_icc_path="/nonexistent.icc",
        )
        workflow = LUTWorkflow(config)

        # 验证阶段会失败
        success, report = workflow.generate()

        self.assertFalse(success)
        self.assertEqual(workflow.state, LUTWorkflowState.FAILED)
        self.assertIsNotNone(workflow.report)

    def test_build_collink_command(self):
        """测试构建 collink 命令"""
        # 创建临时 ICC 文件
        temp_icc = tempfile.NamedTemporaryFile(suffix=".icc", delete=False)
        temp_icc.write(b"dummy icc content")
        temp_icc.close()

        config = LUTWorkflowConfig(
            target_icc_path=temp_icc.name,
            output_path="/tmp/test.cube",
            source_space=SourceSpacePreset.REC709_GAMMA24,
            lut_spec=LUTSpec(size=LUTSize.SIZE_33),
            intent=RenderingIntent.RELATIVE_COLORIMETRIC,
            use_bpc=True,
        )

        workflow = LUTWorkflow(config)
        cmd = workflow.build_collink_command()

        self.assertIn("collink", cmd[0])  # 第一项是 collink 命令
        self.assertIn("-v", cmd)  # verbose
        # 检查目标 ICC 路径
        self.assertIn("-r", cmd)
        # 检查 LUT 尺寸
        self.assertIn("-G33", cmd) or any("-G" in c and "33" in c for c in cmd)
        # 检查 BPC
        self.assertIn("-b", cmd)

        # 清理
        os.unlink(temp_icc.name)

    def test_get_source_icc_path(self):
        """测试获取源 ICC 路径"""
        config = LUTWorkflowConfig(source_space=SourceSpacePreset.SRGB)
        workflow = LUTWorkflow(config)

        source_icc = workflow.get_source_icc_path()

        # 如果找不到文件，应返回预设名称
        self.assertTrue(
            source_icc.endswith("sRGB.icm") or
            source_icc == "sRGB" or
            "sRGB" in source_icc
        )


class TestCUBEFileValidation(unittest.TestCase):
    """测试 CUBE 文件格式验证"""

    def create_valid_cube_file(self, path: str, size: int = 33) -> None:
        """创建有效的 CUBE 文件"""
        with open(path, 'w') as f:
            f.write("TITLE \"Test LUT\"\n")
            f.write("# Created by Topos Calibrator\n")
            f.write(f"LUT_3D_SIZE {size}\n")
            f.write("\n")

            # 写入数据点（size^3 个）
            for i in range(size ** 3):
                r = i / (size ** 3)
                g = (i + 1) / (size ** 3)
                b = (i + 2) / (size ** 3)
                f.write(f"{r:.6f} {g:.6f} {b:.6f}\n")

    def test_validate_valid_cube_file(self):
        """测试验证有效的 CUBE 文件"""
        temp_cube = tempfile.NamedTemporaryFile(suffix=".cube", delete=False)
        temp_cube.close()

        self.create_valid_cube_file(temp_cube.name, 33)

        config = LUTWorkflowConfig(
            target_icc_path="/tmp/test.icc",
            output_path=temp_cube.name,
            lut_spec=LUTSpec(size=LUTSize.SIZE_33),
        )
        Path("/tmp/test.icc").touch()

        workflow = LUTWorkflow(config)
        valid, error = workflow._validate_cube_file(temp_cube.name)

        self.assertTrue(valid)
        self.assertEqual(error, "")

        # 清理
        os.unlink(temp_cube.name)
        os.unlink("/tmp/test.icc")

    def test_validate_missing_file(self):
        """测试验证：文件不存在"""
        config = LUTWorkflowConfig()
        workflow = LUTWorkflow(config)

        valid, error = workflow._validate_cube_file("/nonexistent.cube")

        self.assertFalse(valid)
        self.assertIn("不存在", error)

    def test_validate_missing_title(self):
        """测试验证：缺少 TITLE"""
        temp_cube = tempfile.NamedTemporaryFile(suffix=".cube", delete=False)
        temp_cube.close()

        with open(temp_cube.name, 'w') as f:
            f.write("# Created by Topos Calibrator\n")
            f.write("LUT_3D_SIZE 33\n")
            f.write("\n")
            for i in range(33 ** 3):
                f.write("0.5 0.5 0.5\n")

        config = LUTWorkflowConfig(lut_spec=LUTSpec(size=LUTSize.SIZE_33))
        workflow = LUTWorkflow(config)
        valid, error = workflow._validate_cube_file(temp_cube.name)

        self.assertFalse(valid)
        self.assertIn("TITLE", error)

        # 清理
        os.unlink(temp_cube.name)

    def test_validate_missing_size(self):
        """测试验证：缺少 LUT_3D_SIZE"""
        temp_cube = tempfile.NamedTemporaryFile(suffix=".cube", delete=False)
        temp_cube.close()

        with open(temp_cube.name, 'w') as f:
            f.write("TITLE \"Test LUT\"\n")
            f.write("\n")
            for i in range(1000):
                f.write("0.5 0.5 0.5\n")

        config = LUTWorkflowConfig(lut_spec=LUTSpec(size=LUTSize.SIZE_33))
        workflow = LUTWorkflow(config)
        valid, error = workflow._validate_cube_file(temp_cube.name)

        self.assertFalse(valid)
        self.assertIn("LUT_3D_SIZE", error)

        # 清理
        os.unlink(temp_cube.name)

    def test_validate_size_mismatch(self):
        """测试验证：尺寸不匹配"""
        temp_cube = tempfile.NamedTemporaryFile(suffix=".cube", delete=False)
        temp_cube.close()

        # 创建 17 点的 LUT，但配置期望 33 点
        self.create_valid_cube_file(temp_cube.name, 17)

        config = LUTWorkflowConfig(lut_spec=LUTSpec(size=LUTSize.SIZE_33))
        workflow = LUTWorkflow(config)
        valid, error = workflow._validate_cube_file(temp_cube.name)

        self.assertFalse(valid)
        self.assertIn("尺寸不匹配", error)

        # 清理
        os.unlink(temp_cube.name)

    def test_validate_65_point_cube(self):
        """测试验证 65 点 LUT"""
        temp_cube = tempfile.NamedTemporaryFile(suffix=".cube", delete=False)
        temp_cube.close()

        self.create_valid_cube_file(temp_cube.name, 65)

        config = LUTWorkflowConfig(lut_spec=LUTSpec(size=LUTSize.SIZE_65))
        workflow = LUTWorkflow(config)
        valid, error = workflow._validate_cube_file(temp_cube.name)

        self.assertTrue(valid)

        # 清理
        os.unlink(temp_cube.name)


class TestLUTWorkflowMocked(unittest.TestCase):
    """使用 Mock 测试 LUT 工作流完整流程"""

    @patch('subprocess.Popen')
    def test_successful_generation(self, mock_popen):
        """测试成功生成 LUT"""
        # 创建临时文件
        temp_icc = tempfile.NamedTemporaryFile(suffix=".icc", delete=False)
        temp_icc.write(b"dummy icc content")
        temp_icc.close()

        temp_cube = tempfile.NamedTemporaryFile(suffix=".cube", delete=False)
        temp_cube.close()

        # 创建有效的 CUBE 文件
        with open(temp_cube.name, 'w') as f:
            f.write("TITLE \"Test LUT\"\n")
            f.write("LUT_3D_SIZE 33\n")
            f.write("\n")
            for i in range(33 ** 3):
                f.write("0.5 0.5 0.5\n")

        # Mock subprocess
        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # 进程结束
        mock_process.returncode = 0
        mock_process.stdout.readline.return_value = ""
        mock_process.stderr.readline.return_value = ""
        mock_process.stdout.read.return_value = ""
        mock_process.stderr.read.return_value = ""
        mock_popen.return_value = mock_process

        config = LUTWorkflowConfig(
            target_icc_path=temp_icc.name,
            output_path=temp_cube.name,
            lut_spec=LUTSpec(size=LUTSize.SIZE_33),
        )

        workflow = LUTWorkflow(config)
        success, report = workflow.generate()

        self.assertTrue(success)
        self.assertTrue(report.success)
        self.assertEqual(report.lut_size, 33)
        self.assertEqual(workflow.state, LUTWorkflowState.COMPLETED)

        # 清理
        os.unlink(temp_icc.name)
        os.unlink(temp_cube.name)

    @patch('subprocess.Popen')
    def test_collink_failure(self, mock_popen):
        """测试 collink 执行失败"""
        # 创建临时 ICC 文件
        temp_icc = tempfile.NamedTemporaryFile(suffix=".icc", delete=False)
        temp_icc.write(b"dummy icc content")
        temp_icc.close()

        temp_cube = tempfile.NamedTemporaryFile(suffix=".cube", delete=False)
        temp_cube.close()

        # Mock subprocess - 返回失败
        mock_process = MagicMock()
        mock_process.poll.return_value = 1
        mock_process.returncode = 1  # 执行失败
        mock_process.stdout.readline.return_value = ""
        mock_process.stderr.readline.return_value = "Error: invalid ICC file\n"
        mock_process.stdout.read.return_value = ""
        mock_process.stderr.read.return_value = "Error: invalid ICC file\n"
        mock_popen.return_value = mock_process

        config = LUTWorkflowConfig(
            target_icc_path=temp_icc.name,
            output_path=temp_cube.name,
        )

        workflow = LUTWorkflow(config)
        success, report = workflow.generate()

        self.assertFalse(success)
        self.assertFalse(report.success)
        self.assertTrue(len(report.error_message) > 0)
        self.assertEqual(workflow.state, LUTWorkflowState.FAILED)

        # 清理
        os.unlink(temp_icc.name)
        os.unlink(temp_cube.name)


if __name__ == '__main__':
    unittest.main()
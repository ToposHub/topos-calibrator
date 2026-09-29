"""
test_schema.py - Schema 单元测试

测试 SchemaV1 和 MeasurementSchema 的功能。
"""

import pytest
import json
from datetime import datetime
from pathlib import Path
from dataclasses import asdict
import sys

# 添加 src 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from storage.schema import (
    SchemaV1,
    SchemaVersion,
    MeasurementSchema,
    validate_schema,
    get_schema_version,
    CURRENT_SCHEMA_VERSION,
    SoftwareInfo,
    EnvironmentInfo,
    InstrumentInfo,
    DisplayInfo,
    WorkflowInfo,
    GamutMeasurement,
    MeasurementsData,
    ArtifactEntry,
    ArtifactsInfo,
)


class TestSchemaVersion:
    """测试 SchemaVersion 类"""

    def test_get_current(self):
        """测试获取当前版本"""
        version = SchemaVersion.get_current()
        assert version == "1.0"

    def test_is_supported_v1(self):
        """测试 v1.0 是支持的版本"""
        assert SchemaVersion.is_supported("1.0") == True

    def test_is_supported_v0(self):
        """测试 legacy v0 是支持的版本"""
        assert SchemaVersion.is_supported("0") == True

    def test_is_supported_unknown(self):
        """测试未知版本不支持"""
        assert SchemaVersion.is_supported("2.0") == False
        assert SchemaVersion.is_supported("invalid") == False

    def test_compare_equal(self):
        """测试版本比较 - 相等"""
        assert SchemaVersion.compare("1.0", "1.0") == 0

    def test_compare_greater(self):
        """测试版本比较 - 大于"""
        assert SchemaVersion.compare("2.0", "1.0") == 1
        assert SchemaVersion.compare("1.1", "1.0") == 1

    def test_compare_less(self):
        """测试版本比较 - 小于"""
        assert SchemaVersion.compare("1.0", "2.0") == -1
        assert SchemaVersion.compare("1.0", "1.1") == -1


class TestSchemaV1:
    """测试 SchemaV1 类"""

    def test_init(self):
        """测试初始化"""
        schema = SchemaV1()
        assert schema.schema_version == CURRENT_SCHEMA_VERSION
        assert schema.session_id is not None
        assert schema.created_at is not None
        assert schema.updated_at is not None
        assert schema.status == "draft"

    def test_session_id_format(self):
        """测试 session_id 格式"""
        schema = SchemaV1()
        # 格式应该是 YYYYMMDD-HHMMSS-XXXXXX
        parts = schema.session_id.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 8  # YYYYMMDD
        assert len(parts[1]) == 6  # HHMMSS
        assert len(parts[2]) == 6  # XXXXXX

    def test_to_dict(self):
        """测试转换为字典"""
        schema = SchemaV1()
        data = schema.to_dict()

        assert "schema_version" in data
        assert data["schema_version"] == CURRENT_SCHEMA_VERSION
        assert "session_id" in data
        assert "software" in data
        assert "environment" in data
        assert "instrument" in data
        assert "display" in data
        assert "workflow" in data
        assert "measurements" in data
        assert "artifacts" in data
        assert "status" in data

    def test_to_json(self):
        """测试转换为 JSON"""
        schema = SchemaV1()
        json_str = schema.to_json()

        # 验证是有效的 JSON
        data = json.loads(json_str)
        assert data["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_from_dict(self):
        """测试从字典加载"""
        schema = SchemaV1()
        data = schema.to_dict()

        new_schema = SchemaV1()
        new_schema.from_dict(data)

        assert new_schema.schema_version == schema.schema_version
        assert new_schema.session_id == schema.session_id

    def test_from_json(self):
        """测试从 JSON 加载"""
        schema = SchemaV1()
        json_str = schema.to_json()

        new_schema = SchemaV1()
        new_schema.from_json(json_str)

        assert new_schema.schema_version == CURRENT_SCHEMA_VERSION

    def test_set_instrument(self):
        """测试设置仪器信息"""
        schema = SchemaV1()
        schema.set_instrument("i1d3", "SN12345", "correction.ccss", "abc123")

        assert schema.instrument.probe == "i1d3"
        assert schema.instrument.probe_serial == "SN12345"
        assert schema.instrument.correction_file == "correction.ccss"
        assert schema.instrument.correction_hash == "abc123"

    def test_set_display(self):
        """测试设置显示器信息"""
        schema = SchemaV1()
        schema.set_display("l", "PHL 439P1", "1", "Main Monitor", (3840, 2160), 60)

        assert schema.display.type == "l"
        assert schema.display.model == "PHL 439P1"
        assert schema.display.display_id == "1"
        assert schema.display.display_name == "Main Monitor"
        assert schema.display.resolution == (3840, 2160)
        assert schema.display.refresh_rate == 60

    def test_set_workflow(self):
        """测试设置工作流信息"""
        schema = SchemaV1()
        schema.set_workflow("icc", "sRGB", 2.2, "D65", {"patch_count": 100})

        assert schema.workflow.mode == "icc"
        assert schema.workflow.target == "sRGB"
        assert schema.workflow.gamma_target == 2.2
        assert schema.workflow.white_point_target == "D65"
        assert schema.workflow.parameters == {"patch_count": 100}

    def test_update_gamut_measurement(self):
        """测试更新色域测量"""
        schema = SchemaV1()
        schema.update_gamut_measurement("red", (255, 0, 0), 0.64, 0.33, 100.0)

        # 验证数据已存储
        data = schema.to_dict()
        gamut = data["measurements"]["gamut"]
        assert gamut["red"]["xyY"] == [0.64, 0.33, 100.0]

    def test_update_gamma_measurement(self):
        """测试更新灰阶测量"""
        schema = SchemaV1()
        schema.update_gamma_measurement(50, 50.0)
        schema.update_gamma_measurement(100, 100.0)

        assert len(schema.measurements.gamma) == 2
        assert schema.measurements.gamma[0]["input"] == 50.0

    def test_update_lut_measurement(self):
        """测试更新 LUT 色块测量"""
        schema = SchemaV1()
        schema.update_lut_measurement("A1", (255, 0, 0), 0.64, 0.33, 100.0)
        schema.update_lut_measurement("A2", (0, 255, 0), 0.30, 0.60, 50.0)

        assert len(schema.measurements.lut_patches) == 2
        assert schema.measurements.lut_patches[0]["sample_id"] == "A1"

    def test_add_artifact(self):
        """测试添加 artifact"""
        schema = SchemaV1()
        schema.add_artifact("measurement_json", "measurement.json", "abc123", 1024, "auto_save")

        assert schema.artifacts.measurement_json is not None
        assert schema.artifacts.measurement_json.filename == "measurement.json"
        assert schema.artifacts.measurement_json.sha256 == "abc123"

    def test_is_valid(self):
        """测试有效性检查"""
        schema = SchemaV1()
        # 没有测量数据，应该无效
        assert schema.is_valid() == False

        # 添加测量数据后应该有效
        schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)
        assert schema.is_valid() == True

    def test_update_timestamp(self):
        """测试更新时间戳"""
        schema = SchemaV1()
        original_time = schema.updated_at

        schema.update_timestamp()

        assert schema.updated_at != original_time


class TestMeasurementSchema:
    """测试 MeasurementSchema 转换"""

    def test_from_legacy_dict(self):
        """测试从旧格式转换"""
        legacy_data = {
            "metadata": {
                "software": "Topos Calibrator",
                "version": "0.1.0-preview",
                "timestamp": "2026-04-16T03:06:51.412652",
                "probe": "i1d3",
                "display_type": "l",
                "display_model": "PHL 439P1",
                "measure_mode": "icc",
                "measurement_id": "20260416_030651_ffa1f8",
                "display_name": "Main Monitor"
            },
            "measurements": {
                "gamut": {
                    "red": {"RGB": [255, 0, 0], "xyY": [0.64, 0.33, 100.0]},
                    "green": {"RGB": [0, 255, 0], "xyY": [0.30, 0.60, 50.0]},
                    "blue": {"RGB": [0, 0, 255], "xyY": [0.15, 0.06, 10.0]},
                    "white": {"RGB": [255, 255, 255], "xyY": [0.3127, 0.3290, 100.0]},
                    "black": {"RGB": [0, 0, 0], "xyY": [0.3127, 0.3290, 0.5]}
                },
                "gamma": [
                    {"input": 0, "Y": 0.5, "RGB": [0, 0, 0]},
                    {"input": 50, "Y": 50.0, "RGB": [128, 128, 128]},
                    {"input": 100, "Y": 100.0, "RGB": [255, 255, 255]}
                ],
                "lut_patches": []
            }
        }

        schema = MeasurementSchema.from_legacy_dict(legacy_data)

        # 验证转换结果
        assert schema.schema_version == CURRENT_SCHEMA_VERSION
        assert schema.session_id == "20260416-030651-ffa1f8"
        assert schema.instrument.probe == "i1d3"
        assert schema.display.type == "l"
        assert schema.display.model == "PHL 439P1"
        assert schema.workflow.mode == "icc"
        assert len(schema.measurements.gamma) == 3

    def test_from_legacy_json(self):
        """测试从旧格式 JSON 字符串转换"""
        legacy_json = json.dumps({
            "metadata": {
                "measurement_id": "20260416_030651_abc123",
                "timestamp": "2026-04-16T03:06:51",
                "probe": "i1d3",
                "measure_mode": "gamut"
            },
            "measurements": {
                "gamut": {
                    "white": {"RGB": [255, 255, 255], "xyY": [0.3127, 0.3290, 100.0]}
                }
            }
        })

        schema = MeasurementSchema.from_legacy_json(legacy_json)

        assert schema.schema_version == CURRENT_SCHEMA_VERSION
        assert schema.session_id == "20260416-030651-abc123"

    def test_to_legacy_dict(self):
        """测试转换回旧格式"""
        schema = SchemaV1()
        schema.instrument.probe = "i1d3"
        schema.workflow.mode = "icc"

        legacy = MeasurementSchema.to_legacy_dict(schema)

        assert "metadata" in legacy
        assert "measurements" in legacy
        assert legacy["metadata"]["probe"] == "i1d3"
        assert legacy["metadata"]["measure_mode"] == "icc"


class TestValidateSchema:
    """测试 validate_schema 函数"""

    def test_valid_v1_schema(self):
        """测试有效的 v1 schema"""
        schema = SchemaV1()
        data = schema.to_dict()

        is_valid, errors = validate_schema(data)
        assert is_valid == True
        assert len(errors) == 0

    def test_missing_schema_version(self):
        """测试缺少 schema_version"""
        data = {"metadata": {}, "measurements": {}}

        is_valid, errors = validate_schema(data)
        assert is_valid == False
        assert "Missing schema_version field" in errors

    def test_unsupported_version(self):
        """测试不支持的版本"""
        data = {"schema_version": "999.0"}

        is_valid, errors = validate_schema(data)
        assert is_valid == False
        assert "Unsupported schema version" in errors[0]

    def test_missing_required_field(self):
        """测试缺少必需字段"""
        data = {
            "schema_version": "1.0",
            "session_id": "test",
            # 缺少 created_at
        }

        is_valid, errors = validate_schema(data)
        assert is_valid == False
        assert "Missing required field: created_at" in errors

    def test_version_mismatch(self):
        """测试版本不匹配"""
        schema = SchemaV1()
        data = schema.to_dict()

        is_valid, errors = validate_schema(data, version="2.0")
        assert is_valid == False
        assert "Version mismatch" in errors[0]


class TestGetSchemaVersion:
    """测试 get_schema_version 函数"""

    def test_v1_data(self):
        """测试 v1 数据"""
        data = {"schema_version": "1.0"}
        version = get_schema_version(data)
        assert version == "1.0"

    def test_legacy_data(self):
        """测试旧格式数据"""
        data = {"metadata": {}, "measurements": {}}
        version = get_schema_version(data)
        assert version == "0"

    def test_empty_data(self):
        """测试空数据"""
        data = {}
        version = get_schema_version(data)
        assert version == "0"


class TestDataclasses:
    """测试各种数据类"""

    def test_software_info(self):
        """测试 SoftwareInfo"""
        info = SoftwareInfo()
        assert info.name == "Topos Calibrator"
        assert info.version == "0.1.0-preview"

    def test_environment_info_auto_fill(self):
        """测试 EnvironmentInfo 自动填充"""
        info = EnvironmentInfo()
        # 应该自动填充 os 和 python_version
        assert info.os != ""
        assert info.python_version != ""

    def test_instrument_info(self):
        """测试 InstrumentInfo"""
        info = InstrumentInfo(probe="i1d3")
        assert info.probe == "i1d3"
        assert info.probe_serial is None

    def test_display_info_resolution(self):
        """测试 DisplayInfo resolution 类型"""
        info = DisplayInfo(resolution=(3840, 2160))
        assert info.resolution == (3840, 2160)
        assert isinstance(info.resolution, tuple)

    def test_gamut_measurement(self):
        """测试 GamutMeasurement"""
        gamut = GamutMeasurement()
        assert gamut.red["RGB"] == [255, 0, 0]
        assert gamut.red["xyY"] is None

    def test_artifact_entry(self):
        """测试 ArtifactEntry"""
        entry = ArtifactEntry(
            filename="test.json",
            sha256="abc123",
            size_bytes=1024
        )
        data = asdict(entry)
        assert data["filename"] == "test.json"

        # 验证可以创建空实例
        new_entry = ArtifactEntry()
        assert new_entry.filename == ""


class TestSchemaRoundtrip:
    """测试 Schema 数据往返转换"""

    def test_full_roundtrip(self):
        """测试完整的往返转换"""
        # 创建 SchemaV1 并填充数据
        schema1 = SchemaV1()
        schema1.set_instrument("i1d3")
        schema1.set_display("l", "PHL 439P1")
        schema1.set_workflow("icc", "sRGB")
        schema1.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)
        schema1.update_gamma_measurement(50, 50.0)
        schema1.add_artifact("measurement_json", "test.json", "hash123")

        # 转换为 JSON
        json_str = schema1.to_json()

        # 从 JSON 加载
        schema2 = SchemaV1()
        schema2.from_json(json_str)

        # 验证数据一致性
        assert schema2.instrument.probe == schema1.instrument.probe
        assert schema2.display.model == schema1.display.model
        assert schema2.workflow.mode == schema1.workflow.mode
        assert len(schema2.measurements.gamma) == len(schema1.measurements.gamma)

    def test_legacy_to_v1_to_legacy(self):
        """测试旧格式 -> v1 -> 旧格式"""
        legacy_data = {
            "metadata": {
                "measurement_id": "20260416_030651_test123",
                "timestamp": "2026-04-16T03:06:51",
                "probe": "i1d3",
                "display_type": "l",
                "measure_mode": "gamut"
            },
            "measurements": {
                "gamut": {
                    "white": {"RGB": [255, 255, 255], "xyY": [0.3127, 0.3290, 100.0]}
                },
                "gamma": []
            }
        }

        # 转换为 v1
        schema = MeasurementSchema.from_legacy_dict(legacy_data)

        # 转换回旧格式
        back_to_legacy = MeasurementSchema.to_legacy_dict(schema)

        # 验证关键字段保持一致
        assert back_to_legacy["metadata"]["probe"] == legacy_data["metadata"]["probe"]
        assert back_to_legacy["metadata"]["measure_mode"] == legacy_data["metadata"]["measure_mode"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
test_storage_service.py - StorageService 和 Migration 测试

测试内容：
- StorageService.save_session() 功能
- StorageService.load_session() 功能
- Legacy -> SchemaV1 migration
- SchemaV1 -> Legacy export
- Manifest validate
"""

import pytest
import json
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
import sys

# 添加 src 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from storage.storage_service import (
    StorageService,
    save_session,
    load_session,
)
from storage.schema import SchemaV1, MeasurementSchema, CURRENT_SCHEMA_VERSION
from storage.manifest import (
    ArtifactManifest,
    ManifestEntry,
    load_manifest,
    validate_manifest,
    compute_file_hash,
    MANIFEST_SCHEMA_VERSION,
)


class TestStorageServiceInit:
    """测试 StorageService 初始化"""

    def test_init_default_path(self):
        """测试默认路径初始化"""
        service = StorageService()
        assert service.measurements_dir.exists()
        assert service.sessions_dir.exists()

    def test_init_custom_path(self):
        """测试自定义路径初始化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            assert service.measurements_dir == Path(tmpdir)
            assert service.sessions_dir.exists()

    def test_sessions_dir_created(self):
        """测试 sessions 目录自动创建"""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            assert (Path(tmpdir) / "sessions").exists()


class TestSaveSession:
    """测试 save_session 方法"""

    @pytest.fixture
    def sample_schema(self):
        """创建示例 SchemaV1"""
        schema = SchemaV1()
        schema.set_instrument("i1d3", "SN12345")
        schema.set_display("l", "PHL 439P1", "1", "Main Monitor", (3840, 2160), 60)
        schema.set_workflow("icc", "sRGB", 2.2, "D65")
        schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)
        schema.update_gamut_measurement("red", (255, 0, 0), 0.64, 0.33, 50.0)
        schema.update_gamma_measurement(50, 50.0)
        schema.update_gamma_measurement(100, 100.0)
        return schema

    def test_save_session_basic(self, sample_schema):
        """测试基本保存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            result = service.save_session(sample_schema)

            assert result["success"] is True
            assert result["session_id"] == sample_schema.session_id
            assert result["session_dir"] is not None

            # 检查文件是否创建
            session_dir = Path(result["session_dir"])
            assert session_dir.exists()

            # 检查 SchemaV1 文件
            schema_path = session_dir / "measurement.schema.v1.json"
            assert schema_path.exists()

            # 检查 manifest 文件
            manifest_path = session_dir / "manifest.json"
            assert manifest_path.exists()

            # 检查 legacy 文件
            legacy_path = session_dir / "measurement.legacy.json"
            assert legacy_path.exists()

    def test_save_session_without_legacy(self, sample_schema):
        """测试不保存 legacy"""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            result = service.save_session(sample_schema, include_legacy=False)

            assert result["success"] is True

            session_dir = Path(result["session_dir"])
            legacy_path = session_dir / "measurement.legacy.json"
            assert not legacy_path.exists()

    def test_save_session_with_artifacts(self, sample_schema):
        """测试保存额外 artifacts"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建一个临时 TI3 文件
            ti3_content = "CTI3\nBEGIN_DATA\n0 0 0 0.3127 0.3290 100.0\nEND_DATA"
            ti3_path = Path(tmpdir) / "test.ti3"
            ti3_path.write_text(ti3_content)

            service = StorageService(tmpdir)
            artifacts = [
                {
                    "path": str(ti3_path),
                    "type": "ti3",
                    "generated_by": "targen"
                }
            ]

            result = service.save_session(sample_schema, artifacts=artifacts)

            assert result["success"] is True

            # 检查 artifact 是否复制到 session 目录
            session_dir = Path(result["session_dir"])
            copied_ti3 = session_dir / "test.ti3"
            assert copied_ti3.exists()

            # 检查 artifact 信息
            assert len(result["files"]["artifacts"]) == 1
            artifact_result = result["files"]["artifacts"][0]
            assert artifact_result["success"] is True
            assert artifact_result["hash"] is not None

    def test_save_session_schema_hash(self, sample_schema):
        """测试 schema 文件 hash 计算"""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            result = service.save_session(sample_schema)

            session_dir = Path(result["session_dir"])
            schema_path = session_dir / "measurement.schema.v1.json"

            # 验证 hash
            actual_hash = compute_file_hash(schema_path)
            assert sample_schema.artifacts.measurement_json.sha256 == actual_hash

    def test_save_session_custom_dir(self, sample_schema):
        """测试自定义 session 目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom_location" / sample_schema.session_id

            service = StorageService(tmpdir)
            result = service.save_session(sample_schema, session_dir=custom_dir)

            assert result["success"] is True
            assert Path(result["session_dir"]) == custom_dir


class TestLoadSession:
    """测试 load_session 方法"""

    @pytest.fixture
    def saved_session(self):
        """创建并保存一个 session"""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)

            schema = SchemaV1()
            schema.set_instrument("i1d3")
            schema.set_display("l", "PHL 439P1")
            schema.set_workflow("gamut", "sRGB")
            schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)

            result = service.save_session(schema)
            session_id = schema.session_id

            yield tmpdir, session_id, schema

    def test_load_session_v1(self, saved_session):
        """测试加载 SchemaV1 格式"""
        tmpdir, session_id, original_schema = saved_session

        service = StorageService(tmpdir)
        loaded_schema, loaded_manifest = service.load_session(session_id)

        assert loaded_schema is not None
        assert loaded_manifest is not None

        # 验证数据一致性
        assert loaded_schema.session_id == session_id
        assert loaded_schema.instrument.probe == original_schema.instrument.probe
        assert loaded_schema.display.model == original_schema.display.model
        assert loaded_schema.workflow.mode == original_schema.workflow.mode

    def test_load_session_manifest(self, saved_session):
        """测试加载 manifest"""
        tmpdir, session_id, original_schema = saved_session

        service = StorageService(tmpdir)
        loaded_schema, loaded_manifest = service.load_session(session_id)

        assert loaded_manifest is not None
        assert loaded_manifest.session_id == session_id
        assert loaded_manifest.workflow.get("mode") == "gamut"

    def test_load_session_not_found(self):
        """测试加载不存在的 session"""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            schema, manifest = service.load_session("nonexistent-session")

            assert schema is None
            assert manifest is None

    def test_load_session_from_legacy(self):
        """测试从 legacy 格式加载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)

            # 创建旧格式数据
            legacy_data = {
                "metadata": {
                    "measurement_id": "20260519_120000_test123",
                    "timestamp": "2026-05-19T12:00:00",
                    "probe": "i1d3",
                    "display_type": "l",
                    "display_model": "PHL 439P1",
                    "measure_mode": "gamut"
                },
                "measurements": {
                    "gamut": {
                        "white": {"RGB": [255, 255, 255], "xyY": [0.3127, 0.3290, 100.0]}
                    },
                    "gamma": []
                }
            }

            # 在 auto_save 目录创建
            session_id = "20260519-120000-test123"
            auto_save_dir = Path(tmpdir) / "auto_save" / "2026-05-19" / session_id
            auto_save_dir.mkdir(parents=True)

            legacy_path = auto_save_dir / "measurement.legacy.json"
            with open(legacy_path, 'w', encoding='utf-8') as f:
                json.dump(legacy_data, f)

            # 加载
            loaded_schema, loaded_manifest = service.load_session(session_id)

            assert loaded_schema is not None
            assert loaded_schema.instrument.probe == "i1d3"


class TestMigration:
    """测试数据迁移"""

    def test_migrate_legacy_to_v1(self):
        """测试 Legacy -> SchemaV1 migration"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # 创建旧格式文件
            legacy_data = {
                "metadata": {
                    "measurement_id": "20260519_120000_migrate1",
                    "timestamp": "2026-05-19T12:00:00",
                    "probe": "i1d3",
                    "display_type": "l",
                    "display_model": "PHL 439P1",
                    "display_name": "Main Monitor",
                    "measure_mode": "icc"
                },
                "measurements": {
                    "gamut": {
                        "white": {"RGB": [255, 255, 255], "xyY": [0.3127, 0.3290, 100.0]},
                        "red": {"RGB": [255, 0, 0], "xyY": [0.64, 0.33, 50.0]},
                        "green": {"RGB": [0, 255, 0], "xyY": [0.30, 0.60, 30.0]},
                        "blue": {"RGB": [0, 0, 255], "xyY": [0.15, 0.06, 10.0]},
                        "black": {"RGB": [0, 0, 0], "xyY": [0.3127, 0.3290, 0.5]}
                    },
                    "gamma": [
                        {"input": 0, "Y": 0.5, "RGB": [0, 0, 0]},
                        {"input": 50, "Y": 50.0, "RGB": [128, 128, 128]},
                        {"input": 100, "Y": 100.0, "RGB": [255, 255, 255]}
                    ]
                }
            }

            legacy_path = tmpdir_path / "legacy_measurement.json"
            with open(legacy_path, 'w', encoding='utf-8') as f:
                json.dump(legacy_data, f)

            # 迁移
            service = StorageService(tmpdir_path)
            result = service.migrate_legacy_to_v1(legacy_path)

            assert result["success"] is True
            assert result["session_id"] == "20260519-120000-migrate1"

            # 检查 SchemaV1 文件
            schema_path = Path(result["schema_path"])
            assert schema_path.exists()

            # 检查 legacy backup
            legacy_backup = Path(result["legacy_backup"])
            assert legacy_backup.exists()

            # 检查 manifest
            manifest_path = Path(result["manifest_path"])
            assert manifest_path.exists()

            # 验证数据完整性
            loaded_schema, loaded_manifest = service.load_session(result["session_id"])
            assert loaded_schema is not None
            assert loaded_schema.instrument.probe == "i1d3"
            assert len(loaded_schema.measurements.gamma) == 3

    def test_migrate_legacy_custom_session_id(self):
        """测试迁移时自定义 session_id"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            legacy_data = {
                "metadata": {
                    "measurement_id": "old_id_123",
                    "probe": "i1d3"
                },
                "measurements": {}
            }

            legacy_path = tmpdir_path / "legacy.json"
            with open(legacy_path, 'w', encoding='utf-8') as f:
                json.dump(legacy_data, f)

            service = StorageService(tmpdir_path)
            result = service.migrate_legacy_to_v1(
                legacy_path,
                session_id="custom-new-id-001"
            )

            assert result["success"] is True
            assert result["session_id"] == "custom-new-id-001"

    def test_migrate_legacy_custom_output_dir(self):
        """测试迁移时自定义输出目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            output_dir = tmpdir_path / "migrated_sessions" / "custom-location"

            legacy_data = {
                "metadata": {
                    "measurement_id": "20260519_test",
                    "probe": "i1d3"
                },
                "measurements": {}
            }

            legacy_path = tmpdir_path / "legacy.json"
            with open(legacy_path, 'w', encoding='utf-8') as f:
                json.dump(legacy_data, f)

            service = StorageService(tmpdir_path)
            result = service.migrate_legacy_to_v1(
                legacy_path,
                output_dir=output_dir
            )

            assert result["success"] is True
            assert Path(result["session_dir"]) == output_dir

    def test_export_v1_to_legacy(self):
        """测试 SchemaV1 -> Legacy export"""
        schema = SchemaV1()
        schema.set_instrument("i1d3", "SN12345")
        schema.set_display("l", "PHL 439P1")
        schema.set_workflow("icc", "sRGB")
        schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            result = service.export_v1_to_legacy(schema)

            assert result["success"] is True
            assert result["path"] is not None

            # 验证导出的 legacy 文件
            legacy_path = Path(result["path"])
            assert legacy_path.exists()

            with open(legacy_path, 'r', encoding='utf-8') as f:
                legacy_data = json.load(f)

            assert "metadata" in legacy_data
            assert legacy_data["metadata"]["probe"] == "i1d3"
            assert legacy_data["metadata"]["measure_mode"] == "icc"

    def test_roundtrip_legacy_to_v1_to_legacy(self):
        """测试 Legacy -> V1 -> Legacy 往返转换"""
        legacy_data = {
            "metadata": {
                "measurement_id": "20260519_120000_roundtrip",
                "timestamp": "2026-05-19T12:00:00",
                "probe": "i1d3",
                "display_type": "l",
                "display_model": "PHL 439P1",
                "measure_mode": "gamut"
            },
            "measurements": {
                "gamut": {
                    "white": {"RGB": [255, 255, 255], "xyY": [0.3127, 0.3290, 100.0]}
                },
                "gamma": []
            }
        }

        # 转换为 V1
        schema = MeasurementSchema.from_legacy_dict(legacy_data)

        # 转换回 legacy
        back_to_legacy = MeasurementSchema.to_legacy_dict(schema)

        # 验证关键字段
        assert back_to_legacy["metadata"]["probe"] == legacy_data["metadata"]["probe"]
        assert back_to_legacy["metadata"]["measure_mode"] == legacy_data["metadata"]["measure_mode"]
        assert back_to_legacy["metadata"]["display_model"] == legacy_data["metadata"]["display_model"]


class TestManifestValidation:
    """测试 Manifest 验证"""

    def test_manifest_validate_ok(self):
        """测试 manifest 验证通过"""
        schema = SchemaV1()
        schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            result = service.save_session(schema)

            session_dir = Path(result["session_dir"])
            manifest_path = session_dir / "manifest.json"

            manifest = load_manifest(manifest_path)
            is_valid, errors = validate_manifest(manifest, session_dir)

            assert is_valid is True
            assert len(errors) == 0

    def test_manifest_validate_missing_file(self):
        """测试 manifest 验证 - 文件缺失"""
        schema = SchemaV1()
        schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            result = service.save_session(schema)

            session_dir = Path(result["session_dir"])

            # 删除 schema 文件
            schema_path = session_dir / "measurement.schema.v1.json"
            schema_path.unlink()

            manifest_path = session_dir / "manifest.json"
            manifest = load_manifest(manifest_path)
            is_valid, errors = validate_manifest(manifest, session_dir)

            assert is_valid is False
            assert "File missing" in errors[0]

    def test_manifest_validate_hash_mismatch(self):
        """测试 manifest 验证 - hash 不匹配"""
        schema = SchemaV1()
        schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            result = service.save_session(schema)

            session_dir = Path(result["session_dir"])

            # 修改文件内容
            schema_path = session_dir / "measurement.schema.v1.json"
            with open(schema_path, 'a', encoding='utf-8') as f:
                f.write("\n// modified")

            manifest_path = session_dir / "manifest.json"
            manifest = load_manifest(manifest_path)
            is_valid, errors = validate_manifest(manifest, session_dir)

            assert is_valid is False
            assert "Hash mismatch" in errors[0]

    def test_session_validation(self):
        """测试 session 验证方法"""
        schema = SchemaV1()
        schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            result = service.save_session(schema)

            # 验证
            is_valid, errors = service.validate_session(schema.session_id)
            assert is_valid is True

    def test_session_validation_missing_manifest(self):
        """测试 session 验证 - 缺少 manifest"""
        schema = SchemaV1()
        schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            result = service.save_session(schema)

            # 删除 manifest
            session_dir = Path(result["session_dir"])
            manifest_path = session_dir / "manifest.json"
            manifest_path.unlink()

            # 验证
            is_valid, errors = service.validate_session(schema.session_id)
            assert is_valid is False
            assert "缺少 manifest.json 文件" in errors


class TestListSessions:
    """测试 list_sessions 方法"""

    def test_list_sessions_empty(self):
        """测试空目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            sessions = service.list_sessions()

            assert len(sessions) == 0

    def test_list_sessions_with_data(self):
        """测试有数据"""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)

            # 创建多个 session
            schemas = []
            for i in range(3):
                schema = SchemaV1()
                schema.instrument.probe = f"probe_{i}"
                schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)
                service.save_session(schema)
                schemas.append(schema)

            sessions = service.list_sessions()

            assert len(sessions) == 3

            # 按时间排序
            assert sessions[0]["session_id"] == schemas[-1].session_id

    def test_list_sessions_info(self):
        """测试 session 信息"""
        schema = SchemaV1()
        schema.set_instrument("i1d3")
        schema.set_display("l", "PHL 439P1")
        schema.set_workflow("icc", "sRGB")
        schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            service.save_session(schema)

            sessions = service.list_sessions()

            assert len(sessions) == 1
            session_info = sessions[0]

            assert session_info["has_schema_v1"] is True
            assert session_info["has_manifest"] is True
            assert session_info["has_legacy"] is True
            assert session_info["probe"] == "i1d3"
            assert session_info["workflow_mode"] == "icc"
            assert session_info["workflow_target"] == "sRGB"


class TestGenerateMissingManifests:
    """测试 generate_missing_manifests 方法"""

    def test_generate_missing(self):
        """测试生成缺失的 manifest"""
        schema = SchemaV1()
        schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            result = service.save_session(schema)

            # 删除 manifest
            session_dir = Path(result["session_dir"])
            manifest_path = session_dir / "manifest.json"
            manifest_path.unlink()

            # 重新生成
            gen_result = service.generate_missing_manifests()

            assert len(gen_result["generated"]) == 1
            assert manifest_path.exists()

    def test_generate_skip_existing(self):
        """测试跳过已存在的 manifest"""
        schema = SchemaV1()
        schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            service = StorageService(tmpdir)
            service.save_session(schema)

            # 重新生成
            gen_result = service.generate_missing_manifests()

            assert len(gen_result["skipped"]) == 1
            assert len(gen_result["generated"]) == 0


class TestConvenienceFunctions:
    """测试便捷函数"""

    def test_save_session_function(self):
        """测试 save_session 便捷函数"""
        schema = SchemaV1()
        schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = save_session(schema, Path(tmpdir))

            assert result["success"] is True

    def test_load_session_function(self):
        """测试 load_session 便捷函数"""
        schema = SchemaV1()
        schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            save_session(schema, Path(tmpdir))
            loaded_schema, loaded_manifest = load_session(schema.session_id, Path(tmpdir))

            assert loaded_schema is not None
            assert loaded_manifest is not None


class TestIntegration:
    """集成测试"""

    def test_full_workflow(self):
        """测试完整工作流程"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. 创建 SchemaV1
            schema = SchemaV1()
            schema.set_instrument("i1d3", "SN12345", "correction.ccss", "abc123")
            schema.set_display("l", "PHL 439P1", "1", "Main Monitor", (3840, 2160), 60)
            schema.set_workflow("icc", "sRGB", 2.2, "D65")
            schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 120.0)
            schema.update_gamut_measurement("black", (0, 0, 0), 0.3127, 0.3290, 0.3)
            schema.update_gamma_measurement(0, 0.3)
            schema.update_gamma_measurement(50, 60.0)
            schema.update_gamma_measurement(100, 120.0)
            schema.notes = "Initial calibration"

            # 2. 保存 session
            service = StorageService(tmpdir)
            save_result = service.save_session(schema, include_ti3=True)

            assert save_result["success"] is True

            # 3. 加载 session
            loaded_schema, loaded_manifest = service.load_session(schema.session_id)

            assert loaded_schema is not None
            assert loaded_schema.instrument.probe == "i1d3"
            assert loaded_schema.display.model == "PHL 439P1"
            assert len(loaded_schema.measurements.gamma) == 3

            # 4. 验证 manifest
            session_dir = Path(save_result["session_dir"])
            is_valid, errors = validate_manifest(loaded_manifest, session_dir)
            assert is_valid is True

            # 5. 导出 legacy
            legacy_result = service.export_v1_to_legacy(loaded_schema)
            assert legacy_result["success"] is True

            # 6. 列出 sessions
            sessions = service.list_sessions()
            assert len(sessions) == 1
            assert sessions[0]["workflow_target"] == "sRGB"


# ==============================================================================
# 运行测试
# ==============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
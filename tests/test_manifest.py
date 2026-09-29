"""
test_manifest.py - Manifest 单元测试

测试 ArtifactManifest 和 ManifestManager 的功能。
"""

import pytest
import json
import hashlib
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
import sys

# 添加 src 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from storage.manifest import (
    ManifestEntry,
    ArtifactManifest,
    compute_file_hash,
    compute_file_size,
    generate_manifest,
    save_manifest,
    load_manifest,
    validate_manifest,
    validate_manifest_file,
    check_file_integrity,
    ManifestManager,
    generate_date_dir_manifest,
    verify_all_manifests,
    MANIFEST_SCHEMA_VERSION,
)


class TestManifestEntry:
    """测试 ManifestEntry 类"""

    def test_init(self):
        """测试初始化"""
        entry = ManifestEntry(
            type="measurement",
            filename="test.json",
            sha256="abc123",
            size_bytes=1024
        )
        assert entry.type == "measurement"
        assert entry.filename == "test.json"
        assert entry.sha256 == "abc123"
        assert entry.size_bytes == 1024

    def test_to_dict(self):
        """测试转换为字典"""
        entry = ManifestEntry(
            type="ti3",
            filename="profile.ti3",
            sha256="def456",
            generated_by="CGATSExporter"
        )
        data = entry.to_dict()

        assert data["type"] == "ti3"
        assert data["filename"] == "profile.ti3"
        assert data["sha256"] == "def456"

    def test_from_dict(self):
        """测试从字典加载"""
        data = {
            "type": "cal",
            "filename": "calibration.cal",
            "sha256": "ghi789",
            "size_bytes": 2048,
            "generated_at": "2026-04-16T03:06:51",
            "generated_by": "dispcal"
        }

        entry = ManifestEntry()
        entry.from_dict(data)

        assert entry.type == "cal"
        assert entry.filename == "calibration.cal"
        assert entry.sha256 == "ghi789"
        assert entry.size_bytes == 2048


class TestArtifactManifest:
    """测试 ArtifactManifest 类"""

    def test_init(self):
        """测试初始化"""
        manifest = ArtifactManifest()
        assert manifest.schema_version == MANIFEST_SCHEMA_VERSION
        assert manifest.files == []
        assert manifest.integrity_status == "unknown"

    def test_add_file(self):
        """测试添加文件"""
        manifest = ArtifactManifest()
        entry = ManifestEntry(
            type="measurement",
            filename="test.json",
            sha256="abc123"
        )
        manifest.add_file(entry)

        assert len(manifest.files) == 1
        assert manifest.files[0].filename == "test.json"

    def test_remove_file(self):
        """测试移除文件"""
        manifest = ArtifactManifest()
        manifest.add_file(ManifestEntry(type="measurement", filename="test.json", sha256="abc"))
        manifest.add_file(ManifestEntry(type="ti3", filename="profile.ti3", sha256="def"))

        result = manifest.remove_file("test.json")
        assert result == True
        assert len(manifest.files) == 1

        result = manifest.remove_file("not_exists.json")
        assert result == False

    def test_get_file(self):
        """测试获取文件"""
        manifest = ArtifactManifest()
        manifest.add_file(ManifestEntry(type="measurement", filename="test.json", sha256="abc"))

        entry = manifest.get_file("test.json")
        assert entry is not None
        assert entry.sha256 == "abc"

        entry = manifest.get_file("not_exists.json")
        assert entry is None

    def test_get_files_by_type(self):
        """测试按类型获取文件"""
        manifest = ArtifactManifest()
        manifest.add_file(ManifestEntry(type="measurement", filename="m1.json", sha256="a"))
        manifest.add_file(ManifestEntry(type="measurement", filename="m2.json", sha256="b"))
        manifest.add_file(ManifestEntry(type="ti3", filename="p.ti3", sha256="c"))

        measurements = manifest.get_files_by_type("measurement")
        assert len(measurements) == 2

        ti3s = manifest.get_files_by_type("ti3")
        assert len(ti3s) == 1

    def test_to_dict(self):
        """测试转换为字典"""
        manifest = ArtifactManifest()
        manifest.session_id = "test-session"
        manifest.add_file(ManifestEntry(type="measurement", filename="test.json", sha256="abc"))

        data = manifest.to_dict()

        assert data["schema_version"] == MANIFEST_SCHEMA_VERSION
        assert data["session_id"] == "test-session"
        assert len(data["files"]) == 1

    def test_to_json(self):
        """测试转换为 JSON"""
        manifest = ArtifactManifest()
        manifest.session_id = "test"

        json_str = manifest.to_json()
        data = json.loads(json_str)

        assert data["session_id"] == "test"

    def test_from_dict(self):
        """测试从字典加载"""
        data = {
            "schema_version": "1.0",
            "session_id": "test-session",
            "created_at": "2026-04-16T03:06:51",
            "files": [
                {"type": "measurement", "filename": "test.json", "sha256": "abc"}
            ]
        }

        manifest = ArtifactManifest()
        manifest.from_dict(data)

        assert manifest.session_id == "test-session"
        assert len(manifest.files) == 1
        assert manifest.files[0].filename == "test.json"

    def test_from_json(self):
        """测试从 JSON 加载"""
        json_str = json.dumps({
            "schema_version": "1.0",
            "session_id": "test",
            "files": []
        })

        manifest = ArtifactManifest()
        manifest.from_json(json_str)

        assert manifest.session_id == "test"

    def test_set_workflow_info(self):
        """测试设置工作流信息"""
        manifest = ArtifactManifest()
        manifest.set_workflow_info("icc", "sRGB", "completed")

        assert manifest.workflow["mode"] == "icc"
        assert manifest.workflow["target"] == "sRGB"
        assert manifest.workflow["status"] == "completed"

    def test_set_instrument_info(self):
        """测试设置仪器信息"""
        manifest = ArtifactManifest()
        manifest.set_instrument_info("i1d3", "correction.ccss")

        assert manifest.instrument["probe"] == "i1d3"
        assert manifest.instrument["correction_file"] == "correction.ccss"

    def test_set_display_info(self):
        """测试设置显示器信息"""
        manifest = ArtifactManifest()
        manifest.set_display_info("PHL 439P1", "Main Monitor", "l")

        assert manifest.display["model"] == "PHL 439P1"
        assert manifest.display["display_name"] == "Main Monitor"
        assert manifest.display["type"] == "l"


class TestFileHashAndSize:
    """测试文件 hash 和大小计算"""

    def test_compute_file_hash(self):
        """测试计算文件 hash"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            f.flush()
            path = Path(f.name)

        hash_value = compute_file_hash(path)

        # 验证是 SHA256 hex string
        assert len(hash_value) == 64
        assert all(c in '0123456789abcdef' for c in hash_value)

        # 验证相同内容产生相同 hash
        hash_value2 = compute_file_hash(path)
        assert hash_value == hash_value2

        path.unlink()

    def test_compute_file_size(self):
        """测试计算文件大小"""
        with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
            f.write(b"test12345")  # 9 bytes
            f.flush()
            path = Path(f.name)

        size = compute_file_size(path)
        assert size == 9

        path.unlink()


class TestGenerateManifest:
    """测试 generate_manifest 函数"""

    def test_generate_manifest_empty_dir(self):
        """测试空目录生成 manifest"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session-001"
            session_dir.mkdir()

            manifest = generate_manifest(session_dir)

            assert manifest.session_id == "session-001"
            assert len(manifest.files) == 0

    def test_generate_manifest_with_files(self):
        """测试有文件时生成 manifest"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session-001"
            session_dir.mkdir()

            # 创建测试文件
            json_file = session_dir / "measurement.json"
            json_file.write_text(json.dumps({
                "schema_version": "1.0",
                "workflow": {"mode": "icc", "target": "sRGB"},
                "instrument": {"probe": "i1d3"},
                "display": {"model": "PHL 439P1"}
            }))

            ti3_file = session_dir / "profile.ti3"
            ti3_file.write_text("CTI3\nBEGIN_DATA\nEND_DATA")

            manifest = generate_manifest(session_dir)

            assert manifest.session_id == "session-001"
            assert len(manifest.files) == 2

            # 检查文件类型识别
            json_entry = manifest.get_file("measurement.json")
            assert json_entry.type == "measurement"
            assert json_entry.sha256 is not None

            ti3_entry = manifest.get_file("profile.ti3")
            assert ti3_entry.type == "ti3"

            # 检查从 JSON 文件读取的信息
            assert manifest.workflow["mode"] == "icc"
            assert manifest.instrument["probe"] == "i1d3"
            assert manifest.display["model"] == "PHL 439P1"

    def test_generate_manifest_with_legacy_json(self):
        """测试旧格式 JSON 文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session-001"
            session_dir.mkdir()

            # 创建旧格式 JSON
            json_file = session_dir / "measurement.json"
            json_file.write_text(json.dumps({
                "metadata": {
                    "probe": "i1d3",
                    "display_type": "l",
                    "measure_mode": "gamut"
                },
                "measurements": {}
            }))

            manifest = generate_manifest(session_dir)

            assert manifest.instrument["probe"] == "i1d3"
            assert manifest.workflow["mode"] == "gamut"


class TestSaveAndLoadManifest:
    """测试保存和加载 manifest"""

    def test_save_manifest(self):
        """测试保存 manifest"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session-001"
            session_dir.mkdir()

            manifest = ArtifactManifest()
            manifest.session_id = "test-session"
            manifest.add_file(ManifestEntry(type="measurement", filename="test.json", sha256="abc"))

            manifest_path = save_manifest(manifest, session_dir)

            assert manifest_path.exists()
            assert manifest_path.name == "manifest.json"

    def test_load_manifest(self):
        """测试加载 manifest"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session-001"
            session_dir.mkdir()

            # 先保存
            manifest1 = ArtifactManifest()
            manifest1.session_id = "test"
            manifest1.add_file(ManifestEntry(type="measurement", filename="m.json", sha256="h"))
            save_manifest(manifest1, session_dir)

            # 再加载
            manifest_path = session_dir / "manifest.json"
            manifest2 = load_manifest(manifest_path)

            assert manifest2.session_id == "test"
            assert len(manifest2.files) == 1

    def test_roundtrip(self):
        """测试往返保存和加载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session-001"
            session_dir.mkdir()

            manifest1 = ArtifactManifest()
            manifest1.session_id = "roundtrip-test"
            manifest1.storage_type = "auto_save"
            manifest1.set_workflow_info("icc", "sRGB")
            manifest1.add_file(ManifestEntry(type="measurement", filename="m.json", sha256="hash1"))
            manifest1.add_file(ManifestEntry(type="ti3", filename="p.ti3", sha256="hash2"))

            save_manifest(manifest1, session_dir)

            manifest2 = load_manifest(session_dir / "manifest.json")

            assert manifest2.session_id == manifest1.session_id
            assert manifest2.storage_type == manifest1.storage_type
            assert len(manifest2.files) == len(manifest1.files)
            assert manifest2.workflow["mode"] == manifest1.workflow["mode"]


class TestValidateManifest:
    """测试 manifest 验证"""

    def test_validate_manifest_ok(self):
        """测试验证通过的 manifest"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session-001"
            session_dir.mkdir()

            # 创建文件
            test_file = session_dir / "test.json"
            content = "test content"
            test_file.write_text(content)
            hash_value = hashlib.sha256(content.encode()).hexdigest()

            # 创建 manifest
            manifest = ArtifactManifest()
            manifest.add_file(ManifestEntry(
                type="measurement",
                filename="test.json",
                sha256=hash_value,
                size_bytes=len(content)
            ))

            is_valid, errors = validate_manifest(manifest, session_dir)

            assert is_valid == True
            assert len(errors) == 0
            assert manifest.integrity_status == "ok"

    def test_validate_manifest_missing_file(self):
        """测试验证 - 文件缺失"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session-001"
            session_dir.mkdir()

            manifest = ArtifactManifest()
            manifest.add_file(ManifestEntry(
                type="measurement",
                filename="missing.json",
                sha256="abc"
            ))

            is_valid, errors = validate_manifest(manifest, session_dir)

            assert is_valid == False
            assert "File missing" in errors[0]
            assert manifest.integrity_status == "error"

    def test_validate_manifest_hash_mismatch(self):
        """测试验证 - hash 不匹配"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session-001"
            session_dir.mkdir()

            # 创建文件
            test_file = session_dir / "test.json"
            test_file.write_text("real content")

            # manifest 使用错误的 hash
            manifest = ArtifactManifest()
            manifest.add_file(ManifestEntry(
                type="measurement",
                filename="test.json",
                sha256="wrong_hash_00000000000000000000000000000000"
            ))

            is_valid, errors = validate_manifest(manifest, session_dir)

            assert is_valid == False
            assert "Hash mismatch" in errors[0]

    def test_validate_manifest_untracked_file(self):
        """测试验证 - 未记录的文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session-001"
            session_dir.mkdir()

            # 创建未记录的文件
            extra_file = session_dir / "extra.ti3"
            extra_file.write_text("extra content")

            manifest = ArtifactManifest()
            # manifest 为空

            is_valid, errors = validate_manifest(manifest, session_dir)

            # 应该有警告（但不失败）
            assert "Untracked file" in errors[0]
            assert manifest.integrity_status == "warning"

    def test_validate_manifest_file(self):
        """测试 validate_manifest_file 函数"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session-001"
            session_dir.mkdir()

            # 创建文件和 manifest
            test_file = session_dir / "test.json"
            content = "test"
            test_file.write_text(content)
            hash_value = hashlib.sha256(content.encode()).hexdigest()

            manifest = ArtifactManifest()
            manifest.add_file(ManifestEntry(
                type="measurement",
                filename="test.json",
                sha256=hash_value
            ))
            save_manifest(manifest, session_dir)

            is_valid, errors = validate_manifest_file(session_dir / "manifest.json")
            assert is_valid == True


class TestCheckFileIntegrity:
    """测试单个文件完整性检查"""

    def test_check_file_exists(self):
        """测试文件存在检查"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)

        is_ok, issues = check_file_integrity(path)
        assert is_ok == True

        path.unlink()

    def test_check_file_missing(self):
        """测试文件缺失检查"""
        path = Path("/nonexistent/file.json")

        is_ok, issues = check_file_integrity(path)
        assert is_ok == False
        assert "does not exist" in issues[0]

    def test_check_file_hash(self):
        """测试文件 hash 检查"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            path = Path(f.name)

        correct_hash = compute_file_hash(path)

        is_ok, issues = check_file_integrity(path, expected_hash=correct_hash)
        assert is_ok == True

        is_ok, issues = check_file_integrity(path, expected_hash="wrong_hash")
        assert is_ok == False
        assert "Hash mismatch" in issues[0]

        path.unlink()

    def test_check_file_size(self):
        """测试文件大小检查"""
        with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
            f.write(b"12345")  # 5 bytes
            path = Path(f.name)

        is_ok, issues = check_file_integrity(path, expected_size=5)
        assert is_ok == True

        is_ok, issues = check_file_integrity(path, expected_size=10)
        assert is_ok == False
        assert "Size mismatch" in issues[0]

        path.unlink()


class TestManifestManager:
    """测试 ManifestManager 类"""

    def test_init(self):
        """测试初始化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ManifestManager(Path(tmpdir))
            assert manager.measurements_dir == Path(tmpdir)

    def test_generate_all_manifests(self):
        """测试批量生成 manifest"""
        with tempfile.TemporaryDirectory() as tmpdir:
            measurements_dir = Path(tmpdir)
            auto_save_dir = measurements_dir / "auto_save" / "2026-04-16"
            auto_save_dir.mkdir(parents=True)

            session_dir = auto_save_dir / "session-001"
            session_dir.mkdir()

            # 创建文件
            test_file = session_dir / "measurement.json"
            test_file.write_text(json.dumps({
                "schema_version": "1.0",
                "workflow": {"mode": "icc"},
                "instrument": {"probe": "i1d3"},
                "display": {"model": "Test"}
            }))

            manager = ManifestManager(measurements_dir)
            result = manager.generate_all_manifests()

            assert len(result["generated"]) == 1
            assert (session_dir / "manifest.json").exists()

    def test_validate_all_manifests(self):
        """测试批量验证 manifest"""
        with tempfile.TemporaryDirectory() as tmpdir:
            measurements_dir = Path(tmpdir)
            auto_save_dir = measurements_dir / "auto_save" / "2026-04-16"
            auto_save_dir.mkdir(parents=True)

            session_dir = auto_save_dir / "session-001"
            session_dir.mkdir()

            # 创建文件和有效 manifest
            test_file = session_dir / "test.json"
            content = "test"
            test_file.write_text(content)
            hash_value = hashlib.sha256(content.encode()).hexdigest()

            manifest = ArtifactManifest()
            manifest.add_file(ManifestEntry(filename="test.json", sha256=hash_value, type="measurement"))
            save_manifest(manifest, session_dir)

            manager = ManifestManager(measurements_dir)
            result = manager.validate_all_manifests()

            assert len(result["valid"]) == 1

    def test_get_manifest(self):
        """测试获取指定 manifest"""
        with tempfile.TemporaryDirectory() as tmpdir:
            measurements_dir = Path(tmpdir)
            auto_save_dir = measurements_dir / "auto_save" / "2026-04-16" / "session-001"
            auto_save_dir.mkdir(parents=True)

            manifest = ArtifactManifest()
            manifest.session_id = "session-001"
            save_manifest(manifest, auto_save_dir)

            manager = ManifestManager(measurements_dir)
            retrieved = manager.get_manifest("session-001")

            assert retrieved is not None
            assert retrieved.session_id == "session-001"

    def test_add_file_to_manifest(self):
        """测试向 manifest 添加文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            measurements_dir = Path(tmpdir)
            session_dir = measurements_dir / "auto_save" / "2026-04-16" / "session-001"
            session_dir.mkdir(parents=True)

            # 创建初始 manifest
            manifest = ArtifactManifest()
            manifest.session_id = "session-001"
            save_manifest(manifest, session_dir)

            # 创建新文件
            new_file = session_dir / "new.ti3"
            new_file.write_text("CTI3")

            manager = ManifestManager(measurements_dir)
            result = manager.add_file_to_manifest("session-001", new_file, "ti3", "export")

            assert result == True

            # 验证文件已添加
            updated = manager.get_manifest("session-001")
            assert len(updated.files) == 1
            assert updated.files[0].filename == "new.ti3"


class TestManifestDeletionScenario:
    """测试删除 artifact 后 manifest 校验报错场景"""

    def test_delete_file_detected(self):
        """测试删除文件后被 manifest 检测到"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session-001"
            session_dir.mkdir()

            # 创建文件
            test_file = session_dir / "test.json"
            content = "test content"
            test_file.write_text(content)
            hash_value = hashlib.sha256(content.encode()).hexdigest()

            # 创建 manifest
            manifest = ArtifactManifest()
            manifest.add_file(ManifestEntry(
                type="measurement",
                filename="test.json",
                sha256=hash_value
            ))
            save_manifest(manifest, session_dir)

            # 验证应该通过
            is_valid, _ = validate_manifest_file(session_dir / "manifest.json")
            assert is_valid == True

            # 删除文件
            test_file.unlink()

            # 验证应该失败
            is_valid, errors = validate_manifest_file(session_dir / "manifest.json")
            assert is_valid == False
            assert "File missing" in errors[0]

    def test_move_file_detected(self):
        """测试移动文件后被 manifest 检测到"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "session-001"
            session_dir.mkdir()

            # 创建文件
            test_file = session_dir / "test.json"
            content = "test content"
            test_file.write_text(content)
            hash_value = hashlib.sha256(content.encode()).hexdigest()

            # 创建 manifest
            manifest = ArtifactManifest()
            manifest.add_file(ManifestEntry(
                type="measurement",
                filename="test.json",
                sha256=hash_value
            ))
            save_manifest(manifest, session_dir)

            # 移动文件到其他位置
            test_file.rename(Path(tmpdir) / "moved.json")

            # 验证应该失败
            is_valid, errors = validate_manifest_file(session_dir / "manifest.json")
            assert is_valid == False
            assert "File missing" in errors[0]


class TestVerifyAllManifests:
    """测试 verify_all_manifests 函数"""

    def test_verify_all(self):
        """测试验证所有 manifest"""
        with tempfile.TemporaryDirectory() as tmpdir:
            measurements_dir = Path(tmpdir)
            auto_save_dir = measurements_dir / "auto_save" / "2026-04-16"
            auto_save_dir.mkdir(parents=True)

            # 创建两个 session
            for i in range(2):
                session_dir = auto_save_dir / f"session-{i}"
                session_dir.mkdir()

                test_file = session_dir / "test.json"
                content = f"content {i}"
                test_file.write_text(content)
                hash_value = hashlib.sha256(content.encode()).hexdigest()

                manifest = ArtifactManifest()
                manifest.session_id = f"session-{i}"
                manifest.add_file(ManifestEntry(filename="test.json", sha256=hash_value, type="measurement"))
                save_manifest(manifest, session_dir)

            pass_count, fail_count, issues = verify_all_manifests(measurements_dir)

            assert pass_count == 2
            assert fail_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
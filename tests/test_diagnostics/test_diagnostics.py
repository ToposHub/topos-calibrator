"""
Test Diagnostics Module - 诊断包单元测试

测试 DiagnosticsCollector 和 export_diagnostics_pack 功能：
- 环境信息收集
- 异常记录
- 诊断包导出
- 隐私保护
"""

import json
import os
import platform
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock
from typing import Dict, Any

import pytest

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.diagnostics.diagnostics import (
    DiagnosticsPack,
    DiagnosticsCollector,
    EnvironmentInfo,
    ExceptionRecord,
    export_diagnostics_pack,
    get_export_options,
    create_collector,
    _sanitize_path_in_file,
    _collect_session_logs,
    _collect_session_files,
    DIAGNOSTICS_VERSION,
    EXPORT_OPTIONS,
    PRIVATE_EXTENSIONS,
)


class TestEnvironmentInfo:
    """EnvironmentInfo 测试"""

    def test_auto_fill_platform_info(self):
        """测试自动填充平台信息"""
        env = EnvironmentInfo()
        
        assert env.os_name == platform.system()
        assert env.os_version == platform.version()
        assert env.os_release == platform.release()
        assert env.python_version == platform.python_version()
        assert env.python_executable == sys.executable

    def test_timestamp_auto_set(self):
        """测试时间戳自动设置"""
        env = EnvironmentInfo()
        
        assert env.timestamp is not None
        # ISO 格式验证
        datetime.fromisoformat(env.timestamp)

    def test_to_dict_sanitizes_paths(self):
        """测试 to_dict 脱敏路径"""
        env = EnvironmentInfo()
        env.python_executable = "/Users/testuser/bin/python"
        
        data = env.to_dict()
        
        assert "testuser" not in data["python_executable"]
        assert "***" in data["python_executable"]

    def test_display_info_default_empty(self):
        """测试显示器信息默认为空列表"""
        env = EnvironmentInfo()
        
        assert isinstance(env.display_info, list)

    def test_custom_fields(self):
        """测试自定义字段"""
        env = EnvironmentInfo(
            os_name="CustomOS",
            python_version="3.99.0",
            app_version="1.0.0"
        )
        
        assert env.os_name == "CustomOS"
        assert env.python_version == "3.99.0"
        assert env.app_version == "1.0.0"


class TestExceptionRecord:
    """ExceptionRecord 测试"""

    def test_exception_record_creation(self):
        """测试异常记录创建"""
        record = ExceptionRecord(
            timestamp="2026-05-19T10:00:00",
            exception_type="ValueError",
            exception_message="Test error",
            traceback="Stack trace...",
            context={"key": "value"}
        )
        
        assert record.exception_type == "ValueError"
        assert record.exception_message == "Test error"

    def test_to_dict(self):
        """测试转换为字典"""
        record = ExceptionRecord(
            timestamp="2026-05-19T10:00:00",
            exception_type="RuntimeError",
            exception_message="Runtime issue",
            context={"operation": "test"}
        )
        
        data = record.to_dict()
        
        assert data["exception_type"] == "RuntimeError"
        assert data["context"]["operation"] == "test"


class TestDiagnosticsPack:
    """DiagnosticsPack 测试"""

    def test_pack_creation(self):
        """测试诊断包创建"""
        pack = DiagnosticsPack(
            session_id="test-session",
            created_at="2026-05-19T10:00:00"
        )
        
        assert pack.session_id == "test-session"
        assert pack.version == DIAGNOSTICS_VERSION
        assert isinstance(pack.exceptions, list)
        assert isinstance(pack.included_files, list)

    def test_pack_with_environment(self):
        """测试带环境信息的诊断包"""
        env = EnvironmentInfo()
        pack = DiagnosticsPack(
            session_id="env-session",
            environment=env
        )
        
        assert pack.environment is not None
        assert pack.environment.os_name == platform.system()

    def test_pack_with_exceptions(self):
        """测试带异常记录的诊断包"""
        exc1 = ExceptionRecord(exception_type="Error1", exception_message="First")
        exc2 = ExceptionRecord(exception_type="Error2", exception_message="Second")
        
        pack = DiagnosticsPack(
            session_id="exc-session",
            exceptions=[exc1, exc2]
        )
        
        assert len(pack.exceptions) == 2

    def test_to_dict(self):
        """测试转换为字典"""
        env = EnvironmentInfo()
        exc = ExceptionRecord(exception_type="TestError", exception_message="Test")
        
        pack = DiagnosticsPack(
            session_id="dict-session",
            environment=env,
            exceptions=[exc],
            export_options=["logs", "environment"]
        )
        
        data = pack.to_dict()
        
        assert data["session_id"] == "dict-session"
        assert data["environment"] is not None
        assert len(data["exceptions"]) == 1
        assert "logs" in data["export_options"]


class TestDiagnosticsCollector:
    """DiagnosticsCollector 测试"""

    def test_collector_creation(self):
        """测试收集器创建"""
        collector = DiagnosticsCollector("test-collector")
        
        assert collector.session_id == "test-collector"
        assert isinstance(collector.exceptions, list)

    def test_collector_auto_session_id(self):
        """测试自动生成 session ID"""
        collector = DiagnosticsCollector()
        
        assert collector.session_id is not None
        # 格式验证：YYYYMMDD-HHMMSS
        assert len(collector.session_id) >= 15

    def test_collect_environment(self):
        """测试收集环境信息"""
        collector = DiagnosticsCollector()
        
        env = collector.collect_environment()
        
        assert env is not None
        assert env.os_name == platform.system()
        assert env.python_version == platform.python_version()

    def test_collect_environment_argyll_detection(self):
        """测试 ArgyllCMS 检测"""
        collector = DiagnosticsCollector()
        
        # Mock subprocess 来模拟 ArgyllCMS 存在
        with patch("subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "ArgyllCMS version 2.3.0\nlocated at /usr/local/bin"
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            env = collector.collect_environment()
            
            # 检查检测是否成功
            assert collector._argyll_detected is not None

    def test_record_exception(self):
        """测试记录异常"""
        collector = DiagnosticsCollector()
        
        try:
            raise ValueError("Test exception for collector")
        except Exception as e:
            record = collector.record_exception(e, {"operation": "test"})
        
        assert len(collector.exceptions) == 1
        assert collector.exceptions[0].exception_type == "ValueError"
        assert collector.exceptions[0].exception_message == "Test exception for collector"

    def test_get_environment_lazy(self):
        """测试延迟获取环境信息"""
        collector = DiagnosticsCollector()
        
        # 未调用 collect_environment 时，get_environment 应自动收集
        env = collector.get_environment()
        
        assert env is not None
        assert collector._environment is not None

    def test_record_multiple_exceptions(self):
        """测试记录多个异常"""
        collector = DiagnosticsCollector()
        
        for i in range(3):
            try:
                raise RuntimeError(f"Error {i}")
            except Exception as e:
                collector.record_exception(e)
        
        assert len(collector.exceptions) == 3


class TestExportDiagnosticsPack:
    """export_diagnostics_pack 测试"""

    def test_export_creates_zip(self, temp_session_dir):
        """测试导出创建 ZIP 文件"""
        output_path = temp_session_dir / "diagnostics_test.zip"
        
        zip_path = export_diagnostics_pack(
            session_id="export-test",
            output_path=output_path
        )
        
        assert zip_path.exists()
        assert zip_path.suffix == ".zip"
        assert zipfile.is_zipfile(zip_path)

    def test_export_includes_manifest(self, temp_session_dir):
        """测试导出包含 manifest"""
        output_path = temp_session_dir / "manifest_test.zip"
        
        zip_path = export_diagnostics_pack(
            session_id="manifest-test",
            output_path=output_path
        )
        
        with zipfile.ZipFile(zip_path) as zf:
            assert "diagnostics_manifest.json" in zf.namelist()
            
            # 检查 manifest 内容
            manifest_data = json.loads(zf.read("diagnostics_manifest.json"))
            assert manifest_data["session_id"] == "manifest-test"
            assert manifest_data["version"] == DIAGNOSTICS_VERSION

    def test_export_with_options(self, temp_session_dir):
        """测试按选项导出"""
        output_path = temp_session_dir / "options_test.zip"
        
        # 只导出日志和环境
        zip_path = export_diagnostics_pack(
            session_id="options-test",
            output_path=output_path,
            options={"logs", "environment"}
        )
        
        with zipfile.ZipFile(zip_path) as zf:
            manifest_data = json.loads(zf.read("diagnostics_manifest.json"))
            assert "logs" in manifest_data["export_options"]
            assert "environment" in manifest_data["export_options"]

    def test_export_with_session_dir(self, temp_session_dir):
        """测试导出包含会话目录文件"""
        # 创建会话目录和文件
        session_dir = temp_session_dir / "session_data"
        session_dir.mkdir()
        
        # 创建测量数据文件
        measurement_file = session_dir / "measurement.json"
        measurement_file.write_text(json.dumps({"test": "data"}))
        
        # 创建 TI3 文件
        ti3_file = session_dir / "test.ti3"
        ti3_file.write_text("CTI3\nNUMBER_OF_SETS 1\n")
        
        output_path = temp_session_dir / "session_test.zip"
        
        # 显式包含测量和 argyll_output 选项
        zip_path = export_diagnostics_pack(
            session_id="session-test",
            session_dir=session_dir,
            output_path=output_path,
            options={"logs", "environment", "argyll_output", "measurements"}
        )
        
        with zipfile.ZipFile(zip_path) as zf:
            manifest_data = json.loads(zf.read("diagnostics_manifest.json"))
            # 检查包含的文件
            assert len(manifest_data["included_files"]) > 0

    def test_export_private_files_excluded(self, temp_session_dir):
        """测试隐私文件默认不包含"""
        session_dir = temp_session_dir / "private_session"
        session_dir.mkdir()
        
        # 创建隐私敏感文件
        icc_file = session_dir / "profile.icc"
        icc_file.write_bytes(b"ICC profile data")
        
        cal_file = session_dir / "monitor.cal"
        cal_file.write_text("CAL file content")
        
        output_path = temp_session_dir / "private_test.zip"
        
        # 默认不包含隐私文件
        zip_path = export_diagnostics_pack(
            session_id="private-test",
            session_dir=session_dir,
            output_path=output_path,
            include_private=False
        )
        
        with zipfile.ZipFile(zip_path) as zf:
            # ICC 和 CAL 文件不应在包中
            names = zf.namelist()
            assert not any("profile.icc" in n for n in names)

    def test_export_private_files_included(self, temp_session_dir):
        """测试显式包含隐私文件"""
        session_dir = temp_session_dir / "include_private_session"
        session_dir.mkdir()
        
        icc_file = session_dir / "profile.icc"
        icc_file.write_bytes(b"ICC profile data")
        
        output_path = temp_session_dir / "include_private_test.zip"
        
        # 显式包含隐私文件
        zip_path = export_diagnostics_pack(
            session_id="include-private-test",
            session_dir=session_dir,
            output_path=output_path,
            include_private=True
        )
        
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert any("profile.icc" in n for n in names)

    def test_export_with_collector(self, temp_session_dir):
        """测试使用自定义 collector"""
        collector = DiagnosticsCollector("custom-collector")
        collector.collect_environment()
        
        # 记录异常
        try:
            raise RuntimeError("Collector test error")
        except Exception as e:
            collector.record_exception(e)
        
        output_path = temp_session_dir / "collector_test.zip"
        
        zip_path = export_diagnostics_pack(
            session_id="collector-test",
            output_path=output_path,
            collector=collector
        )
        
        with zipfile.ZipFile(zip_path) as zf:
            manifest_data = json.loads(zf.read("diagnostics_manifest.json"))
            assert len(manifest_data["exceptions"]) == 1
            assert manifest_data["exceptions"][0]["exception_type"] == "RuntimeError"


class TestPathSanitizationInFile:
    """文件路径脱敏测试"""

    def test_sanitize_json_file(self, temp_session_dir):
        """测试脱敏 JSON 文件"""
        # 创建带敏感路径的 JSON 文件
        source_file = temp_session_dir / "source.json"
        source_file.write_text(json.dumps({
            "path": "/Users/testuser/Documents/data.json"
        }))
        
        output_file = temp_session_dir / "sanitized.json"
        
        _sanitize_path_in_file(source_file, output_file)
        
        content = output_file.read_text()
        assert "testuser" not in content
        assert "***" in content

    def test_sanitize_text_file(self, temp_session_dir):
        """测试脱敏文本文件"""
        source_file = temp_session_dir / "source.txt"
        source_file.write_text("Log entry: /Users/heng/project\nAnother: /home/user/data")
        
        output_file = temp_session_dir / "sanitized.txt"
        
        _sanitize_path_in_file(source_file, output_file)
        
        content = output_file.read_text()
        assert "heng" not in content
        assert "user" not in content
        assert "***" in content

    def test_copy_binary_file(self, temp_session_dir):
        """测试复制二进制文件"""
        source_file = temp_session_dir / "source.bin"
        source_file.write_bytes(b"\x00\x01\x02\x03\x04")
        
        output_file = temp_session_dir / "copied.bin"
        
        _sanitize_path_in_file(source_file, output_file)
        
        assert output_file.exists()
        assert output_file.read_bytes() == source_file.read_bytes()


class TestExportOptions:
    """导出选项测试"""

    def test_get_export_options(self):
        """测试获取导出选项"""
        options = get_export_options()
        
        assert isinstance(options, dict)
        assert "logs" in options
        assert "environment" in options
        assert "argyll_output" in options

    def test_export_options_descriptions(self):
        """测试导出选项描述"""
        options = get_export_options()
        
        assert "Session logs" in options["logs"]
        assert "Environment info" in options["environment"]

    def test_create_collector(self):
        """测试创建收集器"""
        collector = create_collector("factory-test")
        
        assert collector is not None
        assert isinstance(collector, DiagnosticsCollector)
        assert collector.session_id == "factory-test"

    def test_create_collector_auto_id(self):
        """测试创建收集器自动 ID"""
        collector = create_collector()
        
        assert collector.session_id is not None


class TestPrivateExtensions:
    """隐私扩展名测试"""

    def test_private_extensions_set(self):
        """测试隐私扩展名集合"""
        assert ".icc" in PRIVATE_EXTENSIONS
        assert ".icm" in PRIVATE_EXTENSIONS
        assert ".cal" in PRIVATE_EXTENSIONS

    def test_non_private_extensions(self):
        """测试非隐私扩展名"""
        assert ".json" not in PRIVATE_EXTENSIONS
        assert ".ti3" not in PRIVATE_EXTENSIONS
        assert ".log" not in PRIVATE_EXTENSIONS


class TestCollectSessionLogs:
    """日志文件收集测试"""

    def test_collect_logs_from_existing_dir(self, temp_session_dir):
        """测试从现有目录收集日志"""
        log_dir = temp_session_dir / "measurements" / "logs"
        date_dir = log_dir / "2026-05-19"
        date_dir.mkdir(parents=True)
        
        log_file = date_dir / "test-session.log"
        log_file.write_text("Log content")
        
        # Mock log_dir 路径
        with patch("src.diagnostics.diagnostics.Path") as mock_path:
            mock_path.return_value = log_dir.parent
            logs = _collect_session_logs("test-session")
            
            # 验证收集逻辑
            assert isinstance(logs, list)

    def test_collect_logs_empty_dir(self):
        """测试空目录收集日志"""
        with patch("pathlib.Path.exists", return_value=False):
            logs = _collect_session_logs("nonexistent")
            
            assert logs == []


class TestDiagnosticsVersion:
    """诊断包版本测试"""

    def test_version_format(self):
        """测试版本格式"""
        assert DIAGNOSTICS_VERSION == "1.0"

    def test_pack_version_matches(self):
        """测试诊断包版本匹配"""
        pack = DiagnosticsPack()
        
        assert pack.version == DIAGNOSTICS_VERSION
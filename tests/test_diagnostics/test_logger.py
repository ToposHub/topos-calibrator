"""
Test Logger Module - 日志系统单元测试

测试 SessionLogger 和相关功能：
- 日志初始化
- 会话日志文件创建
- 日志级别设置
- 路径脱敏
"""

import logging
import os
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.diagnostics.logger import (
    SessionLogger,
    LogSession,
    LogAdapter,
    get_logger,
    init_session_logger,
    get_session_logger,
    close_session_logger,
    set_log_level,
    create_module_logger,
    SENSITIVE_PATH_PATTERNS,
    LOG_LEVELS,
)


class TestSessionLogger:
    """SessionLogger 单例测试"""

    def test_singleton_pattern(self):
        """测试 SessionLogger 是单例"""
        logger1 = SessionLogger()
        logger2 = SessionLogger()
        assert logger1 is logger2

    def test_init_creates_sessions_dict(self):
        """测试初始化创建会话字典"""
        logger = SessionLogger()
        assert hasattr(logger, '_sessions')
        assert isinstance(logger._sessions, dict)

    def test_set_log_dir(self, temp_session_dir):
        """测试设置日志目录"""
        logger = SessionLogger()
        logger.set_log_dir(temp_session_dir / "logs")
        log_dir = logger.get_log_dir()
        assert log_dir == temp_session_dir / "logs"
        assert log_dir.exists()

    def test_init_session(self, temp_session_dir):
        """测试初始化会话日志"""
        logger = SessionLogger()
        logger.set_log_dir(temp_session_dir / "logs")
        
        session_id = logger.init_session("test-session-001")
        
        assert session_id == "test-session-001"
        assert session_id in logger._sessions
        assert logger._current_session_id == session_id
        
        # 检查日志文件是否创建
        session = logger._sessions[session_id]
        assert session.log_file.exists()
        assert session.log_file.name == f"{session_id}.log"

    def test_init_session_auto_id(self, temp_session_dir):
        """测试自动生成会话 ID"""
        logger = SessionLogger()
        logger.set_log_dir(temp_session_dir / "logs")
        
        session_id = logger.init_session()
        
        assert session_id is not None
        assert session_id in logger._sessions
        # 验证格式：YYYYMMDD-HHMMSS
        assert len(session_id) >= 15  # 至少 YYYYMMDD-HHMMSS 格式

    def test_close_session(self, temp_session_dir):
        """测试关闭会话日志"""
        logger = SessionLogger()
        logger.set_log_dir(temp_session_dir / "logs")
        
        session_id = logger.init_session("test-close-session")
        assert session_id in logger._sessions
        
        logger.close_session(session_id)
        
        assert session_id not in logger._sessions
        assert logger._current_session_id is None

    def test_close_current_session(self, temp_session_dir):
        """测试关闭当前会话"""
        logger = SessionLogger()
        logger.set_log_dir(temp_session_dir / "logs")
        
        session_id = logger.init_session("current-session")
        logger.close_session()  # 不指定 ID，关闭当前会话
        
        assert session_id not in logger._sessions

    def test_get_logger_for_session(self, temp_session_dir):
        """测试获取会话日志器"""
        logger = SessionLogger()
        logger.set_log_dir(temp_session_dir / "logs")
        
        session_id = logger.init_session("logger-test")
        session_logger = logger.get_logger()
        
        assert session_logger is not None
        assert isinstance(session_logger, logging.Logger)
        assert "session" in session_logger.name

    def test_get_logger_with_name(self, temp_session_dir):
        """测试获取命名日志器"""
        logger = SessionLogger()
        
        named_logger = logger.get_logger("module.test")
        
        assert named_logger is not None
        assert named_logger.name == "topos.module.test"

    def test_set_level(self, temp_session_dir):
        """测试设置日志级别"""
        logger = SessionLogger()
        logger.set_log_dir(temp_session_dir / "logs")
        
        session_id = logger.init_session("level-test")
        
        logger.set_level("DEBUG")
        session_logger = logger._sessions[session_id].logger
        assert session_logger.level == logging.DEBUG
        
        logger.set_level("WARNING")
        assert session_logger.level == logging.WARNING

    def test_log_exception(self, temp_session_dir):
        """测试记录异常"""
        logger = SessionLogger()
        logger.set_log_dir(temp_session_dir / "logs")
        
        session_id = logger.init_session("exception-test")
        
        try:
            raise ValueError("Test exception")
        except Exception as e:
            logger.log_exception(e, {"context": "test"})
        
        # 验证日志文件包含异常信息
        session = logger._sessions[session_id]
        log_content = session.log_file.read_text()
        assert "ValueError" in log_content
        assert "Test exception" in log_content

    def test_get_session_log_file(self, temp_session_dir):
        """测试获取会话日志文件路径"""
        logger = SessionLogger()
        logger.set_log_dir(temp_session_dir / "logs")
        
        session_id = logger.init_session("log-file-test")
        
        log_file = logger.get_session_log_file(session_id)
        
        assert log_file is not None
        assert log_file.exists()
        assert log_file.name == f"{session_id}.log"


class TestPathSanitization:
    """路径脱敏测试"""

    def test_sanitize_users_path(self):
        """测试脱敏 /Users/ 路径"""
        logger = SessionLogger()
        
        path = "/Users/heng/Documents/test.txt"
        sanitized = logger._sanitize_path(path)
        
        assert "/Users/" in sanitized
        assert "heng" not in sanitized
        assert "***" in sanitized

    def test_sanitize_home_path(self):
        """测试脱敏 /home/ 路径"""
        logger = SessionLogger()
        
        path = "/home/user/Documents/test.txt"
        sanitized = logger._sanitize_path(path)
        
        assert "/home/" in sanitized
        assert "user" not in sanitized
        assert "***" in sanitized

    def test_sanitize_windows_path(self):
        """测试脱敏 Windows 路径"""
        logger = SessionLogger()
        
        path = "C:\\Users\\John\\Documents\\test.txt"
        sanitized = logger._sanitize_path(path)
        
        assert "Users" in sanitized
        assert "John" not in sanitized

    def test_sanitize_dict(self):
        """测试脱敏字典中的路径"""
        logger = SessionLogger()
        
        data = {
            "path": "/Users/heng/test.txt",
            "nested": {
                "inner_path": "/home/user/data.json"
            },
            "list_paths": [
                "/Users/heng/file1.txt",
                "/home/user/file2.txt"
            ]
        }
        
        sanitized = logger._sanitize_dict(data)
        
        assert "heng" not in sanitized["path"]
        assert "user" not in sanitized["nested"]["inner_path"]
        assert "heng" not in sanitized["list_paths"][0]
        assert "user" not in sanitized["list_paths"][1]

    def test_preserve_non_sensitive_paths(self):
        """测试保留非敏感路径"""
        logger = SessionLogger()
        
        path = "/usr/local/bin/python"
        sanitized = logger._sanitize_path(path)
        
        assert sanitized == path


class TestGlobalFunctions:
    """全局函数测试"""

    def test_get_logger_creates_manager(self):
        """测试 get_logger 创建管理器"""
        # 重置全局管理器
        import src.diagnostics.logger as logger_module
        logger_module._logger_manager = None
        
        logger = get_logger()
        
        assert logger is not None
        assert isinstance(logger, logging.Logger)

    def test_init_session_logger(self, temp_session_dir):
        """测试 init_session_logger 全局函数"""
        import src.diagnostics.logger as logger_module
        logger_module._logger_manager = None
        
        session_id = init_session_logger("global-test", log_dir=temp_session_dir / "logs")
        
        assert session_id == "global-test"
        
        # 验证日志文件创建
        log_file = logger_module._logger_manager.get_session_log_file(session_id)
        assert log_file is not None

    def test_get_session_logger(self):
        """测试 get_session_logger 全局函数"""
        import src.diagnostics.logger as logger_module
        logger_module._logger_manager = None
        
        init_session_logger("session-logger-test")
        logger = get_session_logger()
        
        assert logger is not None

    def test_close_session_logger(self):
        """测试 close_session_logger 全局函数"""
        import src.diagnostics.logger as logger_module
        logger_module._logger_manager = None
        
        session_id = init_session_logger("close-test")
        close_session_logger(session_id)
        
        # 验证会话已关闭
        assert session_id not in logger_module._logger_manager._sessions

    def test_set_log_level_global(self):
        """测试 set_log_level 全局函数"""
        import src.diagnostics.logger as logger_module
        logger_module._logger_manager = None
        
        init_session_logger("level-global-test")
        set_log_level("DEBUG")
        
        assert logger_module._logger_manager._log_level == logging.DEBUG


class TestLogAdapter:
    """LogAdapter 测试"""

    def test_create_module_logger(self):
        """测试创建模块日志器"""
        adapter = create_module_logger("test_module")
        
        assert adapter is not None
        assert isinstance(adapter, LogAdapter)
        assert adapter._name == "test_module"

    def test_log_adapter_methods(self, temp_session_dir):
        """测试 LogAdapter 各级别方法"""
        import src.diagnostics.logger as logger_module
        logger_module._logger_manager = None
        
        init_session_logger("adapter-test", log_dir=temp_session_dir / "logs")
        
        adapter = create_module_logger("test.module")
        
        # 各级别日志
        adapter.debug("Debug message")
        adapter.info("Info message")
        adapter.warning("Warning message")
        adapter.error("Error message")
        adapter.critical("Critical message")

    def test_log_adapter_exception(self, temp_session_dir):
        """测试 LogAdapter exception 方法"""
        import src.diagnostics.logger as logger_module
        logger_module._logger_manager = None
        
        init_session_logger("adapter-exception-test", log_dir=temp_session_dir / "logs")
        
        adapter = create_module_logger("test.exception")
        
        try:
            raise RuntimeError("Test error")
        except Exception:
            adapter.exception("Exception occurred")


class TestLogLevels:
    """日志级别测试"""

    def test_log_levels_mapping(self):
        """测试日志级别映射"""
        assert LOG_LEVELS["DEBUG"] == logging.DEBUG
        assert LOG_LEVELS["INFO"] == logging.INFO
        assert LOG_LEVELS["WARNING"] == logging.WARNING
        assert LOG_LEVELS["ERROR"] == logging.ERROR
        assert LOG_LEVELS["CRITICAL"] == logging.CRITICAL

    def test_invalid_log_level(self):
        """测试无效日志级别"""
        logger = SessionLogger()
        
        # 无效级别应该被忽略
        original_level = logger._log_level
        logger.set_level("INVALID")
        
        # 级别不变
        assert logger._log_level == original_level


class TestConcurrentSessions:
    """并发会话测试"""

    def test_multiple_sessions(self, temp_session_dir):
        """测试多个并发会话"""
        logger = SessionLogger()
        logger.set_log_dir(temp_session_dir / "logs")
        
        session1 = logger.init_session("concurrent-1")
        session2 = logger.init_session("concurrent-2")
        
        assert session1 in logger._sessions
        assert session2 in logger._sessions
        
        # 当前会话应该是最后一个
        assert logger._current_session_id == session2

    def test_thread_safety(self, temp_session_dir):
        """测试线程安全"""
        logger = SessionLogger()
        logger.set_log_dir(temp_session_dir / "logs")
        
        results = []
        
        def create_session(i):
            session_id = logger.init_session(f"thread-{i}")
            results.append(session_id)
        
        threads = [
            threading.Thread(target=create_session, args=(i,))
            for i in range(5)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # 验证所有会话创建成功
        assert len(results) == 5
        for session_id in results:
            assert session_id in logger._sessions
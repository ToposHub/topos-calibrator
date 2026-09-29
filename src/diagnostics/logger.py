"""
Logger Module - 统一日志系统

提供基于 Python logging 的会话级日志管理，支持：
- 每个 session 单独日志文件
- 可配置日志级别
- 隐私保护（敏感路径脱敏）
- 统一格式化
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import json
import threading
import traceback


# 日志格式
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 默认日志目录
DEFAULT_LOG_DIR = "logs"

# 敏感路径模式（需要脱敏）
SENSITIVE_PATH_PATTERNS = [
    "/Users/",
    "/home/",
    "/Users",
    "/home",
    "C:\\Users\\",
    "C:\\Documents and Settings\\",
]

# 日志级别映射
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


@dataclass
class LogSession:
    """日志会话信息"""
    session_id: str
    log_file: Path
    logger: logging.Logger
    created_at: datetime = field(default_factory=datetime.now)
    handlers: List[logging.Handler] = field(default_factory=list)


class SessionLogger:
    """
    会话级日志管理器

    每个 session 有独立的日志文件，同时支持全局日志配置。
    """

    _instance: Optional['SessionLogger'] = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化日志管理器"""
        if self._initialized:
            return

        self._sessions: Dict[str, LogSession] = {}
        self._current_session_id: Optional[str] = None
        self._log_level = logging.INFO
        self._log_dir: Optional[Path] = None
        self._initialized = True

        # 配置根日志器
        self._configure_root_logger()

    def _configure_root_logger(self):
        """配置根日志器"""
        # 设置根日志级别
        logging.getLogger().setLevel(logging.DEBUG)

        # 防止日志传播到根日志器（避免重复输出）
        logging.getLogger('topos').propagate = False

    def set_log_dir(self, log_dir: Optional[Path] = None):
        """
        设置日志目录

        Args:
            log_dir: 日志目录路径，None 则使用默认目录
        """
        if log_dir:
            self._log_dir = Path(log_dir)
        else:
            # 使用 measurements 目录下的 logs 子目录
            self._log_dir = Path("measurements") / DEFAULT_LOG_DIR

        # 确保目录存在
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def get_log_dir(self) -> Path:
        """获取日志目录"""
        if self._log_dir is None:
            self.set_log_dir()
        return self._log_dir

    def init_session(self, session_id: Optional[str] = None) -> str:
        """
        初始化会话日志

        Args:
            session_id: 会话 ID，None 则自动生成

        Returns:
            会话 ID
        """
        if session_id is None:
            session_id = datetime.now().strftime("%Y%m%d-%H%M%S")

        if session_id in self._sessions:
            return session_id

        # 创建会话日志器
        logger_name = f"topos.session.{session_id}"
        logger = logging.getLogger(logger_name)
        logger.setLevel(self._log_level)

        # 创建日志文件
        log_dir = self.get_log_dir()
        date_dir = log_dir / datetime.now().strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        log_file = date_dir / f"{session_id}.log"

        # 创建文件处理器
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))

        # 创建控制台处理器（仅 WARNING 及以上）
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))

        # 添加处理器
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        # 记录会话信息
        self._sessions[session_id] = LogSession(
            session_id=session_id,
            log_file=log_file,
            logger=logger,
            handlers=[file_handler, console_handler]
        )

        # 设置为当前会话
        self._current_session_id = session_id

        # 记录会话开始
        logger.info(f"Session started: {session_id}")
        logger.info(f"Log file: {log_file}")

        return session_id

    def close_session(self, session_id: Optional[str] = None):
        """
        关闭会话日志

        Args:
            session_id: 会话 ID，None 则关闭当前会话
        """
        if session_id is None:
            session_id = self._current_session_id

        if session_id is None:
            return

        if session_id not in self._sessions:
            return

        session = self._sessions[session_id]

        # 记录会话结束
        session.logger.info(f"Session ended: {session_id}")

        # 移除处理器
        for handler in session.handlers:
            handler.close()
            session.logger.removeHandler(handler)

        # 删除会话
        del self._sessions[session_id]

        if self._current_session_id == session_id:
            self._current_session_id = None

    def get_logger(self, name: Optional[str] = None) -> logging.Logger:
        """
        获取日志器

        Args:
            name: 日志器名称，None 则返回当前会话日志器

        Returns:
            日志器实例
        """
        if name:
            # 获取命名日志器
            logger = logging.getLogger(f"topos.{name}")
            logger.setLevel(self._log_level)
            return logger

        # 返回当前会话日志器
        if self._current_session_id and self._current_session_id in self._sessions:
            return self._sessions[self._current_session_id].logger

        # 返回默认日志器
        logger = logging.getLogger("topos")
        logger.setLevel(self._log_level)
        return logger

    def get_session_log_file(self, session_id: Optional[str] = None) -> Optional[Path]:
        """
        获取会话日志文件路径

        Args:
            session_id: 会话 ID，None 则返回当前会话

        Returns:
            日志文件路径
        """
        if session_id is None:
            session_id = self._current_session_id

        if session_id and session_id in self._sessions:
            return self._sessions[session_id].log_file

        return None

    def set_level(self, level: str):
        """
        设置日志级别

        Args:
            level: 日志级别字符串 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        if level.upper() in LOG_LEVELS:
            self._log_level = LOG_LEVELS[level.upper()]

            # 更新所有会话日志器
            for session in self._sessions.values():
                session.logger.setLevel(self._log_level)

    def get_all_session_logs(self) -> Dict[str, Path]:
        """
        获取所有会话日志文件

        Returns:
            会话 ID -> 日志文件路径 的映射
        """
        return {sid: session.log_file for sid, session in self._sessions.items()}

    def log_exception(self, exc: Exception, context: Optional[Dict[str, Any]] = None):
        """
        记录异常

        Args:
            exc: 异常实例
            context: 上下文信息
        """
        logger = self.get_logger()

        # 获取完整的异常堆栈
        exc_type, exc_value, exc_tb = sys.exc_info()
        tb_str = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))

        logger.error(f"Exception occurred: {type(exc).__name__}: {exc}")
        logger.debug(f"Traceback:\n{tb_str}")

        if context:
            # 脱敏上下文信息
            safe_context = self._sanitize_dict(context)
            logger.debug(f"Context: {json.dumps(safe_context, ensure_ascii=False)}")

    def _sanitize_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        脱敏字典中的敏感路径

        Args:
            data: 原始字典

        Returns:
            脱敏后的字典
        """
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self._sanitize_path(value)
            elif isinstance(value, dict):
                result[key] = self._sanitize_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    self._sanitize_path(v) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                result[key] = value
        return result

    def _sanitize_path(self, path: str) -> str:
        """
        脱敏路径中的用户名

        Args:
            path: 原始路径

        Returns:
            脱敏后的路径
        """
        import re

        for pattern in SENSITIVE_PATH_PATTERNS:
            if pattern in path:
                # 替换用户名为 ***
                if pattern.startswith("/Users/"):
                    path = re.sub(r'/Users/[^/]+', '/Users/***', path)
                elif pattern.startswith("/home/"):
                    path = re.sub(r'/home/[^/]+', '/home/***', path)
                elif "Users" in pattern:
                    path = re.sub(r'Users\\[^\\]+', 'Users\\***', path)

        return path


# 全局日志管理器实例
_logger_manager: Optional[SessionLogger] = None


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    获取日志器（全局函数）

    Args:
        name: 日志器名称

    Returns:
        日志器实例
    """
    global _logger_manager
    if _logger_manager is None:
        _logger_manager = SessionLogger()
    return _logger_manager.get_logger(name)


def init_session_logger(session_id: Optional[str] = None,
                        log_dir: Optional[Path] = None) -> str:
    """
    初始化会话日志（全局函数）

    Args:
        session_id: 会话 ID
        log_dir: 日志目录

    Returns:
        会话 ID
    """
    global _logger_manager
    if _logger_manager is None:
        _logger_manager = SessionLogger()

    if log_dir:
        _logger_manager.set_log_dir(log_dir)

    return _logger_manager.init_session(session_id)


def get_session_logger() -> logging.Logger:
    """
    获取当前会话日志器（全局函数）

    Returns:
        当前会话日志器
    """
    global _logger_manager
    if _logger_manager is None:
        _logger_manager = SessionLogger()
    return _logger_manager.get_logger()


def close_session_logger(session_id: Optional[str] = None):
    """
    关闭会话日志（全局函数）

    Args:
        session_id: 会话 ID
    """
    global _logger_manager
    if _logger_manager:
        _logger_manager.close_session(session_id)


def set_log_level(level: str):
    """
    设置日志级别（全局函数）

    Args:
        level: 日志级别字符串
    """
    global _logger_manager
    if _logger_manager is None:
        _logger_manager = SessionLogger()
    _logger_manager.set_level(level)


class LogAdapter:
    """
    日志适配器

    用于在模块中创建带名称的日志器，便于追踪日志来源。
    """

    def __init__(self, name: str):
        """
        初始化日志适配器

        Args:
            name: 模块名称
        """
        self._name = name
        self._logger: Optional[logging.Logger] = None

    def _get_logger(self) -> logging.Logger:
        """获取或创建日志器"""
        if self._logger is None:
            self._logger = get_logger(self._name)
        return self._logger

    def debug(self, msg: str, *args, **kwargs):
        """记录 DEBUG 级别日志"""
        self._get_logger().debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        """记录 INFO 级别日志"""
        self._get_logger().info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """记录 WARNING 级别日志"""
        self._get_logger().warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        """记录 ERROR 级别日志"""
        self._get_logger().error(msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        """记录 CRITICAL 级别日志"""
        self._get_logger().critical(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        """记录异常日志"""
        self._get_logger().exception(msg, *args, **kwargs)


def create_module_logger(module_name: str) -> LogAdapter:
    """
    创建模块日志器

    Args:
        module_name: 模块名称

    Returns:
        日志适配器
    """
    return LogAdapter(module_name)
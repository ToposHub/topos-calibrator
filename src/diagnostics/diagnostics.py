"""
Diagnostics Module - 诊断包生成

提供一键导出诊断包功能，包含：
- manifest.json
- session 日志
- 环境信息
- Argyll 输出文件
- 异常栈
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import traceback
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Set

from .logger import SessionLogger, get_session_logger, get_logger


# 诊断包版本
DIAGNOSTICS_VERSION = "1.0"

# 默认诊断包目录名
DIAGNOSTICS_DIR = "diagnostics"

# 敏感路径模式（需要脱敏）
SENSITIVE_PATTERNS = [
    "/Users/",
    "/home/",
    "C:\\Users\\",
    "C:\\Documents and Settings\\",
]

# 隐私敏感的文件扩展名（默认不包含）
PRIVATE_EXTENSIONS = {
    ".icc", ".icm",  # ICC profiles 可能包含显示器信息
    ".cal",  # CAL 文件可能包含硬件配置
}

# 用户可选择的导出内容选项
EXPORT_OPTIONS = {
    "logs": "Session logs",
    "environment": "Environment info (OS, Python, Argyll version)",
    "argyll_output": "Argyll output files (.ti3, .ti1, .log)",
    "measurements": "Measurement data files (.json)",
    "manifests": "Session manifests (manifest.json)",
    "exceptions": "Exception stack traces",
    "icc_profiles": "ICC profile files (may contain display info)",
    "cal_files": "CAL files (may contain hardware config)",
}


@dataclass
class EnvironmentInfo:
    """环境信息"""
    os_name: str = ""
    os_version: str = ""
    os_release: str = ""
    python_version: str = ""
    python_executable: str = ""
    python_path: List[str] = field(default_factory=list)
    argyll_version: str = ""
    argyll_path: str = ""
    display_info: List[Dict[str, Any]] = field(default_factory=list)
    app_version: str = "0.1.0-preview"
    timestamp: str = ""

    def __post_init__(self):
        """自动填充环境信息"""
        if not self.os_name:
            self.os_name = platform.system()
        if not self.os_version:
            self.os_version = platform.version()
        if not self.os_release:
            self.os_release = platform.release()
        if not self.python_version:
            self.python_version = platform.python_version()
        if not self.python_executable:
            self.python_executable = sys.executable
        if not self.python_path:
            self.python_path = sys.path.copy()
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        # 脱敏 Python 可执行路径
        data["python_executable"] = self._sanitize_path(data["python_executable"])
        data["python_path"] = [self._sanitize_path(p) for p in data["python_path"]]
        return data

    def _sanitize_path(self, path: str) -> str:
        """脱敏路径"""
        import re
        for pattern in SENSITIVE_PATTERNS:
            if pattern in path:
                if pattern.startswith("/Users/"):
                    path = re.sub(r'/Users/[^/]+', '/Users/***', path)
                elif pattern.startswith("/home/"):
                    path = re.sub(r'/home/[^/]+', '/home/***', path)
                elif "Users" in pattern:
                    path = re.sub(r'Users\\[^\\]+', 'Users\\***', path)
        return path


@dataclass
class ExceptionRecord:
    """异常记录"""
    timestamp: str = ""
    exception_type: str = ""
    exception_message: str = ""
    traceback: str = ""
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class DiagnosticsPack:
    """诊断包结构"""
    version: str = DIAGNOSTICS_VERSION
    session_id: str = ""
    created_at: str = ""
    environment: Optional[EnvironmentInfo] = None
    exceptions: List[ExceptionRecord] = field(default_factory=list)
    included_files: List[str] = field(default_factory=list)
    export_options: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "version": self.version,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "environment": self.environment.to_dict() if self.environment else None,
            "exceptions": [e.to_dict() for e in self.exceptions],
            "included_files": self.included_files,
            "export_options": self.export_options,
        }


class DiagnosticsCollector:
    """
    诊断信息收集器

    收集环境信息、异常记录、文件列表等，用于生成诊断包。
    """

    def __init__(self, session_id: Optional[str] = None):
        """
        初始化收集器

        Args:
            session_id: 会话 ID
        """
        self.session_id = session_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        self.exceptions: List[ExceptionRecord] = []
        self._environment: Optional[EnvironmentInfo] = None
        self._argyll_detected = False

    def _sanitize_path(self, path: str) -> str:
        """
        脱敏路径中的用户名

        Args:
            path: 原始路径

        Returns:
            脱敏后的路径
        """
        import re

        if not path:
            return ""

        for pattern in SENSITIVE_PATTERNS:
            if pattern in path:
                # 替换用户名为 ***
                if pattern.startswith("/Users/"):
                    path = re.sub(r'/Users/[^/]+', '/Users/***', path)
                elif pattern.startswith("/home/"):
                    path = re.sub(r'/home/[^/]+', '/home/***', path)
                elif "Users" in pattern:
                    path = re.sub(r'Users\\[^\\]+', 'Users\\***', path)

        return path

    def collect_environment(self) -> EnvironmentInfo:
        """
        收集环境信息

        Returns:
            环境信息对象
        """
        env = EnvironmentInfo()

        # 检测 ArgyllCMS
        argyll_version, argyll_path = self._detect_argyll()
        env.argyll_version = argyll_version
        env.argyll_path = self._sanitize_path(argyll_path)

        # 收集显示器信息
        env.display_info = self._collect_display_info()

        self._environment = env
        return env

    def _detect_argyll(self) -> tuple:
        """
        检测 ArgyllCMS 版本和路径

        Returns:
            (version, path) 元组
        """
        try:
            # 尝试运行 dispwin -v 获取版本
            result = subprocess.run(
                ["dispwin", "-v"],
                capture_output=True,
                text=True,
                timeout=5
            )

            output = result.stdout + result.stderr
            version = ""
            path = ""

            # 解析版本信息
            for line in output.split('\n'):
                if "version" in line.lower():
                    # 提取版本号
                    import re
                    match = re.search(r'version\s+([\d.]+)', line, re.IGNORECASE)
                    if match:
                        version = match.group(1)
                if "located at" in line.lower() or "path" in line.lower():
                    # 提取路径
                    parts = line.split(':')
                    if len(parts) > 1:
                        path = parts[-1].strip()

            # 尝试获取 dispwin 的实际路径
            if not path:
                try:
                    which_result = subprocess.run(
                        ["which", "dispwin"] if platform.system() != "Windows" else ["where", "dispwin"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if which_result.returncode == 0:
                        path = which_result.stdout.strip().split('\n')[0]
                except Exception:
                    pass

            self._argyll_detected = bool(version)
            return version, path

        except FileNotFoundError:
            return "", ""
        except subprocess.TimeoutExpired:
            return "", ""
        except Exception as e:
            get_logger("diagnostics").warning(f"Error detecting ArgyllCMS: {e}")
            return "", ""

    def _collect_display_info(self) -> List[Dict[str, Any]]:
        """
        收集显示器信息（仅收集非敏感信息）

        Returns:
            显示器信息列表
        """
        displays = []

        try:
            # 尝试使用 dispwin -d 获取显示器列表
            result = subprocess.run(
                ["dispwin", "-d"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                output = result.stdout
                for line in output.split('\n'):
                    if line.strip() and not line.startswith('Usage'):
                        # 解析显示器信息，但不包含序列号等敏感信息
                        display = {
                            "description": line.strip(),
                            "index": len(displays),
                        }
                        displays.append(display)

        except Exception:
            # 如果无法获取显示器信息，返回空列表
            pass

        return displays

    def record_exception(self, exc: Exception, context: Optional[Dict[str, Any]] = None) -> ExceptionRecord:
        """
        记录异常

        Args:
            exc: 异常实例
            context: 上下文信息

        Returns:
            异常记录
        """
        exc_type, exc_value, exc_tb = sys.exc_info()
        tb_str = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))

        record = ExceptionRecord(
            timestamp=datetime.now().isoformat(),
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            traceback=tb_str,
            context=context or {}
        )

        self.exceptions.append(record)
        return record

    def get_environment(self) -> Optional[EnvironmentInfo]:
        """获取已收集的环境信息"""
        if self._environment is None:
            self.collect_environment()
        return self._environment


def _sanitize_path_in_file(file_path: Path, output_path: Path):
    """
    处理文件中的敏感路径

    Args:
        file_path: 原始文件路径
        output_path: 输出文件路径
    """
    import re

    try:
        # 检查是否是文本文件
        if file_path.suffix in {'.json', '.txt', '.log', '.ti1', '.ti3', '.cal'}:
            content = file_path.read_text(encoding='utf-8', errors='ignore')

            # 脱敏路径
            content = re.sub(r'/Users/[^/\s]+', '/Users/***', content)
            content = re.sub(r'/home/[^/\s]+', '/home/***', content)
            content = re.sub(r'Users\\[^\\\s]+', 'Users\\***', content)

            output_path.write_text(content, encoding='utf-8')
        else:
            # 二进制文件直接复制
            shutil.copy2(file_path, output_path)

    except Exception as e:
        get_logger("diagnostics").warning(f"Error processing file {file_path}: {e}")
        # 出错时仍然复制文件
        shutil.copy2(file_path, output_path)


def export_diagnostics_pack(
    session_id: Optional[str] = None,
    session_dir: Optional[Path] = None,
    output_path: Optional[Path] = None,
    options: Optional[Set[str]] = None,
    include_private: bool = False,
    collector: Optional[DiagnosticsCollector] = None,
) -> Path:
    """
    导出诊断包

    Args:
        session_id: 会话 ID
        session_dir: 会话目录（包含日志、测量数据等）
        output_path: 输出路径，None 则自动生成
        options: 导出选项集合，None 则导出全部非隐私内容
        include_private: 是否包含隐私敏感文件（ICC、CAL）
        collector: 诊断收集器实例

    Returns:
        诊断包 ZIP 文件路径
    """
    if session_id is None:
        session_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    if options is None:
        # 默认导出非隐私内容
        options = {"logs", "environment", "argyll_output", "measurements", "manifests", "exceptions"}

    if collector is None:
        collector = DiagnosticsCollector(session_id)

    # 收集环境信息
    if "environment" in options:
        collector.collect_environment()

    # 创建诊断包结构
    pack = DiagnosticsPack(
        session_id=session_id,
        created_at=datetime.now().isoformat(),
        environment=collector.get_environment(),
        exceptions=collector.exceptions.copy(),
        export_options=list(options)
    )

    # 确定输出路径
    if output_path is None:
        output_dir = Path("measurements") / DIAGNOSTICS_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"diagnostics_{session_id}.zip"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    # 创建临时目录
    temp_dir = Path(output_path).parent / f"_temp_diagnostics_{session_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 收集日志文件
        if "logs" in options:
            log_files = _collect_session_logs(session_id)
            for log_file in log_files:
                dest = temp_dir / "logs" / log_file.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                _sanitize_path_in_file(log_file, dest)
                pack.included_files.append(f"logs/{log_file.name}")

        # 收集会话目录中的文件
        if session_dir and session_dir.exists():
            _collect_session_files(
                session_dir, temp_dir, pack,
                options, include_private
            )

        # 写入 manifest（在收集完所有文件后）
        pack.included_files.append("diagnostics_manifest.json")
        manifest_path = temp_dir / "diagnostics_manifest.json"
        manifest_path.write_text(
            json.dumps(pack.to_dict(), indent=2, ensure_ascii=False),
            encoding='utf-8'
        )

        # 创建 ZIP 文件
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path in temp_dir.rglob('*'):
                if file_path.is_file():
                    arcname = file_path.relative_to(temp_dir)
                    zf.write(file_path, arcname)

    finally:
        # 清理临时目录
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    return output_path


def _collect_session_logs(session_id: str) -> List[Path]:
    """
    收集会话日志文件

    Args:
        session_id: 会话 ID

    Returns:
        日志文件路径列表
    """
    log_files = []
    log_dir = Path("measurements") / "logs"

    if not log_dir.exists():
        return log_files

    # 查找匹配的日志文件
    for date_dir in log_dir.iterdir():
        if date_dir.is_dir():
            for log_file in date_dir.glob(f"{session_id}*.log"):
                log_files.append(log_file)
            # 也收集同一天的其他日志
            for log_file in date_dir.glob("*.log"):
                if log_file not in log_files:
                    log_files.append(log_file)

    return log_files


def _collect_session_files(
    session_dir: Path,
    temp_dir: Path,
    pack: DiagnosticsPack,
    options: Set[str],
    include_private: bool
):
    """
    收集会话目录中的文件

    Args:
        session_dir: 会话目录
        temp_dir: 临时目录
        pack: 诊断包
        options: 导出选项
        include_private: 是否包含隐私文件
    """
    # 文件类型映射
    file_type_map = {
        "argyll_output": {'.ti1', '.ti3', '.log'},
        "measurements": {'.json'},
        "manifests": {'manifest.json'},
        "icc_profiles": {'.icc', '.icm'},
        "cal_files": {'.cal'},
    }

    for file_path in session_dir.rglob('*'):
        if not file_path.is_file():
            continue

        suffix = file_path.suffix.lower()

        # 检查是否是隐私敏感文件
        if suffix in PRIVATE_EXTENSIONS and not include_private:
            continue

        # 确定目标子目录
        dest_subdir = None

        for option, extensions in file_type_map.items():
            if option in options and suffix in extensions:
                dest_subdir = option
                break

        if dest_subdir is None:
            dest_subdir = "other"

        # 复制文件
        dest = temp_dir / dest_subdir / file_path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        _sanitize_path_in_file(file_path, dest)
        pack.included_files.append(f"{dest_subdir}/{file_path.name}")


def get_export_options() -> Dict[str, str]:
    """
    获取可用的导出选项

    Returns:
        选项名称 -> 描述 的映射
    """
    return EXPORT_OPTIONS.copy()


def create_collector(session_id: Optional[str] = None) -> DiagnosticsCollector:
    """
    创建诊断收集器

    Args:
        session_id: 会话 ID

    Returns:
        诊断收集器实例
    """
    return DiagnosticsCollector(session_id)

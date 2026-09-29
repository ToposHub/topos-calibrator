"""
Manifest Module - Artifact Manifest 管理

每个 session 目录包含 manifest.json，记录所有 artifact 文件的信息。
提供验证和完整性检查功能。
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict

# Manifest schema 版本
MANIFEST_SCHEMA_VERSION = "1.0"


@dataclass
class ManifestEntry:
    """
    Manifest 文件条目
    
    记录单个 artifact 文件的完整信息。
    """
    type: str = ""  # measurement, ti3, cal, icc, lut, report
    filename: str = ""
    sha256: str = ""
    size_bytes: int = 0
    generated_at: str = ""
    generated_by: str = ""  # 生成命令或方法
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    def from_dict(self, data: Dict[str, Any]):
        """从字典加载"""
        self.type = data.get("type", "")
        self.filename = data.get("filename", "")
        self.sha256 = data.get("sha256", "")
        self.size_bytes = data.get("size_bytes", 0)
        self.generated_at = data.get("generated_at", "")
        self.generated_by = data.get("generated_by", "")
        self.parameters = data.get("parameters", {})


@dataclass
class ArtifactManifest:
    """
    Artifact Manifest
    
    每个 session 目录包含 manifest.json，记录所有文件信息。
    
    结构：
    {
        "schema_version": "1.0",
        "session_id": "...",
        "created_at": "...",
        "updated_at": "...",
        "storage_type": "auto_save",
        "date_dir": "2026-04-16",
        "files": [...],
        "workflow": {...},
        "instrument": {...},
        "display": {...},
        "checksums_validated": true,
        "integrity_status": "ok"
    }
    """
    schema_version: str = MANIFEST_SCHEMA_VERSION
    session_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    storage_type: str = ""  # auto_save, sessions
    date_dir: str = ""  # YYYY-MM-DD
    files: List[ManifestEntry] = field(default_factory=list)
    workflow: Dict[str, Any] = field(default_factory=dict)
    instrument: Dict[str, Any] = field(default_factory=dict)
    display: Dict[str, Any] = field(default_factory=dict)
    checksums_validated: bool = False
    integrity_status: str = "unknown"  # ok, warning, error
    integrity_errors: List[str] = field(default_factory=list)

    def add_file(self, entry: ManifestEntry):
        """添加文件条目"""
        self.files.append(entry)

    def remove_file(self, filename: str) -> bool:
        """移除文件条目"""
        for i, entry in enumerate(self.files):
            if entry.filename == filename:
                self.files.pop(i)
                return True
        return False

    def get_file(self, filename: str) -> Optional[ManifestEntry]:
        """获取指定文件条目"""
        for entry in self.files:
            if entry.filename == filename:
                return entry
        return None

    def get_files_by_type(self, file_type: str) -> List[ManifestEntry]:
        """获取指定类型的所有文件"""
        return [e for e in self.files if e.type == file_type]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "storage_type": self.storage_type,
            "date_dir": self.date_dir,
            "files": [e.to_dict() for e in self.files],
            "workflow": self.workflow,
            "instrument": self.instrument,
            "display": self.display,
            "checksums_validated": self.checksums_validated,
            "integrity_status": self.integrity_status,
            "integrity_errors": self.integrity_errors,
        }

    def to_json(self) -> str:
        """转换为 JSON"""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def from_dict(self, data: Dict[str, Any]):
        """从字典加载"""
        self.schema_version = data.get("schema_version", MANIFEST_SCHEMA_VERSION)
        self.session_id = data.get("session_id", "")
        self.created_at = data.get("created_at", "")
        self.updated_at = data.get("updated_at", "")
        self.storage_type = data.get("storage_type", "")
        self.date_dir = data.get("date_dir", "")
        self.workflow = data.get("workflow", {})
        self.instrument = data.get("instrument", {})
        self.display = data.get("display", {})
        self.checksums_validated = data.get("checksums_validated", False)
        self.integrity_status = data.get("integrity_status", "unknown")
        self.integrity_errors = data.get("integrity_errors", [])

        # 加载文件列表
        self.files = []
        for file_data in data.get("files", []):
            entry = ManifestEntry()
            entry.from_dict(file_data)
            self.files.append(entry)

    def from_json(self, json_str: str):
        """从 JSON 加载"""
        data = json.loads(json_str)
        self.from_dict(data)

    def update_timestamp(self):
        """更新时间戳"""
        self.updated_at = datetime.now().isoformat()

    def set_workflow_info(self, mode: str, target: str = "", status: str = "completed"):
        """设置工作流信息"""
        self.workflow = {
            "mode": mode,
            "target": target,
            "status": status,
        }

    def set_instrument_info(self, probe: str, correction_file: str = None):
        """设置仪器信息"""
        self.instrument = {
            "probe": probe,
            "correction_file": correction_file,
        }

    def set_display_info(self, model: str, display_name: str = "",
                         display_type: str = ""):
        """设置显示器信息"""
        self.display = {
            "model": model,
            "display_name": display_name,
            "type": display_type,
        }


def compute_file_hash(file_path: Path) -> str:
    """计算文件 SHA256 hash"""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_file_size(file_path: Path) -> int:
    """获取文件大小"""
    return file_path.stat().st_size


def generate_manifest(session_dir: Path, session_id: str = None,
                      workflow_info: Dict = None,
                      instrument_info: Dict = None,
                      display_info: Dict = None) -> ArtifactManifest:
    """
    为 session 目录生成 manifest
    
    Args:
        session_dir: session 目录路径
        session_id: session ID（可选，从目录名推断）
        workflow_info: 工作流信息（可选）
        instrument_info: 仪器信息（可选）
        display_info: 显示器信息（可选）
    
    Returns:
        ArtifactManifest: 生成的 manifest 对象
    """
    manifest = ArtifactManifest()
    manifest.created_at = datetime.now().isoformat()
    manifest.updated_at = manifest.created_at

    # 推断 session_id 和存储类型
    if session_id:
        manifest.session_id = session_id
    else:
        manifest.session_id = session_dir.name

    # 推断存储类型和日期目录
    parent_name = session_dir.parent.name
    if parent_name == "auto_save":
        manifest.storage_type = "auto_save"
        # 检查父目录是否是日期格式
        grandparent = session_dir.parent.parent
        if grandparent.name == "auto_save":
            manifest.date_dir = parent_name  # YYYY-MM-DD
    elif parent_name == "sessions":
        manifest.storage_type = "sessions"

    # 扫描目录中的文件
    supported_types = {
        ".json": "measurement",
        ".ti3": "ti3",
        ".cal": "cal",
        ".icc": "icc",
        ".icm": "icc",
        ".cube": "lut",
        ".3dl": "lut",
        ".html": "report",
        ".pdf": "report",
    }

    # 跳过 manifest.json 本身
    for file_path in session_dir.iterdir():
        if file_path.is_file() and file_path.name != "manifest.json":
            ext = file_path.suffix.lower()
            file_type = supported_types.get(ext, "unknown")

            if file_type != "unknown":
                entry = ManifestEntry(
                    type=file_type,
                    filename=file_path.name,
                    sha256=compute_file_hash(file_path),
                    size_bytes=compute_file_size(file_path),
                    generated_at=datetime.fromtimestamp(
                        file_path.stat().st_mtime
                    ).isoformat(),
                    generated_by="auto_scan",
                    parameters={}
                )
                manifest.add_file(entry)

    # 尝试从 JSON 文件读取更多信息
    json_files = [f for f in session_dir.glob("*.json") if f.name != "manifest.json"]
    if json_files:
        try:
            with open(json_files[0], 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 检查是否是 v1 格式
            if data.get("schema_version") == "1.0":
                # 从 v1 格式读取
                if not workflow_info:
                    wf = data.get("workflow", {})
                    manifest.set_workflow_info(
                        wf.get("mode", ""),
                        wf.get("target", ""),
                        "completed"
                    )
                if not instrument_info:
                    inst = data.get("instrument", {})
                    manifest.set_instrument_info(
                        inst.get("probe", ""),
                        inst.get("correction_file")
                    )
                if not display_info:
                    disp = data.get("display", {})
                    manifest.set_display_info(
                        disp.get("model", ""),
                        disp.get("display_name", ""),
                        disp.get("type", "")
                    )

            else:
                # 从旧格式读取
                metadata = data.get("metadata", {})
                if not workflow_info:
                    manifest.set_workflow_info(
                        metadata.get("measure_mode", ""),
                        "",
                        "completed"
                    )
                if not instrument_info:
                    manifest.set_instrument_info(
                        metadata.get("probe", ""),
                        None
                    )
                if not display_info:
                    manifest.set_display_info(
                        metadata.get("display_model", ""),
                        metadata.get("display_name", ""),
                        metadata.get("display_type", "")
                    )

        except Exception as e:
            print(f"Error reading JSON file: {e}")

    # 使用传入的信息覆盖推断的信息
    if workflow_info:
        manifest.workflow = workflow_info
    if instrument_info:
        manifest.instrument = instrument_info
    if display_info:
        manifest.display = display_info

    # 标记为已验证
    manifest.checksums_validated = True
    manifest.integrity_status = "ok"

    return manifest


def save_manifest(manifest: ArtifactManifest, session_dir: Path) -> Path:
    """
    保存 manifest 到 session 目录
    
    Args:
        manifest: manifest 对象
        session_dir: session 目录路径
    
    Returns:
        Path: manifest.json 文件路径
    """
    manifest_path = session_dir / "manifest.json"
    session_dir.mkdir(parents=True, exist_ok=True)

    manifest.update_timestamp()

    with open(manifest_path, 'w', encoding='utf-8') as f:
        f.write(manifest.to_json())

    print(f"Manifest saved: {manifest_path}")
    return manifest_path


def load_manifest(manifest_path: Path) -> ArtifactManifest:
    """
    从文件加载 manifest
    
    Args:
        manifest_path: manifest.json 文件路径
    
    Returns:
        ArtifactManifest: manifest 对象
    """
    with open(manifest_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    manifest = ArtifactManifest()
    manifest.from_dict(data)
    return manifest


def validate_manifest(manifest: ArtifactManifest, session_dir: Path) -> Tuple[bool, List[str]]:
    """
    验证 manifest 中的文件完整性
    
    检查：
    1. 所有记录的文件是否存在
    2. 文件 hash 是否匹配
    3. 文件大小是否匹配
    
    Args:
        manifest: manifest 对象
        session_dir: session 目录路径
    
    Returns:
        Tuple[bool, List[str]]: (是否通过, 问题列表)
    """
    errors = []
    warnings = []

    for entry in manifest.files:
        file_path = session_dir / entry.filename

        # 检查文件是否存在
        if not file_path.exists():
            errors.append(f"File missing: {entry.filename}")
            continue

        # 检查 hash
        if entry.sha256:
            actual_hash = compute_file_hash(file_path)
            if actual_hash != entry.sha256:
                errors.append(f"Hash mismatch for {entry.filename}: "
                             f"expected {entry.sha256[:16]}..., "
                             f"got {actual_hash[:16]}...")

        # 检查大小
        if entry.size_bytes:
            actual_size = compute_file_size(file_path)
            if actual_size != entry.size_bytes:
                warnings.append(f"Size mismatch for {entry.filename}: "
                               f"expected {entry.size_bytes}, got {actual_size}")

    # 检查目录中是否有未记录的文件
    supported_extensions = [".json", ".ti3", ".cal", ".icc", ".icm", ".cube", ".3dl", ".html", ".pdf"]
    for file_path in session_dir.iterdir():
        if file_path.is_file() and file_path.name != "manifest.json":
            ext = file_path.suffix.lower()
            if ext in supported_extensions:
                if not manifest.get_file(file_path.name):
                    warnings.append(f"Untracked file: {file_path.name}")

    # 更新 manifest 状态
    manifest.integrity_errors = errors + warnings
    manifest.checksums_validated = len(errors) == 0

    if errors:
        manifest.integrity_status = "error"
    elif warnings:
        manifest.integrity_status = "warning"
    else:
        manifest.integrity_status = "ok"

    return len(errors) == 0, errors + warnings


def validate_manifest_file(manifest_path: Path) -> Tuple[bool, List[str]]:
    """
    验证 manifest 文件
    
    Args:
        manifest_path: manifest.json 文件路径
    
    Returns:
        Tuple[bool, List[str]]: (是否通过, 问题列表)
    """
    session_dir = manifest_path.parent
    manifest = load_manifest(manifest_path)
    return validate_manifest(manifest, session_dir)


def check_file_integrity(file_path: Path, expected_hash: str = None,
                         expected_size: int = None) -> Tuple[bool, List[str]]:
    """
    检查单个文件完整性
    
    Args:
        file_path: 文件路径
        expected_hash: 预期的 SHA256 hash（可选）
        expected_size: 预期的大小（可选）
    
    Returns:
        Tuple[bool, List[str]]: (是否通过, 问题列表)
    """
    issues = []

    if not file_path.exists():
        issues.append(f"File does not exist: {file_path}")
        return False, issues

    if expected_hash:
        actual_hash = compute_file_hash(file_path)
        if actual_hash != expected_hash:
            issues.append(f"Hash mismatch: expected {expected_hash[:16]}..., "
                         f"got {actual_hash[:16]}...")

    if expected_size:
        actual_size = compute_file_size(file_path)
        if actual_size != expected_size:
            issues.append(f"Size mismatch: expected {expected_size}, got {actual_size}")

    return len(issues) == 0, issues


class ManifestManager:
    """
    Manifest 管理器
    
    提供批量生成、更新、验证 manifest 的功能。
    """

    def __init__(self, measurements_dir: Path):
        """
        初始化
        
        Args:
            measurements_dir: measurements 根目录
        """
        self.measurements_dir = Path(measurements_dir)
        self.auto_save_dir = self.measurements_dir / "auto_save"
        self.sessions_dir = self.measurements_dir / "sessions"

    def generate_all_manifests(self, force: bool = False) -> Dict[str, Any]:
        """
        为所有 session 目录生成 manifest
        
        Args:
            force: 是否强制重新生成（覆盖现有的 manifest）
        
        Returns:
            Dict: 生成结果统计
        """
        result = {
            "generated": [],
            "skipped": [],
            "errors": [],
            "total": 0,
        }

        # 处理 auto_save 目录
        if self.auto_save_dir.exists():
            for date_dir in self.auto_save_dir.iterdir():
                if date_dir.is_dir() and date_dir.name != "latest":
                    # 检查是否是 session 目录还是包含多个 session 的日期目录
                    for session_dir in date_dir.iterdir():
                        if session_dir.is_dir():
                            self._generate_session_manifest(session_dir, force, result)

        # 处理 sessions 目录
        if self.sessions_dir.exists():
            for session_dir in self.sessions_dir.iterdir():
                if session_dir.is_dir():
                    self._generate_session_manifest(session_dir, force, result)

        result["total"] = len(result["generated"]) + len(result["skipped"]) + len(result["errors"])
        return result

    def _generate_session_manifest(self, session_dir: Path, force: bool, result: Dict):
        """为单个 session 目录生成 manifest"""
        manifest_path = session_dir / "manifest.json"

        # 如果已有 manifest 且不强制覆盖，跳过
        if manifest_path.exists() and not force:
            result["skipped"].append(str(session_dir))
            return

        try:
            manifest = generate_manifest(session_dir)
            save_manifest(manifest, session_dir)
            result["generated"].append(str(session_dir))
        except Exception as e:
            result["errors"].append({
                "path": str(session_dir),
                "error": str(e)
            })

    def validate_all_manifests(self) -> Dict[str, Any]:
        """
        验证所有 manifest
        
        Returns:
            Dict: 验证结果统计
        """
        result = {
            "valid": [],
            "invalid": [],
            "warnings": [],
            "total": 0,
        }

        # 扫描所有 manifest.json 文件
        for manifest_path in self.measurements_dir.rglob("manifest.json"):
            is_valid, issues = validate_manifest_file(manifest_path)

            if is_valid:
                if issues:
                    result["warnings"].append({
                        "path": str(manifest_path),
                        "issues": issues
                    })
                else:
                    result["valid"].append(str(manifest_path))
            else:
                result["invalid"].append({
                    "path": str(manifest_path),
                    "issues": issues
                })

        result["total"] = len(result["valid"]) + len(result["invalid"]) + len(result["warnings"])
        return result

    def get_manifest(self, session_id: str) -> Optional[ArtifactManifest]:
        """
        获取指定 session 的 manifest
        
        Args:
            session_id: session ID
        
        Returns:
            ArtifactManifest: manifest 对象，找不到返回 None
        """
        # 先在 sessions 目录查找
        manifest_path = self.sessions_dir / session_id / "manifest.json"
        if manifest_path.exists():
            return load_manifest(manifest_path)

        # 在 auto_save 目录查找
        if self.auto_save_dir.exists():
            for date_dir in self.auto_save_dir.iterdir():
                if date_dir.is_dir() and date_dir.name != "latest":
                    manifest_path = date_dir / session_id / "manifest.json"
                    if manifest_path.exists():
                        return load_manifest(manifest_path)

        return None

    def update_manifest(self, session_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新指定 session 的 manifest
        
        Args:
            session_id: session ID
            updates: 更新内容
        
        Returns:
            bool: 是否成功
        """
        manifest = self.get_manifest(session_id)
        if not manifest:
            return False

        # 应用更新
        for key, value in updates.items():
            if hasattr(manifest, key):
                setattr(manifest, key, value)

        # 保存
        manifest_dir = self._find_session_dir(session_id)
        if manifest_dir:
            save_manifest(manifest, manifest_dir)
            return True

        return False

    def _find_session_dir(self, session_id: str) -> Optional[Path]:
        """查找 session 目录"""
        # sessions 目录
        session_dir = self.sessions_dir / session_id
        if session_dir.exists():
            return session_dir

        # auto_save 目录
        if self.auto_save_dir.exists():
            for date_dir in self.auto_save_dir.iterdir():
                if date_dir.is_dir() and date_dir.name != "latest":
                    session_dir = date_dir / session_id
                    if session_dir.exists():
                        return session_dir

        return None

    def add_file_to_manifest(self, session_id: str, file_path: Path,
                             file_type: str, generated_by: str = "") -> bool:
        """
        向 manifest 添加新文件
        
        Args:
            session_id: session ID
            file_path: 文件路径
            file_type: 文件类型
            generated_by: 生成方法
        
        Returns:
            bool: 是否成功
        """
        manifest = self.get_manifest(session_id)
        if not manifest:
            return False

        entry = ManifestEntry(
            type=file_type,
            filename=file_path.name,
            sha256=compute_file_hash(file_path),
            size_bytes=compute_file_size(file_path),
            generated_at=datetime.now().isoformat(),
            generated_by=generated_by,
            parameters={}
        )

        manifest.add_file(entry)

        manifest_dir = self._find_session_dir(session_id)
        if manifest_dir:
            save_manifest(manifest, manifest_dir)
            return True

        return False

    def remove_file_from_manifest(self, session_id: str, filename: str) -> bool:
        """
        从 manifest 移除文件
        
        Args:
            session_id: session ID
            filename: 文件名
        
        Returns:
            bool: 是否成功
        """
        manifest = self.get_manifest(session_id)
        if not manifest:
            return False

        manifest.remove_file(filename)

        manifest_dir = self._find_session_dir(session_id)
        if manifest_dir:
            save_manifest(manifest, manifest_dir)
            return True

        return False


def generate_date_dir_manifest(date_dir: Path) -> Dict[str, ArtifactManifest]:
    """
    为日期目录中的所有 session 生成 manifest
    
    Args:
        date_dir: 日期目录路径 (YYYY-MM-DD 格式)
    
    Returns:
        Dict[str, ArtifactManifest]: session_id -> manifest 映射
    """
    manifests = {}

    for session_dir in date_dir.iterdir():
        if session_dir.is_dir():
            manifest = generate_manifest(session_dir)
            manifests[manifest.session_id] = manifest
            save_manifest(manifest, session_dir)

    return manifests


def verify_all_manifests(measurements_dir: Path) -> Tuple[int, int, List[Dict]]:
    """
    验证所有 manifest 并返回统计
    
    Args:
        measurements_dir: measurements 根目录
    
    Returns:
        Tuple[int, int, List[Dict]]: (通过数, 失败数, 问题列表)
    """
    manager = ManifestManager(measurements_dir)
    result = manager.validate_all_manifests()

    pass_count = len(result["valid"])
    fail_count = len(result["invalid"])
    issues = result["invalid"] + result["warnings"]

    return pass_count, fail_count, issues
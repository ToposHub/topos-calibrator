"""
StorageService - 统一数据保存入口

提供统一的 session 保存方法，写入 SchemaV1 + Manifest + Legacy 兼容副本。

目录结构：
    measurements/
    └── sessions/
        └── <session_id>/          # e.g., 20260519-120000-ab1234
            ├── measurement.schema.v1.json  # SchemaV1 主保存格式
            ├── manifest.json               # ArtifactManifest
            ├── measurement.legacy.json     # Legacy 兼容副本
            ├── profile.ti3                 # (可选) TI3 文件
            ├── calibration.cal             # (可选) CAL 文件
            ├── profile.icc                 # (可选) ICC 文件
            └── ...                         # 其他 artifacts

文件命名约定：
    - SchemaV1: measurement.schema.v1.json
    - Manifest: manifest.json
    - Legacy: measurement.legacy.json（文件名标明 legacy）
"""

import json
import hashlib
import logging
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

from .schema import SchemaV1, MeasurementSchema, validate_schema

logger = logging.getLogger(__name__)


def _atomic_write_text(path: Path, text: str) -> None:
    """原子写文件：先写临时文件再 os.replace，避免崩溃留下截断文件。"""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, 'w', encoding='utf-8') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
from .manifest import (
    ArtifactManifest,
    ManifestEntry,
    compute_file_hash,
    compute_file_size,
    save_manifest,
    load_manifest,
    validate_manifest,
    validate_manifest_file,
    ManifestManager,
)
# 使用绝对导入
try:
    from src.data_storage import MeasurementData, CGATSExporter
except ImportError:
    from ..data_storage import MeasurementData, CGATSExporter


class StorageService:
    """
    统一数据保存服务

    作为所有测量数据保存的唯一入口，确保：
    - 新 session 使用 SchemaV1 作为主保存格式
    - 自动生成 manifest.json 记录所有 artifacts
    - 生成 legacy 兼容副本，确保旧代码仍能读取
    - 支持旧数据迁移到新格式
    """

    # 文件命名约定
    SCHEMA_V1_FILENAME = "measurement.schema.v1.json"
    MANIFEST_FILENAME = "manifest.json"
    LEGACY_FILENAME = "measurement.legacy.json"

    # Artifact 类型映射
    ARTIFACT_TYPES = {
        "measurement": "measurement",
        "ti3": "ti3",
        "cal": "cal",
        "icc": "icc",
        "icm": "icc",
        "lut": "lut",
        "cube": "lut",
        "3dl": "lut",
        "html": "report",
        "pdf": "report",
    }

    def __init__(self, measurements_dir: Union[str, Path] = None):
        """
        初始化 StorageService

        Args:
            measurements_dir: measurements 根目录路径，默认为项目目录下的 measurements/
        """
        if measurements_dir:
            self.measurements_dir = Path(measurements_dir)
        else:
            # 默认路径
            project_root = Path(__file__).parent.parent.parent
            self.measurements_dir = project_root / "measurements"

        # 确保目录存在
        self.measurements_dir.mkdir(parents=True, exist_ok=True)

        # Session 存储目录
        self.sessions_dir = self.measurements_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        # Auto save 目录（兼容旧逻辑）
        self.auto_save_dir = self.measurements_dir / "auto_save"

        # Manifest 管理器
        self._manifest_manager = ManifestManager(self.measurements_dir)

    def save_session(
        self,
        schema: SchemaV1,
        artifacts: List[Dict[str, Any]] = None,
        session_dir: Path = None,
        include_legacy: bool = True,
        include_ti3: bool = False,
    ) -> Dict[str, Any]:
        """
        保存完整的 session 数据

        写入文件：
        - measurement.schema.v1.json（SchemaV1 主保存格式）
        - manifest.json（ArtifactManifest）
        - measurement.legacy.json（Legacy 兼容副本）
        - 其他 artifacts（如果提供）

        Args:
            schema: SchemaV1 数据对象
            artifacts: 额外的 artifact 文件信息列表
                格式: [{"path": "/path/to/file.ti3", "type": "ti3", "generated_by": "targen"}, ...]
            session_dir: 指定 session 目录路径（可选，默认自动生成）
            include_legacy: 是否生成 legacy 兼容副本（默认 True）
            include_ti3: 是否自动导出 TI3 文件（默认 False）

        Returns:
            Dict: 保存结果
                {
                    "success": True/False,
                    "session_id": "...",
                    "session_dir": "...",
                    "files": {
                        "schema_v1": "...",
                        "manifest": "...",
                        "legacy": "...",
                        "artifacts": [...],
                    },
                    "errors": [],
                }
        """
        result = {
            "success": False,
            "session_id": schema.session_id,
            "session_dir": None,
            "files": {
                "schema_v1": None,
                "manifest": None,
                "legacy": None,
                "artifacts": [],
            },
            "errors": [],
        }

        # 进程级锁：防止自动保存线程与手动保存并发写坏同一 session
        with StorageService._save_lock:
            return self._save_session_locked(
                schema, artifacts, session_dir, include_legacy, include_ti3, result
            )

    # 保存锁（跨实例共享：自动保存与手动保存可能操作同一 session 目录）
    _save_lock = threading.Lock()

    def _save_session_locked(
        self,
        schema: SchemaV1,
        artifacts: Optional[List[Dict[str, Any]]],
        session_dir: Optional[Union[str, Path]],
        include_legacy: bool,
        include_ti3: bool,
        result: Dict[str, Any],
    ):
        try:
            # 1. 确定 session 目录
            if session_dir:
                session_dir = Path(session_dir)
            else:
                session_dir = self.sessions_dir / schema.session_id

            session_dir.mkdir(parents=True, exist_ok=True)
            result["session_dir"] = str(session_dir)

            # 2. 更新 schema 时间戳
            schema.update_timestamp()

            # 3. 保存 SchemaV1 文件
            schema_path = session_dir / self.SCHEMA_V1_FILENAME
            schema_json = schema.to_json()

            _atomic_write_text(schema_path, schema_json)

            # 计算 hash 和 size
            schema_hash = compute_file_hash(schema_path)
            schema_size = compute_file_size(schema_path)

            result["files"]["schema_v1"] = str(schema_path)

            # 注意：schema_hash 是"不含自身 artifact 条目"内容的 hash——
            # 自引用决定了两者无法同时一致。完整的 artifact 列表（含自身条目）
            # 由 manifest.json 承载，磁盘上的 schema 保持与其记录的 hash 一致。
            schema.add_artifact(
                "measurement_json",
                self.SCHEMA_V1_FILENAME,
                schema_hash,
                schema_size,
                "StorageService.save_session"
            )

            # 4. 保存 Legacy 兼容副本
            if include_legacy:
                legacy_path = session_dir / self.LEGACY_FILENAME
                legacy_data = MeasurementSchema.to_legacy_dict(schema)
                legacy_json = json.dumps(legacy_data, indent=2, ensure_ascii=False)

                _atomic_write_text(legacy_path, legacy_json)

                legacy_hash = compute_file_hash(legacy_path)
                legacy_size = compute_file_size(legacy_path)

                result["files"]["legacy"] = str(legacy_path)

            # 5. 处理额外的 artifacts
            if artifacts:
                for artifact_info in artifacts:
                    artifact_result = self._copy_artifact(
                        session_dir, artifact_info, schema
                    )
                    if artifact_result["success"]:
                        result["files"]["artifacts"].append(artifact_result)
                    else:
                        result["errors"].append(artifact_result["error"])

            # 6. 自动导出 TI3 文件
            if include_ti3:
                ti3_result = self._export_ti3(session_dir, schema)
                if ti3_result["success"]:
                    result["files"]["artifacts"].append(ti3_result)
                else:
                    result["errors"].append(ti3_result["error"])

            # 7. 生成并保存 Manifest
            manifest = self._generate_manifest(schema, session_dir)
            manifest_path = save_manifest(manifest, session_dir)

            result["files"]["manifest"] = str(manifest_path)

            # 8. 验证保存结果
            is_valid, validation_errors = validate_manifest(manifest, session_dir)
            if not is_valid:
                result["errors"].extend(validation_errors)

            result["success"] = len(result["errors"]) == 0

        except Exception as e:
            result["errors"].append(f"保存失败: {str(e)}")

        return result

    def _copy_artifact(
        self,
        session_dir: Path,
        artifact_info: Dict[str, Any],
        schema: SchemaV1
    ) -> Dict[str, Any]:
        """
        复制 artifact 文件到 session 目录

        Args:
            session_dir: session 目录
            artifact_info: artifact 信息
                {"path": "...", "type": "...", "generated_by": "..."}
            schema: SchemaV1 对象（用于更新 artifacts 信息）

        Returns:
            Dict: 复制结果
        """
        result = {
            "success": False,
            "source_path": artifact_info.get("path"),
            "dest_path": None,
            "filename": None,
            "hash": None,
            "size": None,
            "error": None,
        }

        try:
            source_path = Path(artifact_info["path"])
            if not source_path.exists():
                result["error"] = f"源文件不存在: {source_path}"
                return result

            # 确定文件类型
            ext = source_path.suffix.lower()
            file_type = artifact_info.get("type") or self.ARTIFACT_TYPES.get(ext, "unknown")

            # 复制文件
            dest_path = session_dir / source_path.name
            shutil.copy2(source_path, dest_path)

            # 计算 hash 和 size
            file_hash = compute_file_hash(dest_path)
            file_size = compute_file_size(dest_path)
            created_at = datetime.now().isoformat()
            generated_by = artifact_info.get("generated_by", "manual")

            result["success"] = True
            result["dest_path"] = str(dest_path)
            result["filename"] = source_path.name
            result["hash"] = file_hash
            result["size"] = file_size

            # 更新 schema artifacts
            # 映射文件类型到 schema artifacts 字段
            schema_artifact_type = self._map_artifact_type_to_schema(file_type)
            if schema_artifact_type:
                schema.add_artifact(
                    schema_artifact_type,
                    source_path.name,
                    file_hash,
                    file_size,
                    generated_by
                )

        except Exception as e:
            result["error"] = f"复制文件失败: {str(e)}"

        return result

    def _map_artifact_type_to_schema(self, artifact_type: str) -> Optional[str]:
        """
        映射 artifact 类型到 schema 字段名

        Args:
            artifact_type: 文件类型（measurement, ti3, cal, icc, lut, report）

        Returns:
            str: schema artifacts 字段名，如 "ti3", "cal", "icc" 等
        """
        mapping = {
            "measurement": "measurement_json",
            "ti3": "ti3",
            "cal": "cal",
            "icc": "icc",
            "icm": "icc",
            "lut": "lut",
            "report": "report",
        }
        return mapping.get(artifact_type)

    def _export_ti3(self, session_dir: Path, schema: SchemaV1) -> Dict[str, Any]:
        """
        从 SchemaV1 导出 TI3 文件

        Args:
            session_dir: session 目录
            schema: SchemaV1 对象

        Returns:
            Dict: 导出结果
        """
        result = {
            "success": False,
            "path": None,
            "filename": None,
            "hash": None,
            "size": None,
            "error": None,
        }

        try:
            # 从 SchemaV1 创建 MeasurementData（用于 CGATSExporter）
            legacy_data = MeasurementSchema.to_legacy_dict(schema)
            measurement_data = MeasurementData()
            measurement_data.from_dict(legacy_data)

            # 生成 TI3 文件名
            ti3_filename = f"{schema.session_id}.ti3"
            ti3_path = session_dir / ti3_filename

            # 导出
            exporter = CGATSExporter()
            success = exporter.export_ti3(measurement_data, str(ti3_path))

            if success:
                file_hash = compute_file_hash(ti3_path)
                file_size = compute_file_size(ti3_path)

                result["success"] = True
                result["path"] = str(ti3_path)
                result["filename"] = ti3_filename
                result["hash"] = file_hash
                result["size"] = file_size

                # 更新 schema
                schema.add_artifact("ti3", ti3_filename, file_hash, file_size, "CGATSExporter")
            else:
                result["error"] = "TI3 导出失败"

        except Exception as e:
            result["error"] = f"TI3 导出异常: {str(e)}"

        return result

    def _generate_manifest(self, schema: SchemaV1, session_dir: Path) -> ArtifactManifest:
        """
        从 SchemaV1 生成 ArtifactManifest

        Args:
            schema: SchemaV1 对象
            session_dir: session 目录

        Returns:
            ArtifactManifest: manifest 对象
        """
        manifest = ArtifactManifest()
        manifest.session_id = schema.session_id
        manifest.created_at = schema.created_at
        manifest.updated_at = schema.updated_at
        manifest.storage_type = "sessions"

        # 设置 workflow 信息
        manifest.set_workflow_info(
            schema.workflow.mode,
            schema.workflow.target,
            schema.status
        )

        # 设置 instrument 信息
        manifest.set_instrument_info(
            schema.instrument.probe,
            schema.instrument.correction_file
        )

        # 设置 display 信息
        manifest.set_display_info(
            schema.display.model,
            schema.display.display_name,
            schema.display.type
        )

        # 扫描目录中的所有文件并添加到 manifest
        for file_path in session_dir.iterdir():
            if file_path.is_file() and file_path.name != self.MANIFEST_FILENAME:
                # 使用文件名和扩展名来识别类型
                filename = file_path.name

                # 特殊文件类型识别（优先使用文件名）
                if filename == self.SCHEMA_V1_FILENAME:
                    file_type = "measurement"
                elif filename == self.LEGACY_FILENAME:
                    file_type = "measurement"
                else:
                    ext = file_path.suffix.lower()
                    file_type = self.ARTIFACT_TYPES.get(ext, "unknown")

                if file_type != "unknown":
                    entry = ManifestEntry(
                        type=file_type,
                        filename=file_path.name,
                        sha256=compute_file_hash(file_path),
                        size_bytes=compute_file_size(file_path),
                        generated_at=datetime.now().isoformat(),
                        generated_by="save_session",
                    )
                    manifest.add_file(entry)

        manifest.checksums_validated = True
        manifest.integrity_status = "ok"

        return manifest

    def load_session(self, session_id: str) -> Tuple[Optional[SchemaV1], Optional[ArtifactManifest]]:
        """
        加载 session 数据

        优先读取 SchemaV1 格式，如果没有则尝试读取 legacy 格式。

        Args:
            session_id: session ID

        Returns:
            Tuple[SchemaV1, ArtifactManifest]: (schema, manifest)，
                如果不存在返回 (None, None)
        """
        # 查找 session 目录
        session_dir = self._find_session_dir(session_id)
        if not session_dir:
            return None, None

        # 优先读取 SchemaV1
        schema_path = session_dir / self.SCHEMA_V1_FILENAME
        if schema_path.exists():
            try:
                with open(schema_path, 'r', encoding='utf-8') as f:
                    schema_json = f.read()

                schema = SchemaV1()
                schema.from_json(schema_json)

                # 加载 manifest
                manifest_path = session_dir / self.MANIFEST_FILENAME
                if manifest_path.exists():
                    manifest = load_manifest(manifest_path)
                else:
                    # 如果没有 manifest，生成一个
                    manifest = self._generate_manifest(schema, session_dir)

                return schema, manifest

            except Exception as e:
                logger.warning(f"加载 SchemaV1 失败: {e}", exc_info=True)

        # 尝试读取 legacy 格式
        legacy_path = session_dir / self.LEGACY_FILENAME
        if legacy_path.exists():
            try:
                with open(legacy_path, 'r', encoding='utf-8') as f:
                    legacy_json = f.read()

                schema = MeasurementSchema.from_legacy_json(legacy_json)

                # 加载或生成 manifest
                manifest_path = session_dir / self.MANIFEST_FILENAME
                if manifest_path.exists():
                    manifest = load_manifest(manifest_path)
                else:
                    manifest = self._generate_manifest(schema, session_dir)

                return schema, manifest

            except Exception as e:
                logger.warning(f"加载 legacy 格式失败: {e}", exc_info=True)

        # 尝试查找任意 JSON 文件
        for json_file in session_dir.glob("*.json"):
            if json_file.name not in [self.SCHEMA_V1_FILENAME, self.LEGACY_FILENAME, self.MANIFEST_FILENAME]:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    # 检查格式
                    if data.get("schema_version") == "1.0":
                        schema = SchemaV1()
                        schema.from_dict(data)
                    else:
                        schema = MeasurementSchema.from_legacy_dict(data)

                    manifest_path = session_dir / self.MANIFEST_FILENAME
                    if manifest_path.exists():
                        manifest = load_manifest(manifest_path)
                    else:
                        manifest = self._generate_manifest(schema, session_dir)

                    return schema, manifest

                except Exception as e:
                    logger.warning(f"加载 {json_file} 失败: {e}")

        return None, None

    def _find_session_dir(self, session_id: str) -> Optional[Path]:
        """
        查找 session 目录

        Args:
            session_id: session ID

        Returns:
            Path: session 目录路径，不存在返回 None
        """
        # 优先在 sessions 目录查找
        session_dir = self.sessions_dir / session_id
        if session_dir.exists():
            return session_dir

        # 在 auto_save 目录查找
        if self.auto_save_dir.exists():
            for date_dir in self.auto_save_dir.iterdir():
                if date_dir.is_dir() and date_dir.name != "latest":
                    session_dir = date_dir / session_id
                    if session_dir.exists():
                        return session_dir

            # 尝试直接在 auto_save 下查找（旧格式）
            session_dir = self.auto_save_dir / session_id
            if session_dir.exists():
                return session_dir

        return None

    def migrate_legacy_to_v1(
        self,
        legacy_path: Path,
        session_id: str = None,
        output_dir: Path = None
    ) -> Dict[str, Any]:
        """
        将旧格式数据迁移到 SchemaV1 格式

        Args:
            legacy_path: 旧格式 JSON 文件路径
            session_id: 新 session ID（可选，默认从 legacy 数据生成）
            output_dir: 输出目录（可选，默认 sessions/<session_id>）

        Returns:
            Dict: 迁移结果
        """
        result = {
            "success": False,
            "session_id": None,
            "session_dir": None,
            "schema_path": None,
            "manifest_path": None,
            "legacy_backup": None,
            "errors": [],
        }

        try:
            # 加载旧格式数据
            with open(legacy_path, 'r', encoding='utf-8') as f:
                legacy_data = json.load(f)

            # 转换为 SchemaV1
            schema = MeasurementSchema.from_legacy_dict(legacy_data)

            # 如果指定了 session_id，使用指定的
            if session_id:
                schema.session_id = session_id

            result["session_id"] = schema.session_id

            # 确定输出目录
            if output_dir:
                session_dir = Path(output_dir)
            else:
                session_dir = self.sessions_dir / schema.session_id

            session_dir.mkdir(parents=True, exist_ok=True)
            result["session_dir"] = str(session_dir)

            # 保存 SchemaV1
            schema_path = session_dir / self.SCHEMA_V1_FILENAME
            schema_json = schema.to_json()

            with open(schema_path, 'w', encoding='utf-8') as f:
                f.write(schema_json)

            result["schema_path"] = str(schema_path)

            # 备份原始 legacy 文件
            legacy_backup = session_dir / self.LEGACY_FILENAME
            shutil.copy2(legacy_path, legacy_backup)
            result["legacy_backup"] = str(legacy_backup)

            # 生成 manifest
            manifest = self._generate_manifest(schema, session_dir)
            manifest_path = save_manifest(manifest, session_dir)
            result["manifest_path"] = str(manifest_path)

            result["success"] = True

        except Exception as e:
            result["errors"].append(f"迁移失败: {str(e)}")

        return result

    def export_v1_to_legacy(
        self,
        schema: SchemaV1,
        output_path: Path = None
    ) -> Dict[str, Any]:
        """
        将 SchemaV1 导出为 legacy 格式

        Args:
            schema: SchemaV1 对象
            output_path: 输出路径（可选）

        Returns:
            Dict: 导出结果
        """
        result = {
            "success": False,
            "path": None,
            "errors": [],
        }

        try:
            # 转换为 legacy 格式
            legacy_data = MeasurementSchema.to_legacy_dict(schema)

            # 确定输出路径
            if output_path:
                output_path = Path(output_path)
            else:
                # 使用旧的文件名格式：YYYYMMDD_HHMMSS_XXXXXX.json
                old_id = schema.session_id.replace("-", "_")
                output_path = self.measurements_dir / f"{old_id}.json"

            output_path.parent.mkdir(parents=True, exist_ok=True)

            # 保存
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(legacy_data, f, indent=2, ensure_ascii=False)

            result["success"] = True
            result["path"] = str(output_path)

        except Exception as e:
            result["errors"].append(f"导出失败: {str(e)}")

        return result

    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        列出所有 session

        Returns:
            List[Dict]: session 信息列表
        """
        sessions = []

        # 扫描 sessions 目录
        if self.sessions_dir.exists():
            for session_dir in self.sessions_dir.iterdir():
                if session_dir.is_dir():
                    session_info = self._get_session_info(session_dir)
                    if session_info:
                        sessions.append(session_info)

        # 扫描 auto_save 目录（兼容旧数据）
        if self.auto_save_dir.exists():
            for date_dir in self.auto_save_dir.iterdir():
                if date_dir.is_dir() and date_dir.name != "latest":
                    # 检查是日期目录还是 session 目录
                    if self._is_date_dir(date_dir):
                        for session_dir in date_dir.iterdir():
                            if session_dir.is_dir():
                                session_info = self._get_session_info(session_dir)
                                if session_info:
                                    sessions.append(session_info)
                    else:
                        # 直接是 session 目录
                        session_info = self._get_session_info(date_dir)
                        if session_info:
                            sessions.append(session_info)

        # 按时间排序
        sessions.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return sessions

    def _is_date_dir(self, dir_path: Path) -> bool:
        """
        检查是否是日期目录（YYYY-MM-DD 格式）

        Args:
            dir_path: 目录路径

        Returns:
            bool: 是否是日期目录
        """
        import re
        pattern = r'^\d{4}-\d{2}-\d{2}$'
        return bool(re.match(pattern, dir_path.name))

    def _get_session_info(self, session_dir: Path) -> Optional[Dict[str, Any]]:
        """
        获取 session 目录的信息

        Args:
            session_dir: session 目录路径

        Returns:
            Dict: session 信息
        """
        info = {
            "session_id": session_dir.name,
            "session_dir": str(session_dir),
            "has_schema_v1": False,
            "has_manifest": False,
            "has_legacy": False,
            "created_at": None,
            "workflow_mode": None,
            "workflow_target": None,
            "probe": None,
            "display_model": None,
            "display_name": None,
        }

        # 检查文件存在
        schema_path = session_dir / self.SCHEMA_V1_FILENAME
        manifest_path = session_dir / self.MANIFEST_FILENAME
        legacy_path = session_dir / self.LEGACY_FILENAME

        info["has_schema_v1"] = schema_path.exists()
        info["has_manifest"] = manifest_path.exists()
        info["has_legacy"] = legacy_path.exists()

        # 从 manifest 读取信息（优先）
        if manifest_path.exists():
            try:
                manifest = load_manifest(manifest_path)
                info["created_at"] = manifest.created_at
                info["workflow_mode"] = manifest.workflow.get("mode")
                info["workflow_target"] = manifest.workflow.get("target")
                info["probe"] = manifest.instrument.get("probe")
                info["display_model"] = manifest.display.get("model")
                info["display_name"] = manifest.display.get("display_name")
            except Exception as e:
                logger.warning(f"读取 manifest 失败: {e}")

        # 如果 manifest 没有信息，从 schema 读取
        if not info["created_at"] and schema_path.exists():
            try:
                with open(schema_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                info["created_at"] = data.get("created_at")
                info["workflow_mode"] = data.get("workflow", {}).get("mode")
                info["workflow_target"] = data.get("workflow", {}).get("target")
                info["probe"] = data.get("instrument", {}).get("probe")
                info["display_model"] = data.get("display", {}).get("model")
                info["display_name"] = data.get("display", {}).get("display_name")
            except Exception as e:
                logger.warning(f"读取 schema 失败: {e}")

        # 如果都没有，从 legacy 读取
        if not info["created_at"] and legacy_path.exists():
            try:
                with open(legacy_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                metadata = data.get("metadata", {})
                info["created_at"] = metadata.get("timestamp")
                info["workflow_mode"] = metadata.get("measure_mode")
                info["probe"] = metadata.get("probe")
                info["display_model"] = metadata.get("display_model")
                info["display_name"] = metadata.get("display_name")
            except Exception as e:
                logger.warning(f"读取 legacy 失败: {e}")

        return info

    def validate_session(self, session_id: str) -> Tuple[bool, List[str]]:
        """
        验证 session 数据完整性

        Args:
            session_id: session ID

        Returns:
            Tuple[bool, List[str]]: (是否通过, 问题列表)
        """
        session_dir = self._find_session_dir(session_id)
        if not session_dir:
            return False, [f"Session 目录不存在: {session_id}"]

        errors = []

        # 检查 SchemaV1 文件
        schema_path = session_dir / self.SCHEMA_V1_FILENAME
        if schema_path.exists():
            try:
                with open(schema_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                is_valid, schema_errors = validate_schema(data)
                if not is_valid:
                    errors.extend(schema_errors)
            except Exception as e:
                errors.append(f"SchemaV1 文件读取失败: {e}")

        # 检查 manifest
        manifest_path = session_dir / self.MANIFEST_FILENAME
        if manifest_path.exists():
            is_valid, manifest_errors = validate_manifest_file(manifest_path)
            if not is_valid:
                errors.extend(manifest_errors)
        else:
            errors.append("缺少 manifest.json 文件")

        return len(errors) == 0, errors

    def generate_missing_manifests(self) -> Dict[str, Any]:
        """
        为缺少 manifest 的 session 生成 manifest

        Returns:
            Dict: 生成结果统计
        """
        result = {
            "generated": [],
            "skipped": [],
            "errors": [],
        }

        # 扫描 sessions 目录
        if self.sessions_dir.exists():
            for session_dir in self.sessions_dir.iterdir():
                if session_dir.is_dir():
                    manifest_path = session_dir / self.MANIFEST_FILENAME
                    if not manifest_path.exists():
                        try:
                            # 尝试加载 schema
                            schema, _ = self.load_session(session_dir.name)
                            if schema:
                                manifest = self._generate_manifest(schema, session_dir)
                                save_manifest(manifest, session_dir)
                                result["generated"].append(str(session_dir))
                            else:
                                result["errors"].append({
                                    "path": str(session_dir),
                                    "error": "无法读取 session 数据"
                                })
                        except Exception as e:
                            result["errors"].append({
                                "path": str(session_dir),
                                "error": str(e)
                            })
                    else:
                        result["skipped"].append(str(session_dir))

        return result


# 便捷导出函数
def save_session(
    schema: SchemaV1,
    measurements_dir: Path = None,
    artifacts: List[Dict] = None
) -> Dict[str, Any]:
    """
    便捷函数：保存 session

    Args:
        schema: SchemaV1 对象
        measurements_dir: measurements 目录（可选）
        artifacts: artifact 文件列表（可选）

    Returns:
        Dict: 保存结果
    """
    service = StorageService(measurements_dir)
    return service.save_session(schema, artifacts)


def load_session(session_id: str, measurements_dir: Path = None) -> Tuple[Optional[SchemaV1], Optional[ArtifactManifest]]:
    """
    便捷函数：加载 session

    Args:
        session_id: session ID
        measurements_dir: measurements 目录（可选）

    Returns:
        Tuple[SchemaV1, ArtifactManifest]: (schema, manifest)
    """
    service = StorageService(measurements_dir)
    return service.load_session(session_id)
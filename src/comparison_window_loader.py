"""
comparison_window_loader.py - ComparisonWindow 数据加载辅助模块

P7 升级：使用 StorageService 和 Manifest 读取数据，不再依赖隐式路径猜测。

提供：
- load_sessions_from_storage_service(): 从 StorageService.list_sessions() 加载
- load_session_metadata_from_manifest(): 从 manifest 读取元数据
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

try:
    from .storage.schema import SchemaV1, MeasurementSchema, get_schema_version
    from .storage.manifest import ArtifactManifest, load_manifest, ManifestManager
    from .storage.storage_service import StorageService
    SCHEMA_AVAILABLE = True
except ImportError:
    SCHEMA_AVAILABLE = False


def load_sessions_from_storage_service(storage_service: StorageService) -> List[Dict]:
    """
    从 StorageService.list_sessions() 加载 session 列表

    P7 升级：优先使用 manifest 读取数据，不依赖隐式路径猜测。

    Args:
        storage_service: StorageService 实例

    Returns:
        List[Dict]: session 信息列表
    """
    if not SCHEMA_AVAILABLE:
        return []

    sessions = storage_service.list_sessions()

    measurements = []
    for session_info in sessions:
        measurement_data = load_session_metadata_from_manifest(
            storage_service,
            session_info["session_id"]
        )
        if measurement_data:
            measurements.append(measurement_data)

    return measurements


def load_session_metadata_from_manifest(
    storage_service: StorageService,
    session_id: str
) -> Optional[Dict]:
    """
    从 manifest 和 schema 读取 session 元数据

    Args:
        storage_service: StorageService 实例
        session_id: session ID

    Returns:
        Dict: session 元数据
    """
    if not SCHEMA_AVAILABLE:
        return None

    # 使用 StorageService 加载
    schema, manifest = storage_service.load_session(session_id)

    if schema is None:
        return None

    result = {
        "id": session_id,
        "session_id": session_id,
        "json_path": None,
        "timestamp": schema.created_at,
        "probe": schema.instrument.probe,
        "display_type": schema.display.type,
        "display_model": schema.display.model,
        "display_name": schema.display.display_name,
        "measure_mode": schema.workflow.mode,
        "has_gamut": schema.is_valid(),
        "has_gamma": len(schema.measurements.gamma) > 0,
        "has_lut": len(schema.measurements.lut_patches) > 0,
        "target_standard": schema.workflow.target,
        "workflow_target": schema.workflow.target,
        "workflow_mode": schema.workflow.mode,
        "gamma_target": schema.workflow.gamma_target,
        "white_point_target": schema.workflow.white_point_target,
        "status": schema.status,
        "notes": schema.notes,
        # Manifest 信息
        "manifest_status": manifest.integrity_status if manifest else "unknown",
        "artifact_count": len(manifest.files) if manifest else 0,
    }

    # 如果有 manifest，添加更多信息
    if manifest:
        result["storage_type"] = manifest.storage_type
        result["date_dir"] = manifest.date_dir

        # 检查文件类型
        artifact_types = [f.type for f in manifest.files]
        result["has_ti3"] = "ti3" in artifact_types
        result["has_cal"] = "cal" in artifact_types
        result["has_icc"] = "icc" in artifact_types

    return result


def parse_timestamp(ts) -> datetime:
    """解析时间戳"""
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts)
    try:
        return datetime.fromisoformat(str(ts))
    except:
        return datetime.min


# ==============================================================================
# 用于 ComparisonBackend 的辅助函数
# ==============================================================================

def update_comparison_backend_init(backend_instance, data_storage):
    """
    更新 ComparisonBackend 实例，添加 StorageService 支持

    Args:
        backend_instance: ComparisonBackend 实例
        data_storage: DataStorage 实例
    """
    if SCHEMA_AVAILABLE:
        backend_instance._storage_service = StorageService(data_storage.base_path)
    else:
        backend_instance._storage_service = None


def load_measurement_list_with_storage_service(backend_instance) -> List[Dict]:
    """
    使用 StorageService 加载测量列表

    Args:
        backend_instance: ComparisonBackend 实例

    Returns:
        List[Dict]: 测量数据列表
    """
    if backend_instance._storage_service and SCHEMA_AVAILABLE:
        return load_sessions_from_storage_service(backend_instance._storage_service)
    else:
        # 回退到旧逻辑
        raw_list = backend_instance._data_storage.get_all_saved_measurements()
        measurements = []
        for item in raw_list:
            json_path = item.get("json_path", "")
            measurement_data = backend_instance._load_measurement_metadata(json_path, item)
            measurements.append(measurement_data)
        return measurements
"""
Storage Module - 数据模型、迁移和 Manifest 管理

提供 Schema 版本控制、数据迁移和 Artifact Manifest 功能。

Backend integration:
- StorageFacade provides unified storage API for Backend
- Backend delegates storage operations to StorageFacade
- Backend keeps Qt signals/slots for UI communication
"""

from .schema import (
    SchemaVersion,
    SchemaV1,
    MeasurementSchema,
    validate_schema,
    get_schema_version,
)
from .migrations import (
    MigrationManager,
    migrate_v0_to_v1,
    deduplicate_records,
)
from .manifest import (
    ArtifactManifest,
    ManifestEntry,
    generate_manifest,
    validate_manifest,
)
from .storage_service import StorageService
from .storage_facade import StorageFacade

__all__ = [
    "SchemaVersion",
    "SchemaV1",
    "MeasurementSchema",
    "validate_schema",
    "get_schema_version",
    "MigrationManager",
    "migrate_v0_to_v1",
    "deduplicate_records",
    "ArtifactManifest",
    "ManifestEntry",
    "generate_manifest",
    "validate_manifest",
    # Backend facade
    "StorageService",
    "StorageFacade",
]
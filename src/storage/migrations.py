"""
Migrations Module - 数据迁移工具

提供从旧格式到新 schema 的迁移功能，包括去重策略。
"""

import json
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

from .schema import (
    SchemaV1,
    MeasurementSchema,
    SchemaVersion,
    validate_schema,
    get_schema_version,
    CURRENT_SCHEMA_VERSION,
)


@dataclass
class MigrationResult:
    """迁移结果"""
    success: bool
    migrated_count: int
    skipped_count: int
    error_count: int
    errors: List[str]
    migrated_files: List[str]
    skipped_files: List[str]


@dataclass
class DeduplicationResult:
    """去重结果"""
    total_records: int
    unique_records: int
    duplicate_groups: List[Dict[str, Any]]
    duplicates_removed: int


class MigrationManager:
    """
    数据迁移管理器
    
    负责：
    1. 读取旧格式数据
    2. 转换为新 schema v1.0
    3. 去重处理
    4. 生成迁移报告
    """

    def __init__(self, source_dir: Path, target_dir: Path = None):
        """
        初始化迁移管理器
        
        Args:
            source_dir: 源数据目录
            target_dir: 目标目录（可选，默认原地迁移）
        """
        self.source_dir = Path(source_dir)
        self.target_dir = Path(target_dir) if target_dir else self.source_dir
        self.backup_dir = None

    def migrate_all(self, backup: bool = True) -> MigrationResult:
        """
        迁移所有数据文件
        
        Args:
            backup: 是否创建备份
        
        Returns:
            MigrationResult: 迁移结果
        """
        result = MigrationResult(
            success=True,
            migrated_count=0,
            skipped_count=0,
            error_count=0,
            errors=[],
            migrated_files=[],
            skipped_files=[]
        )

        # 创建备份
        if backup:
            self._create_backup()

        # 扫描所有 JSON 文件
        json_files = self._scan_json_files()

        for json_file in json_files:
            try:
                # 检测版本
                version = self._detect_file_version(json_file)

                if version == CURRENT_SCHEMA_VERSION:
                    # 已经是新版本，跳过
                    result.skipped_count += 1
                    result.skipped_files.append(str(json_file))
                    continue

                # 执行迁移
                success = self._migrate_file(json_file)

                if success:
                    result.migrated_count += 1
                    result.migrated_files.append(str(json_file))
                else:
                    result.error_count += 1
                    result.errors.append(f"Failed to migrate: {json_file}")

            except Exception as e:
                result.error_count += 1
                result.errors.append(f"Error processing {json_file}: {str(e)}")

        result.success = result.error_count == 0
        return result

    def _scan_json_files(self) -> List[Path]:
        """扫描所有 JSON 文件"""
        json_files = []

        # 扫描根目录
        for f in self.source_dir.glob("*.json"):
            json_files.append(f)

        # 扫描 auto_save 子目录
        auto_save_dir = self.source_dir / "auto_save"
        if auto_save_dir.exists():
            for date_dir in auto_save_dir.iterdir():
                if date_dir.is_dir() and date_dir.name != "latest":
                    for f in date_dir.glob("*.json"):
                        json_files.append(f)

        return sorted(json_files)

    def _detect_file_version(self, json_file: Path) -> str:
        """检测文件版本"""
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return get_schema_version(data)
        except Exception:
            return "0"

    def _migrate_file(self, json_file: Path) -> bool:
        """迁移单个文件"""
        try:
            # 读取旧数据
            with open(json_file, 'r', encoding='utf-8') as f:
                legacy_data = json.load(f)

            # 转换为新格式
            schema = MeasurementSchema.from_legacy_dict(legacy_data)

            # 计算文件 hash 并添加 artifact 信息
            file_hash = self._compute_file_hash(json_file)
            file_size = json_file.stat().st_size
            schema.add_artifact(
                "measurement_json",
                json_file.name,
                file_hash,
                file_size,
                "MigrationManager.migrate_file"
            )

            # 写入新格式
            new_data = schema.to_dict()

            # 决定目标路径
            target_path = self._get_target_path(json_file)
            target_path.parent.mkdir(parents=True, exist_ok=True)

            with open(target_path, 'w', encoding='utf-8') as f:
                json.dump(new_data, f, indent=2, ensure_ascii=False)

            return True

        except Exception as e:
            print(f"Migration error for {json_file}: {e}")
            return False

    def _get_target_path(self, source_path: Path) -> Path:
        """获取目标文件路径"""
        if self.target_dir == self.source_dir:
            # 原地迁移
            return source_path
        else:
            # 迁移到新目录，保持相对路径结构
            rel_path = source_path.relative_to(self.source_dir)
            return self.target_dir / rel_path

    def _compute_file_hash(self, file_path: Path) -> str:
        """计算文件 SHA256 hash"""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _create_backup(self) -> Path:
        """创建备份目录"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.backup_dir = self.source_dir.parent / f"measurements_backup_{timestamp}"
        shutil.copytree(self.source_dir, self.backup_dir)
        print(f"Backup created: {self.backup_dir}")
        return self.backup_dir

    def migrate_single_file(self, json_path: Path) -> Tuple[bool, SchemaV1]:
        """
        迁移单个文件
        
        Args:
            json_path: JSON 文件路径
        
        Returns:
            Tuple[bool, SchemaV1]: (是否成功, 新格式数据)
        """
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                legacy_data = json.load(f)

            schema = MeasurementSchema.from_legacy_dict(legacy_data)
            return True, schema

        except Exception as e:
            print(f"Migration error: {e}")
            return False, None

    def add_schema_version_to_file(self, json_path: Path) -> bool:
        """
        为单个 JSON 文件添加 schema_version 字段
        
        Args:
            json_path: JSON 文件路径
        
        Returns:
            bool: 是否成功
        """
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 如果已经有 schema_version，跳过
            if "schema_version" in data:
                return True

            # 添加 schema_version 到顶层
            data["schema_version"] = CURRENT_SCHEMA_VERSION

            # 重新排序字段，把 schema_version 放在最前面
            ordered_data = {"schema_version": data["schema_version"]}
            ordered_data.update(data)

            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(ordered_data, f, indent=2, ensure_ascii=False)

            return True

        except Exception as e:
            print(f"Error adding schema_version: {e}")
            return False


def migrate_v0_to_v1(source_dir: Path, target_dir: Path = None,
                     backup: bool = True) -> MigrationResult:
    """
    迁移旧格式数据到 v1 schema
    
    Args:
        source_dir: 源目录
        target_dir: 目标目录（可选）
        backup: 是否创建备份
    
    Returns:
        MigrationResult: 迁移结果
    """
    manager = MigrationManager(source_dir, target_dir)
    return manager.migrate_all(backup)


def deduplicate_records(data_dir: Path, strategy: str = "hash",
                        output_report: Path = None) -> DeduplicationResult:
    """
    对历史记录进行去重
    
    Args:
        data_dir: 数据目录
        strategy: 去重策略 (hash, measurement_id, path, timestamp)
        output_report: 输出报告路径（可选）
    
    Returns:
        DeduplicationResult: 去重结果
    """
    result = DeduplicationResult(
        total_records=0,
        unique_records=0,
        duplicate_groups=[],
        duplicates_removed=0
    )

    # 收集所有记录及其键值
    records = {}  # key -> [file_paths]

    json_files = list(data_dir.glob("*.json"))
    json_files.extend(data_dir.rglob("*.json"))

    for json_file in json_files:
        if json_file.parent.name == "latest":  # 跳过符号链接目录
            continue

        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            result.total_records += 1

            # 根据策略生成键
            key = _generate_dedup_key(json_file, data, strategy)

            if key not in records:
                records[key] = []
            records[key].append({
                "path": str(json_file),
                "hash": _compute_file_hash(json_file),
                "timestamp": data.get("metadata", {}).get("timestamp", ""),
                "measurement_id": data.get("metadata", {}).get("measurement_id", "")
            })

        except Exception as e:
            print(f"Error reading {json_file}: {e}")

    # 分析重复组
    for key, file_list in records.items():
        if len(file_list) > 1:
            # 找出重复组
            duplicate_group = {
                "key": key,
                "strategy": strategy,
                "files": file_list,
                "count": len(file_list)
            }
            result.duplicate_groups.append(duplicate_group)
            result.duplicates_removed += len(file_list) - 1

    result.unique_records = len(records)

    # 生成报告
    if output_report:
        _generate_dedup_report(result, output_report)

    return result


def _generate_dedup_key(file_path: Path, data: Dict, strategy: str) -> str:
    """根据策略生成去重键"""
    metadata = data.get("metadata", {})
    measurements = data.get("measurements", {})

    if strategy == "hash":
        # 使用文件内容的 hash 作为键
        return _compute_file_hash(file_path)

    elif strategy == "measurement_id":
        # 使用 measurement_id 作为键
        return metadata.get("measurement_id", "")

    elif strategy == "path":
        # 使用文件路径作为键（实际上不会产生重复）
        return str(file_path)

    elif strategy == "timestamp":
        # 使用时间戳作为键（同秒可能产生重复）
        return metadata.get("timestamp", "")

    elif strategy == "composite":
        # 组合键：measurement_id + hash 前缀
        id_part = metadata.get("measurement_id", "")
        hash_part = _compute_file_hash(file_path)[:8]
        return f"{id_part}_{hash_part}"

    else:
        # 默认使用 hash
        return _compute_file_hash(file_path)


def _compute_file_hash(file_path: Path) -> str:
    """计算文件 SHA256 hash"""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def _generate_dedup_report(result: DeduplicationResult, output_path: Path):
    """生成去重报告"""
    report = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_records": result.total_records,
            "unique_records": result.unique_records,
            "duplicate_groups_count": len(result.duplicate_groups),
            "duplicates_removed": result.duplicates_removed
        },
        "duplicate_groups": result.duplicate_groups
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"Dedup report saved: {output_path}")


def convert_measurement_data_to_schema(measurement_data_dict: Dict) -> SchemaV1:
    """
    将 MeasurementData.to_dict() 的输出转换为 SchemaV1
    
    这是一个便捷函数，用于在保存数据时直接转换格式。
    
    Args:
        measurement_data_dict: MeasurementData.to_dict() 的输出
    
    Returns:
        SchemaV1: 新格式数据对象
    """
    return MeasurementSchema.from_legacy_dict(measurement_data_dict)


class LegacyDataReader:
    """
    旧数据读取器
    
    提供读取旧格式数据的能力，确保旧数据不丢失。
    """

    @staticmethod
    def read_json(json_path: Path) -> Tuple[Dict, str]:
        """
        读取 JSON 文件，返回数据和版本
        
        Args:
            json_path: JSON 文件路径
        
        Returns:
            Tuple[Dict, str]: (数据, 版本)
        """
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        version = get_schema_version(data)

        # 如果是旧格式，添加标记
        if version == "0":
            data["_legacy_format"] = True

        return data, version

    @staticmethod
    def is_legacy_format(data: Dict) -> bool:
        """检查是否是旧格式"""
        return get_schema_version(data) == "0"

    @staticmethod
    def normalize_to_v1(data: Dict) -> SchemaV1:
        """
        将任意格式数据规范化为 v1
        
        Args:
            data: 任意格式的数据
        
        Returns:
            SchemaV1: 规范化后的数据
        """
        version = get_schema_version(data)

        if version == CURRENT_SCHEMA_VERSION:
            # 已经是 v1 格式
            schema = SchemaV1()
            schema.from_dict(data)
            return schema

        elif version == "0":
            # 旧格式，转换
            return MeasurementSchema.from_legacy_dict(data)

        else:
            raise ValueError(f"Unsupported schema version: {version}")


def check_data_integrity(json_path: Path) -> Tuple[bool, List[str]]:
    """
    检查数据完整性
    
    Args:
        json_path: JSON 文件路径
    
    Returns:
        Tuple[bool, List[str]]: (是否完整, 问题列表)
    """
    issues = []

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 检查基本结构
        if "metadata" not in data and "measurements" not in data:
            # 可能是新格式，检查 schema_version
            if "schema_version" not in data:
                issues.append("Missing both metadata/measurements and schema_version")

        # 检查旧格式字段
        if "metadata" in data:
            metadata = data["metadata"]
            required_metadata = ["measurement_id", "timestamp"]
            for field in required_metadata:
                if field not in metadata:
                    issues.append(f"Missing metadata field: {field}")

        # 检查新格式字段
        if "schema_version" in data:
            is_valid, errors = validate_schema(data)
            if not is_valid:
                issues.extend(errors)

        # 检查测量数据
        if "measurements" in data:
            meas = data["measurements"]
            # 至少应该有一种测量数据
            has_data = False
            if "gamut" in meas:
                gamut = meas["gamut"]
                if any(v.get("xyY") for v in gamut.values() if isinstance(v, dict)):
                    has_data = True
            if "gamma" in meas and len(meas["gamma"]) > 0:
                has_data = True
            if "lut_patches" in meas and len(meas["lut_patches"]) > 0:
                has_data = True

            if not has_data:
                issues.append("No actual measurement data found")

    except json.JSONDecodeError as e:
        issues.append(f"JSON decode error: {e}")
    except Exception as e:
        issues.append(f"Error reading file: {e}")

    return len(issues) == 0, issues
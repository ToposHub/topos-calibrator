"""
session_report.py - Session 报告生成辅助模块

P7 升级：使用 StorageService 和 SchemaV1 生成报告，不依赖隐式路径猜测。

提供：
- generate_from_session(): 从 session ID 生成报告
- generate_from_session_dir(): 从 session 目录生成报告
"""

import json
from pathlib import Path
from typing import Dict, Optional, Tuple, Any

from ..storage.schema import SchemaV1, MeasurementSchema
from ..storage.manifest import ArtifactManifest, load_manifest
from ..storage.storage_service import StorageService


# 文件命名约定（与 StorageService 保持一致）
SCHEMA_V1_FILENAME = "measurement.schema.v1.json"
MANIFEST_FILENAME = "manifest.json"
LEGACY_FILENAME = "measurement.legacy.json"


def generate_from_session(
    session_id: str,
    measurements_dir: Path = None,
    report_generator=None,
    report_type: str = "full_report"
) -> Tuple[Optional[str], Optional[Dict]]:
    """
    从 session ID 生成报告

    P7 升级：优先读取 SchemaV1，不依赖隐式路径猜测

    Args:
        session_id: session ID
        measurements_dir: measurements 目录（可选）
        report_generator: ReportGenerator 实例（可选）
        report_type: 报告类型

    Returns:
        Tuple[str, Dict]: (HTML 报告内容, manifest 数据)
            如果找不到数据返回 (None, None)
    """
    # 使用 StorageService 加载 session
    service = StorageService(measurements_dir)
    schema, manifest = service.load_session(session_id)

    if schema is None:
        return None, None

    # 使用报告生成器生成报告
    if report_generator:
        from .generator import ReportType

        # 转换 report_type 字符串到 ReportType enum
        type_map = {
            "full_report": ReportType.FULL_REPORT,
            "icc_validation": ReportType.ICC_VALIDATION,
            "lut_validation": ReportType.LUT_VALIDATION,
            "gamut_measurement": ReportType.GAMUT_MEASUREMENT,
            "gamma_analysis": ReportType.GAMMA_ANALYSIS,
            "comparison": ReportType.COMPARISON,
        }
        actual_type = type_map.get(report_type, ReportType.FULL_REPORT)

        html_report = report_generator.generate_from_schema(schema, actual_type)
    else:
        # 如果没有 report_generator，使用默认生成器
        from .generator import ReportGenerator, ReportType

        generator = ReportGenerator()
        type_map = {
            "full_report": ReportType.FULL_REPORT,
            "icc_validation": ReportType.ICC_VALIDATION,
            "lut_validation": ReportType.LUT_VALIDATION,
            "gamut_measurement": ReportType.GAMUT_MEASUREMENT,
            "gamma_analysis": ReportType.GAMMA_ANALYSIS,
            "comparison": ReportType.COMPARISON,
        }
        actual_type = type_map.get(report_type, ReportType.FULL_REPORT)

        html_report = generator.generate_from_schema(schema, actual_type)

    # 返回 manifest 信息
    manifest_dict = manifest.to_dict() if manifest else None

    return html_report, manifest_dict


def generate_from_session_dir(
    session_dir: Path,
    report_generator=None,
    report_type: str = "full_report"
) -> Tuple[Optional[str], Optional[Dict]]:
    """
    从 session 目录生成报告

    P7 升级：优先读取 SchemaV1，不依赖隐式路径猜测

    Args:
        session_dir: session 目录路径
        report_generator: ReportGenerator 实例（可选）
        report_type: 报告类型

    Returns:
        Tuple[str, Dict]: (HTML 报告内容, manifest 数据)
    """
    session_dir = Path(session_dir)

    if not session_dir.exists():
        return None, None

    # 优先读取 SchemaV1
    schema_path = session_dir / SCHEMA_V1_FILENAME
    if schema_path.exists():
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            schema = SchemaV1()
            schema.from_dict(data)

            # 加载 manifest
            manifest_path = session_dir / MANIFEST_FILENAME
            if manifest_path.exists():
                manifest = load_manifest(manifest_path)
                manifest_dict = manifest.to_dict()
            else:
                manifest_dict = None

            html_report = _generate_report_from_schema(schema, report_generator, report_type)
            return html_report, manifest_dict

        except Exception as e:
            print(f"读取 SchemaV1 失败: {e}")

    # 尝试读取 legacy 格式
    legacy_path = session_dir / LEGACY_FILENAME
    if legacy_path.exists():
        try:
            with open(legacy_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            schema = MeasurementSchema.from_legacy_dict(data)

            html_report = _generate_report_from_schema(schema, report_generator, report_type)

            manifest_path = session_dir / MANIFEST_FILENAME
            if manifest_path.exists():
                manifest = load_manifest(manifest_path)
                manifest_dict = manifest.to_dict()
            else:
                manifest_dict = None

            return html_report, manifest_dict

        except Exception as e:
            print(f"读取 legacy 格式失败: {e}")

    # 尝试读取任意 JSON 文件
    for json_file in session_dir.glob("*.json"):
        if json_file.name not in [SCHEMA_V1_FILENAME, LEGACY_FILENAME, MANIFEST_FILENAME]:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if data.get("schema_version") == "1.0":
                    schema = SchemaV1()
                    schema.from_dict(data)
                else:
                    schema = MeasurementSchema.from_legacy_dict(data)

                html_report = _generate_report_from_schema(schema, report_generator, report_type)

                manifest_path = session_dir / MANIFEST_FILENAME
                if manifest_path.exists():
                    manifest = load_manifest(manifest_path)
                    manifest_dict = manifest.to_dict()
                else:
                    manifest_dict = None

                return html_report, manifest_dict

            except Exception as e:
                print(f"读取 {json_file} 失败: {e}")

    return None, None


def _generate_report_from_schema(schema: SchemaV1, report_generator=None, report_type: str = "full_report") -> str:
    """
    从 SchemaV1 生成报告

    Args:
        schema: SchemaV1 实例
        report_generator: ReportGenerator 实例（可选）
        report_type: 报告类型

    Returns:
        str: HTML 报告内容
    """
    if report_generator:
        from .generator import ReportType

        type_map = {
            "full_report": ReportType.FULL_REPORT,
            "icc_validation": ReportType.ICC_VALIDATION,
            "lut_validation": ReportType.LUT_VALIDATION,
            "gamut_measurement": ReportType.GAMUT_MEASUREMENT,
            "gamma_analysis": ReportType.GAMMA_ANALYSIS,
            "comparison": ReportType.COMPARISON,
        }
        actual_type = type_map.get(report_type, ReportType.FULL_REPORT)

        return report_generator.generate_from_schema(schema, actual_type)
    else:
        from .generator import ReportGenerator, ReportType

        generator = ReportGenerator()

        type_map = {
            "full_report": ReportType.FULL_REPORT,
            "icc_validation": ReportType.ICC_VALIDATION,
            "lut_validation": ReportType.LUT_VALIDATION,
            "gamut_measurement": ReportType.GAMUT_MEASUREMENT,
            "gamma_analysis": ReportType.GAMMA_ANALYSIS,
            "comparison": ReportType.COMPARISON,
        }
        actual_type = type_map.get(report_type, ReportType.FULL_REPORT)

        return generator.generate_from_schema(schema, actual_type)


def get_session_info_for_report(session_id: str, measurements_dir: Path = None) -> Optional[Dict]:
    """
    获取 session 信息用于报告

    Args:
        session_id: session ID
        measurements_dir: measurements 目录（可选）

    Returns:
        Dict: session 信息
    """
    service = StorageService(measurements_dir)
    schema, manifest = service.load_session(session_id)

    if schema is None:
        return None

    info = {
        "session_id": schema.session_id,
        "created_at": schema.created_at,
        "probe": schema.instrument.probe,
        "display_model": schema.display.model,
        "display_name": schema.display.display_name,
        "workflow_mode": schema.workflow.mode,
        "workflow_target": schema.workflow.target,
        "gamma_target": schema.workflow.gamma_target,
        "white_point_target": schema.workflow.white_point_target,
        "status": schema.status,
        "notes": schema.notes,
        "has_gamut": schema.is_valid(),
        "has_gamma": len(schema.measurements.gamma) > 0,
        "has_lut": len(schema.measurements.lut_patches) > 0,
    }

    if manifest:
        info["manifest_status"] = manifest.integrity_status
        info["artifact_count"] = len(manifest.files)
        info["storage_type"] = manifest.storage_type
        info["date_dir"] = manifest.date_dir

    return info
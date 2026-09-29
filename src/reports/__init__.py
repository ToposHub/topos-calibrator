"""
Reports Module - 专业校准报告生成

提供 HTML 报告生成和导出功能，支持：
- ICC Profile 验证报告
- 3D LUT 验证报告
- 色域测量报告
- Gamma/EOTF 分析报告

报告特性：
- HTML 格式优先，可离线打开
- 内嵌 CSS 样式，无需外部依赖
- 图表使用 ECharts（内嵌或 SVG 备选）
- 自动生成于验证完成时

Backend integration:
- ReportService provides facade layer for Backend
- Backend delegates report operations to ReportService
- Backend keeps Qt signals/slots for UI communication
"""

from .generator import (
    ReportGenerator,
    ReportConfig,
    ReportType,
    generate_html_report,
    generate_pdf_report,
    ReportData,
    ValidationResult,
    ValidationSummary,
    PassStatus,
    ThresholdConfig,
)

from .report_service import ReportService

__all__ = [
    "ReportGenerator",
    "ReportConfig",
    "ReportType",
    "generate_html_report",
    "generate_pdf_report",
    "ReportData",
    "ValidationResult",
    "ValidationSummary",
    "PassStatus",
    "ThresholdConfig",
    # Backend facade
    "ReportService",
]
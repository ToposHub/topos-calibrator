"""
Report Generator - 专业校准报告生成核心

生成 HTML 格式的专业校准报告，支持：
- ICC Profile 验证报告
- 3D LUT 验证报告
- 色域测量报告
- Gamma/EOTF 分析报告

报告内容：
- 目标标准
- 设备信息
- 环境条件
- 校正文件信息
- 测量设置
- 白点、亮度、对比度
- Gamma/EOTF 分析
- 色域覆盖
- Delta E 统计
- 验证结论
"""

import json
import logging
import math
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import i18n
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# 导入数据存储模块
from ..storage.schema import SchemaV1, AnalysisInfo, MeasurementSchema
from ..storage.manifest import ArtifactManifest, load_manifest
from ..storage.storage_service import StorageService
from ..measurement_analyzer import MeasurementAnalyzer, STANDARD_GAMUTS


class ReportType(Enum):
    """报告类型"""
    ICC_VALIDATION = "icc_validation"
    LUT_VALIDATION = "lut_validation"
    GAMUT_MEASUREMENT = "gamut_measurement"
    GAMMA_ANALYSIS = "gamma_analysis"
    FULL_REPORT = "full_report"
    COMPARISON = "comparison"


class PassStatus(Enum):
    """验证通过状态"""
    PASS = "pass"           # 完全合格
    WARN = "warn"           # 警告（接近阈值）
    FAIL = "fail"           # 不合格
    NOT_TESTED = "not_tested"  # 未测试


@dataclass
class ThresholdConfig:
    """验证阈值配置（可自定义）"""
    # Delta E 阈值
    delta_e_avg_pass: float = 2.0      # 平均 Delta E 合格阈值
    delta_e_avg_warn: float = 3.0      # 平均 Delta E 警告阈值
    delta_e_max_pass: float = 4.0      # 最大 Delta E 合格阈值
    delta_e_max_warn: float = 6.0      # 最大 Delta E 警告阈值
    
    # 白点偏差阈值
    white_point_delta_e_pass: float = 2.0
    white_point_delta_e_warn: float = 4.0
    white_point_duv_pass: float = 0.005
    white_point_duv_warn: float = 0.010
    
    # Gamma 偏差阈值
    gamma_deviation_pass: float = 0.05
    gamma_deviation_warn: float = 0.10
    
    # 色域覆盖率阈值
    gamut_coverage_pass: float = 95.0  # %
    gamut_coverage_warn: float = 90.0  # %
    
    # 亮度范围阈值
    brightness_min_pass: float = 80.0  # cd/m²
    brightness_min_warn: float = 60.0  # cd/m²
    
    # 对比度阈值
    contrast_ratio_pass: float = 500.0
    contrast_ratio_warn: float = 300.0


@dataclass
class ValidationResult:
    """单个指标的验证结果"""
    metric_name: str
    value: Any
    target: Any
    deviation: Optional[float] = None
    status: PassStatus = PassStatus.NOT_TESTED
    unit: str = ""
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "value": self.value,
            "target": self.target,
            "deviation": self.deviation,
            "status": self.status.value,
            "unit": self.unit,
            "description": self.description,
        }


@dataclass
class ValidationSummary:
    """验证结果汇总"""
    overall_status: PassStatus = PassStatus.NOT_TESTED
    pass_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    results: List[ValidationResult] = field(default_factory=list)
    
    def add_result(self, result: ValidationResult):
        """添加验证结果"""
        self.results.append(result)
        if result.status == PassStatus.PASS:
            self.pass_count += 1
        elif result.status == PassStatus.WARN:
            self.warn_count += 1
        elif result.status == PassStatus.FAIL:
            self.fail_count += 1
        
        # 更新总体状态
        if self.fail_count > 0:
            self.overall_status = PassStatus.FAIL
        elif self.warn_count > 0:
            self.overall_status = PassStatus.WARN
        elif self.pass_count > 0:
            self.overall_status = PassStatus.PASS
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_status": self.overall_status.value,
            "pass_count": self.pass_count,
            "warn_count": self.warn_count,
            "fail_count": self.fail_count,
            "results": [r.to_dict() for r in self.results],
        }


@dataclass
class ReportData:
    """报告数据结构"""
    # 基本信息
    report_id: str = ""
    report_type: ReportType = ReportType.FULL_REPORT
    generated_at: str = ""
    
    # 目标标准
    target_standard: str = "sRGB"
    target_gamma: float = 2.2
    target_white_point: str = "D65"
    target_brightness: Optional[float] = None
    
    # 设备信息
    probe: str = ""
    probe_serial: str = ""
    display_type: str = ""
    display_model: str = ""
    display_name: str = ""
    display_resolution: Tuple[int, int] = (0, 0)
    display_refresh_rate: int = 0
    
    # 环境条件
    os: str = ""
    os_version: str = ""
    argyll_version: str = ""
    
    # 校正文件
    correction_file: str = ""
    correction_type: str = ""
    correction_hash: str = ""
    correction_instrument: str = ""
    correction_technology: str = ""
    
    # 测量设置
    measure_mode: str = ""
    patch_count: int = 0
    measurement_time: str = ""
    
    # 白点测量
    white_point_x: float = 0.3127
    white_point_y: float = 0.3290
    white_point_Y: float = 100.0
    white_point_cct: float = 6500.0
    white_point_duv: float = 0.0
    white_point_delta_e: float = 0.0
    
    # 亮度与对比度
    max_brightness: float = 100.0
    min_brightness: float = 0.1
    contrast_ratio: float = 1000.0
    
    # Gamma/EOTF 分析
    measured_gamma: float = 2.2
    gamma_deviation: float = 0.0
    gamma_r_squared: float = 1.0
    gamma_curve_data: List[Dict[str, float]] = field(default_factory=list)
    
    # 色域覆盖率
    gamut_coverage_percent: float = 0.0
    gamut_area_ratio_percent: float = 0.0
    measured_gamut_triangle: List[Tuple[float, float]] = field(default_factory=list)
    standard_gamut_triangle: List[Tuple[float, float]] = field(default_factory=list)
    
    # Delta E 统计
    delta_e_avg: float = 0.0
    delta_e_max: float = 0.0
    delta_e_min: float = 0.0
    delta_e_std: float = 0.0
    delta_e_95th_percentile: float = 0.0
    delta_e_distribution: Dict[str, int] = field(default_factory=dict)

    # 测量可信度与可靠性
    overall_confidence: float = 0.0           # 整体置信度评分 (0-1)
    confidence_status: str = "unknown"        # pass/warn/fail/unknown
    total_readings: int = 0                   # 总测量读数
    total_rejected: int = 0                   # 总拒绝读数
    rejection_ratio: float = 0.0              # 拒绝比例
    outlier_method_used: str = ""             # 使用的异常值剔除方法
    patch_confidence_details: List[Dict[str, Any]] = field(default_factory=list)  # 各色块置信度详情
    low_confidence_patches: List[int] = field(default_factory=list)               # 低置信度色块索引
    warmup_performed: bool = False            # 是否执行了warm-up
    warmup_stable: bool = False               # warm-up后是否稳定

    # 验证结果
    validation_summary: ValidationSummary = field(default_factory=ValidationSummary)
    
    # 备注
    # 均匀性分析（多点网格测量）
    uniformity_points: List[Dict[str, Any]] = field(default_factory=list)
    uniformity_percent: float = 0.0      # 亮度均匀性 % = (1-(Ymax-Ymin)/Ymax)*100
    uniformity_max_dev_pct: float = 0.0  # 相对中心测点的最大亮度偏差 %
    uniformity_max_duv: float = 0.0      # 相对中心测点的最大 Δu'v'

    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        data = {
            "report_id": self.report_id,
            "report_type": self.report_type.value,
            "generated_at": self.generated_at,
            "target_standard": self.target_standard,
            "target_gamma": self.target_gamma,
            "target_white_point": self.target_white_point,
            "target_brightness": self.target_brightness,
            "probe": self.probe,
            "probe_serial": self.probe_serial,
            "display_type": self.display_type,
            "display_model": self.display_model,
            "display_name": self.display_name,
            "display_resolution": list(self.display_resolution),
            "display_refresh_rate": self.display_refresh_rate,
            "os": self.os,
            "os_version": self.os_version,
            "argyll_version": self.argyll_version,
            "correction_file": self.correction_file,
            "correction_type": self.correction_type,
            "correction_hash": self.correction_hash,
            "correction_instrument": self.correction_instrument,
            "correction_technology": self.correction_technology,
            "measure_mode": self.measure_mode,
            "patch_count": self.patch_count,
            "measurement_time": self.measurement_time,
            "white_point": {
                "x": self.white_point_x,
                "y": self.white_point_y,
                "Y": self.white_point_Y,
                "cct": self.white_point_cct,
                "duv": self.white_point_duv,
                "delta_e": self.white_point_delta_e,
            },
            "brightness": {
                "max": self.max_brightness,
                "min": self.min_brightness,
            },
            "contrast_ratio": self.contrast_ratio,
            "gamma": {
                "measured": self.measured_gamma,
                "deviation": self.gamma_deviation,
                "r_squared": self.gamma_r_squared,
            },
            "gamut": {
                "coverage_percent": self.gamut_coverage_percent,
                "area_ratio_percent": self.gamut_area_ratio_percent,
                "measured_triangle": [list(p) for p in self.measured_gamut_triangle],
                "standard_triangle": [list(p) for p in self.standard_gamut_triangle],
            },
            "delta_e": {
                "avg": self.delta_e_avg,
                "max": self.delta_e_max,
                "min": self.delta_e_min,
                "std": self.delta_e_std,
                "95th_percentile": self.delta_e_95th_percentile,
                "distribution": self.delta_e_distribution,
            },
            "measurement_reliability": {
                "overall_confidence": self.overall_confidence,
                "confidence_status": self.confidence_status,
                "total_readings": self.total_readings,
                "total_rejected": self.total_rejected,
                "rejection_ratio": self.rejection_ratio,
                "outlier_method_used": self.outlier_method_used,
                "low_confidence_patches": self.low_confidence_patches,
                "warmup_performed": self.warmup_performed,
                "warmup_stable": self.warmup_stable,
            },
            "validation_summary": self.validation_summary.to_dict(),
            "notes": self.notes,
        }

        # 添加各色块置信度详情（如果有）
        if self.patch_confidence_details:
            data["measurement_reliability"]["patch_details"] = self.patch_confidence_details
        
        # 添加 Gamma 曲线数据（如果有）
        if self.gamma_curve_data:
            data["gamma_curve"] = self.gamma_curve_data
        
        return data


@dataclass
class ReportConfig:
    """报告配置"""
    title: str = "Topos Calibrator 校准报告"
    include_charts: bool = True
    include_validation: bool = True
    threshold_config: ThresholdConfig = field(default_factory=ThresholdConfig)
    output_format: str = "html"  # html, pdf
    language: str = "zh-CN"
    embed_charts_data: bool = True  # 将图表数据内嵌到 HTML


class ReportGenerator:
    """
    专业校准报告生成器
    
    支持从多种数据源生成报告：
    - SchemaV1 数据结构
    - MeasurementAnalyzer 分析结果
    - 旧格式 JSON 数据
    
    生成的 HTML 报告可离线打开，无需外部依赖。
    """
    
    def __init__(self, config: ReportConfig = None):
        """
        初始化报告生成器
        
        Args:
            config: 报告配置，默认使用标准配置
        """
        self.config = config or ReportConfig()
        self.template_path: Optional[Path] = None
        self._template_content: Optional[str] = None
    
    def set_template_path(self, template_path: str):
        """设置 HTML 模板路径"""
        self.template_path = Path(template_path)
    
    def _load_template(self) -> str:
        """加载 HTML 模板"""
        if self._template_content:
            return self._template_content
        
        # 尝试加载模板文件
        if self.template_path and self.template_path.exists():
            with open(self.template_path, 'r', encoding='utf-8') as f:
                self._template_content = f.read()
            return self._template_content
        
        # 如果没有模板文件，使用内置模板
        return self._get_builtin_template()
    
    def _get_builtin_template(self) -> str:
        """获取内置 HTML 模板"""
        # 模板较长，在文件末尾定义
        return BUILTIN_HTML_TEMPLATE
    
    def generate_from_schema(self, schema: SchemaV1, 
                             report_type: ReportType = ReportType.FULL_REPORT) -> str:
        """
        从 SchemaV1 数据结构生成 HTML 报告
        
        Args:
            schema: SchemaV1 实例
            report_type: 报告类型
            
        Returns:
            str: HTML 报告内容
        """
        # 构建 ReportData
        report_data = self._build_report_data_from_schema(schema, report_type)
        
        # 执行验证并更新报告数据
        self._validate_report_data(report_data)
        
        # 渲染 HTML
        return self._render_html(report_data)
    
    def generate_from_analyzer(self, analyzer: MeasurementAnalyzer,
                               metadata: Dict[str, Any] = None,
                               report_type: ReportType = ReportType.GAMUT_MEASUREMENT) -> str:
        """
        从 MeasurementAnalyzer 生成报告
        
        Args:
            analyzer: MeasurementAnalyzer 实例
            metadata: 元数据（探头、显示器等信息）
            report_type: 报告类型
            
        Returns:
            str: HTML 报告内容
        """
        # 构建 ReportData
        report_data = self._build_report_data_from_analyzer(analyzer, metadata)
        
        # 执行验证
        self._validate_report_data(report_data)
        
        # 渲染 HTML
        return self._render_html(report_data)
    
    def generate_from_dict(self, data: Dict[str, Any],
                           report_type: ReportType = ReportType.FULL_REPORT) -> str:
        """
        从字典数据生成报告（兼容旧格式）
        
        Args:
            data: 测量数据字典
            report_type: 报告类型
            
        Returns:
            str: HTML 报告内容
        """
        # 构建 ReportData
        report_data = self._build_report_data_from_dict(data)
        
        # 执行验证
        self._validate_report_data(report_data)
        
        # 渲染 HTML
        return self._render_html(report_data)
    
    def _build_report_data_from_schema(self, schema: SchemaV1, 
                                        report_type: ReportType) -> ReportData:
        """从 SchemaV1 构建 ReportData"""
        report_data = ReportData()
        
        # 基本信息
        report_data.report_id = schema.session_id
        report_data.report_type = report_type
        report_data.generated_at = datetime.now().isoformat()
        
        # 目标标准
        report_data.target_standard = schema.workflow.target or "sRGB"
        report_data.target_gamma = schema.workflow.gamma_target
        report_data.target_white_point = schema.workflow.white_point_target
        
        # 设备信息
        report_data.probe = schema.instrument.probe
        report_data.probe_serial = schema.instrument.probe_serial or ""
        report_data.display_type = schema.display.type
        report_data.display_model = schema.display.model
        report_data.display_name = schema.display.display_name
        report_data.display_resolution = schema.display.resolution
        report_data.display_refresh_rate = schema.display.refresh_rate
        
        # 环境
        report_data.os = schema.environment.os
        report_data.os_version = schema.environment.os_version
        report_data.argyll_version = schema.environment.argyll_version
        
        # 校正文件
        report_data.correction_file = schema.instrument.correction_file or ""
        report_data.correction_hash = schema.instrument.correction_hash or ""
        
        # 测量设置
        report_data.measure_mode = schema.workflow.mode
        report_data.measurement_time = schema.created_at
        
        # 白点测量
        gamut = schema.measurements.gamut
        if gamut.white and gamut.white.get("xyY"):
            xyY = gamut.white["xyY"]
            report_data.white_point_x = xyY[0]
            report_data.white_point_y = xyY[1]
            report_data.white_point_Y = xyY[2]
        
        # 黑场测量（用于对比度）
        if gamut.black and gamut.black.get("xyY"):
            report_data.min_brightness = gamut.black["xyY"][2]
        
        # 亮度/对比度
        report_data.max_brightness = report_data.white_point_Y
        if report_data.min_brightness > 0:
            report_data.contrast_ratio = report_data.max_brightness / report_data.min_brightness
        
        # Gamma 数据
        gamma_data = schema.measurements.gamma
        if gamma_data:
            report_data.gamma_curve_data = gamma_data
            report_data.patch_count = len(gamma_data)
        
        # 色域三角形
        if gamut.red and gamut.red.get("xyY"):
            report_data.measured_gamut_triangle.append((gamut.red["xyY"][0], gamut.red["xyY"][1]))
        if gamut.green and gamut.green.get("xyY"):
            report_data.measured_gamut_triangle.append((gamut.green["xyY"][0], gamut.green["xyY"][1]))
        if gamut.blue and gamut.blue.get("xyY"):
            report_data.measured_gamut_triangle.append((gamut.blue["xyY"][0], gamut.blue["xyY"][1]))
        
        # 标准色域三角形
        standard = report_data.target_standard
        if standard in STANDARD_GAMUTS:
            std_gamut = STANDARD_GAMUTS[standard]
            report_data.standard_gamut_triangle = [
                std_gamut["red"],
                std_gamut["green"],
                std_gamut["blue"],
            ]
        
        # 分析结果
        analysis = schema.analysis
        if analysis.gamut_coverage:
            report_data.gamut_coverage_percent = analysis.gamut_coverage.get("coverage_percent", 0)
            report_data.gamut_area_ratio_percent = analysis.gamut_coverage.get("area_ratio_percent", 0)
        
        if analysis.gamma_result:
            report_data.measured_gamma = analysis.gamma_result.get("measured_gamma", 2.2)
            report_data.gamma_deviation = analysis.gamma_result.get("deviation", 0)
            report_data.gamma_r_squared = analysis.gamma_result.get("r_squared", 1.0)
        
        if analysis.delta_e_summary:
            report_data.delta_e_avg = analysis.delta_e_summary.get("avg", 0)
            report_data.delta_e_max = analysis.delta_e_summary.get("max", 0)
            report_data.delta_e_min = analysis.delta_e_summary.get("min", 0)
            report_data.delta_e_std = analysis.delta_e_summary.get("std", 0)
            report_data.delta_e_95th_percentile = analysis.delta_e_summary.get("95th_percentile", 0)
            report_data.delta_e_distribution = analysis.delta_e_summary.get("distribution", {})
        
        if analysis.white_point_result:
            report_data.white_point_cct = analysis.white_point_result.get("cct", 6500)
            report_data.white_point_duv = analysis.white_point_result.get("duv", 0)
            report_data.white_point_delta_e = analysis.white_point_result.get("delta_e", 0)
        
        # 备注
        report_data.notes = schema.notes
        
        return report_data
    
    def _build_report_data_from_analyzer(self, analyzer: MeasurementAnalyzer,
                                          metadata: Dict[str, Any] = None) -> ReportData:
        """从 MeasurementAnalyzer 构建 ReportData"""
        report_data = ReportData()
        metadata = metadata or {}
        
        # 基本信息
        report_data.report_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "_" + os.urandom(3).hex()
        report_data.generated_at = datetime.now().isoformat()
        
        # 元数据
        report_data.probe = metadata.get("probe", "")
        report_data.display_type = metadata.get("display_type", "")
        report_data.display_model = metadata.get("display_model", "")
        report_data.target_standard = metadata.get("target_standard", "sRGB")
        report_data.target_gamma = metadata.get("target_gamma", 2.2)
        
        # 白点
        white_point = analyzer.get_white_point()
        if white_point:
            report_data.white_point_x, report_data.white_point_y = white_point
        
        # 白场亮度
        if analyzer.gamut_data.get("white"):
            report_data.white_point_Y = analyzer.gamut_data["white"].get("Y", 100)
            report_data.max_brightness = report_data.white_point_Y
        
        # 黑场亮度
        if analyzer.gamut_data.get("black"):
            report_data.min_brightness = analyzer.gamut_data["black"].get("Y", 0.1)
        
        # 对比度
        if report_data.min_brightness > 0:
            report_data.contrast_ratio = report_data.max_brightness / report_data.min_brightness
        
        # Gamma
        gamma = analyzer.calculate_gamma()
        if gamma:
            report_data.measured_gamma = gamma
            report_data.gamma_deviation = abs(gamma - report_data.target_gamma)
        
        # Gamma 曲线数据
        if analyzer.gamma_data:
            report_data.gamma_curve_data = analyzer.gamma_data
            report_data.patch_count = len(analyzer.gamma_data)
        
        # 色域三角形
        gamut_triangle = analyzer.get_gamut_triangle()
        if gamut_triangle:
            report_data.measured_gamut_triangle = gamut_triangle
        
        # 色域覆盖率
        gamut_metrics = analyzer.calculate_gamut_metrics(report_data.target_standard)
        report_data.gamut_coverage_percent = gamut_metrics.get("coverage_percent", 0)
        report_data.gamut_area_ratio_percent = gamut_metrics.get("area_ratio_percent", 0)
        
        # 标准色域三角形
        if report_data.target_standard in STANDARD_GAMUTS:
            std_gamut = STANDARD_GAMUTS[report_data.target_standard]
            report_data.standard_gamut_triangle = [
                std_gamut["red"],
                std_gamut["green"],
                std_gamut["blue"],
            ]
        
        return report_data
    
    def _build_report_data_from_dict(self, data: Dict[str, Any]) -> ReportData:
        """从字典数据构建 ReportData（兼容旧格式）"""
        report_data = ReportData()
        
        # 基本信息
        metadata = data.get("metadata", {})
        report_data.report_id = metadata.get("measurement_id", 
            datetime.now().strftime("%Y%m%d-%H%M%S") + "_" + os.urandom(3).hex())
        report_data.generated_at = datetime.now().isoformat()
        
        # 元数据
        report_data.probe = metadata.get("probe", "")
        report_data.display_type = metadata.get("display_type", "")
        report_data.display_model = metadata.get("display_model", "")
        report_data.display_name = metadata.get("display_name", "")
        report_data.measure_mode = metadata.get("measure_mode", "")
        report_data.measurement_time = metadata.get("timestamp", "")
        
        # 校正文件
        correction = metadata.get("correction_file", {})
        if isinstance(correction, dict):
            report_data.correction_file = correction.get("path", "")
            report_data.correction_hash = correction.get("hash", "")
            report_data.correction_type = correction.get("type", "")
        
        # 测量数据
        measurements = data.get("measurements", {})
        
        # 色域测量
        gamut = measurements.get("gamut", {})
        for color_name in ["red", "green", "blue", "white", "black"]:
            color_data = gamut.get(color_name)
            if color_data and color_data.get("xyY"):
                xyY = color_data["xyY"]
                x, y, Y = xyY[0], xyY[1], xyY[2]
                
                if color_name == "white":
                    report_data.white_point_x = x
                    report_data.white_point_y = y
                    report_data.white_point_Y = Y
                    report_data.max_brightness = Y
                elif color_name == "black":
                    report_data.min_brightness = Y
                elif color_name in ["red", "green", "blue"]:
                    report_data.measured_gamut_triangle.append((x, y))
        
        # 对比度
        if report_data.min_brightness > 0:
            report_data.contrast_ratio = report_data.max_brightness / report_data.min_brightness
        
        # Gamma 数据
        gamma_data = measurements.get("gamma", [])
        if gamma_data:
            report_data.gamma_curve_data = gamma_data
            report_data.patch_count = len(gamma_data)
            
            # 计算平均 Gamma（简单估计）
            # 更精确的计算需要 MeasurementAnalyzer
            gamma_values = []
            max_brightness = report_data.max_brightness or 0.0
            for point in gamma_data:
                input_level = point.get("input", 0) / 100.0
                # 无 white 测量时 max_brightness 为 0，跳过归一化避免除零
                if max_brightness <= 0:
                    break
                Y = point.get("Y", 0) / max_brightness
                # 防止除零和无效输入
                if input_level > 0.05 and Y > 0.05 and input_level < 1.0:
                    try:
                        gamma = math.log(Y) / math.log(input_level)
                        if 1.0 < gamma < 3.0:
                            gamma_values.append(gamma)
                    except (ValueError, ZeroDivisionError):
                        pass
            
            if gamma_values:
                report_data.measured_gamma = sum(gamma_values) / len(gamma_values)
        
        # 均匀性网格测点：计算相对中心的偏差与摘要指标
        uniformity_data = measurements.get("uniformity", [])
        if uniformity_data:
            def _xy_to_upvp(px, py):
                denom = -2 * px + 12 * py + 3
                if abs(denom) < 1e-9:
                    return None
                return (4 * px / denom, 9 * py / denom)

            grid = max(int(pt.get("row", 0)) for pt in uniformity_data) + 1
            center_idx = grid // 2
            center = next(
                (pt for pt in uniformity_data
                 if pt.get("row") == center_idx and pt.get("col") == center_idx),
                uniformity_data[0],
            )
            c_xy = center.get("xyY") or [0, 0, 0]
            c_uv = _xy_to_upvp(c_xy[0], c_xy[1])

            enriched = []
            worst_dev, worst_duv = 0.0, 0.0
            for pt in uniformity_data:
                xyY = pt.get("xyY") or [0, 0, 0]
                dev = (xyY[2] - c_xy[2]) / c_xy[2] * 100 if c_xy[2] > 0 else 0.0
                duv = 0.0
                uv = _xy_to_upvp(xyY[0], xyY[1])
                if uv and c_uv:
                    duv = math.hypot(uv[0] - c_uv[0], uv[1] - c_uv[1])
                worst_dev = max(worst_dev, abs(dev))
                worst_duv = max(worst_duv, duv)
                enriched.append({
                    "row": int(pt.get("row", 0)),
                    "col": int(pt.get("col", 0)),
                    "Y": xyY[2],
                    "x": xyY[0],
                    "y": xyY[1],
                    "cct": pt.get("cct"),
                    "dev_pct": round(dev, 2),
                    "duv": round(duv, 4),
                    "is_center": pt is center,
                })

            Ys = [pt["Y"] for pt in enriched]
            ymax = max(Ys) if Ys else 0
            ymin = min(Ys) if Ys else 0
            report_data.uniformity_points = enriched
            report_data.uniformity_percent = (
                (1 - (ymax - ymin) / ymax) * 100 if ymax > 0 else 0.0
            )
            report_data.uniformity_max_dev_pct = round(worst_dev, 2)
            report_data.uniformity_max_duv = round(worst_duv, 4)

        # LUT 色块数据（用于 Delta E）
        lut_patches = measurements.get("lut_patches", [])
        if lut_patches:
            report_data.patch_count = len(lut_patches)
        
        # 目标标准（默认）
        report_data.target_standard = "sRGB"
        report_data.target_gamma = 2.2
        
        # 标准色域三角形
        if report_data.target_standard in STANDARD_GAMUTS:
            std_gamut = STANDARD_GAMUTS[report_data.target_standard]
            report_data.standard_gamut_triangle = [
                std_gamut["red"],
                std_gamut["green"],
                std_gamut["blue"],
            ]
        
        return report_data
    
    def _validate_report_data(self, report_data: ReportData):
        """对报告数据进行验证并更新 validation_summary"""
        thresholds = self.config.threshold_config
        summary = report_data.validation_summary
        
        # 1. 白点验证
        if report_data.white_point_delta_e > 0:
            wp_status = self._check_threshold(
                report_data.white_point_delta_e,
                thresholds.white_point_delta_e_pass,
                thresholds.white_point_delta_e_warn,
            )
            summary.add_result(ValidationResult(
                metric_name=i18n.t("白点 Delta E"),
                value=report_data.white_point_delta_e,
                target=0,
                deviation=report_data.white_point_delta_e,
                status=wp_status,
                unit="",
                description=i18n.t("白点与目标 {target} 的偏差", target=report_data.target_white_point),
            ))
        
        # 2. 白点 Duv
        if abs(report_data.white_point_duv) > 0:
            duv_status = self._check_threshold(
                abs(report_data.white_point_duv),
                thresholds.white_point_duv_pass,
                thresholds.white_point_duv_warn,
            )
            summary.add_result(ValidationResult(
                metric_name=i18n.t("白点 Duv"),
                value=report_data.white_point_duv,
                target=0,
                deviation=abs(report_data.white_point_duv),
                status=duv_status,
                unit="",
                description=i18n.t("白点偏离普朗克轨迹的距离"),
            ))
        
        # 3. Gamma 偏差
        if report_data.gamma_deviation > 0:
            gamma_status = self._check_threshold(
                report_data.gamma_deviation,
                thresholds.gamma_deviation_pass,
                thresholds.gamma_deviation_warn,
            )
            summary.add_result(ValidationResult(
                metric_name=i18n.t("Gamma 偏差"),
                value=report_data.measured_gamma,
                target=report_data.target_gamma,
                deviation=report_data.gamma_deviation,
                status=gamma_status,
                unit="",
                description=i18n.t("EOTF 与目标 Gamma {gamma} 的偏差", gamma=report_data.target_gamma),
            ))
        
        # 4. 色域覆盖率
        if report_data.gamut_coverage_percent > 0:
            coverage_status = self._check_threshold(
                report_data.gamut_coverage_percent,
                thresholds.gamut_coverage_pass,
                thresholds.gamut_coverage_warn,
                reverse=True,  # 越高越好
            )
            summary.add_result(ValidationResult(
                metric_name=i18n.t("色域覆盖率"),
                value=report_data.gamut_coverage_percent,
                target=100,
                deviation=100 - report_data.gamut_coverage_percent,
                status=coverage_status,
                unit="%",
                description=i18n.t("对 {standard} 色域的覆盖程度", standard=report_data.target_standard),
            ))
        
        # 5. Delta E 平均值
        if report_data.delta_e_avg > 0:
            de_avg_status = self._check_threshold(
                report_data.delta_e_avg,
                thresholds.delta_e_avg_pass,
                thresholds.delta_e_avg_warn,
            )
            summary.add_result(ValidationResult(
                metric_name=i18n.t("平均 Delta E"),
                value=report_data.delta_e_avg,
                target=0,
                deviation=report_data.delta_e_avg,
                status=de_avg_status,
                unit="",
                description=i18n.t("所有色块的平均色彩偏差"),
            ))
        
        # 6. Delta E 最大值
        if report_data.delta_e_max > 0:
            de_max_status = self._check_threshold(
                report_data.delta_e_max,
                thresholds.delta_e_max_pass,
                thresholds.delta_e_max_warn,
            )
            summary.add_result(ValidationResult(
                metric_name=i18n.t("最大 Delta E"),
                value=report_data.delta_e_max,
                target=0,
                deviation=report_data.delta_e_max,
                status=de_max_status,
                unit="",
                description=i18n.t("最差色块的色彩偏差"),
            ))
        
        # 7. 亮度
        if report_data.max_brightness > 0:
            brightness_status = self._check_threshold(
                report_data.max_brightness,
                thresholds.brightness_min_pass,
                thresholds.brightness_min_warn,
                reverse=True,
            )
            summary.add_result(ValidationResult(
                metric_name=i18n.t("峰值亮度"),
                value=report_data.max_brightness,
                target=thresholds.brightness_min_pass,
                deviation=report_data.max_brightness - thresholds.brightness_min_pass,
                status=brightness_status,
                unit="cd/m²",
                description=i18n.t("显示器峰值亮度"),
            ))
        
        # 8. 对比度
        if report_data.contrast_ratio > 0:
            contrast_status = self._check_threshold(
                report_data.contrast_ratio,
                thresholds.contrast_ratio_pass,
                thresholds.contrast_ratio_warn,
                reverse=True,
            )
            summary.add_result(ValidationResult(
                metric_name=i18n.t("对比度"),
                value=report_data.contrast_ratio,
                target=thresholds.contrast_ratio_pass,
                deviation=report_data.contrast_ratio - thresholds.contrast_ratio_pass,
                status=contrast_status,
                unit=":1",
                description=i18n.t("白场/黑场亮度比值"),
            ))
    
    def _check_threshold(self, value: float, pass_threshold: float,
                          warn_threshold: float, reverse: bool = False) -> PassStatus:
        """
        检查值是否符合阈值
        
        Args:
            value: 测量值
            pass_threshold: 合格阈值
            warn_threshold: 警告阈值
            reverse: 是否反向（越大越好）
        
        Returns:
            PassStatus: 通过状态
        """
        if reverse:
            # 越大越好
            if value >= pass_threshold:
                return PassStatus.PASS
            elif value >= warn_threshold:
                return PassStatus.WARN
            else:
                return PassStatus.FAIL
        else:
            # 越小越好
            if value <= pass_threshold:
                return PassStatus.PASS
            elif value <= warn_threshold:
                return PassStatus.WARN
            else:
                return PassStatus.FAIL
    
    def _localize_template(self, template: str) -> str:
        """
        按当前语言本地化报告模板（含内嵌图表 JS 的静态文案）。

        词源于 src/reports/report_locales/<lang>.json，key 为模板原文（含 {{占位符}}），
        因此必须在变量替换之前执行。zh-CN（源语言）直接返回原模板。
        """
        lang = i18n.get_language()
        if lang == i18n.DEFAULT_LANGUAGE:
            return template
        mapping = self._load_report_locale(lang)
        if not mapping:
            return template
        # 长键优先，避免短键破坏长键匹配
        for key in sorted(mapping, key=len, reverse=True):
            template = template.replace(key, mapping[key])
        return template

    def _load_report_locale(self, lang: str) -> Dict[str, str]:
        """加载报告语言包（带缓存；缺失时返回空字典）"""
        if getattr(self, "_report_locale_lang", None) == lang:
            return self._report_locale_cache
        path = Path(__file__).parent / "report_locales" / f"{lang}.json"
        mapping: Dict[str, str] = {}
        if path.exists():
            try:
                mapping = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                mapping = {}
        self._report_locale_lang = lang
        self._report_locale_cache = mapping
        return mapping

    def _render_html(self, report_data: ReportData) -> str:
        """
        渲染 HTML 报告
        
        Args:
            report_data: 报告数据
        
        Returns:
            str: HTML 内容
        """
        template = self._load_template()
        template = self._localize_template(template)
        
        # 构建替换变量
        data_json = json.dumps(report_data.to_dict(), indent=2, ensure_ascii=False)
        
        # 格式化数值
        def format_value(val, unit="", precision=2):
            if isinstance(val, float):
                return f"{val:.{precision}f}{unit}"
            return f"{val}{unit}"
        
        # 状态徽章颜色
        status_colors = {
            "pass": "#28a745",
            "warn": "#ffc107",
            "fail": "#dc3545",
            "not_tested": "#6c757d",
        }
        
        overall_status = report_data.validation_summary.overall_status.value
        overall_color = status_colors.get(overall_status, "#6c757d")
        
        # 验证结果列表
        validation_html = self._render_validation_results(report_data.validation_summary)
        
        # Gamma 曲线图表数据
        gamma_chart_data = self._prepare_gamma_chart_data(report_data)
        
        # 色域图表数据
        gamut_chart_data = self._prepare_gamut_chart_data(report_data)
        
        # Delta E 分布图表数据
        delta_e_chart_data = self._prepare_delta_e_chart_data(report_data)
        
        # 替换模板变量
        html = template.replace("{{REPORT_TITLE}}", i18n.t(self.config.title))
        html = html.replace("{{REPORT_ID}}", report_data.report_id)
        html = html.replace("{{GENERATED_AT}}", report_data.generated_at)
        html = html.replace("{{TARGET_STANDARD}}", report_data.target_standard)
        html = html.replace("{{TARGET_GAMMA}}", format_value(report_data.target_gamma, "", 1))
        html = html.replace("{{TARGET_WHITE_POINT}}", report_data.target_white_point)
        html = html.replace("{{PROBE}}", report_data.probe or i18n.t("未指定"))
        html = html.replace("{{DISPLAY_MODEL}}", report_data.display_model or i18n.t("未指定"))
        html = html.replace("{{DISPLAY_NAME}}", report_data.display_name or report_data.display_model or i18n.t("未指定"))
        html = html.replace("{{OS}}", report_data.os or i18n.t("未知"))
        html = html.replace("{{ARGYLL_VERSION}}", report_data.argyll_version or i18n.t("未知"))
        html = html.replace("{{CORRECTION_FILE}}", report_data.correction_file or i18n.t("未使用"))
        html = html.replace("{{CORRECTION_TYPE}}", report_data.correction_type or "")
        html = html.replace("{{WHITE_POINT_X}}", format_value(report_data.white_point_x, "", 4))
        html = html.replace("{{WHITE_POINT_Y}}", format_value(report_data.white_point_y, "", 4))
        html = html.replace("{{WHITE_POINT_Y}}", format_value(report_data.white_point_Y, " cd/m²", 1))
        html = html.replace("{{WHITE_POINT_CCT}}", format_value(report_data.white_point_cct, " K", 0))
        html = html.replace("{{WHITE_POINT_DUV}}", format_value(report_data.white_point_duv, "", 4))
        html = html.replace("{{WHITE_POINT_DELTA_E}}", format_value(report_data.white_point_delta_e, "", 2))
        html = html.replace("{{MAX_BRIGHTNESS}}", format_value(report_data.max_brightness, " cd/m²", 1))
        html = html.replace("{{MIN_BRIGHTNESS}}", format_value(report_data.min_brightness, " cd/m²", 3))
        html = html.replace("{{CONTRAST_RATIO}}", format_value(report_data.contrast_ratio, ":1", 0))
        html = html.replace("{{MEASURED_GAMMA}}", format_value(report_data.measured_gamma, "", 2))
        html = html.replace("{{GAMMA_DEVIATION}}", format_value(report_data.gamma_deviation, "", 3))
        html = html.replace("{{GAMUT_COVERAGE}}", format_value(report_data.gamut_coverage_percent, "%", 1))
        html = html.replace("{{GAMUT_AREA_RATIO}}", format_value(report_data.gamut_area_ratio_percent, "%", 1))
        html = html.replace("{{DELTA_E_AVG}}", format_value(report_data.delta_e_avg, "", 2))
        html = html.replace("{{DELTA_E_MAX}}", format_value(report_data.delta_e_max, "", 2))
        html = html.replace("{{DELTA_E_95TH}}", format_value(report_data.delta_e_95th_percentile, "", 2))
        html = html.replace("{{OVERALL_STATUS}}", overall_status.upper())
        html = html.replace("{{OVERALL_COLOR}}", overall_color)
        html = html.replace("{{PASS_COUNT}}", str(report_data.validation_summary.pass_count))
        html = html.replace("{{WARN_COUNT}}", str(report_data.validation_summary.warn_count))
        html = html.replace("{{FAIL_COUNT}}", str(report_data.validation_summary.fail_count))
        html = html.replace("{{VALIDATION_RESULTS}}", validation_html)
        html = html.replace("{{GAMMA_CHART_DATA}}", json.dumps(gamma_chart_data, ensure_ascii=False))
        html = html.replace("{{GAMUT_CHART_DATA}}", json.dumps(gamut_chart_data, ensure_ascii=False))
        html = html.replace("{{DELTA_E_CHART_DATA}}", json.dumps(delta_e_chart_data, ensure_ascii=False))
        html = html.replace("{{REPORT_DATA_JSON}}", data_json)
        html = html.replace("{{NOTES}}", report_data.notes or i18n.t("无备注"))
        html = html.replace("{{UNIFORMITY_SECTION}}", self._render_uniformity_section(report_data))
        
        return html

    @staticmethod
    def _render_uniformity_section(report_data: ReportData) -> str:
        """
        渲染均匀性分析段（无测点数据时返回空字符串，段落整体隐藏）
        """
        points = getattr(report_data, "uniformity_points", [])
        if not points:
            return ""

        def dev_color(dev):
            a = abs(dev)
            if a <= 3:
                return "#10b981"
            if a <= 5:
                return "#84cc16"
            if a <= 10:
                return "#f59e0b"
            return "#ef4444"

        grid = max(p["row"] for p in points) + 1
        grid = max(grid, max(p["col"] for p in points) + 1)

        cell_map = {(p["row"], p["col"]): p for p in points}

        rows_html = ""
        for r in range(grid):
            cells = ""
            for c in range(grid):
                pt = cell_map.get((r, c))
                if pt is None:
                    cells += (
                        '<td style="background:#2a2a3d;color:#8888a0;'
                        'text-align:center;padding:8px 6px;">--</td>'
                    )
                    continue
                sign = "+" if pt["dev_pct"] > 0 else ""
                cct_txt = f"{pt['cct']}K" if pt.get("cct") else "--"
                border = (
                    'border:2px solid #ffffff;'
                    if pt.get("is_center") else 'border:1px solid rgba(255,255,255,0.25);'
                )
                cells += (
                    f'<td style="background:{dev_color(pt["dev_pct"])};color:#ffffff;'
                    f'text-align:center;padding:8px 6px;{border}">'
                    f'<div style="font-weight:600;">{sign}{pt["dev_pct"]:.1f}%</div>'
                    f'<div style="font-size:11px;opacity:.9;">{pt["Y"]:.1f} nit · {cct_txt}</div>'
                    f'<div style="font-size:10px;opacity:.8;">Δu\'v\' {pt["duv"]:.4f}</div>'
                    f"</td>"
                )
            rows_html += f"<tr>{cells}</tr>"

        return f"""
        <div class="section">
            <h2>均匀性分析（{grid}×{grid} 网格）</h2>
            <div class="info-grid">
                <div class="info-item">
                    <label>亮度均匀性</label>
                    <value>{report_data.uniformity_percent:.1f}%</value>
                </div>
                <div class="info-item">
                    <label>最大亮度偏差（相对中心）</label>
                    <value>{report_data.uniformity_max_dev_pct:.1f}%</value>
                </div>
                <div class="info-item">
                    <label>最大 Δu'v'（相对中心）</label>
                    <value>{report_data.uniformity_max_duv:.4f}</value>
                </div>
            </div>
            <p style="color:#666;font-size:12px;margin:8px 0;">
                各单元格为相对中心测点（白框标注）的亮度偏差；绿色 ≤3%、黄绿 ≤5%、橙 ≤10%、红 &gt;10%。
            </p>
            <table style="border-collapse:collapse;width:100%;max-width:640px;margin:0 auto;">
                {rows_html}
            </table>
        </div>
        """
    
    def _render_validation_results(self, summary: ValidationSummary) -> str:
        """渲染验证结果表格"""
        if not summary.results:
            return "<p>" + i18n.t("暂无验证结果") + "</p>"
        
        rows = []
        for result in summary.results:
            status_class = result.status.value
            status_text = {
                "pass": i18n.t("合格"),
                "warn": i18n.t("警告"),
                "fail": i18n.t("不合格"),
                "not_tested": i18n.t("未测试"),
            }.get(status_class, i18n.t("未知"))
            
            row = f"""
            <tr class="validation-{status_class}">
                <td>{result.metric_name}</td>
                <td>{result.value}{result.unit}</td>
                <td>{result.target}{result.unit}</td>
                <td>{result.deviation if result.deviation is not None else 'N/A'}</td>
                <td><span class="status-badge {status_class}">{status_text}</span></td>
                <td>{result.description}</td>
            </tr>
            """
            rows.append(row)
        
        return "\n".join(rows)
    
    def _prepare_gamma_chart_data(self, report_data: ReportData) -> Dict:
        """准备 Gamma 曲线图表数据"""
        if not report_data.gamma_curve_data:
            return {"input": [], "measured": [], "target": []}
        
        inputs = []
        measured = []
        target = []
        
        for point in report_data.gamma_curve_data:
            input_level = point.get("input", 0) / 100.0
            Y = point.get("Y", 0)
            
            inputs.append(input_level)
            measured.append(Y / report_data.max_brightness if report_data.max_brightness > 0 else Y)
            
            # 目标曲线
            target_Y = input_level ** report_data.target_gamma
            target.append(target_Y)
        
        return {
            "input": inputs,
            "measured": measured,
            "target": target,
            "max_brightness": report_data.max_brightness,
            "target_gamma": report_data.target_gamma,
        }
    
    def _prepare_gamut_chart_data(self, report_data: ReportData) -> Dict:
        """准备色域图表数据"""
        measured_points = []
        for point in report_data.measured_gamut_triangle:
            measured_points.append({"x": point[0], "y": point[1]})
        
        standard_points = []
        for point in report_data.standard_gamut_triangle:
            standard_points.append({"x": point[0], "y": point[1]})
        
        # 白点
        white_point = {
            "x": report_data.white_point_x,
            "y": report_data.white_point_y,
        }
        
        # 目标白点
        target_white_point = {
            "x": 0.3127 if report_data.target_white_point == "D65" else 0.3457,
            "y": 0.3290 if report_data.target_white_point == "D65" else 0.3585,
        }
        
        return {
            "measured": measured_points,
            "standard": standard_points,
            "white_point": white_point,
            "target_white_point": target_white_point,
            "coverage": report_data.gamut_coverage_percent,
            "area_ratio": report_data.gamut_area_ratio_percent,
        }
    
    def _prepare_delta_e_chart_data(self, report_data: ReportData) -> Dict:
        """准备 Delta E 分布图表数据"""
        distribution = report_data.delta_e_distribution or {}
        
        # 如果没有分布数据，生成默认分布
        if not distribution:
            # 根据统计值估计分布
            bins = ["<1", "1-2", "2-3", "3-4", ">4"]
            counts = [0, 0, 0, 0, 0]
            distribution = dict(zip(bins, counts))
        
        return {
            "distribution": distribution,
            "avg": report_data.delta_e_avg,
            "max": report_data.delta_e_max,
            "95th": report_data.delta_e_95th_percentile,
        }
    
    def save_report(self, html_content: str, output_path: str) -> bool:
        """
        保存 HTML 报告到文件
        
        Args:
            html_content: HTML 内容
            output_path: 输出文件路径
        
        Returns:
            bool: 是否成功保存
        """
        try:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            print(i18n.t("报告已保存: {path}", path=path))
            return True
        except Exception as e:
            print(i18n.t("保存报告失败: {e}", e=e))
            return False
    
    def export_json_data(self, report_data: ReportData) -> str:
        """导出报告数据为 JSON 格式"""
        return json.dumps(report_data.to_dict(), indent=2, ensure_ascii=False)


# ========== 便捷函数 ==========

def generate_html_report(data: Any, 
                         report_type: ReportType = ReportType.FULL_REPORT,
                         config: ReportConfig = None) -> str:
    """
    快捷函数：生成 HTML 报告
    
    Args:
        data: 数据源（SchemaV1、MeasurementAnalyzer 或 dict）
        report_type: 报告类型
        config: 报告配置
    
    Returns:
        str: HTML 报告内容
    """
    generator = ReportGenerator(config)
    
    if isinstance(data, SchemaV1):
        return generator.generate_from_schema(data, report_type)
    elif isinstance(data, MeasurementAnalyzer):
        return generator.generate_from_analyzer(data)
    elif isinstance(data, dict):
        return generator.generate_from_dict(data, report_type)
    else:
        raise ValueError(f"不支持的数据类型: {type(data)}")


def generate_pdf_report(html_content: str, output_path: str) -> bool:
    """
    生成 PDF 报告（weasyprint 渲染引擎，P4 修复）

    渲染链：HTML → weasyprint → PDF。
    已知限制：weasyprint 不执行 JavaScript，模板中的 ECharts 图表区域
    在 PDF 中为空白；数据表与文字指标完整保留。

    Args:
        html_content: HTML 内容
        output_path: PDF 输出路径

    Returns:
        bool: 是否成功生成
    """
    # 为 weasyprint 注入 CJK 字体栈（其默认无中文字体回退）
    try:
        head = html_content.split("</head>", 1)[0]
        has_cjk_font = any(
            f in head for f in ("PingFang", "Hiragino", "YaHei", "Noto Sans CJK")
        )
    except Exception:
        has_cjk_font = False
    if not has_cjk_font:
        html_content = html_content.replace(
            "<head>",
            "<head><style>body{font-family:'PingFang SC','Hiragino Sans GB',"
            "'Microsoft YaHei','Noto Sans CJK SC',sans-serif;}</style>",
            1,
        )

    try:
        from weasyprint import HTML
        HTML(string=html_content).write_pdf(output_path)
        return True
    except ImportError:
        logger.error(i18n.t("PDF 导出失败: weasyprint 未安装 (pip install weasyprint)"))
        return False
    except Exception as e:
        logger.error(i18n.t("PDF 导出失败: {e}", e=e))
        return False


# ========== 内置 HTML 模板 ==========

BUILTIN_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{REPORT_TITLE}} - {{REPORT_ID}}</title>
    <style>
        /* 基础样式 */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, 
                         "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            padding: 20px;
        }
        
        .report-container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        /* 标题样式 */
        .header {
            text-align: center;
            border-bottom: 2px solid #007bff;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }
        
        .header h1 {
            color: #007bff;
            font-size: 28px;
            margin-bottom: 10px;
        }
        
        .header .meta {
            color: #666;
            font-size: 14px;
        }
        
        /* 总体状态 */
        .overall-status {
            text-align: center;
            padding: 20px;
            margin-bottom: 30px;
            border-radius: 8px;
        }
        
        .overall-status.pass {
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white;
        }
        
        .overall-status.warn {
            background: linear-gradient(135deg, #ffc107 0%, #fd7e14 100%);
            color: white;
        }
        
        .overall-status.fail {
            background: linear-gradient(135deg, #dc3545 0%, #c82333 100%);
            color: white;
        }
        
        .overall-status h2 {
            font-size: 24px;
            margin-bottom: 10px;
        }
        
        .overall-status .counts {
            font-size: 16px;
        }
        
        /* 分区样式 */
        .section {
            margin-bottom: 30px;
        }
        
        .section h2 {
            color: #007bff;
            font-size: 20px;
            border-bottom: 1px solid #ddd;
            padding-bottom: 10px;
            margin-bottom: 15px;
        }
        
        .section h3 {
            color: #333;
            font-size: 16px;
            margin-bottom: 10px;
        }
        
        /* 信息网格 */
        .info-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
        }
        
        .info-item {
            padding: 10px;
            background: #f8f9fa;
            border-radius: 4px;
        }
        
        .info-item label {
            color: #666;
            font-size: 12px;
            display: block;
            margin-bottom: 5px;
        }
        
        .info-item value {
            color: #333;
            font-size: 14px;
            font-weight: 500;
        }
        
        /* 数值卡片 */
        .metric-card {
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }
        
        .metric-card .value {
            font-size: 32px;
            font-weight: bold;
            color: #007bff;
        }
        
        .metric-card .unit {
            font-size: 14px;
            color: #666;
        }
        
        .metric-card .label {
            font-size: 12px;
            color: #666;
            margin-top: 5px;
        }
        
        /* 验证结果表格 */
        .validation-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }
        
        .validation-table th,
        .validation-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        
        .validation-table th {
            background: #007bff;
            color: white;
            font-weight: 500;
        }
        
        .validation-table tr:hover {
            background: #f8f9fa;
        }
        
        .validation-pass {
            background: rgba(40, 167, 69, 0.1);
        }
        
        .validation-warn {
            background: rgba(255, 193, 7, 0.1);
        }
        
        .validation-fail {
            background: rgba(220, 53, 69, 0.1);
        }
        
        /* 状态徽章 */
        .status-badge {
            padding: 4px 12px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 500;
        }
        
        .status-badge.pass {
            background: #28a745;
            color: white;
        }
        
        .status-badge.warn {
            background: #ffc107;
            color: #333;
        }
        
        .status-badge.fail {
            background: #dc3545;
            color: white;
        }
        
        .status-badge.not_tested {
            background: #6c757d;
            color: white;
        }
        
        /* 图表容器 */
        .chart-container {
            height: 400px;
            margin: 20px 0;
            border: 1px solid #ddd;
            border-radius: 8px;
            background: #f8f9fa;
        }
        
        /* 图表替代显示（无 ECharts 时） */
        .chart-placeholder {
            height: 400px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #666;
            font-size: 14px;
        }
        
        /* 数据表格 */
        .data-section {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
        }
        
        .data-section h3 {
            font-size: 14px;
            color: #666;
            margin-bottom: 10px;
        }
        
        .raw-data {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 4px;
            font-family: monospace;
            font-size: 12px;
            overflow-x: auto;
            max-height: 300px;
        }
        
        /* 页脚 */
        .footer {
            text-align: center;
            color: #666;
            font-size: 12px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            margin-top: 30px;
        }
        
        /* 响应式 */
        @media print {
            body {
                background: white;
                padding: 0;
            }
            
            .report-container {
                box-shadow: none;
                padding: 20px;
            }
            
            .chart-container {
                height: 300px;
            }
            
            .raw-data {
                display: none;
            }
        }
        
        @media (max-width: 768px) {
            .info-grid {
                grid-template-columns: 1fr;
            }
            
            .report-container {
                padding: 20px;
            }
        }
    </style>
</head>
<body>
    <div class="report-container">
        <!-- 标题 -->
        <div class="header">
            <h1>{{REPORT_TITLE}}</h1>
            <div class="meta">
                报告编号: {{REPORT_ID}} | 
                生成时间: {{GENERATED_AT}} |
                目标标准: {{TARGET_STANDARD}}
            </div>
        </div>
        
        <!-- 总体状态 -->
        <div class="overall-status {{OVERALL_STATUS}}" style="background: {{OVERALL_COLOR}};">
            <h2>验证结果: {{OVERALL_STATUS}}</h2>
            <div class="counts">
                合格: {{PASS_COUNT}} | 警告: {{WARN_COUNT}} | 不合格: {{FAIL_COUNT}}
            </div>
        </div>
        
        <!-- 目标标准 -->
        <div class="section">
            <h2>目标标准</h2>
            <div class="info-grid">
                <div class="info-item">
                    <label>色域标准</label>
                    <value>{{TARGET_STANDARD}}</value>
                </div>
                <div class="info-item">
                    <label>Gamma 目标</label>
                    <value>{{TARGET_GAMMA}}</value>
                </div>
                <div class="info-item">
                    <label>白点目标</label>
                    <value>{{TARGET_WHITE_POINT}}</value>
                </div>
                <div class="info-item">
                    <label>测量模式</label>
                    <value>{{REPORT_TYPE}}</value>
                </div>
            </div>
        </div>
        
        <!-- 均匀性分析（有测点数据时渲染） -->
        {{UNIFORMITY_SECTION}}

        <!-- 设备信息 -->
        <div class="section">
            <h2>设备信息</h2>
            <div class="info-grid">
                <div class="info-item">
                    <label>探头</label>
                    <value>{{PROBE}}</value>
                </div>
                <div class="info-item">
                    <label>显示器型号</label>
                    <value>{{DISPLAY_MODEL}}</value>
                </div>
                <div class="info-item">
                    <label>显示器名称</label>
                    <value>{{DISPLAY_NAME}}</value>
                </div>
                <div class="info-item">
                    <label>操作系统</label>
                    <value>{{OS}}</value>
                </div>
                <div class="info-item">
                    <label>ArgyllCMS 版本</label>
                    <value>{{ARGYLL_VERSION}}</value>
                </div>
                <div class="info-item">
                    <label>校正文件</label>
                    <value>{{CORRECTION_FILE}}</value>
                </div>
            </div>
        </div>
        
        <!-- 白点测量 -->
        <div class="section">
            <h2>白点测量</h2>
            <div class="info-grid">
                <div class="metric-card">
                    <div class="value">{{WHITE_POINT_CCT}}</div>
                    <div class="unit">K</div>
                    <div class="label">相关色温</div>
                </div>
                <div class="metric-card">
                    <div class="value">{{WHITE_POINT_DUV}}</div>
                    <div class="unit"></div>
                    <div class="label">Duv 偏移</div>
                </div>
                <div class="info-item">
                    <label>xy 坐标</label>
                    <value>({{WHITE_POINT_X}}, {{WHITE_POINT_Y}})</value>
                </div>
                <div class="info-item">
                    <label>亮度</label>
                    <value>{{WHITE_POINT_Y_VALUE}} cd/m²</value>
                </div>
            </div>
        </div>
        
        <!-- 亮度与对比度 -->
        <div class="section">
            <h2>亮度与对比度</h2>
            <div class="info-grid">
                <div class="metric-card">
                    <div class="value">{{MAX_BRIGHTNESS}}</div>
                    <div class="unit">cd/m²</div>
                    <div class="label">峰值亮度</div>
                </div>
                <div class="metric-card">
                    <div class="value">{{MIN_BRIGHTNESS}}</div>
                    <div class="unit">cd/m²</div>
                    <div class="label">黑场亮度</div>
                </div>
                <div class="metric-card">
                    <div class="value">{{CONTRAST_RATIO}}</div>
                    <div class="unit"></div>
                    <div class="label">对比度</div>
                </div>
            </div>
        </div>
        
        <!-- Gamma/EOTF -->
        <div class="section">
            <h2>Gamma/EOTF 分析</h2>
            <div class="info-grid">
                <div class="metric-card">
                    <div class="value">{{MEASURED_GAMMA}}</div>
                    <div class="unit"></div>
                    <div class="label">测量 Gamma</div>
                </div>
                <div class="metric-card">
                    <div class="value">{{GAMMA_DEVIATION}}</div>
                    <div class="unit"></div>
                    <div class="label">与目标偏差</div>
                </div>
            </div>
            
            <h3>EOTF 曲线</h3>
            <div class="chart-container" id="gamma-chart">
                <!-- 图表将通过 JavaScript 渲染 -->
                <div class="chart-placeholder">
                    Gamma 曲线图表（需要 ECharts 支持）
                </div>
            </div>
        </div>
        
        <!-- 色域覆盖 -->
        <div class="section">
            <h2>色域覆盖</h2>
            <div class="info-grid">
                <div class="metric-card">
                    <div class="value">{{GAMUT_COVERAGE}}</div>
                    <div class="unit">%</div>
                    <div class="label">覆盖率</div>
                </div>
                <div class="metric-card">
                    <div class="value">{{GAMUT_AREA_RATIO}}</div>
                    <div class="unit">%</div>
                    <div class="label">面积比</div>
                </div>
            </div>
            
            <h3>色域三角形</h3>
            <div class="chart-container" id="gamut-chart">
                <div class="chart-placeholder">
                    色域三角形图表（需要 ECharts 支持）
                </div>
            </div>
        </div>
        
        <!-- Delta E 统计 -->
        <div class="section">
            <h2>Delta E 统计</h2>
            <div class="info-grid">
                <div class="metric-card">
                    <div class="value">{{DELTA_E_AVG}}</div>
                    <div class="unit"></div>
                    <div class="label">平均 ΔE</div>
                </div>
                <div class="metric-card">
                    <div class="value">{{DELTA_E_MAX}}</div>
                    <div class="unit"></div>
                    <div class="label">最大 ΔE</div>
                </div>
                <div class="metric-card">
                    <div class="value">{{DELTA_E_95TH}}</div>
                    <div class="unit"></div>
                    <div class="label">95分位 ΔE</div>
                </div>
            </div>
            
            <h3>Delta E 分布</h3>
            <div class="chart-container" id="delta-e-chart">
                <div class="chart-placeholder">
                    Delta E 分布图表（需要 ECharts 支持）
                </div>
            </div>
        </div>
        
        <!-- 验证结果详情 -->
        <div class="section">
            <h2>验证结果详情</h2>
            <table class="validation-table">
                <thead>
                    <tr>
                        <th>指标</th>
                        <th>测量值</th>
                        <th>目标值</th>
                        <th>偏差</th>
                        <th>状态</th>
                        <th>说明</th>
                    </tr>
                </thead>
                <tbody>
                    {{VALIDATION_RESULTS}}
                </tbody>
            </table>
        </div>
        
        <!-- 备注 -->
        <div class="section">
            <h2>备注</h2>
            <p>{{NOTES}}</p>
        </div>
        
        <!-- 原始数据 -->
        <div class="data-section">
            <h3>原始数据 (JSON)</h3>
            <div class="raw-data">
                <pre>{{REPORT_DATA_JSON}}</pre>
            </div>
        </div>
        
        <!-- 页脚 -->
        <div class="footer">
            本报告由 Topos Calibrator 自动生成 |
            报告可离线打开，无需外部依赖 |
            如需 PDF，请使用浏览器打印功能
        </div>
    </div>
    
    <!-- ECharts 图表渲染（可选） -->
    <script>
        // 图表数据（内嵌）
        const gammaChartData = {{GAMMA_CHART_DATA}};
        const gamutChartData = {{GAMUT_CHART_DATA}};
        const deltaEChartData = {{DELTA_E_CHART_DATA}};
        
        // 如果 ECharts 可用，渲染图表
        if (typeof echarts !== 'undefined') {
            // Gamma 曲线图
            const gammaChart = echarts.init(document.getElementById('gamma-chart'));
            gammaChart.setOption({
                title: { text: 'EOTF 曲线', left: 'center' },
                tooltip: { trigger: 'axis' },
                legend: { data: ['实测', '目标'], top: 30 },
                xAxis: { 
                    type: 'value',
                    name: '输入 (%)',
                    min: 0, max: 1
                },
                yAxis: {
                    type: 'value',
                    name: '亮度 (归一化)',
                    min: 0, max: 1
                },
                series: [
                    {
                        name: '实测',
                        type: 'line',
                        data: gammaChartData.input.map((x, i) => [x, gammaChartData.measured[i]]),
                        smooth: true,
                        lineStyle: { color: '#007bff' }
                    },
                    {
                        name: '目标',
                        type: 'line',
                        data: gammaChartData.input.map((x, i) => [x, gammaChartData.target[i]]),
                        smooth: true,
                        lineStyle: { color: '#28a745', type: 'dashed' }
                    }
                ]
            });
            
            // 色域三角形图
            const gamutChart = echarts.init(document.getElementById('gamut-chart'));
            gamutChart.setOption({
                title: { text: '色域三角形', left: 'center' },
                tooltip: { trigger: 'item' },
                xAxis: { 
                    type: 'value',
                    name: 'x',
                    min: 0, max: 0.8
                },
                yAxis: {
                    type: 'value',
                    name: 'y',
                    min: 0, max: 0.9
                },
                series: [
                    {
                        name: '测量色域',
                        type: 'line',
                        data: gamutChartData.measured.map(p => [p.x, p.y]),
                        lineStyle: { color: '#007bff', width: 2 },
                        areaStyle: { color: 'rgba(0, 123, 255, 0.2)' }
                    },
                    {
                        name: '标准色域',
                        type: 'line',
                        data: gamutChartData.standard.map(p => [p.x, p.y]),
                        lineStyle: { color: '#28a745', width: 2, type: 'dashed' },
                        areaStyle: { color: 'rgba(40, 167, 69, 0.1)' }
                    },
                    {
                        name: '测量白点',
                        type: 'scatter',
                        data: [[gamutChartData.white_point.x, gamutChartData.white_point.y]],
                        symbolSize: 10,
                        itemStyle: { color: '#dc3545' }
                    },
                    {
                        name: '目标白点',
                        type: 'scatter',
                        data: [[gamutChartData.target_white_point.x, gamutChartData.target_white_point.y]],
                        symbolSize: 10,
                        itemStyle: { color: '#ffc107' }
                    }
                ]
            });
            
            // Delta E 分布图
            const deltaEChart = echarts.init(document.getElementById('delta-e-chart'));
            deltaEChart.setOption({
                title: { text: 'Delta E 分布', left: 'center' },
                tooltip: { trigger: 'axis' },
                xAxis: {
                    type: 'category',
                    data: Object.keys(deltaEChartData.distribution)
                },
                yAxis: {
                    type: 'value',
                    name: '数量'
                },
                series: [{
                    name: '数量',
                    type: 'bar',
                    data: Object.values(deltaEChartData.distribution),
                    itemStyle: {
                        color: function(params) {
                            const bin = Object.keys(deltaEChartData.distribution)[params.dataIndex];
                            if (bin === '<1') return '#28a745';
                            if (bin === '1-2') return '#5cb85c';
                            if (bin === '2-3') return '#ffc107';
                            if (bin === '3-4') return '#fd7e14';
                            return '#dc3545';
                        }
                    }
                }]
            });
            
            // 窗口大小变化时重新调整图表
            window.addEventListener('resize', function() {
                gammaChart.resize();
                gamutChart.resize();
                deltaEChart.resize();
            });
        }
    </script>
</body>
</html>
"""

# 导入 math 模块用于 Gamma 计算
import math
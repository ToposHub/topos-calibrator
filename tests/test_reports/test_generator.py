"""
Tests for Report Generator Module

测试报告生成功能：
- ReportData 数据结构
- ValidationResult 验证逻辑
- HTML 报告生成
- 多数据源支持（SchemaV1, MeasurementAnalyzer, dict）
"""

import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict
import pytest

from src.reports import (
    ReportGenerator,
    ReportConfig,
    ReportType,
    ReportData,
    ValidationResult,
    ValidationSummary,
    PassStatus,
    ThresholdConfig,
    generate_html_report,
)
from src.storage import SchemaV1
from src.measurement_analyzer import MeasurementAnalyzer


class TestThresholdConfig:
    """测试阈值配置"""
    
    def test_default_thresholds(self):
        """测试默认阈值"""
        config = ThresholdConfig()
        
        assert config.delta_e_avg_pass == 2.0
        assert config.delta_e_avg_warn == 3.0
        assert config.delta_e_max_pass == 4.0
        assert config.gamma_deviation_pass == 0.05
        assert config.gamut_coverage_pass == 95.0
    
    def test_custom_thresholds(self):
        """测试自定义阈值"""
        config = ThresholdConfig(
            delta_e_avg_pass=1.5,
            delta_e_avg_warn=2.5,
            gamma_deviation_pass=0.03
        )
        
        assert config.delta_e_avg_pass == 1.5
        assert config.delta_e_avg_warn == 2.5
        assert config.gamma_deviation_pass == 0.03


class TestPassStatus:
    """测试验证状态枚举"""
    
    def test_status_values(self):
        """测试状态值"""
        assert PassStatus.PASS.value == "pass"
        assert PassStatus.WARN.value == "warn"
        assert PassStatus.FAIL.value == "fail"
        assert PassStatus.NOT_TESTED.value == "not_tested"


class TestValidationResult:
    """测试验证结果"""
    
    def test_result_creation(self):
        """测试结果创建"""
        result = ValidationResult(
            metric_name="Delta E 平均",
            value=1.5,
            target=2.0,
            deviation=0.5,
            status=PassStatus.PASS,
            unit="",
            description="平均色彩偏差"
        )
        
        assert result.metric_name == "Delta E 平均"
        assert result.value == 1.5
        assert result.status == PassStatus.PASS
    
    def test_result_to_dict(self):
        """测试转换为字典"""
        result = ValidationResult(
            metric_name="Gamma",
            value=2.2,
            target=2.2,
            deviation=0.0,
            status=PassStatus.PASS,
            unit="",
            description="Gamma 值"
        )
        
        data = result.to_dict()
        
        assert data["metric_name"] == "Gamma"
        assert data["value"] == 2.2
        assert data["status"] == "pass"


class TestValidationSummary:
    """测试验证汇总"""
    
    def test_empty_summary(self):
        """测试空汇总"""
        summary = ValidationSummary()
        
        assert summary.overall_status == PassStatus.NOT_TESTED
        assert summary.pass_count == 0
        assert summary.warn_count == 0
        assert summary.fail_count == 0
    
    def test_add_pass_result(self):
        """测试添加合格结果"""
        summary = ValidationSummary()
        result = ValidationResult(
            metric_name="Gamma",
            value=2.2,
            target=2.2,
            status=PassStatus.PASS
        )
        
        summary.add_result(result)
        
        assert summary.pass_count == 1
        assert summary.overall_status == PassStatus.PASS
    
    def test_add_fail_result(self):
        """测试添加不合格结果"""
        summary = ValidationSummary()
        
        # 先添加一个合格
        summary.add_result(ValidationResult(
            metric_name="Gamma",
            value=2.2,
            target=2.2,
            status=PassStatus.PASS
        ))
        
        # 再添加一个不合格
        summary.add_result(ValidationResult(
            metric_name="Delta E",
            value=5.0,
            target=2.0,
            status=PassStatus.FAIL
        ))
        
        assert summary.pass_count == 1
        assert summary.fail_count == 1
        assert summary.overall_status == PassStatus.FAIL
    
    def test_mixed_results(self):
        """测试混合结果"""
        summary = ValidationSummary()
        
        summary.add_result(ValidationResult("A", 1.0, target=1.0, status=PassStatus.PASS))
        summary.add_result(ValidationResult("B", 2.5, target=2.0, status=PassStatus.WARN))
        summary.add_result(ValidationResult("C", 1.0, target=1.0, status=PassStatus.PASS))
        
        assert summary.pass_count == 2
        assert summary.warn_count == 1
        assert summary.overall_status == PassStatus.WARN
    
    def test_to_dict(self):
        """测试转换为字典"""
        summary = ValidationSummary()
        summary.add_result(ValidationResult("A", 1.0, target=1.0, status=PassStatus.PASS))
        summary.add_result(ValidationResult("B", 2.0, target=2.0, status=PassStatus.WARN))
        
        data = summary.to_dict()
        
        assert data["overall_status"] == "warn"
        assert data["pass_count"] == 1
        assert data["warn_count"] == 1
        assert len(data["results"]) == 2


class TestReportData:
    """测试报告数据结构"""
    
    def test_default_data(self):
        """测试默认数据"""
        data = ReportData()
        
        assert data.target_standard == "sRGB"
        assert data.target_gamma == 2.2
        assert data.target_white_point == "D65"
        assert data.white_point_x == 0.3127
        assert data.white_point_y == 0.3290
    
    def test_data_with_values(self):
        """测试带值数据"""
        data = ReportData(
            report_id="test-001",
            target_standard="DCI-P3",
            target_gamma=2.6,
            measured_gamma=2.55,
            gamma_deviation=0.05,
            gamut_coverage_percent=98.5,
            delta_e_avg=1.2,
            delta_e_max=3.5
        )
        
        assert data.target_standard == "DCI-P3"
        assert data.measured_gamma == 2.55
        assert data.gamut_coverage_percent == 98.5
    
    def test_data_to_dict(self):
        """测试转换为字典"""
        data = ReportData(
            report_id="test-002",
            measured_gamma=2.2,
            gamut_coverage_percent=95.0
        )
        
        result = data.to_dict()
        
        assert result["report_id"] == "test-002"
        assert result["gamma"]["measured"] == 2.2
        assert result["gamut"]["coverage_percent"] == 95.0
    
    def test_gamma_curve_data(self):
        """测试 Gamma 曲线数据"""
        data = ReportData(
            gamma_curve_data=[
                {"input": 0, "Y": 0.1},
                {"input": 50, "Y": 50},
                {"input": 100, "Y": 100}
            ]
        )
        
        result = data.to_dict()
        
        assert "gamma_curve" in result
        assert len(result["gamma_curve"]) == 3


class TestReportConfig:
    """测试报告配置"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = ReportConfig()
        
        assert config.title == "Topos Calibrator 校准报告"
        assert config.include_charts == True
        assert config.output_format == "html"
    
    def test_custom_config(self):
        """测试自定义配置"""
        config = ReportConfig(
            title="自定义报告",
            include_charts=False,
            language="en-US"
        )
        
        assert config.title == "自定义报告"
        assert config.include_charts == False
        assert config.language == "en-US"


class TestReportGenerator:
    """测试报告生成器"""
    
    def test_generator_creation(self):
        """测试生成器创建"""
        generator = ReportGenerator()
        
        assert generator.config is not None
        assert generator.template_path is None
    
    def test_generator_with_config(self):
        """测试带配置的生成器"""
        config = ReportConfig(title="测试报告")
        generator = ReportGenerator(config)
        
        assert generator.config.title == "测试报告"
    
    def test_builtin_template(self):
        """测试内置模板"""
        generator = ReportGenerator()
        template = generator._load_template()
        
        assert "<!DOCTYPE html>" in template
        assert "{{REPORT_TITLE}}" in template
        assert "{{REPORT_ID}}" in template
    
    def test_check_threshold_pass(self):
        """测试阈值检查 - 合格"""
        generator = ReportGenerator()
        
        status = generator._check_threshold(1.0, 2.0, 3.0)
        assert status == PassStatus.PASS
    
    def test_check_threshold_warn(self):
        """测试阈值检查 - 警告"""
        generator = ReportGenerator()
        
        status = generator._check_threshold(2.5, 2.0, 3.0)
        assert status == PassStatus.WARN
    
    def test_check_threshold_fail(self):
        """测试阈值检查 - 不合格"""
        generator = ReportGenerator()
        
        status = generator._check_threshold(4.0, 2.0, 3.0)
        assert status == PassStatus.FAIL
    
    def test_check_threshold_reverse(self):
        """测试反向阈值检查（越大越好）"""
        generator = ReportGenerator()
        
        # 95% >= 95% 合格
        status = generator._check_threshold(95.0, 95.0, 90.0, reverse=True)
        assert status == PassStatus.PASS
        
        # 92% >= 90% 但 < 95% 警告
        status = generator._check_threshold(92.0, 95.0, 90.0, reverse=True)
        assert status == PassStatus.WARN
        
        # 85% < 90% 不合格
        status = generator._check_threshold(85.0, 95.0, 90.0, reverse=True)
        assert status == PassStatus.FAIL
    
    def test_generate_from_dict(self):
        """测试从字典生成报告"""
        generator = ReportGenerator()
        
        # 测试数据
        data = {
            "metadata": {
                "measurement_id": "test-001",
                "probe": "i1d3",
                "display_model": "PHL 439P1",
                "timestamp": "2026-05-19T10:00:00"
            },
            "measurements": {
                "gamut": {
                    "white": {"xyY": [0.3127, 0.3290, 100.0]},
                    "black": {"xyY": [0.3127, 0.3290, 0.1]},
                    "red": {"xyY": [0.64, 0.33, 20.0]},
                    "green": {"xyY": [0.30, 0.60, 40.0]},
                    "blue": {"xyY": [0.15, 0.06, 10.0]}
                },
                "gamma": [
                    {"input": 10, "Y": 1.0},
                    {"input": 50, "Y": 22.0},
                    {"input": 100, "Y": 100.0}
                ]
            }
        }
        
        html = generator.generate_from_dict(data, ReportType.FULL_REPORT)
        
        assert "<!DOCTYPE html>" in html
        assert "test-001" in html
        assert "i1d3" in html
        assert "PHL 439P1" in html
    
    def test_generate_from_schema(self):
        """测试从 SchemaV1 生成报告"""
        generator = ReportGenerator()
        
        # 创建 SchemaV1 数据
        schema = SchemaV1()
        schema.instrument.probe = "i1d3"
        schema.display.model = "Test Monitor"
        schema.workflow.target = "sRGB"
        schema.workflow.gamma_target = 2.2
        
        # 设置测量数据
        schema.measurements.gamut.white = {"RGB": [255, 255, 255], "xyY": [0.3127, 0.3290, 100.0]}
        schema.measurements.gamut.black = {"RGB": [0, 0, 0], "xyY": [0.3127, 0.3290, 0.1]}
        schema.measurements.gamma = [
            {"input": 10, "Y": 1.0},
            {"input": 50, "Y": 22.0}
        ]
        
        html = generator.generate_from_schema(schema, ReportType.FULL_REPORT)
        
        assert "<!DOCTYPE html>" in html
        assert "i1d3" in html
        assert "Test Monitor" in html
    
    def test_generate_from_analyzer(self):
        """测试从 MeasurementAnalyzer 生成报告"""
        generator = ReportGenerator()
        
        # 创建 MeasurementAnalyzer
        analyzer = MeasurementAnalyzer()
        analyzer.set_gamut_data(
            red={"x": 0.64, "y": 0.33, "Y": 20.0},
            green={"x": 0.30, "y": 0.60, "Y": 40.0},
            blue={"x": 0.15, "y": 0.06, "Y": 10.0},
            white={"x": 0.3127, "y": 0.3290, "Y": 100.0}
        )
        analyzer.set_gamma_data([
            {"patchNames": "10%", "Y": 1.0, "rgb": {"r": 26, "g": 26, "b": 26}},
            {"patchNames": "50%", "Y": 22.0, "rgb": {"r": 128, "g": 128, "b": 128}},
            {"patchNames": "100%", "Y": 100.0, "rgb": {"r": 255, "g": 255, "b": 255}}
        ])
        
        metadata = {
            "probe": "i1d3",
            "display_model": "Test Display",
            "target_standard": "sRGB"
        }
        
        html = generator.generate_from_analyzer(analyzer, metadata)
        
        assert "<!DOCTYPE html>" in html
        assert "i1d3" in html
        assert "Test Display" in html
    
    def test_save_report(self):
        """测试保存报告"""
        generator = ReportGenerator()
        
        # 生成报告
        data = {
            "metadata": {"measurement_id": "save-test"},
            "measurements": {"gamut": {}, "gamma": []}
        }
        html = generator.generate_from_dict(data)
        
        # 保存到临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
            temp_path = f.name
        
        try:
            result = generator.save_report(html, temp_path)
            
            assert result == True
            assert os.path.exists(temp_path)
            
            # 验证文件内容
            with open(temp_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            assert "<!DOCTYPE html>" in content
            assert "save-test" in content
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_save_report_to_nonexistent_dir(self):
        """测试保存到不存在的目录"""
        generator = ReportGenerator()
        
        html = "<html><body>Test</body></html>"
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建一个不存在的子目录路径
            nonexistent_path = os.path.join(tmpdir, "subdir", "report.html")
            
            result = generator.save_report(html, nonexistent_path)
            
            assert result == True
            assert os.path.exists(nonexistent_path)


class TestValidationLogic:
    """测试验证逻辑"""
    
    def test_validate_report_data_pass(self):
        """测试验证合格数据"""
        generator = ReportGenerator()
        
        # 创建合格数据
        data = ReportData(
            measured_gamma=2.2,
            gamma_deviation=0.02,  # < 0.05 合格
            gamut_coverage_percent=98.0,  # > 95 合格
            delta_e_avg=1.5,  # < 2 合格
            delta_e_max=3.0,  # < 4 合格
            white_point_delta_e=1.0,  # < 2 合格
            max_brightness=120.0,  # > 80 合格
            contrast_ratio=1000.0,  # > 500 合格
        )
        
        generator._validate_report_data(data)
        
        # 检查验证结果
        summary = data.validation_summary
        
        # 所有指标应该合格
        assert summary.fail_count == 0
        assert summary.warn_count == 0
        assert summary.pass_count > 0
        assert summary.overall_status == PassStatus.PASS
    
    def test_validate_report_data_warn(self):
        """测试验证警告数据"""
        generator = ReportGenerator()
        
        # 创建有警告的数据
        data = ReportData(
            measured_gamma=2.28,
            gamma_deviation=0.08,  # > 0.05 警告, < 0.10
            gamut_coverage_percent=92.0,  # < 95 警告, > 90
            delta_e_avg=2.5,  # > 2 警告, < 3
        )
        
        generator._validate_report_data(data)
        
        summary = data.validation_summary
        
        assert summary.warn_count > 0
        assert summary.overall_status == PassStatus.WARN
    
    def test_validate_report_data_fail(self):
        """测试验证不合格数据"""
        generator = ReportGenerator()
        
        # 创建不合格数据
        data = ReportData(
            measured_gamma=2.35,
            gamma_deviation=0.15,  # > 0.10 不合格
            gamut_coverage_percent=80.0,  # < 90 不合格
            delta_e_avg=5.0,  # > 3 不合格
            delta_e_max=10.0,  # > 6 不合格
        )
        
        generator._validate_report_data(data)
        
        summary = data.validation_summary
        
        assert summary.fail_count > 0
        assert summary.overall_status == PassStatus.FAIL


class TestChartDataPreparation:
    """测试图表数据准备"""
    
    def test_prepare_gamma_chart_data(self):
        """测试 Gamma 图表数据准备"""
        generator = ReportGenerator()
        
        data = ReportData(
            gamma_curve_data=[
                {"input": 0, "Y": 0.1},
                {"input": 25, "Y": 5.5},
                {"input": 50, "Y": 22.0},
                {"input": 75, "Y": 55.0},
                {"input": 100, "Y": 100.0}
            ],
            max_brightness=100.0,
            target_gamma=2.2
        )
        
        chart_data = generator._prepare_gamma_chart_data(data)
        
        assert len(chart_data["input"]) == 5
        assert len(chart_data["measured"]) == 5
        assert len(chart_data["target"]) == 5
        
        # 检查目标曲线计算
        # 对于 Gamma 2.2，输入 0.5 应产生 0.5^2.2 ≈ 0.22
        assert abs(chart_data["target"][2] - 0.22) < 0.1
    
    def test_prepare_gamma_chart_data_empty(self):
        """测试空 Gamma 数据"""
        generator = ReportGenerator()
        
        data = ReportData()
        
        chart_data = generator._prepare_gamma_chart_data(data)
        
        assert chart_data["input"] == []
        assert chart_data["measured"] == []
        assert chart_data["target"] == []
    
    def test_prepare_gamut_chart_data(self):
        """测试色域图表数据准备"""
        generator = ReportGenerator()
        
        data = ReportData(
            measured_gamut_triangle=[
                (0.64, 0.33),  # red
                (0.30, 0.60),  # green
                (0.15, 0.06),  # blue
            ],
            standard_gamut_triangle=[
                (0.64, 0.33),  # sRGB red
                (0.30, 0.60),  # sRGB green
                (0.15, 0.06),  # sRGB blue
            ],
            white_point_x=0.3127,
            white_point_y=0.3290,
            gamut_coverage_percent=100.0,
            gamut_area_ratio_percent=100.0
        )
        
        chart_data = generator._prepare_gamut_chart_data(data)
        
        assert len(chart_data["measured"]) == 3
        assert len(chart_data["standard"]) == 3
        assert chart_data["white_point"]["x"] == 0.3127
        assert chart_data["coverage"] == 100.0
    
    def test_prepare_delta_e_chart_data(self):
        """测试 Delta E 分布数据准备"""
        generator = ReportGenerator()
        
        data = ReportData(
            delta_e_distribution={
                "<1": 50,
                "1-2": 30,
                "2-3": 15,
                "3-4": 5,
                ">4": 0
            },
            delta_e_avg=1.2,
            delta_e_max=3.5,
            delta_e_95th_percentile=2.8
        )
        
        chart_data = generator._prepare_delta_e_chart_data(data)
        
        assert chart_data["distribution"]["<1"] == 50
        assert chart_data["avg"] == 1.2
        assert chart_data["max"] == 3.5


class TestGenerateHTMLReportFunction:
    """测试便捷函数"""
    
    def test_generate_from_dict_function(self):
        """测试便捷函数生成报告"""
        data = {
            "metadata": {"measurement_id": "func-test"},
            "measurements": {"gamut": {}, "gamma": []}
        }
        
        html = generate_html_report(data)
        
        assert "<!DOCTYPE html>" in html
        assert "func-test" in html
    
    def test_generate_with_config(self):
        """测试带配置的便捷函数"""
        config = ReportConfig(title="自定义标题测试")
        
        data = {
            "metadata": {"measurement_id": "config-test"},
            "measurements": {"gamut": {}, "gamma": []}
        }
        
        html = generate_html_report(data, config=config)
        
        assert "自定义标题测试" in html
    
    def test_generate_unsupported_type(self):
        """测试不支持的数据类型"""
        with pytest.raises(ValueError):
            generate_html_report("unsupported string data")


class TestReportOfflineCapability:
    """测试报告离线能力"""
    
    def test_html_can_open_offline(self):
        """测试 HTML 可以离线打开"""
        generator = ReportGenerator()
        
        data = {
            "metadata": {"measurement_id": "offline-test"},
            "measurements": {
                "gamut": {
                    "white": {"xyY": [0.3127, 0.3290, 100.0]},
                    "red": {"xyY": [0.64, 0.33, 20.0]},
                    "green": {"xyY": [0.30, 0.60, 40.0]},
                    "blue": {"xyY": [0.15, 0.06, 10.0]}
                },
                "gamma": [
                    {"input": 50, "Y": 22.0}
                ]
            }
        }
        
        html = generator.generate_from_dict(data)
        
        # 检查 HTML 不依赖外部资源
        assert "<!DOCTYPE html>" in html
        assert "<style>" in html  # 内嵌样式
        
        # 不应该有外部 CSS/JS 链接（除非是可选的 ECharts CDN）
        # 检查所有 CSS 都是内嵌的
        assert "href=" not in html or "cdn" in html.lower() or "https://cdnjs.cloudflare.com/ajax/libs/echarts" in html
    
    def test_html_contains_all_data(self):
        """测试 HTML 包含所有数据"""
        generator = ReportGenerator()
        
        data = ReportData(
            report_id="complete-test",
            probe="i1d3",
            display_model="Test Monitor",
            measured_gamma=2.2,
            gamut_coverage_percent=95.0,
            delta_e_avg=1.5,
            delta_e_max=3.0,
            white_point_cct=6500,
            max_brightness=120.0,
            contrast_ratio=1000.0
        )
        
        generator._validate_report_data(data)
        html = generator._render_html(data)
        
        # 检查所有关键数据都在 HTML 中
        assert "complete-test" in html
        assert "i1d3" in html
        assert "Test Monitor" in html
        assert "2.2" in html
        assert "95.0" in html or "95" in html
        assert "6500" in html


class TestReportTemplateReplacement:
    """测试模板变量替换"""
    
    def test_all_template_vars_replaced(self):
        """测试所有模板变量都被替换"""
        generator = ReportGenerator()
        
        data = ReportData(
            report_id="replacement-test",
            target_standard="sRGB",
            target_gamma=2.2,
            probe="i1d3",
            display_model="Test",
            white_point_cct=6500,
            measured_gamma=2.2,
            gamut_coverage_percent=95.0,
            delta_e_avg=1.5,
            max_brightness=100.0,
            contrast_ratio=1000.0
        )
        
        generator._validate_report_data(data)
        html = generator._render_html(data)
        
        # 检查关键模板变量已替换
        assert "{{REPORT_ID}}" not in html
        assert "{{TARGET_STANDARD}}" not in html
        assert "{{PROBE}}" not in html
        
        # 检查实际值存在
        assert "replacement-test" in html
        assert "sRGB" in html


class TestEdgeCases:
    """测试边缘情况"""
    
    def test_empty_measurements(self):
        """测试空测量数据"""
        generator = ReportGenerator()
        
        data = {
            "metadata": {"measurement_id": "empty-test"},
            "measurements": {"gamut": {}, "gamma": [], "lut_patches": []}
        }
        
        html = generator.generate_from_dict(data)
        
        assert "<!DOCTYPE html>" in html
        assert "empty-test" in html
    
    def test_partial_measurements(self):
        """测试部分测量数据"""
        generator = ReportGenerator()
        
        # 只有白点测量
        data = {
            "metadata": {"measurement_id": "partial-test"},
            "measurements": {
                "gamut": {
                    "white": {"xyY": [0.3127, 0.3290, 100.0]}
                },
                "gamma": []
            }
        }
        
        html = generator.generate_from_dict(data)
        
        assert "<!DOCTYPE html>" in html
        assert "partial-test" in html
    
    def test_unicode_handling(self):
        """测试 Unicode 处理"""
        generator = ReportGenerator()
        
        data = {
            "metadata": {
                "measurement_id": "unicode-test",
                "display_model": "测试显示器"
            },
            "measurements": {"gamut": {}, "gamma": []}
        }
        
        html = generator.generate_from_dict(data)
        
        # 测试中文显示名称
        assert "测试显示器" in html
    
    def test_special_characters(self):
        """测试特殊字符处理"""
        generator = ReportGenerator()
        
        data = {
            "metadata": {
                "measurement_id": "special-test",
                "display_name": "Monitor <Test> & \"Quote\""
            },
            "measurements": {"gamut": {}, "gamma": []}
        }
        
        html = generator.generate_from_dict(data)
        
        # HTML 应该正确处理特殊字符
        assert "<!DOCTYPE html>" in html


# 运行测试的入口
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
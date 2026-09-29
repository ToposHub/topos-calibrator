"""
ReportService - Report Generation Facade for Backend

This module provides a facade layer that wraps ReportGenerator and
provides Backend-friendly API for report generation.

Backend integration:
- Backend delegates report operations to this service
- Service handles generator initialization and config management
- Backend keeps Qt signals/slots for UI communication
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from .generator import ReportGenerator, ReportConfig, ReportType, ReportData


logger = logging.getLogger(__name__)


class ReportService:
    """
    Report generation facade service
    
    This service wraps ReportGenerator and provides:
    - Config management
    - Path resolution for report storage
    - Helper methods for JSON serialization
    
    Usage:
        service = ReportService()
        result = service.generate_for_measurement(measurement_data, measurement_id)
        service.save_report(result["html_content"], result["path"])
    """
    
    def __init__(self, config: Optional[ReportConfig] = None):
        """Initialize report service"""
        self._config = config or ReportConfig()
        self._generator = ReportGenerator(self._config)
        self._last_report_path: Optional[str] = None
        self._project_root: Optional[str] = None
        
    # ========== Configuration Methods ==========
    
    def set_config(self, config: ReportConfig) -> None:
        """Set report configuration"""
        self._config = config
        self._generator = ReportGenerator(self._config)
    
    def update_config(self, config_dict: Dict[str, Any]) -> None:
        """Update config from dict (partial update)"""
        if "title" in config_dict:
            self._config.title = config_dict["title"]
        if "include_charts" in config_dict:
            self._config.include_charts = config_dict["include_charts"]
        
        # Update threshold config
        if "thresholds" in config_dict:
            thresholds = config_dict["thresholds"]
            tc = self._config.threshold_config
            if "delta_e_avg_pass" in thresholds:
                tc.delta_e_avg_pass = thresholds["delta_e_avg_pass"]
            if "delta_e_avg_warn" in thresholds:
                tc.delta_e_avg_warn = thresholds["delta_e_avg_warn"]
            if "delta_e_max_pass" in thresholds:
                tc.delta_e_max_pass = thresholds["delta_e_max_pass"]
            if "gamma_deviation_pass" in thresholds:
                tc.gamma_deviation_pass = thresholds["gamma_deviation_pass"]
            if "gamut_coverage_pass" in thresholds:
                tc.gamut_coverage_pass = thresholds["gamut_coverage_pass"]
        
        # Regenerate generator with updated config
        self._generator = ReportGenerator(self._config)
    
    def get_config(self) -> ReportConfig:
        """Get current config"""
        return self._config
    
    def get_config_json(self) -> str:
        """Get config as JSON string"""
        config_data = {
            "title": self._config.title,
            "include_charts": self._config.include_charts,
            "output_format": self._config.output_format,
            "language": self._config.language,
            "thresholds": {
                "delta_e_avg_pass": self._config.threshold_config.delta_e_avg_pass,
                "delta_e_avg_warn": self._config.threshold_config.delta_e_avg_warn,
                "delta_e_max_pass": self._config.threshold_config.delta_e_max_pass,
                "gamma_deviation_pass": self._config.threshold_config.gamma_deviation_pass,
                "gamut_coverage_pass": self._config.threshold_config.gamut_coverage_pass,
            }
        }
        return json.dumps(config_data)
    
    # ========== Path Resolution ==========
    
    def set_project_root(self, path: str) -> None:
        """Set project root path"""
        self._project_root = path
    
    def _get_project_root(self) -> str:
        """Get project root path"""
        if self._project_root:
            return self._project_root
        # Default: parent of src directory
        return str(Path(__file__).parent.parent.parent)
    
    def get_reports_dir(self, session_path: Optional[str] = None) -> str:
        """Get reports directory path"""
        if session_path:
            reports_dir = os.path.join(session_path, "reports")
        else:
            reports_dir = os.path.join(self._get_project_root(), "measurements", "reports")
        
        if not os.path.exists(reports_dir):
            os.makedirs(reports_dir)
        
        return reports_dir
    
    # ========== Report Generation Methods ==========
    
    def generate_for_measurement(
        self,
        measurement_data: Any,  # MeasurementData
        measurement_id: str,
        session_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate report for a measurement
        
        Args:
            measurement_data: MeasurementData instance
            measurement_id: Measurement ID
            session_path: Optional session path for report storage
            
        Returns:
            Dict with success, path, report_id, html_content, etc.
        """
        try:
            # Determine report type from measure mode
            report_type = ReportType.FULL_REPORT
            mode = measurement_data.metadata.get("measure_mode", "")
            
            type_mapping = {
                "icc": ReportType.ICC_VALIDATION,
                "lut": ReportType.LUT_VALIDATION,
                "gamut": ReportType.GAMUT_MEASUREMENT,
                "gamma": ReportType.GAMMA_ANALYSIS,
            }
            report_type = type_mapping.get(mode, ReportType.FULL_REPORT)
            
            # Generate HTML content
            html_content = self._generator.generate_from_dict(
                measurement_data.to_dict(), report_type
            )
            
            # Determine save path
            reports_dir = self.get_reports_dir(session_path)
            report_filename = f"{measurement_id}_report.html"
            report_path = os.path.join(reports_dir, report_filename)
            
            return {
                "success": True,
                "html_content": html_content,
                "path": report_path,
                "report_id": measurement_id,
                "report_type": report_type.value,
            }
            
        except Exception as e:
            logger.error(f"Generate report failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }
    
    def generate_from_dict(
        self,
        data_dict: Dict[str, Any],
        report_type: Optional[ReportType] = None,
    ) -> Dict[str, Any]:
        """
        Generate report from dict data
        
        Args:
            data_dict: Measurement data as dict
            report_type: Optional report type (auto-detected if not provided)
            
        Returns:
            Dict with success and html_content
        """
        try:
            if report_type is None:
                mode = data_dict.get("metadata", {}).get("measure_mode", "")
                type_mapping = {
                    "icc": ReportType.ICC_VALIDATION,
                    "lut": ReportType.LUT_VALIDATION,
                    "gamut": ReportType.GAMUT_MEASUREMENT,
                    "gamma": ReportType.GAMMA_ANALYSIS,
                }
                report_type = type_mapping.get(mode, ReportType.FULL_REPORT)
            
            html_content = self._generator.generate_from_dict(data_dict, report_type)
            
            return {
                "success": True,
                "html_content": html_content,
                "report_type": report_type.value,
            }
            
        except Exception as e:
            logger.error(f"Generate report from dict failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }
    
    def generate_current(
        self,
        measurement_data: Any,
        measure_mode: str,
        session_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate report for current measurement
        
        Args:
            measurement_data: MeasurementData instance
            measure_mode: Current measure mode
            session_path: Optional session path
            
        Returns:
            Dict with success, path, report_id, etc.
        """
        try:
            # Determine report type
            type_mapping = {
                "icc": ReportType.ICC_VALIDATION,
                "lut": ReportType.LUT_VALIDATION,
            }
            report_type = type_mapping.get(measure_mode, ReportType.FULL_REPORT)
            
            # Generate HTML
            html_content = self._generator.generate_from_dict(
                measurement_data.to_dict(), report_type
            )
            
            # Determine path
            reports_dir = self.get_reports_dir(session_path)
            
            # Generate report ID
            report_id = measurement_data.metadata.get("measurement_id",
                datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + os.urandom(3).hex())
            report_filename = f"{report_id}_report.html"
            report_path = os.path.join(reports_dir, report_filename)
            
            return {
                "success": True,
                "html_content": html_content,
                "path": report_path,
                "report_id": report_id,
                "report_type": report_type.value,
            }
            
        except Exception as e:
            logger.error(f"Generate current report failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }
    
    # ========== Report Saving Methods ==========
    
    def save_report(self, html_content: str, filepath: str) -> bool:
        """Save HTML report to file"""
        return self._generator.save_report(html_content, filepath)
    
    def generate_and_save(
        self,
        measurement_data: Any,
        measurement_id: str,
        session_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate and save report
        
        Args:
            measurement_data: MeasurementData instance
            measurement_id: Measurement ID
            session_path: Optional session path
            
        Returns:
            Dict with success, path, message
        """
        result = self.generate_for_measurement(measurement_data, measurement_id, session_path)
        
        if result.get("success"):
            html_content = result["html_content"]
            path = result["path"]
            
            save_success = self.save_report(html_content, path)
            
            if save_success:
                self._last_report_path = path
                return {
                    "success": True,
                    "path": path,
                    "report_id": measurement_id,
                    "message": "报告已生成",
                }
            else:
                return {
                    "success": False,
                    "error": "保存报告失败",
                }
        
        return result
    
    def export_to_path(
        self,
        measurement_data: Any,
        measurement_id: str,
        output_path: str,
    ) -> Dict[str, Any]:
        """
        Export report to specified path
        
        Args:
            measurement_data: MeasurementData instance
            measurement_id: Measurement ID
            output_path: Output file path
            
        Returns:
            Dict with success, path, message
        """
        result = self.generate_for_measurement(measurement_data, measurement_id)
        
        if result.get("success"):
            html_content = result["html_content"]
            
            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            save_success = self.save_report(html_content, output_path)
            
            if save_success:
                self._last_report_path = output_path
                return {
                    "success": True,
                    "path": output_path,
                    "message": "报告已导出",
                }
            else:
                return {
                    "success": False,
                    "error": "保存报告失败",
                }
        
        return result
    
    # ========== Last Report Access ==========
    
    def get_last_report_path(self) -> Optional[str]:
        """Get last generated report path"""
        return self._last_report_path
    
    def get_last_report_path_json(self) -> str:
        """Get last report path as JSON"""
        if self._last_report_path:
            exists = os.path.exists(self._last_report_path)
            return json.dumps({
                "path": self._last_report_path,
                "exists": exists
            })
        else:
            return json.dumps({
                "path": "",
                "exists": False
            })


__all__ = [
    "ReportService",
]
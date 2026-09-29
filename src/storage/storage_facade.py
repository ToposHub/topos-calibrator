"""
StorageFacade - Unified Storage Facade for Backend

This module provides a facade layer that unifies:
- MeasurementData persistence (DataStorage)
- Session management (SessionStorage)
- CGATS/TI3 export (CGATSExporter)
- SchemaV1 storage (StorageService)

Backend integration:
- Backend delegates all storage operations to this facade
- Backend keeps Qt signals/slots for UI communication
- Facade handles data synchronization and format conversion
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# Import from existing modules
from .storage_service import StorageService

# Import from data_storage (legacy compatibility)
try:
    from ..data_storage import (
        DataStorage,
        MeasurementData,
        CGATSExporter,
        SessionStorage,
        SessionData,
    )
except ImportError:
    # Direct import for tests
    from src.data_storage import (
        DataStorage,
        MeasurementData,
        CGATSExporter,
        SessionStorage,
        SessionData,
    )


logger = logging.getLogger(__name__)


class StorageFacade:
    """
    Unified storage facade for Backend
    
    This facade provides:
    - Measurement data save/load/delete
    - Session management (create/load/delete/archive)
    - Export to TI3/CGATS/CSV/JSON formats
    - Measurement list management
    
    Usage:
        facade = StorageFacade()
        facade.save_measurement(measurement_data)
        facade.load_measurement(measurement_id)
        facade.export_ti3(measurement_data, filepath)
    """
    
    def __init__(self, measurements_dir: Optional[str] = None):
        """Initialize storage facade"""
        self._measurements_dir = measurements_dir
        
        # Initialize components
        self._data_storage = DataStorage(base_path=measurements_dir)
        self._session_storage = SessionStorage()
        self._cgats_exporter = CGATSExporter()
        self._storage_service = StorageService(measurements_dir=measurements_dir)
        
        # Current measurement and session
        self._current_measurement: Optional[MeasurementData] = None
        self._current_session: Optional[SessionData] = None
        
    # ========== Configuration ==========
    
    def set_measurements_dir(self, path: str) -> None:
        """Set measurements directory"""
        self._measurements_dir = path
        self._data_storage = DataStorage(base_path=path)
        self._storage_service = StorageService(measurements_dir=path)
    
    # ========== Measurement Operations ==========
    
    def save_measurement(self, measurement: MeasurementData) -> Dict[str, Any]:
        """
        Save measurement data
        
        Args:
            measurement: MeasurementData instance
            
        Returns:
            Dict with success, filepath, id
        """
        filepath = self._data_storage.save_measurement(measurement)
        
        if filepath:
            return {
                "success": True,
                "filepath": filepath,
                "id": measurement.metadata.get("measurement_id"),
            }
        else:
            return {
                "success": False,
                "message": "保存失败",
            }
    
    def load_measurement(self, measurement_id: str) -> Optional[MeasurementData]:
        """Load measurement by ID"""
        return self._data_storage.load_measurement(measurement_id)
    
    def delete_measurement(self, measurement_id: str) -> bool:
        """Delete measurement by ID"""
        return self._data_storage.delete_measurement(measurement_id)
    
    def get_all_measurements(self) -> List[Dict[str, Any]]:
        """Get all saved measurements (including auto_save)"""
        return self._data_storage.get_all_saved_measurements()
    
    def get_measurement_list_formatted(self) -> List[Dict[str, Any]]:
        """
        Get formatted measurement list for UI
        
        Returns:
            List of dicts with id, name, display_name, paths, timestamps, etc.
        """
        raw_list = self._data_storage.get_all_saved_measurements()
        
        measurements = []
        for item in raw_list:
            # Try to read metadata from JSON
            display_name = ""
            probe = ""
            has_gamut = False
            has_gamma = False
            has_lut = False
            
            json_path = item.get("json_path")
            if json_path and Path(json_path).exists():
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        metadata = data.get("metadata", {})
                        probe = metadata.get("probe", "")
                        display_name = metadata.get("display_name", "")
                        
                        meas_data = data.get("measurements", {})
                        has_gamut = "gamut" in meas_data
                        has_gamma = "gamma" in meas_data
                        has_lut = "lut" in meas_data or "custom_patches" in meas_data
                except Exception as e:
                    logger.warning(f"读取 {json_path} 失败: {e}")
            
            # Generate ID
            measurement_id = ""
            if json_path:
                measurement_id = Path(json_path).stem
            
            measurements.append({
                "id": measurement_id,
                "name": item.get("name", ""),
                "display_name": display_name,
                "json_path": item.get("json_path", ""),
                "ti3_path": item.get("ti3_path", ""),
                "cal_path": item.get("cal_path", ""),
                "measure_mode": item.get("measure_mode", ""),
                "timestamp": item.get("timestamp", 0),
                "filename": Path(item.get("json_path") or item.get("ti3_path") or "").name,
                "date_dir": item.get("date_dir", ""),
                "time_str": item.get("time_str", ""),
                "probe": probe,
                "has_gamut": has_gamut,
                "has_gamma": has_gamma,
                "has_lut": has_lut
            })
        
        # Sort by timestamp (newest first)
        measurements.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        
        return measurements
    
    # ========== Session Operations ==========
    
    def create_session(self, measure_mode: str = "") -> SessionData:
        """Create new session"""
        self._current_session = self._session_storage.create_session(measure_mode)
        return self._current_session
    
    def load_session(self, session_id: str) -> Optional[Tuple[SessionData, MeasurementData]]:
        """Load session by ID"""
        result = self._session_storage.load_session(session_id)
        if result:
            self._current_session, self._current_measurement = result
        return result
    
    def delete_session(self, session_id: str) -> bool:
        """Delete session"""
        return self._session_storage.delete_session(session_id)
    
    def archive_session(self, session_id: str) -> bool:
        """Archive session"""
        return self._session_storage.archive_session(session_id)
    
    def list_sessions(self, include_auto_save: bool = True) -> List[Dict[str, Any]]:
        """List all sessions"""
        return self._session_storage.list_sessions(include_auto_save=include_auto_save)
    
    def get_current_session(self) -> Optional[SessionData]:
        """Get current session"""
        return self._current_session
    
    def get_session_path(self) -> Optional[str]:
        """Get current session path"""
        if self._current_session:
            return self._session_storage.get_session_path()
        return None
    
    # ========== Current Measurement Management ==========
    
    def set_current_measurement(self, measurement: MeasurementData) -> None:
        """Set current measurement"""
        self._current_measurement = measurement
    
    def get_current_measurement(self) -> Optional[MeasurementData]:
        """Get current measurement"""
        return self._current_measurement
    
    def create_empty_measurement(self) -> MeasurementData:
        """Create empty measurement"""
        self._current_measurement = MeasurementData()
        return self._current_measurement
    
    def clear_current_measurement(self) -> None:
        """Clear current measurement"""
        self._current_measurement = MeasurementData()
    
    def is_current_valid(self) -> bool:
        """Check if current measurement is valid"""
        if self._current_measurement:
            return self._current_measurement.is_valid()
        return False
    
    # ========== Export Operations ==========
    
    def export_ti3(self, measurement: MeasurementData, filepath: str) -> bool:
        """Export to TI3 format"""
        return self._cgats_exporter.export_ti3(measurement, filepath)
    
    def export_cgats(self, measurement: MeasurementData, filepath: str) -> bool:
        """Export to CGATS format"""
        return self._cgats_exporter.export_cgats(measurement, filepath)
    
    def export_csv(
        self,
        measurement: MeasurementData,
        filepath: str,
        include_gamut: bool = True,
        include_gamma: bool = True,
    ) -> bool:
        """Export to CSV format"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                # Write gamut data
                if include_gamut:
                    f.write("# 色域数据\n")
                    f.write("Color,RGB_R,RGB_G,RGB_B,XYZ_X,XYZ_Y,XYZ_Z,xy_x,xy_y,Y\n")
                    gamut = measurement.get_gamut()
                    for color_name, color_data in gamut.items():
                        if color_data:
                            rgb = color_data.get('RGB', [0, 0, 0])
                            xyz = color_data.get('XYZ', [0, 0, 0])
                            xyY = color_data.get('xyY', {})
                            f.write(f"{color_name},{rgb[0]},{rgb[1]},{rgb[2]},")
                            f.write(f"{xyz[0]:.4f},{xyz[1]:.4f},{xyz[2]:.4f},")
                            f.write(f"{xyY.get('x', 0):.4f},{xyY.get('y', 0):.4f},{xyY.get('Y', 0):.4f}\n")
                    f.write("\n")
                
                # Write gamma data
                if include_gamma:
                    f.write("# 灰阶数据\n")
                    f.write("RGB_R,RGB_G,RGB_B,XYZ_X,XYZ_Y,XYZ_Z,xy_x,xy_y,Y\n")
                    gamma = measurement.get_gray_scale()
                    for gray_point in gamma:
                        rgb = gray_point.get('RGB', [0, 0, 0])
                        xyz = gray_point.get('XYZ', [0, 0, 0])
                        xyY = gray_point.get('xyY', {})
                        f.write(f"{rgb[0]},{rgb[1]},{rgb[2]},")
                        f.write(f"{xyz[0]:.4f},{xyz[1]:.4f},{xyz[2]:.4f},")
                        f.write(f"{xyY.get('x', 0):.4f},{xyY.get('y', 0):.4f},{xyY.get('Y', 0):.4f}\n")
            
            return True
        except Exception as e:
            logger.error(f"Export CSV failed: {e}")
            return False
    
    def export_json(
        self,
        measurement: MeasurementData,
        filepath: str,
        include_gamut: bool = True,
        include_gamma: bool = True,
    ) -> bool:
        """Export to JSON format"""
        try:
            data = {
                "metadata": {
                    "software": "Topos Calibrator",
                    "version": "0.1.0-preview",
                    "timestamp": datetime.now().isoformat()
                }
            }
            
            if include_gamut:
                data["gamut"] = measurement.get_gamut()
            
            if include_gamma:
                data["grayScale"] = measurement.get_gray_scale()
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            logger.error(f"Export JSON failed: {e}")
            return False
    
    def export_measurement(
        self,
        measurement: MeasurementData,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Export measurement with params
        
        Args:
            measurement: MeasurementData to export
            params: Export params (format, file_path, file_name, include_gamut, include_gamma)
            
        Returns:
            Dict with success, filepath, format
        """
        format_type = params.get("format", "csv")
        file_path = params.get("file_path", "")
        file_name = params.get("file_name", "export")
        include_gamut = params.get("include_gamut", True)
        include_gamma = params.get("include_gamma", True)
        
        if file_path:
            full_path = Path(file_path)
        else:
            if self._measurements_dir:
                project_measurements_dir = Path(self._measurements_dir)
            else:
                project_measurements_dir = Path(__file__).parent.parent.parent / "measurements"
            project_measurements_dir.mkdir(parents=True, exist_ok=True)
            extension = ".csv" if format_type == "csv" else ".json"
            full_path = project_measurements_dir / (file_name + extension)
        
        if not measurement.is_valid():
            return {
                "success": False,
                "message": "没有有效的测量数据",
            }
        
        if format_type == "csv":
            success = self.export_csv(full_path, include_gamut, include_gamma)
            format_name = "CSV"
        elif format_type == "json":
            success = self.export_json(full_path, include_gamut, include_gamma)
            format_name = "JSON"
        else:
            return {
                "success": False,
                "message": f"不支持的导出格式: {format_type}",
            }
        
        if success:
            return {
                "success": True,
                "filepath": str(full_path),
                "format": format_name,
            }
        else:
            return {
                "success": False,
                "message": f"导出{format_name}文件失败",
            }
    
    # ========== CAL File Operations ==========
    
    def list_cal_files(self) -> List[str]:
        """List CAL files"""
        return self._data_storage.list_cal_files()
    
    # ========== Legacy Format Sync ==========
    
    def sync_measurement_to_legacy_format(
        self,
        measurement: MeasurementData,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Sync MeasurementData to legacy format for compatibility
        
        Args:
            measurement: MeasurementData instance
            
        Returns:
            Tuple of (gamut_measurements dict, gamma_measurements list)
        """
        gamut = measurement.measurements.get("gamut", {})
        
        # Color mapping
        color_map = {
            "red": "红",
            "green": "绿",
            "blue": "蓝",
            "white": "白",
            "black": "黑"
        }
        
        gamut_measurements = {}
        for eng_key, chn_name in color_map.items():
            if eng_key in gamut and gamut[eng_key].get("xyY"):
                xyY = gamut[eng_key]["xyY"]
                rgb = gamut[eng_key]["RGB"]
                gamut_measurements[chn_name] = {
                    "patchName": chn_name,
                    "rgb": {"r": rgb[0], "g": rgb[1], "b": rgb[2]},
                    "x": xyY[0],
                    "y": xyY[1],
                    "Y": xyY[2]
                }
        
        # Gamma data
        gamma = measurement.measurements.get("gamma", [])
        gamma_measurements = []
        for point in gamma:
            rgb = point.get("RGB", [128, 128, 128])
            gamma_measurements.append({
                "patchName": point.get("patch_name", f"{point['input']}%"),
                "rgb": {"r": rgb[0], "g": rgb[1], "b": rgb[2]},
                "x": 0.3127,
                "y": 0.3290,
                "Y": point["Y"]
            })
        
        return gamut_measurements, gamma_measurements


__all__ = [
    "StorageFacade",
]

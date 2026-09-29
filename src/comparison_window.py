"""
ComparisonWindow - 数据对比窗口
用于对比多条历史测量数据

P6-C 任务升级：
    - 分组显示：按 display、target、workflow、date 分组历史记录
    - Before/After 对比：固定展示相同指标
    - Golden Baseline：支持标记 golden baseline，后续测量与之对比
    - 防止误对比：不同目标标准的数据不会被误放在同一对比结论里
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QFileDialog
from PyQt6.QtCore import QUrl, QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel

from .data_storage import DataStorage, MeasurementData
from . import i18n
from .measurement_analyzer import MeasurementAnalyzer

# 导入 P5-A/P5-B 的 schema 和 manifest（如果可用）
try:
    from .storage.schema import SchemaV1, MeasurementSchema, get_schema_version
    from .storage.manifest import ArtifactManifest, load_manifest, ManifestManager
    from .storage.storage_service import StorageService
    SCHEMA_AVAILABLE = True
except ImportError:
    SCHEMA_AVAILABLE = False

# 导入 P4-D 验证工作流（如果可用）
try:
    from .workflows.validation_workflow import (
        ValidationThreshold,
        STANDARD_THRESHOLDS,
        get_threshold_for_standard,
        MeasurementType,
    )
    VALIDATION_AVAILABLE = True
except ImportError:
    VALIDATION_AVAILABLE = False

logger = logging.getLogger(__name__)


# ==============================================================================
# Golden Baseline 管理
# ==============================================================================

class GoldenBaselineManager:
    """
    Golden Baseline 管理器
    
    支持标记某次测量为 golden baseline，后续测量与之对比。
    
    Golden baseline 存储在 measurements/golden_baselines.json 中：
    {
        "baselines": {
            "<display_id>": {
                "<target_standard>": {
                    "measurement_id": "...",
                    "marked_at": "...",
                    "notes": "...",
                }
            }
        }
    }
    """
    
    GOLDEN_FILE = "golden_baselines.json"
    
    def __init__(self, measurements_dir: Path):
        self.measurements_dir = Path(measurements_dir)
        self.golden_file = self.measurements_dir / self.GOLDEN_FILE
        self._baselines: Dict[str, Dict[str, Dict]] = {}
        self._load()
    
    def _load(self):
        """加载 golden baseline 数据"""
        if self.golden_file.exists():
            try:
                with open(self.golden_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._baselines = data.get("baselines", {})
                logger.info(f"已加载 {len(self._baselines)} 个 golden baseline 配置")
            except Exception as e:
                logger.error(f"加载 golden baseline 失败: {e}")
                self._baselines = {}
    
    def _save(self):
        """保存 golden baseline 数据"""
        try:
            self.measurements_dir.mkdir(parents=True, exist_ok=True)
            with open(self.golden_file, 'w', encoding='utf-8') as f:
                json.dump({"baselines": self._baselines}, f, indent=2, ensure_ascii=False)
            logger.info("Golden baseline 数据已保存")
        except Exception as e:
            logger.error(f"保存 golden baseline 失败: {e}")
    
    def mark_baseline(self, measurement_id: str, display_id: str, 
                      target_standard: str, notes: str = "") -> bool:
        """
        标记某次测量为 golden baseline
        
        Args:
            measurement_id: 测量 ID
            display_id: 显示器标识（display_model 或 display_name）
            target_standard: 目标标准（如 sRGB、DCI-P3 等）
            notes: 备注
            
        Returns:
            bool: 是否成功
        """
        if display_id not in self._baselines:
            self._baselines[display_id] = {}
        
        self._baselines[display_id][target_standard] = {
            "measurement_id": measurement_id,
            "marked_at": datetime.now().isoformat(),
            "notes": notes,
        }
        
        self._save()
        return True
    
    def unmark_baseline(self, display_id: str, target_standard: str) -> bool:
        """
        取消 golden baseline 标记
        
        Args:
            display_id: 显示器标识
            target_standard: 目标标准
            
        Returns:
            bool: 是否成功
        """
        if display_id in self._baselines:
            if target_standard in self._baselines[display_id]:
                del self._baselines[display_id][target_standard]
                self._save()
                return True
        return False
    
    def get_baseline(self, display_id: str, target_standard: str) -> Optional[Dict]:
        """
        获取指定显示器和目标标准的 golden baseline
        
        Args:
            display_id: 显示器标识
            target_standard: 目标标准
            
        Returns:
            Dict: baseline 信息，包含 measurement_id、marked_at、notes
        """
        if display_id in self._baselines:
            return self._baselines[display_id].get(target_standard)
        return None
    
    def get_all_baselines(self) -> Dict[str, Dict[str, Dict]]:
        """
        获取所有 golden baseline
        
        Returns:
            Dict: {display_id: {target_standard: baseline_info}}
        """
        return self._baselines
    
    def is_baseline(self, measurement_id: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        检查某次测量是否是 golden baseline
        
        Args:
            measurement_id: 测量 ID
            
        Returns:
            Tuple: (是否是 baseline, display_id, target_standard)
        """
        for display_id, standards in self._baselines.items():
            for target_standard, info in standards.items():
                if info.get("measurement_id") == measurement_id:
                    return True, display_id, target_standard
        return False, None, None


# ==============================================================================
# 分组管理
# ==============================================================================

class MeasurementGroup:
    """
    测量数据分组
    
    按 display、target、workflow、date 分组历史记录。
    """
    
    def __init__(self, group_key: str, group_type: str, display_name: str = ""):
        self.group_key = group_key  # 分组键值（如 display_model、target_standard 等）
        self.group_type = group_type  # 分组类型（display、target、workflow、date）
        self.display_name = display_name or group_key  # 用于显示的名称
        self.measurements: List[Dict] = []  # 该组内的测量数据列表
    
    def add_measurement(self, measurement: Dict):
        """添加测量数据到组"""
        self.measurements.append(measurement)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "group_key": self.group_key,
            "group_type": self.group_type,
            "display_name": self.display_name,
            "count": len(self.measurements),
            "measurements": self.measurements,
        }


class GroupingManager:
    """
    分组管理器
    
    提供按不同维度分组测量数据的功能。
    """
    
    @staticmethod
    def group_by_display(measurements: List[Dict]) -> List[MeasurementGroup]:
        """
        按 display 分组
        
        使用 display_model 或 display_type 作为分组键。
        """
        groups: Dict[str, MeasurementGroup] = {}
        
        for m in measurements:
            # 使用 display_model 作为主要分组键，如果没有则使用 display_type
            display_key = m.get("display_model") or m.get("display_type") or "未知显示器"
            
            if display_key not in groups:
                groups[display_key] = MeasurementGroup(
                    group_key=display_key,
                    group_type="display",
                    display_name=display_key
                )
            
            groups[display_key].add_measurement(m)
        
        # 按测量数量排序
        result = list(groups.values())
        result.sort(key=lambda g: len(g.measurements), reverse=True)
        return result
    
    @staticmethod
    def group_by_target(measurements: List[Dict]) -> List[MeasurementGroup]:
        """
        按 target standard 分组
        
        从 workflow.target 或 metadata 中提取目标标准。
        """
        groups: Dict[str, MeasurementGroup] = {}
        
        for m in measurements:
            # 尝试从多个字段提取目标标准
            target_key = m.get("target_standard") or m.get("workflow_target") or ""
            
            # 如果没有明确的目标标准，尝试从 measure_mode 推断
            if not target_key:
                measure_mode = m.get("measure_mode", "")
                # 常见模式：gamut、icc、lut 等，默认对应 sRGB
                if measure_mode in ["gamut", "icc", "gamma"]:
                    target_key = "sRGB"
                elif measure_mode == "lut":
                    target_key = "Rec.709"
                else:
                    target_key = "未指定目标"
            
            if target_key not in groups:
                groups[target_key] = MeasurementGroup(
                    group_key=target_key,
                    group_type="target",
                    display_name=target_key
                )
            
            groups[target_key].add_measurement(m)
        
        # 按测量数量排序
        result = list(groups.values())
        result.sort(key=lambda g: len(g.measurements), reverse=True)
        return result
    
    @staticmethod
    def group_by_workflow(measurements: List[Dict]) -> List[MeasurementGroup]:
        """
        按 workflow 分组
        
        使用 measure_mode 或 workflow.mode 作为分组键。
        """
        groups: Dict[str, MeasurementGroup] = {}
        
        workflow_names = {
            "gamut": "色域测量",
            "gamma": "Gamma 曲线",
            "icc": "ICC 校准",
            "lut": "3D LUT",
            "dispcal": "显示器校准",
            "ccmx": "CCMX 制作",
            "custom": "自定义色块",
        }
        
        for m in measurements:
            workflow_key = m.get("measure_mode") or m.get("workflow_mode") or "未知模式"
            
            display_name = workflow_names.get(workflow_key, workflow_key)
            
            if workflow_key not in groups:
                groups[workflow_key] = MeasurementGroup(
                    group_key=workflow_key,
                    group_type="workflow",
                    display_name=display_name
                )
            
            groups[workflow_key].add_measurement(m)
        
        # 按测量数量排序
        result = list(groups.values())
        result.sort(key=lambda g: len(g.measurements), reverse=True)
        return result
    
    @staticmethod
    def group_by_date(measurements: List[Dict]) -> List[MeasurementGroup]:
        """
        按 date 分组
        
        使用日期（YYYY-MM-DD）作为分组键。
        """
        groups: Dict[str, MeasurementGroup] = {}
        
        for m in measurements:
            timestamp = m.get("timestamp", "")
            
            # 提取日期部分
            if timestamp:
                try:
                    if "T" in timestamp:
                        date_key = timestamp.split("T")[0]
                    else:
                        date_key = timestamp.split(" ")[0] if " " in timestamp else timestamp[:10]
                except:
                    date_key = "未知日期"
            else:
                date_key = "未知日期"
            
            if date_key not in groups:
                groups[date_key] = MeasurementGroup(
                    group_key=date_key,
                    group_type="date",
                    display_name=date_key
                )
            
            groups[date_key].add_measurement(m)
        
        # 按日期排序（最新的在前）
        result = list(groups.values())
        result.sort(key=lambda g: g.group_key, reverse=True)
        return result
    
    @staticmethod
    def group_measurements(measurements: List[Dict], group_type: str) -> List[MeasurementGroup]:
        """
        按指定类型分组
        
        Args:
            measurements: 测量数据列表
            group_type: 分组类型（display、target、workflow、date）
            
        Returns:
            List[MeasurementGroup]: 分组列表
        """
        group_functions = {
            "display": GroupingManager.group_by_display,
            "target": GroupingManager.group_by_target,
            "workflow": GroupingManager.group_by_workflow,
            "date": GroupingManager.group_by_date,
        }
        
        func = group_functions.get(group_type)
        if func:
            return func(measurements)
        
        # 默认按 display 分组
        return GroupingManager.group_by_display(measurements)


# ==============================================================================
# Before/After 对比结果
# ==============================================================================

class BeforeAfterResult:
    """
    Before/After 对比结果
    
    包含校准前后各项指标的对比数据。
    """
    
    def __init__(self, before_id: str, after_id: str):
        self.before_id = before_id
        self.after_id = after_id
        
        # Delta E 对比
        self.delta_e_before_avg: Optional[float] = None
        self.delta_e_before_max: Optional[float] = None
        self.delta_e_after_avg: Optional[float] = None
        self.delta_e_after_max: Optional[float] = None
        self.delta_e_improvement_avg: Optional[float] = None  # 改善量
        self.delta_e_improved: bool = False
        
        # 白点对比
        self.white_point_before_cct: Optional[int] = None
        self.white_point_before_duv: Optional[float] = None
        self.white_point_after_cct: Optional[int] = None
        self.white_point_after_duv: Optional[float] = None
        self.white_point_cct_improvement: Optional[int] = None
        self.white_point_improved: bool = False
        
        # Gamma 对比
        self.gamma_before: Optional[float] = None
        self.gamma_after: Optional[float] = None
        self.gamma_improvement: Optional[float] = None
        self.gamma_improved: bool = False
        
        # 色域对比
        self.gamut_coverage_before: Optional[float] = None
        self.gamut_coverage_after: Optional[float] = None
        self.gamut_coverage_improvement: Optional[float] = None
        self.gamut_improved: bool = False
        
        # 对比度对比
        self.contrast_before: Optional[float] = None
        self.contrast_after: Optional[float] = None
        self.contrast_improvement: Optional[float] = None
        self.contrast_improved: bool = False
        
        # 亮度对比
        self.luminance_before: Optional[float] = None
        self.luminance_after: Optional[float] = None
        
        # 整体评估
        self.overall_improved: bool = False
        self.summary: str = ""
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "before_id": self.before_id,
            "after_id": self.after_id,
            "delta_e": {
                "before_avg": self.delta_e_before_avg,
                "before_max": self.delta_e_before_max,
                "after_avg": self.delta_e_after_avg,
                "after_max": self.delta_e_after_max,
                "improvement_avg": self.delta_e_improvement_avg,
                "improved": self.delta_e_improved,
            },
            "white_point": {
                "before_cct": self.white_point_before_cct,
                "before_duv": self.white_point_before_duv,
                "after_cct": self.white_point_after_cct,
                "after_duv": self.white_point_after_duv,
                "cct_improvement": self.white_point_cct_improvement,
                "improved": self.white_point_improved,
            },
            "gamma": {
                "before": self.gamma_before,
                "after": self.gamma_after,
                "improvement": self.gamma_improvement,
                "improved": self.gamma_improved,
            },
            "gamut_coverage": {
                "before": self.gamut_coverage_before,
                "after": self.gamut_coverage_after,
                "improvement": self.gamut_coverage_improvement,
                "improved": self.gamut_improved,
            },
            "contrast": {
                "before": self.contrast_before,
                "after": self.contrast_after,
                "improvement": self.contrast_improvement,
                "improved": self.contrast_improved,
            },
            "luminance": {
                "before": self.luminance_before,
                "after": self.luminance_after,
            },
            "overall_improved": self.overall_improved,
            "summary": self.summary,
        }


# ==============================================================================
# ComparisonBackend - 数据对比窗口后端
# ==============================================================================

class ComparisonBackend(QObject):
    """
    数据对比窗口的后端通信类
    通过 QWebChannel 暴露给前端
    
    P6-C 升级功能：
    - 分组显示：按 display、target、workflow、date 分组
    - Golden Baseline：标记和对比
    - 防误对比：检查目标标准一致性
    - Before/After 对比：固定指标对比
    """
    
    # 信号定义
    logMessage = pyqtSignal(str)
    measurementListUpdated = pyqtSignal(str)  # 测量列表 JSON
    groupedMeasurementListUpdated = pyqtSignal(str)  # 分组后的测量列表 JSON
    comparisonDataUpdated = pyqtSignal(str)   # 对比数据 JSON
    goldenBaselineUpdated = pyqtSignal(str)   # Golden baseline 状态更新
    beforeAfterComparisonUpdated = pyqtSignal(str)  # Before/After 对比结果
    compatibilityCheckResult = pyqtSignal(str)  # 兼容性检查结果
    errorOccurred = pyqtSignal(str)           # 错误消息
    measurementRenamed = pyqtSignal()         # 数据重命名通知
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data_storage = DataStorage()
        self._analyzer = MeasurementAnalyzer()
        self._loaded_measurements: Dict[str, MeasurementData] = {}
        
        # P6-C 新增
        self._golden_manager = GoldenBaselineManager(self._data_storage.base_path)
        self._current_group_type = "display"  # 当前分组类型
        self._cached_measurements: List[Dict] = []  # 缓存的测量列表
    
    @pyqtSlot()
    def ping(self):
        """测试通信"""
        self.logMessage.emit("ComparisonBackend: 通信正常")
    
    @pyqtSlot()
    def load_measurement_list(self):
        """
        加载所有历史测量数据列表
        返回包含 id, timestamp, probe, display_type, measure_mode, target_standard 的列表
        
        P6-C 升级：
        - 从 v1 schema 读取 target_standard
        - 从 manifest 读取更多信息
        """
        try:
            raw_list = self._data_storage.get_all_saved_measurements()
            
            measurements = []
            for item in raw_list:
                json_path = item.get("json_path", "")
                
                measurement_data = self._load_measurement_metadata(json_path, item)
                measurements.append(measurement_data)
            
            # 按时间戳排序
            measurements.sort(
                key=lambda x: self._parse_timestamp(x.get("timestamp", "")),
                reverse=True
            )
            
            self._cached_measurements = measurements
            
            # 发送原始列表（不分组）
            result = {"measurements": measurements}
            self.measurementListUpdated.emit(json.dumps(result, ensure_ascii=False))
            
            # 同时发送分组列表
            self._emit_grouped_list()
            
            # 发送 golden baseline 状态
            self._emit_golden_baselines()
            
            self.logMessage.emit(f"已加载 {len(measurements)} 条历史测量数据")
            
        except Exception as e:
            self.errorOccurred.emit(f"加载测量列表失败: {str(e)}")
            self.logMessage.emit(f"错误: {str(e)}")
    
    def _load_measurement_metadata(self, json_path: str, item: Dict) -> Dict:
        """
        加载单个测量数据的元数据
        
        P6-C 升级：支持读取 v1 schema 格式的数据
        """
        measurement_id = Path(json_path).stem if json_path else item.get("name", "")
        
        # 基础数据
        result = {
            "id": measurement_id,
            "name": item.get("name", ""),
            "json_path": json_path,
            "timestamp": item.get("timestamp", ""),
            "probe": item.get("probe", ""),
            "display_type": item.get("display_type", ""),
            "display_model": item.get("display_model", ""),
            "display_name": item.get("display_name", ""),
            "measure_mode": item.get("measure_mode", ""),
            "has_gamut": False,
            "has_gamma": False,
            "has_lut": False,
            "target_standard": "",  # P6-C 新增
            "workflow_target": "",  # P6-C 新增
            "is_golden_baseline": False,  # P6-C 新增
            "golden_display": None,  # P6-C 新增
            "golden_target": None,  # P6-C 新增
        }
        
        if json_path and Path(json_path).exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 检查 schema 版本
                schema_version = data.get("schema_version", "0")
                
                if schema_version == "1.0" and SCHEMA_AVAILABLE:
                    # v1 schema 格式
                    result = self._parse_v1_schema(data, result)
                else:
                    # 旧格式
                    result = self._parse_legacy_format(data, result)
                
                # 检查是否是 golden baseline
                is_golden, golden_display, golden_target = self._golden_manager.is_baseline(measurement_id)
                result["is_golden_baseline"] = is_golden
                result["golden_display"] = golden_display
                result["golden_target"] = golden_target
                
            except Exception as e:
                logger.debug(f"读取 {json_path} 失败: {e}")
        
        return result
    
    def _parse_v1_schema(self, data: Dict, result: Dict) -> Dict:
        """
        解析 v1 schema 格式的数据
        
        Args:
            data: JSON 数据
            result: 已解析的基础数据
            
        Returns:
            Dict: 完整的测量数据信息
        """
        # workflow 信息
        workflow = data.get("workflow", {})
        result["measure_mode"] = workflow.get("mode", result.get("measure_mode", ""))
        result["target_standard"] = workflow.get("target", "")
        result["workflow_target"] = workflow.get("target", "")
        
        # display 信息
        display = data.get("display", {})
        result["display_type"] = display.get("type", result.get("display_type", ""))
        result["display_model"] = display.get("model", result.get("display_model", ""))
        result["display_name"] = display.get("display_name", result.get("display_name", ""))
        
        # instrument 信息
        instrument = data.get("instrument", {})
        result["probe"] = instrument.get("probe", result.get("probe", ""))
        
        # 时间戳
        result["timestamp"] = data.get("created_at", result.get("timestamp", ""))
        
        # measurements 数据类型检查
        measurements = data.get("measurements", {})
        result["has_gamut"] = "gamut" in measurements
        result["has_gamma"] = "gamma" in measurements and len(measurements.get("gamma", [])) > 0
        result["has_lut"] = "lut_patches" in measurements and len(measurements.get("lut_patches", [])) > 0
        
        return result
    
    def _parse_legacy_format(self, data: Dict, result: Dict) -> Dict:
        """
        解析旧格式数据
        """
        metadata = data.get("metadata", {})
        
        result["probe"] = metadata.get("probe", result.get("probe", ""))
        result["display_name"] = metadata.get("display_name", result.get("display_name", ""))
        result["display_model"] = metadata.get("display_model", result.get("display_model", ""))
        result["display_type"] = metadata.get("display_type", result.get("display_type", ""))
        result["measure_mode"] = metadata.get("measure_mode", result.get("measure_mode", ""))
        result["timestamp"] = metadata.get("timestamp", result.get("timestamp", ""))
        
        # 尝试从旧格式推断目标标准
        measure_mode = result.get("measure_mode", "")
        if measure_mode in ["gamut", "icc", "gamma"]:
            result["target_standard"] = "sRGB"
        elif measure_mode == "lut":
            result["target_standard"] = "Rec.709"
        
        measurements = data.get("measurements", {})
        result["has_gamut"] = "gamut" in measurements
        result["has_gamma"] = "gamma" in measurements and len(measurements.get("gamma", [])) > 0
        result["has_lut"] = "lut" in measurements or "custom_patches" in measurements
        
        return result
    
    def _parse_timestamp(self, ts) -> datetime:
        """解析时间戳"""
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts)
        try:
            return datetime.fromisoformat(str(ts))
        except:
            return datetime.min
    
    @pyqtSlot(str)
    def set_group_type(self, group_type: str):
        """
        设置分组类型
        
        Args:
            group_type: 分组类型（display、target、workflow、date）
        """
        self._current_group_type = group_type
        self._emit_grouped_list()
    
    def _emit_grouped_list(self):
        """发送分组后的测量列表"""
        groups = GroupingManager.group_measurements(
            self._cached_measurements,
            self._current_group_type
        )
        
        result = {
            "group_type": self._current_group_type,
            "groups": [g.to_dict() for g in groups],
        }
        
        self.groupedMeasurementListUpdated.emit(json.dumps(result, ensure_ascii=False))
    
    def _emit_golden_baselines(self):
        """发送 golden baseline 状态"""
        baselines = self._golden_manager.get_all_baselines()
        
        # 为每个测量数据标记是否是 baseline
        marked_ids = []
        for display_id, standards in baselines.items():
            for target_standard, info in standards.items():
                marked_ids.append({
                    "measurement_id": info.get("measurement_id"),
                    "display_id": display_id,
                    "target_standard": target_standard,
                    "marked_at": info.get("marked_at"),
                    "notes": info.get("notes", ""),
                })
        
        result = {
            "baselines": baselines,
            "marked_measurements": marked_ids,
        }
        
        self.goldenBaselineUpdated.emit(json.dumps(result, ensure_ascii=False))
    
    @pyqtSlot(str, str, str, str, result=str)
    def mark_golden_baseline(self, measurement_id: str, display_id: str,
                             target_standard: str, notes: str = "") -> str:
        """
        标记某次测量为 golden baseline
        
        Args:
            measurement_id: 测量 ID
            display_id: 显示器标识
            target_standard: 目标标准
            notes: 备注
            
        Returns:
            str: 操作结果 JSON
        """
        try:
            success = self._golden_manager.mark_baseline(
                measurement_id, display_id, target_standard, notes
            )
            
            if success:
                # 刷新列表
                self.load_measurement_list()
                
                result = {
                    "success": True,
                    "message": f"已标记为 {target_standard} 的 Golden Baseline",
                }
                self.logMessage.emit(f"Golden Baseline 已标记: {measurement_id}")
            else:
                result = {
                    "success": False,
                    "message": "标记失败",
                }
            
            return json.dumps(result, ensure_ascii=False)
            
        except Exception as e:
            error_msg = f"标记失败: {str(e)}"
            self.errorOccurred.emit(error_msg)
            return json.dumps({"success": False, "message": error_msg}, ensure_ascii=False)
    
    @pyqtSlot(str, str, result=str)
    def unmark_golden_baseline(self, display_id: str, target_standard: str) -> str:
        """
        取消 golden baseline 标记
        
        Args:
            display_id: 显示器标识
            target_standard: 目标标准
            
        Returns:
            str: 操作结果 JSON
        """
        try:
            success = self._golden_manager.unmark_baseline(display_id, target_standard)
            
            if success:
                self.load_measurement_list()
                result = {
                    "success": True,
                    "message": "已取消 Golden Baseline 标记",
                }
                self.logMessage.emit(f"Golden Baseline 已取消: {display_id}/{target_standard}")
            else:
                result = {
                    "success": False,
                    "message": "未找到对应的 Golden Baseline",
                }
            
            return json.dumps(result, ensure_ascii=False)
            
        except Exception as e:
            error_msg = f"取消标记失败: {str(e)}"
            self.errorOccurred.emit(error_msg)
            return json.dumps({"success": False, "message": error_msg}, ensure_ascii=False)
    
    @pyqtSlot(str, result=str)
    def check_compatibility(self, measurement_ids_json: str) -> str:
        """
        检查多条测量数据的兼容性（是否可以安全对比）
        
        P6-C 防误对比功能：
        - 检查目标标准是否一致
        - 检查显示器是否一致（可选）
        - 检查测量类型是否一致
        
        Args:
            measurement_ids_json: JSON 字符串，包含要检查的测量ID列表
            
        Returns:
            str: 兼容性检查结果 JSON
        """
        try:
            ids = json.loads(measurement_ids_json)
            
            if len(ids) < 2:
                return json.dumps({
                    "compatible": True,
                    "warnings": [],
                    "errors": [],
                    "message": "单条数据无需检查兼容性",
                }, ensure_ascii=False)
            
            # 获取各条数据的详细信息
            measurements_info = []
            for mid in ids:
                info = next((m for m in self._cached_measurements if m.get("id") == mid), None)
                if info:
                    measurements_info.append(info)
            
            warnings = []
            errors = []
            
            # 1. 检查目标标准是否一致
            targets = set()
            for info in measurements_info:
                target = info.get("target_standard") or info.get("workflow_target") or ""
                if target:
                    targets.add(target)
            
            if len(targets) > 1:
                errors.append({
                    "type": "target_mismatch",
                    "message": f"目标标准不一致: {', '.join(targets)}",
                    "details": list(targets),
                })
            elif len(targets) == 0:
                warnings.append({
                    "type": "target_unknown",
                    "message": "部分数据未指定目标标准，对比结果可能不准确",
                })
            
            # 2. 检查显示器是否一致（警告级别）
            displays = set()
            for info in measurements_info:
                display = info.get("display_model") or info.get("display_type") or ""
                if display:
                    displays.add(display)
            
            if len(displays) > 1:
                warnings.append({
                    "type": "display_mismatch",
                    "message": f"显示器不一致: {', '.join(displays)}",
                    "details": list(displays),
                })
            
            # 3. 检查测量类型是否一致
            modes = set()
            for info in measurements_info:
                mode = info.get("measure_mode", "")
                if mode:
                    modes.add(mode)
            
            if len(modes) > 1:
                warnings.append({
                    "type": "mode_mismatch",
                    "message": f"测量类型不一致: {', '.join(modes)}",
                    "details": list(modes),
                })
            
            # 构建结果
            compatible = len(errors) == 0
            
            if compatible and len(warnings) == 0:
                message = "数据兼容，可以安全对比"
            elif compatible:
                message = f"数据可对比，但有 {len(warnings)} 个警告"
            else:
                message = f"数据不兼容，有 {len(errors)} 个错误"
            
            result = {
                "compatible": compatible,
                "warnings": warnings,
                "errors": errors,
                "message": message,
                "target_standard": list(targets)[0] if len(targets) == 1 else "",
                "display": list(displays)[0] if len(displays) == 1 else "",
            }
            
            self.compatibilityCheckResult.emit(json.dumps(result, ensure_ascii=False))
            return json.dumps(result, ensure_ascii=False)
            
        except Exception as e:
            error_msg = f"兼容性检查失败: {str(e)}"
            self.errorOccurred.emit(error_msg)
            return json.dumps({
                "compatible": False,
                "warnings": [],
                "errors": [{"type": "check_error", "message": error_msg}],
                "message": error_msg,
            }, ensure_ascii=False)
    
    @pyqtSlot(str)
    def load_measurements_for_comparison(self, measurement_ids_json: str):
        """
        加载指定的测量数据用于对比
        
        P6-C 升级：
        - 先进行兼容性检查
        - 如果不兼容，发出警告但仍加载数据
        """
        try:
            ids = json.loads(measurement_ids_json)
            self._loaded_measurements.clear()
            
            # 先检查兼容性
            compat_result = json.loads(self.check_compatibility(measurement_ids_json))
            
            # 加载数据
            for mid in ids:
                data = self._data_storage.load_measurement(mid)
                if data and data.is_valid():
                    self._loaded_measurements[mid] = data
            
            self.logMessage.emit(f"已加载 {len(self._loaded_measurements)} 条测量数据用于对比")
            
            # 如果有兼容性问题，记录警告
            if not compat_result.get("compatible", True):
                self.errorOccurred.emit(f"兼容性警告: {compat_result.get('message', '')}")
            
            # 计算并发送对比数据
            self._calculate_and_emit_comparison_data()

        except Exception as e:
            self.errorOccurred.emit(f"加载测量数据失败: {str(e)}")
            self.logMessage.emit(f"错误: {str(e)}")

    @staticmethod
    def _mccamy_cct(x: float, y: float) -> Optional[float]:
        """McCamy 近似：xy 色度 → CCT (K)"""
        try:
            denom = 0.1858 - y
            if abs(denom) < 1e-9:
                return None
            n = (x - 0.3320) / denom
            cct = 449 * n ** 3 + 3525 * n ** 2 + 6823.3 * n + 5520.33
            return round(cct) if 1000 < cct < 25000 else None
        except Exception:
            return None

    @staticmethod
    def _fit_gamma(gamma_points: list) -> Optional[float]:
        """灰阶 log-log 线性回归拟合平均 Gamma（5%-95% 输入范围）"""
        import math
        xs, ys = [], []
        for p in gamma_points or []:
            try:
                lvl = float(p.get("input", 0)) / 100.0
                Y = float(p.get("Y", 0))
            except (TypeError, ValueError):
                continue
            if 0.05 <= lvl <= 0.95 and Y > 0:
                xs.append(math.log(lvl))
                ys.append(math.log(Y))
        if len(xs) < 2:
            return None
        n = len(xs)
        mx = sum(xs) / n
        my = sum(ys) / n
        var = sum((v - mx) ** 2 for v in xs)
        if var < 1e-12:
            return None
        cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        return round(cov / var, 4)

    @pyqtSlot(str, result=str)
    def get_trend_data(self, measurement_ids_json: str) -> str:
        """
        按时间序列计算会话关键指标（供趋势图）

        每个会话输出：白点亮度 Y、白点 xy/CCT、灰阶 Gamma 拟合值。

        Args:
            measurement_ids_json: JSON 数组，测量 ID 列表

        Returns:
            JSON: {"success": true, "points": [{id, timestamp, name,
                     whiteY, white_x, white_y, whiteCCT, gamma}, ...]}
                  按时间戳升序排列
        """
        try:
            ids = json.loads(measurement_ids_json)
        except Exception as e:
            return json.dumps({"success": False, "error": f"ID 列表解析失败: {e}"})

        points = []
        for mid in ids:
            try:
                data = self._data_storage.load_measurement(mid)
            except Exception:
                data = None
            if data is None or not data.is_valid():
                continue

            measurements = data.measurements or {}
            metadata = data.metadata or {}

            point = {
                "id": mid,
                "timestamp": metadata.get("timestamp", ""),
                "name": metadata.get("display_name")
                        or metadata.get("display_model")
                        or metadata.get("display_type", ""),
                "probe": metadata.get("probe", ""),
            }

            white = (measurements.get("gamut") or {}).get("white") or {}
            xyY = white.get("xyY")
            if xyY and len(xyY) >= 3:
                point["whiteY"] = round(float(xyY[2]), 2)
                point["white_x"] = float(xyY[0])
                point["white_y"] = float(xyY[1])
                cct = self._mccamy_cct(float(xyY[0]), float(xyY[1]))
                if cct:
                    point["whiteCCT"] = cct

            gamma = self._fit_gamma(measurements.get("gamma"))
            if gamma:
                point["gamma"] = gamma

            if "whiteY" in point or "gamma" in point:
                points.append(point)

        points.sort(key=lambda p: p.get("timestamp", ""))
        return json.dumps({"success": True, "points": points}, ensure_ascii=False)
    
    @pyqtSlot(str, str, result=str)
    def compare_with_golden_baseline(self, measurement_id: str, target_standard: str) -> str:
        """
        将指定测量与 golden baseline 对比
        
        Args:
            measurement_id: 要对比的测量 ID
            target_standard: 目标标准
            
        Returns:
            str: 对比结果 JSON
        """
        try:
            # 获取测量数据信息
            info = next((m for m in self._cached_measurements if m.get("id") == measurement_id), None)
            if not info:
                return json.dumps({
                    "success": False,
                    "message": "未找到测量数据",
                }, ensure_ascii=False)
            
            display_id = info.get("display_model") or info.get("display_type") or ""
            
            # 获取 golden baseline
            baseline = self._golden_manager.get_baseline(display_id, target_standard)
            if not baseline:
                return json.dumps({
                    "success": False,
                    "message": f"未找到 {display_id} 的 {target_standard} Golden Baseline",
                    "has_baseline": False,
                }, ensure_ascii=False)
            
            baseline_id = baseline.get("measurement_id")
            
            # 加载两条数据
            baseline_data = self._data_storage.load_measurement(baseline_id)
            current_data = self._data_storage.load_measurement(measurement_id)
            
            if not baseline_data or not current_data:
                return json.dumps({
                    "success": False,
                    "message": "无法加载测量数据",
                }, ensure_ascii=False)
            
            # 计算 Before/After 对比
            result = self._calculate_before_after_comparison(
                baseline_id, baseline_data,
                measurement_id, current_data,
                target_standard
            )
            
            self.beforeAfterComparisonUpdated.emit(json.dumps(result.to_dict(), ensure_ascii=False))
            
            return json.dumps({
                "success": True,
                "has_baseline": True,
                "baseline_id": baseline_id,
                "comparison": result.to_dict(),
            }, ensure_ascii=False)
            
        except Exception as e:
            error_msg = f"对比失败: {str(e)}"
            self.errorOccurred.emit(error_msg)
            return json.dumps({
                "success": False,
                "message": error_msg,
            }, ensure_ascii=False)
    
    def _calculate_before_after_comparison(
        self,
        before_id: str, before_data: MeasurementData,
        after_id: str, after_data: MeasurementData,
        target_standard: str = "sRGB"
    ) -> BeforeAfterResult:
        """
        计算 Before/After 对比结果
        
        P6-C 功能：固定展示相同指标
        - Delta E 平均值、最大值
        - 白点 CCT、Duv
        - Gamma
        - 色域覆盖率
        - 对比度
        """
        result = BeforeAfterResult(before_id, after_id)
        
        # 计算各自的汇总数据
        before_summary = self._calculate_summary_row(before_data, before_data.metadata)
        after_summary = self._calculate_summary_row(after_data, after_data.metadata)
        
        # Delta E 对比
        before_delta_e = self._calculate_delta_e_values(before_data.measurements.get("gamut", {}))
        after_delta_e = self._calculate_delta_e_values(after_data.measurements.get("gamut", {}))
        
        result.delta_e_before_avg = before_delta_e.get("avg")
        result.delta_e_before_max = max(
            [v for v in before_delta_e.values() if v is not None and v != before_delta_e.get("avg")] or [0]
        )
        result.delta_e_after_avg = after_delta_e.get("avg")
        result.delta_e_after_max = max(
            [v for v in after_delta_e.values() if v is not None and v != after_delta_e.get("avg")] or [0]
        )
        
        if result.delta_e_before_avg and result.delta_e_after_avg:
            result.delta_e_improvement_avg = result.delta_e_before_avg - result.delta_e_after_avg
            result.delta_e_improved = result.delta_e_improvement_avg > 0
        
        # 白点对比
        result.white_point_before_cct = before_summary.get("whiteCCT")
        result.white_point_after_cct = after_summary.get("whiteCCT")
        
        if result.white_point_before_cct and result.white_point_after_cct:
            # 计算相对于目标（如 D65 = 6500K）的偏移改善
            target_cct = 6500 if target_standard in ["sRGB", "Rec.709", "Display P3"] else 5000
            before_offset = abs(result.white_point_before_cct - target_cct)
            after_offset = abs(result.white_point_after_cct - target_cct)
            result.white_point_cct_improvement = before_offset - after_offset
            result.white_point_improved = after_offset < before_offset
        
        # Gamma 对比
        result.gamma_before = before_summary.get("gamma")
        result.gamma_after = after_summary.get("gamma")
        
        if result.gamma_before and result.gamma_after:
            target_gamma = 2.2  # 默认目标
            before_offset = abs(result.gamma_before - target_gamma)
            after_offset = abs(result.gamma_after - target_gamma)
            result.gamma_improvement = before_offset - after_offset
            result.gamma_improved = after_offset < before_offset
        
        # 色域覆盖率对比
        before_coverage = before_summary.get("gamutCoverage", {})
        after_coverage = after_summary.get("gamutCoverage", {})
        
        # 根据目标标准选择覆盖率
        if target_standard in ["DCI-P3", "Display P3"]:
            result.gamut_coverage_before = before_coverage.get("DCI_P3")
            result.gamut_coverage_after = after_coverage.get("DCI_P3")
        elif target_standard == "Adobe RGB":
            result.gamut_coverage_before = before_coverage.get("AdobeRGB")
            result.gamut_coverage_after = after_coverage.get("AdobeRGB")
        elif target_standard == "Rec.2020":
            result.gamut_coverage_before = before_coverage.get("Rec2020")
            result.gamut_coverage_after = after_coverage.get("Rec2020")
        else:
            result.gamut_coverage_before = before_coverage.get("sRGB")
            result.gamut_coverage_after = after_coverage.get("sRGB")
        
        if result.gamut_coverage_before and result.gamut_coverage_after:
            result.gamut_coverage_improvement = result.gamut_coverage_after - result.gamut_coverage_before
            result.gamut_improved = result.gamut_coverage_improvement > 0
        
        # 对比度对比
        result.contrast_before = before_summary.get("contrastRatio")
        result.contrast_after = after_summary.get("contrastRatio")
        
        if result.contrast_before and result.contrast_after:
            # 对比度变化率（不是改善）
            result.contrast_improvement = (result.contrast_after - result.contrast_before) / result.contrast_before * 100
            # 对比度通常不需要改善，保持稳定即可
        
        # 亮度对比
        result.luminance_before = before_summary.get("peakLuminance")
        result.luminance_after = after_summary.get("peakLuminance")
        
        # 整体评估
        improvements = [
            result.delta_e_improved,
            result.white_point_improved,
            result.gamma_improved,
            result.gamut_improved,
        ]
        result.overall_improved = sum(1 for i in improvements if i) >= 2
        
        # 生成摘要
        if result.overall_improved:
            result.summary = "整体改善，校准效果良好"
        elif sum(1 for i in improvements if not i) >= 2:
            result.summary = "多项指标未改善，建议重新校准"
        else:
            result.summary = "部分改善，效果一般"
        
        return result
    
    def _calculate_and_emit_comparison_data(self):
        """
        计算对比数据并发送信号
        包括：色域对比、Gamma对比、关键参数表格、详细色块数据
        """
        if not self._loaded_measurements:
            return
        
        comparison_data = {
            "gamut_data": [],
            "gamma_data": [],
            "summary_table": [],
            "detail_data": [],
            "colors": [],
            "metadata_list": [],
            "target_standards": [],  # P6-C 新增
            "display_info": "",  # P6-C 新增
        }
        
        comparison_colors = [
            "#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6",
            "#ec4899", "#06b6d4", "#84cc16", "#f97316", "#6366f1",
        ]
        
        # 收集目标标准和显示器信息
        targets = set()
        displays = set()
        
        for idx, (mid, data) in enumerate(self._loaded_measurements.items()):
            color = comparison_colors[idx % len(comparison_colors)]
            metadata = data.metadata
            measurements = data.measurements
            
            # 获取该条数据的详细信息
            info = next((m for m in self._cached_measurements if m.get("id") == mid), None)
            if info:
                target = info.get("target_standard") or info.get("workflow_target") or ""
                if target:
                    targets.add(target)
                display = info.get("display_model") or info.get("display_type") or ""
                if display:
                    displays.add(display)
            
            # 色域数据
            gamut = measurements.get("gamut", {})
            gamut_triangle = self._extract_gamut_triangle(gamut)
            if gamut_triangle:
                comparison_data["gamut_data"].append({
                    "id": mid,
                    "name": self._format_display_name(metadata),
                    "shortName": self._format_short_name(metadata, idx),
                    "color": color,
                    "triangle": gamut_triangle,
                    "white_point": gamut_triangle.get("white"),
                })
            
            # Gamma 曲线数据
            gamma_points = measurements.get("gamma", [])
            if gamma_points:
                gamma_curve = self._process_gamma_curve(gamma_points)
                comparison_data["gamma_data"].append({
                    "id": mid,
                    "name": self._format_display_name(metadata),
                    "shortName": self._format_short_name(metadata, idx),
                    "color": color,
                    "curve": gamma_curve,
                    "avg_gamma": self._calculate_average_gamma(gamma_points),
                })
            
            # 汇总表格行
            summary_row = self._calculate_summary_row(data, metadata)
            summary_row["id"] = mid
            summary_row["name"] = self._format_short_name(metadata, idx)
            summary_row["color"] = color
            # P6-C: 添加目标标准标注
            if info:
                summary_row["target_standard"] = info.get("target_standard", "")
            comparison_data["summary_table"].append(summary_row)
            
            # 详细色块数据
            detail_item = self._calculate_detail_data(data, metadata, color, idx)
            comparison_data["detail_data"].append(detail_item)
            
            comparison_data["colors"].append(color)
            
            # 元数据列表
            metadata_item = {
                "color": color,
                "name": self._format_short_name(metadata, idx),
                "timestamp": metadata.get("timestamp", ""),
                "probe": metadata.get("probe", ""),
                "display_type": metadata.get("display_type", ""),
                "display_model": metadata.get("display_model", ""),
                "measure_mode": metadata.get("measure_mode", ""),
            }
            if info:
                metadata_item["target_standard"] = info.get("target_standard", "")
                metadata_item["is_golden_baseline"] = info.get("is_golden_baseline", False)
            comparison_data["metadata_list"].append(metadata_item)
        
        # 设置目标标准列表和显示器信息
        comparison_data["target_standards"] = list(targets)
        comparison_data["display_info"] = ", ".join(displays) if displays else ""
        
        # 标记最佳值
        self._mark_best_values(comparison_data["summary_table"])
        
        self.comparisonDataUpdated.emit(json.dumps(comparison_data, ensure_ascii=False))
    
    # === 保留原有方法 ===
    
    def _extract_gamut_triangle(self, gamut: Dict) -> Optional[Dict]:
        """从测量数据提取色域三角形坐标"""
        result = {}
        for color_key in ["red", "green", "blue", "white", "black"]:
            if gamut.get(color_key) and gamut[color_key].get("xyY"):
                xyY = gamut[color_key]["xyY"]
                result[color_key] = [xyY[0], xyY[1]]
        
        if "red" in result and "green" in result and "blue" in result:
            return result
        return None
    
    def _process_gamma_curve(self, gamma_points: List[Dict]) -> List[Dict]:
        """处理 Gamma 曲线数据点"""
        if not gamma_points:
            return []
        
        max_Y = max(p.get("Y", 0) for p in gamma_points) or 100
        
        curve = []
        for point in gamma_points:
            input_level = point.get("input", 0)
            Y = point.get("Y", 0)
            normalized_Y = (Y / max_Y) * 100 if max_Y > 0 else 0
            
            curve.append({
                "input": input_level,
                "Y": round(Y, 2),
                "normalizedY": round(normalized_Y, 1),
            })
        
        curve.sort(key=lambda x: x["input"])
        return curve
    
    def _calculate_average_gamma(self, gamma_points: List[Dict]) -> Optional[float]:
        """计算平均 Gamma 值"""
        if len(gamma_points) < 2:
            return None
        
        try:
            formatted_points = []
            for p in gamma_points:
                formatted_points.append({
                    "patchName": f"{p.get('input', 0)}%",
                    "Y": p.get("Y", 0),
                })
            self._analyzer.set_gamma_data(formatted_points)
            gamma_value = self._analyzer.calculate_gamma()
            return round(gamma_value, 2) if gamma_value else None
        except:
            return None
    
    def _calculate_summary_row(self, data: MeasurementData, metadata: Dict) -> Dict:
        """计算汇总表格的单行数据"""
        gamut = data.measurements.get("gamut", {})
        gamma_points = data.measurements.get("gamma", [])
        
        white = gamut.get("white", {})
        white_xyY = white.get("xyY") if white else None
        
        black = gamut.get("black", {})
        black_xyY = black.get("xyY") if black else None
        
        gamut_coverage = {}
        if self._extract_gamut_triangle(gamut):
            red = gamut.get("red", {})
            green = gamut.get("green", {})
            blue = gamut.get("blue", {})
            
            red_xyY = red.get("xyY") if red else None
            green_xyY = green.get("xyY") if green else None
            blue_xyY = blue.get("xyY") if blue else None
            
            if red_xyY and green_xyY and blue_xyY:
                self._analyzer.set_gamut_data(
                    {"x": red_xyY[0], "y": red_xyY[1], "Y": red_xyY[2]},
                    {"x": green_xyY[0], "y": green_xyY[1], "Y": green_xyY[2]},
                    {"x": blue_xyY[0], "y": blue_xyY[1], "Y": blue_xyY[2]},
                    {"x": white_xyY[0], "y": white_xyY[1], "Y": white_xyY[2]} if white_xyY else {}
                )
                gamut_coverage = {
                    "sRGB": round(self._analyzer.calculate_gamut_coverage("sRGB"), 1),
                    "DCI_P3": round(self._analyzer.calculate_gamut_coverage("DCI-P3"), 1),
                    "AdobeRGB": round(self._analyzer.calculate_gamut_coverage("Adobe RGB"), 1),
                    "Rec2020": round(self._analyzer.calculate_gamut_coverage("Rec.2020"), 1),
                }
        
        contrast_ratio = None
        peak_Y = white_xyY[2] if white_xyY else None
        black_Y = black_xyY[2] if black_xyY else None
        if peak_Y and black_Y and black_Y > 0:
            contrast_ratio = round(peak_Y / black_Y, 1)
        
        return {
            "timestamp": metadata.get("timestamp", ""),
            "probe": metadata.get("probe", "未知"),
            "display_type": metadata.get("display_type", "未知"),
            "peakLuminance": round(white_xyY[2], 2) if white_xyY else None,
            "blackLuminance": round(black_xyY[2], 4) if black_xyY else None,
            "contrastRatio": contrast_ratio,
            "whiteX": round(white_xyY[0], 4) if white_xyY else None,
            "whiteY": round(white_xyY[1], 4) if white_xyY else None,
            "whiteCCT": self._calculate_cct(white_xyY) if white_xyY else None,
            "gamma": self._calculate_average_gamma(gamma_points),
            "gamutCoverage": gamut_coverage,
        }
    
    def _calculate_cct(self, xyY: List[float]) -> Optional[int]:
        """计算白点 CCT（相关色温）"""
        if not xyY:
            return None
        try:
            cct = self._analyzer.calculate_cct(xyY[0], xyY[1])
            return round(cct) if cct else None
        except:
            return None
    
    def _format_display_name(self, metadata: Dict) -> str:
        """格式化显示名称（用于图表标签）"""
        timestamp = metadata.get("timestamp", "")
        probe = metadata.get("probe", "未知")
        
        if timestamp:
            try:
                date_part = timestamp.split("T")[0]
                return f"{date_part} ({probe})"
            except:
                pass
        
        return f"{probe}"
    
    def _format_short_name(self, metadata: Dict, idx: int) -> str:
        """格式化短名称（用于详细表格表头）"""
        timestamp = metadata.get("timestamp", "")
        if timestamp:
            try:
                date_part = timestamp.split("T")[0]
                time_part = timestamp.split("T")[1][:5] if "T" in timestamp else ""
                month_day = date_part[5:]
                return f"{month_day} {time_part}"
            except:
                pass
        return f"数据{idx + 1}"
    
    def _calculate_detail_data(self, data: MeasurementData, metadata: Dict, color: str, idx: int) -> Dict:
        """计算详细色块数据（用于详细表格）"""
        gamut = data.measurements.get("gamut", {})
        gamma_points = data.measurements.get("gamma", [])
        
        white_xyY = gamut.get("white", {}).get("xyY") if gamut.get("white") else None
        white_cct = self._calculate_cct(white_xyY) if white_xyY else None
        
        delta_e = self._calculate_delta_e_values(gamut)
        avg_gamma = self._calculate_average_gamma(gamma_points)
        
        gamma_data = []
        for p in gamma_points:
            gamma_data.append({
                "input": p.get("input", 0),
                "Y": p.get("Y", 0),
                "RGB": p.get("RGB", []),
            })
        
        return {
            "id": metadata.get("measurement_id", ""),
            "name": self._format_display_name(metadata),
            "shortName": self._format_short_name(metadata, idx),
            "color": color,
            "gamut": gamut,
            "whiteCCT": white_cct,
            "deltaE": delta_e,
            "avgGamma": avg_gamma,
            "gammaPoints": gamma_data,
        }
    
    def _calculate_delta_e_values(self, gamut: Dict) -> Dict:
        """计算各色块相对于 sRGB 标准的 Delta E 值"""
        SRGB_TARGETS = {
            "red": {"x": 0.64, "y": 0.33, "Y": 21.26},
            "green": {"x": 0.30, "y": 0.60, "Y": 71.52},
            "blue": {"x": 0.15, "y": 0.06, "Y": 7.22},
            "white": {"x": 0.3127, "y": 0.3290, "Y": 100},
            "black": {"x": 0.3127, "y": 0.3290, "Y": 0},
        }
        
        delta_e_values = {}
        
        for color_key in ["red", "green", "blue", "white", "black"]:
            patch_data = gamut.get(color_key, {})
            xyY = patch_data.get("xyY")
            
            if xyY:
                target = SRGB_TARGETS.get(color_key)
                if target:
                    measured = {"x": xyY[0], "y": xyY[1], "Y": xyY[2]}
                    try:
                        de = self._analyzer.calculate_delta_e_2000(measured, target)
                        delta_e_values[color_key] = round(de, 2) if de else None
                    except:
                        try:
                            de = self._analyzer.calculate_delta_e(measured, target)
                            delta_e_values[color_key] = round(de, 2) if de else None
                        except:
                            delta_e_values[color_key] = None
        
        valid_values = [v for v in delta_e_values.values() if v is not None]
        if valid_values:
            delta_e_values["avg"] = round(sum(valid_values) / len(valid_values), 2)
        
        return delta_e_values
    
    def _mark_best_values(self, summary_table: List[Dict]):
        """标记表格中的最佳值（用于高亮显示）"""
        if len(summary_table) < 2:
            return
        
        contrast_values = [r.get("contrastRatio") for r in summary_table if r.get("contrastRatio")]
        if contrast_values:
            best_contrast = max(contrast_values)
            for row in summary_table:
                if row.get("contrastRatio") == best_contrast:
                    row["bestContrast"] = True
        
        gamma_values = [(r.get("gamma"), idx) for idx, r in enumerate(summary_table) if r.get("gamma")]
        if gamma_values:
            best_gamma_idx = min(gamma_values, key=lambda x: abs(x[0] - 2.2))[1]
            summary_table[best_gamma_idx]["bestGamma"] = True
        
        srgb_values = [(r.get("gamutCoverage", {}).get("sRGB"), idx) for idx, r in enumerate(summary_table)
                       if r.get("gamutCoverage", {}).get("sRGB")]
        if srgb_values:
            best_srgb_idx = max(srgb_values, key=lambda x: x[0])[1]
            summary_table[best_srgb_idx]["bestSRGB"] = True
    
    @pyqtSlot(str, str, result=str)
    def rename_measurement(self, measurement_id: str, new_name: str) -> str:
        """重命名测量数据的显示名称"""
        try:
            success = self._data_storage.rename_measurement(measurement_id, new_name)
            
            if success:
                self.load_measurement_list()
                self.measurementRenamed.emit()
                result = {"success": True, "message": f"已重命名为: {new_name}"}
                self.logMessage.emit(f"重命名成功: {measurement_id} -> {new_name}")
            else:
                result = {"success": False, "message": "重命名失败，请检查数据文件是否存在"}
                self.errorOccurred.emit(result["message"])
            
            return json.dumps(result, ensure_ascii=False)
            
        except Exception as e:
            error_msg = f"重命名失败: {str(e)}"
            self.errorOccurred.emit(error_msg)
            self.logMessage.emit(f"错误: {str(e)}")
            return json.dumps({"success": False, "message": error_msg}, ensure_ascii=False)
    
    @pyqtSlot(str, str, result=str)
    def save_html_file(self, html_content: str, default_filename: str) -> str:
        """保存 HTML 文件（弹出保存对话框）"""
        try:
            if not default_filename:
                timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
                default_filename = f"comparison-report-{timestamp}.html"
            
            filepath, _ = QFileDialog.getSaveFileName(
                None, "保存对比报告", default_filename,
                "HTML 文件 (*.html);;所有文件 (*)"
            )
            
            if not filepath:
                return json.dumps({
                    "success": False,
                    "filepath": "",
                    "message": "用户取消保存",
                }, ensure_ascii=False)
            
            if not filepath.lower().endswith('.html'):
                filepath += '.html'
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            self.logMessage.emit(f"报告已保存: {filepath}")
            
            return json.dumps({
                "success": True,
                "filepath": filepath,
                "message": "保存成功",
            }, ensure_ascii=False)
            
        except Exception as e:
            error_msg = f"保存文件失败: {str(e)}"
            self.logMessage.emit(error_msg)
            self.errorOccurred.emit(error_msg)
            return json.dumps({
                "success": False,
                "filepath": "",
                "message": error_msg,
            }, ensure_ascii=False)


# ==============================================================================
# ComparisonWindow - PyQt 主窗口
# ==============================================================================

class ComparisonWindow(QMainWindow):
    """
    数据对比窗口 - PyQt 主窗口
    使用 QWebEngineView 渲染 Web UI
    
    P6-C 升级功能：
    - 分组显示历史记录
    - Golden Baseline 标记和对比
    - Before/After 对比
    - 防误对比提示
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.backend = None
        self.channel = None
        
        self._init_ui()
        self._setup_web_channel()
    
    def _init_ui(self):
        """初始化界面"""
        self.setWindowTitle(i18n.t("Topos Calibrator - 数据对比"))
        self.setMinimumSize(1200, 800)
        
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0d0d14;
            }
        """)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.web_view = QWebEngineView()
        main_layout.addWidget(self.web_view)
        
        from PyQt6.QtWebEngineCore import QWebEngineProfile
        QWebEngineProfile.defaultProfile().setHttpCacheType(
            QWebEngineProfile.HttpCacheType.NoCache
        )
        
        self._load_html()
    
    def _load_html(self):
        """加载本地 HTML 文件"""
        html_path = Path(__file__).parent.parent / "web" / "comparison.html"
        
        if html_path.exists():
            self.web_view.setUrl(QUrl.fromLocalFile(str(html_path)))
        else:
            self.web_view.setHtml(f"""
                <html>
                <body style="background: #0d0d14; color: white;
                            font-family: sans-serif; padding: 20px;">
                    <h1>错误: HTML 文件未找到</h1>
                    <p>请确保文件存在: {html_path}</p>
                </body>
                </html>
            """)
    
    def _setup_web_channel(self):
        """设置 QWebChannel 通信"""
        self.backend = ComparisonBackend()
        self.channel = QWebChannel()
        self.channel.registerObject("backend", self.backend)
        self.web_view.page().setWebChannel(self.channel)
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        super().closeEvent(event)
"""
Schema Module - 数据结构定义和版本控制

定义 v1.0 schema 结构，提供验证和转换功能。
"""

import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from dataclasses import dataclass, field, asdict
import uuid
import platform
import sys


# Schema 版本常量
CURRENT_SCHEMA_VERSION = "1.0"
SUPPORTED_VERSIONS = ["1.0", "0"]  # 0 = legacy 无版本格式


@dataclass
class SoftwareInfo:
    """软件信息"""
    name: str = "Topos Calibrator"
    version: str = "0.1.0-preview"


@dataclass
class EnvironmentInfo:
    """环境信息"""
    os: str = ""
    os_version: str = ""
    argyll_version: str = ""
    python_version: str = ""

    def __post_init__(self):
        """自动填充环境信息"""
        if not self.os:
            self.os = platform.system().lower()
        if not self.os_version:
            self.os_version = platform.version()
        if not self.python_version:
            self.python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


@dataclass
class InstrumentInfo:
    """仪器信息"""
    probe: str = ""
    probe_serial: Optional[str] = None
    correction_file: Optional[str] = None
    correction_hash: Optional[str] = None


@dataclass
class DisplayInfo:
    """显示器信息"""
    type: str = ""  # l=LCD, o=OLED, c=CRT, p=投影仪
    model: str = ""
    display_id: str = ""
    display_name: str = ""
    resolution: Tuple[int, int] = (0, 0)
    refresh_rate: int = 0


@dataclass
class WorkflowInfo:
    """工作流信息"""
    mode: str = ""  # icc, lut, gamut, gamma, dispcal, custom, ccmx
    target: str = ""  # sRGB, Rec.709, DCI-P3, Rec.2020 等
    gamma_target: float = 2.2
    white_point_target: str = "D65"
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GamutMeasurement:
    """色域测量数据"""
    red: Dict[str, Any] = field(default_factory=lambda: {"RGB": [255, 0, 0], "xyY": None})
    green: Dict[str, Any] = field(default_factory=lambda: {"RGB": [0, 255, 0], "xyY": None})
    blue: Dict[str, Any] = field(default_factory=lambda: {"RGB": [0, 0, 255], "xyY": None})
    white: Dict[str, Any] = field(default_factory=lambda: {"RGB": [255, 255, 255], "xyY": None})
    black: Dict[str, Any] = field(default_factory=lambda: {"RGB": [0, 0, 0], "xyY": None})


@dataclass
class MeasurementsData:
    """测量数据"""
    gamut: GamutMeasurement = field(default_factory=GamutMeasurement)
    gamma: List[Dict[str, Any]] = field(default_factory=list)
    lut_patches: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ArtifactEntry:
    """单个 Artifact 信息"""
    type: str = ""  # measurement, ti3, cal, icc, lut, report
    filename: str = ""
    sha256: str = ""
    size_bytes: int = 0
    generated_at: str = ""
    generated_by: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ArtifactsInfo:
    """所有 Artifact 信息"""
    measurement_json: Optional[ArtifactEntry] = None
    ti3: Optional[ArtifactEntry] = None
    cal: Optional[ArtifactEntry] = None
    icc: Optional[ArtifactEntry] = None
    lut: Optional[ArtifactEntry] = None
    report: Optional[ArtifactEntry] = None


@dataclass
class AnalysisInfo:
    """分析结果（可选）"""
    gamut_coverage: Optional[Dict[str, Any]] = None
    gamma_result: Optional[Dict[str, Any]] = None
    delta_e_summary: Optional[Dict[str, Any]] = None
    white_point_result: Optional[Dict[str, Any]] = None


class SchemaVersion:
    """Schema 版本管理"""

    @staticmethod
    def get_current() -> str:
        """获取当前 schema 版本"""
        return CURRENT_SCHEMA_VERSION

    @staticmethod
    def is_supported(version: str) -> bool:
        """检查版本是否支持"""
        return version in SUPPORTED_VERSIONS

    @staticmethod
    def compare(v1: str, v2: str) -> int:
        """
        比较两个版本号
        
        Returns:
            -1: v1 < v2
            0: v1 == v2
            1: v1 > v2
        """
        # 简单字符串比较（假设版本格式为 "X.Y"）
        parts1 = v1.split(".")
        parts2 = v2.split(".")
        
        for i in range(max(len(parts1), len(parts2))):
            p1 = int(parts1[i]) if i < len(parts1) else 0
            p2 = int(parts2[i]) if i < len(parts2) else 0
            if p1 < p2:
                return -1
            if p1 > p2:
                return 1
        return 0


class SchemaV1:
    """
    Schema v1.0 数据结构
    
    新 JSON 根字段：
    - schema_version: 当前版本 "1.0"
    - session_id: 唯一会话 ID
    - created_at, updated_at: 时间戳
    - software, environment, instrument, display, workflow: 元数据
    - measurements: 测量数据
    - artifacts: 文件清单
    - analysis: 分析结果（可选）
    - status: 状态 (draft/completed/archived)
    - notes: 备注
    """

    def __init__(self):
        self.schema_version = CURRENT_SCHEMA_VERSION
        self.session_id = self._generate_session_id()
        self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
        
        self.software = SoftwareInfo()
        self.environment = EnvironmentInfo()
        self.instrument = InstrumentInfo()
        self.display = DisplayInfo()
        self.workflow = WorkflowInfo()
        
        self.measurements = MeasurementsData()
        self.artifacts = ArtifactsInfo()
        self.analysis = AnalysisInfo()
        
        self.status = "draft"
        self.notes = ""

    def _generate_session_id(self) -> str:
        """生成唯一会话 ID：YYYYMMDD-HHMMSS-XXXXXX"""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        random_suffix = uuid.uuid4().hex[:6]
        return f"{timestamp}-{random_suffix}"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "software": asdict(self.software),
            "environment": asdict(self.environment),
            "instrument": asdict(self.instrument),
            "display": asdict(self.display),
            "workflow": asdict(self.workflow),
            "measurements": {
                "gamut": asdict(self.measurements.gamut),
                "gamma": self.measurements.gamma,
                "lut_patches": self.measurements.lut_patches,
            },
            "artifacts": self._serialize_artifacts(),
            "status": self.status,
            "notes": self.notes,
        }
        
        # 可选字段：analysis
        if self.analysis.gamut_coverage or self.analysis.gamma_result:
            result["analysis"] = self._serialize_analysis()
        
        return result

    def _serialize_artifacts(self) -> Dict[str, Any]:
        """序列化 artifacts 字段"""
        artifacts = {}
        for field_name in ["measurement_json", "ti3", "cal", "icc", "lut", "report"]:
            entry = getattr(self.artifacts, field_name)
            if entry:
                artifacts[field_name] = asdict(entry)
            else:
                artifacts[field_name] = None
        return artifacts

    def _serialize_analysis(self) -> Dict[str, Any]:
        """序列化 analysis 字段"""
        analysis = {}
        if self.analysis.gamut_coverage:
            analysis["gamut_coverage"] = self.analysis.gamut_coverage
        if self.analysis.gamma_result:
            analysis["gamma_result"] = self.analysis.gamma_result
        if self.analysis.delta_e_summary:
            analysis["delta_e_summary"] = self.analysis.delta_e_summary
        if self.analysis.white_point_result:
            analysis["white_point_result"] = self.analysis.white_point_result
        return analysis

    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def from_dict(self, data: Dict[str, Any]):
        """从字典加载数据"""
        # 必须有 schema_version
        if "schema_version" not in data:
            raise ValueError("Missing schema_version field")
        
        version = data["schema_version"]
        if not SchemaVersion.is_supported(version):
            raise ValueError(f"Unsupported schema version: {version}")
        
        self.schema_version = version
        
        # 基础字段
        self.session_id = data.get("session_id", self._generate_session_id())
        self.created_at = data.get("created_at", datetime.now().isoformat())
        self.updated_at = data.get("updated_at", datetime.now().isoformat())
        self.status = data.get("status", "draft")
        self.notes = data.get("notes", "")
        
        # 软件信息
        if "software" in data:
            self.software = SoftwareInfo(**data["software"])
        
        # 环境信息
        if "environment" in data:
            env_data = data["environment"]
            self.environment = EnvironmentInfo(**env_data)
        
        # 仪器信息
        if "instrument" in data:
            inst_data = data["instrument"]
            self.instrument = InstrumentInfo(**inst_data)
        
        # 显示器信息
        if "display" in data:
            disp_data = data["display"]
            # resolution 可能是列表，需要转换为 tuple
            if "resolution" in disp_data and isinstance(disp_data["resolution"], list):
                disp_data["resolution"] = tuple(disp_data["resolution"])
            self.display = DisplayInfo(**disp_data)
        
        # 工作流信息
        if "workflow" in data:
            wf_data = data["workflow"]
            self.workflow = WorkflowInfo(**wf_data)
        
        # 测量数据
        if "measurements" in data:
            meas_data = data["measurements"]
            if "gamut" in meas_data:
                self.measurements.gamut = GamutMeasurement(**meas_data["gamut"])
            if "gamma" in meas_data:
                self.measurements.gamma = meas_data["gamma"]
            if "lut_patches" in meas_data:
                self.measurements.lut_patches = meas_data["lut_patches"]
        
        # Artifacts
        if "artifacts" in data:
            self._load_artifacts(data["artifacts"])
        
        # Analysis
        if "analysis" in data:
            self._load_analysis(data["analysis"])

    def _load_artifacts(self, artifacts_data: Dict[str, Any]):
        """加载 artifacts 数据"""
        for field_name in ["measurement_json", "ti3", "cal", "icc", "lut", "report"]:
            entry_data = artifacts_data.get(field_name)
            if entry_data and isinstance(entry_data, dict):
                setattr(self.artifacts, field_name, ArtifactEntry(**entry_data))
            else:
                setattr(self.artifacts, field_name, None)

    def _load_analysis(self, analysis_data: Dict[str, Any]):
        """加载 analysis 数据"""
        self.analysis.gamut_coverage = analysis_data.get("gamut_coverage")
        self.analysis.gamma_result = analysis_data.get("gamma_result")
        self.analysis.delta_e_summary = analysis_data.get("delta_e_summary")
        self.analysis.white_point_result = analysis_data.get("white_point_result")

    def from_json(self, json_str: str):
        """从 JSON 字符串加载数据"""
        data = json.loads(json_str)
        self.from_dict(data)

    def update_timestamp(self):
        """更新 updated_at 时间戳"""
        self.updated_at = datetime.now().isoformat()

    def set_instrument(self, probe: str, probe_serial: str = None,
                       correction_file: str = None, correction_hash: str = None):
        """设置仪器信息"""
        self.instrument.probe = probe
        self.instrument.probe_serial = probe_serial
        self.instrument.correction_file = correction_file
        self.instrument.correction_hash = correction_hash

    def set_display(self, display_type: str, model: str = "",
                    display_id: str = "", display_name: str = "",
                    resolution: Tuple[int, int] = (0, 0), refresh_rate: int = 0):
        """设置显示器信息"""
        self.display.type = display_type
        self.display.model = model
        self.display.display_id = display_id
        self.display.display_name = display_name
        self.display.resolution = resolution
        self.display.refresh_rate = refresh_rate

    def set_workflow(self, mode: str, target: str = "",
                     gamma_target: float = 2.2, white_point_target: str = "D65",
                     parameters: Dict = None):
        """设置工作流信息"""
        self.workflow.mode = mode
        self.workflow.target = target
        self.workflow.gamma_target = gamma_target
        self.workflow.white_point_target = white_point_target
        if parameters:
            self.workflow.parameters = parameters

    def add_artifact(self, artifact_type: str, filename: str, sha256: str,
                     size_bytes: int = 0, generated_by: str = ""):
        """添加 artifact 信息"""
        entry = ArtifactEntry(
            filename=filename,
            sha256=sha256,
            size_bytes=size_bytes,
            generated_at=datetime.now().isoformat(),
            generated_by=generated_by
        )
        
        valid_types = ["measurement_json", "ti3", "cal", "icc", "lut", "report"]
        if artifact_type in valid_types:
            setattr(self.artifacts, artifact_type, entry)
        else:
            raise ValueError(f"Invalid artifact type: {artifact_type}")

    def update_gamut_measurement(self, color_name: str, rgb: Tuple[int, int, int],
                                  x: float, y: float, Y: float):
        """
        更新色域测量数据
        
        Args:
            color_name: 颜色名称 ('red', 'green', 'blue', 'white', 'black')
            rgb: RGB 值元组
            x: CIE x 坐标
            y: CIE y 坐标
            Y: 亮度值
        """
        valid_colors = ["red", "green", "blue", "white", "black"]
        if color_name not in valid_colors:
            raise ValueError(f"Invalid color name: {color_name}")
        
        gamut_dict = {
            "RGB": list(rgb),
            "xyY": [round(x, 4), round(y, 4), round(Y, 2)]
        }
        
        # 直接设置 dataclass 字段
        setattr(self.measurements.gamut, color_name, gamut_dict)

    def update_gamma_measurement(self, input_level: float, Y: float,
                                  rgb: Tuple[int, int, int] = None):
        """
        更新灰阶测量数据
        
        Args:
            input_level: 输入级别百分比 (0-100)
            Y: 亮度值
            rgb: RGB 值元组（可选）
        """
        gamma_point = {
            "input": round(input_level, 1),
            "Y": round(Y, 2),
            "RGB": list(rgb) if rgb else [int(input_level * 255 / 100)] * 3
        }
        
        # 检查是否已存在
        existing_idx = None
        for i, item in enumerate(self.measurements.gamma):
            if item.get("input") == input_level:
                existing_idx = i
                break
        
        if existing_idx is not None:
            self.measurements.gamma[existing_idx] = gamma_point
        else:
            self.measurements.gamma.append(gamma_point)
        
        # 排序
        self.measurements.gamma.sort(key=lambda x: x["input"])

    def update_lut_measurement(self, sample_id: str, rgb: Tuple[int, int, int],
                                x: float, y: float, Y: float):
        """
        更新 LUT 色块测量数据
        
        Args:
            sample_id: 色块样本 ID
            rgb: RGB 值元组 (0-255)
            x: CIE x 坐标
            y: CIE y 坐标
            Y: 亮度值
        """
        lut_point = {
            "sample_id": sample_id,
            "RGB": list(rgb),
            "xyY": [round(x, 4), round(y, 4), round(Y, 2)]
        }
        
        # 检查是否已存在
        existing_idx = None
        for i, item in enumerate(self.measurements.lut_patches):
            if item.get("sample_id") == sample_id:
                existing_idx = i
                break
        
        if existing_idx is not None:
            self.measurements.lut_patches[existing_idx] = lut_point
        else:
            self.measurements.lut_patches.append(lut_point)

    def is_valid(self) -> bool:
        """检查数据是否有效（至少有部分测量数据）"""
        gamut_valid = any(
            v.get("xyY") is not None
            for v in asdict(self.measurements.gamut).values()
            if isinstance(v, dict)
        )
        gamma_valid = len(self.measurements.gamma) > 0
        lut_valid = len(self.measurements.lut_patches) > 0
        return gamut_valid or gamma_valid or lut_valid


class MeasurementSchema:
    """
    测量数据 Schema 工具类
    
    提供从旧格式 MeasurementData 转换为新 SchemaV1 的功能。
    """

    @staticmethod
    def from_legacy_dict(legacy_data: Dict[str, Any]) -> SchemaV1:
        """
        从旧格式字典转换为 SchemaV1
        
        Args:
            legacy_data: 旧格式数据，包含 "metadata" 和 "measurements" 字段
        
        Returns:
            SchemaV1: 新格式数据对象
        """
        schema = SchemaV1()
        
        # 从 metadata 转换
        metadata = legacy_data.get("metadata", {})
        
        # session_id - 使用 measurement_id 或生成新 ID
        measurement_id = metadata.get("measurement_id", "")
        if measurement_id:
            # 旧 ID 格式: YYYYMMDD_HHMMSS_XXXXXX
            # 新 ID 格式: YYYYMMDD-HHMMSS-XXXXXX
            schema.session_id = measurement_id.replace("_", "-")
        
        # 时间戳
        schema.created_at = metadata.get("timestamp", schema.created_at)
        schema.updated_at = schema.created_at
        
        # 软件
        schema.software.name = metadata.get("software", "Topos Calibrator")
        schema.software.version = metadata.get("version", "0.1.0-preview")
        
        # 仪器
        schema.instrument.probe = metadata.get("probe", "")
        
        # 显示器
        schema.display.type = metadata.get("display_type", "")
        schema.display.model = metadata.get("display_model", "")
        schema.display.display_name = metadata.get("display_name", "")
        
        # 工作流
        schema.workflow.mode = metadata.get("measure_mode", "")
        
        # 测量数据
        measurements = legacy_data.get("measurements", {})
        
        # 色域数据
        if "gamut" in measurements:
            gamut_data = measurements["gamut"]
            for color in ["red", "green", "blue", "white", "black"]:
                if color in gamut_data and gamut_data[color].get("xyY"):
                    rgb = gamut_data[color].get("RGB", [0, 0, 0])
                    xyY = gamut_data[color].get("xyY")
                    schema.update_gamut_measurement(color, tuple(rgb), xyY[0], xyY[1], xyY[2])
        
        # Gamma 数据
        if "gamma" in measurements:
            for gamma_point in measurements["gamma"]:
                input_level = gamma_point.get("input", 0)
                Y = gamma_point.get("Y", 0)
                rgb = gamma_point.get("RGB")
                schema.update_gamma_measurement(input_level, Y, tuple(rgb) if rgb else None)
        
        # LUT 数据
        if "lut_patches" in measurements:
            for lut_point in measurements["lut_patches"]:
                sample_id = lut_point.get("sample_id", "")
                rgb = lut_point.get("RGB", [0, 0, 0])
                xyY = lut_point.get("xyY", [0, 0, 0])
                schema.update_lut_measurement(sample_id, tuple(rgb), xyY[0], xyY[1], xyY[2])
        
        return schema

    @staticmethod
    def from_legacy_json(json_str: str) -> SchemaV1:
        """从旧格式 JSON 字符串转换为 SchemaV1"""
        data = json.loads(json_str)
        return MeasurementSchema.from_legacy_dict(data)

    @staticmethod
    def to_legacy_dict(schema: SchemaV1) -> Dict[str, Any]:
        """
        将 SchemaV1 转换为旧格式字典（用于兼容）
        
        Args:
            schema: SchemaV1 对象
        
        Returns:
            Dict: 旧格式数据
        """
        return {
            "metadata": {
                "software": schema.software.name,
                "version": schema.software.version,
                "timestamp": schema.created_at,
                "probe": schema.instrument.probe,
                "display_type": schema.display.type,
                "display_model": schema.display.model,
                "measure_mode": schema.workflow.mode,
                "measurement_id": schema.session_id.replace("-", "_"),
                "display_name": schema.display.display_name,
            },
            "measurements": {
                "gamut": asdict(schema.measurements.gamut),
                "gamma": schema.measurements.gamma,
                "lut_patches": schema.measurements.lut_patches,
            }
        }


def validate_schema(data: Dict[str, Any], version: str = None) -> Tuple[bool, List[str]]:
    """
    验证数据是否符合 schema
    
    Args:
        data: 数据字典
        version: 目标版本（可选，默认检查数据中的版本）
    
    Returns:
        Tuple[bool, List[str]]: (是否有效, 错误列表)
    """
    errors = []
    
    # 检查 schema_version
    if "schema_version" not in data:
        errors.append("Missing schema_version field")
        return False, errors
    
    actual_version = data["schema_version"]
    if version and actual_version != version:
        errors.append(f"Version mismatch: expected {version}, got {actual_version}")
        return False, errors
    
    if not SchemaVersion.is_supported(actual_version):
        errors.append(f"Unsupported schema version: {actual_version}")
        return False, errors
    
    # v1.0 必须字段检查
    if actual_version == "1.0":
        required_fields = [
            "schema_version", "session_id", "created_at", "updated_at",
            "software", "environment", "instrument", "display", "workflow",
            "measurements", "artifacts", "status"
        ]
        
        for field in required_fields:
            if field not in data:
                errors.append(f"Missing required field: {field}")
        
        # 检查 measurements 结构
        if "measurements" in data:
            meas = data["measurements"]
            if "gamut" not in meas:
                errors.append("Missing measurements.gamut")
    
    return len(errors) == 0, errors


def get_schema_version(data: Dict[str, Any]) -> str:
    """
    获取数据的 schema 版本
    
    Args:
        data: 数据字典
    
    Returns:
        str: 版本号，如果没有版本字段返回 "0"
    """
    return data.get("schema_version", "0")


def detect_schema_version(json_path: Path) -> str:
    """
    检测 JSON 文件的 schema 版本
    
    Args:
        json_path: JSON 文件路径
    
    Returns:
        str: 版本号
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return get_schema_version(data)
    except Exception as e:
        print(f"Error reading {json_path}: {e}")
        return "0"

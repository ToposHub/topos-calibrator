"""
DataStorage - 测量数据存储与管理模块
负责测量数据的保存、加载、列表管理和导出
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import uuid


class MeasurementData:
    """
    测量数据封装类
    统一封装测量数据和元数据
    """

    def __init__(self):
        self.metadata = {
            "software": "Topos Calibrator",
            "version": "0.1.0-preview",
            "timestamp": datetime.now().isoformat(),
            "probe": "",
            "display_type": "",
            "display_model": "",  # 显示器型号（自动获取，如 "PHL 439P1"）
            "measure_mode": "",  # 测量模式：gamut, icc, lut, custom, ccmx
            "measurement_id": self._generate_id(),
            "display_name": ""  # 用户自定义显示名称（可选）
        }
        self.measurements = {
            "gamut": {
                "red": {"RGB": [255, 0, 0], "xyY": None},
                "green": {"RGB": [0, 255, 0], "xyY": None},
                "blue": {"RGB": [0, 0, 255], "xyY": None},
                "white": {"RGB": [255, 255, 255], "xyY": None},
                "black": {"RGB": [0, 0, 0], "xyY": None}
            },
            "gamma": [],
            # LUT 模式：存储 ti1 生成的色块测量数据
            # 格式：[{"sample_id": "A1", "RGB": [r, g, b], "xyY": [x, y, Y]}, ...]
            "lut_patches": [],
            # 均匀性测量：网格测点数据
            # 格式：[{"row": 0, "col": 0, "xyY": [x, y, Y], "cct": 6500}, ...]
            "uniformity": []
        }

    def _generate_id(self) -> str:
        """生成唯一测量ID"""
        return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

    def regenerate_id(self):
        """重新生成测量ID（在保存时调用，确保每次保存都有唯一ID）"""
        self.metadata["measurement_id"] = self._generate_id()

    def set_probe(self, probe_type: str):
        """设置探头类型"""
        self.metadata["probe"] = probe_type

    def set_display_type(self, display_type: str):
        """设置显示器类型"""
        self.metadata["display_type"] = display_type

    def set_display_model(self, display_model: str):
        """设置显示器型号"""
        self.metadata["display_model"] = display_model

    def set_measure_mode(self, measure_mode: str):
        """设置测量模式"""
        self.metadata["measure_mode"] = measure_mode

    def set_timestamp(self, timestamp: str = None):
        """设置测量时间"""
        if timestamp:
            self.metadata["timestamp"] = timestamp
        else:
            self.metadata["timestamp"] = datetime.now().isoformat()

    def set_display_name(self, name: str):
        """设置显示名称"""
        self.metadata["display_name"] = name

    def set_correction_file(self, correction_hash: str, correction_path: str = "",
                            correction_descriptor: str = "", correction_type: str = "",
                            correction_instrument: str = "", correction_technology: str = "",
                            correction_reference: str = "", correction_created: str = ""):
        """
        设置修正文件信息

        Args:
            correction_hash: 修正文件的 SHA-256 hash
            correction_path: 修正文件路径
            correction_descriptor: 修正文件描述
            correction_type: 修正文件类型 (ccss/ccmx)
            correction_instrument: 目标探头类型
            correction_technology: 目标显示技术
            correction_reference: 基准探头类型
            correction_created: 创建时间
        """
        self.metadata["correction_file"] = {
            "hash": correction_hash,
            "path": correction_path,
            "descriptor": correction_descriptor,
            "type": correction_type,
            "instrument": correction_instrument,
            "technology": correction_technology,
            "reference": correction_reference,
            "created": correction_created
        }

    def get_correction_hash(self) -> str:
        """获取修正文件 hash"""
        correction_info = self.metadata.get("correction_file", {})
        return correction_info.get("hash", "")

    def get_correction_info(self) -> Dict:
        """获取修正文件完整信息"""
        return self.metadata.get("correction_file", {})

    def update_gamut_measurement(self, color_name: str, rgb: Tuple[int, int, int],
                                  x: float, y: float, Y: float):
        """
        更新色域测量数据

        Args:
            color_name: 颜色名称 ('红', '绿', '蓝', '白', '黑')
            rgb: RGB值元组
            x: CIE x坐标
            y: CIE y坐标
            Y: 亮度值
        """
        # 映射中文颜色名称到英文键
        color_map = {
            "红": "red",
            "绿": "green",
            "蓝": "blue",
            "白": "white",
            "黑": "black"
        }

        key = color_map.get(color_name, color_name.lower())
        if key in self.measurements["gamut"]:
            self.measurements["gamut"][key] = {
                "RGB": list(rgb),
                "xyY": [round(x, 4), round(y, 4), round(Y, 2)]
            }

    def update_gamma_measurement(self, input_level: float, Y: float, 
                                  patch_name: str = None, rgb: Tuple[int, int, int] = None):
        """
        更新灰阶测量数据

        Args:
            input_level: 输入级别百分比 (0-100)
            Y: 亮度值
            patch_name: 色块名称
            rgb: RGB值元组
        """
        # 查找是否已存在该灰阶数据
        existing_idx = None
        for i, item in enumerate(self.measurements["gamma"]):
            if item.get("input") == input_level:
                existing_idx = i
                break

        gamma_point = {
            "input": round(input_level, 1),
            "Y": round(Y, 2),
            "RGB": list(rgb) if rgb else [int(input_level * 255 / 100)] * 3
        }
        if patch_name:
            gamma_point["patch_name"] = patch_name

        if existing_idx is not None:
            self.measurements["gamma"][existing_idx] = gamma_point
        else:
            self.measurements["gamma"].append(gamma_point)

        # 按input排序
        self.measurements["gamma"].sort(key=lambda x: x["input"])

    def update_lut_measurement(self, sample_id: str, rgb: Tuple[int, int, int],
                                x: float, y: float, Y: float):
        """
        更新 LUT 色块测量数据

        用于存储 ti1 生成的色块测量结果，支持高精度 3D LUT 制作。

        Args:
            sample_id: 色块样本 ID（如 "A1", "Patch_1" 等）
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

        # 检查是否已存在相同 sample_id 的数据
        existing_idx = None
        for i, item in enumerate(self.measurements["lut_patches"]):
            if item.get("sample_id") == sample_id:
                existing_idx = i
                break

        if existing_idx is not None:
            self.measurements["lut_patches"][existing_idx] = lut_point
        else:
            self.measurements["lut_patches"].append(lut_point)

    def update_uniformity_measurement(self, row: int, col: int,
                                        x: float, y: float, Y: float,
                                        cct: float = None):
        """
        更新均匀性网格测点数据（同一 row/col 重复测量时覆盖）

        Args:
            row/col: 网格行列（0-based）
            x, y, Y: 测量色度与亮度
            cct: 相关色温（可选）
        """
        entries = self.measurements.setdefault("uniformity", [])
        point = {
            "row": int(row),
            "col": int(col),
            "xyY": [round(float(x), 4), round(float(y), 4), round(float(Y), 2)],
        }
        if cct is not None and cct == cct:
            point["cct"] = round(float(cct))
        existing = [e for e in entries if not (e.get("row") == point["row"] and e.get("col") == point["col"])]
        existing.append(point)
        self.measurements["uniformity"] = existing

    def get_lut_patch_count(self) -> int:
        """
        获取 LUT 色块测量数量

        Returns:
            int: 已测量的 LUT 色块数量
        """
        return len(self.measurements.get("lut_patches", []))

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {
            "metadata": self.metadata,
            "measurements": self.measurements
        }

    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def from_dict(self, data: Dict):
        """从字典加载数据"""
        if "metadata" in data:
            self.metadata = data["metadata"]
        if "measurements" in data:
            self.measurements = data["measurements"]

    def from_json(self, json_str: str):
        """从JSON字符串加载数据"""
        data = json.loads(json_str)
        self.from_dict(data)

    def is_valid(self) -> bool:
        """检查数据是否有效（至少有部分测量数据）"""
        gamut_valid = any(
            v.get("xyY") is not None
            for v in self.measurements["gamut"].values()
        )
        gamma_valid = len(self.measurements["gamma"]) > 0
        lut_valid = len(self.measurements.get("lut_patches", [])) > 0
        uniformity_valid = len(self.measurements.get("uniformity", [])) > 0
        return gamut_valid or gamma_valid or lut_valid or uniformity_valid

    def get_gamut_coverage_data(self) -> Dict:
        """获取色域覆盖率计算所需的数据"""
        gamut = self.measurements["gamut"]
        result = {}
        
        for color_key in ["red", "green", "blue", "white"]:
            if gamut.get(color_key) and gamut[color_key].get("xyY"):
                xyY = gamut[color_key]["xyY"]
                result[color_key] = {
                    "x": xyY[0],
                    "y": xyY[1],
                    "Y": xyY[2]
                }
        
        return result

    def get_gamma_curve_data(self) -> List[Dict]:
        """获取Gamma曲线数据"""
        return self.measurements["gamma"]


class SessionData:
    """
    会话元数据封装类
    用于关联和管理一次测量会话的所有文件
    """

    def __init__(self, measure_mode: str = ""):
        self.session_id = self._generate_session_id()
        self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
        self.software = {
            "name": "Topos Calibrator",
            "version": "0.1.0-preview"
        }
        self.hardware = {
            "probe": "",
            "display_type": "",
            "display_model": ""
        }
        self.measure_mode = measure_mode
        self.display_name = ""
        self.status = "draft"  # draft/completed/archived
        self.files = {
            "measurement": "measurement.json",
            "calibration": None,
            "ti3": None
        }
        self.tags = []
        self.notes = ""

    def _generate_session_id(self) -> str:
        """生成唯一会话ID：YYYYMMDD-HHMMSS-XXXXXX"""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        random_suffix = uuid.uuid4().hex[:6]
        return f"{timestamp}-{random_suffix}"

    def set_hardware(self, probe: str, display_type: str, display_model: str = ""):
        """设置硬件信息"""
        self.hardware["probe"] = probe
        self.hardware["display_type"] = display_type
        self.hardware["display_model"] = display_model

    def set_display_name(self, name: str):
        """设置显示名称"""
        self.display_name = name

    def set_status(self, status: str):
        """设置会话状态"""
        if status in ["draft", "completed", "archived"]:
            self.status = status

    def add_file(self, file_type: str, filename: str):
        """添加关联文件"""
        if file_type in ["measurement", "calibration", "ti3"]:
            self.files[file_type] = filename

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "software": self.software,
            "hardware": self.hardware,
            "measure_mode": self.measure_mode,
            "display_name": self.display_name,
            "status": self.status,
            "files": self.files,
            "tags": self.tags,
            "notes": self.notes
        }

    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def from_dict(self, data: Dict):
        """从字典加载数据"""
        self.session_id = data.get("session_id", self._generate_session_id())
        self.created_at = data.get("created_at", datetime.now().isoformat())
        self.updated_at = data.get("updated_at", datetime.now().isoformat())
        self.software = data.get("software", {"name": "Topos Calibrator", "version": "0.1.0-preview"})
        self.hardware = data.get("hardware", {"probe": "", "display_type": "", "display_model": ""})
        self.measure_mode = data.get("measure_mode", "")
        self.display_name = data.get("display_name", "")
        self.status = data.get("status", "draft")
        self.files = data.get("files", {"measurement": "measurement.json", "calibration": None, "ti3": None})
        self.tags = data.get("tags", [])
        self.notes = data.get("notes", "")

    def from_json(self, json_str: str):
        """从JSON字符串加载数据"""
        data = json.loads(json_str)
        self.from_dict(data)


class DataStorage:
    """
    测量数据存储管理类
    负责数据的持久化存储和加载
    """

    def __init__(self, base_path: str = None):
        """
        初始化数据存储

        Args:
            base_path: 存储根目录，默认为项目目录下的 'measurements' 文件夹
        """
        if base_path:
            self.base_path = Path(base_path)
        else:
            # 默认在项目目录下创建 measurements 文件夹
            project_root = Path(__file__).parent.parent
            self.base_path = project_root / "measurements"

        # 确保目录存在
        self._ensure_directory()

    def _ensure_directory(self):
        """确保存储目录存在"""
        if not self.base_path.exists():
            self.base_path.mkdir(parents=True, exist_ok=True)
            print(f"创建测量数据存储目录: {self.base_path}")

    def save_measurement(self, data: MeasurementData) -> str:
        """
        保存测量数据到文件

        文件名直接使用 measurement_id，确保加载时能正确找到文件
        例如：20260405_004100_abc123.json

        Args:
            data: MeasurementData 对象

        Returns:
            str: 保存的文件路径
        """
        # 文件名直接使用 measurement_id，确保与加载逻辑一致
        measurement_id = data.metadata.get('measurement_id', '')
        if not measurement_id:
            # 如果没有 ID，生成一个
            measurement_id = data._generate_id()
            data.metadata['measurement_id'] = measurement_id

        filename = f"{measurement_id}.json"
        filepath = self.base_path / filename

        # 写入JSON文件
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(data.to_json())

        print(f"测量数据已保存: {filepath}")
        return str(filepath)

    def load_measurement(self, measurement_id: str) -> Optional[MeasurementData]:
        """
        加载测量数据

        Args:
            measurement_id: 测量ID或文件名

        Returns:
            MeasurementData: 加载的数据对象，失败返回None
        """
        # 处理文件名格式
        if not measurement_id.endswith('.json'):
            filename = f"{measurement_id}.json"
        else:
            filename = measurement_id

        # 先在 base_path 直接查找
        filepath = self.base_path / filename
        
        if filepath.exists():
            return self._load_measurement_from_file(filepath)

        # 如果不在 base_path，尝试在 auto_save 子目录中查找
        auto_save_path = self.base_path / "auto_save"
        if auto_save_path.exists():
            # 遍历所有日期目录
            for date_dir in auto_save_path.iterdir():
                if date_dir.is_dir() and date_dir.name != "latest":
                    filepath = date_dir / filename
                    if filepath.exists():
                        return self._load_measurement_from_file(filepath)
        
        print(f"测量数据文件不存在: {filename}")
        return None
    
    def _load_measurement_from_file(self, filepath: Path) -> Optional[MeasurementData]:
        """
        从文件路径加载测量数据
        
        Args:
            filepath: 文件完整路径
            
        Returns:
            MeasurementData: 加载的数据对象，失败返回None
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                json_str = f.read()

            data = MeasurementData()
            data.from_json(json_str)
            return data
        except Exception as e:
            print(f"加载测量数据失败: {e}")
            return None

    def list_measurements(self) -> List[Dict]:
        """
        获取所有测量数据列表

        Returns:
            List[Dict]: 测量数据列表，每项包含 id, timestamp, probe, display_type, measure_mode, filename, display_name
        """
        measurements = []

        # 遍历所有JSON文件
        for filepath in self.base_path.glob("*.json"):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                metadata = data.get("metadata", {})
                measurements.append({
                    "id": metadata.get("measurement_id", filepath.stem),
                    "timestamp": metadata.get("timestamp", ""),
                    "probe": metadata.get("probe", "未知"),
                    "display_type": metadata.get("display_type", "未知"),
                    "display_model": metadata.get("display_model", ""),  # 显示器型号
                    "measure_mode": metadata.get("measure_mode", ""),
                    "display_name": metadata.get("display_name", ""),  # 用户自定义名称
                    "filename": filepath.name,
                    "has_gamut": self._check_has_gamut(data),
                    "has_gamma": self._check_has_gamma(data),
                    "has_lut": self._check_has_lut(data)
                })
            except Exception as e:
                print(f"读取文件失败 {filepath}: {e}")

        # 按时间排序（最新的在前）
        measurements.sort(key=lambda x: x["timestamp"], reverse=True)

        return measurements

    def _check_has_gamut(self, data: Dict) -> bool:
        """检查是否有色域测量数据"""
        gamut = data.get("measurements", {}).get("gamut", {})
        return any(
            v.get("xyY") is not None
            for v in gamut.values()
            if isinstance(v, dict)
        )

    def _check_has_gamma(self, data: Dict) -> bool:
        """检查是否有Gamma测量数据"""
        gamma = data.get("measurements", {}).get("gamma", [])
        return len(gamma) > 0

    def _check_has_lut(self, data: Dict) -> bool:
        """检查是否有LUT色块测量数据"""
        lut_patches = data.get("measurements", {}).get("lut_patches", [])
        return len(lut_patches) > 0

    def list_cal_files(self) -> List[Dict]:
        """
        获取所有 .cal 校准文件列表

        Returns:
            List[Dict]: cal文件列表，每项包含 filename, filepath, timestamp
        """
        cal_files = []

        # 遍历所有 .cal 文件
        for filepath in self.base_path.glob("*.cal"):
            try:
                stat = filepath.stat()
                cal_files.append({
                    "filename": filepath.name,
                    "filepath": str(filepath),
                    "timestamp": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
            except Exception as e:
                print(f"读取cal文件信息失败 {filepath}: {e}")

        # 按时间排序（最新的在前）
        cal_files.sort(key=lambda x: x["timestamp"], reverse=True)

        return cal_files

    def delete_measurement(self, measurement_id: str) -> bool:
        """
        删除测量数据文件

        Args:
            measurement_id: 测量ID或文件名

        Returns:
            bool: 是否成功删除
        """
        if not measurement_id.endswith('.json'):
            filename = f"{measurement_id}.json"
        else:
            filename = measurement_id

        filepath = self.base_path / filename

        if filepath.exists():
            try:
                filepath.unlink()
                print(f"已删除测量数据: {filepath}")
                return True
            except Exception as e:
                print(f"删除失败: {e}")
                return False

        return False

    def rename_measurement(self, measurement_id: str, new_display_name: str) -> bool:
        """
        重命名测量数据的显示名称

        Args:
            measurement_id: 测量ID或文件名
            new_display_name: 新的显示名称

        Returns:
            bool: 是否成功重命名
        """
        if not measurement_id.endswith('.json'):
            filename = f"{measurement_id}.json"
        else:
            filename = measurement_id

        filepath = self.base_path / filename

        if not filepath.exists():
            print(f"测量数据文件不存在: {filepath}")
            return False

        try:
            # 加载现有数据
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 更新显示名称
            if "metadata" not in data:
                data["metadata"] = {}
            data["metadata"]["display_name"] = new_display_name

            # 保存回文件
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            print(f"已重命名测量数据 {measurement_id}: {new_display_name}")
            return True

        except Exception as e:
            print(f"重命名失败: {e}")
            return False

    def get_storage_path(self) -> str:
        """获取存储目录路径"""
        return str(self.base_path)

    # ========== 自动保存功能 ==========

    def create_auto_save_directory(self) -> str:
        """
        创建自动保存目录结构

        Returns:
            str: 自动保存基础目录路径
        """
        auto_save_dir = self.base_path / "auto_save"
        if not auto_save_dir.exists():
            auto_save_dir.mkdir(parents=True, exist_ok=True)
            print(f"创建自动保存目录: {auto_save_dir}")
        return str(auto_save_dir)

    def get_auto_save_date_dir(self) -> str:
        """
        获取当前日期的自动保存目录

        Returns:
            str: 日期目录路径，格式为 measurements/auto_save/YYYY-MM-DD/
        """
        auto_save_base = self.create_auto_save_directory()
        date_str = datetime.now().strftime("%Y-%m-%d")
        date_dir = Path(auto_save_base) / date_str
        if not date_dir.exists():
            date_dir.mkdir(parents=True, exist_ok=True)
        return str(date_dir)

    def save_measurement_bundle(self, data: MeasurementData, measure_mode: str,
                                 include_ti3: bool = True) -> Dict:
        """
        保存完整的测量数据包（JSON + TI3）

        Args:
            data: MeasurementData 对象
            measure_mode: 测量类型 ('gamut', 'gamma', 'lut', 'dispcal')
            include_ti3: 是否导出 TI3 文件

        Returns:
            Dict: 包含保存文件路径的字典
                {
                    "success": True/False,
                    "date_dir": "日期目录路径",
                    "json_path": "JSON文件路径",
                    "ti3_path": "TI3文件路径" (如果 include_ti3=True)
                }
        """
        try:
            # 获取日期目录
            date_dir = self.get_auto_save_date_dir()

            # 生成文件名前缀（使用毫秒后缀避免同秒覆盖）
            timestamp = datetime.now()
            time_str = timestamp.strftime("%H%M%S")
            millis = timestamp.microsecond // 1000
            file_prefix = f"{time_str}-{millis:03d}-{measure_mode}"

            # 1. 保存 JSON 文件
            json_filename = f"{file_prefix}.json"
            json_path = Path(date_dir) / json_filename

            # 在保存前更新 measure_mode（确保 metadata 中有正确的模式）
            data.set_measure_mode(measure_mode)

            with open(json_path, 'w', encoding='utf-8') as f:
                f.write(data.to_json())

            result = {
                "success": True,
                "date_dir": str(date_dir),
                "json_path": str(json_path),
                "measure_mode": measure_mode
            }

            # 2. 导出 TI3 文件
            if include_ti3:
                ti3_filename = f"{file_prefix}.ti3"
                ti3_path = Path(date_dir) / ti3_filename

                exporter = CGATSExporter()
                if exporter.export_ti3(data, str(ti3_path)):
                    result["ti3_path"] = str(ti3_path)
                else:
                    result["ti3_path"] = None

            # 3. 更新 latest 符号链接
            self._update_latest_symlink(date_dir)

            print(f"自动保存完成: {date_dir}")
            return result

        except Exception as e:
            print(f"自动保存失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _update_latest_symlink(self, date_dir: str) -> bool:
        """
        更新 latest 符号链接到最新日期目录（仅 Unix-like 系统）

        Args:
            date_dir: 当前日期目录路径

        Returns:
            bool: 是否成功更新
        """
        import platform
        if platform.system() == "Windows":
            # Windows 不支持符号链接，跳过
            return False

        try:
            auto_save_base = Path(date_dir).parent
            latest_link = auto_save_base / "latest"

            # 删除旧的符号链接
            if latest_link.exists() or latest_link.is_symlink():
                latest_link.unlink()

            # 创建新的符号链接
            latest_link.symlink_to(date_dir)
            print(f"更新 latest 符号链接: {latest_link} -> {date_dir}")
            return True
        except Exception as e:
            print(f"更新符号链接失败: {e}")
            return False

    def copy_cal_file_to_auto_save(self, cal_source_path: str, measure_mode: str) -> Optional[str]:
        """
        复制 .cal 文件到自动保存目录（使用毫秒后缀避免覆盖）

        Args:
            cal_source_path: 源 .cal 文件路径
            measure_mode: 测量类型

        Returns:
            str: 复制后的文件路径，失败返回 None
        """
        try:
            import shutil

            date_dir = self.get_auto_save_date_dir()
            timestamp = datetime.now()
            time_str = timestamp.strftime("%H%M%S")
            millis = timestamp.microsecond // 1000
            cal_filename = f"{time_str}-{millis:03d}-{measure_mode}.cal"
            cal_dest = Path(date_dir) / cal_filename

            shutil.copy2(cal_source_path, cal_dest)
            print(f"CAL 文件已复制到自动保存目录: {cal_dest}")
            return str(cal_dest)
        except Exception as e:
            print(f"复制 CAL 文件失败: {e}")
            return None

    def get_saved_calibration_list(self) -> list:
        """
        获取自动保存目录中的所有校准数据列表

        Returns:
            list: 校准数据列表，每个元素包含:
                - name: 显示名称 (日期 时间)
                - date_dir: 日期目录 (YYYY-MM-DD)
                - time_str: 时间戳 (HHMMSS)
                - cal_path: .cal 文件完整路径
                - ti3_path: .ti3 文件完整路径
                - json_path: .json 文件完整路径
                - timestamp: Unix 时间戳用于排序
        """
        import os

        calibration_list = []

        try:
            auto_save_base = self.base_path / "auto_save"
            if not auto_save_base.exists():
                return calibration_list

            # 遍历所有日期目录
            for date_dir in sorted(auto_save_base.iterdir(), reverse=True):
                if not date_dir.is_dir() or date_dir.name == "latest":
                    continue

                # 验证日期格式 (YYYY-MM-DD)
                if not self._is_valid_date_format(date_dir.name):
                    continue

                # 查找该目录下的所有 dispcal 相关文件
                date_path = auto_save_base / date_dir.name

                # 按 HHMMSS_dispcal.* 或 HHMMSS-mmm-dispcal.* 格式查找文件
                calibrations = {}
                for file in date_path.iterdir():
                    if file.is_file():
                        # 匹配 HHMMSS_dispcal.ext (旧格式) 或 HHMMSS-mmm-dispcal.ext (新格式)
                        name = file.stem
                        ext = file.suffix

                        if name.endswith("_dispcal"):
                            time_str = name.replace("_dispcal", "")
                            # 验证时间格式 (HHMMSS)
                            if self._is_valid_time_format(time_str):
                                if time_str not in calibrations:
                                    calibrations[time_str] = {
                                        "date_dir": date_dir.name,
                                        "time_str": time_str,
                                        "cal_path": None,
                                        "ti3_path": None,
                                        "json_path": None
                                    }

                                if ext == ".cal":
                                    calibrations[time_str]["cal_path"] = str(file)
                                elif ext == ".ti3":
                                    calibrations[time_str]["ti3_path"] = str(file)
                                elif ext == ".json":
                                    calibrations[time_str]["json_path"] = str(file)
                        elif name.endswith("-dispcal"):
                            # 新格式：HHMMSS-mmm-dispcal
                            parts = name.rsplit("-dispcal", 1)
                            if len(parts) == 1:
                                time_millis = parts[0]
                                time_str = time_millis.split("-")[0]
                                # 验证时间格式 (HHMMSS)
                                if self._is_valid_time_format(time_str):
                                    if time_str not in calibrations:
                                        calibrations[time_str] = {
                                            "date_dir": date_dir.name,
                                            "time_str": time_str,
                                            "cal_path": None,
                                            "ti3_path": None,
                                            "json_path": None
                                        }

                                    if ext == ".cal":
                                        calibrations[time_str]["cal_path"] = str(file)
                                    elif ext == ".ti3":
                                        calibrations[time_str]["ti3_path"] = str(file)
                                    elif ext == ".json":
                                        calibrations[time_str]["json_path"] = str(file)

                # 转换为列表格式，只包含有 .cal 文件的记录
                for time_str, cal_data in calibrations.items():
                    if cal_data["cal_path"]:  # 必须有 .cal 文件
                        # 生成时间戳用于排序
                        try:
                            from datetime import datetime
                            dt = datetime.strptime(
                                f"{cal_data['date_dir']} {cal_data['time_str'][:2]}:{cal_data['time_str'][2:4]}:{cal_data['time_str'][4:]}",
                                "%Y-%m-%d %H:%M:%S"
                            )
                            timestamp = dt.timestamp()
                        except:
                            timestamp = 0

                        # 生成显示名称
                        display_time = f"{cal_data['time_str'][:2]}:{cal_data['time_str'][2:4]}:{cal_data['time_str'][4:]}"
                        display_name = f"{cal_data['date_dir']} {display_time}"

                        calibration_list.append({
                            "name": display_name,
                            "date_dir": cal_data["date_dir"],
                            "time_str": cal_data["time_str"],
                            "cal_path": cal_data["cal_path"],
                            "ti3_path": cal_data["ti3_path"],
                            "json_path": cal_data["json_path"],
                            "timestamp": timestamp
                        })

            # 按时间戳降序排序（最新的在前）
            calibration_list.sort(key=lambda x: x["timestamp"], reverse=True)

        except Exception as e:
            print(f"获取校准数据列表失败: {e}")

        return calibration_list

    def _is_valid_date_format(self, date_str: str) -> bool:
        """验证日期格式是否为 YYYY-MM-DD"""
        try:
            from datetime import datetime
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except:
            return False

    def _is_valid_time_format(self, time_str: str) -> bool:
        """验证时间格式是否为 HHMMSS（6位数字）"""
        if len(time_str) != 6 or not time_str.isdigit():
            return False
        try:
            from datetime import datetime
            datetime.strptime(time_str, "%H%M%S")
            return True
        except:
            return False

    def get_latest_calibration(self) -> dict:
        """
        获取最新的校准数据

        Returns:
            dict: 最新的校准数据，如果没有则返回 None
        """
        calibrations = self.get_saved_calibration_list()
        return calibrations[0] if calibrations else None

    def get_all_saved_measurements(self) -> list:
        """
        获取自动保存目录中的所有测量数据列表（包括 ICC、LUT、gamut、gamma 等所有模式）

        与 get_saved_calibration_list() 不同，此方法返回所有测量模式的数据，
        不仅仅限于 dispcal 模式。

        Returns:
            list: 测量数据列表，每个元素包含:
                - name: 显示名称 (日期 时间 模式)
                - date_dir: 日期目录 (YYYY-MM-DD)
                - time_str: 时间戳 (HHMMSS)
                - measure_mode: 测量模式 (icc, lut, gamut, gamma, dispcal 等)
                - cal_path: .cal 文件完整路径 (如果有)
                - ti3_path: .ti3 文件完整路径 (如果有)
                - json_path: .json 文件完整路径
                - timestamp: Unix 时间戳用于排序
        """
        import os

        measurement_list = []

        try:
            auto_save_base = self.base_path / "auto_save"
            if not auto_save_base.exists():
                return measurement_list

            # 支持的测量模式
            measure_modes = ['icc', 'lut', 'gamut', 'gamma', 'dispcal', 'custom', 'ccmx']

            # 遍历所有日期目录
            for date_dir in sorted(auto_save_base.iterdir(), reverse=True):
                if not date_dir.is_dir() or date_dir.name == "latest":
                    continue

                # 验证日期格式 (YYYY-MM-DD)
                if not self._is_valid_date_format(date_dir.name):
                    continue

                date_path = auto_save_base / date_dir.name

                # 按模式分组文件（支持新旧两种格式）
                measurements = {}
                for file in date_path.iterdir():
                    if file.is_file():
                        name = file.stem
                        ext = file.suffix

                        # 匹配 HHMMSS_mode.ext (旧格式) 或 HHMMSS-mmm-mode.ext (新格式)
                        for mode in measure_modes:
                            matched = False
                            time_str = None

                            # 旧格式：HHMMSS_mode
                            suffix_old = f"_{mode}"
                            if name.endswith(suffix_old):
                                time_str = name.replace(suffix_old, "")
                                matched = True
                            # 新格式：HHMMSS-mmm-mode
                            # 注意：需要从右向左匹配，因为文件名包含连字符
                            elif name.endswith(f"-{mode}"):
                                # 分割出时间部分和毫秒部分
                                # 例如: 001856-295-icc -> 001856-295
                                without_mode = name[:-len(f"-{mode}")]
                                # 再分割出时间部分
                                # 例如: 001856-295 -> 001856
                                if "-" in without_mode:
                                    time_str = without_mode.split("-")[0]
                                else:
                                    time_str = without_mode
                                matched = True

                            if matched and time_str:
                                # 验证时间格式 (HHMMSS)
                                if self._is_valid_time_format(time_str):
                                    key = f"{time_str}_{mode}"
                                    if key not in measurements:
                                        measurements[key] = {
                                            "date_dir": date_dir.name,
                                            "time_str": time_str,
                                            "measure_mode": mode,
                                            "cal_path": None,
                                            "ti3_path": None,
                                            "json_path": None
                                        }

                                    if ext == ".cal":
                                        measurements[key]["cal_path"] = str(file)
                                    elif ext == ".ti3":
                                        measurements[key]["ti3_path"] = str(file)
                                    elif ext == ".json":
                                        measurements[key]["json_path"] = str(file)
                                break

                # 转换为列表格式，只要有 .json 或 .ti3 文件即可
                for key, meas_data in measurements.items():
                    if meas_data["json_path"] or meas_data["ti3_path"]:
                        # 生成时间戳用于排序
                        try:
                            from datetime import datetime
                            dt = datetime.strptime(
                                f"{meas_data['date_dir']} {meas_data['time_str'][:2]}:{meas_data['time_str'][2:4]}:{meas_data['time_str'][4:]}",
                                "%Y-%m-%d %H:%M:%S"
                            )
                            timestamp = dt.timestamp()
                        except:
                            timestamp = 0

                        # 生成显示名称
                        display_time = f"{meas_data['time_str'][:2]}:{meas_data['time_str'][2:4]}:{meas_data['time_str'][4:]}"
                        mode_display = meas_data['measure_mode'].upper()
                        display_name = f"{meas_data['date_dir']} {display_time} ({mode_display})"

                        measurement_list.append({
                            "name": display_name,
                            "date_dir": meas_data["date_dir"],
                            "time_str": meas_data["time_str"],
                            "measure_mode": meas_data["measure_mode"],
                            "cal_path": meas_data["cal_path"],
                            "ti3_path": meas_data["ti3_path"],
                            "json_path": meas_data["json_path"],
                            "timestamp": timestamp
                        })

            # 按时间戳降序排序（最新的在前）
            measurement_list.sort(key=lambda x: x["timestamp"], reverse=True)

        except Exception as e:
            print(f"获取测量数据列表失败: {e}")

        return measurement_list


class SessionStorage:
    """
    会话存储管理类
    负责会话数据的保存、加载和管理
    """

    def __init__(self, base_path: str = None):
        """
        初始化会话存储

        Args:
            base_path: 存储根目录，默认为项目目录下的 'measurements' 文件夹
        """
        if base_path:
            self.base_path = Path(base_path)
        else:
            project_root = Path(__file__).parent.parent
            self.base_path = project_root / "measurements"

        self.sessions_path = self.base_path / "sessions"
        self.auto_save_path = self.base_path / "auto_save"

        # 确保目录存在
        self.sessions_path.mkdir(parents=True, exist_ok=True)
        self.auto_save_path.mkdir(parents=True, exist_ok=True)

    def create_session(self, measure_mode: str = "") -> SessionData:
        """
        创建新会话

        Args:
            measure_mode: 测量模式

        Returns:
            SessionData: 新创建的会话对象
        """
        return SessionData(measure_mode)

    def save_session(self, session: SessionData, measurement: MeasurementData,
                     is_auto_save: bool = False) -> Dict:
        """
        保存会话数据

        Args:
            session: 会话对象
            measurement: 测量数据对象
            is_auto_save: 是否为自动保存（使用不同目录结构）

        Returns:
            Dict: 保存结果，包含 session_id 和路径
        """
        try:
            if is_auto_save:
                # 使用毫秒后缀避免覆盖
                timestamp = datetime.now()
                time_str = timestamp.strftime("%H%M%S")
                millis = timestamp.microsecond // 1000
                dir_name = f"{time_str}-{millis:03d}-{session.measure_mode}"
                date_str = timestamp.strftime("%Y-%m-%d")
                session_dir = self.auto_save_path / date_str / dir_name
            else:
                session_dir = self.sessions_path / session.session_id

            session_dir.mkdir(parents=True, exist_ok=True)

            # 更新会话时间
            session.updated_at = datetime.now().isoformat()

            # 保存 session.json
            with open(session_dir / "session.json", "w", encoding="utf-8") as f:
                f.write(session.to_json())

            # 保存 measurement.json
            with open(session_dir / "measurement.json", "w", encoding="utf-8") as f:
                f.write(measurement.to_json())

            # 导出 TI3（如果需要）
            if session.measure_mode in ['icc', 'lut', 'custom', 'ccmx']:
                ti3_path = session_dir / "profile.ti3"
                exporter = CGATSExporter()
                if exporter.export_ti3(measurement, str(ti3_path)):
                    session.add_file("ti3", "profile.ti3")

            # 复制 cal 文件（如果存在）
            cal_source = self._find_cal_file(measurement)
            if cal_source:
                import shutil
                cal_dest = session_dir / "calibration.cal"
                shutil.copy2(cal_source, cal_dest)
                session.add_file("calibration", "calibration.cal")

            return {
                "success": True,
                "session_id": session.session_id,
                "path": str(session_dir),
                "is_auto_save": is_auto_save
            }

        except Exception as e:
            print(f"保存会话失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _find_cal_file(self, measurement: MeasurementData) -> Optional[Path]:
        """查找与测量数据关联的 cal 文件"""
        # 在 auto_save 目录中查找同时间的 cal 文件
        measure_id = measurement.metadata.get("measurement_id", "")
        if not measure_id:
            return None

        # 尝试匹配时间戳
        for cal_file in self.auto_save_path.rglob("*.cal"):
            if measure_id[:14] in cal_file.name:  # 匹配时间戳部分
                return cal_file

        return None

    def load_session(self, session_id: str) -> Optional[Tuple[SessionData, MeasurementData]]:
        """
        加载会话数据

        Args:
            session_id: 会话ID（完整ID或目录名）

        Returns:
            Tuple[SessionData, MeasurementData]: 会话和测量数据，失败返回None
        """
        session_dir = None

        # 先尝试 sessions/ 目录
        potential_path = self.sessions_path / session_id
        if potential_path.exists() and potential_path.is_dir():
            session_dir = potential_path
        else:
            # 再尝试 auto_save/ 目录
            for date_dir in self.auto_save_path.iterdir():
                if date_dir.is_dir():
                    potential_path = date_dir / session_id
                    if potential_path.exists() and potential_path.is_dir():
                        session_dir = potential_path
                        break

        if not session_dir:
            print(f"会话目录不存在: {session_id}")
            return None

        try:
            # 读取 session.json
            session_file = session_dir / "session.json"
            if not session_file.exists():
                # 兼容旧格式：没有 session.json 的目录
                session = SessionData()
                session.session_id = session_id
                # 从目录名推断模式
                parts = session_id.split("-")
                if len(parts) >= 3:
                    session.measure_mode = parts[-1]
            else:
                with open(session_file, "r", encoding="utf-8") as f:
                    session = SessionData()
                    session.from_json(f.read())

            # 读取 measurement.json
            measurement_file = session_dir / "measurement.json"
            if not measurement_file.exists():
                print(f"测量数据文件不存在: {measurement_file}")
                return None

            with open(measurement_file, "r", encoding="utf-8") as f:
                measurement = MeasurementData()
                measurement.from_json(f.read())

            return session, measurement

        except Exception as e:
            print(f"加载会话失败: {e}")
            return None

    def list_sessions(self, include_auto_save: bool = True) -> List[Dict]:
        """
        列出所有会话

        Args:
            include_auto_save: 是否包含自动保存的会话

        Returns:
            List[Dict]: 会话列表，每项包含会话摘要信息
        """
        sessions = []

        # 扫描 sessions/ 目录
        for session_dir in self.sessions_path.iterdir():
            if session_dir.is_dir():
                session = self._load_session_summary(session_dir)
                if session:
                    session["storage_type"] = "sessions"
                    sessions.append(session)

        # 扫描 auto_save/ 目录
        if include_auto_save:
            for date_dir in self.auto_save_path.iterdir():
                if date_dir.is_dir() and date_dir.name != "latest":
                    for session_dir in date_dir.iterdir():
                        if session_dir.is_dir():
                            session = self._load_session_summary(session_dir)
                            if session:
                                session["storage_type"] = "auto_save"
                                sessions.append(session)

        # 按创建时间排序（最新的在前）
        sessions.sort(key=lambda x: x["created_at"], reverse=True)
        return sessions

    def _load_session_summary(self, session_dir: Path) -> Optional[Dict]:
        """加载会话摘要信息"""
        session_file = session_dir / "session.json"

        # 如果有 session.json，从中读取
        if session_file.exists():
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                return {
                    "session_id": data["session_id"],
                    "created_at": data["created_at"],
                    "measure_mode": data["measure_mode"],
                    "display_name": data.get("display_name", ""),
                    "status": data["status"],
                    "path": str(session_dir)
                }
            except Exception as e:
                print(f"读取会话摘要失败 {session_dir}: {e}")

        # 兼容旧格式：没有 session.json 的目录
        # 尝试从目录名解析信息
        dir_name = session_dir.name
        measurement_file = session_dir / "measurement.json"

        if measurement_file.exists():
            try:
                with open(measurement_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                metadata = data.get("metadata", {})

                # 解析目录名获取时间戳
                # 新格式：HHMMSS-mmm-mode 或 YYYYMMDD-HHMMSS-XXXXXX
                time_str = dir_name.split("-")[0] if "-" in dir_name else dir_name[:6]

                return {
                    "session_id": dir_name,
                    "created_at": metadata.get("timestamp", ""),
                    "measure_mode": metadata.get("measure_mode", ""),
                    "display_name": metadata.get("display_name", ""),
                    "status": "completed",
                    "path": str(session_dir)
                }
            except Exception as e:
                print(f"读取旧格式会话摘要失败 {session_dir}: {e}")

        return None

    def delete_session(self, session_id: str) -> bool:
        """
        删除会话（整个目录）

        Args:
            session_id: 会话ID

        Returns:
            bool: 是否成功删除
        """
        import shutil

        session_dir = self.sessions_path / session_id
        if session_dir.exists():
            try:
                shutil.rmtree(session_dir)
                print(f"已删除会话: {session_id}")
                return True
            except Exception as e:
                print(f"删除会话失败: {e}")
                return False

        # 也尝试从 auto_save 中删除
        for date_dir in self.auto_save_path.iterdir():
            if date_dir.is_dir():
                session_dir = date_dir / session_id
                if session_dir.exists():
                    try:
                        shutil.rmtree(session_dir)
                        print(f"已删除自动保存会话: {session_id}")
                        return True
                    except Exception as e:
                        print(f"删除会话失败: {e}")
                        return False

        return False

    def archive_session(self, session_id: str) -> bool:
        """
        归档会话到 archive 目录

        Args:
            session_id: 会话ID

        Returns:
            bool: 是否成功归档
        """
        import shutil

        session_dir = self.sessions_path / session_id
        if not session_dir.exists():
            return False

        # 创建归档目录
        archive_base = self.base_path / "archive"
        archive_base.mkdir(parents=True, exist_ok=True)

        # 按年月归档
        date_str = session_id[:8]  # YYYYMMDD
        try:
            dt = datetime.strptime(date_str, "%Y%m%d")
            archive_dir = archive_base / dt.strftime("%Y-%m")
        except:
            archive_dir = archive_base / "unknown"

        archive_dir.mkdir(parents=True, exist_ok=True)

        # 移动会话目录
        dest_path = archive_dir / session_id
        try:
            shutil.move(str(session_dir), str(dest_path))
            print(f"已归档会话: {session_id} -> {dest_path}")
            return True
        except Exception as e:
            print(f"归档会话失败: {e}")
            return False


class CGATSExporter:
    """
    CGATS/TI3 格式导出器
    将测量数据导出为行业标准格式
    """

    # CGATS 标准字段定义
    CGATS_FIELDS = [
        "SAMPLE_ID",
        "RGB_R",
        "RGB_G",
        "RGB_B",
        "XYZ_X",
        "XYZ_Y",
        "XYZ_Z"
    ]

    def __init__(self):
        pass

    def export_ti3(self, data: MeasurementData, filepath: str) -> bool:
        """
        导出为 .ti3 格式（ArgyllCMS 兼容格式）

        Args:
            data: MeasurementData 对象
            filepath: 导出文件路径

        Returns:
            bool: 是否成功导出
        """
        try:
            content = self._generate_ti3_content(data)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            print(f"TI3文件已导出: {filepath}")
            return True
        except Exception as e:
            print(f"导出TI3失败: {e}")
            return False

    def _generate_ti3_content(self, data: MeasurementData) -> str:
        """生成TI3文件内容"""
        lines = []

        # 文件头 - CTI3 格式（colprof 要求）
        lines.append("CTI3")
        lines.append("")
        lines.append("ORIGINATOR \"Topos Calibrator\"")

        # ccxxmake 必须的硬件基准声明（必须大写、双引号）
        probe_name = data.metadata.get("probe", "i1d3")
        lines.append(f"TARGET_INSTRUMENT \"{probe_name}\"")

        # 显示技术类型：l=LCD, o=OLED, c=CRT, p=投影仪
        display_type = data.metadata.get("display_type", "l")
        lines.append(f"DISPLAY_TYPE_REF \"{display_type}\"")

        # ArgyllCMS 强制要求的 CGATS 规范声明
        lines.append("DEVICE_CLASS \"DISPLAY\"")
        lines.append("COLOR_REP \"RGB_XYZ\"")

        # ArgyllCMS 只认 INSTRUMENT_TYPE_SPECTRAL 标签（YES=分光仪, NO=色度计）
        spectral_probes = ["i1pro", "i1pro2", "i1pro3", "colormunki", "colormunki_smile",
                          "specbos", "spectraval", "spectro", "spectroscan"]
        is_spectral = probe_name.lower() in spectral_probes
        lines.append(f"INSTRUMENT_TYPE_SPECTRAL \"{'YES' if is_spectral else 'NO'}\"")

        # 显示器类型基准ID（ccxxmake 强制要求）
        lines.append("DISPLAY_TYPE_BASE_ID \"1\"")

        lines.append("")

        # 设备信息
        lines.append("# Device Information")
        lines.append("# Probe: " + data.metadata.get("probe", "Unknown"))
        lines.append("# Display: " + data.metadata.get("display_type", "Unknown"))
        lines.append("")

        # 数据格式声明
        lines.append("NUMBER_OF_FIELDS 7")
        lines.append("BEGIN_DATA_FORMAT")
        lines.append("SAMPLE_ID RGB_R RGB_G RGB_B XYZ_X XYZ_Y XYZ_Z")
        lines.append("END_DATA_FORMAT")
        lines.append("")

        # 计算数据行数
        sample_count = self._count_samples(data)
        lines.append(f"NUMBER_OF_SETS {sample_count}")
        lines.append("")

        # 数据内容
        lines.append("BEGIN_DATA")

        sample_id = 1

        # 色域测量数据
        gamut = data.measurements.get("gamut", {})
        color_order = ["red", "green", "blue", "white", "black"]

        for color_key in color_order:
            if color_key in gamut and gamut[color_key].get("xyY"):
                color_data = gamut[color_key]
                rgb = color_data.get("RGB", [0, 0, 0])
                xyY = color_data.get("xyY", [0, 0, 0])

                # 转换 xyY 到 XYZ
                X, Y, Z = self._xyY_to_XYZ(xyY[0], xyY[1], xyY[2])

                # 格式化数据行 - RGB 需转换为百分比 (0-100)
                rgb_pct = [rgb[0] / 255.0 * 100.0, rgb[1] / 255.0 * 100.0, rgb[2] / 255.0 * 100.0]
                line = f"{sample_id} {rgb_pct[0]:.4f} {rgb_pct[1]:.4f} {rgb_pct[2]:.4f} {X:.4f} {Y:.4f} {Z:.4f}"
                lines.append(line)
                sample_id += 1

        # Gamma/灰阶测量数据
        gamma = data.measurements.get("gamma", [])
        for gamma_point in gamma:
            rgb = gamma_point.get("RGB", [128, 128, 128])
            Y = gamma_point.get("Y", 0)
            input_level = gamma_point.get("input", 50)

            # 对于灰阶，假设 x,y 为 D65 白点
            x, y = 0.3127, 0.3290
            X, Y_val, Z = self._xyY_to_XYZ(x, y, Y)

            # 格式化数据行 - RGB 需转换为百分比 (0-100)
            rgb_pct = [rgb[0] / 255.0 * 100.0, rgb[1] / 255.0 * 100.0, rgb[2] / 255.0 * 100.0]
            line = f"{sample_id} {rgb_pct[0]:.4f} {rgb_pct[1]:.4f} {rgb_pct[2]:.4f} {X:.4f} {Y_val:.4f} {Z:.4f}"
            lines.append(line)
            sample_id += 1

        # ========== LUT 色块测量数据 ==========
        # 对于 LUT 工作流，导出 ti1 生成的色块测量结果
        lut_patches = data.measurements.get("lut_patches", [])
        if lut_patches:
            for lut_point in lut_patches:
                rgb = lut_point.get("RGB", [0, 0, 0])
                xyY = lut_point.get("xyY", [0.3127, 0.3290, 0])

                # 转换 xyY 到 XYZ
                X, Y_val, Z = self._xyY_to_XYZ(xyY[0], xyY[1], xyY[2])

                # 格式化数据行 - RGB 需转换为百分比 (0-100)
                rgb_pct = [rgb[0] / 255.0 * 100.0, rgb[1] / 255.0 * 100.0, rgb[2] / 255.0 * 100.0]
                line = f"{sample_id} {rgb_pct[0]:.4f} {rgb_pct[1]:.4f} {rgb_pct[2]:.4f} {X:.4f} {Y_val:.4f} {Z:.4f}"
                lines.append(line)
                sample_id += 1

        lines.append("END_DATA")
        lines.append("")

        return "\n".join(lines)

    def _xyY_to_XYZ(self, x: float, y: float, Y: float) -> Tuple[float, float, float]:
        """
        将 CIE xyY 转换为 XYZ

        生产级加固：添加浮点数容差检查，防止极小 y 值导致的浮点溢出。

        Args:
            x: CIE x 坐标
            y: CIE y 坐标
            Y: 亮度值

        Returns:
            Tuple: (X, Y, Z)
        """
        # ========== 生产级加固：浮点数容差检查 ==========
        # 当 y 是极小浮点数（如 1e-8）时，除法会导致数值爆炸。
        # 使用 epsilon 容差：当 y < epsilon 时，按黑色处理。
        # 典型探头底噪约为 0.001-0.0001，设置 epsilon = 1e-6
        EPSILON = 1e-6

        if abs(y) < EPSILON:
            # y 值过小，按黑色处理（X=0, Z=0）
            # 注意：即使 Y != 0（如极暗色块），也应返回 (0, Y, 0)
            # 因为此时 x/y 的计算会导致数值溢出或不稳定
            return (0.0, Y, 0.0)

        # 正常计算
        X = (x * Y) / y
        Z = ((1.0 - x - y) * Y) / y

        # ========== 额外安全检查：防止 NaN/Inf ==========
        # 如果计算结果出现异常值，返回安全值
        if not (abs(X) < 1e10):  # X 值过大
            X = 0.0
        if not (abs(Z) < 1e10):  # Z 值过大
            Z = 0.0

        return (X, Y, Z)

    def _count_samples(self, data: MeasurementData) -> int:
        """计算样本数量"""
        count = 0

        # 色域测量
        gamut = data.measurements.get("gamut", {})
        for color_key in ["red", "green", "blue", "white", "black"]:
            if color_key in gamut and gamut[color_key].get("xyY"):
                count += 1

        # Gamma测量
        gamma = data.measurements.get("gamma", [])
        count += len(gamma)

        # LUT 色块测量
        lut_patches = data.measurements.get("lut_patches", [])
        count += len(lut_patches)

        return count

    def export_cgats(self, data: MeasurementData, filepath: str) -> bool:
        """
        导出为标准 CGATS 格式

        Args:
            data: MeasurementData 对象
            filepath: 导出文件路径

        Returns:
            bool: 是否成功导出
        """
        # CGATS格式与TI3类似，但更通用
        return self.export_ti3(data, filepath)


# ========== ICC Profile 相关存储功能 (P4-B) ==========

class ICCSessionStorage:
    """
    ICC Profile 会话存储管理类

    提供 ICC 工作流相关的数据存储功能：
    - ICC 会话数据保存和加载
    - ICC Profile 文件管理
    - 验证测量数据存储
    - Manifest 生成和更新

    Reference: docs/agent_handoffs/P4-B_icc_workflow.md
    """

    def __init__(self, base_path: str = None):
        """
        初始化 ICC 会话存储

        Args:
            base_path: 存储根目录，默认为 measurements/sessions
        """
        if base_path:
            self.base_path = Path(base_path)
        else:
            project_root = Path(__file__).parent.parent
            self.base_path = project_root / "measurements" / "sessions"

        # 确保目录存在
        self.base_path.mkdir(parents=True, exist_ok=True)

    def create_icc_session_dir(self, session_id: str) -> Path:
        """
        创建 ICC 会话目录

        Args:
            session_id: 会话 ID

        Returns:
            Path: 会话目录路径
        """
        session_dir = self.base_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def save_icc_session_data(self, session_dir: Path, session_data: Dict) -> bool:
        """
        保存 ICC 会话数据

        Args:
            session_dir: 会话目录
            session_data: 会话数据字典

        Returns:
            bool: 是否成功
        """
        try:
            session_file = session_dir / "icc_session.json"
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"保存 ICC 会话数据失败: {e}")
            return False

    def load_icc_session_data(self, session_dir: Path) -> Optional[Dict]:
        """
        加载 ICC 会话数据

        Args:
            session_dir: 会话目录

        Returns:
            Dict: 会话数据，失败返回 None
        """
        session_file = session_dir / "icc_session.json"
        if not session_file.exists():
            return None

        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"加载 ICC 会话数据失败: {e}")
            return None

    def save_verification_data(self, session_dir: Path, verification_data: Dict) -> bool:
        """
        保存验证测量数据

        Args:
            session_dir: 会话目录
            verification_data: 验证测量数据

        Returns:
            bool: 是否成功
        """
        try:
            verify_file = session_dir / "verification.json"
            with open(verify_file, 'w', encoding='utf-8') as f:
                json.dump(verification_data, f, indent=2, ensure_ascii=False)

            # 同时导出 TI3 格式
            ti3_content = self._generate_verification_ti3(verification_data)
            ti3_file = session_dir / "verification.ti3"
            with open(ti3_file, 'w', encoding='utf-8') as f:
                f.write(ti3_content)

            return True
        except Exception as e:
            print(f"保存验证数据失败: {e}")
            return False

    def load_verification_data(self, session_dir: Path) -> Optional[Dict]:
        """
        加载验证测量数据

        Args:
            session_dir: 会话目录

        Returns:
            Dict: 验证数据，失败返回 None
        """
        verify_file = session_dir / "verification.json"
        if not verify_file.exists():
            return None

        try:
            with open(verify_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"加载验证数据失败: {e}")
            return None

    def _generate_verification_ti3(self, verification_data: Dict) -> str:
        """
        生成验证数据 TI3 文件内容

        Args:
            verification_data: 验证测量数据

        Returns:
            str: TI3 文件内容
        """
        measurements = verification_data.get("measurements", [])

        lines = [
            "CTI3",
            "",
            "ORIGINATOR \"Topos Calibrator Verification\"",
            "DEVICE_CLASS \"DISPLAY\"",
            "COLOR_REP \"RGB_XYZ\"",
            "",
            "NUMBER_OF_FIELDS 7",
            "BEGIN_DATA_FORMAT",
            "SAMPLE_ID RGB_R RGB_G RGB_B XYZ_X XYZ_Y XYZ_Z",
            "END_DATA_FORMAT",
            "",
            f"NUMBER_OF_SETS {len(measurements)}",
            "",
            "BEGIN_DATA",
        ]

        for i, m in enumerate(measurements):
            sample_id = m.get("sample_id", i + 1)
            rgb = m.get("RGB", [0, 0, 0])
            xyY = m.get("xyY", [0.3127, 0.3290, 0])

            # 转换 xyY 到 XYZ
            x, y, Y = xyY[0], xyY[1], xyY[2]
            if y > 0:
                X = x * Y / y
                Z = (1 - x - y) * Y / y
            else:
                X, Z = 0, 0

            # RGB 转换为百分比
            rgb_pct = [rgb[0] / 255.0 * 100.0, rgb[1] / 255.0 * 100.0, rgb[2] / 255.0 * 100.0]
            lines.append(f"{sample_id} {rgb_pct[0]:.4f} {rgb_pct[1]:.4f} {rgb_pct[2]:.4f} {X:.4f} {Y:.4f} {Z:.4f}")

        lines.extend([
            "END_DATA",
            "",
        ])

        return "\n".join(lines)

    def list_icc_sessions(self) -> List[Dict]:
        """
        列出所有 ICC 会话

        Returns:
            List[Dict]: ICC 会话列表
        """
        sessions = []

        for session_dir in self.base_path.iterdir():
            if session_dir.is_dir() and session_dir.name.startswith("icc-"):
                session_data = self.load_icc_session_data(session_dir)
                if session_data:
                    sessions.append({
                        "session_id": session_data.get("session_id", session_dir.name),
                        "state": session_data.get("state", "unknown"),
                        "preset": session_data.get("config", {}).get("preset", "general"),
                        "created_at": session_data.get("started_at", ""),
                        "icc_file": session_data.get("icc_file"),
                        "session_dir": str(session_dir),
                    })

        # 按创建时间排序
        sessions.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return sessions

    def get_icc_profile_path(self, session_id: str) -> Optional[Path]:
        """
        获取 ICC Profile 文件路径

        Args:
            session_id: 会话 ID

        Returns:
            Path: ICC 文件路径，不存在返回 None
        """
        session_dir = self.base_path / session_id
        if not session_dir.exists():
            return None

        # 查找 ICC 文件
        for icc_file in session_dir.glob("*.icc"):
            return icc_file

        return None

    def get_recoverable_sessions(self) -> List[Dict]:
        """
        获取可恢复的 ICC 会话

        查找有 checkpoint.json 的会话，可用于失败恢复。

        Returns:
            List[Dict]: 可恢复会话列表
        """
        recoverable = []

        for session_dir in self.base_path.iterdir():
            if session_dir.is_dir():
                checkpoint_file = session_dir / "checkpoint.json"
                if checkpoint_file.exists():
                    try:
                        with open(checkpoint_file, 'r', encoding='utf-8') as f:
                            checkpoint = json.load(f)

                        recoverable.append({
                            "session_id": checkpoint.get("session_id", session_dir.name),
                            "state": checkpoint.get("state", "unknown"),
                            "reason": checkpoint.get("reason", ""),
                            "created_at": checkpoint.get("created_at", ""),
                            "has_cal": checkpoint.get("cal_file_exists", False),
                            "has_ti3": checkpoint.get("ti3_file_exists", False),
                            "has_icc": checkpoint.get("icc_file_exists", False),
                            "session_dir": str(session_dir),
                        })
                    except Exception as e:
                        print(f"读取 checkpoint 失败: {e}")

        return recoverable

    def delete_icc_session(self, session_id: str) -> bool:
        """
        删除 ICC 会话目录

        Args:
            session_id: 会话 ID

        Returns:
            bool: 是否成功删除
        """
        import shutil

        session_dir = self.base_path / session_id
        if session_dir.exists():
            try:
                shutil.rmtree(session_dir)
                return True
            except Exception as e:
                print(f"删除 ICC 会话失败: {e}")
                return False

        return False


def get_icc_presets_info() -> Dict[str, Dict]:
    """
    获取 ICC Profile 预设信息

    Returns:
        Dict: 预设名称到配置信息的映射
    """
    return {
        "photography": {
            "description": "摄影工作流：高质量，包含VCGT，感知渲染意图",
            "quality": "h",
            "use_vcgt": True,
            "intent": "p",
            "recommended_patches": 2048,
        },
        "video": {
            "description": "视频工作流：高质量，无VCGT，相对色域映射",
            "quality": "h",
            "use_vcgt": False,
            "intent": "r",
            "recommended_patches": 2048,
        },
        "general": {
            "description": "通用工作流：平衡质量和速度",
            "quality": "m",
            "use_vcgt": True,
            "intent": "r",
            "recommended_patches": 1024,
        },
        "soft_proof": {
            "description": "软打样工作流：绝对色域映射，用于印刷校对",
            "quality": "h",
            "use_vcgt": False,
            "intent": "a",
            "recommended_patches": 2048,
        },
    }


def compute_file_sha256(filepath: str) -> str:
    """
    计算文件 SHA256 hash

    Args:
        filepath: 文件路径

    Returns:
        str: SHA256 hash 字符串
    """
    import hashlib

    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()

"""
MeasurementAnalyzer - 测量数据分析模块
计算色域覆盖率、Gamma值、Delta E、CCT/Duv等

更新说明 (P2-D):
- Delta E 计算现在支持白点适配 (Bradford/CAT02)
- CCT/Duv 使用 Robertson 等温线方法，更精确
- 灰阶报告支持 xy偏移、Duv、Delta E 组合
- 白点偏差报告增强：包含偏移方向描述

依赖模块：
- src/color_science/colorimetry.py - 白点适配、Delta E、CCT/Duv
- src/color_science/spaces.py - XYZ/Lab转换、白点定义
"""

import math
import warnings
from typing import Dict, List, Tuple, Optional

# 导入新的色彩科学模块（P2-A/P2-D 新增）
from .color_science.colorimetry import (
    chromatic_adaptation,
    adapt_to_white_point,
    delta_e_ciede2000,
    delta_e_from_xyY,
    xy_to_cct_mccamy,
    xy_to_cct_robertson,
    cct_duv_from_xy,
    calculate_duv,
    calculate_white_point_error,
    xy_to_uv_1976,
)
from .color_science.spaces import (
    xyz_to_lab,
    lab_to_xyz,
    xyY_to_xyz,
    get_white_point_xyz,
    get_white_point_xy,
    ILLUMINANTS,
    WHITE_POINTS,
)
# P2-B 新增：精确色域计算
from .color_science.gamut_sampling import (
    polygon_area,
    polygon_intersection_area,
    polygon_vertices_from_rgbw,
    gamut_coverage_percent,
    gamut_area_ratio,
    gamut_metrics,
)


# 标准色域的 CIE xy 坐标 - 影视制作常用色域预设
STANDARD_GAMUTS = {
    # === 基础色域 ===
    "sRGB": {
        "red": (0.64, 0.33),
        "green": (0.30, 0.60),
        "blue": (0.15, 0.06),
        "white": (0.3127, 0.3290),  # D65
        "category": "基础",
        "description": "sRGB (IEC 61966-2-1)"
    },
    "Rec.709": {
        "red": (0.64, 0.33),
        "green": (0.30, 0.60),
        "blue": (0.15, 0.06),
        "white": (0.3127, 0.3290),  # D65
        "category": "基础",
        "description": "Rec.709 (BT.709) - HD视频标准"
    },
    
    # === 宽色域 ===
    "DCI-P3": {
        "red": (0.68, 0.32),
        "green": (0.265, 0.69),
        "blue": (0.15, 0.06),
        "white": (0.314, 0.351),  # DCI白点 (~6300K)
        "category": "宽色域",
        "description": "DCI-P3 (SMPTE RP 431-2) - 数字影院"
    },
    "Display P3": {
        "red": (0.68, 0.32),
        "green": (0.265, 0.69),
        "blue": (0.15, 0.06),
        "white": (0.3127, 0.3290),  # D65
        "category": "宽色域",
        "description": "Display P3 - Apple/DCI-P3 D65版本"
    },
    "Adobe RGB": {
        "red": (0.64, 0.33),
        "green": (0.21, 0.71),
        "blue": (0.15, 0.06),
        "white": (0.3127, 0.3290),  # D65
        "category": "宽色域",
        "description": "Adobe RGB (1998)"
    },
    "Rec.2020": {
        "red": (0.708, 0.292),
        "green": (0.170, 0.797),
        "blue": (0.131, 0.046),
        "white": (0.3127, 0.3290),  # D65
        "category": "宽色域",
        "description": "Rec.2020 (BT.2020) - UHD/4K/8K"
    },
    
    # === 专业电影色域 ===
    "ProPhoto RGB": {
        "red": (0.7347, 0.2653),
        "green": (0.1596, 0.8404),
        "blue": (0.0366, 0.0001),
        "white": (0.3457, 0.3585),  # D50
        "category": "专业",
        "description": "ProPhoto RGB (ROMM) - 摄影宽色域"
    },
    "Cinema Gamut": {
        "red": (0.7347, 0.2653),
        "green": (0.1596, 0.8404),
        "blue": (0.0366, 0.0001),
        "white": (0.3127, 0.3290),  # D65
        "category": "专业",
        "description": "Cinema Gamut - Canon电影色域"
    },
    "ACES AP0": {
        "red": (0.7347, 0.2653),
        "green": (0.0000, 1.0000),
        "blue": (0.0001, -0.0770),
        "white": (0.32168, 0.33767),  # ACES白点
        "category": "专业",
        "description": "ACES AP0 - Academy色彩编码系统"
    },
    "ACES AP1": {
        "red": (0.713, 0.293),
        "green": (0.165, 0.830),
        "blue": (0.128, 0.044),
        "white": (0.32168, 0.33767),  # ACES白点
        "category": "专业",
        "description": "ACES AP1 (ACEScg) - ACES工作色域"
    },
    
    # === 品牌特定色域 ===
    "S-Gamut3": {
        "red": (0.730, 0.280),
        "green": (0.140, 0.850),
        "blue": (0.100, 0.050),
        "white": (0.3127, 0.3290),  # D65
        "category": "品牌",
        "description": "S-Gamut3 - Sony电影色域"
    },
    "S-Gamut3.Cine": {
        "red": (0.766, 0.274),
        "green": (0.150, 0.860),
        "blue": (0.094, 0.056),
        "white": (0.3127, 0.3290),  # D65
        "category": "品牌",
        "description": "S-Gamut3.Cine - Sony电影色域(优化版)"
    },
    "V-Gamut": {
        "red": (0.730, 0.280),
        "green": (0.165, 0.840),
        "blue": (0.100, 0.010),
        "white": (0.3127, 0.3290),  # D65
        "category": "品牌",
        "description": "V-Gamut - Panasonic VariCam"
    },
    "C-Gamut": {
        "red": (0.740, 0.270),
        "green": (0.170, 0.830),
        "blue": (0.100, 0.020),
        "white": (0.3127, 0.3290),  # D65
        "category": "品牌",
        "description": "C-Gamut - Canon Cinema EOS"
    },
    "RED Wide Gamut RGB": {
        "red": (0.780, 0.304),
        "green": (0.121, 0.873),
        "blue": (0.095, -0.084),
        "white": (0.3127, 0.3290),  # D65
        "category": "品牌",
        "description": "RED Wide Gamut RGB"
    }
}


class MeasurementAnalyzer:
    """
    测量数据分析器
    计算色域覆盖率、Gamma值等指标
    """

    def __init__(self):
        self.gamut_data: Dict = {}  # RGBW 测量数据
        self.gamma_data: List = []  # 灰阶测量数据

    def set_gamut_data(self, red: Dict, green: Dict, blue: Dict, white: Dict):
        """设置色域测量数据"""
        self.gamut_data = {
            "red": red,
            "green": green,
            "blue": blue,
            "white": white
        }

    def set_gamma_data(self, gray_scale: List[Dict]):
        """设置灰阶测量数据"""
        self.gamma_data = gray_scale

    # ========== 色域计算 ==========

    def get_gamut_triangle(self) -> List[Tuple[float, float]]:
        """
        获取测量色域的三角形坐标

        Returns:
            List of (x, y) tuples for red, green, blue points
        """
        if not self.gamut_data:
            return []

        points = []
        for color in ["red", "green", "blue"]:
            if color in self.gamut_data and self.gamut_data[color]:
                data = self.gamut_data[color]
                points.append((data["x"], data["y"]))

        return points

    def get_white_point(self) -> Optional[Tuple[float, float]]:
        """获取测量的白点坐标"""
        if "white" in self.gamut_data and self.gamut_data["white"]:
            return (self.gamut_data["white"]["x"], self.gamut_data["white"]["y"])
        return None

    def calculate_gamut_coverage(self, standard: str = "sRGB") -> float:
        """
        计算色域覆盖率（已废弃，请使用 calculate_gamut_metrics）

        ⚠️ 此函数实际计算的是"面积比"而非真正的"覆盖率"：
        - 面积比 = 测量面积 / 标准面积（可 >100%）
        - 覆盖率 = 交集面积 / 标准面积（最大 100%）

        Args:
            standard: 标准色域名称 ("sRGB", "DCI-P3", "Adobe RGB")

        Returns:
            float: 面积比百分比（注意：这不是覆盖率）

        Deprecated:
            使用 calculate_gamut_metrics() 获取正确的 coverage_percent 和 area_ratio_percent
        """
        warnings.warn(
            "calculate_gamut_coverage() 计算的是面积比而非覆盖率，请使用 calculate_gamut_metrics()",
            DeprecationWarning,
            stacklevel=2
        )
        
        # 使用新的精确算法计算面积比
        metrics = self.calculate_gamut_metrics(standard)
        return metrics["area_ratio_percent"]

    def calculate_gamut_metrics(self, standard: str = "sRGB") -> Dict:
        """
        计算完整的色域指标（P2-B 新增）

        使用 Sutherland-Hodgman 算法精确计算交集面积，
        区分"覆盖率"和"面积比"两个独立指标。

        Args:
            standard: 标准色域名称 ("sRGB", "DCI-P3", "Adobe RGB", "Rec.2020")

        Returns:
            Dict: {
                "coverage_percent": 覆盖率 (0-100%) - 标准色域被覆盖多少,
                "area_ratio_percent": 面积比 (可>100%) - 测量色域相对大小,
                "measured_area": 测量面积,
                "standard_area": 标准面积,
                "intersection_area": 交集面积,
                "standard": 标准色域名称
            }
        """
        if standard not in STANDARD_GAMUTS:
            return {
                "coverage_percent": 0.0,
                "area_ratio_percent": 0.0,
                "measured_area": 0.0,
                "standard_area": 0.0,
                "intersection_area": 0.0,
                "standard": standard,
            }

        measured_triangle = self.get_gamut_triangle()
        if len(measured_triangle) != 3:
            return {
                "coverage_percent": 0.0,
                "area_ratio_percent": 0.0,
                "measured_area": 0.0,
                "standard_area": 0.0,
                "intersection_area": 0.0,
                "standard": standard,
            }

        standard_triangle = [
            STANDARD_GAMUTS[standard]["red"],
            STANDARD_GAMUTS[standard]["green"],
            STANDARD_GAMUTS[standard]["blue"]
        ]

        # 使用 Sutherland-Hodgman 算法计算精确交集
        metrics = gamut_metrics(measured_triangle, standard)
        
        # 添加额外信息
        metrics["standard"] = standard
        
        return metrics

    def calculate_gamut_overlap(self, standard: str = "sRGB") -> float:
        """
        计算色域重叠率（真正的覆盖率）

        使用 Sutherland-Hodgman 算法精确计算交集面积

        Args:
            standard: 标准色域名称

        Returns:
            float: 覆盖率百分比 (0-100%)

        Note:
            此函数现在使用精确的多边形交集算法，
            替换之前不可靠的蒙特卡洛采样方法。
        """
        # 使用新的精确算法
        metrics = self.calculate_gamut_metrics(standard)
        return metrics["coverage_percent"]

    def _triangle_area(self, points: List[Tuple[float, float]]) -> float:
        """
        计算三角形面积（使用叉积公式）

        Args:
            points: 三个点的 (x, y) 坐标列表

        Returns:
            float: 面积
        """
        if len(points) != 3:
            return 0.0

        p1, p2, p3 = points
        # 使用叉积公式：Area = 0.5 * |x1(y2-y3) + x2(y3-y1) + x3(y1-y2)|
        area = abs(p1[0] * (p2[1] - p3[1]) +
                   p2[0] * (p3[1] - p1[1]) +
                   p3[0] * (p1[1] - p2[1])) / 2
        return area

    def _calculate_overlap_area(self, triangle1: List[Tuple[float, float]],
                                triangle2: List[Tuple[float, float]]) -> float:
        """
        计算两个三角形的重叠面积（采样点方法）

        Args:
            triangle1: 第一个三角形
            triangle2: 第二个三角形

        Returns:
            float: 重叠面积
        """
        # 使用蒙特卡洛采样估算重叠面积
        # 在 triangle2 内采样大量点，检查有多少在 triangle1 内

        # 获取边界框
        all_points = triangle1 + triangle2
        min_x = min(p[0] for p in all_points)
        max_x = max(p[0] for p in all_points)
        min_y = min(p[1] for p in all_points)
        max_y = max(p[1] for p in all_points)

        # 采样
        num_samples = 10000
        count_in_both = 0
        count_in_triangle2 = 0

        for _ in range(num_samples):
            # 随机生成点
            x = min_x + (max_x - min_x) * (hash(str(_)) % 10000) / 10000
            y = min_y + (max_y - min_y) * (hash(str(_ + 10000)) % 10000) / 10000

            point = (x, y)

            if self._point_in_triangle(point, triangle2):
                count_in_triangle2 += 1
                if self._point_in_triangle(point, triangle1):
                    count_in_both += 1

        if count_in_triangle2 == 0:
            return 0.0

        # 计算重叠比例
        overlap_ratio = count_in_both / count_in_triangle2

        # 计算 triangle2 的面积
        triangle2_area = self._triangle_area(triangle2)

        return triangle2_area * overlap_ratio

    def _point_in_triangle(self, point: Tuple[float, float],
                           triangle: List[Tuple[float, float]]) -> bool:
        """
        检查点是否在三角形内（使用重心坐标法）

        Args:
            point: 要检查的点
            triangle: 三角形的三个顶点

        Returns:
            bool: 是否在三角形内
        """
        p = point
        a, b, c = triangle

        # 计算重心坐标
        v0 = (c[0] - a[0], c[1] - a[1])
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (p[0] - a[0], p[1] - a[1])

        dot00 = v0[0] * v0[0] + v0[1] * v0[1]
        dot01 = v0[0] * v1[0] + v0[1] * v1[1]
        dot02 = v0[0] * v2[0] + v0[1] * v2[1]
        dot11 = v1[0] * v1[0] + v1[1] * v1[1]
        dot12 = v1[0] * v2[0] + v1[1] * v2[1]

        inv_denom = 1 / (dot00 * dot11 - dot01 * dot01)
        u = (dot11 * dot02 - dot01 * dot12) * inv_denom
        v = (dot00 * dot12 - dot01 * dot02) * inv_denom

        return u >= 0 and v >= 0 and u + v <= 1

    # ========== Gamma/EOTF 计算 ==========

    def calculate_gamma(self) -> Optional[float]:
        """
        计算平均 Gamma 值（已修复黑场识别问题）

        使用灰阶测量数据计算 Gamma 值。
        正确识别黑场（patchName == "0%" 或 "black"），而非错误地识别 10%。

        Returns:
            Optional[float]: 平均 Gamma 值
        """
        if len(self.gamma_data) < 2:
            return None

        # 使用 transfer.py 的正确黑场/白场识别
        from src.color_science.transfer import (
            identify_black_patch,
            identify_white_patch,
            prepare_measurements_for_eotf,
        )

        # 识别黑场和白场
        black_point, black_Y = identify_black_patch(self.gamma_data)
        white_point, white_Y = identify_white_patch(self.gamma_data, self.gamut_data)

        if white_Y <= black_Y or white_Y <= 0:
            return None

        gamma_values = []

        for data in self.gamma_data:
            # 解析灰阶百分比
            patch_name = data.get("patchName", "")
            input_level = None

            # 从 patchName 解析百分比
            if "%" in patch_name:
                try:
                    percent = float(patch_name.replace("%", "").strip())
                    input_level = percent / 100.0
                except ValueError:
                    pass

            # 如果无法从 patchName 解析，从 RGB 估算
            if input_level is None:
                rgb = data.get("rgb", data.get("RGB", {}))
                if isinstance(rgb, dict):
                    r = rgb.get("r", rgb.get("R", 128))
                    g = rgb.get("g", rgb.get("G", 128))
                    b = rgb.get("b", rgb.get("B", 128))
                elif isinstance(rgb, (list, tuple)) and len(rgb) >= 3:
                    r, g, b = rgb[0], rgb[1], rgb[2]
                else:
                    r, g, b = 128, 128, 128

                # 灰阶时 R=G=B，取平均值
                input_level = ((r + g + b) / 3.0) / 255.0

            Y = data.get("Y", 0.0)

            # 计算 Gamma（跳过黑场和白场点）
            if input_level > 0.01 and input_level < 0.99 and Y > black_Y:
                Y_normalized = (Y - black_Y) / (white_Y - black_Y)

                if Y_normalized > 0 and Y_normalized < 1:
                    gamma = math.log(Y_normalized) / math.log(input_level)
                    if 1.0 <= gamma <= 4.0:  # 合理范围
                        gamma_values.append(gamma)

        if len(gamma_values) == 0:
            return None

        # 返回平均 Gamma 值
        return sum(gamma_values) / len(gamma_values)

    def calculate_gamma_curve(self) -> List[Tuple[float, float, float]]:
        """
        计算 Gamma 曲线数据点（已修复黑场识别问题）

        Returns:
            List of (input_level, measured_Y, gamma_value) tuples
        """
        if len(self.gamma_data) < 2:
            return []

        from src.color_science.transfer import identify_black_patch, identify_white_patch

        # 正确识别黑场和白场
        black_point, black_Y = identify_black_patch(self.gamma_data)
        white_point, white_Y = identify_white_patch(self.gamma_data, self.gamut_data)

        if white_Y <= black_Y:
            return []

        curve_data = []

        for data in self.gamma_data:
            patch_name = data.get("patchName", "")
            input_level = None

            if "%" in patch_name:
                try:
                    percent = float(patch_name.replace("%", "").strip())
                    input_level = percent / 100.0
                except ValueError:
                    pass

            if input_level is None:
                rgb = data.get("rgb", data.get("RGB", {}))
                if isinstance(rgb, dict):
                    r = rgb.get("r", rgb.get("R", 128))
                elif isinstance(rgb, (list, tuple)):
                    r = rgb[0]
                else:
                    r = 128
                input_level = r / 255.0

            Y = data.get("Y", 0.0)

            # 计算该点的 Gamma 值
            Y_normalized = (Y - black_Y) / (white_Y - black_Y)
            if input_level > 0 and Y_normalized > 0:
                gamma = math.log(Y_normalized) / math.log(input_level)
            else:
                gamma = None

            curve_data.append((input_level, Y, gamma))

        return curve_data

    def calculate_eotf_errors(
        self,
        target_curve: str = "gamma2.2",
        **kwargs
    ) -> Dict:
        """
        计算测量数据与目标 EOTF 曲线的误差

        Args:
            target_curve: 目标曲线名称
                - "gamma2.2", "gamma2.4"
                - "sRGB" (分段 Gamma)
                - "BT.1886" (带黑场补偿)
                - "PQ" (HDR)
                - "HLG" (HDR)
            **kwargs: 曲线参数
                - Lw: 白场亮度 (cd/m²)
                - Lb: 黑场亮度 (cd/m²)
                - L_max: 最大亮度 (HDR, cd/m²)

        Returns:
            Dict: 误差统计
                - mean_error: 平均误差 (cd/m²)
                - max_error: 最大误差 (cd/m²)
                - max_error_point: 最大误差点
                - dark_error: 暗部误差 (L < 20)
                - bright_error: 亮部误差
                - gamma_estimate: 估算 Gamma 值
                - points: 每点详情
        """
        if len(self.gamma_data) < 2:
            return {
                "mean_error": 0.0,
                "max_error": 0.0,
                "max_error_point": None,
                "dark_error": 0.0,
                "bright_error": 0.0,
                "gamma_estimate": None,
                "points": [],
            }

        from src.color_science.transfer import (
            prepare_measurements_for_eotf,
            calculate_eotf_errors,
            apply_eotf,
        )

        # 准备测量数据并自动识别黑场白场
        processed, Lb, Lw = prepare_measurements_for_eotf(self.gamma_data, self.gamut_data)

        # 如果未提供参数，使用实测值
        curve_kwargs = kwargs.copy()
        if target_curve == "BT.1886":
            if "Lw" not in curve_kwargs:
                curve_kwargs["Lw"] = Lw
            if "Lb" not in curve_kwargs:
                curve_kwargs["Lb"] = Lb

        # 计算误差
        errors = calculate_eotf_errors(processed, target_curve, **curve_kwargs)

        return errors

    def calculate_bt1886_errors(self) -> Dict:
        """
        计算测量数据与 BT.1886 曲线的误差（使用实测黑场和白场）

        BT.1886 正确实现：使用实测的 Lw 和 Lb 参数

        Returns:
            Dict: 包含 Lw, Lb, gamma 和误差统计
        """
        if len(self.gamma_data) < 2:
            return {
                "Lw": 100.0,
                "Lb": 0.0,
                "gamma": 2.4,
                "error": "没有足够的测量数据",
            }

        from src.color_science.transfer import calculate_bt1886_with_measured_black

        result = calculate_bt1886_with_measured_black(self.gamma_data, self.gamut_data)

        return result

    def get_gamma_report(self) -> Dict:
        """
        获取完整的 Gamma/EOTF 报告

        包含：
        - 平均 Gamma 值
        - 黑场亮度 Lb
        - 白场亮度 Lw
        - 与标准曲线的误差对比

        Returns:
            Dict: 完整报告
        """
        from src.color_science.transfer import identify_black_patch, identify_white_patch

        # 获取基本数据
        black_point, Lb = identify_black_patch(self.gamma_data)
        white_point, Lw = identify_white_patch(self.gamma_data, self.gamut_data)
        avg_gamma = self.calculate_gamma()

        # 对比多种目标曲线
        curves = ["gamma2.2", "gamma2.4", "sRGB", "BT.1886"]
        curve_errors = {}

        for curve in curves:
            errors = self.calculate_eotf_errors(curve)
            curve_errors[curve] = {
                "mean_error": errors["mean_error"],
                "max_error": errors["max_error"],
                "dark_error": errors["dark_error"],
            }

        # BT.1886 专用报告
        bt1886_result = self.calculate_bt1886_errors()

        return {
            "average_gamma": avg_gamma,
            "black_luminance": Lb,
            "white_luminance": Lw,
            "contrast_ratio": Lw / Lb if Lb > 0 else None,
            "curve_errors": curve_errors,
            "bt1886": bt1886_result,
            "num_points": len(self.gamma_data),
        }

    # ========== Delta E 计算 ==========

    def calculate_delta_e(self, measured: Dict, target: Dict) -> float:
        """
        计算 Delta E (CIE 1976)

        简化的 Delta E 计算，使用 CIE 1976 公式

        Args:
            measured: 测量结果 {"x": ..., "y": ..., "Y": ...}
            target: 目标值 {"x": ..., "y": ..., "Y": ...}

        Returns:
            float: Delta E 值
        """
        # 转换到 CIE L*u*v* 或使用简化公式
        # 这里使用简化的 xyY Delta E

        dx = measured["x"] - target["x"]
        dy = measured["y"] - target["y"]

        # Y 值的相对差异
        if target["Y"] > 0:
            dY_ratio = (measured["Y"] - target["Y"]) / target["Y"]
        else:
            dY_ratio = measured["Y"]

        # 简化的 Delta E
        delta_e = math.sqrt(dx * dx + dy * dy + dY_ratio * dY_ratio)

        return delta_e

    # ========== 色温计算 ==========

    def calculate_cct(self, x: float, y: float, method: str = "robertson") -> float:
        """
        从 CIE xy 坐标计算相关色温 (CCT)

        支持 McCamy 近似或 Robertson 等温线方法

        Args:
            x: CIE x 坐标
            y: CIE y 坐标
            method: 计算方法 ("robertson" 更精确，"mccamy" 快速近似)

        Returns:
            float: 相关色温 (K)
        """
        if method.lower() == "robertson":
            return xy_to_cct_robertson(x, y)
        else:
            return xy_to_cct_mccamy(x, y)

    def calculate_cct_duv(self, x: float, y: float) -> Tuple[float, float]:
        """
        从 CIE xy 坐标计算 CCT 和 Duv

        Duv 表示偏离普朗克曲线的程度：
        - 正值 (>0): 偏黄/偏绿（高于 Planckian 轨迹）
        - 负值 (<0): 偏蓝/偏紫（低于 Planckian 轨迹）
        - 接近 0: 在 Planckian 轨迹附近，色温准确

        Args:
            x: CIE x 坐标
            y: CIE y 坐标

        Returns:
            Tuple[float, float]: (CCT, Duv)
            - CCT: 相关色温 (K)
            - Duv: 偏离普朗克曲线的程度
        """
        return cct_duv_from_xy(x, y)

    def interpret_duv_direction(self, duv: float) -> str:
        """
        解释 Duv 偏移方向

        Args:
            duv: Duv 值

        Returns:
            str: 方向描述
        """
        if abs(duv) < 0.001:
            return "色温准确，在普朗克曲线上"
        elif duv > 0.005:
            return "偏黄/偏绿（高于普朗克曲线，可能偏暖）"
        elif duv > 0.001:
            return "轻微偏黄（略高于普朗克曲线）"
        elif duv < -0.005:
            return "偏蓝/偏紫（低于普朗克曲线，可能偏冷）"
        elif duv < -0.001:
            return "轻微偏蓝（略低于普朗克曲线）"
        else:
            return "色温基本准确"

    # ========== 白点偏差计算 ==========

    def calculate_white_point_deviation(self, measured_x: float, measured_y: float,
                                         target_x: float = 0.3127, target_y: float = 0.3290) -> float:
        """
        计算白点偏差（相对于目标白点，默认D65）

        使用 CIE 1976 u'v' 色差公式

        Args:
            measured_x: 测量的 x 坐标
            measured_y: 测量的 y 坐标
            target_x: 目标 x 坐标（默认 D65）
            target_y: 目标 y 坐标（默认 D65）

        Returns:
            float: 白点偏差 ΔE
        """
        # 转换到 CIE 1976 u'v'
        measured_uv = self._xy_to_uv(measured_x, measured_y)
        target_uv = self._xy_to_uv(target_x, target_y)

        # 计算 u'v' 色差
        delta_u = measured_uv[0] - target_uv[0]
        delta_v = measured_uv[1] - target_uv[1]

        # ΔE = 13 * sqrt(Δu'² + Δv'²)
        delta_e = 13 * math.sqrt(delta_u ** 2 + delta_v ** 2)

        return delta_e

    def _xy_to_uv(self, x: float, y: float) -> Tuple[float, float]:
        """
        将 CIE 1931 xy 转换为 CIE 1976 u'v'

        Args:
            x: CIE x 坐标
            y: CIE y 坐标

        Returns:
            Tuple: (u', v')
        """
        denominator = 12 * y - 2 * x + 3
        if denominator == 0:
            return (0, 0)

        u = (4 * x) / denominator
        v = (9 * y) / denominator

        return (u, v)

    def _xy_to_XYZ(self, x: float, y: float, Y: float = 100) -> Tuple[float, float, float]:
        """
        将 CIE xyY 转换为 XYZ

        Args:
            x: CIE x 坐标
            y: CIE y 坐标
            Y: 亮度值

        Returns:
            Tuple: (X, Y, Z)
        """
        if y == 0:
            return (0, Y, 0)

        X = (x * Y) / y
        Z = ((1 - x - y) * Y) / y

        return (X, Y, Z)

    def _XYZ_to_Lab(self, X: float, Y: float, Z: float,
                    ref_X: float = 95.047, ref_Y: float = 100.0, ref_Z: float = 108.883) -> Tuple[float, float, float]:
        """
        将 XYZ 转换为 CIE L*a*b*

        Args:
            X, Y, Z: XYZ 值
            ref_X, ref_Y, ref_Z: 参考白点（默认 D65）

        Returns:
            Tuple: (L*, a*, b*)
        """
        # 归一化
        x = X / ref_X
        y = Y / ref_Y
        z = Z / ref_Z

        # 非线性变换
        def f(t):
            delta = 6/29
            if t > delta ** 3:
                return t ** (1/3)
            else:
                return t / (3 * delta ** 2) + 4/29

        fx = f(x)
        fy = f(y)
        fz = f(z)

        L = 116 * fy - 16
        a = 500 * (fx - fy)
        b = 200 * (fy - fz)

        return (L, a, b)

    def calculate_delta_e_2000(
        self,
        measured: Dict,
        target: Dict,
        white_point: str = "D65",
        adapt: bool = True,
        measured_white: Optional[str] = None,
        method: str = "bradford"
    ) -> float:
        """
        计算 Delta E 2000（支持白点适配）

        更精确的色差计算公式，支持：
        - 使用实际测量白点或目标白点
        - Bradford 或 CAT02 白点适配

        Args:
            measured: 测量结果 {"x": ..., "y": ..., "Y": ...}
            target: 目标值 {"x": ..., "y": ..., "Y": ...}
            white_point: 计算 Lab 使用的参考白点（默认 D65）
            adapt: 是否做白点适配（默认 True）
            measured_white: 测量光源的白点名称（如 "D65", "D50", None表示使用默认）
            method: 白点适配方法 ("bradford" 或 "cat02")

        Returns:
            float: Delta E 2000 值

        示例:
            # 使用默认 D65 白点
            delta_e = analyzer.calculate_delta_e_2000(measured, target)

            # 使用测量光源 D50
            delta_e = analyzer.calculate_delta_e_2000(
                measured, target,
                white_point="D50",
                measured_white="D50"
            )

            # 使用测量白点适配到目标 D65
            delta_e = analyzer.calculate_delta_e_2000(
                measured, target,
                white_point="D65",
                measured_white="D50",  # 测量光源是 D50，适配到 D65 计算
                adapt=True
            )
        """
        # 获取测量白点（如果未指定，使用默认白点）
        source_white = measured_white if measured_white else white_point

        # 使用 colorimetry.py 的 delta_e_from_xyY 函数
        return delta_e_from_xyY(
            (measured["x"], measured["y"], measured.get("Y", 100)),
            (target["x"], target["y"], target.get("Y", 100)),
            white_point=white_point,
            method="ciede2000",
            adapt=adapt,
            source_white1=source_white if adapt else None,
            source_white2=white_point if adapt else None,
        )

    def calculate_delta_e_2000_old(self, measured: Dict, target: Dict) -> float:
        """
        计算 Delta E 2000（旧方法，固定 D65）

        已废弃：建议使用 calculate_delta_e_2000() 新方法

        Args:
            measured: 测量结果 {"x": ..., "y": ..., "Y": ...}
            target: 目标值 {"x": ..., "y": ..., "Y": ...}

        Returns:
            float: Delta E 2000 值
        """
        # 转换到 XYZ
        measured_XYZ = self._xy_to_XYZ(measured["x"], measured["y"], measured.get("Y", 100))
        target_XYZ = self._xy_to_XYZ(target["x"], target["y"], target.get("Y", 100))

        # 转换到 Lab
        measured_Lab = self._XYZ_to_Lab(*measured_XYZ)
        target_Lab = self._XYZ_to_Lab(*target_XYZ)

        # 计算 Delta E 2000
        return self._delta_e_2000(measured_Lab, target_Lab)

    def _delta_e_2000(self, lab1: Tuple[float, float, float], lab2: Tuple[float, float, float]) -> float:
        """
        计算 CIE Delta E 2000

        Args:
            lab1: 第一个颜色的 L*, a*, b* 值
            lab2: 第二个颜色的 L*, a*, b* 值

        Returns:
            float: Delta E 2000 值
        """
        L1, a1, b1 = lab1
        L2, a2, b2 = lab2

        # 参数
        kL = 1.0
        kC = 1.0
        kH = 1.0

        # 计算 C* 和 h
        C1 = math.sqrt(a1 ** 2 + b1 ** 2)
        C2 = math.sqrt(a2 ** 2 + b2 ** 2)
        C_avg = (C1 + C2) / 2

        G = 0.5 * (1 - math.sqrt(C_avg ** 7 / (C_avg ** 7 + 25 ** 7)))

        a1_prime = a1 * (1 + G)
        a2_prime = a2 * (1 + G)

        C1_prime = math.sqrt(a1_prime ** 2 + b1 ** 2)
        C2_prime = math.sqrt(a2_prime ** 2 + b2 ** 2)

        def calc_h(a_prime, b):
            if a_prime == 0 and b == 0:
                return 0
            h = math.degrees(math.atan2(b, a_prime))
            if h < 0:
                h += 360
            return h

        h1_prime = calc_h(a1_prime, b1)
        h2_prime = calc_h(a2_prime, b2)

        # 计算 ΔL', ΔC', ΔH'
        delta_L_prime = L2 - L1
        delta_C_prime = C2_prime - C1_prime

        if C1_prime * C2_prime == 0:
            delta_h_prime = 0
        else:
            diff = h2_prime - h1_prime
            if abs(diff) <= 180:
                delta_h_prime = diff
            elif diff > 180:
                delta_h_prime = diff - 360
            else:
                delta_h_prime = diff + 360

        delta_H_prime = 2 * math.sqrt(C1_prime * C2_prime) * math.sin(math.radians(delta_h_prime / 2))

        # 计算 CIEDE2000
        L_prime_avg = (L1 + L2) / 2
        C_prime_avg = (C1_prime + C2_prime) / 2

        if C1_prime * C2_prime == 0:
            h_prime_avg = h1_prime + h2_prime
        else:
            if abs(h1_prime - h2_prime) <= 180:
                h_prime_avg = (h1_prime + h2_prime) / 2
            else:
                if h1_prime + h2_prime < 360:
                    h_prime_avg = (h1_prime + h2_prime + 360) / 2
                else:
                    h_prime_avg = (h1_prime + h2_prime - 360) / 2

        T = (1 - 0.17 * math.cos(math.radians(h_prime_avg - 30))
             + 0.24 * math.cos(math.radians(2 * h_prime_avg))
             + 0.32 * math.cos(math.radians(3 * h_prime_avg + 6))
             - 0.20 * math.cos(math.radians(4 * h_prime_avg - 63)))

        delta_theta = 30 * math.exp(-((h_prime_avg - 275) / 25) ** 2)
        R_C = 2 * math.sqrt(C_prime_avg ** 7 / (C_prime_avg ** 7 + 25 ** 7))
        S_L = 1 + (0.015 * (L_prime_avg - 50) ** 2) / math.sqrt(20 + (L_prime_avg - 50) ** 2)
        S_C = 1 + 0.045 * C_prime_avg
        S_H = 1 + 0.015 * C_prime_avg * T
        R_T = -math.sin(math.radians(2 * delta_theta)) * R_C

        delta_E = math.sqrt(
            (delta_L_prime / (kL * S_L)) ** 2 +
            (delta_C_prime / (kC * S_C)) ** 2 +
            (delta_H_prime / (kH * S_H)) ** 2 +
            R_T * (delta_C_prime / (kC * S_C)) * (delta_H_prime / (kH * S_H))
        )

        return delta_E

    # ========== 显示器基础数据计算 ==========

    def calculate_display_basic_data(self, gamut_data: Dict, gamma_data: List = None) -> Dict:
        """
        计算显示器基础数据

        Args:
            gamut_data: 色域测量数据（包含红绿蓝白黑）
            gamma_data: 灰阶测量数据

        Returns:
            Dict: 显示器基础数据
        """
        result = {
            "peak_luminance": None,
            "black_luminance": None,
            "contrast_ratio": None,
            "white_cct": None,
            "white_deviation": None,
            "gamma": None
        }

        # 峰值亮度（白色）- 支持中英文键
        white_data = gamut_data.get("white") or gamut_data.get("白")
        if white_data:
            result["peak_luminance"] = white_data.get("Y")
            result["white_cct"] = self.calculate_cct(
                white_data["x"],
                white_data["y"]
            )
            result["white_deviation"] = self.calculate_white_point_deviation(
                white_data["x"],
                white_data["y"]
            )

        # 黑场亮度 - 支持中英文键
        black_data = gamut_data.get("black") or gamut_data.get("黑")
        if black_data:
            result["black_luminance"] = black_data.get("Y")

        # 对比度
        if result["peak_luminance"] and result["black_luminance"] and result["black_luminance"] > 0:
            result["contrast_ratio"] = result["peak_luminance"] / result["black_luminance"]

        # Gamma
        if gamma_data and len(gamma_data) >= 2:
            self.set_gamma_data(gamma_data)
            result["gamma"] = self.calculate_gamma()

        return result

    # ========== 灰阶报告（P2-D 新增） ==========

    def analyze_grayscale_point(
        self,
        measured: Dict,
        target_white: Tuple[float, float] = (0.3127, 0.3290),
        measured_Y: Optional[float] = None
    ) -> Dict:
        """
        分析单个灰阶点

        报告 xy 偏移、Duv、Delta E 组合，能解释"偏绿/偏品红"的方向

        Args:
            measured: 测量结果 {"x": ..., "y": ..., "Y": ...}
            target_white: 目标白点 xy 坐标（默认 D65）
            measured_Y: 如果需要计算 Delta E，提供 Y 值（默认使用 measured 中的 Y）

        Returns:
            Dict: 灰阶分析结果
                - x, y: 测量坐标
                - target_x, target_y: 目标白点
                - delta_x, delta_y: xy 偏移
                - cct: 相关色温
                - duv: Duv 值
                - duv_direction: Duv 方向描述
                - xy_direction: xy 偏移方向描述
                - delta_e: Delta E 2000（如果 Y 值提供）
        """
        x = measured["x"]
        y = measured["y"]
        Y = measured_Y or measured.get("Y", 100)
        target_x, target_y = target_white

        # 计算 xy 偏移
        delta_x = x - target_x
        delta_y = y - target_y

        # 计算 CCT 和 Duv
        cct, duv = self.calculate_cct_duv(x, y)

        # 方向解释
        duv_direction = self.interpret_duv_direction(duv)

        # xy 偏移方向
        xy_direction = self._interpret_xy_offset(delta_x, delta_y)

        result = {
            "x": x,
            "y": y,
            "target_x": target_x,
            "target_y": target_y,
            "delta_x": delta_x,
            "delta_y": delta_y,
            "cct": cct,
            "duv": duv,
            "duv_direction": duv_direction,
            "xy_direction": xy_direction,
        }

        # 计算 Delta E（与目标白点）
        result["delta_e"] = self.calculate_delta_e_2000(
            {"x": x, "y": y, "Y": Y},
            {"x": target_x, "y": target_y, "Y": Y}
        )

        return result

    def analyze_grayscale_series(
        self,
        gray_scale_data: List[Dict],
        target_white: Tuple[float, float] = (0.3127, 0.3290),
        white_point_name: Optional[str] = None
    ) -> Dict:
        """
        分析灰阶系列数据

        Args:
            gray_scale_data: 灰阶测量数据列表
                [{"patchName": "10%", "x": ..., "y": ..., "Y": ...}, ...]
            target_white: 目标白点 xy 坐标（默认 D65）
            white_point_name: 目标白点名称（如 "D65", "D50")

        Returns:
            Dict: 灰阶系列分析结果
                - points: 每个灰阶点的分析结果列表
                - summary: 汇总统计
                    - avg_delta_e: 平均 Delta E
                    - max_delta_e: 最大 Delta E
                    - avg_duv: 平均 Duv
                    - max_duv_abs: 最大 Duv 绝对值
                    - avg_cct: 平均 CCT
                    - overall_direction: 总体偏移方向描述
        """
        if white_point_name:
            try:
                target_white = get_white_point_xy(white_point_name)
            except KeyError:
                pass

        points_analysis = []
        delta_e_values = []
        duv_values = []
        cct_values = []

        for point_data in gray_scale_data:
            analysis = self.analyze_grayscale_point(point_data, target_white)
            analysis["patch_name"] = point_data.get("patchName", "unknown")
            points_analysis.append(analysis)

            delta_e_values.append(analysis["delta_e"])
            duv_values.append(analysis["duv"])
            cct_values.append(analysis["cct"])

        # 计算汇总统计
        avg_delta_e = sum(delta_e_values) / len(delta_e_values) if delta_e_values else 0
        max_delta_e = max(delta_e_values) if delta_e_values else 0
        avg_duv = sum(duv_values) / len(duv_values) if duv_values else 0
        max_duv_abs = max(abs(d) for d in duv_values) if duv_values else 0
        avg_cct = sum(cct_values) / len(cct_values) if cct_values else 0

        # 总体偏移方向
        overall_direction = self._interpret_grayscale_trend(duv_values, delta_e_values)

        return {
            "points": points_analysis,
            "summary": {
                "avg_delta_e": avg_delta_e,
                "max_delta_e": max_delta_e,
                "avg_duv": avg_duv,
                "max_duv_abs": max_duv_abs,
                "avg_cct": avg_cct,
                "overall_direction": overall_direction,
                "target_white": target_white,
            }
        }

    def _interpret_xy_offset(self, delta_x: float, delta_y: float) -> str:
        """
        解释 xy 偏移方向

        Args:
            delta_x: x 坐标偏移
            delta_y: y 坐标偏移

        Returns:
            str: 方向描述
        """
        if abs(delta_x) < 0.001 and abs(delta_y) < 0.001:
            return "色度准确"

        # 主方向判断
        directions = []

        if delta_y > 0.01:
            directions.append("偏绿")
        elif delta_y > 0.002:
            directions.append("微偏绿")
        elif delta_y < -0.01:
            directions.append("偏品红")
        elif delta_y < -0.002:
            directions.append("微偏品红")

        if delta_x > 0.01:
            directions.append("偏红")
        elif delta_x > 0.002:
            directions.append("微偏红")
        elif delta_x < -0.01:
            directions.append("偏蓝")
        elif delta_x < -0.002:
            directions.append("微偏蓝")

        return "，".join(directions) if directions else "轻微偏移"

    def _interpret_grayscale_trend(self, duv_values: List[float], delta_e_values: List[float]) -> str:
        """
        解释灰阶趋势

        Args:
            duv_values: 各灰阶点的 Duv 值列表
            delta_e_values: 各灰阶点的 Delta E 值列表

        Returns:
            str: 总体趋势描述
        """
        avg_duv = sum(duv_values) / len(duv_values) if duv_values else 0
        avg_delta_e = sum(delta_e_values) / len(delta_e_values) if delta_e_values else 0

        # 判断整体趋势
        if avg_delta_e < 0.5:
            quality = "优秀"
        elif avg_delta_e < 1.0:
            quality = "良好"
        elif avg_delta_e < 2.0:
            quality = "一般"
        elif avg_delta_e < 4.0:
            quality = "较差"
        else:
            quality = "很差"

        # 判断颜色偏移趋势
        if avg_duv > 0.005:
            color_trend = "整体偏黄/偏绿"
        elif avg_duv > 0.001:
            color_trend = "轻微偏黄"
        elif avg_duv < -0.005:
            color_trend = "整体偏蓝/偏紫"
        elif avg_duv < -0.001:
            color_trend = "轻微偏蓝"
        else:
            color_trend = "色度基本准确"

        return f"{quality}，{color_trend}，平均Delta E={avg_delta_e:.2f}"


# ========== CIE 1931 光谱轨迹数据 ==========

# CIE 1931 色度图的光谱轨迹边界点（波长 380nm - 700nm）
CIE_SPECTRAL_LOCUS = [
    # 380nm - 紫色边缘
    (0.174, 0.005),
    (0.175, 0.005),
    # 400nm - 紫色
    (0.173, 0.005),
    # 420nm - 紫蓝
    (0.171, 0.006),
    # 440nm - 蓝
    (0.164, 0.011),
    # 460nm - 青
    (0.145, 0.024),
    # 480nm - 青
    (0.135, 0.040),
    # 500nm - 绿
    (0.124, 0.058),
    # 520nm - 绿
    (0.109, 0.086),
    # 540nm - 黄绿
    (0.091, 0.132),
    # 550nm - 黄绿
    (0.078, 0.170),
    # 560nm - 黄
    (0.063, 0.217),
    # 570nm - 黄
    (0.051, 0.267),
    # 580nm - 黄橙
    (0.042, 0.317),
    # 590nm - 橙
    (0.036, 0.367),
    # 600nm - 橙红
    (0.032, 0.417),
    # 610nm - 红
    (0.029, 0.467),
    # 620nm - 红
    (0.026, 0.517),
    # 630nm - 红
    (0.024, 0.567),
    # 640nm - 红
    (0.022, 0.617),
    # 650nm - 红
    (0.021, 0.667),
    # 660nm - 红
    (0.020, 0.717),
    # 670nm - 红
    (0.019, 0.767),
    # 680nm - 红边缘
    (0.018, 0.800),
    # 700nm - 红边缘
    (0.017, 0.800),
    # 紫红线（连接红端和紫端）
    (0.174, 0.005),  # 回到起点闭合
]

# 更精确的光谱轨迹数据（标准）
CIE_SPECTRAL_LOCUS_PRECISE = [
    # (x, y, wavelength_nm)
    (0.1741, 0.0050, 380),
    (0.1740, 0.0050, 385),
    (0.1738, 0.0049, 390),
    (0.1736, 0.0049, 395),
    (0.1733, 0.0048, 400),
    (0.1730, 0.0048, 405),
    (0.1726, 0.0048, 410),
    (0.1721, 0.0048, 415),
    (0.1714, 0.0051, 420),
    (0.1703, 0.0058, 425),
    (0.1689, 0.0069, 430),
    (0.1669, 0.0086, 435),
    (0.1644, 0.0109, 440),
    (0.1611, 0.0138, 445),
    (0.1566, 0.0177, 450),
    (0.1510, 0.0227, 455),
    (0.1440, 0.0297, 460),
    (0.1355, 0.0399, 465),
    (0.1241, 0.0578, 470),
    (0.1096, 0.0868, 475),
    (0.0913, 0.1327, 480),
    (0.0687, 0.2007, 485),
    (0.0454, 0.2950, 490),
    (0.0235, 0.4127, 495),
    (0.0082, 0.5384, 500),
    (0.0039, 0.6548, 505),
    (0.0139, 0.7459, 510),
    (0.0389, 0.8019, 515),
    (0.0743, 0.8225, 520),
    (0.1142, 0.8115, 525),
    (0.1547, 0.7737, 530),
    (0.1929, 0.7188, 535),
    (0.2296, 0.6495, 540),
    (0.2658, 0.5744, 545),
    (0.3016, 0.4983, 550),
    (0.3373, 0.4240, 555),
    (0.3731, 0.3527, 560),
    (0.4087, 0.2867, 565),
    (0.4440, 0.2277, 570),
    (0.4788, 0.1770, 575),
    (0.5125, 0.1363, 580),
    (0.5448, 0.1042, 585),
    (0.5752, 0.0790, 590),
    (0.6029, 0.0602, 595),
    (0.6270, 0.0465, 600),
    (0.6482, 0.0366, 605),
    (0.6658, 0.0296, 610),
    (0.6801, 0.0248, 615),
    (0.6915, 0.0213, 620),
    (0.7006, 0.0187, 625),
    (0.7079, 0.0167, 630),
    (0.7140, 0.0151, 635),
    (0.7190, 0.0139, 640),
    (0.7230, 0.0129, 645),
    (0.7260, 0.0122, 650),
    (0.7283, 0.0116, 655),
    (0.7300, 0.0112, 660),
    (0.7311, 0.0109, 665),
    (0.7317, 0.0107, 670),
    (0.7319, 0.0105, 675),
    (0.7318, 0.0104, 680),
    (0.7314, 0.0103, 685),
    (0.7307, 0.0102, 690),
    (0.7297, 0.0101, 695),
    (0.7284, 0.0100, 700),
    # 紫红线起点
    (0.1741, 0.0050, 380),  # 闭合
]


def get_cie_spectral_locus() -> List[Tuple[float, float]]:
    """获取 CIE 1931 光谱轨迹坐标"""
    return [(p[0], p[1]) for p in CIE_SPECTRAL_LOCUS_PRECISE]


def get_standard_gamut_triangle(name: str) -> List[Tuple[float, float]]:
    """获取标准色域三角形坐标"""
    if name not in STANDARD_GAMUTS:
        return []
    gamut = STANDARD_GAMUTS[name]
    return [
        gamut["red"],
        gamut["green"],
        gamut["blue"]
    ]


# ==============================================================================
# P4-D 验证分析函数
# ==============================================================================

def calculate_validation_delta_e_statistics(
    verification_points: List[Dict],
    target_standard: str = "sRGB"
) -> Dict:
    """
    计算验证色块的 Delta E 统计

    Args:
        verification_points: 验证色块测量数据
            [{"rgb": (r, g, b), "name": "...", "xyz": (X, Y, Z), "xyY": (x, y, Y)}, ...]
        target_standard: 目标标准

    Returns:
        Dict: Delta E 统计
            - delta_e_avg: 平均 Delta E
            - delta_e_max: 最大 Delta E
            - delta_e_95: 95% Delta E
            - delta_e_distribution: Delta E 分布
            - passed_count: 合格数量 (Delta E < 2)
            - failed_count: 不合格数量
            - worst_points: 最差色块列表
    """
    if not verification_points:
        return {
            "delta_e_avg": 0.0,
            "delta_e_max": 0.0,
            "delta_e_95": 0.0,
            "delta_e_distribution": [],
            "passed_count": 0,
            "failed_count": 0,
            "worst_points": [],
        }

    analyzer = MeasurementAnalyzer()
    delta_e_values = []
    points_with_delta_e = []

    # 计算每个点的 Delta E
    for point in verification_points:
        rgb = point.get("rgb", (128, 128, 128))
        name = point.get("name", "unknown")
        measured_xyY = point.get("xyY", (0.3127, 0.3290, 100.0))

        # 计算目标 xyY
        target_xyY = _calculate_target_xyY(rgb, target_standard)

        # 计算 Delta E 2000
        measured = {"x": measured_xyY[0], "y": measured_xyY[1], "Y": measured_xyY[2]}
        target = {"x": target_xyY[0], "y": target_xyY[1], "Y": target_xyY[2]}
        delta_e = analyzer.calculate_delta_e_2000(measured, target)

        delta_e_values.append(delta_e)
        points_with_delta_e.append({
            "rgb": rgb,
            "name": name,
            "delta_e": delta_e,
            "measured_xyY": measured_xyY,
            "target_xyY": target_xyY,
        })

    if not delta_e_values:
        return {
            "delta_e_avg": 0.0,
            "delta_e_max": 0.0,
            "delta_e_95": 0.0,
            "delta_e_distribution": [],
            "passed_count": 0,
            "failed_count": 0,
            "worst_points": [],
        }

    # 计算统计值
    delta_e_avg = sum(delta_e_values) / len(delta_e_values)
    delta_e_max = max(delta_e_values)

    # 95 percentile
    sorted_values = sorted(delta_e_values)
    idx_95 = int(len(sorted_values) * 0.95)
    delta_e_95 = sorted_values[min(idx_95, len(sorted_values) - 1)]

    # 合格/不合格统计
    passed_threshold = 2.0  # Delta E < 2 为合格
    passed_count = sum(1 for d in delta_e_values if d < passed_threshold)
    failed_count = len(delta_e_values) - passed_count

    # 找出最差色块
    sorted_points = sorted(points_with_delta_e, key=lambda p: p["delta_e"], reverse=True)
    worst_points = sorted_points[:5]  # 取最差 5 个

    return {
        "delta_e_avg": delta_e_avg,
        "delta_e_max": delta_e_max,
        "delta_e_95": delta_e_95,
        "delta_e_distribution": delta_e_values,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "worst_points": worst_points,
        "total_points": len(delta_e_values),
    }


def _calculate_target_xyY(
    rgb: Tuple[int, int, int],
    standard: str = "sRGB"
) -> Tuple[float, float, float]:
    """
    计算 RGB 对应的目标 xyY 值

    内部辅助函数，用于验证计算

    Args:
        rgb: RGB 值 (0-255)
        standard: 目标标准

    Returns:
        Tuple[float, float, float]: 目标 xyY
    """
    # 简化实现：使用 sRGB 转换
    from .color_science import srgb_to_xyz

    r, g, b = rgb

    # 转换到 XYZ
    X, Y, Z = srgb_to_xyz(r, g, b)

    # 计算 xyY
    total = X + Y + Z
    if total > 0:
        x = X / total
        y = Y / total
    else:
        x = 0.3127
        y = 0.3290

    return (x, y, Y)


def compare_before_after_metrics(
    before_data: Dict,
    after_data: Dict
) -> Dict:
    """
    对比校准前后数据

    Args:
        before_data: 校准前测量数据
            {"delta_e_avg": ..., "white_point": {...}, "gamma": ..., "gamut_coverage": ..., ...}
        after_data: 校准后测量数据

    Returns:
        Dict: 对比结果
            - improvements: 各指标改善
            - overall_improvement: 综合改善评分
            - recommendation: 建议
    """
    comparison = {
        "before": before_data.copy(),
        "after": after_data.copy(),
        "improvements": {},
    }

    # Delta E 改善
    before_delta_e = before_data.get("delta_e_avg", 0.0)
    after_delta_e = after_data.get("delta_e_avg", 0.0)
    delta_e_improvement = before_delta_e - after_delta_e
    comparison["improvements"]["delta_e_avg"] = {
        "before": before_delta_e,
        "after": after_delta_e,
        "improvement": delta_e_improvement,
        "improved": delta_e_improvement > 0,
    }

    # 白点改善 (Duv)
    before_duv = abs(before_data.get("white_point", {}).get("duv", 0.0))
    after_duv = abs(after_data.get("white_point", {}).get("duv", 0.0))
    duv_improvement = before_duv - after_duv
    comparison["improvements"]["white_point_duv"] = {
        "before": before_duv,
        "after": after_duv,
        "improvement": duv_improvement,
        "improved": duv_improvement > 0,
    }

    # Gamma 改善
    before_gamma_offset = abs(before_data.get("gamma", 2.2) - 2.2)
    after_gamma_offset = abs(after_data.get("gamma", 2.2) - 2.2)
    gamma_improvement = before_gamma_offset - after_gamma_offset
    comparison["improvements"]["gamma_offset"] = {
        "before": before_gamma_offset,
        "after": after_gamma_offset,
        "improvement": gamma_improvement,
        "improved": gamma_improvement > 0,
    }

    # 色域覆盖率改善
    before_coverage = before_data.get("gamut_coverage", 0.0)
    after_coverage = after_data.get("gamut_coverage", 0.0)
    coverage_improvement = after_coverage - before_coverage
    comparison["improvements"]["gamut_coverage"] = {
        "before": before_coverage,
        "after": after_coverage,
        "improvement": coverage_improvement,
        "improved": coverage_improvement > 0,
    }

    # 对比度改善
    before_contrast = before_data.get("contrast_ratio", 1000.0)
    after_contrast = after_data.get("contrast_ratio", 1000.0)
    contrast_improvement = after_contrast - before_contrast
    comparison["improvements"]["contrast_ratio"] = {
        "before": before_contrast,
        "after": after_contrast,
        "improvement": contrast_improvement,
        "improved": contrast_improvement > 0,
    }

    # 综合改善评分
    improvements = [
        comparison["improvements"]["delta_e_avg"]["improved"],
        comparison["improvements"]["white_point_duv"]["improved"],
        comparison["improvements"]["gamma_offset"]["improved"],
        comparison["improvements"]["gamut_coverage"]["improved"],
        comparison["improvements"]["contrast_ratio"]["improved"],
    ]
    improved_count = sum(improvements)
    comparison["overall_improvement_count"] = improved_count

    # 生成建议
    if improved_count >= 5:
        comparison["recommendation"] = "校准效果优秀，所有指标均有改善"
    elif improved_count >= 4:
        comparison["recommendation"] = "校准效果良好，大部分指标改善"
    elif improved_count >= 3:
        comparison["recommendation"] = "校准效果中等，部分指标改善"
    elif improved_count >= 2:
        comparison["recommendation"] = "校准效果一般，建议检查校准流程"
    else:
        comparison["recommendation"] = "校准效果不佳，建议重新校准或检查设备"

    return comparison


def generate_validation_report(
    run_data: Dict,
    threshold: Optional[Dict] = None,
    target_standard: str = "sRGB"
) -> Dict:
    """
    生成验证报告

    Args:
        run_data: 运行数据
            {"gamut_data": {...}, "grayscale_data": [...], "verification_points": [...], ...}
        threshold: 验证阈值 (默认使用标准阈值)
        target_standard: 目标标准

    Returns:
        Dict: 验证报告
    """
    # 使用默认阈值
    if threshold is None:
        threshold = {
            "delta_e_avg": 2.0,
            "delta_e_max": 6.0,
            "white_point_cct_tolerance": 200.0,
            "white_point_duv_tolerance": 0.005,
            "gamma_tolerance": 0.05,
            "gamut_coverage_threshold": 95.0,
        }

    report = {
        "target_standard": target_standard,
        "threshold": threshold,
        "metrics": {},
        "validation": {},
        "summary": {},
    }

    # 计算 Delta E 统计
    verification_points = run_data.get("verification_points", [])
    delta_e_stats = calculate_validation_delta_e_statistics(verification_points, target_standard)
    report["metrics"]["delta_e"] = delta_e_stats

    # Delta E 验证
    delta_e_avg = delta_e_stats["delta_e_avg"]
    delta_e_max = delta_e_stats["delta_e_max"]
    delta_e_passed = (delta_e_avg <= threshold["delta_e_avg"] and
                      delta_e_max <= threshold["delta_e_max"])
    report["validation"]["delta_e"] = {
        "passed": delta_e_passed,
        "avg": delta_e_avg,
        "max": delta_e_max,
        "threshold_avg": threshold["delta_e_avg"],
        "threshold_max": threshold["delta_e_max"],
    }

    # 白点验证
    white_point = run_data.get("white_point", {})
    cct = white_point.get("cct", 6500.0)
    duv = white_point.get("duv", 0.0)
    cct_offset = cct - 6500.0
    white_passed = (abs(cct_offset) <= threshold["white_point_cct_tolerance"] and
                    abs(duv) <= threshold["white_point_duv_tolerance"])
    report["metrics"]["white_point"] = white_point
    report["validation"]["white_point"] = {
        "passed": white_passed,
        "cct": cct,
        "cct_offset": cct_offset,
        "duv": duv,
        "threshold_cct": threshold["white_point_cct_tolerance"],
        "threshold_duv": threshold["white_point_duv_tolerance"],
    }

    # Gamma 验证
    gamma = run_data.get("gamma", 2.2)
    gamma_offset = abs(gamma - 2.2)
    gamma_passed = gamma_offset <= threshold["gamma_tolerance"]
    report["metrics"]["gamma"] = gamma
    report["validation"]["gamma"] = {
        "passed": gamma_passed,
        "gamma": gamma,
        "offset": gamma_offset,
        "threshold": threshold["gamma_tolerance"],
    }

    # 色域验证
    gamut_coverage = run_data.get("gamut_coverage", 0.0)
    gamut_passed = gamut_coverage >= threshold["gamut_coverage_threshold"]
    report["metrics"]["gamut_coverage"] = gamut_coverage
    report["validation"]["gamut"] = {
        "passed": gamut_passed,
        "coverage": gamut_coverage,
        "threshold": threshold["gamut_coverage_threshold"],
    }

    # 亮度验证
    peak_luminance = run_data.get("peak_luminance", 100.0)
    black_luminance = run_data.get("black_luminance", 0.0)
    contrast_ratio = peak_luminance / black_luminance if black_luminance > 0 else 0
    report["metrics"]["luminance"] = {
        "peak": peak_luminance,
        "black": black_luminance,
        "contrast_ratio": contrast_ratio,
    }

    # 综合验证
    all_validations = [
        report["validation"]["delta_e"]["passed"],
        report["validation"]["white_point"]["passed"],
        report["validation"]["gamma"]["passed"],
        report["validation"]["gamut"]["passed"],
    ]
    passed_count = sum(all_validations)

    if passed_count == len(all_validations):
        overall_status = "PASSED"
        overall_summary = "所有验证指标合格，校准效果优秀"
    elif passed_count >= len(all_validations) - 1:
        overall_status = "WARNING"
        overall_summary = f"{passed_count}/{len(all_validations)} 项合格，有轻微问题"
    else:
        overall_status = "FAILED"
        overall_summary = f"仅 {passed_count}/{len(all_validations)} 项合格，需要重新校准"

    report["summary"] = {
        "status": overall_status,
        "passed_count": passed_count,
        "total_count": len(all_validations),
        "summary_text": overall_summary,
    }

    return report
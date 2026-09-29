"""
色域计算与采样策略 - xy 多边形交集、覆盖率、面积、容积、色块采样

本模块实现：
    - xy 平面上的多边形面积计算
    - Sutherland-Hodgman 多边形裁剪（精确交集面积）
    - 色域覆盖率 vs 面积比计算
    - RGB/Lab 空间色块采样策略
"""

import math
from typing import Tuple, List, Dict, Optional, Set
from enum import Enum
from dataclasses import dataclass

from .spaces import (
    srgb_to_xyz,
    xyz_to_srgb,
    xyz_to_lab,
    lab_to_xyz,
    rgb_to_lab,
    lab_to_rgb,
    COLOR_SPACES,
    get_white_point_xy,
)


# ==============================================================================
# 多边形基础运算
# ==============================================================================

def polygon_area(vertices: List[Tuple[float, float]]) -> float:
    """
    计算多边形面积（使用叉积公式 / Shoelace formula）
    
    Area = 0.5 * |Σ(xi * yi+1 - xi+1 * yi)|
    
    Args:
        vertices: 多边形顶点列表 [(x1, y1), (x2, y2), ...]
        
    Returns:
        float: 多边形面积
    """
    if len(vertices) < 3:
        return 0.0
    
    n = len(vertices)
    area = 0.0
    
    for i in range(n):
        j = (i + 1) % n
        x_i, y_i = vertices[i]
        x_j, y_j = vertices[j]
        area += x_i * y_j - x_j * y_i
    
    return abs(area) / 2.0


def polygon_centroid(vertices: List[Tuple[float, float]]) -> Tuple[float, float]:
    """
    计算多边形中心
    
    Args:
        vertices: 多边形顶点列表
        
    Returns:
        Tuple[float, float]: (cx, cy) 中心坐标
    """
    if len(vertices) < 3:
        if len(vertices) == 0:
            return (0.0, 0.0)
        return (sum(v[0] for v in vertices) / len(vertices),
                sum(v[1] for v in vertices) / len(vertices))
    
    n = len(vertices)
    cx = 0.0
    cy = 0.0
    area = 0.0
    
    for i in range(n):
        j = (i + 1) % n
        x_i, y_i = vertices[i]
        x_j, y_j = vertices[j]
        cross = x_i * y_j - x_j * y_i
        area += cross
        cx += (x_i + x_j) * cross
        cy += (y_i + y_j) * cross
    
    area = abs(area) / 2.0
    
    if area == 0:
        return (sum(v[0] for v in vertices) / n,
                sum(v[1] for v in vertices) / n)
    
    cx /= (6.0 * area)
    cy /= (6.0 * area)
    
    return (cx, cy)


def point_in_polygon(point: Tuple[float, float], vertices: List[Tuple[float, float]]) -> bool:
    """
    判断点是否在多边形内
    
    使用射线法（Ray casting algorithm）
    
    Args:
        point: 要判断的点 (x, y)
        vertices: 多边形顶点
        
    Returns:
        bool: 是否在多边形内
    """
    x, y = point
    n = len(vertices)
    
    if n < 3:
        return False
    
    inside = False
    
    j = n - 1
    for i in range(n):
        xi, yi = vertices[i]
        xj, yj = vertices[j]
        
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        
        j = i
    
    return inside


# ==============================================================================
# Sutherland-Hodgman 多边形裁剪
# ==============================================================================

def clip_polygon_by_edge(
    vertices: List[Tuple[float, float]],
    edge_start: Tuple[float, float],
    edge_end: Tuple[float, float]
) -> List[Tuple[float, float]]:
    """
    使用一条边裁剪多边形
    
    Sutherland-Hodgman 算法的单步
    
    Args:
        vertices: 输入多边形顶点
        edge_start: 边的起点
        edge_end: 边的终点
        
    Returns:
        List[Tuple[float, float]]: 裁剪后的顶点
    """
    def is_inside(p: Tuple[float, float], edge_start: Tuple[float, float], edge_end: Tuple[float, float]) -> bool:
        """判断点是否在边的内侧"""
        # 边的方向向量
        edge_dx = edge_end[0] - edge_start[0]
        edge_dy = edge_end[1] - edge_start[1]
        
        # 点相对于边起点
        px = p[0] - edge_start[0]
        py = p[1] - edge_start[1]
        
        # 使用叉积判断（内侧为正或负取决于多边形方向）
        cross = edge_dx * py - edge_dy * px
        
        return cross >= 0
    
    def intersection(
        p1: Tuple[float, float], p2: Tuple[float, float],
        edge_start: Tuple[float, float], edge_end: Tuple[float, float]
    ) -> Tuple[float, float]:
        """计算边与边的交点"""
        # 边 1: p1 -> p2
        # 边 2: edge_start -> edge_end
        
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = edge_start
        x4, y4 = edge_end
        
        # 参数方程求交
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        
        if abs(denom) < 1e-10:
            # 平行，返回中点
            return ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        
        x = x1 + t * (x2 - x1)
        y = y1 + t * (y2 - y1)
        
        return (x, y)
    
    if len(vertices) < 3:
        return vertices
    
    output = []
    n = len(vertices)
    
    for i in range(n):
        current = vertices[i]
        previous = vertices[(i - 1) % n]
        
        current_inside = is_inside(current, edge_start, edge_end)
        previous_inside = is_inside(previous, edge_start, edge_end)
        
        if current_inside:
            if not previous_inside:
                # 进入裁剪区域，添加交点
                inter = intersection(previous, current, edge_start, edge_end)
                output.append(inter)
            output.append(current)
        elif previous_inside:
            # 离开裁剪区域，添加交点
            inter = intersection(previous, current, edge_start, edge_end)
            output.append(inter)
    
    return output


def polygon_intersection(
    polygon1: List[Tuple[float, float]],
    polygon2: List[Tuple[float, float]]
) -> List[Tuple[float, float]]:
    """
    计算两个多边形的交集
    
    使用 Sutherland-Hodgman 算法
    
    Args:
        polygon1: 被裁剪多边形（主体）
        polygon2: 裁剪多边形（裁剪窗口）
        
    Returns:
        List[Tuple[float, float]]: 交集多边形顶点
    """
    result = polygon1.copy()
    
    n = len(polygon2)
    for i in range(n):
        edge_start = polygon2[i]
        edge_end = polygon2[(i + 1) % n]
        
        result = clip_polygon_by_edge(result, edge_start, edge_end)
        
        if len(result) < 3:
            return []  # 无交集
    
    return result


def polygon_intersection_area(
    polygon1: List[Tuple[float, float]],
    polygon2: List[Tuple[float, float]]
) -> float:
    """
    计算两个多边形交集的面积
    
    Args:
        polygon1: 第一个多边形
        polygon2: 第二个多边形
        
    Returns:
        float: 交集面积
    """
    intersection_polygon = polygon_intersection(polygon1, polygon2)
    
    if len(intersection_polygon) < 3:
        return 0.0
    
    return polygon_area(intersection_polygon)


# ==============================================================================
# 色域计算
# ==============================================================================

def get_gamut_vertices(color_space: str) -> List[Tuple[float, float]]:
    """
    获取色彩空间在 xy 平面的顶点

    Args:
        color_space: 色彩空间名称（支持别名，如 "DCI-P3" -> "DCI_P3"）

    Returns:
        List[Tuple[float, float]]: [(x_r, y_r), (x_g, y_g), (x_b, y_b)]
    """
    from .spaces import normalize_color_space_name

    try:
        normalized = normalize_color_space_name(color_space)
    except KeyError:
        raise KeyError(f"未知的色彩空间: {color_space}")

    cs = COLOR_SPACES[normalized]

    return [
        cs["red"],
        cs["green"],
        cs["blue"],
    ]


def polygon_vertices_from_rgbw(
    red: Dict, green: Dict, blue: Dict, white: Optional[Dict] = None
) -> List[Tuple[float, float]]:
    """
    从 RGBW 测量数据构建色域多边形
    
    Args:
        red: {"x": ..., "y": ...}
        green: {"x": ..., "y": ...}
        blue: {"x": ..., "y": ...}
        white: {"x": ..., "y": ...}（可选，用于验证）
        
    Returns:
        List[Tuple[float, float]]: 色域三角形顶点
    """
    vertices = [
        (red["x"], red["y"]),
        (green["x"], green["y"]),
        (blue["x"], blue["y"]),
    ]
    
    return vertices


def gamut_coverage_percent(
    measured_vertices: List[Tuple[float, float]],
    standard_vertices: List[Tuple[float, float]]
) -> float:
    """
    计算色域覆盖率
    
    覆盖率 = 交集面积 / 标准色域面积 * 100
    
    表示测量色域覆盖了标准色域的多少百分比
    最大值为 100%（即使测量色域更大）
    
    Args:
        measured_vertices: 测量色域顶点
        standard_vertices: 标准色域顶点
        
    Returns:
        float: 覆盖率百分比 (0-100)
    """
    intersection_area = polygon_intersection_area(measured_vertices, standard_vertices)
    standard_area = polygon_area(standard_vertices)
    
    if standard_area == 0:
        return 0.0
    
    coverage = (intersection_area / standard_area) * 100.0
    
    return min(100.0, max(0.0, coverage))


def gamut_area_ratio(
    measured_vertices: List[Tuple[float, float]],
    standard_vertices: List[Tuple[float, float]]
) -> float:
    """
    计算色域面积比
    
    面积比 = 测量面积 / 标准面积 * 100
    
    表示测量色域相对于标准色域的大小
    可以大于 100%（表示测量色域更大）
    
    Args:
        measured_vertices: 测量色域顶点
        standard_vertices: 标准色域顶点
        
    Returns:
        float: 面积比百分比 (可 > 100)
    """
    measured_area = polygon_area(measured_vertices)
    standard_area = polygon_area(standard_vertices)
    
    if standard_area == 0:
        return 0.0
    
    ratio = (measured_area / standard_area) * 100.0
    
    return max(0.0, ratio)


def gamut_metrics(
    measured_vertices: List[Tuple[float, float]],
    standard: str = "sRGB"
) -> Dict:
    """
    计算完整的色域指标
    
    Args:
        measured_vertices: 测量色域顶点
        standard: 标准色域名称
        
    Returns:
        Dict: 色域指标
            - coverage_percent: 覆盖率 (0-100)
            - area_ratio_percent: 面积比 (可 > 100)
            - measured_area: 测量面积
            - standard_area: 标准面积
            - intersection_area: 交集面积
    """
    standard_vertices = get_gamut_vertices(standard)
    
    measured_area = polygon_area(measured_vertices)
    standard_area = polygon_area(standard_vertices)
    intersection_area = polygon_intersection_area(measured_vertices, standard_vertices)
    
    coverage_percent = 0.0 if standard_area == 0 else (intersection_area / standard_area) * 100.0
    area_ratio_percent = 0.0 if standard_area == 0 else (measured_area / standard_area) * 100.0
    
    return {
        "coverage_percent": min(100.0, coverage_percent),
        "area_ratio_percent": area_ratio_percent,
        "measured_area": measured_area,
        "standard_area": standard_area,
        "intersection_area": intersection_area,
        "standard": standard,
    }


# ==============================================================================
# RGB/Lab 边界计算
# ==============================================================================

# 预计算的 sRGB Lab 边界缓存
_SRGB_LAB_BOUNDARY_CACHE: Dict[float, Dict] = {}

# 端点 epsilon：与 Lab/RGB 转换误差一致
_LAB_BOUNDARY_EPSILON = 0.01


def get_srgb_lab_boundary_for_L(L: float, use_cache: bool = True) -> Dict:
    """
    计算给定 L* 值下 sRGB 色域的边界

    通过遍历 RGB 立方体的边界点，找到每个 L* 对应的 a*b* 范围。
    
    特殊处理端点：
        - 当 L <= epsilon 时，边界退化到黑点附近 (a≈0, b≈0)
        - 当 L >= 100 - epsilon 时，边界退化到白点附近 (a≈0, b≈0)

    Args:
        L: 亮度值 (0-100)
        use_cache: 是否使用缓存（默认 True）

    Returns:
        Dict: 边界信息
            - a_min, a_max: a* 范围
            - b_min, b_max: b* 范围
            - boundary_points: 边界上的 Lab 点（端点时为空）
            - in_gamut: 是否在色域内
    """
    global _SRGB_LAB_BOUNDARY_CACHE
    
    # 端点特殊处理：L <= epsilon 或 L >= 100 - epsilon
    # 此时边界退化到黑点或白点附近，a* 和 b* 接近 0
    if L <= _LAB_BOUNDARY_EPSILON:
        # 黑点：RGB(0,0,0) -> Lab(0, 0, 0)
        # 由于 Lab/RGB 转换有精度误差，允许小范围波动
        return {
            "L": L,
            "a_min": -0.5,
            "a_max": 0.5,
            "b_min": -0.5,
            "b_max": 0.5,
            "boundary_points": [(0.0, 0.0)],
            "in_gamut": True,
        }
    
    if L >= 100.0 - _LAB_BOUNDARY_EPSILON:
        # 白点：RGB(255,255,255) -> Lab(100, 0, 0)
        return {
            "L": L,
            "a_min": -0.5,
            "a_max": 0.5,
            "b_min": -0.5,
            "b_max": 0.5,
            "boundary_points": [(0.0, 0.0)],
            "in_gamut": True,
        }
    
    # 检查缓存
    L_key = round(L, 1)  # 缓存键：精确到 0.1
    if use_cache and L_key in _SRGB_LAB_BOUNDARY_CACHE:
        cached = _SRGB_LAB_BOUNDARY_CACHE[L_key]
        # 返回缓存结果，但更新 L 值
        return {
            "L": L,
            "a_min": cached["a_min"],
            "a_max": cached["a_max"],
            "b_min": cached["b_min"],
            "b_max": cached["b_max"],
            "boundary_points": cached["boundary_points"],
            "in_gamut": cached["in_gamut"],
        }
    
    # 边界采样：RGB 立方体的 6 个面
    # 使用更高效的采样策略：减少采样点数，依赖缓存
    
    boundary_points = []
    
    # 采样步数：平衡精度与性能
    # 128 步足以覆盖色域边界，且性能较好
    steps = 64  # 从 256 降至 64，性能提升 4x

    # 6 个面
    faces = [
        # R = 0, G 和 B 变化
        lambda s, t: (0, int(s * 255), int(t * 255)),
        # R = 255
        lambda s, t: (255, int(s * 255), int(t * 255)),
        # G = 0
        lambda s, t: (int(s * 255), 0, int(t * 255)),
        # G = 255
        lambda s, t: (int(s * 255), 255, int(t * 255)),
        # B = 0
        lambda s, t: (int(s * 255), int(t * 255), 0),
        # B = 255
        lambda s, t: (int(s * 255), int(t * 255), 255),
    ]

    # 找到接近目标 L 的点
    L_tolerance = 2.0  # L* 容差
    
    a_min = float('inf')
    a_max = float('-inf')
    b_min = float('inf')
    b_max = float('-inf')
    
    filtered_points = []

    for face in faces:
        for s in range(steps):
            s_ratio = s / (steps - 1)
            for t in range(steps):
                t_ratio = t / (steps - 1)
                rgb = face(s_ratio, t_ratio)
                X, Y, Z = srgb_to_xyz(rgb[0], rgb[1], rgb[2])
                lab_L, lab_a, lab_b = xyz_to_lab(X, Y, Z)
                
                if abs(lab_L - L) < L_tolerance:
                    filtered_points.append((lab_a, lab_b))
                    a_min = min(a_min, lab_a)
                    a_max = max(a_max, lab_a)
                    b_min = min(b_min, lab_b)
                    b_max = max(b_max, lab_b)

    if not filtered_points:
        # 该 L* 值不在 sRGB 色域内
        result = {
            "L": L,
            "a_min": 0.0,
            "a_max": 0.0,
            "b_min": 0.0,
            "b_max": 0.0,
            "boundary_points": [],
            "in_gamut": False,
        }
    else:
        result = {
            "L": L,
            "a_min": a_min,
            "a_max": a_max,
            "b_min": b_min,
            "b_max": b_max,
            "boundary_points": filtered_points,
            "in_gamut": True,
        }
    
    # 缓存结果
    if use_cache:
        _SRGB_LAB_BOUNDARY_CACHE[L_key] = result
    
    return result


def is_in_srgb_gamut(L: float, a: float, b: float) -> bool:
    """
    判断 Lab 值是否在 sRGB 色域内

    Args:
        L, a, b: Lab 值

    Returns:
        bool: 是否在色域内
    """
    # 转换到 XYZ
    X, Y, Z = lab_to_xyz(L, a, b, "D65")

    # 转换到 sRGB（线性）
    # 使用 spaces.py 的 xyz_to_rgb
    r, g, b_rgb = lab_to_rgb(L, a, b, "sRGB", "D65")

    # 检查是否在 0-1 范围
    # 注意：由于浮点精度问题，允许小的误差（epsilon = 1e-6）
    epsilon = 1e-6
    return -epsilon <= r <= 1.0 + epsilon and \
           -epsilon <= g <= 1.0 + epsilon and \
           -epsilon <= b_rgb <= 1.0 + epsilon


# ==============================================================================
# 采样策略
# ==============================================================================

class SamplingStrategy(Enum):
    """采样策略枚举"""
    FAST_VALIDATION = "fast_validation"     # 快速验证（~100 色块）
    ICC_STANDARD = "icc_standard"           # ICC 标准（~500 色块）
    LUT_HIGH_PRECISION = "lut_high_precision"  # LUT 高精度（~1500 色块）
    DARK_PRIORITY = "dark_priority"         # 暗部优先
    SKIN_TONE_PRIORITY = "skin_tone_priority"  # 肤色优先
    GRAY_SCALE = "gray_scale"               # 灰阶优先
    UNIFORM = "uniform"                     # 均匀分布


@dataclass
class PatchInfo:
    """色块信息"""
    sample_id: str
    rgb: Tuple[int, int, int]
    lab: Tuple[float, float, float]
    purpose: str
    priority: int  # 1-5，越高越重要


class GamutSampler:
    """
    sRGB 色域采样器
    
    实现：
        1. 在 RGB 空间采样（避免超色域）
        2. 转换到 Lab 空间
        3. 多种采样策略
        4. 去重机制
    """
    
    # 基础色块（必须包含）
    BASIC_PATCHES = [
        (255, 0, 0),    # 红
        (0, 255, 0),    # 绿
        (0, 0, 255),    # 蓝
        (255, 255, 255),  # 白
        (0, 0, 0),      # 黑
        (255, 255, 0),  # 黄
        (255, 0, 255),  # 紫
        (0, 255, 255),  # 青
    ]
    
    # 灰阶色块
    GRAY_PATCHES = [
        (13, 13, 13),   # 5%
        (25, 25, 25),   # 10%
        (38, 38, 38),   # 15%
        (51, 51, 51),   # 20%
        (64, 64, 64),   # 25%
        (76, 76, 76),   # 30%
        (89, 89, 89),   # 35%
        (102, 102, 102),  # 40%
        (115, 115, 115),  # 45%
        (128, 128, 128),  # 50%
        (141, 141, 141),  # 55%
        (153, 153, 153),  # 60%
        (166, 166, 166),  # 65%
        (179, 179, 179),  # 70%
        (192, 192, 192),  # 75%
        (204, 204, 204),  # 80%
        (217, 217, 217),  # 85%
        (230, 230, 230),  # 90%
        (242, 242, 242),  # 95%
    ]
    
    def __init__(self, strategy: SamplingStrategy = SamplingStrategy.ICC_STANDARD):
        """
        初始化采样器
        
        Args:
            strategy: 采样策略
        """
        self.strategy = strategy
        self._patches: List[PatchInfo] = []
        self._seen_rgb: Set[Tuple[int, int, int]] = set()
    
    def generate_patches(self, count: Optional[int] = None) -> List[PatchInfo]:
        """
        生成色块列表
        
        Args:
            count: 色块数量（如果不指定，使用策略默认值）
            
        Returns:
            List[PatchInfo]: 色块信息列表
        """
        if count is None:
            count = self._get_default_count()
        
        self._patches = []
        self._seen_rgb = set()
        
        # 添加基础色块
        self._add_basic_patches()
        
        # 添加灰阶色块
        self._add_gray_patches()
        
        # 根据策略添加其他色块
        remaining = count - len(self._patches)
        
        if remaining > 0:
            self._add_strategy_patches(remaining)
        
        return self._patches
    
    def _get_default_count(self) -> int:
        """获取策略默认色块数量"""
        defaults = {
            SamplingStrategy.FAST_VALIDATION: 100,
            SamplingStrategy.ICC_STANDARD: 500,
            SamplingStrategy.LUT_HIGH_PRECISION: 1500,
            SamplingStrategy.DARK_PRIORITY: 300,
            SamplingStrategy.SKIN_TONE_PRIORITY: 400,
            SamplingStrategy.GRAY_SCALE: 50,
            SamplingStrategy.UNIFORM: 500,
        }
        return defaults.get(self.strategy, 500)
    
    def _add_patch(self, rgb: Tuple[int, int, int], purpose: str, priority: int) -> bool:
        """添加色块（如果未重复）"""
        rgb_tuple = (rgb[0], rgb[1], rgb[2])
        
        if rgb_tuple in self._seen_rgb:
            return False
        
        # 计算 Lab
        X, Y, Z = srgb_to_xyz(rgb[0], rgb[1], rgb[2])
        L, a, b = xyz_to_lab(X, Y, Z)
        
        sample_id = f"P{len(self._patches) + 1:04d}"
        
        patch = PatchInfo(
            sample_id=sample_id,
            rgb=rgb_tuple,
            lab=(L, a, b),
            purpose=purpose,
            priority=priority
        )
        
        self._patches.append(patch)
        self._seen_rgb.add(rgb_tuple)
        
        return True
    
    def _add_basic_patches(self):
        """添加基础色块"""
        purposes = ["primary_red", "primary_green", "primary_blue",
                   "white", "black", "secondary_yellow", "secondary_magenta", "secondary_cyan"]
        
        for i, rgb in enumerate(self.BASIC_PATCHES):
            self._add_patch(rgb, purposes[i], 5)
    
    def _add_gray_patches(self):
        """添加灰阶色块"""
        for i, rgb in enumerate(self.GRAY_PATCHES):
            percent = (i + 1) * 5
            purpose = f"gray_{percent}%"
            priority = 4 if percent <= 20 else 3  # 暗部灰阶优先级更高
            self._add_patch(rgb, purpose, priority)
    
    def _add_strategy_patches(self, count: int):
        """根据策略添加色块
        
        所有策略使用高效的 RGB 空间采样，避免慢速的 Lab→RGB 转换。
        LUT_HIGH_PRECISION 策略使用预计算的 RGB 网格采样。
        
        性能要求：1500 色块生成应在 5 秒内完成。
        """
        if self.strategy == SamplingStrategy.DARK_PRIORITY:
            self._add_dark_patches_rgb(int(count))
        elif self.strategy == SamplingStrategy.SKIN_TONE_PRIORITY:
            self._add_skin_tone_patches_rgb(int(count))
        elif self.strategy == SamplingStrategy.GRAY_SCALE:
            # 灰阶已在基础中添加，这里添加精细灰阶
            self._add_fine_gray_patches(int(count))
        elif self.strategy == SamplingStrategy.LUT_HIGH_PRECISION:
            # LUT 高精度：使用 RGB 网格采样，避免 Lab 空间转换
            self._add_lut_high_precision_patches(int(count))
        elif self.strategy == SamplingStrategy.UNIFORM:
            self._add_uniform_patches(int(count))
        else:
            # 默认策略（ICC_STANDARD 等）：使用 RGB 采样
            self._add_dark_patches_rgb(int(count * 0.3))
            self._add_saturation_patches_rgb(int(count * 0.3))
            self._add_uniform_patches(int(count * 0.4))
    

    def _add_lut_high_precision_patches(self, count: int):
        """LUT 高精度策略：使用 RGB 网格采样
        
        特点：
        - 纯 RGB 空间采样，无 Lab→RGB 转换
        - 非线性分布增加暗部密度
        - 明确的上限控制
        
        性能目标：1500 色块在 2 秒内完成
        
        Args:
            count: 目标色块数量
            
        Returns:
            int: 实际添加数量
        """
        if count <= 0:
            return 0
        
        added = 0
        max_attempts = count * 3
        target_total = count + len(self.BASIC_PATCHES) + len(self.GRAY_PATCHES)
        
        # 第一阶段：暗部采样（非线性分布）
        for r in range(0, 121, 20):
            for g in range(0, 121, 20):
                for b in range(0, 121, 20):
                    if added >= max_attempts or len(self._patches) >= target_total:
                        break
                    if abs(r - g) < 12 and abs(g - b) < 12:
                        continue
                    rgb = (r, g, b)
                    if self._add_patch(rgb, "lut_dark", 4):
                        added += 1
        
        # 第二阶段：中间调采样
        for r in range(120, 221, 25):
            for g in range(120, 221, 25):
                for b in range(120, 221, 25):
                    if added >= max_attempts or len(self._patches) >= target_total:
                        break
                    rgb = (r, g, b)
                    if self._add_patch(rgb, "lut_mid", 2):
                        added += 1
        
        # 第三阶段：高饱和采样（边界点）
        saturation_configs = [
            [(255, 0, 0), (200, 30, 30), (150, 50, 50)],
            [(0, 255, 0), (30, 200, 30), (50, 150, 50)],
            [(0, 0, 255), (30, 30, 200), (50, 50, 150)],
            [(255, 255, 0), (200, 200, 30), (150, 150, 50)],
            [(255, 0, 255), (200, 30, 200), (150, 50, 150)],
            [(0, 255, 255), (30, 200, 200), (50, 150, 150)],
        ]
        purposes = ["lut_red", "lut_green", "lut_blue", "lut_yellow", "lut_magenta", "lut_cyan"]
        
        for config_idx, config in enumerate(saturation_configs):
            for rgb in config:
                if added >= max_attempts or len(self._patches) >= target_total:
                    break
                if self._add_patch(rgb, purposes[config_idx], 3):
                    added += 1
        
        # 第四阶段：填充剩余空间
        remaining = target_total - len(self._patches)
        if remaining > 0:
            fill_step = max(15, int(255 / math.sqrt(remaining)))
            for r in range(0, 256, fill_step):
                for g in range(0, 256, fill_step):
                    for b in range(0, 256, fill_step):
                        if added >= max_attempts or len(self._patches) >= target_total:
                            break
                        rgb = (r, g, b)
                        if self._add_patch(rgb, "lut_fill", 1):
                            added += 1
        
        return added

    def _add_dark_patches_rgb(self, count: int):
        """暗部色块采样（纯 RGB 空间）
        
        Args:
            count: 目标色块数量
            
        Returns:
            int: 实际添加数量
        """
        if count <= 0:
            return 0
        
        max_rgb = 60
        added = 0
        max_attempts = count * 2
        target_total = count + 27
        
        step = max(3, int(math.pow(max_rgb * max_rgb * max_rgb / count, 1/3)))
        
        for r in range(0, max_rgb + 1, step):
            for g in range(0, max_rgb + 1, step):
                for b in range(0, max_rgb + 1, step):
                    if added >= max_attempts or len(self._patches) >= target_total:
                        return added
                    if abs(r - g) < 8 and abs(g - b) < 8:
                        continue
                    rgb = (r, g, b)
                    if self._add_patch(rgb, "dark_rgb", 4):
                        added += 1
        return added

    def _add_saturation_patches_rgb(self, count: int):
        """高饱和色块采样（纯 RGB 空间）
        
        Args:
            count: 目标色块数量
            
        Returns:
            int: 实际添加数量
        """
        if count <= 0:
            return 0
        
        added = 0
        max_attempts = count * 2
        target_total = count + 27
        
        for channel in range(3):
            for high_val in range(200, 256, 8):
                for low_val in range(0, 60, 12):
                    if added >= max_attempts or len(self._patches) >= target_total:
                        return added
                    if channel == 0:
                        rgb = (high_val, low_val, low_val)
                    elif channel == 1:
                        rgb = (low_val, high_val, low_val)
                    else:
                        rgb = (low_val, low_val, high_val)
                    if self._add_patch(rgb, "primary_saturation", 3):
                        added += 1
        
        for combo in [(0, 1), (0, 2), (1, 2)]:
            for high_val in range(180, 256, 12):
                for low_val in range(0, 50, 15):
                    if added >= max_attempts or len(self._patches) >= target_total:
                        return added
                    rgb = [low_val, low_val, low_val]
                    rgb[combo[0]] = high_val
                    rgb[combo[1]] = high_val
                    purpose = "yellow_saturation" if combo == (0, 1) else "magenta_saturation" if combo == (0, 2) else "cyan_saturation"
                    if self._add_patch(tuple(rgb), purpose, 3):
                        added += 1
        return added

    def _add_skin_tone_patches_rgb(self, count: int):
        """肤色色块采样（纯 RGB 空间）
        
        Args:
            count: 目标色块数量
            
        Returns:
            int: 实际添加数量
        """
        if count <= 0:
            return 0
        
        added = 0
        max_attempts = count * 2
        target_total = count + 27
        
        for r in range(150, 256, 8):
            for g in range(100, min(r, 201), 8):
                for b in range(80, min(g, 181), 8):
                    if added >= max_attempts or len(self._patches) >= target_total:
                        return added
                    if not (r >= g >= b):
                        continue
                    if r - g < 10 or g - b < 5:
                        continue
                    rgb = (r, g, b)
                    if self._add_patch(rgb, "skin_tone", 4):
                        added += 1
        return added
    def _add_dark_patches(self, count: int):
        """添加暗部色块（L* < 20 区域）

        使用 RGB 空间直接采样，避免 Lab→RGB 转换导致的重复色块问题。
        """
        # 暗部区域：RGB 值在 0-60 范围
        max_rgb = 60

        # 计算采样密度（确保覆盖且不重复）
        step = max(1, int(math.sqrt(max_rgb * max_rgb * max_rgb / max(count, 1))))

        added = 0
        for r in range(0, max_rgb + 1, step):
            for g in range(0, max_rgb + 1, step):
                for b_rgb in range(0, max_rgb + 1, step):
                    if added >= count:
                        return added

                    # 跳过灰阶（已单独添加）
                    if abs(r - g) < 8 and abs(g - b_rgb) < 8:
                        continue

                    rgb = (r, g, b_rgb)
                    if self._add_patch(rgb, "dark", 4):
                        added += 1

        # 补充：使用 Lab 空间采样增加多样性
        remaining = count - added
        if remaining > 0:
            L_values = [3, 5, 8, 10, 12, 15, 18]
            patches_per_L = max(1, remaining // len(L_values))

            for L in L_values:
                # 暗部色域半径约 L * 0.15（精确值来自色域边界）
                max_radius = L * 0.15
                angles = patches_per_L

                for angle_idx in range(angles):
                    angle = angle_idx * 360 / angles
                    a = max_radius * math.cos(math.radians(angle))
                    b_val = max_radius * math.sin(math.radians(angle))

                    # Lab → XYZ → RGB（正确参数范围）
                    X, Y, Z = lab_to_xyz(L, a, b_val, "D65")
                    rgb = xyz_to_srgb(X, Y, Z)  # xyz_to_srgb 接受 Y 范围 0-100
                    self._add_patch(rgb, f"dark_L{L}", 4)

        return added
    
    def _add_saturation_patches(self, count: int):
        """添加高饱和色块（接近色域边界）

        使用 RGB 空间直接采样，优先选择高 RGB 值组合。
        """
        # 高饱和色块：至少一个 RGB 值接近 255，其他值较低
        if count <= 0:
            return

        added = 0

        # 采样策略：遍历高饱和 RGB 组合
        # 至少一个通道 > 200，至少一个通道 < 50

        # 原色附近（单通道高）
        for channel in range(3):  # R, G, B
            for high_val in range(200, 256, 5):
                for low_val in range(0, 60, 10):
                    if added >= count:
                        return

                    if channel == 0:  # 红色系
                        rgb = (high_val, low_val, low_val)
                    elif channel == 1:  # 绿色系
                        rgb = (low_val, high_val, low_val)
                    else:  # 蓝色系
                        rgb = (low_val, low_val, high_val)

                    if self._add_patch(rgb, "primary_saturation", 3):
                        added += 1

        # 二次色附近（两通道高）
        for combo in [(0, 1), (0, 2), (1, 2)]:  # 黄、紫、青
            for high_val in range(180, 256, 10):
                for low_val in range(0, 50, 15):
                    if added >= count:
                        return

                    rgb = [low_val, low_val, low_val]
                    rgb[combo[0]] = high_val
                    rgb[combo[1]] = high_val

                    if combo == (0, 1):
                        purpose = "yellow_saturation"
                    elif combo == (0, 2):
                        purpose = "magenta_saturation"
                    else:
                        purpose = "cyan_saturation"

                    if self._add_patch(tuple(rgb), purpose, 3):
                        added += 1

        # 补充：使用 Lab 空间采样色域边界
        remaining = count - added
        if remaining > 0:
            L_planes = [30, 50, 70]
            patches_per_L = max(1, remaining // len(L_planes))

            for L in L_planes:
                angles = patches_per_L

                for angle_idx in range(angles):
                    angle = angle_idx * 360 / angles

                    # 使用色域边界近似半径
                    boundary = get_srgb_lab_boundary_for_L(L)

                    if boundary["in_gamut"]:
                        max_a = boundary["a_max"]
                        max_b = boundary["b_max"]
                        min_a = boundary["a_min"]
                        min_b = boundary["b_min"]

                        # 椭圆采样，半径约 90%
                        a_range = max_a - min_a
                        b_range = max_b - min_b

                        a = min_a + a_range / 2 + 0.9 * a_range / 2 * math.cos(math.radians(angle))
                        b_val = min_b + b_range / 2 + 0.9 * b_range / 2 * math.sin(math.radians(angle))

                        # Lab → XYZ → RGB（正确参数范围）
                        X, Y, Z = lab_to_xyz(L, a, b_val, "D65")
                        rgb = xyz_to_srgb(X, Y, Z)
                        self._add_patch(rgb, f"saturation_L{L}", 3)
    
    def _add_skin_tone_patches(self, count: int):
        """添加肤色色块

        肤色区域：L* 40-70, a* 10-25, b* 10-30
        使用 RGB 空间直接采样避免重复。
        """
        if count <= 0:
            return

        # 肤色 RGB 范围近似：
        # R: 150-255（偏高）
        # G: 100-200（中等）
        # B: 80-180（偏低）
        # 形成暖色调

        added = 0

        # RGB 采样肤色区域
        for r in range(150, 256, 10):
            for g in range(100, 201, 10):
                for b_rgb in range(80, 181, 10):
                    if added >= count:
                        return

                    # 肤色特征：R > G > B（暖色调）
                    if not (r >= g >= b_rgb):
                        continue

                    # 检查是否形成合理的肤色色调
                    rg_diff = r - g
                    gb_diff = g - b_rgb
                    if rg_diff < 10 or gb_diff < 5:  # 需有足够差异形成暖色
                        continue

                    rgb = (r, g, b_rgb)
                    if self._add_patch(rgb, "skin_tone", 4):
                        added += 1

        # 补充：使用 Lab 空间采样
        remaining = count - added
        if remaining > 0:
            L_values = [40, 50, 60, 70]
            a_values = [10, 15, 20, 25]
            b_values = [15, 20, 25, 30]

            patches_per_grid = max(1, remaining // (len(L_values) * len(a_values) * len(b_values)))

            for L in L_values:
                for a in a_values:
                    for b_val in b_values:
                        # Lab → XYZ → RGB（正确参数范围）
                        X, Y, Z = lab_to_xyz(L, a, b_val, "D65")
                        rgb = xyz_to_srgb(X, Y, Z)
                        self._add_patch(rgb, "skin_tone_lab", 4)
    
    def _add_fine_gray_patches(self, count: int):
        """添加精细灰阶"""
        # 1% 步进的灰阶
        for percent in range(1, 100):
            if len(self._patches) >= count + len(self.GRAY_PATCHES) + len(self.BASIC_PATCHES):
                break
            
            gray_value = int(percent * 255 / 100)
            rgb = (gray_value, gray_value, gray_value)
            self._add_patch(rgb, f"gray_{percent}%_fine", 2)
    
    def _add_uniform_patches(self, count: int):
        """添加均匀分布色块"""
        if count <= 0:
            return

        # RGB 空间均匀采样 - 步数需平衡覆盖度和性能
        # 使用 sqrt(sqrt(count)) 确保步数合理
        steps = int(math.sqrt(math.sqrt(count))) + 3  # 平衡覆盖和性能

        added = 0
        for r_step in range(steps):
            for g_step in range(steps):
                for b_step in range(steps):
                    if added >= count:
                        return
                    
                    # 非线性分布（增加暗部密度）
                    r = int(255 * (r_step / (steps - 1)) ** 2)
                    g = int(255 * (g_step / (steps - 1)) ** 2)
                    b = int(255 * (b_step / (steps - 1)) ** 2)
                    
                    rgb = (r, g, b)
                    if self._add_patch(rgb, "uniform", 1):
                        added += 1
    
    def get_rgb_list(self) -> List[Tuple[int, int, int]]:
        """获取 RGB 列表"""
        return [p.rgb for p in self._patches]
    
    def get_lab_list(self) -> List[Tuple[float, float, float]]:
        """获取 Lab 列表"""
        return [p.lab for p in self._patches]
    
    def get_patch_dict_list(self) -> List[Dict]:
        """获取色块字典列表（兼容旧格式）"""
        return [
            {
                "sample_id": p.sample_id,
                "rgb": list(p.rgb),
                "lab": list(p.lab),
                "purpose": p.purpose,
                "priority": p.priority,
            }
            for p in self._patches
        ]


def generate_patch_list(
    count: int,
    strategy: SamplingStrategy = SamplingStrategy.ICC_STANDARD
) -> List[Dict]:
    """
    生成色块列表（便捷函数）
    
    Args:
        count: 色块数量
        strategy: 采样策略
        
    Returns:
        List[Dict]: 色块字典列表
    """
    sampler = GamutSampler(strategy)
    patches = sampler.generate_patches(count)
    return sampler.get_patch_dict_list()


# ==============================================================================
# 辅助函数
# ==============================================================================

def rgb_to_lab_for_sampler(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """
    8-bit RGB 到 Lab（便捷函数）
    
    Args:
        r, g, b: 0-255 RGB 值
        
    Returns:
        Tuple[float, float, float]: (L*, a*, b*)
    """
    X, Y, Z = srgb_to_xyz(r, g, b)
    return xyz_to_lab(X, Y, Z)


def lab_to_rgb_for_sampler(L: float, a: float, b: float) -> Tuple[int, int, int]:
    """
    Lab 到 8-bit RGB（便捷函数）

    Args:
        L, a, b: Lab 值

    Returns:
        Tuple[int, int, int]: 0-255 RGB 值
    """
    X, Y, Z = lab_to_xyz(L, a, b, "D65")
    # lab_to_xyz 返回的 XYZ 已经是 Y=100 范围，直接传递给 xyz_to_srgb
    return xyz_to_srgb(X, Y, Z)


def check_duplicate_rate(patches: List[Dict]) -> float:
    """
    检查色块列表的重复率
    
    Args:
        patches: 色块列表
        
    Returns:
        float: 重复率（0-1）
    """
    rgb_set = set()
    duplicates = 0
    
    for p in patches:
        rgb = tuple(p["rgb"])
        if rgb in rgb_set:
            duplicates += 1
        else:
            rgb_set.add(rgb)
    
    return duplicates / len(patches) if patches else 0.0
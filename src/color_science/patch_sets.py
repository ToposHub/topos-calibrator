"""
专业 Patch Set 引擎 - 为不同用途提供标准化的色块集合

本模块实现：
    - PatchPurpose: 色块用途枚举
    - Patch: 单个色块数据结构
    - PatchSet: 色块集合，支持多种导出格式
    - 预定义生成器：快速预检、灰阶、gamma ramp、ColorChecker、饱和度扫描、色相扫描、3D LUT cube、Adaptive

设计原则：
    - GamutSampler 只做算法采样，不负责 workflow 语义
    - PatchSet 负责业务语义（用途、预期时长、显示顺序等）
    - 所有生成器 deterministic（通过 seed 控制）
"""

import math
import random
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
import json

from .spaces import srgb_to_xyz, xyz_to_lab, lab_to_xyz, xyz_to_srgb


class PatchPurpose(Enum):
    """色块用途枚举"""
    # 基础色块
    PRIMARY = "primary"                    # RGB 原色
    SECONDARY = "secondary"               # CMY 二次色
    GRAY = "gray"                         # 灰阶
    BLACK = "black"                       # 黑色
    WHITE = "white"                       # 白色

    # 校准相关
    GAMMA_RAMP = "gamma_ramp"             # gamma/EOTF ramp
    SATURATION_SWEEP = "saturation_sweep" # 饱和度扫描
    HUE_SWEEP = "hue_sweep"               # 色相扫描

    # 特定用途
    QUICK_CHECK = "quick_check"           # 快速预检
    COLORCHECKER = "colorchecker"         # ColorChecker 色块
    MEMORY_COLOR = "memory_color"         # 记忆色
    SKIN_TONE = "skin_tone"              # 肤色

    # LUT 相关
    LUT_CUBE = "lut_cube"                 # 3D LUT cube 点

    # Adaptive
    ADAPTIVE = "adaptive"                 # 自适应追加点

    # 其他
    CUSTOM = "custom"                     # 自定义


class PatchSetType(Enum):
    """Patch Set 类型枚举"""
    QUICK_CHECK = "quick_check"           # 快速预检: 10-30 点
    GRAYSCALE_5 = "grayscale_5"           # 灰阶 5 点
    GRAYSCALE_11 = "grayscale_11"         # 灰阶 11 点
    GRAYSCALE_21 = "grayscale_21"         # 灰阶 21 点
    GAMMA_RAMP = "gamma_ramp"             # gamma/EOTF ramp（可配置步数）
    COLORCHECKER = "colorchecker"         # ColorChecker 24 色
    MEMORY_COLORS = "memory_colors"       # 记忆色
    SATURATION_SWEEP = "saturation_sweep" # 饱和度扫描
    HUE_SWEEP = "hue_sweep"               # 色相扫描
    LUT_CUBE_9 = "lut_cube_9"             # 3D LUT 9^3 = 729 点
    LUT_CUBE_17 = "lut_cube_17"           # 3D LUT 17^3 = 4913 点
    LUT_CUBE_21 = "lut_cube_21"           # 3D LUT 21^3 = 9261 点
    LUT_CUBE_33 = "lut_cube_33"           # 3D LUT 33^3 = 35937 点
    ADAPTIVE = "adaptive"                 # 自适应（根据误差追加）
    FULL_CALIBRATION = "full_calibration" # 完整校准集


@dataclass
class Patch:
    """
    单个色块数据结构

    Attributes:
        rgb: RGB 值 (0-255)
        lab: Lab 目标值
        purpose: 色块用途
        priority: 优先级 (1-5, 越高越重要)
        display_order: 显示顺序（用于测量顺序优化）
        expected_duration_ms: 预期测量时长（毫秒）
        metadata: 额外元数据
    """
    rgb: Tuple[int, int, int]
    lab: Tuple[float, float, float]
    purpose: PatchPurpose
    priority: int = 3
    display_order: int = 0
    expected_duration_ms: int = 500
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """验证数据"""
        if not all(0 <= v <= 255 for v in self.rgb):
            raise ValueError(f"RGB 值必须在 0-255 范围内: {self.rgb}")
        if not (1 <= self.priority <= 5):
            raise ValueError(f"优先级必须在 1-5 范围内: {self.priority}")

    @property
    def rgb_8bit(self) -> Tuple[int, int, int]:
        """8-bit RGB"""
        return self.rgb

    @property
    def rgb_10bit(self) -> Tuple[int, int, int]:
        """10-bit RGB (0-1023)"""
        return tuple(int(v * 1023 / 255) for v in self.rgb)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "rgb": list(self.rgb),
            "rgb_10bit": list(self.rgb_10bit),
            "lab": list(self.lab),
            "purpose": self.purpose.value,
            "priority": self.priority,
            "display_order": self.display_order,
            "expected_duration_ms": self.expected_duration_ms,
            "metadata": self.metadata,
        }

    def to_csv_row(self) -> List[str]:
        """转换为 CSV 行"""
        return [
            f"{self.rgb[0]}", f"{self.rgb[1]}", f"{self.rgb[2]}",
            f"{self.lab[0]:.2f}", f"{self.lab[1]:.2f}", f"{self.lab[2]:.2f}",
            self.purpose.value,
            str(self.priority),
            str(self.display_order),
            str(self.expected_duration_ms),
        ]


@dataclass
class PatchSet:
    """
    色块集合

    Attributes:
        name: 集合名称
        set_type: 集合类型
        patches: 色块列表
        description: 描述
        total_expected_duration_ms: 总预期时长（毫秒）
        seed: 随机种子（用于 deterministic 生成）
    """
    name: str
    set_type: PatchSetType
    patches: List[Patch] = field(default_factory=list)
    description: str = ""
    total_expected_duration_ms: int = 0
    seed: Optional[int] = None

    def __post_init__(self):
        """计算总时长"""
        if not self.total_expected_duration_ms:
            self.total_expected_duration_ms = sum(p.expected_duration_ms for p in self.patches)

    @property
    def count(self) -> int:
        """色块数量"""
        return len(self.patches)

    def add_patch(self, patch: Patch):
        """添加色块"""
        if not self.total_expected_duration_ms:
            self.total_expected_duration_ms = 0
        self.patches.append(patch)
        self.total_expected_duration_ms += patch.expected_duration_ms

    def get_rgb_list(self) -> List[Tuple[int, int, int]]:
        """获取 RGB 列表"""
        return [p.rgb for p in self.patches]

    def get_lab_list(self) -> List[Tuple[float, float, float]]:
        """获取 Lab 目标列表"""
        return [p.lab for p in self.patches]

    def get_rgb_10bit_list(self) -> List[Tuple[int, int, int]]:
        """获取 10-bit RGB 列表"""
        return [p.rgb_10bit for p in self.patches]

    def sort_by_display_order(self) -> 'PatchSet':
        """按显示顺序排序（返回新集合）"""
        sorted_patches = sorted(self.patches, key=lambda p: p.display_order)
        return PatchSet(
            name=self.name,
            set_type=self.set_type,
            patches=sorted_patches,
            description=self.description,
            seed=self.seed,
        )

    def sort_by_priority(self) -> 'PatchSet':
        """按优先级排序（返回新集合）"""
        sorted_patches = sorted(self.patches, key=lambda p: -p.priority)
        return PatchSet(
            name=self.name,
            set_type=self.set_type,
            patches=sorted_patches,
            description=self.description,
            seed=self.seed,
        )

    def export_rgb_8bit(self) -> List[Tuple[int, int, int]]:
        """导出 8-bit RGB"""
        return self.get_rgb_list()

    def export_rgb_10bit(self) -> List[Tuple[int, int, int]]:
        """导出 10-bit RGB"""
        return self.get_rgb_10bit_list()

    def export_lab_targets(self) -> List[Tuple[float, float, float]]:
        """导出 Lab 目标"""
        return self.get_lab_list()

    def export_xyz_targets(self, white_point: str = "D65") -> List[Tuple[float, float, float]]:
        """导出 XYZ 目标（Y 范围 0-100）"""
        xyz_list = []
        for patch in self.patches:
            X, Y, Z = lab_to_xyz(patch.lab[0], patch.lab[1], patch.lab[2], white_point)
            xyz_list.append((X, Y, Z))
        return xyz_list

    def export_display_order(self) -> List[int]:
        """导出显示顺序"""
        return [p.display_order for p in self.patches]

    def export_expected_duration(self) -> List[int]:
        """导出预期时长列表"""
        return [p.expected_duration_ms for p in self.patches]

    def to_dict_list(self) -> List[Dict[str, Any]]:
        """转换为字典列表"""
        return [p.to_dict() for p in self.patches]

    def to_json(self, indent: int = 2) -> str:
        """导出为 JSON"""
        data = {
            "name": self.name,
            "type": self.set_type.value,
            "description": self.description,
            "count": self.count,
            "total_expected_duration_ms": self.total_expected_duration_ms,
            "seed": self.seed,
            "patches": self.to_dict_list(),
        }
        return json.dumps(data, indent=indent, ensure_ascii=False)

    def to_csv(self) -> str:
        """导出为 CSV"""
        lines = [
            "R,G,B,L,a,b,purpose,priority,display_order,expected_duration_ms"
        ]
        for patch in self.patches:
            lines.append(",".join(patch.to_csv_row()))
        return "\n".join(lines)


# ==============================================================================
# 辅助函数
# ==============================================================================

def _rgb_to_lab(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """RGB 转 Lab"""
    X, Y, Z = srgb_to_xyz(r, g, b)
    return xyz_to_lab(X, Y, Z)


def _create_patch(
    rgb: Tuple[int, int, int],
    purpose: PatchPurpose,
    priority: int = 3,
    display_order: int = 0,
    expected_duration_ms: int = 500,
    metadata: Optional[Dict] = None
) -> Patch:
    """创建 Patch 实例"""
    lab = _rgb_to_lab(*rgb)
    return Patch(
        rgb=rgb,
        lab=lab,
        purpose=purpose,
        priority=priority,
        display_order=display_order,
        expected_duration_ms=expected_duration_ms,
        metadata=metadata or {},
    )


# ==============================================================================
# 预定义生成器
# ==============================================================================

def generate_quick_check_patch_set(
    count: int = 20,
    seed: int = 42,
    include_primaries: bool = True,
    include_grayscale: bool = True
) -> PatchSet:
    """
    生成快速预检 Patch Set (10-30 点)

    用途：快速验证校准状态，不进行完整校准

    Args:
        count: 色块数量 (10-30)
        seed: 随机种子（保证 deterministic）
        include_primaries: 是否包含 RGB 原色
        include_grayscale: 是否包含灰阶

    Returns:
        PatchSet: 快速预检色块集合
    """
    random.seed(seed)

    count = max(10, min(30, count))  # 限制在 10-30
    patches = []
    order = 0

    # 基础色块：白、黑
    patches.append(_create_patch((255, 255, 255), PatchPurpose.WHITE, 5, order, 300))
    order += 1
    patches.append(_create_patch((0, 0, 0), PatchPurpose.BLACK, 5, order, 500))
    order += 1

    # RGB 原色
    if include_primaries:
        for rgb, name in [((255, 0, 0), "red"), ((0, 255, 0), "green"), ((0, 0, 255), "blue")]:
            patches.append(_create_patch(rgb, PatchPurpose.PRIMARY, 5, order, 400))
            order += 1

        # 二次色 (CMY)
        for rgb, name in [((255, 255, 0), "yellow"), ((255, 0, 255), "magenta"), ((0, 255, 255), "cyan")]:
            patches.append(_create_patch(rgb, PatchPurpose.SECONDARY, 5, order, 400))
            order += 1

    # 灰阶（5 点）
    if include_grayscale:
        gray_values = [51, 102, 128, 153, 204]  # 20%, 40%, 50%, 60%, 80%
        for gray in gray_values:
            patches.append(_create_patch((gray, gray, gray), PatchPurpose.GRAY, 4, order, 400))
            order += 1

    # 剩余点：随机采样色域
    remaining = count - len(patches)
    if remaining > 0:
        # 确定采样区域
        for _ in range(remaining * 3):  # 多采样几次，跳过重复
            if len(patches) >= count:
                break

            # 随机选择采样策略
            strategy = random.choice(["mid_gray", "saturation", "skin"])

            if strategy == "mid_gray":
                # 中灰附近
                base = random.randint(60, 200)
                noise = random.randint(-20, 20)
                rgb = (
                    max(0, min(255, base + noise)),
                    max(0, min(255, base + noise)),
                    max(0, min(255, base + noise)),
                )
            elif strategy == "saturation":
                # 高饱和
                channel = random.randint(0, 2)
                rgb = [random.randint(0, 80), random.randint(0, 80), random.randint(0, 80)]
                rgb[channel] = random.randint(180, 255)
                rgb = tuple(rgb)
            else:  # skin
                # 肤色区域
                r = random.randint(180, 255)
                g = random.randint(120, 200)
                b = random.randint(100, 180)
                rgb = (r, g, b)

            # 检查是否重复
            if rgb not in [p.rgb for p in patches]:
                patches.append(_create_patch(rgb, PatchPurpose.QUICK_CHECK, 2, order, 400))
                order += 1

    return PatchSet(
        name="Quick Check",
        set_type=PatchSetType.QUICK_CHECK,
        patches=patches,
        description=f"快速预检色块集合 ({count} 点)",
        seed=seed,
    )


def generate_grayscale_patch_set(
    steps: int = 11,
    include_endpoints: bool = True
) -> PatchSet:
    """
    生成灰阶 Patch Set

    Args:
        steps: 灰阶点数 (5/11/21)
        include_endpoints: 是否包含黑/白端点

    Returns:
        PatchSet: 灰阶色块集合
    """
    steps = max(5, min(21, steps))

    # 标准化步数
    if steps <= 7:
        steps = 5
    elif steps <= 15:
        steps = 11
    else:
        steps = 21

    patches = []
    order = 0

    if include_endpoints:
        # 黑
        patches.append(_create_patch((0, 0, 0), PatchPurpose.BLACK, 5, order, 500))
        order += 1

    # 灰阶
    if steps == 5:
        # 5 点: 20%, 40%, 50%, 60%, 80%
        gray_values = [51, 102, 128, 153, 204]
    elif steps == 11:
        # 11 点: 0%, 10%, 20%, ..., 100%（0% 和 100% 由 include_endpoints 控制）
        gray_values = [int(i * 255 / 10) for i in range(1, 10)]
    else:  # 21
        # 21 点: 0%, 5%, 10%, ..., 100%
        gray_values = [int(i * 255 / 20) for i in range(1, 20)]

    for gray in gray_values:
        patches.append(_create_patch((gray, gray, gray), PatchPurpose.GRAY, 4, order, 400))
        order += 1

    if include_endpoints:
        # 白
        patches.append(_create_patch((255, 255, 255), PatchPurpose.WHITE, 5, order, 300))
        order += 1

    set_type_map = {5: PatchSetType.GRAYSCALE_5, 11: PatchSetType.GRAYSCALE_11, 21: PatchSetType.GRAYSCALE_21}

    return PatchSet(
        name=f"Grayscale {steps}-step",
        set_type=set_type_map[steps],
        patches=patches,
        description=f"灰阶色块集合 ({steps} 点)",
    )


def generate_gamma_ramp_patch_set(
    steps: int = 21,
    channel: str = "gray",
    include_rgb_channels: bool = False
) -> PatchSet:
    """
    生成 gamma/EOTF ramp Patch Set

    Args:
        steps: 步数
        channel: "gray" | "R" | "G" | "B"
        include_rgb_channels: 是否同时包含 RGB 三通道

    Returns:
        PatchSet: gamma ramp 色块集合
    """
    steps = max(5, min(256, steps))

    patches = []
    order = 0

    if include_rgb_channels:
        # 包含 RGB 三通道
        for ch_idx, ch_name in enumerate(["R", "G", "B"]):
            for i in range(steps):
                val = int(i * 255 / (steps - 1)) if steps > 1 else 128
                rgb = [0, 0, 0]
                rgb[ch_idx] = val
                patches.append(_create_patch(
                    tuple(rgb),
                    PatchPurpose.GAMMA_RAMP,
                    4,
                    order,
                    400,
                    {"channel": ch_name, "step": i, "total_steps": steps}
                ))
                order += 1
    else:
        # 单通道
        if channel == "gray":
            for i in range(steps):
                val = int(i * 255 / (steps - 1)) if steps > 1 else 128
                patches.append(_create_patch(
                    (val, val, val),
                    PatchPurpose.GAMMA_RAMP,
                    4,
                    order,
                    400,
                    {"channel": "gray", "step": i, "total_steps": steps}
                ))
                order += 1
        else:
            ch_idx = {"R": 0, "G": 1, "B": 2}[channel]
            for i in range(steps):
                val = int(i * 255 / (steps - 1)) if steps > 1 else 128
                rgb = [0, 0, 0]
                rgb[ch_idx] = val
                patches.append(_create_patch(
                    tuple(rgb),
                    PatchPurpose.GAMMA_RAMP,
                    4,
                    order,
                    400,
                    {"channel": channel, "step": i, "total_steps": steps}
                ))
                order += 1

    return PatchSet(
        name=f"Gamma Ramp {steps}-step",
        set_type=PatchSetType.GAMMA_RAMP,
        patches=patches,
        description=f"gamma/EOTF ramp 色块集合 ({steps} 步)",
    )


# ColorChecker 24 色标准数据
COLORCHECKER_DATA = [
    # Row 1 (dark skin, light skin, blue sky, foliage, blue flower, bluish green)
    ((115, 82, 68), "dark_skin"),
    ((194, 150, 130), "light_skin"),
    ((98, 122, 157), "blue_sky"),
    ((87, 108, 67), "foliage"),
    ((133, 128, 177), "blue_flower"),
    ((103, 189, 170), "bluish_green"),
    # Row 2 (orange, purplish blue, moderate red, purple, yellow green, orange yellow)
    ((214, 126, 44), "orange"),
    ((80, 91, 166), "purplish_blue"),
    ((193, 90, 99), "moderate_red"),
    ((94, 60, 108), "purple"),
    ((157, 188, 64), "yellow_green"),
    ((224, 163, 46), "orange_yellow"),
    # Row 3 (blue, green, red, yellow, magenta, cyan)
    ((56, 61, 150), "blue"),
    ((70, 148, 73), "green"),
    ((175, 54, 60), "red"),
    ((231, 199, 31), "yellow"),
    ((187, 86, 149), "magenta"),
    ((8, 133, 161), "cyan"),
    # Row 4 (white, neutral 8, neutral 6.5, neutral 5, neutral 3.5, black)
    ((243, 243, 242), "white"),
    ((200, 200, 200), "neutral_8"),
    ((160, 160, 160), "neutral_65"),
    ((122, 122, 121), "neutral_5"),
    ((85, 85, 85), "neutral_35"),
    ((52, 52, 52), "black"),
]


def generate_colorchecker_patch_set() -> PatchSet:
    """
    生成 ColorChecker 24 色 Patch Set

    Returns:
        PatchSet: ColorChecker 24 色色块集合
    """
    patches = []
    order = 0

    for rgb, name in COLORCHECKER_DATA:
        purpose = PatchPurpose.GRAY if name.startswith("neutral") or name in ["white", "black"] else PatchPurpose.COLORCHECKER
        priority = 5 if purpose == PatchPurpose.GRAY else 4

        patches.append(_create_patch(
            rgb,
            purpose,
            priority,
            order,
            500,
            {"colorchecker_name": name}
        ))
        order += 1

    return PatchSet(
        name="ColorChecker 24",
        set_type=PatchSetType.COLORCHECKER,
        patches=patches,
        description="ColorChecker 24 色标准色块集合",
    )


# 记忆色数据
MEMORY_COLORS_DATA = [
    # 肤色
    ((255, 219, 181), "caucasian_skin"),
    ((225, 172, 125), "asian_skin"),
    ((180, 120, 80), "african_skin"),
    # 天空
    ((135, 206, 235), "sky_blue"),
    ((70, 130, 180), "deep_sky"),
    # 草地
    ((34, 139, 34), "grass_green"),
    ((124, 252, 0), "lawn_green"),
    # 水面
    ((0, 191, 255), "water_blue"),
    # 其他
    ((255, 0, 0), "fire_engine_red"),
    ((255, 165, 0), "orange"),
    ((255, 255, 0), "canary_yellow"),
]


def generate_memory_colors_patch_set() -> PatchSet:
    """
    生成记忆色 Patch Set

    Returns:
        PatchSet: 记忆色色块集合
    """
    patches = []
    order = 0

    for rgb, name in MEMORY_COLORS_DATA:
        patches.append(_create_patch(
            rgb,
            PatchPurpose.MEMORY_COLOR,
            4,
            order,
            500,
            {"memory_color_name": name}
        ))
        order += 1

    return PatchSet(
        name="Memory Colors",
        set_type=PatchSetType.MEMORY_COLORS,
        patches=patches,
        description="记忆色色块集合（肤色、天空、草地等）",
    )


def generate_saturation_sweep_patch_set(
    levels: List[int] = None,
    include_neutrals: bool = True
) -> PatchSet:
    """
    生成饱和度扫描 Patch Set

    扫描每个 primary/secondary 在不同饱和度级别的表现

    Args:
        levels: 饱和度级别列表 (默认 [25, 50, 75, 100])
        include_neutrals: 是否包含中性灰

    Returns:
        PatchSet: 饱和度扫描色块集合
    """
    if levels is None:
        levels = [25, 50, 75, 100]

    patches = []
    order = 0

    # Primary 和 Secondary 颜色
    # 格式: (channel_high_indices, name)
    colors = [
        ([0], "R"),      # Red
        ([1], "G"),      # Green
        ([2], "B"),      # Blue
        ([0, 1], "Y"),   # Yellow
        ([0, 2], "M"),   # Magenta
        ([1, 2], "C"),   # Cyan
    ]

    for high_indices, color_name in colors:
        for level in levels:
            high_val = int(255 * level / 100)
            low_val = 0

            rgb = [low_val, low_val, low_val]
            for idx in high_indices:
                rgb[idx] = high_val

            patches.append(_create_patch(
                tuple(rgb),
                PatchPurpose.SATURATION_SWEEP,
                4,
                order,
                400,
                {"color": color_name, "saturation_percent": level}
            ))
            order += 1

    # 中性灰（可选）
    if include_neutrals:
        for level in levels:
            gray_val = int(255 * level / 100)
            patches.append(_create_patch(
                (gray_val, gray_val, gray_val),
                PatchPurpose.GRAY,
                3,
                order,
                400,
                {"saturation_percent": level, "color": "neutral"}
            ))
            order += 1

    return PatchSet(
        name="Saturation Sweep",
        set_type=PatchSetType.SATURATION_SWEEP,
        patches=patches,
        description=f"饱和度扫描色块集合 ({len(levels)} 级别)",
    )


def generate_hue_sweep_patch_set(
    saturation: int = 100,
    lightness: int = 50,
    steps: int = 12,
    seed: int = 42
) -> PatchSet:
    """
    生成色相扫描 Patch Set

    在固定饱和度和亮度下，扫描不同色相

    Args:
        saturation: 饱和度百分比 (0-100)
        lightness: 亮度百分比 (0-100)
        steps: 色相步数
        seed: 随机种子

    Returns:
        PatchSet: 色相扫描色块集合
    """
    random.seed(seed)

    patches = []
    order = 0

    # 使用 HSL 到 RGB 的近似方法
    # 简化版：直接在 RGB 空间采样色轮
    for i in range(steps):
        hue_angle = i * 360 / steps

        # HSV to RGB (简化，S=1, V=lightness/50)
        h = hue_angle / 60
        s = saturation / 100
        v = lightness / 50

        # HSV to RGB 转换
        c = v * s
        x = c * (1 - abs(h % 2 - 1))
        m = v - c

        if h < 1:
            r, g, b = c, x, 0
        elif h < 2:
            r, g, b = x, c, 0
        elif h < 3:
            r, g, b = 0, c, x
        elif h < 4:
            r, g, b = 0, x, c
        elif h < 5:
            r, g, b = x, 0, c
        else:
            r, g, b = c, 0, x

        rgb = (
            int((r + m) * 127.5),  # 缩放到 0-255
            int((g + m) * 127.5),
            int((b + m) * 127.5),
        )

        patches.append(_create_patch(
            rgb,
            PatchPurpose.HUE_SWEEP,
            3,
            order,
            400,
            {"hue_angle": hue_angle, "saturation": saturation, "lightness": lightness}
        ))
        order += 1

    return PatchSet(
        name="Hue Sweep",
        set_type=PatchSetType.HUE_SWEEP,
        patches=patches,
        description=f"色相扫描色块集合 ({steps} 步)",
        seed=seed,
    )


def generate_lut_cube_patch_set(grid_size: int = 17) -> PatchSet:
    """
    生成 3D LUT cube Patch Set

    Args:
        grid_size: 立方体网格大小 (9/17/21/33)

    Returns:
        PatchSet: 3D LUT cube 色块集合
    """
    # 验证 grid_size
    valid_sizes = [9, 17, 21, 33]
    if grid_size not in valid_sizes:
        closest = min(valid_sizes, key=lambda x: abs(x - grid_size))
        grid_size = closest

    patches = []
    order = 0

    # 均匀采样 RGB 立方体
    for r_idx in range(grid_size):
        for g_idx in range(grid_size):
            for b_idx in range(grid_size):
                r = int(r_idx * 255 / (grid_size - 1)) if grid_size > 1 else 128
                g = int(g_idx * 255 / (grid_size - 1)) if grid_size > 1 else 128
                b = int(b_idx * 255 / (grid_size - 1)) if grid_size > 1 else 128

                # 根据位置判断优先级
                # 角点和边缘优先级更高
                is_corner = (r_idx in [0, grid_size-1] and
                            g_idx in [0, grid_size-1] and
                            b_idx in [0, grid_size-1])
                is_edge = sum([
                    r_idx in [0, grid_size-1],
                    g_idx in [0, grid_size-1],
                    b_idx in [0, grid_size-1]
                ]) >= 2

                if is_corner:
                    priority = 5
                elif is_edge:
                    priority = 4
                else:
                    priority = 2

                # 预估测量时间（大 LUT 点数多，时间短）
                expected_duration = 200 if grid_size >= 33 else 300

                patches.append(_create_patch(
                    (r, g, b),
                    PatchPurpose.LUT_CUBE,
                    priority,
                    order,
                    expected_duration,
                    {"grid_position": [r_idx, g_idx, b_idx], "grid_size": grid_size}
                ))
                order += 1

    # 确定类型
    set_type_map = {
        9: PatchSetType.LUT_CUBE_9,
        17: PatchSetType.LUT_CUBE_17,
        21: PatchSetType.LUT_CUBE_21,
        33: PatchSetType.LUT_CUBE_33,
    }

    return PatchSet(
        name=f"3D LUT Cube {grid_size}^3",
        set_type=set_type_map[grid_size],
        patches=patches,
        description=f"3D LUT cube 色块集合 ({grid_size}^3 = {grid_size**3} 点)",
    )


def generate_adaptive_patch_set(
    previous_errors: List[Dict[str, Any]],
    threshold: float = 5.0,
    max_patches: int = 50,
    seed: int = 42
) -> PatchSet:
    """
    生成自适应 Patch Set（根据上一轮误差追加高风险区域）

    Args:
        previous_errors: 上一轮测量误差列表，格式:
            [{"rgb": [R, G, B], "delta_e": float, "lab_measured": [L, a, b]}, ...]
        threshold: Delta E 阈值，超过此值认为需要追加
        max_patches: 最大追加点数
        seed: 随机种子

    Returns:
        PatchSet: 自适应追加色块集合
    """
    random.seed(seed)

    patches = []
    order = 0
    added_rgb = set()

    # 找出高误差区域
    high_error_patches = [
        p for p in previous_errors
        if p.get("delta_e", 0) > threshold
    ]

    # 按误差排序
    high_error_patches.sort(key=lambda p: p.get("delta_e", 0), reverse=True)

    for p in high_error_patches[:max_patches]:
        rgb = tuple(p["rgb"])
        if rgb in added_rgb:
            continue

        # 在高误差点周围生成采样点
        # 原点
        patches.append(_create_patch(
            rgb,
            PatchPurpose.ADAPTIVE,
            5,
            order,
            500,
            {"source_error": p.get("delta_e", 0), "type": "center"}
        ))
        added_rgb.add(rgb)
        order += 1

        # 周围点（偏移 ±10）
        for dr in [-10, 0, 10]:
            for dg in [-10, 0, 10]:
                for db in [-10, 0, 10]:
                    if dr == 0 and dg == 0 and db == 0:
                        continue

                    new_rgb = (
                        max(0, min(255, rgb[0] + dr)),
                        max(0, min(255, rgb[1] + dg)),
                        max(0, min(255, rgb[2] + db)),
                    )

                    if new_rgb not in added_rgb:
                        patches.append(_create_patch(
                            new_rgb,
                            PatchPurpose.ADAPTIVE,
                            4,
                            order,
                            500,
                            {"source_rgb": list(rgb), "source_error": p.get("delta_e", 0), "type": "neighbor"}
                        ))
                        added_rgb.add(new_rgb)
                        order += 1

                    if len(patches) >= max_patches:
                        break
                if len(patches) >= max_patches:
                    break
            if len(patches) >= max_patches:
                break

        if len(patches) >= max_patches:
            break

    return PatchSet(
        name="Adaptive",
        set_type=PatchSetType.ADAPTIVE,
        patches=patches,
        description=f"自适应追加色块集合（基于误差阈值 {threshold}）",
        seed=seed,
    )


def generate_full_calibration_patch_set(
    include_grayscale: bool = True,
    include_colorchecker: bool = True,
    include_saturation: bool = True,
    grayscale_steps: int = 21,
    saturation_levels: List[int] = None,
    seed: int = 42
) -> PatchSet:
    """
    生成完整校准 Patch Set

    组合多种 Patch Set，用于完整校准流程

    Args:
        include_grayscale: 是否包含灰阶
        include_colorchecker: 是否包含 ColorChecker
        include_saturation: 是否包含饱和度扫描
        grayscale_steps: 灰阶步数
        saturation_levels: 饱和度级别
        seed: 随机种子

    Returns:
        PatchSet: 完整校准色块集合
    """
    random.seed(seed)

    all_patches = []
    order = 0

    # 1. 快速预检（基础点）
    quick_set = generate_quick_check_patch_set(10, seed)
    for p in quick_set.patches:
        p.display_order = order
        p.priority = 5
        all_patches.append(p)
        order += 1

    # 2. 灰阶
    if include_grayscale:
        gray_set = generate_grayscale_patch_set(grayscale_steps)
        for p in gray_set.patches:
            p.display_order = order
            all_patches.append(p)
            order += 1

    # 3. ColorChecker
    if include_colorchecker:
        cc_set = generate_colorchecker_patch_set()
        for p in cc_set.patches:
            p.display_order = order
            all_patches.append(p)
            order += 1

    # 4. 饱和度扫描
    if include_saturation:
        sat_set = generate_saturation_sweep_patch_set(saturation_levels)
        for p in sat_set.patches:
            p.display_order = order
            all_patches.append(p)
            order += 1

    return PatchSet(
        name="Full Calibration",
        set_type=PatchSetType.FULL_CALIBRATION,
        patches=all_patches,
        description="完整校准色块集合（组合多种类型）",
        seed=seed,
    )


# ==============================================================================
# 便捷工厂函数
# ==============================================================================

def create_patch_set(
    set_type: PatchSetType,
    **kwargs
) -> PatchSet:
    """
    创建 Patch Set 的工厂函数

    Args:
        set_type: Patch Set 类型
        **kwargs: 传递给对应生成器的参数

    Returns:
        PatchSet: 对应类型的色块集合
    """
    generators = {
        PatchSetType.QUICK_CHECK: generate_quick_check_patch_set,
        PatchSetType.GRAYSCALE_5: lambda **kw: generate_grayscale_patch_set(5, **kw),
        PatchSetType.GRAYSCALE_11: lambda **kw: generate_grayscale_patch_set(11, **kw),
        PatchSetType.GRAYSCALE_21: lambda **kw: generate_grayscale_patch_set(21, **kw),
        PatchSetType.GAMMA_RAMP: generate_gamma_ramp_patch_set,
        PatchSetType.COLORCHECKER: generate_colorchecker_patch_set,
        PatchSetType.MEMORY_COLORS: generate_memory_colors_patch_set,
        PatchSetType.SATURATION_SWEEP: generate_saturation_sweep_patch_set,
        PatchSetType.HUE_SWEEP: generate_hue_sweep_patch_set,
        PatchSetType.LUT_CUBE_9: lambda **kw: generate_lut_cube_patch_set(9),
        PatchSetType.LUT_CUBE_17: lambda **kw: generate_lut_cube_patch_set(17),
        PatchSetType.LUT_CUBE_21: lambda **kw: generate_lut_cube_patch_set(21),
        PatchSetType.LUT_CUBE_33: lambda **kw: generate_lut_cube_patch_set(33),
        PatchSetType.ADAPTIVE: generate_adaptive_patch_set,
        PatchSetType.FULL_CALIBRATION: generate_full_calibration_patch_set,
    }

    generator = generators.get(set_type)
    if generator is None:
        raise ValueError(f"未知的 PatchSetType: {set_type}")

    return generator(**kwargs)
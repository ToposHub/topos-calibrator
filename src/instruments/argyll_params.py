"""
ArgyllCMS Command Parameters - Dataclass definitions for standardized command construction.

This module defines parameter dataclasses for each ArgyllCMS tool:
- SpotreadParams: spotread measurement tool
- DispcalParams: display calibration tool
- TargenParams: test chart generator
- ColprofParams: ICC profile generator
- CollinkParams: 3D LUT / device link creator

Design Goals:
- Avoid scattering command string construction in business logic
- Provide type-safe, validated parameters
- Enable easy testing and documentation
- Support serialization for checkpoint/resume

Reference:
- docs/agent_handoffs/P0-C_argyll_audit.md
- src/argyll_controller.py (wrapped implementation)
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple


# ========== Enums for ArgyllCMS Parameters ==========

class DisplayType(Enum):
    """Display type for ArgyllCMS tools (same as in argyll_controller.py)."""
    LCD = "l"
    LCD_WHITE_LED = "e"
    LCD_RGB_LED = "b"
    OLED = "o"
    CRT = "c"
    PLASMA = "m"
    PROJECTOR = "p"


class ProbeType(Enum):
    """Probe/instrument type for ArgyllCMS tools."""
    I1_DISPLAY_PRO = "i1d3"
    I1_DISPLAY_2 = "i1d2"
    I1_PRO = "i1pro"
    I1_PRO_2 = "i1pro2"
    I1_PRO_3 = "i1pro3"
    SPYDERX = "spydx"
    SPYDERX2 = "spydx2"
    SPYDER5 = "spyd5"
    SPYDER4 = "spyd4"
    K10A = "k10a"
    COLOR_MUNKI = "colormunki"


class QualityLevel(Enum):
    """Quality level for dispcal and colprof."""
    LOW = "l"
    MEDIUM = "m"
    HIGH = "h"
    ULTRA = "u"


class RenderingIntent(Enum):
    """Rendering intent for collink."""
    RELATIVE_COLORIMETRIC = "r"
    ABSOLUTE_COLORIMETRIC = "a"
    PERCEPTUAL = "p"
    SATURATION = "s"


class SourceSpace(Enum):
    """Source color space for collink."""
    REC709 = "Rec709"
    SRGB = "sRGB"
    DCI_P3 = "DCI-P3"
    DISPLAY_P3 = "DisplayP3"
    REC2020 = "Rec2020"
    ADOBE_RGB = "AdobeRGB"


# ========== SpotreadParams ==========

@dataclass
class SpotreadParams:
    """
    Parameters for spotread command.

    spotread is the interactive spot reading tool for display measurements.

    Args:
        display_type: Type of display being measured
        instrument_port: Port number for specific instrument (if multiple)
        correction_file: Path to CCSS/CCMX spectral correction file
        emissive_mode: Use emissive (display) mode (default True)
        verbose: Enable verbose output
    """
    display_type: DisplayType = DisplayType.LCD
    instrument_port: Optional[int] = None
    correction_file: Optional[str] = None
    emissive_mode: bool = True
    verbose: bool = False

    def to_command_args(self) -> list:
        """
        Convert parameters to spotread command arguments.

        Returns:
            List of command arguments (without executable name)
        """
        args = []

        # Emissive mode (display measurement)
        if self.emissive_mode:
            args.append("-e")

        # Display type
        args.extend(["-d", self.display_type.value])

        # Instrument port
        if self.instrument_port is not None:
            args.extend(["-c", str(self.instrument_port)])

        # Correction file (CCSS/CCMX)
        if self.correction_file:
            resolved = Path(self.correction_file).resolve()
            if resolved.exists():
                args.extend(["-X", str(resolved)])

        return args

    def validate(self) -> Tuple[bool, str]:
        """
        Validate parameters.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if self.correction_file:
            if not Path(self.correction_file).exists():
                return (False, f"Correction file not found: {self.correction_file}")
        return (True, "")


# ========== DispcalParams ==========

@dataclass
class DispcalParams:
    """
    Parameters for dispcal display calibration command.

    dispcal generates 1D LUT / VCGT for display calibration.

    Args:
        output_path: Output .cal file path (without extension)
        display_index: Display number (1-based)
        instrument_index: Instrument port number
        quality: Calibration quality level
        white_point_xy: Target white point coordinates (x, y)
        white_temp: Target white point temperature (K)
        gamma: Target gamma value
        brightness: Target brightness (cd/m²)
        use_web_server: Enable web server mode
        web_port: Web server port number
        skip_display_adjust: Skip display adjustment prompts (-m flag)
        no_vcgt: Don't create VCGT tag (-y c flag)
    """
    output_path: str
    display_index: int = 1
    instrument_index: int = 1
    quality: QualityLevel = QualityLevel.MEDIUM
    white_point_xy: Optional[Tuple[float, float]] = None
    white_temp: Optional[int] = None
    gamma: float = 2.2
    brightness: Optional[float] = None
    use_web_server: bool = False
    web_port: int = 9292
    skip_display_adjust: bool = True
    no_vcgt: bool = True

    def to_command_args(self) -> list:
        """Convert parameters to dispcal command arguments."""
        args = ["-v"]

        # Skip display adjustment
        if self.skip_display_adjust:
            args.append("-m")

        # Display mode: web server or traditional
        if self.use_web_server:
            args.append(f"-dweb:{self.web_port}")
            args.extend(["-Y", "p"])  # Skip placement confirmation
        else:
            args.extend(["-d", str(self.display_index)])

        # Instrument
        args.extend(["-c", str(self.instrument_index)])

        # Quality
        args.extend(["-q", self.quality.value])

        # White point: coordinates or temperature
        if self.white_point_xy:
            x, y = self.white_point_xy
            args.extend(["-w", f"{x:.4f},{y:.4f}"])
        elif self.white_temp:
            args.extend(["-t", str(self.white_temp)])

        # Gamma
        args.extend(["-g", str(self.gamma)])

        # Brightness
        if self.brightness:
            args.extend(["-b", str(self.brightness)])

        # Output path
        args.append(self.output_path)

        return args

    def validate(self) -> Tuple[bool, str]:
        """Validate parameters."""
        if self.display_index < 1:
            return (False, "Display index must be >= 1")
        if self.instrument_index < 1:
            return (False, "Instrument index must be >= 1")
        if self.gamma < 1.0 or self.gamma > 3.0:
            return (False, f"Gamma must be between 1.0 and 3.0: {self.gamma}")
        if self.white_point_xy:
            x, y = self.white_point_xy
            if x < 0 or x > 1 or y < 0 or y > 1:
                return (False, f"White point coordinates out of range: ({x}, {y})")
        if self.white_temp and (self.white_temp < 3000 or self.white_temp > 10000):
            return (False, f"White temperature out of range: {self.white_temp}K")
        return (True, "")

    @property
    def cal_file_path(self) -> str:
        """Expected .cal file output path."""
        return self.output_path + ".cal"


# ========== TargenParams ==========

@dataclass
class TargenParams:
    """
    Parameters for targen test chart generator.

    targen creates .ti1 files containing test patch sequences.

    Args:
        output_path: Output .ti1 file path (without extension)
        patch_count: Number of test patches to generate
        device_type: Device type (3 = emissive display)
        gray_patches: Number of gray axis patches
        include_primaries: Include primary colors
        verbose: Enable verbose output
    """
    output_path: str
    patch_count: int = 1024
    device_type: int = 3  # 3 = emissive display
    gray_patches: Optional[int] = None
    include_primaries: bool = True
    verbose: bool = False

    def to_command_args(self) -> list:
        """Convert parameters to targen command arguments."""
        args = []

        if self.verbose:
            args.append("-v")

        # Device type
        args.append(f"-d{self.device_type}")

        # Patch count
        args.append(f"-f{self.patch_count}")

        # Gray patches
        if self.gray_patches:
            args.append(f"-s{self.gray_patches}")

        # Output path
        args.append(self.output_path)

        return args

    def validate(self) -> Tuple[bool, str]:
        """Validate parameters."""
        if self.patch_count < 16:
            return (False, f"Patch count too low: {self.patch_count}")
        if self.patch_count > 4096:
            return (False, f"Patch count too high (may cause performance issues): {self.patch_count}")
        return (True, "")

    @property
    def ti1_file_path(self) -> str:
        """Expected .ti1 file output path."""
        return self.output_path + ".ti1"


# ========== ColprofParams ==========

@dataclass
class ColprofParams:
    """
    Parameters for colprof ICC profile generator.

    colprof creates ICC profiles from measurement data (.ti3).

    Args:
        ti3_path: Input .ti3 measurement file path
        output_path: Output .icc file path (without extension)
        profile_name: ICC profile description name
        quality: Profile quality level
        profile_type: Profile type (l = Lab, x = XYZ)
        no_vcgt: Don't create VCGT tag (-y c)
        verbose: Enable verbose output
    """
    ti3_path: str
    output_path: str
    profile_name: str = "Display Profile"
    quality: QualityLevel = QualityLevel.MEDIUM
    profile_type: str = "l"  # Lab output profile
    no_vcgt: bool = True
    verbose: bool = False

    def to_command_args(self) -> list:
        """Convert parameters to colprof command arguments."""
        args = []

        if self.verbose:
            args.append("-v")

        # Quality
        args.append(f"-q{self.quality.value}")

        # Profile description
        args.extend(["-D", self.profile_name])

        # Profile type (a = auto, l = Lab, x = XYZ)
        args.append(f"-a{self.profile_type}")

        # No VCGT
        if self.no_vcgt:
            args.extend(["-y", "c"])

        # Output path
        args.append(self.output_path)

        return args

    def validate(self) -> Tuple[bool, str]:
        """Validate parameters."""
        if not Path(self.ti3_path).exists():
            return (False, f"TI3 file not found: {self.ti3_path}")
        if self.profile_type not in ["l", "x", "s", "a"]:
            return (False, f"Invalid profile type: {self.profile_type}")
        return (True, "")

    @property
    def icc_file_path(self) -> str:
        """Expected .icc file output path."""
        return self.output_path + ".icc"


# ========== CollinkParams ==========

@dataclass
class CollinkParams:
    """
    Parameters for collink 3D LUT generator.

    collink creates device link profiles and 3D LUTs.

    Args:
        source_space: Source color space (preset name or ICC path)
        target_icc_path: Target ICC profile path
        output_path: Output .cube file path
        lut_size: 3D LUT cube size (33, 65, 129)
        intent: Rendering intent
        use_bpc: Black point compensation (not compatible with perceptual intent)
        verbose: Enable verbose output
    """
    source_space: str
    target_icc_path: str
    output_path: str
    lut_size: int = 33
    intent: RenderingIntent = RenderingIntent.RELATIVE_COLORIMETRIC
    use_bpc: bool = True
    verbose: bool = False

    def to_command_args(self) -> list:
        """
        Convert parameters to collink command arguments.

        Note: BPC is automatically disabled for perceptual intent
        to avoid ArgyllCMS parameter conflict.
        """
        args = []

        if self.verbose:
            args.append("-v")

        # Source space
        source = self._get_source_param()
        if Path(source).exists():
            args.extend(["-i", source])
        else:
            args.append(f"-i{source}")

        # Target ICC
        args.extend(["-r", self.target_icc_path])

        # Rendering intent
        args.append(f"-n{self.intent.value}")

        # Black point compensation
        # IMPORTANT: BPC is incompatible with perceptual intent
        actual_bpc = self.use_bpc
        if self.intent == RenderingIntent.PERCEPTUAL:
            actual_bpc = False  # Force disable for perceptual
        if actual_bpc:
            args.append("-b")

        # LUT size and output
        args.append(f"-G{self.lut_size}")
        args.extend(["-O", self.output_path])

        return args

    def _get_source_param(self) -> str:
        """Get source space parameter value."""
        # Map enum to parameter string
        if isinstance(self.source_space, SourceSpace):
            return self.source_space.value
        return self.source_space

    def validate(self) -> Tuple[bool, str]:
        """Validate parameters."""
        if not Path(self.target_icc_path).exists():
            return (False, f"Target ICC file not found: {self.target_icc_path}")
        if self.lut_size not in [17, 33, 65, 129]:
            return (False, f"Invalid LUT size: {self.lut_size}")
        # Warn about BPC + perceptual conflict
        if self.intent == RenderingIntent.PERCEPTUAL and self.use_bpc:
            return (True, "Note: BPC will be disabled for perceptual intent")
        return (True, "")


# ========== Error Mapping ==========

@dataclass
class ArgyllErrorMapping:
    """
    Error message to user-friendly suggestion mapping.

    Maps ArgyllCMS error keywords to actionable user guidance.
    """
    keyword: str
    user_message: str
    recoverable: bool
    action: str  # "reconnect", "calibrate", "restart", "contact_support"


# Default error mappings (same as ERROR_MESSAGE_MAP in argyll_controller.py)
DEFAULT_ERROR_MAPPINGS = [
    ArgyllErrorMapping(
        keyword="ambient filter should be removed",
        user_message="柔光罩未移除，请确保柔光罩已打开或移除后再进行测量",
        recoverable=True,
        action="calibrate"
    ),
    ArgyllErrorMapping(
        keyword="sensor being in the wrong position",
        user_message="传感器位置错误，请将探头正确放置在被测区域",
        recoverable=True,
        action="calibrate"
    ),
    ArgyllErrorMapping(
        keyword="no instrument found",
        user_message="未检测到探头，请检查探头连接",
        recoverable=True,
        action="reconnect"
    ),
    ArgyllErrorMapping(
        keyword="communication error",
        user_message="探头通信错误，请重新连接探头",
        recoverable=True,
        action="reconnect"
    ),
    ArgyllErrorMapping(
        keyword="usb error",
        user_message="USB 连接错误，请检查探头 USB 连接",
        recoverable=True,
        action="reconnect"
    ),
    ArgyllErrorMapping(
        keyword="readpipeasync failed",
        user_message="USB 设备已断开，探头已被拔出",
        recoverable=True,
        action="reconnect"
    ),
    ArgyllErrorMapping(
        keyword="calibration failed",
        user_message="校准失败，请重新校准探头",
        recoverable=True,
        action="calibrate"
    ),
    ArgyllErrorMapping(
        keyword="spot read failed",
        user_message="测量失败，请检查探头状态",
        recoverable=True,
        action="calibrate"
    ),
    ArgyllErrorMapping(
        keyword="Black point compensation",
        user_message="黑场补偿参数与渲染意图冲突，已自动调整",
        recoverable=True,
        action="restart"
    ),
    ArgyllErrorMapping(
        keyword="Out of memory",
        user_message="系统内存不足，请关闭其他程序后重试",
        recoverable=False,
        action="restart"
    ),
    ArgyllErrorMapping(
        keyword="Can't open input file",
        user_message="找不到输入文件，请检查文件路径",
        recoverable=False,
        action="restart"
    ),
]


def map_error_to_suggestion(error_message: str) -> ArgyllErrorMapping:
    """
    Map an ArgyllCMS error message to a user-friendly suggestion.

    Args:
        error_message: Raw error message from ArgyllCMS

    Returns:
        ArgyllErrorMapping with user-friendly message and action
    """
    error_lower = error_message.lower()

    for mapping in DEFAULT_ERROR_MAPPINGS:
        if mapping.keyword.lower() in error_lower:
            return mapping

    # Default unknown error
    return ArgyllErrorMapping(
        keyword="unknown",
        user_message=f"未知错误: {error_message}",
        recoverable=False,
        action="contact_support"
    )
"""
Settling Policy - Display stabilization strategy for accurate measurements.

This module defines policies for how long to wait after displaying a patch
before triggering measurement, and whether special handling (black frame
insertion, window patch, repeat measurement) is needed.

Display technologies have different response characteristics:
- OLED: Fast pixel response (<0.1ms) but ABL (Automatic Brightness Limiter)
  may need black frame insertion and window patches
- miniLED: Local dimming zones need time to stabilize
- LCD: Liquid crystal response varies (G2G 1-50ms), dark patches slower
- Projector: Long signal chain latency (processing + light path)

Reference:
- docs/agent_handoffs/P0-A_architecture_audit.md (architecture context)
- docs/agent_handoffs/P1-B_measurement_service.md (measurement service)
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class DisplayTechnology(Enum):
    """
    Display technology categories for settling policy selection.

    Each technology has different response characteristics that affect
    measurement timing and accuracy.
    """
    LCD = "lcd"              # Standard LCD (CCFL or white LED)
    LCD_RGB_LED = "lcd_rgb_led"  # LCD with RGB LED backlight (wide gamut)
    OLED = "oled"            # OLED (organic light emitting diode)
    WOLED = "woled"          # WOLED (white OLED with color filters, LG style)
    MINILED = "miniled"      # miniLED with local dimming zones
    PROJECTOR = "projector"  # DLP/LCD projector
    CRT = "crt"              # CRT (legacy, very fast response)
    UNKNOWN = "unknown"      # Unknown/unspecified display


class ProbeType(Enum):
    """
    Probe type for settling policy consideration.

    Different probe types have different measurement characteristics:
    - Spot colorimeters: faster measurement
    - Spectrometers: longer integration time needed
    - Contact vs. non-contact probes affect settling time
    """
    COLORIMETER = "colorimeter"   # Spot colorimeter (i1 Display, SpyderX)
    SPECTROMETER = "spectrometer"  # Spectrometer (i1 Pro, ColorMunki)
    UNKNOWN = "unknown"


@dataclass
class SettlingDecision:
    """
    Decision result from settling policy evaluation.

    This contains all the parameters needed for proper patch settling
    before measurement.

    Attributes:
        settling_time_ms: Time to wait after patch display (milliseconds)
        insert_black_frame: Whether to insert black frame before patch
        black_frame_duration_ms: Duration of black frame if inserted
        use_window_patch: Whether to use window patch (not fullscreen)
        window_size_percent: Window patch size percentage (10%, 18%, etc.)
        repeat_measurement: Whether to repeat measurement for accuracy
        repeat_count: Number of repeat measurements if needed
        reason: Human-readable explanation for the decision
        metadata: Additional policy-specific metadata
    """
    settling_time_ms: int = 300
    insert_black_frame: bool = False
    black_frame_duration_ms: int = 100
    use_window_patch: bool = False
    window_size_percent: float = 100.0
    repeat_measurement: bool = False
    repeat_count: int = 1
    reason: str = ""
    metadata: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        parts = [f"wait={self.settling_time_ms}ms"]
        if self.insert_black_frame:
            parts.append(f"bfi={self.black_frame_duration_ms}ms")
        if self.use_window_patch:
            parts.append(f"window={self.window_size_percent}%")
        if self.repeat_measurement:
            parts.append(f"repeat={self.repeat_count}")
        return f"SettlingDecision({', '.join(parts)})"


@dataclass
class PatchContext:
    """
    Context information for settling policy evaluation.

    Attributes:
        current_rgb: RGB values of current patch (r, g, b)
        previous_rgb: RGB values of previous patch (None if first patch)
        is_hdr: Whether this is an HDR measurement
        patch_index: Index in measurement sequence
        patch_name: Name/label of the patch
        display_technology: Display technology type
        probe_type: Probe type being used
        previous_brightness: Brightness (Y) of previous measurement
        previous_settling_time: Settling time used for previous patch
    """
    current_rgb: Tuple[int, int, int] = (0, 0, 0)
    previous_rgb: Optional[Tuple[int, int, int]] = None
    is_hdr: bool = False
    patch_index: int = 0
    patch_name: str = ""
    display_technology: DisplayTechnology = DisplayTechnology.LCD
    probe_type: ProbeType = ProbeType.COLORIMETER
    previous_brightness: float = 0.0
    previous_settling_time: int = 300

    @property
    def brightness(self) -> float:
        """Calculate approximate brightness from RGB."""
        r, g, b = self.current_rgb
        # Use sRGB luminance formula approximation
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0

    @property
    def rgb_average(self) -> float:
        """Calculate average RGB value."""
        r, g, b = self.current_rgb
        return (r + g + b) / 3.0

    @property
    def is_dark_patch(self) -> bool:
        """Check if this is a dark patch (average RGB < 50)."""
        return self.rgb_average < 50

    @property
    def is_bright_patch(self) -> bool:
        """Check if this is a bright patch (average RGB > 200)."""
        return self.rgb_average > 200

    @property
    def is_grayscale(self) -> bool:
        """Check if this is a grayscale patch (R ≈ G ≈ B)."""
        r, g, b = self.current_rgb
        return abs(r - g) < 10 and abs(g - b) < 10

    @property
    def brightness_delta(self) -> float:
        """Calculate brightness change from previous patch."""
        if self.previous_rgb is None:
            return 0.0
        prev_avg = sum(self.previous_rgb) / 3.0 / 255.0
        return abs(self.brightness - prev_avg)


class SettlingPolicy(ABC):
    """
    Abstract base class for display settling policies.

    Each display technology has its own settling policy that determines:
    - How long to wait after displaying a patch
    - Whether to insert black frames (for OLED ABL reset)
    - Whether to use window patches (for HDR measurements)
    - Whether to repeat measurements (for dark patches)

    Implementation requirements:
    - Must return SettlingDecision with valid parameters
    - Should consider patch context (RGB, HDR, previous patch)
    - Should be deterministic for same input
    """

    @abstractmethod
    def evaluate(self, context: PatchContext) -> SettlingDecision:
        """
        Evaluate settling parameters for given patch context.

        Args:
            context: Context information about current patch

        Returns:
            SettlingDecision with settling time and handling options
        """
        pass

    @property
    @abstractmethod
    def technology(self) -> DisplayTechnology:
        """Get display technology this policy is designed for."""
        pass

    @property
    @abstractmethod
    def default_settling_ms(self) -> int:
        """Get default settling time in milliseconds."""
        pass

    def get_base_delay(self, probe_type: ProbeType) -> int:
        """
        Get base delay based on probe type.

        Spectrometers typically need longer integration time.

        Args:
            probe_type: Type of measurement probe

        Returns:
            Base delay in milliseconds
        """
        if probe_type == ProbeType.SPECTROMETER:
            return 500  # Spectrometers need more time
        else:
            return 300  # Colorimeters are faster


class LCDSettlingPolicy(SettlingPolicy):
    """
    Settling policy for LCD displays.

    LCD characteristics:
    - Liquid crystal response time varies by model (G2G 1-50ms)
    - Dark-to-dark transitions slower (up to 150ms in some cases)
    - No ABL concerns like OLED
    - Standard measurements use base delay

    Special handling:
    - Dark patches need extra settling time
    - Large brightness transitions may need more time
    """

    def __init__(
        self,
        base_delay_ms: int = 300,
        dark_patch_bonus_ms: int = 150,
        brightness_transition_threshold: float = 0.3,
        transition_bonus_ms: int = 100
    ):
        """
        Initialize LCD settling policy.

        Args:
            base_delay_ms: Base settling time (default 300ms)
            dark_patch_bonus_ms: Extra time for dark patches
            brightness_transition_threshold: Threshold for large brightness change
            transition_bonus_ms: Extra time for large transitions
        """
        self._base_delay = base_delay_ms
        self._dark_patch_bonus = dark_patch_bonus_ms
        self._transition_threshold = brightness_transition_threshold
        self._transition_bonus = transition_bonus_ms

    @property
    def technology(self) -> DisplayTechnology:
        return DisplayTechnology.LCD

    @property
    def default_settling_ms(self) -> int:
        return self._base_delay

    def evaluate(self, context: PatchContext) -> SettlingDecision:
        """
        Evaluate LCD settling parameters.

        Rules:
        1. Use base delay from probe type
        2. Add dark patch bonus for RGB average < 50
        3. Add transition bonus for large brightness changes
        """
        settling_ms = self.get_base_delay(context.probe_type)

        reasons = []

        # Dark patch handling
        if context.is_dark_patch:
            settling_ms += self._dark_patch_bonus
            reasons.append(f"暗场色块 +{self._dark_patch_bonus}ms")

        # Large brightness transition
        if context.brightness_delta > self._transition_threshold:
            settling_ms += self._transition_bonus
            reasons.append(f"亮度跳变 +{self._transition_bonus}ms (delta={context.brightness_delta:.2f})")

        # No black frame or window patch for LCD
        reason_text = "; ".join(reasons) if reasons else "标准 LCD 延迟"

        return SettlingDecision(
            settling_time_ms=settling_ms,
            insert_black_frame=False,
            use_window_patch=False,
            window_size_percent=100.0,
            repeat_measurement=False,
            reason=reason_text,
            metadata={
                "technology": self.technology.value,
                "is_dark": context.is_dark_patch,
                "brightness_delta": context.brightness_delta
            }
        )


class OLEDSettlingPolicy(SettlingPolicy):
    """
    Settling policy for OLED displays.

    OLED characteristics:
    - Pixel response extremely fast (<0.1ms)
    - ABL (Automatic Brightness Limiter) may reduce brightness
    - ASBL (Auto Static Brightness Limiter) for sustained bright patches
    - HDR measurements need window patches (10% or 18%)
    - Black frame insertion helps reset ABL state

    Special handling:
    - Bright patches trigger ABL, need black frame before/after
    - HDR measurements use window patch to avoid ABL limiting
    - Large brightness transitions need black frame reset
    """

    def __init__(
        self,
        base_delay_ms: int = 200,
        black_frame_duration_ms: int = 1500,
        black_frame_trigger_threshold: float = 0.4,
        black_frame_rgb_threshold: int = 128,
        window_patch_percent: float = 10.0,
        hdr_window_percent: float = 10.0,
        extended_settling_ms: int = 300
    ):
        """
        Initialize OLED settling policy.

        Args:
            base_delay_ms: Base settling time (default 200ms, OLED is fast)
            black_frame_duration_ms: Duration of black frame for ABL reset
            black_frame_trigger_threshold: Brightness delta threshold for BFI
            black_frame_rgb_threshold: RGB average threshold for BFI
            window_patch_percent: Default window patch size
            hdr_window_percent: Window patch size for HDR measurements
            extended_settling_ms: Extra settling after black frame
        """
        self._base_delay = base_delay_ms
        self._black_frame_duration = black_frame_duration_ms
        self._bfi_brightness_threshold = black_frame_trigger_threshold
        self._bfi_rgb_threshold = black_frame_rgb_threshold
        self._window_patch_percent = window_patch_percent
        self._hdr_window_percent = hdr_window_percent
        self._extended_settling = extended_settling_ms

    @property
    def technology(self) -> DisplayTechnology:
        return DisplayTechnology.OLED

    @property
    def default_settling_ms(self) -> int:
        return self._base_delay

    def _should_insert_black_frame(self, context: PatchContext) -> bool:
        """
        Determine if black frame insertion is needed.

        BFI is needed when:
        1. Current patch is bright (RGB avg > threshold)
        2. Large brightness transition from previous patch
        3. Not the last patch in sequence
        """
        # Brightness threshold check
        brightness_trigger = context.brightness > self._bfi_brightness_threshold

        # RGB average threshold check
        rgb_trigger = context.rgb_average > self._bfi_rgb_threshold

        # Large brightness transition
        transition_trigger = context.brightness_delta > 0.3

        # BFI needed if any trigger is true
        return brightness_trigger or rgb_trigger or transition_trigger

    def evaluate(self, context: PatchContext) -> SettlingDecision:
        """
        Evaluate OLED settling parameters.

        Rules:
        1. Use base delay (OLED is very fast)
        2. Insert black frame for bright patches or large transitions
        3. Use window patch for HDR measurements
        4. Add extended settling after black frame
        """
        settling_ms = self._base_delay
        insert_bfi = False
        use_window = False
        window_percent = 100.0

        reasons = ["OLED 极快响应"]

        # Check for black frame insertion
        if self._should_insert_black_frame(context):
            insert_bfi = True
            reasons.append(f"插入黑帧 {self._black_frame_duration}ms (ABL 重置)")

        # HDR measurements need window patch
        if context.is_hdr:
            use_window = True
            window_percent = self._hdr_window_percent
            reasons.append(f"HDR 窗口模式 {window_percent}%")

        # Window patch for high brightness (non-HDR)
        elif context.rgb_average > 180:
            use_window = True
            window_percent = self._window_patch_percent
            reasons.append(f"窗口模式 {window_percent}% (避免 ABL)")

        # Extended settling after black frame
        if insert_bfi:
            settling_ms = self._extended_settling

        # Dark patch handling (OLED can have noise at low luminance)
        if context.is_dark_patch:
            settling_ms += 100
            reasons.append("暗场 +100ms")

        reason_text = "; ".join(reasons)

        return SettlingDecision(
            settling_time_ms=settling_ms,
            insert_black_frame=insert_bfi,
            black_frame_duration_ms=self._black_frame_duration,
            use_window_patch=use_window,
            window_size_percent=window_percent,
            repeat_measurement=False,
            reason=reason_text,
            metadata={
                "technology": self.technology.value,
                "is_hdr": context.is_hdr,
                "brightness": context.brightness,
                "rgb_average": context.rgb_average,
                "bfi_triggered": insert_bfi
            }
        )


class WOLEDSettlingPolicy(OLEDSettlingPolicy):
    """
    Settling policy for WOLED displays (LG OLED TVs).

    WOLED (White OLED with color filters) has similar characteristics to OLED
    but may have slightly different ABL behavior. Inherits from OLEDSettlingPolicy
    with modified thresholds.
    """

    @property
    def technology(self) -> DisplayTechnology:
        return DisplayTechnology.WOLED

    def __init__(self, **kwargs):
        """
        Initialize WOLED settling policy.

        Uses OLED defaults but with slightly longer black frame duration
        since WOLED TVs may have more aggressive ABL.
        """
        if 'black_frame_duration_ms' not in kwargs:
            kwargs['black_frame_duration_ms'] = 2000  # Longer for TV OLEDs
        if 'hdr_window_percent' not in kwargs:
            kwargs['hdr_window_percent'] = 18.0  # Larger window for TVs
        super().__init__(**kwargs)


class MiniLEDSettlingPolicy(SettlingPolicy):
    """
    Settling policy for miniLED displays.

    miniLED characteristics:
    - Local dimming zones (hundreds to thousands)
    - Zone response time varies (10-50ms typical)
    - Bright patches may activate many zones
    - Dark patches in bright areas may have blooming/halo
    - Large transitions need zone stabilization time

    Special handling:
    - Large brightness transitions need extra settling for zone adjustment
    - High contrast patches need zone stabilization
    - HDR measurements may benefit from window patch
    """

    def __init__(
        self,
        base_delay_ms: int = 400,
        zone_transition_bonus_ms: int = 200,
        high_contrast_bonus_ms: int = 150,
        hdr_window_percent: float = 18.0
    ):
        """
        Initialize miniLED settling policy.

        Args:
            base_delay_ms: Base settling time (default 400ms)
            zone_transition_bonus_ms: Extra time for zone adjustments
            high_contrast_bonus_ms: Extra time for high contrast patches
            hdr_window_percent: Window patch size for HDR
        """
        self._base_delay = base_delay_ms
        self._zone_transition_bonus = zone_transition_bonus_ms
        self._high_contrast_bonus = high_contrast_bonus_ms
        self._hdr_window_percent = hdr_window_percent

    @property
    def technology(self) -> DisplayTechnology:
        return DisplayTechnology.MINILED

    @property
    def default_settling_ms(self) -> int:
        return self._base_delay

    def _is_high_contrast_transition(self, context: PatchContext) -> bool:
        """
        Check if this is a high contrast transition.

        High contrast: transitioning from very dark to very bright,
        or vice versa.
        """
        if context.previous_rgb is None:
            return False

        prev_avg = sum(context.previous_rgb) / 3.0
        curr_avg = context.rgb_average

        # High contrast: one patch is dark (< 50), other is bright (> 200)
        is_dark_to_bright = prev_avg < 50 and curr_avg > 200
        is_bright_to_dark = prev_avg > 200 and curr_avg < 50

        return is_dark_to_bright or is_bright_to_dark

    def evaluate(self, context: PatchContext) -> SettlingDecision:
        """
        Evaluate miniLED settling parameters.

        Rules:
        1. Use base delay (longer than standard LCD)
        2. Add zone transition bonus for large brightness changes
        3. Add high contrast bonus for dark/bright transitions
        4. Use window patch for HDR measurements
        """
        settling_ms = self._base_delay
        use_window = False
        window_percent = 100.0

        reasons = ["miniLED 分区响应"]

        # Large brightness transition (zones need to adjust)
        if context.brightness_delta > 0.3:
            settling_ms += self._zone_transition_bonus
            reasons.append(f"分区调整 +{self._zone_transition_bonus}ms")

        # High contrast transition
        if self._is_high_contrast_transition(context):
            settling_ms += self._high_contrast_bonus
            reasons.append(f"高对比度 +{self._high_contrast_bonus}ms")

        # HDR window patch
        if context.is_hdr:
            use_window = True
            window_percent = self._hdr_window_percent
            reasons.append(f"HDR 窗口 {window_percent}%")

        # Dark patch handling
        if context.is_dark_patch:
            settling_ms += 100
            reasons.append("暗场 +100ms")

        reason_text = "; ".join(reasons)

        return SettlingDecision(
            settling_time_ms=settling_ms,
            insert_black_frame=False,  # miniLED doesn't need BFI
            use_window_patch=use_window,
            window_size_percent=window_percent,
            repeat_measurement=False,
            reason=reason_text,
            metadata={
                "technology": self.technology.value,
                "zone_transition": context.brightness_delta > 0.3,
                "high_contrast": self._is_high_contrast_transition(context)
            }
        )


class ProjectorSettlingPolicy(SettlingPolicy):
    """
    Settling policy for projectors.

    Projector characteristics:
    - Long signal chain: source -> processing -> light path -> screen
    - Processing latency varies (10-100ms)
    - Light path adds delay (lamp/laser response)
    - Screen surface may affect response
    - Color wheel in DLP projectors adds flicker considerations

    Special handling:
    - Longer base settling time to account for signal chain
    - Dark patches may have different lamp/laser behavior
    - Large transitions need extra time for processing
    """

    def __init__(
        self,
        base_delay_ms: int = 800,
        dark_patch_bonus_ms: int = 200,
        transition_bonus_ms: int = 150,
        lamp_stabilization_ms: int = 500
    ):
        """
        Initialize projector settling policy.

        Args:
            base_delay_ms: Base settling time (default 800ms)
            dark_patch_bonus_ms: Extra time for dark patches
            transition_bonus_ms: Extra time for large transitions
            lamp_stabilization_ms: Extra time for lamp/laser stabilization
        """
        self._base_delay = base_delay_ms
        self._dark_patch_bonus = dark_patch_bonus_ms
        self._transition_bonus = transition_bonus_ms
        self._lamp_stabilization = lamp_stabilization_ms

    @property
    def technology(self) -> DisplayTechnology:
        return DisplayTechnology.PROJECTOR

    @property
    def default_settling_ms(self) -> int:
        return self._base_delay

    def evaluate(self, context: PatchContext) -> SettlingDecision:
        """
        Evaluate projector settling parameters.

        Rules:
        1. Use long base delay for signal chain latency
        2. Add dark patch bonus
        3. Add transition bonus for large changes
        4. Add lamp stabilization for bright patches
        """
        settling_ms = self._base_delay

        reasons = ["投影仪信号链路延迟"]

        # Dark patch handling
        if context.is_dark_patch:
            settling_ms += self._dark_patch_bonus
            reasons.append(f"暗场 +{self._dark_patch_bonus}ms")

        # Large brightness transition
        if context.brightness_delta > 0.3:
            settling_ms += self._transition_bonus
            reasons.append(f"亮度跳变 +{self._transition_bonus}ms")

        # Bright patches need lamp/laser stabilization
        if context.is_bright_patch:
            settling_ms += self._lamp_stabilization
            reasons.append(f"光源稳定 +{self._lamp_stabilization}ms")

        # Grayscale patches may need extra time for uniformity
        if context.is_grayscale:
            settling_ms += 100
            reasons.append("灰阶均匀性 +100ms")

        reason_text = "; ".join(reasons)

        return SettlingDecision(
            settling_time_ms=settling_ms,
            insert_black_frame=False,
            use_window_patch=False,
            window_size_percent=100.0,
            repeat_measurement=False,
            reason=reason_text,
            metadata={
                "technology": self.technology.value,
                "is_dark": context.is_dark_patch,
                "is_bright": context.is_bright_patch,
                "is_grayscale": context.is_grayscale
            }
        )


class CRTSettlingPolicy(SettlingPolicy):
    """
    Settling policy for CRT displays (legacy).

    CRT characteristics:
    - Extremely fast pixel response (phosphor decay < 1ms)
    - No ABL or local dimming concerns
    - Scan rate considerations (raster timing)
    - Generally obsolete but may be encountered

    Special handling:
    - Minimal settling time needed
    - No special features required
    """

    def __init__(self, base_delay_ms: int = 150):
        """
        Initialize CRT settling policy.

        Args:
            base_delay_ms: Base settling time (default 150ms, very fast)
        """
        self._base_delay = base_delay_ms

    @property
    def technology(self) -> DisplayTechnology:
        return DisplayTechnology.CRT

    @property
    def default_settling_ms(self) -> int:
        return self._base_delay

    def evaluate(self, context: PatchContext) -> SettlingDecision:
        """CRT is very fast, minimal settling needed."""
        settling_ms = self.get_base_delay(context.probe_type)
        settling_ms = max(settling_ms, self._base_delay)

        return SettlingDecision(
            settling_time_ms=settling_ms,
            insert_black_frame=False,
            use_window_patch=False,
            window_size_percent=100.0,
            repeat_measurement=False,
            reason="CRT 极快响应",
            metadata={"technology": self.technology.value}
        )


class UnknownSettlingPolicy(SettlingPolicy):
    """
    Fallback settling policy for unknown display types.

    Uses conservative settings to ensure measurements are accurate
    even when display type is not specified.
    """

    def __init__(self, base_delay_ms: int = 500):
        """
        Initialize unknown display settling policy.

        Args:
            base_delay_ms: Conservative base settling time
        """
        self._base_delay = base_delay_ms

    @property
    def technology(self) -> DisplayTechnology:
        return DisplayTechnology.UNKNOWN

    @property
    def default_settling_ms(self) -> int:
        return self._base_delay

    def evaluate(self, context: PatchContext) -> SettlingDecision:
        """Use conservative settings for unknown displays."""
        settling_ms = self._base_delay

        reasons = ["未知显示器类型，保守延迟"]

        # Add extra time for dark patches
        if context.is_dark_patch:
            settling_ms += 200
            reasons.append("暗场 +200ms")

        # Add extra time for transitions
        if context.brightness_delta > 0.3:
            settling_ms += 150
            reasons.append("亮度跳变 +150ms")

        reason_text = "; ".join(reasons)

        return SettlingDecision(
            settling_time_ms=settling_ms,
            insert_black_frame=False,
            use_window_patch=False,
            window_size_percent=100.0,
            repeat_measurement=False,
            reason=reason_text,
            metadata={"technology": self.technology.value}
        )


class SettlingPolicyFactory:
    """
    Factory for creating settling policies based on display technology.

    This factory provides the appropriate settling policy for a given
    display technology, allowing consistent policy selection across
    the application.
    """

    # Policy registry
    _policies: dict = {
        DisplayTechnology.LCD: LCDSettlingPolicy,
        DisplayTechnology.LCD_RGB_LED: LCDSettlingPolicy,  # Similar to LCD
        DisplayTechnology.OLED: OLEDSettlingPolicy,
        DisplayTechnology.WOLED: WOLEDSettlingPolicy,
        DisplayTechnology.MINILED: MiniLEDSettlingPolicy,
        DisplayTechnology.PROJECTOR: ProjectorSettlingPolicy,
        DisplayTechnology.CRT: CRTSettlingPolicy,
        DisplayTechnology.UNKNOWN: UnknownSettlingPolicy,
    }

    @classmethod
    def create(cls, technology: DisplayTechnology, **kwargs) -> SettlingPolicy:
        """
        Create settling policy for given display technology.

        Args:
            technology: Display technology type
            **kwargs: Optional policy-specific parameters

        Returns:
            SettlingPolicy instance for the technology

        Raises:
            ValueError: If technology is not supported
        """
        if technology not in cls._policies:
            logger.warning(f"Unknown technology: {technology}, using fallback")
            return UnknownSettlingPolicy(**kwargs)

        policy_class = cls._policies[technology]
        return policy_class(**kwargs)

    @classmethod
    def register(cls, technology: DisplayTechnology, policy_class: type) -> None:
        """
        Register a custom policy for a display technology.

        Args:
            technology: Display technology type
            policy_class: SettlingPolicy subclass to use
        """
        if not isinstance(policy_class, type) or not issubclass(policy_class, SettlingPolicy):
            raise ValueError("policy_class must be a SettlingPolicy subclass")
        cls._policies[technology] = policy_class

    @classmethod
    def supported_technologies(cls) -> list:
        """Get list of supported display technologies."""
        return list(cls._policies.keys())

    @classmethod
    def from_display_type_string(cls, display_type_str: str) -> DisplayTechnology:
        """
        Convert display type string to DisplayTechnology enum.

        Handles various string formats from ArgyllCMS and UI.

        Args:
            display_type_str: Display type string (e.g., "LCD", "oled", "projector")

        Returns:
            DisplayTechnology enum value
        """
        # Normalize input
        normalized = display_type_str.lower().strip()

        # Mapping from common strings to DisplayTechnology
        mapping = {
            "lcd": DisplayTechnology.LCD,
            "lcd_ccfl": DisplayTechnology.LCD,
            "lcd_white_led": DisplayTechnology.LCD,
            "lcd_rgb_led": DisplayTechnology.LCD_RGB_LED,
            "oled": DisplayTechnology.OLED,
            "amoled": DisplayTechnology.OLED,
            "woled": DisplayTechnology.WOLED,
            "miniled": DisplayTechnology.MINILED,
            "mini_led": DisplayTechnology.MINILED,
            "projector": DisplayTechnology.PROJECTOR,
            "dlp": DisplayTechnology.PROJECTOR,
            "crt": DisplayTechnology.CRT,
            "l": DisplayTechnology.LCD,  # ArgyllCMS code
            "o": DisplayTechnology.OLED,  # ArgyllCMS code
            "w": DisplayTechnology.WOLED,  # ArgyllCMS code
            "p": DisplayTechnology.PROJECTOR,  # ArgyllCMS code
        }

        return mapping.get(normalized, DisplayTechnology.UNKNOWN)


def evaluate_settling(
    display_technology: DisplayTechnology,
    current_rgb: Tuple[int, int, int],
    previous_rgb: Optional[Tuple[int, int, int]] = None,
    is_hdr: bool = False,
    probe_type: ProbeType = ProbeType.COLORIMETER,
    previous_brightness: float = 0.0,
    **kwargs
) -> SettlingDecision:
    """
    Convenience function for settling policy evaluation.

    Creates appropriate policy and evaluates settling parameters
    in one call.

    Args:
        display_technology: Display technology type
        current_rgb: Current patch RGB values
        previous_rgb: Previous patch RGB values (if any)
        is_hdr: Whether HDR measurement
        probe_type: Probe type
        previous_brightness: Previous measurement brightness
        **kwargs: Additional policy-specific parameters

    Returns:
        SettlingDecision with settling parameters
    """
    policy = SettlingPolicyFactory.create(display_technology, **kwargs)

    context = PatchContext(
        current_rgb=current_rgb,
        previous_rgb=previous_rgb,
        is_hdr=is_hdr,
        display_technology=display_technology,
        probe_type=probe_type,
        previous_brightness=previous_brightness
    )

    return policy.evaluate(context)
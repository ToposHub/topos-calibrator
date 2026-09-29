"""
Base interfaces for measurement instruments and patch presentation.

This module defines the abstract interfaces that all measurement-related
components must implement. These interfaces enable:
- Swappable instrument implementations (real hardware, fake for testing)
- Swappable patch display implementations (PyQt window, web display, fake)
- Clean separation of concerns between measurement logic and UI/hardware

Reference: docs/agent_handoffs/P0-A_architecture_audit.md
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class InstrumentState(Enum):
    """State of a measurement instrument."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    CALIBRATING = "calibrating"
    MEASURING = "measuring"
    ERROR = "error"


@dataclass
class InstrumentStatus:
    """
    Status information about a measurement instrument.

    Attributes:
        state: Current instrument state
        connected: Whether instrument is connected
        model: Instrument model name (e.g., "i1 Display Pro")
        serial: Serial number if available
        last_calibration: Timestamp of last calibration
        battery_level: Battery percentage (if applicable)
        temperature: Instrument temperature (if applicable)
        error_code: Error code if in error state
        error_message: Human-readable error message
        correction_file: Path to active correction file (CCSS/CCMX)
    """
    state: InstrumentState = InstrumentState.DISCONNECTED
    connected: bool = False
    model: str = ""
    serial: str = ""
    last_calibration: Optional[datetime] = None
    battery_level: Optional[int] = None
    temperature: Optional[float] = None
    error_code: Optional[str] = None
    error_message: str = ""
    correction_file: str = ""

    def is_ready_for_measurement(self) -> bool:
        """Check if instrument is ready to take a measurement."""
        return self.state == InstrumentState.READY and self.connected

    def needs_calibration(self) -> bool:
        """Check if instrument needs recalibration."""
        if not self.last_calibration:
            return True
        # Check if calibration is older than 30 minutes
        age = datetime.now() - self.last_calibration
        return age.total_seconds() > 1800


@dataclass
class RawReading:
    """
    Single raw reading from instrument.

    Records each individual measurement before averaging/outlier rejection.

    Attributes:
        xyz: XYZ tristimulus values
        xyY: CIE xyY values
        timestamp: Reading timestamp
        reading_index: Index in the sequence of readings
        integration_time_ms: Integration time used (if available)
        temperature: Instrument temperature (if available)
        metadata: Additional reading metadata
    """
    xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    xyY: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    timestamp: datetime = field(default_factory=datetime.now)
    reading_index: int = 0
    integration_time_ms: Optional[float] = None
    temperature: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MeasurementResult:
    """
    Result from a single color measurement.

    Attributes:
        xyz: XYZ tristimulus values (X, Y, Z)
        xyY: CIE xyY values (x, y, Y)
        rgb_requested: The RGB values that were requested for display
        timestamp: When the measurement was taken
        patch_index: Index of the patch in the sequence
        patch_name: Name/label of the patch
        patch_id: Unique identifier for the patch
        is_retry: Whether this is a retry measurement
        confidence: Confidence score (0-1) if available
        raw_data: Raw data from instrument if available
        metadata: Additional metadata (temperature, integration time, etc.)
        raw_readings: List of raw readings before averaging
        repeat_count: Number of measurements taken
        standard_deviation: XYZ standard deviation (std_X, std_Y, std_Z)
        rejected_readings: List of readings rejected as outliers
        outlier_rejection_method: Method used for outlier rejection
        luminance_level: Classification of luminance (dark/mid/bright)
        measurement_status: Quality status (pass/warn/fail/unknown)
    """
    xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    xyY: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    rgb_requested: Tuple[int, int, int] = (0, 0, 0)
    timestamp: datetime = field(default_factory=datetime.now)
    patch_index: int = 0
    patch_name: str = ""
    patch_id: str = ""
    is_retry: bool = False
    confidence: Optional[float] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # New fields for reliability tracking
    raw_readings: List[RawReading] = field(default_factory=list)
    repeat_count: int = 1
    standard_deviation: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    rejected_readings: List[RawReading] = field(default_factory=list)
    outlier_rejection_method: str = ""
    luminance_level: str = "mid"
    measurement_status: str = "unknown"

    @property
    def Y(self) -> float:
        """Get luminance (Y value)."""
        return self.xyY[2]

    @property
    def is_dark_sample(self, threshold: float = 0.2) -> bool:
        """Check if this is a dark sample (below threshold cd/m^2)."""
        return self.Y < threshold

    @property
    def accepted_readings_count(self) -> int:
        """Number of readings accepted (not rejected as outliers)."""
        return self.repeat_count - len(self.rejected_readings)

    @property
    def relative_std_Y(self) -> float:
        """Relative standard deviation of Y (percentage)."""
        if self.xyY[2] == 0:
            return 0.0
        return (self.standard_deviation[1] / self.xyY[2]) * 100.0


class InstrumentError(Exception):
    """
    Exception raised when an instrument operation fails.

    Attributes:
        error_code: Machine-readable error code
        instrument_id: Identifier of the instrument that failed
        recoverable: Whether the error can be recovered from
        suggestion: Suggested action to resolve the error
    """
    def __init__(
        self,
        message: str,
        error_code: str = "UNKNOWN",
        instrument_id: str = "",
        recoverable: bool = False,
        suggestion: str = ""
    ):
        super().__init__(message)
        self.error_code = error_code
        self.instrument_id = instrument_id
        self.recoverable = recoverable
        self.suggestion = suggestion


class PatchDisplayError(Exception):
    """
    Exception raised when patch display fails.

    Attributes:
        display_id: ID of the display that failed
        rgb_requested: RGB values that were attempted
    """
    def __init__(
        self,
        message: str,
        display_id: Optional[int] = None,
        rgb_requested: Optional[Tuple[int, int, int]] = None
    ):
        super().__init__(message)
        self.display_id = display_id
        self.rgb_requested = rgb_requested


class InstrumentAdapter(ABC):
    """
    Abstract interface for measurement instruments.

    All measurement instruments must implement this interface to be used
    with the MeasurementService. This enables:
    - Swapping between different instrument types (i1, SpyderX, etc.)
    - Using fake instruments for testing without hardware
    - Clean separation from measurement workflow logic

    Implementation requirements:
    - connect() must block until connected or timeout
    - measure() must return valid XYZ/xyY within timeout
    - All methods should raise InstrumentError on failure
    """

    @abstractmethod
    def connect(self) -> bool:
        """
        Connect to the measurement instrument.

        This method should:
        - Initialize communication with the instrument
        - Verify instrument is responding
        - Set up any required configuration

        Returns:
            True if connection successful

        Raises:
            InstrumentError: If connection fails
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """
        Disconnect from the measurement instrument.

        This method should:
        - Clean up communication resources
        - Return instrument to safe state
        - Clear any pending operations
        """
        pass

    @abstractmethod
    def measure(self, timeout: float = 30.0) -> MeasurementResult:
        """
        Perform a color measurement.

        This method should:
        - Trigger measurement on the instrument
        - Wait for measurement result
        - Parse and return XYZ/xyY values

        Args:
            timeout: Maximum time to wait for measurement (seconds)

        Returns:
            MeasurementResult containing XYZ/xyY values

        Raises:
            InstrumentError: If measurement fails or times out
        """
        pass

    @abstractmethod
    def calibrate(self, calibration_type: str = "standard") -> bool:
        """
        Perform instrument calibration.

        This method should:
        - Initiate calibration routine (white reference, dark, etc.)
        - Wait for calibration to complete
        - Update internal calibration state

        Args:
            calibration_type: Type of calibration ("standard", "white", "dark")

        Returns:
            True if calibration successful

        Raises:
            InstrumentError: If calibration fails
        """
        pass

    @abstractmethod
    def status(self) -> InstrumentStatus:
        """
        Get current instrument status.

        Returns:
            InstrumentStatus with current state, model, serial, etc.
        """
        pass

    @property
    @abstractmethod
    def instrument_id(self) -> str:
        """
        Get unique identifier for this instrument.

        Returns:
            Unique identifier (model + serial or similar)
        """
        pass

    @property
    @abstractmethod
    def instrument_type(self) -> str:
        """
        Get instrument type/model name.

        Returns:
            Instrument type string (e.g., "i1 Display Pro", "SpyderX")
        """
        pass

    def is_connected(self) -> bool:
        """Check if instrument is currently connected."""
        return self.status().connected

    def is_ready(self) -> bool:
        """Check if instrument is ready for measurement."""
        return self.status().is_ready_for_measurement()


class PatchPresenter(ABC):
    """
    Abstract interface for displaying color patches.

    All patch display implementations must implement this interface.
    This enables:
    - Swapping between different display methods (PyQt window, web, etc.)
    - Using fake presenters for testing without GUI
    - Clean separation from measurement workflow logic

    Implementation requirements:
    - show_rgb() must display the color before returning
    - hide() must clear the display
    - Must handle OLED/window modes if applicable
    """

    @abstractmethod
    def show_rgb(self, r: int, g: int, b: int) -> None:
        """
        Display a color patch with given RGB values.

        Args:
            r: Red value (0-255)
            g: Green value (0-255)
            b: Blue value (0-255)

        Raises:
            PatchDisplayError: If display fails
        """
        pass

    @abstractmethod
    def hide(self) -> None:
        """
        Hide/clear the color patch display.

        Should return display to neutral state (black or hidden window).
        """
        pass

    @abstractmethod
    def target_display_id(self) -> int:
        """
        Get the ID of the target display.

        Returns:
            Display ID/index being used for patch display
        """
        pass

    @abstractmethod
    def set_oled_window_size(self, percent: float) -> None:
        """
        Set window size percentage for OLED displays.

        OLED displays need smaller window patches to avoid ABL
        (Automatic Brightness Limiter) effects. Common values:
        - 10% window: Standard for HDR measurements
        - 18% window: Alternative for some displays

        Args:
            percent: Window size as percentage of display (10.0, 18.0, etc.)
        """
        pass

    def show_xyz(self, X: float, Y: float, Z: float) -> None:
        """
        Display a color patch with given XYZ values.

        This is a convenience method that converts XYZ to RGB.
        Implementations may override for better accuracy.

        Args:
            X: X tristimulus value
            Y: Y tristimulus value (luminance)
            Z: Z tristimulus value
        """
        # Default implementation: approximate RGB from XYZ
        # Real implementations should use proper conversion
        r = int(min(255, max(0, X * 2.5)))
        g = int(min(255, max(0, Y * 2.5)))
        b = int(min(255, max(0, Z * 2.5)))
        self.show_rgb(r, g, b)

    def show_black_frame(self, duration_ms: int = 100) -> None:
        """
        Display a black frame for OLED BFI (Black Frame Insertion).

        Used between measurements on OLED displays to prevent
        pixel aging and improve measurement stability.

        Args:
            duration_ms: Duration of black frame in milliseconds

        Note:
            Default implementation just shows black. Implementations
            should override for proper timed BFI.
        """
        self.show_rgb(0, 0, 0)


class FakeInstrument(InstrumentAdapter):
    """
    Fake instrument implementation for testing.

    This implementation does not require real hardware and can be
    configured with preset measurement results. Used for:
    - Unit testing without hardware
    - CI/CD testing
    - Development testing

    Example:
        >>> instrument = FakeInstrument()
        >>> instrument.set_measurement_result((95.0, 100.0, 108.9))
        >>> result = instrument.measure()
        >>> print(result.xyz)
        (95.0, 100.0, 108.9)
    """

    def __init__(
        self,
        model: str = "Fake Instrument",
        serial: str = "TEST-001",
        initial_status: Optional[InstrumentStatus] = None
    ):
        """
        Initialize fake instrument.

        Args:
            model: Instrument model name
            serial: Serial number
            initial_status: Optional initial status
        """
        self._model = model
        self._serial = serial
        self._connected = False
        self._calibrated = False
        self._calibration_time: Optional[datetime] = None
        self._measuring = False

        # Preset measurement results
        self._preset_xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._preset_xyY: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._measurement_results: Dict[str, Tuple] = {}

        # Error simulation
        self._simulate_error: bool = False
        self._error_code: str = ""
        self._error_message: str = ""

        # Status
        self._status = initial_status or InstrumentStatus(
            state=InstrumentState.DISCONNECTED,
            connected=False,
            model=model,
            serial=serial
        )

    def set_measurement_result(
        self,
        xyz: Tuple[float, float, float],
        xyY: Optional[Tuple[float, float, float]] = None
    ) -> None:
        """
        Set preset measurement result for next measure() call.

        Args:
            xyz: XYZ tristimulus values
            xyY: Optional xyY values (calculated from XYZ if not provided)
        """
        self._preset_xyz = xyz
        if xyY:
            self._preset_xyY = xyY
        else:
            # Calculate xyY from XYZ
            X, Y, Z = xyz
            total = X + Y + Z
            if total > 0:
                x = X / total
                y = Y / total
            else:
                x = 0.0
                y = 0.0
            self._preset_xyY = (x, y, Y)

    def set_measurement_for_rgb(
        self,
        rgb: Tuple[int, int, int],
        xyz: Tuple[float, float, float],
        xyY: Optional[Tuple[float, float, float]] = None
    ) -> None:
        """
        Set measurement result for specific RGB input.

        Args:
            rgb: RGB values that will trigger this result
            xyz: XYZ result for this RGB
            xyY: Optional xyY values
        """
        key = f"{rgb[0]}_{rgb[1]}_{rgb[2]}"
        self._measurement_results[key] = (xyz, xyY)

    def simulate_error(self, error_code: str, message: str) -> None:
        """
        Configure the instrument to simulate an error.

        Args:
            error_code: Error code to return
            message: Error message
        """
        self._simulate_error = True
        self._error_code = error_code
        self._error_message = message

    def clear_error(self) -> None:
        """Clear simulated error state."""
        self._simulate_error = False
        self._error_code = ""
        self._error_message = ""

    def connect(self) -> bool:
        """Simulate connecting to instrument."""
        if self._simulate_error:
            raise InstrumentError(
                message=self._error_message,
                error_code=self._error_code,
                instrument_id=self.instrument_id,
                recoverable=False
            )

        self._connected = True
        self._status = InstrumentStatus(
            state=InstrumentState.READY,
            connected=True,
            model=self._model,
            serial=self._serial
        )
        return True

    def disconnect(self) -> None:
        """Simulate disconnecting from instrument."""
        self._connected = False
        self._calibrated = False
        self._measuring = False
        self._status = InstrumentStatus(
            state=InstrumentState.DISCONNECTED,
            connected=False,
            model=self._model,
            serial=self._serial
        )

    def measure(self, timeout: float = 30.0) -> MeasurementResult:
        """Simulate taking a measurement."""
        if not self._connected:
            raise InstrumentError(
                message="Instrument not connected",
                error_code="NOT_CONNECTED",
                instrument_id=self.instrument_id,
                recoverable=True,
                suggestion="Call connect() before measure()"
            )

        if self._simulate_error:
            raise InstrumentError(
                message=self._error_message,
                error_code=self._error_code,
                instrument_id=self.instrument_id,
                recoverable=self._error_code in ["TIMEOUT", "MEASUREMENT_FAILED"]
            )

        return MeasurementResult(
            xyz=self._preset_xyz,
            xyY=self._preset_xyY,
            timestamp=datetime.now(),
            confidence=1.0,
            metadata={"fake": True, "timeout": timeout}
        )

    def calibrate(self, calibration_type: str = "standard") -> bool:
        """Simulate instrument calibration."""
        if not self._connected:
            raise InstrumentError(
                message="Instrument not connected",
                error_code="NOT_CONNECTED",
                instrument_id=self.instrument_id,
                recoverable=True
            )

        if self._simulate_error:
            raise InstrumentError(
                message=self._error_message,
                error_code=self._error_code,
                instrument_id=self.instrument_id,
                recoverable=False
            )

        self._calibrated = True
        self._calibration_time = datetime.now()
        self._status = InstrumentStatus(
            state=InstrumentState.READY,
            connected=True,
            model=self._model,
            serial=self._serial,
            last_calibration=self._calibration_time
        )
        return True

    def status(self) -> InstrumentStatus:
        """Get current fake instrument status."""
        return self._status

    @property
    def instrument_id(self) -> str:
        """Get fake instrument ID."""
        return f"{self._model}_{self._serial}"

    @property
    def instrument_type(self) -> str:
        """Get fake instrument type."""
        return self._model

    def reset(self) -> None:
        """Reset all preset values and state."""
        self._preset_xyz = (0.0, 0.0, 0.0)
        self._preset_xyY = (0.0, 0.0, 0.0)
        self._measurement_results.clear()
        self._simulate_error = False
        self._error_code = ""
        self._error_message = ""


class FakePatchPresenter(PatchPresenter):
    """
    Fake patch presenter implementation for testing.

    This implementation does not require GUI and simply tracks
    what colors were requested to display. Used for:
    - Unit testing without GUI
    - CI/CD testing
    - Development testing

    Example:
        >>> presenter = FakePatchPresenter()
        >>> presenter.show_rgb(255, 0, 0)
        >>> presenter.current_rgb
        (255, 0, 0)
        >>> presenter.display_history
        [(255, 0, 0)]
    """

    def __init__(
        self,
        display_id: int = 0,
        oled_window_percent: float = 100.0
    ):
        """
        Initialize fake patch presenter.

        Args:
            display_id: Target display ID
            oled_window_percent: Initial OLED window size
        """
        self._display_id = display_id
        self._oled_window_percent = oled_window_percent
        self._current_rgb: Tuple[int, int, int] = (0, 0, 0)
        self._visible = False
        self._display_history: list = []
        self._black_frame_count = 0

        # Error simulation
        self._simulate_error: bool = False
        self._error_message: str = ""

    def show_rgb(self, r: int, g: int, b: int) -> None:
        """Record color request without actual display."""
        if self._simulate_error:
            raise PatchDisplayError(
                message=self._error_message,
                display_id=self._display_id,
                rgb_requested=(r, g, b)
            )

        self._current_rgb = (r, g, b)
        self._visible = True
        self._display_history.append((r, g, b))

    def hide(self) -> None:
        """Record hide request."""
        self._visible = False
        self._current_rgb = (0, 0, 0)

    def target_display_id(self) -> int:
        """Return target display ID."""
        return self._display_id

    def set_oled_window_size(self, percent: float) -> None:
        """Set OLED window size percentage."""
        self._oled_window_percent = percent

    def show_black_frame(self, duration_ms: int = 100) -> None:
        """Record black frame insertion."""
        self.show_rgb(0, 0, 0)
        self._black_frame_count += 1

    @property
    def current_rgb(self) -> Tuple[int, int, int]:
        """Get current RGB being displayed."""
        return self._current_rgb

    @property
    def is_visible(self) -> bool:
        """Check if patch is currently visible."""
        return self._visible

    @property
    def display_history(self) -> list:
        """Get history of all displayed colors."""
        return self._display_history.copy()

    @property
    def black_frame_count(self) -> int:
        """Get count of black frames shown."""
        return self._black_frame_count

    @property
    def oled_window_percent(self) -> float:
        """Get current OLED window size."""
        return self._oled_window_percent

    def simulate_error(self, message: str) -> None:
        """Configure to simulate display error."""
        self._simulate_error = True
        self._error_message = message

    def clear_error(self) -> None:
        """Clear simulated error."""
        self._simulate_error = False
        self._error_message = ""

    def reset(self) -> None:
        """Reset all tracking state."""
        self._current_rgb = (0, 0, 0)
        self._visible = False
        self._display_history.clear()
        self._black_frame_count = 0
        self._simulate_error = False
        self._error_message = ""
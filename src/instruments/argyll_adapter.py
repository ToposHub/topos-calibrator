"""
ArgyllAdapter - Complete InstrumentAdapter implementation for ArgyllCMS.

This adapter wraps ArgyllController to provide:
- InstrumentAdapter interface compliance
- Standardized command construction via dataclass parameters
- Output parsing with user-friendly error mapping
- Process lifecycle management (start, cancel, timeout, cleanup)

Thread Safety:
    Like ArgyllController, this adapter is NOT thread-safe. All operations
    should be performed on the Qt main thread or through proper signal/slot
    mechanism.

Reference:
- src/argyll_controller.py (wrapped implementation)
- src/instruments/base.py (interface definition)
- src/instruments/argyll_params.py (parameter dataclasses)
- docs/agent_handoffs/P0-C_argyll_audit.md
"""

import logging
import re
import time
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from .base import (
    InstrumentAdapter,
    InstrumentError,
    InstrumentStatus,
    InstrumentState,
    MeasurementResult,
    PatchPresenter,
    PatchDisplayError,
)
from .argyll_params import (
    SpotreadParams,
    DispcalParams,
    TargenParams,
    ColprofParams,
    CollinkParams,
    ArgyllErrorMapping,
    map_error_to_suggestion,
    DisplayType,
    ProbeType,
    QualityLevel,
    RenderingIntent,
)


logger = logging.getLogger(__name__)


# ========== Output Parsing Patterns ==========

class OutputPatterns:
    """Regular expressions for parsing ArgyllCMS output."""

    # spotread XYZ measurement result
    XYZ_RESULT = re.compile(
        r'Result is XYZ:\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)',
        re.IGNORECASE
    )

    # spotread Yxy format (backup)
    YXY_RESULT = re.compile(
        r'Yxy:\s*Y\s*=\s*([\d.]+),\s*x\s*=\s*([\d.]+),\s*y\s*=\s*([\d.]+)',
        re.IGNORECASE
    )

    # dispcal progress
    DISPCAL_PROGRESS = re.compile(
        r'patch\s+(\d+)\s+of\s+(\d+)',
        re.IGNORECASE
    )

    # dispcal web server URL
    DISPCAL_WEB_URL = re.compile(
        r"'(http://[^']+)'"
    )

    # dispcal calibration written
    DISPCAL_WRITTEN = re.compile(
        r"Written.*'([^']+\.cal)'"
    )

    # targen patches created
    TARGET_PATCHES = re.compile(
        r'Created\s+(\d+)\s+patches',
        re.IGNORECASE
    )

    # targen NUMBER_OF_SETS
    TI1_SETS = re.compile(
        r'NUMBER_OF_SETS\s+(\d+)',
        re.IGNORECASE
    )

    # colprof progress (various formats)
    COLPROF_PROGRESS = re.compile(
        r'(?:(?:Progress|Done)[:\s]+)?(\d+)%',
        re.IGNORECASE
    )

    # colprof profile created
    COLPROF_CREATED = re.compile(
        r"Created profile '([^']+\.icc)'"
    )

    # collink progress
    COLLINK_PROGRESS = re.compile(
        r'Making lookup tables - (\d+)% done',
        re.IGNORECASE
    )

    # collink LUT created
    COLLINK_CREATED = re.compile(
        r"Created.*'([^']+\.cube)'"
    )

    # device enumeration
    DEVICE_ENUM = re.compile(
        r"^\s*(\d+)\s*=\s*['\"]?([^'\"\n]+)['\"]?\s*$",
        re.MULTILINE
    )

    # USB disconnect keywords
    USB_DISCONNECT_KEYWORDS = [
        'readpipeasync failed',
        'read pipe async',
        'no instrument found',
        'instrument not found',
        'usb error',
        'communication error',
        'device not found',
    ]

    # Hardware error keywords
    ERROR_KEYWORDS = [
        'spot read failed',
        'sensor being in the wrong position',
        'wrong position',
        'ambient filter should be removed',
        'ambient filter',
        'filter should be',
        'no instrument found',
        'instrument not found',
        'communication error',
        'usb error',
        'device not found',
        'access denied',
        'permission denied',
        'failed to open',
        'calibration failed',
        'readpipeasync failed',
        'read pipe',
    ]


class ParseResult:
    """Result from parsing ArgyllCMS output."""

    def __init__(
        self,
        success: bool = False,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        progress: Optional[int] = None,
        stage: Optional[str] = None,
    ):
        self.success = success
        self.data = data or {}
        self.error = error
        self.progress = progress
        self.stage = stage


# ========== Output Parsers ==========

class OutputParser:
    """
    Parser for ArgyllCMS tool output.

    Provides methods to parse output from each ArgyllCMS tool:
    - parse_spotread: spotread measurement results
    - parse_dispcal: dispcal progress and completion
    - parse_targen: targen patch count
    - parse_colprof: colprof progress and completion
    - parse_collink: collink progress and completion
    """

    @staticmethod
    def parse_spotread(output: str) -> ParseResult:
        """
        Parse spotread output for measurement results.

        Args:
            output: Raw output from spotread

        Returns:
            ParseResult with XYZ/xyY values or error
        """
        # Check for errors first
        for keyword in OutputPatterns.ERROR_KEYWORDS:
            if keyword.lower() in output.lower():
                mapping = map_error_to_suggestion(output)
                return ParseResult(
                    success=False,
                    error=mapping.user_message,
                    data={'recoverable': mapping.recoverable, 'action': mapping.action}
                )

        # Try XYZ format first
        xyz_match = OutputPatterns.XYZ_RESULT.search(output)
        if xyz_match:
            try:
                X = float(xyz_match.group(1))
                Y = float(xyz_match.group(2))
                Z = float(xyz_match.group(3))

                # Convert XYZ to xyY
                xyz_sum = X + Y + Z
                if xyz_sum > 0:
                    x = X / xyz_sum
                    y = Y / xyz_sum
                    xyY = (x, y, Y)
                    xyz = (X, Y, Z)
                    return ParseResult(
                        success=True,
                        data={'xyz': xyz, 'xyY': xyY, 'Y': Y}
                    )
            except (ValueError, ZeroDivisionError) as e:
                logger.error(f"Failed to parse XYZ values: {e}")

        # Try Yxy format as backup
        yxy_match = OutputPatterns.YXY_RESULT.search(output)
        if yxy_match:
            try:
                Y = float(yxy_match.group(1))
                x = float(yxy_match.group(2))
                y = float(yxy_match.group(3))
                # Convert xyY to XYZ
                if y > 0:
                    X = x * Y / y
                    Z = (1 - x - y) * Y / y
                    return ParseResult(
                        success=True,
                        data={'xyz': (X, Y, Z), 'xyY': (x, y, Y), 'Y': Y}
                    )
            except (ValueError, ZeroDivisionError) as e:
                logger.error(f"Failed to parse Yxy values: {e}")

        return ParseResult(success=False, error="No measurement result found")

    @staticmethod
    def parse_dispcal(output: str) -> ParseResult:
        """
        Parse dispcal output for progress and completion.

        Args:
            output: Raw output from dispcal

        Returns:
            ParseResult with progress, web URL, or completion status
        """
        # Check for completion
        written_match = OutputPatterns.DISPCAL_WRITTEN.search(output)
        if written_match:
            cal_file = written_match.group(1)
            return ParseResult(
                success=True,
                data={'cal_file': cal_file, 'complete': True},
                progress=100,
                stage='complete'
            )

        # Check for web server URL
        url_match = OutputPatterns.DISPCAL_WEB_URL.search(output)
        if url_match:
            url = url_match.group(1)
            return ParseResult(
                success=True,
                data={'web_url': url},
                stage='web_server_ready'
            )

        # Parse progress
        progress_match = OutputPatterns.DISPCAL_PROGRESS.search(output)
        if progress_match:
            current = int(progress_match.group(1))
            total = int(progress_match.group(2))
            # Progress mapping: 15-70% range for patch reading
            progress_pct = 15 + int(55 * current / total)
            return ParseResult(
                success=True,
                data={'current_patch': current, 'total_patches': total},
                progress=progress_pct,
                stage='measuring_patches'
            )

        # Check for stages
        output_lower = output.lower()
        if 'commencing display calibration' in output_lower:
            return ParseResult(success=True, progress=15, stage='starting')
        if 'computing calibration curves' in output_lower:
            return ParseResult(success=True, progress=70, stage='computing')
        if 'creating vcgt' in output_lower:
            return ParseResult(success=True, progress=80, stage='vcgt')

        return ParseResult(success=True, stage='running')

    @staticmethod
    def parse_targen(output: str) -> ParseResult:
        """
        Parse targen output for patch count.

        Args:
            output: Raw output from targen

        Returns:
            ParseResult with created patch count
        """
        # Check for NUMBER_OF_SETS
        sets_match = OutputPatterns.TI1_SETS.search(output)
        if sets_match:
            count = int(sets_match.group(1))
            return ParseResult(
                success=True,
                data={'patch_count': count, 'complete': True},
                progress=100,
                stage='complete'
            )

        # Check for created patches (progress)
        patches_match = OutputPatterns.TARGET_PATCHES.search(output)
        if patches_match:
            count = int(patches_match.group(1))
            return ParseResult(
                success=True,
                data={'created_patches': count},
                progress=50,
                stage='generating'
            )

        return ParseResult(success=True, stage='running')

    @staticmethod
    def parse_colprof(output: str) -> ParseResult:
        """
        Parse colprof output for progress and completion.

        Args:
            output: Raw output from colprof

        Returns:
            ParseResult with progress or ICC file path
        """
        # Check for completion
        created_match = OutputPatterns.COLPROF_CREATED.search(output)
        if created_match:
            icc_file = created_match.group(1)
            return ParseResult(
                success=True,
                data={'icc_file': icc_file, 'complete': True},
                progress=100,
                stage='complete'
            )

        # Parse progress percentage
        progress_match = OutputPatterns.COLPROF_PROGRESS.search(output)
        if progress_match:
            progress_pct = int(progress_match.group(1))
            return ParseResult(
                success=True,
                progress=progress_pct,
                stage='building_lut'
            )

        # Check for stages
        output_lower = output.lower()
        if 'reading measurement data' in output_lower:
            return ParseResult(success=True, progress=5, stage='reading')
        if 'building forward lookup' in output_lower:
            return ParseResult(success=True, progress=20, stage='forward_lut')
        if 'computing inverse lookup' in output_lower:
            return ParseResult(success=True, progress=50, stage='inverse_lut')
        if 'creating a2b0' in output_lower:
            return ParseResult(success=True, progress=70, stage='a2b0')
        if 'creating b2a0' in output_lower:
            return ParseResult(success=True, progress=80, stage='b2a0')
        if 'smoothing' in output_lower:
            return ParseResult(success=True, progress=85, stage='smoothing')
        if 'writing' in output_lower:
            return ParseResult(success=True, progress=95, stage='writing')

        return ParseResult(success=True, stage='running')

    @staticmethod
    def parse_collink(output: str) -> ParseResult:
        """
        Parse collink output for progress and completion.

        Args:
            output: Raw output from collink

        Returns:
            ParseResult with progress or cube file path
        """
        # Check for completion
        created_match = OutputPatterns.COLLINK_CREATED.search(output)
        if created_match:
            cube_file = created_match.group(1)
            return ParseResult(
                success=True,
                data={'cube_file': cube_file, 'complete': True},
                progress=100,
                stage='complete'
            )

        # Parse progress percentage
        progress_match = OutputPatterns.COLLINK_PROGRESS.search(output)
        if progress_match:
            progress_pct = int(progress_match.group(1))
            return ParseResult(
                success=True,
                progress=progress_pct,
                stage='building_lut'
            )

        return ParseResult(success=True, stage='running')


# ========== Process Lifecycle Manager ==========

class ProcessLifecycle:
    """
    Manages process lifecycle: start, cancel, timeout, cleanup.

    This class provides unified process management for all ArgyllCMS tools.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        cancel_timeout: float = 2.0,
        cleanup_timeout: float = 5.0,
    ):
        self.timeout = timeout
        self.cancel_timeout = cancel_timeout
        self.cleanup_timeout = cleanup_timeout
        self._process: Optional[Any] = None
        self._start_time: Optional[float] = None
        self._cancelled: bool = False

    def start(self, process: Any) -> None:
        """
        Start tracking a process.

        Args:
            process: subprocess.Popen instance
        """
        self._process = process
        self._start_time = time.time()
        self._cancelled = False
        logger.debug(f"Process started: PID={process.pid}")

    def is_timeout(self) -> bool:
        """Check if process has exceeded timeout."""
        if self._start_time is None:
            return False
        elapsed = time.time() - self._start_time
        return elapsed > self.timeout

    def cancel(self) -> bool:
        """
        Cancel the running process.

        Returns:
            True if process was cancelled successfully
        """
        if self._process is None or self._process.poll() is not None:
            return True

        self._cancelled = True
        logger.info("Cancelling process...")

        try:
            # Graceful termination
            self._process.terminate()
            self._process.wait(timeout=self.cancel_timeout)
            logger.info("Process terminated gracefully")
            return True
        except Exception:
            # Force kill
            try:
                self._process.kill()
                self._process.wait(timeout=self.cancel_timeout)
                logger.info("Process killed")
                return True
            except Exception as e:
                logger.error(f"Failed to kill process: {e}")
                return False

    def cleanup(self) -> None:
        """
        Cleanup process resources.

        This should be called after process completion or cancellation.
        """
        if self._process is None:
            return

        # Ensure process is terminated
        if self._process.poll() is None:
            self.cancel()

        self._process = None
        self._start_time = None
        logger.debug("Process cleanup complete")

    def get_elapsed_time(self) -> float:
        """Get elapsed time since process start."""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    def is_running(self) -> bool:
        """Check if process is still running."""
        if self._process is None:
            return False
        return self._process.poll() is None

    @property
    def was_cancelled(self) -> bool:
        """Check if process was cancelled by user."""
        return self._cancelled


# ========== ArgyllAdapter Implementation ==========

class ArgyllAdapter(InstrumentAdapter):
    """
    Complete InstrumentAdapter implementation wrapping ArgyllController.

    This adapter provides:
    1. InstrumentAdapter interface compliance for MeasurementService
    2. Standardized command construction via dataclass parameters
    3. Output parsing with user-friendly error mapping
    4. Process lifecycle management

    Example:
        >>> from src.argyll_controller import ArgyllController
        >>> controller = ArgyllController()
        >>> adapter = ArgyllAdapter(controller)
        >>> adapter.connect()
        >>> result = adapter.measure()
        >>> print(result.xyY)
    """

    def __init__(self, controller: 'ArgyllController'):
        """
        Initialize adapter with existing ArgyllController.

        Args:
            controller: ArgyllController instance to wrap
        """
        self._controller = controller
        self._last_result: Optional[MeasurementResult] = None
        self._measurement_callbacks: List[Callable] = []
        self._waiting_for_result = False
        self._result_timeout = 30.0

        # Process lifecycle manager
        self._lifecycle = ProcessLifecycle()

        # Output parser
        self._parser = OutputParser()

        # Register callbacks (ArgyllController 只暴露 set_callbacks，无逐事件注册方法)
        self._controller.set_callbacks(
            on_measurement=self._handle_measurement_result,
            on_error=self._handle_error,
        )

    def _handle_measurement_result(self, result):
        """Handle measurement result callback from ArgyllController.

        Args:
            result: (x, y, Y) tuple as emitted by ArgyllController.
        """
        x, y, Y = result
        self._last_result = MeasurementResult(
            xyz=self._xyY_to_xyz(x, y, Y),
            xyY=(x, y, Y),
            timestamp=datetime.now(),
            confidence=1.0,
            metadata={"source": "argyll"}
        )
        self._waiting_for_result = False

    def _handle_disconnect(self):
        """Handle disconnect callback from ArgyllController."""
        logger.warning("ArgyllAdapter: Instrument disconnected")
        self._lifecycle.cleanup()

    def _handle_error(self, error_message: str):
        """Handle error callback from ArgyllController."""
        logger.error(f"ArgyllAdapter: Instrument error: {error_message}")
        self._waiting_for_result = False
        # Map error to user-friendly message
        mapping = map_error_to_suggestion(error_message)
        logger.info(f"Error mapping: {mapping.user_message} (action: {mapping.action})")

    def _xyY_to_xyz(self, x: float, y: float, Y: float) -> Tuple[float, float, float]:
        """Convert xyY to XYZ tristimulus values."""
        if y == 0:
            return (0.0, Y, 0.0)
        X = x * Y / y
        Z = (1 - x - y) * Y / y
        return (X, Y, Z)

    # ========== InstrumentAdapter Interface Implementation ==========

    def connect(self) -> bool:
        """
        Connect to measurement instrument via ArgyllController.

        Returns:
            True if connection successful

        Raises:
            InstrumentError: If connection fails
        """
        try:
            success = self._controller.connect()
            if not success:
                error_msg = self._controller.get_error_message()
                mapping = map_error_to_suggestion(error_msg)
                raise InstrumentError(
                    message=mapping.user_message,
                    error_code="CONNECT_FAILED",
                    instrument_id=self.instrument_id,
                    recoverable=mapping.recoverable,
                    suggestion=mapping.action
                )
            return True

        except Exception as e:
            mapping = map_error_to_suggestion(str(e))
            raise InstrumentError(
                message=mapping.user_message,
                error_code="CONNECT_EXCEPTION",
                instrument_id=self.instrument_id,
                recoverable=mapping.recoverable
            )

    def disconnect(self) -> None:
        """Disconnect from measurement instrument."""
        self._controller.disconnect()
        self._lifecycle.cleanup()
        self._last_result = None

    def measure(self, timeout: float = 30.0) -> MeasurementResult:
        """
        Perform a color measurement.

        This method triggers a measurement and waits for the result.
        ArgyllController.measure() is non-blocking, so we poll/wait.

        Args:
            timeout: Maximum time to wait for measurement (seconds)

        Returns:
            MeasurementResult containing XYZ/xyY values

        Raises:
            InstrumentError: If measurement fails or times out
        """
        if not self.is_connected():
            raise InstrumentError(
                message="Instrument not connected",
                error_code="NOT_CONNECTED",
                instrument_id=self.instrument_id,
                recoverable=True,
                suggestion="Call connect() before measure()"
            )

        # Clear previous result
        self._last_result = None
        self._waiting_for_result = True
        self._result_timeout = timeout

        # Trigger measurement
        success = self._controller.measure()
        if not success:
            error_msg = self._controller.get_error_message()
            mapping = map_error_to_suggestion(error_msg)
            raise InstrumentError(
                message=mapping.user_message,
                error_code="MEASURE_TRIGGER_FAILED",
                instrument_id=self.instrument_id,
                recoverable=mapping.recoverable,
                suggestion=mapping.action
            )

        # Wait for result with timeout
        start_time = time.time()
        while self._waiting_for_result and (time.time() - start_time) < timeout:
            time.sleep(0.05)  # 50ms poll interval

            # Check if disconnected
            if not self._controller.is_connected():
                raise InstrumentError(
                    message="Instrument disconnected during measurement",
                    error_code="DISCONNECTED_DURING_MEASURE",
                    instrument_id=self.instrument_id,
                    recoverable=True,
                    suggestion="Reconnect instrument and retry"
                )

        # Check if we got a result
        if self._last_result is None:
            raise InstrumentError(
                message="Measurement timeout",
                error_code="TIMEOUT",
                instrument_id=self.instrument_id,
                recoverable=True,
                suggestion="Check instrument response and retry"
            )

        return self._last_result

    def calibrate(self, calibration_type: str = "standard") -> bool:
        """
        Perform instrument calibration.

        Args:
            calibration_type: Type of calibration ("standard", "white", "dark")

        Returns:
            True if calibration successful

        Raises:
            InstrumentError: If calibration fails
        """
        if not self.is_connected():
            raise InstrumentError(
                message="Instrument not connected",
                error_code="NOT_CONNECTED",
                instrument_id=self.instrument_id,
                recoverable=True
            )

        success = self._controller.calibrate()
        if not success:
            error_msg = self._controller.get_error_message()
            mapping = map_error_to_suggestion(error_msg)
            raise InstrumentError(
                message=mapping.user_message,
                error_code="CALIBRATE_FAILED",
                instrument_id=self.instrument_id,
                recoverable=mapping.recoverable,
                suggestion=mapping.action
            )

        return True

    def status(self) -> InstrumentStatus:
        """
        Get current instrument status.

        Returns:
            InstrumentStatus with current state, model, serial, etc.
        """
        connected = self._controller.is_connected()
        measuring = self._controller.is_measuring()
        reconnecting = self._controller.is_reconnecting()

        # Determine state
        if reconnecting:
            state = InstrumentState.CONNECTING
        elif measuring:
            state = InstrumentState.MEASURING
        elif connected:
            state = InstrumentState.READY
        else:
            state = InstrumentState.DISCONNECTED

        # Get instrument info
        probe_type = self._controller.get_probe_type()

        return InstrumentStatus(
            state=state,
            connected=connected,
            model=probe_type.value if probe_type else "",
            serial="",  # ArgyllController doesn't track serial
            correction_file=self._controller.get_correction_file_path(),
            error_message=self._controller.get_error_message() if not connected else ""
        )

    @property
    def instrument_id(self) -> str:
        """Get unique identifier for this instrument."""
        probe_type = self._controller.get_probe_type()
        port = self._controller.get_instrument_port()
        if probe_type and port:
            return f"{probe_type.value}_{port}"
        return "argyll_unknown"

    @property
    def instrument_type(self) -> str:
        """Get instrument type/model name."""
        probe_type = self._controller.get_probe_type()
        return probe_type.value if probe_type else "unknown"

    # ========== Extended Methods for ArgyllCMS Tools ==========

    def configure(self, params: SpotreadParams) -> bool:
        """
        Configure the adapter with SpotreadParams.

        Args:
            params: SpotreadParams dataclass instance

        Returns:
            True if configuration successful
        """
        valid, error = params.validate()
        if not valid:
            logger.error(f"Invalid SpotreadParams: {error}")
            return False

        # Apply configuration to controller
        self._controller.set_display_type(params.display_type)

        if params.instrument_port:
            self._controller._instrument_port = params.instrument_port

        if params.correction_file:
            self._controller.set_correction_file(params.correction_file)

        return True

    def parse_output(self, tool: str, output: str) -> ParseResult:
        """
        Parse output from an ArgyllCMS tool.

        Args:
            tool: Tool name (spotread, dispcal, targen, colprof, collink)
            output: Raw output string

        Returns:
            ParseResult with parsed data
        """
        parser_map = {
            'spotread': OutputParser.parse_spotread,
            'dispcal': OutputParser.parse_dispcal,
            'targen': OutputParser.parse_targen,
            'colprof': OutputParser.parse_colprof,
            'collink': OutputParser.parse_collink,
        }

        parser_func = parser_map.get(tool.lower())
        if parser_func:
            return parser_func(output)

        return ParseResult(success=False, error=f"Unknown tool: {tool}")

    # ========== Utility Methods ==========

    def set_correction_file(self, path: str) -> None:
        """Set spectral correction file (CCSS/CCMX)."""
        self._controller.set_correction_file(path)

    def set_display_type(self, display_type: DisplayType) -> None:
        """Set display type for measurement optimization."""
        self._controller.set_display_type(display_type)

    def set_probe_type(self, probe_type: ProbeType) -> None:
        """Set probe/instrument type."""
        self._controller.set_probe_type(probe_type)

    def get_recommended_delay(self) -> int:
        """Get recommended measurement delay in milliseconds."""
        return self._controller.get_recommended_delay()

    def set_current_patch_rgb(self, rgb: Tuple[int, int, int]) -> None:
        """Set current patch RGB for delay calculation."""
        self._controller.set_current_patch_rgb(rgb)

    def reconnect(self) -> bool:
        """Attempt to reconnect after disconnect."""
        return self._controller.reconnect()

    def is_reconnecting(self) -> bool:
        """Check if adapter is in reconnecting state."""
        return self._controller.is_reconnecting()

    # ========== Callback Registration ==========

    def on_measurement(self, callback: Callable) -> None:
        """Register measurement result callback."""
        self._measurement_callbacks.append(callback)

    def on_disconnect(self, callback: Callable) -> None:
        """Register disconnect callback."""
        self._controller.on_disconnect(callback)

    def on_error(self, callback: Callable) -> None:
        """Register error callback."""
        self._controller.on_error(callback)


# ========== Factory Function ==========

def create_argyll_adapter(controller: Optional['ArgyllController'] = None) -> ArgyllAdapter:
    """
    Create an ArgyllAdapter instance.

    Args:
        controller: Optional ArgyllController instance.
                   If None, a new one will be created.

    Returns:
        ArgyllAdapter instance
    """
    if controller is None:
        # Import here to avoid circular dependency
        from src.argyll_controller import ArgyllController
        controller = ArgyllController()

    return ArgyllAdapter(controller)
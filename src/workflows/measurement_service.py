"""
Measurement Service - Core orchestration for color measurements.

This service implements the measurement workflow:
- Display color patch -> Wait for stabilization -> Trigger measurement ->
  Receive result -> Store -> Next patch

Key features:
- Integrates with state machine (src/core/state.py)
- Supports dark sample multi-sampling (multiple measurements for dark patches)
- Supports OLED black frame insertion (BFI) between measurements
- Supports checkpoint/resume for instrument disconnection recovery
- Uses InstrumentAdapter and PatchPresenter interfaces for abstraction
- Supports repeatability analysis and threshold-based remeasurement prompts

Reference:
- docs/agent_handoffs/P0-A_architecture_audit.md (architecture context)
- docs/agent_handoffs/P1-A_state_machine.md (state machine integration)
- docs/agent_handoffs/P3-A_statistics.md (repeatability analysis)
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core.events import (
    Event,
    StartRequested,
    PrecheckPassed,
    PrecheckFailed,
    InstrumentConnected,
    PatchDisplayed,
    MeasurementReceived,
    InstrumentDisconnected,
    ResumeRequested,
    StopRequested,
    WorkflowFailed,
    CalibrationCompleted,
    ProfileGenerated,
    AllPatchesCompleted,
)
from src.core.state import (
    MeasurementStateMachine,
    MeasurementState,
    TransitionResult,
    start_session,
    complete_precheck,
    fail_precheck,
    connect_instrument,
    disconnect_instrument,
    resume_session,
    stop_session,
    fail_workflow,
)
from src.instruments.base import (
    InstrumentAdapter,
    InstrumentError,
    InstrumentStatus,
    InstrumentState,
    MeasurementResult,
    PatchPresenter,
    PatchDisplayError,
    RawReading,
)
from src.color_science.statistics import (
    SingleMeasurement,
    MeasurementStatistics,
    RepeatabilityThreshold,
    RepeatabilityResult,
    PatchRepeatabilityRecord,
    SessionRepeatabilitySummary,
    MeasurementStatus as RepeatabilityStatus,
    AveragingMethod,
    calculate_measurement_statistics,
    evaluate_repeatability,
    generate_repeatability_summary,
    create_single_measurement,
    get_luminance_level,
    # New imports for reliability features
    OutlierRejectionMethod,
    OutlierDetectionResult,
    PatchMeasurementPolicy,
    LuminanceLevel,
    detect_outliers,
    get_luminance_policy,
    get_luminance_level_enum,
    calculate_confidence_score,
    get_measurement_quality_status,
    xyz_to_xyY,
)


logger = logging.getLogger(__name__)


class MeasurementServiceError(Exception):
    """
    Exception raised when measurement service operation fails.

    Attributes:
        error_code: Machine-readable error code
        state: State the service was in when error occurred
        recoverable: Whether error can be recovered from
    """
    def __init__(
        self,
        message: str,
        error_code: str = "UNKNOWN",
        state: Optional[MeasurementState] = None,
        recoverable: bool = False
    ):
        super().__init__(message)
        self.error_code = error_code
        self.state = state
        self.recoverable = recoverable


@dataclass
class DarkSampleConfig:
    """
    Configuration for dark sample multi-sampling.

    Dark samples (below threshold) may need multiple measurements
    for accurate results due to instrument noise at low luminance.

    Attributes:
        threshold: Luminance threshold in cd/m^2 (default 0.2)
        sample_count: Number of samples to take (default 3)
        use_xyz_average: Use XYZ linear averaging (default True)
        max_retries: Maximum retry attempts per sample (default 2)
        integration_time_factor: Integration time multiplier for dark (default 2.0)
        confidence_threshold: Minimum confidence for dark samples (default 0.5)
    """
    threshold: float = 0.2
    sample_count: int = 3
    use_xyz_average: bool = True
    max_retries: int = 2
    integration_time_factor: float = 2.0
    confidence_threshold: float = 0.5


@dataclass
class OLEDConfig:
    """
    Configuration for OLED-specific measurement behavior.

    OLED displays may need special handling:
    - Black frame insertion (BFI) to prevent pixel aging
    - Window patches to avoid ABL (Automatic Brightness Limiter)
    - Extended settling time for low luminance patches

    Attributes:
        enabled: OLED mode enabled
        black_frame_duration_ms: Duration of black frame (default 100ms)
        black_frame_threshold: Brightness delta to trigger BFI (default 0.3)
        window_size_percent: Window patch size (default 10%)
        extended_settling_ms: Extra settling time for OLED (default 500ms)
        stabilization_delay_ms: Additional delay for OLED stabilization (default 200ms)
    """
    enabled: bool = False
    black_frame_duration_ms: int = 100
    black_frame_threshold: float = 0.3
    window_size_percent: float = 10.0
    extended_settling_ms: int = 500
    stabilization_delay_ms: int = 200


@dataclass
class MiniLEDConfig:
    """
    Configuration for MiniLED-specific measurement behavior.

    MiniLED displays may need special handling:
    - Extended settling time due to local dimming zones
    - Higher repeat count for stability

    Attributes:
        enabled: MiniLED mode enabled
        settling_time_ms: Base settling time (default 400ms)
        stabilization_delay_ms: Additional stabilization delay (default 300ms)
        repeat_count: Recommended repeat count for MiniLED (default 3)
    """
    enabled: bool = False
    settling_time_ms: int = 400
    stabilization_delay_ms: int = 300
    repeat_count: int = 3


@dataclass
class WarmupConfig:
    """
    Configuration for instrument warm-up.

    Many measurement instruments need warm-up time for stable readings.

    Attributes:
        enabled: Enable warm-up checks
        warmup_time_ms: Warm-up duration in milliseconds (default 60000)
        warmup_readings: Number of warm-up readings to take (default 5)
        warmup_interval_ms: Interval between warm-up readings (default 10000)
        stability_threshold: Y stability threshold for warm-up pass (default 0.1)
        skip_if_already_warm: Skip warm-up if instrument already stable
    """
    enabled: bool = True
    warmup_time_ms: int = 60000  # 60 seconds
    warmup_readings: int = 5
    warmup_interval_ms: int = 10000  # 10 seconds between readings
    stability_threshold: float = 0.1  # cd/m² Y stability
    skip_if_already_warm: bool = True


@dataclass
class InstrumentRecoveryConfig:
    """
    Configuration for instrument disconnection recovery.

    Handles unexpected disconnections during measurement.

    Attributes:
        enabled: Enable recovery features
        max_reconnect_attempts: Maximum reconnect attempts (default 3)
        reconnect_delay_ms: Delay between reconnect attempts (default 2000)
        save_checkpoint_on_disconnect: Auto-save checkpoint on disconnect
        auto_resume_after_reconnect: Auto-resume after successful reconnect
        dark_sample_after_reconnect: Take dark sample after reconnect
    """
    enabled: bool = True
    max_reconnect_attempts: int = 3
    reconnect_delay_ms: int = 2000
    save_checkpoint_on_disconnect: bool = True
    auto_resume_after_reconnect: bool = False
    dark_sample_after_reconnect: bool = True


@dataclass
class ReliabilityConfig:
    """
    Configuration for measurement reliability features.

    Controls outlier rejection, confidence thresholds, and per-patch policies.

    Attributes:
        default_outlier_method: Default outlier rejection method (default MAD)
        outlier_threshold: Default outlier threshold (default 3.0)
        confidence_threshold: Minimum confidence for all measurements (default 0.7)
        min_accepted_readings: Minimum accepted readings per patch (default 2)
        adaptive_policy: Use adaptive per-patch policy based on luminance
        reject_high_outlier_ratio: Reject patch if outlier ratio > threshold (default 0.5)
        patch_policies: Custom per-patch policy overrides (patch_index -> policy)
    """
    default_outlier_method: OutlierRejectionMethod = OutlierRejectionMethod.MAD
    outlier_threshold: float = 3.0
    confidence_threshold: float = 0.7
    min_accepted_readings: int = 2
    adaptive_policy: bool = True
    reject_high_outlier_ratio: float = 0.5
    patch_policies: Dict[int, PatchMeasurementPolicy] = field(default_factory=dict)


@dataclass
class RepeatMeasureConfig:
    """
    Configuration for repeat measurement and repeatability analysis.

    Key patches may need multiple measurements for:
    - Verifying measurement stability
    - Detecting instrument drift
    - Ensuring accuracy for critical colors

    Attributes:
        enabled: Enable repeat measurement mode
        repeat_count: Number of measurements per patch (default 3)
        apply_to_all: Apply repeat measurement to all patches (default False)
        key_patches_only: Only repeat key patches (primary/secondary/white/black)
        threshold: Repeatability threshold for pass/fail judgment
        auto_prompt_remeasure: Automatically prompt UI when threshold exceeded
        max_remeasure_attempts: Maximum remeasurement attempts per patch
        key_patch_indices: Indices of key patches (if key_patches_only=True)
        outlier_rejection: Enable outlier rejection (default True)
        outlier_method: Outlier rejection method (default MAD)
    """
    enabled: bool = False
    repeat_count: int = 3
    apply_to_all: bool = False
    key_patches_only: bool = True
    threshold: RepeatabilityThreshold = field(default_factory=RepeatabilityThreshold)
    auto_prompt_remeasure: bool = True
    max_remeasure_attempts: int = 2
    key_patch_indices: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    outlier_rejection: bool = True
    outlier_method: OutlierRejectionMethod = OutlierRejectionMethod.MAD


@dataclass
class MeasurementConfig:
    """
    Configuration for a measurement session.

    Attributes:
        measure_mode: Measurement mode (gamut, icc, lut, custom)
        settling_time_ms: Time to wait after displaying patch (default 300ms)
        dark_sample: Dark sample configuration
        oled: OLED-specific configuration
        repeat_measure: Repeat measurement configuration
        reliability: Reliability and confidence configuration
        warmup: Instrument warm-up configuration
        recovery: Disconnection recovery configuration
        auto_calibrate: Automatically calibrate instrument before session
        auto_reconnect: Automatically reconnect if instrument disconnects
        save_checkpoints: Save checkpoint data for resume capability
        confidence_threshold: Minimum confidence for accepting measurement (default 0.7)
    """
    measure_mode: str = "gamut"
    settling_time_ms: int = 300
    dark_sample: DarkSampleConfig = field(default_factory=DarkSampleConfig)
    oled: OLEDConfig = field(default_factory=OLEDConfig)
    repeat_measure: RepeatMeasureConfig = field(default_factory=RepeatMeasureConfig)
    reliability: ReliabilityConfig = field(default_factory=ReliabilityConfig)
    warmup: WarmupConfig = field(default_factory=WarmupConfig)
    recovery: InstrumentRecoveryConfig = field(default_factory=InstrumentRecoveryConfig)
    auto_calibrate: bool = True
    auto_reconnect: bool = True
    save_checkpoints: bool = True
    confidence_threshold: float = 0.7


@dataclass
class CheckpointData:
    """
    Data for resuming a measurement session from interruption.

    Attributes:
        session_id: Unique session identifier
        patch_queue: Remaining patches to measure
        completed_results: Already measured results
        current_patch_index: Index of last attempted patch
        current_patch_rgb: RGB of last attempted patch
        config: Measurement configuration used
        created_at: When checkpoint was created
        reason: Reason for checkpoint (disconnect, user_cancel, etc.)
    """
    session_id: str = ""
    patch_queue: List[Tuple[int, int, int, str]] = field(default_factory=list)
    completed_results: List[MeasurementResult] = field(default_factory=list)
    current_patch_index: int = 0
    current_patch_rgb: Tuple[int, int, int] = (0, 0, 0)
    config: Optional[MeasurementConfig] = None
    created_at: datetime = field(default_factory=datetime.now)
    reason: str = "disconnect"


@dataclass
class MeasurementSession:
    """
    Active measurement session state.

    Attributes:
        session_id: Unique session identifier
        config: Measurement configuration
        patch_queue: Patches to measure [(r, g, b, name), ...]
        current_index: Current patch index
        results: Measurement results
        started_at: Session start time
        completed_at: Session completion time (if finished)
    """
    session_id: str = ""
    config: MeasurementConfig = field(default_factory=MeasurementConfig)
    patch_queue: List[Tuple[int, int, int, str]] = field(default_factory=list)
    current_index: int = 0
    results: List[MeasurementResult] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def total_patches(self) -> int:
        """Total number of patches in queue."""
        return len(self.patch_queue)

    @property
    def completed_patches(self) -> int:
        """Number of completed measurements."""
        return len(self.results)

    @property
    def remaining_patches(self) -> int:
        """Number of remaining patches."""
        return self.total_patches - self.current_index

    @property
    def progress_percent(self) -> float:
        """Progress as percentage."""
        if self.total_patches == 0:
            return 0.0
        return (self.current_index / self.total_patches) * 100

    @property
    def current_patch(self) -> Optional[Tuple[int, int, int, str]]:
        """Get current patch from queue."""
        if self.current_index < len(self.patch_queue):
            return self.patch_queue[self.current_index]
        return None


class MeasurementService:
    """
    Core service for orchestrating color measurements.

    This service coordinates:
    - Instrument connection and calibration
    - Patch display and settling
    - Measurement triggering and result collection
    - Dark sample multi-sampling
    - OLED black frame insertion
    - State machine integration
    - Checkpoint/resume capability

    Thread Safety:
        This service is NOT thread-safe. In Qt applications, ensure all
        interactions happen on the main thread.

    Example:
        >>> from src.instruments.base import FakeInstrument, FakePatchPresenter
        >>> instrument = FakeInstrument()
        >>> presenter = FakePatchPresenter()
        >>> service = MeasurementService(instrument, presenter)
        >>> patches = [(255, 0, 0, "Red"), (0, 255, 0, "Green")]
        >>> results = service.measure_patches(patches)
    """

    def __init__(
        self,
        instrument: InstrumentAdapter,
        presenter: PatchPresenter,
        config: Optional[MeasurementConfig] = None,
        state_machine: Optional[MeasurementStateMachine] = None
    ):
        """
        Initialize measurement service.

        Args:
            instrument: Instrument adapter for measurements
            presenter: Patch presenter for displaying colors
            config: Measurement configuration (defaults if None)
            state_machine: State machine for workflow tracking (creates if None)
        """
        self._instrument = instrument
        self._presenter = presenter
        # 取消标志：stop_session 置位，测量循环/等待环节周期性检查，
        # 避免 stop 与阻塞中的 sleep/测量竞态（停止后仍闪色块）
        self._stop_requested = threading.Event()
        self._config = config or MeasurementConfig()
        self._state_machine = state_machine or MeasurementStateMachine()

        # Session state
        self._session: Optional[MeasurementSession] = None
        self._checkpoint: Optional[CheckpointData] = None

        # Repeatability tracking
        self._repeatability_records: List[PatchRepeatabilityRecord] = []
        self._current_patch_measurements: List[SingleMeasurement] = []
        self._remeasure_attempts: Dict[int, int] = {}  # patch_index -> attempts count

        # Callbacks
        self._on_patch_displayed_callbacks: List[Callable[[int, Tuple[int, int, int], str], None]] = []
        self._on_measurement_received_callbacks: List[Callable[[MeasurementResult], None]] = []
        self._on_progress_callbacks: List[Callable[[int, int, float], None]] = []
        self._on_error_callbacks: List[Callable[[MeasurementServiceError], None]] = []
        self._on_state_change_callbacks: List[Callable[[MeasurementState, MeasurementState], None]] = []
        self._on_repeatability_warning_callbacks: List[Callable[[int, RepeatabilityResult], None]] = []
        self._on_remeasure_required_callbacks: List[Callable[[int, PatchRepeatabilityRecord], None]] = []
        self._on_confidence_warning_callbacks: List[Callable[[int, float, str], None]] = []
        self._on_outlier_rejected_callbacks: List[Callable[[int, int, List[RawReading]], None]] = []

        # Dark sample tracking
        self._dark_sample_measurements: List[MeasurementResult] = []
        self._dark_sample_retry_count: int = 0

        # OLED tracking
        self._last_patch_brightness: float = 0.0

        # Warm-up state tracking
        self._warmup_done: bool = False
        self._warmup_stable: bool = False
        self._warmup_readings: List[MeasurementResult] = []

        # Confidence tracking
        self._session_confidence_records: Dict[int, float] = {}  # patch_index -> confidence
        self._session_rejected_count: int = 0

        # Register state machine callback
        self._state_machine.on_state_change(self._handle_state_change)

    @property
    def state(self) -> MeasurementState:
        """Get current state machine state."""
        return self._state_machine.state

    @property
    def session(self) -> Optional[MeasurementSession]:
        """Get current session."""
        return self._session

    @property
    def instrument(self) -> InstrumentAdapter:
        """Get instrument adapter."""
        return self._instrument

    @property
    def presenter(self) -> PatchPresenter:
        """Get patch presenter."""
        return self._presenter

    @property
    def config(self) -> MeasurementConfig:
        """Get measurement configuration."""
        return self._config

    @property
    def checkpoint(self) -> Optional[CheckpointData]:
        """Get current checkpoint data."""
        return self._checkpoint

    @property
    def warmup_done(self) -> bool:
        """Check if instrument warm-up has been completed."""
        return self._warmup_done

    @property
    def warmup_stable(self) -> bool:
        """Check if instrument was stable after warm-up."""
        return self._warmup_stable

    @property
    def session_confidence(self) -> float:
        """Get average confidence for the current session."""
        if not self._session_confidence_records:
            return 0.0
        return sum(self._session_confidence_records.values()) / len(self._session_confidence_records)

    @property
    def session_rejected_count(self) -> int:
        """Get total rejected readings count for session."""
        return self._session_rejected_count

    def on_confidence_warning(
        self, callback: Callable[[int, float, str], None]
    ) -> None:
        """Register callback for low confidence warning events."""
        self._on_confidence_warning_callbacks.append(callback)

    def on_outlier_rejected(
        self, callback: Callable[[int, int, List[RawReading]], None]
    ) -> None:
        """Register callback for outlier rejection events."""
        self._on_outlier_rejected_callbacks.append(callback)

    def on_patch_displayed(
        self, callback: Callable[[int, Tuple[int, int, int], str], None]
    ) -> None:
        """Register callback for patch display events."""
        self._on_patch_displayed_callbacks.append(callback)

    def on_measurement_received(
        self, callback: Callable[[MeasurementResult], None]
    ) -> None:
        """Register callback for measurement result events."""
        self._on_measurement_received_callbacks.append(callback)

    def on_progress(
        self, callback: Callable[[int, int, float], None]
    ) -> None:
        """Register callback for progress updates."""
        self._on_progress_callbacks.append(callback)

    def on_error(
        self, callback: Callable[[MeasurementServiceError], None]
    ) -> None:
        """Register callback for error events."""
        self._on_error_callbacks.append(callback)

    def on_state_change(
        self, callback: Callable[[MeasurementState, MeasurementState], None]
    ) -> None:
        """Register callback for state changes."""
        self._on_state_change_callbacks.append(callback)

    def on_repeatability_warning(
        self, callback: Callable[[int, RepeatabilityResult], None]
    ) -> None:
        """Register callback for repeatability warning events."""
        self._on_repeatability_warning_callbacks.append(callback)

    def on_remeasure_required(
        self, callback: Callable[[int, PatchRepeatabilityRecord], None]
    ) -> None:
        """Register callback for remeasurement required events."""
        self._on_remeasure_required_callbacks.append(callback)

    def _handle_state_change(
        self, old_state: MeasurementState, new_state: MeasurementState, event: Event
    ) -> None:
        """Handle state machine state change."""
        logger.info(f"MeasurementService state change: {old_state.value} -> {new_state.value}")

        # Notify callbacks
        for callback in self._on_state_change_callbacks:
            try:
                callback(old_state, new_state)
            except Exception as e:
                logger.error(f"State change callback error: {e}")

    def _notify_patch_displayed(
        self, index: int, rgb: Tuple[int, int, int], name: str
    ) -> None:
        """Notify callbacks of patch display."""
        for callback in self._on_patch_displayed_callbacks:
            try:
                callback(index, rgb, name)
            except Exception as e:
                logger.error(f"Patch display callback error: {e}")

    def _notify_measurement_received(self, result: MeasurementResult) -> None:
        """Notify callbacks of measurement result."""
        for callback in self._on_measurement_received_callbacks:
            try:
                callback(result)
            except Exception as e:
                logger.error(f"Measurement received callback error: {e}")

    def _notify_progress(self) -> None:
        """Notify callbacks of progress update."""
        if self._session:
            for callback in self._on_progress_callbacks:
                try:
                    callback(
                        self._session.current_index,
                        self._session.total_patches,
                        self._session.progress_percent
                    )
                except Exception as e:
                    logger.error(f"Progress callback error: {e}")

    def _notify_error(self, error: MeasurementServiceError) -> None:
        """Notify callbacks of error."""
        for callback in self._on_error_callbacks:
            try:
                callback(error)
            except Exception as e:
                logger.error(f"Error callback error: {e}")

    def _notify_repeatability_warning(
        self, patch_index: int, result: RepeatabilityResult
    ) -> None:
        """Notify callbacks of repeatability warning."""
        for callback in self._on_repeatability_warning_callbacks:
            try:
                callback(patch_index, result)
            except Exception as e:
                logger.error(f"Repeatability warning callback error: {e}")

    def _notify_remeasure_required(
        self, patch_index: int, record: PatchRepeatabilityRecord
    ) -> None:
        """Notify callbacks of remeasurement requirement."""
        for callback in self._on_remeasure_required_callbacks:
            try:
                callback(patch_index, record)
            except Exception as e:
                logger.error(f"Remeasure required callback error: {e}")

    def start_session(
        self,
        patches: List[Tuple[int, int, int, str]],
        session_id: Optional[str] = None,
        config: Optional[MeasurementConfig] = None
    ) -> bool:
        """
        Start a new measurement session.

        Args:
            patches: List of patches to measure [(r, g, b, name), ...]
            session_id: Optional session identifier
            config: Optional configuration override

        Returns:
            True if session started successfully

        Raises:
            MeasurementServiceError: If session cannot be started
        """
        if self._state_machine.is_active():
            raise MeasurementServiceError(
                "Session already active",
                error_code="SESSION_ACTIVE",
                state=self.state,
                recoverable=False
            )

        # Use provided config or default
        effective_config = config or self._config

        # Generate session ID if not provided
        if not session_id:
            session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Reset cancel flag for the new session
        self._stop_requested.clear()

        # Create session
        self._session = MeasurementSession(
            session_id=session_id,
            config=effective_config,
            patch_queue=patches.copy(),
            started_at=datetime.now()
        )

        # Initialize repeatability tracking
        self._repeatability_records.clear()
        self._current_patch_measurements.clear()
        self._remeasure_attempts.clear()

        # Start state machine
        try:
            start_session(self._state_machine, effective_config.measure_mode)
        except Exception as e:
            raise MeasurementServiceError(
                f"Failed to start session: {e}",
                error_code="START_FAILED",
                recoverable=False
            )

        # Run precheck
        precheck_result = self._run_precheck()
        if not precheck_result:
            return False

        # Connect instrument
        connect_result = self._connect_instrument()
        if not connect_result:
            return False

        return True

    def _run_precheck(self) -> bool:
        """Run pre-flight checks."""
        checks_passed = []
        checks_failed = []

        # Check instrument availability
        try:
            status = self._instrument.status()
            if status.state != InstrumentState.ERROR:
                checks_passed.append("instrument_available")
            else:
                checks_failed.append("instrument_error")
        except Exception as e:
            checks_failed.append("instrument_check_failed")

        # Check presenter availability
        try:
            display_id = self._presenter.target_display_id()
            checks_passed.append("display_available")
        except Exception as e:
            checks_failed.append("display_check_failed")

        if checks_failed:
            fail_precheck(self._state_machine, tuple(checks_failed), "Precheck failed")
            self._notify_error(MeasurementServiceError(
                f"Precheck failed: {checks_failed}",
                error_code="PRECHECK_FAILED",
                state=self.state,
                recoverable=False
            ))
            return False

        complete_precheck(self._state_machine, tuple(checks_passed))
        return True

    def _connect_instrument(self) -> bool:
        """Connect to measurement instrument."""
        try:
            connected = self._instrument.connect()
            if not connected:
                raise InstrumentError("Connect returned false")

            # Update state machine
            connect_instrument(
                self._state_machine,
                self._instrument.instrument_type,
                self._instrument.instrument_id
            )

            # Check if calibration needed
            if self._config.auto_calibrate:
                status = self._instrument.status()
                if status.needs_calibration():
                    self._calibrate_instrument()

            return True

        except InstrumentError as e:
            fail_workflow(
                self._state_machine,
                e.error_code,
                str(e),
                e.recoverable
            )
            self._notify_error(MeasurementServiceError(
                f"Instrument connection failed: {e}",
                error_code=e.error_code,
                state=self.state,
                recoverable=e.recoverable
            ))
            return False

    def _calibrate_instrument(self) -> bool:
        """Calibrate the measurement instrument."""
        try:
            calibrated = self._instrument.calibrate()
            if not calibrated:
                raise InstrumentError("Calibration returned false")

            # Update state machine
            self._state_machine.handle_event(CalibrationCompleted(
                calibration_type="standard"
            ))

            return True

        except InstrumentError as e:
            fail_workflow(
                self._state_machine,
                e.error_code,
                f"Calibration failed: {e}",
                e.recoverable
            )
            return False

    def measure_next_patch(self) -> Optional[MeasurementResult]:
        """
        Measure the next patch in the queue.

        Returns:
            MeasurementResult if successful, None if queue empty or error

        Raises:
            MeasurementServiceError: If measurement cannot proceed
        """
        if not self._session:
            raise MeasurementServiceError(
                "No active session",
                error_code="NO_SESSION",
                state=self.state,
                recoverable=True
            )

        if self.state != MeasurementState.MEASURING:
            raise MeasurementServiceError(
                f"Not in measuring state: {self.state}",
                error_code="WRONG_STATE",
                state=self.state,
                recoverable=True
            )

        patch = self._session.current_patch
        if not patch:
            # All patches completed
            self._complete_session()
            return None

        r, g, b, name = patch

        try:
            result = self._measure_patch(r, g, b, name, self._session.current_index)
            self._session.results.append(result)
            self._session.current_index += 1
            self._notify_progress()
            return result

        except (InstrumentError, PatchDisplayError) as e:
            error = MeasurementServiceError(
                f"Measurement failed: {e}",
                error_code="MEASUREMENT_FAILED",
                state=self.state,
                recoverable=True
            )
            self._notify_error(error)
            # Save checkpoint for recovery
            self._save_checkpoint("measurement_error")
            # 状态机转入 FAILED：让调用方能区分"中途失败"与"全部完成"
            try:
                self._state_machine.handle_event(WorkflowFailed(
                    error_code="MEASUREMENT_FAILED",
                    error_message=str(e),
                    recoverable=True,
                ))
            except Exception as state_err:
                logger.warning(f"Failed to transition state after error: {state_err}")
            return None

    def _measure_patch(
        self,
        r: int, g: int, b: int,
        name: str,
        index: int
    ) -> MeasurementResult:
        """
        Measure a single patch.

        This handles:
        - OLED black frame insertion
        - Patch display and settling
        - Dark sample multi-sampling
        - Result collection

        Args:
            r, g, b: RGB values
            name: Patch name
            index: Patch index in queue

        Returns:
            MeasurementResult
        """
        # Check if OLED black frame needed
        if self._config.oled.enabled:
            self._handle_oled_black_frame(r, g, b)

        # Display patch
        self._presenter.show_rgb(r, g, b)
        self._notify_patch_displayed(index, (r, g, b), name)

        # Update state machine
        self._state_machine.handle_event(PatchDisplayed(
            patch_index=index,
            patch_name=name,
            rgb=(r, g, b),
            patch_id=f"{self._session.session_id}_{index}"
        ))

        # Wait for settling
        self._wait_for_settling(r, g, b)

        # Take measurement
        if self._is_dark_sample(r, g, b):
            result = self._measure_dark_sample(r, g, b, name, index)
        else:
            result = self._instrument.measure()
            result.patch_index = index
            result.patch_name = name
            result.rgb_requested = (r, g, b)

        # Update state machine
        self._state_machine.handle_event(MeasurementReceived(
            patch_index=index,
            xyz=result.xyz,
            xyY=result.xyY,
            patch_id=result.patch_id
        ))

        self._notify_measurement_received(result)

        return result

    def _handle_oled_black_frame(self, r: int, g: int, b: int) -> None:
        """Handle OLED black frame insertion if needed."""
        current_brightness = (r + g + b) / 3.0 / 255.0

        # Check if brightness delta exceeds threshold
        brightness_delta = abs(current_brightness - self._last_patch_brightness)

        if brightness_delta > self._config.oled.black_frame_threshold:
            # Insert black frame
            self._presenter.show_black_frame(self._config.oled.black_frame_duration_ms)
            logger.debug(f"OLED black frame inserted (delta={brightness_delta:.2f})")

        self._last_patch_brightness = current_brightness

    def _sleep_interruptible(self, seconds: float) -> None:
        """可中断的 sleep：stop_session 请求取消时立即返回。"""
        deadline = time.monotonic() + seconds
        while not self._stop_requested.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.05, remaining))

    def _wait_for_settling(self, r: int, g: int, b: int) -> None:
        """Wait for patch settling time."""
        settling_ms = self._config.settling_time_ms

        # Add OLED extended settling if enabled and dark
        if self._config.oled.enabled:
            brightness = (r + g + b) / 3.0
            if brightness < 50:  # Dark patch
                settling_ms += self._config.oled.extended_settling_ms

        self._sleep_interruptible(settling_ms / 1000.0)

    def _is_dark_sample(self, r: int, g: int, b: int) -> bool:
        """Check if patch is likely a dark sample based on RGB."""
        # Rough estimate: RGB < 50 is likely dark
        avg = (r + g + b) / 3.0
        return avg < 50

    def _measure_dark_sample(
        self,
        r: int, g: int, b: int,
        name: str,
        index: int
    ) -> MeasurementResult:
        """
        Perform multi-sampling for dark patch.

        Dark samples need multiple measurements for accurate averaging.
        Uses XYZ linear averaging for best results.

        Args:
            r, g, b: RGB values
            name: Patch name
            index: Patch index

        Returns:
            Averaged MeasurementResult
        """
        measurements: List[MeasurementResult] = []
        self._dark_sample_measurements.clear()
        self._dark_sample_retry_count = 0

        for sample_num in range(self._config.dark_sample.sample_count):
            for retry in range(self._config.dark_sample.max_retries + 1):
                try:
                    result = self._instrument.measure()
                    result.patch_index = index
                    result.patch_name = name
                    result.rgb_requested = (r, g, b)
                    result.is_retry = retry > 0
                    measurements.append(result)
                    self._dark_sample_measurements.append(result)
                    break

                except InstrumentError as e:
                    self._dark_sample_retry_count += 1
                    logger.warning(f"Dark sample retry {retry}: {e}")
                    if retry == self._config.dark_sample.max_retries:
                        # Max retries reached, use partial data
                        if measurements:
                            break
                        raise

        if not measurements:
            raise InstrumentError("No dark sample measurements collected")

        # Average results
        if self._config.dark_sample.use_xyz_average:
            return self._average_xyz_measurements(measurements, r, g, b, name, index)
        else:
            # Use first measurement
            return measurements[0]

    def _average_xyz_measurements(
        self,
        measurements: List[MeasurementResult],
        r: int, g: int, b: int,
        name: str,
        index: int
    ) -> MeasurementResult:
        """
        Average multiple XYZ measurements.

        XYZ linear averaging is recommended for dark samples.

        Args:
            measurements: List of measurements to average
            r, g, b: Requested RGB
            name: Patch name
            index: Patch index

        Returns:
            Averaged MeasurementResult
        """
        X_total = sum(m.xyz[0] for m in measurements)
        Y_total = sum(m.xyz[1] for m in measurements)
        Z_total = sum(m.xyz[2] for m in measurements)

        count = len(measurements)
        X_avg = X_total / count
        Y_avg = Y_total / count
        Z_avg = Z_total / count

        # Calculate xyY from averaged XYZ
        total = X_avg + Y_avg + Z_avg
        if total > 0:
            x = X_avg / total
            y = Y_avg / total
        else:
            x = 0.0
            y = 0.0

        return MeasurementResult(
            xyz=(X_avg, Y_avg, Z_avg),
            xyY=(x, y, Y_avg),
            rgb_requested=(r, g, b),
            timestamp=datetime.now(),
            patch_index=index,
            patch_name=name,
            patch_id=f"{self._session.session_id}_{index}",
            is_retry=False,
            confidence=1.0 / self._dark_sample_retry_count if self._dark_sample_retry_count > 0 else 1.0,
            metadata={
                "sample_count": count,
                "retry_count": self._dark_sample_retry_count,
                "averaged": True
            }
        )

    def _perform_instrument_warmup(self) -> bool:
        """
        Perform instrument warm-up procedure.

        Many colorimeters and spectrophotometers need warm-up
        for stable readings. This method:
        - Takes warm-up readings on white patch
        - Checks stability via Y variation
        - Marks warm-up complete when stable

        Returns:
            bool: True if warm-up successful and instrument stable
        """
        if not self._config.warmup.enabled:
            self._warmup_done = True
            self._warmup_stable = True
            return True

        if self._warmup_done:
            # Already done
            return self._warmup_stable

        logger.info(f"Starting instrument warm-up ({self._config.warmup.warmup_time_ms}ms)")

        # Display white patch for warm-up
        self._presenter.show_rgb(255, 255, 255)
        time.sleep(self._config.settling_time_ms / 1000.0)

        self._warmup_readings.clear()
        prev_Y: Optional[float] = None

        for i in range(self._config.warmup.warmup_readings):
            result = self._instrument.measure()
            self._warmup_readings.append(result)

            current_Y = result.xyz[1]

            # Check stability
            if prev_Y is not None:
                Y_change = abs(current_Y - prev_Y)
                if Y_change < self._config.warmup.stability_threshold:
                    logger.info(f"Warm-up stable after {i+1} readings (Y change: {Y_change:.4f})")
                    self._warmup_stable = True
                    break

            prev_Y = current_Y

            # Wait interval between readings
            if i < self._config.warmup.warmup_readings - 1:
                self._sleep_interruptible(self._config.warmup.warmup_interval_ms / 1000.0)
            if self._stop_requested.is_set():
                return False

        self._warmup_done = True

        if not self._warmup_stable:
            logger.warning("Instrument not stable after warm-up readings")

        return self._warmup_stable

    def _get_patch_policy(self, index: int, Y_estimate: float = 100.0) -> PatchMeasurementPolicy:
        """
        Get measurement policy for a specific patch.

        Combines:
        - Base configuration policy
        - Luminance-adaptive policy
        - Per-patch custom overrides

        Args:
            index: Patch index
            Y_estimate: Estimated luminance (for adaptive policy)

        Returns:
            PatchMeasurementPolicy: Policy to use for this patch
        """
        # Start with base policy
        base_policy = PatchMeasurementPolicy(
            repeat_count=self._config.repeat_measure.repeat_count,
            outlier_rejection_method=self._config.repeat_measure.outlier_method,
            outlier_threshold=3.0,
            confidence_threshold=self._config.confidence_threshold,
            settling_time_ms=self._config.settling_time_ms,
            integration_time_factor=self._config.dark_sample.integration_time_factor,
            min_accepted_readings=self._config.reliability.min_accepted_readings,
        )

        # Apply luminance-adaptive policy
        if self._config.reliability.adaptive_policy:
            base_policy = get_luminance_policy(Y_estimate, base_policy)

        # Apply per-patch custom override
        if self._config.reliability.patch_policies and index in self._config.reliability.patch_policies:
            custom = self._config.reliability.patch_policies[index]
            # Merge custom policy
            base_policy = PatchMeasurementPolicy(
                repeat_count=custom.repeat_count,
                outlier_rejection_method=custom.outlier_rejection_method,
                outlier_threshold=custom.outlier_threshold,
                confidence_threshold=custom.confidence_threshold,
                settling_time_ms=custom.settling_time_ms or base_policy.settling_time_ms,
                integration_time_factor=custom.integration_time_factor,
                min_accepted_readings=custom.min_accepted_readings,
                force_dark_handling=custom.force_dark_handling,
            )

        return base_policy

    def _measure_with_reliability(
        self,
        r: int, g: int, b: int,
        name: str,
        index: int,
        policy: Optional[PatchMeasurementPolicy] = None
    ) -> MeasurementResult:
        """
        Measure a patch with full reliability features.

        Includes:
        - Multiple readings based on policy
        - Outlier rejection
        - Confidence calculation
        - Raw readings tracking

        Args:
            r, g, b: RGB values
            name: Patch name
            index: Patch index
            policy: Measurement policy (computed if None)

        Returns:
            MeasurementResult with full reliability metadata
        """
        # Get policy if not provided
        effective_policy = policy or self._get_patch_policy(index)

        # Take multiple readings
        raw_readings: List[RawReading] = []
        single_measurements: List[SingleMeasurement] = []

        for reading_idx in range(effective_policy.repeat_count):
            result = self._instrument.measure()

            # Create raw reading record
            raw_reading = RawReading(
                xyz=result.xyz,
                xyY=result.xyY,
                timestamp=datetime.now(),
                reading_index=reading_idx,
                integration_time_ms=result.metadata.get("integration_time_ms"),
                temperature=result.metadata.get("temperature"),
                metadata={"original_result": result}
            )
            raw_readings.append(raw_reading)

            # Create single measurement for statistics
            single = create_single_measurement(
                xyz=result.xyz,
                xyY=result.xyY,
                metadata={"reading_index": reading_idx}
            )
            single_measurements.append(single)

        # Perform outlier rejection if enabled
        outlier_result: Optional[OutlierDetectionResult] = None
        if effective_policy.outlier_rejection_method != OutlierRejectionMethod.NONE:
            outlier_result = detect_outliers(
                single_measurements,
                method=effective_policy.outlier_rejection_method,
                threshold=effective_policy.outlier_threshold,
                use_component="Y"
            )

            # Check rejection ratio
            if outlier_result.has_outliers:
                rejection_ratio = outlier_result.rejection_ratio
                if rejection_ratio > self._config.reliability.reject_high_outlier_ratio:
                    # Too many outliers - might be measurement issue
                    logger.warning(
                        f"High outlier ratio {rejection_ratio:.2%} for patch {index} ({name})"
                    )

                # Track rejected readings
                self._session_rejected_count += len(outlier_result.rejected_measurements)

                # Notify callback
                rejected_raw = [
                    RawReading(
                        xyz=m.xyz,
                        xyY=m.xyY,
                        timestamp=m.timestamp,
                        reading_index=i,
                    )
                    for i, m in enumerate(single_measurements)
                    if m in outlier_result.rejected_measurements
                ]
                for callback in self._on_outlier_rejected_callbacks:
                    try:
                        callback(index, len(rejected_raw), rejected_raw)
                    except Exception as e:
                        logger.error(f"Outlier rejected callback error: {e}")

        # Use accepted measurements for statistics
        accepted_measurements = (
            outlier_result.accepted_measurements if outlier_result
            else single_measurements
        )

        # Check minimum accepted readings
        if len(accepted_measurements) < effective_policy.min_accepted_readings:
            logger.warning(
                f"Insufficient accepted readings ({len(accepted_measurements)} < "
                f"{effective_policy.min_accepted_readings}) for patch {index}"
            )
            # Could trigger remeasurement here

        # Calculate statistics on accepted readings
        stats = calculate_measurement_statistics(accepted_measurements)

        # Calculate confidence score
        confidence = calculate_confidence_score(stats, outlier_result)

        # Determine luminance level and quality status
        luminance_level_enum = get_luminance_level_enum(stats.mean_Y)
        quality_status = get_measurement_quality_status(
            confidence,
            self._config.repeat_measure.threshold,
            luminance_level_enum
        )

        # Store confidence record
        self._session_confidence_records[index] = confidence

        # Check confidence threshold
        if confidence < effective_policy.confidence_threshold:
            logger.warning(
                f"Low confidence {confidence:.2f} for patch {index} "
                f"(threshold: {effective_policy.confidence_threshold:.2f})"
            )
            # Notify confidence warning callback
            for callback in self._on_confidence_warning_callbacks:
                try:
                    callback(index, confidence, quality_status.value)
                except Exception as e:
                    logger.error(f"Confidence warning callback error: {e}")

        # Create rejected readings list
        rejected_raw_readings: List[RawReading] = []
        if outlier_result and outlier_result.has_outliers:
            rejected_raw_readings = [
                RawReading(
                    xyz=m.xyz,
                    xyY=m.xyY,
                    timestamp=m.timestamp,
                    reading_index=i,
                    metadata={"outlier": True}
                )
                for i, m in enumerate(single_measurements)
                if m in outlier_result.rejected_measurements
            ]

        # Create final result with full metadata
        final_result = MeasurementResult(
            xyz=stats.mean_xyz,
            xyY=stats.mean_xyY,
            rgb_requested=(r, g, b),
            timestamp=datetime.now(),
            patch_index=index,
            patch_name=name,
            patch_id=f"{self._session.session_id}_{index}",
            is_retry=False,
            confidence=confidence,
            raw_readings=raw_readings,
            repeat_count=effective_policy.repeat_count,
            standard_deviation=stats.std_xyz,
            rejected_readings=rejected_raw_readings,
            outlier_rejection_method=effective_policy.outlier_rejection_method.value,
            luminance_level=luminance_level_enum.value,
            measurement_status=quality_status.value,
            metadata={
                "accepted_count": len(accepted_measurements),
                "rejected_count": len(rejected_raw_readings),
                "relative_std_Y_percent": stats.relative_std_Y,
                "settling_time_ms": effective_policy.settling_time_ms,
                "policy_applied": True,
            }
        )

        return final_result

    def measure_all_patches(self) -> List[MeasurementResult]:
        """
        Measure all patches in the queue.

        Returns:
            List of all measurement results

        Raises:
            MeasurementServiceError: If session fails
        """
        if not self._session:
            raise MeasurementServiceError(
                "No active session",
                error_code="NO_SESSION",
                state=self.state,
                recoverable=True
            )

        results: List[MeasurementResult] = []

        while self.state == MeasurementState.MEASURING:
            if self._stop_requested.is_set():
                logger.info("Measurement loop cancelled by stop request")
                break
            result = self.measure_next_patch()
            if result:
                results.append(result)
            else:
                break

        return results

    def measure_patches(
        self,
        patches: List[Tuple[int, int, int, str]]
    ) -> List[MeasurementResult]:
        """
        Convenience method: start session and measure all patches.

        Args:
            patches: List of patches to measure [(r, g, b, name), ...]

        Returns:
            List of measurement results

        Raises:
            MeasurementServiceError: If measurement fails
        """
        self.start_session(patches)
        return self.measure_all_patches()

    def stop_session(self, save_checkpoint: bool = False) -> CheckpointData:
        """
        Stop the current session.

        Args:
            save_checkpoint: Whether to save checkpoint for resume

        Returns:
            CheckpointData if saved, empty checkpoint otherwise

        Raises:
            MeasurementServiceError: If not in active session
        """
        if not self._session:
            raise MeasurementServiceError(
                "No active session to stop",
                error_code="NO_SESSION",
                state=self.state,
                recoverable=False
            )

        # 先置取消标志，测量循环/settling 等待会尽快退出
        self._stop_requested.set()

        checkpoint = CheckpointData()
        if save_checkpoint:
            checkpoint = self._save_checkpoint("user_cancel")

        # Update state machine
        stop_session(self._state_machine, save_checkpoint, "user_cancel")

        # Hide patch display
        self._presenter.hide()

        # Disconnect instrument
        try:
            self._instrument.disconnect()
        except Exception as e:
            logger.warning(f"Disconnect error during stop: {e}")

        self._session.completed_at = datetime.now()

        return checkpoint

    def _complete_session(self) -> None:
        """Complete the measurement session."""
        if not self._session:
            return

        # Update state machine - measurement phase complete
        self._state_machine.handle_event(AllPatchesCompleted(
            total_patches=self._session.total_patches,
            successful_patches=self._session.completed_patches,
            failed_patches=0
        ))

        # For pure measurement sessions (no profile generation),
        # immediately complete the workflow
        # Note: If profile generation is needed, a separate service
        # (e.g., ICCWorkflowService) would handle GENERATING_PROFILE state
        if self.state == MeasurementState.GENERATING_PROFILE:
            self._state_machine.handle_event(ProfileGenerated(
                profile_type="measurement_only",
                profile_path="",
                profile_size=0
            ))

        # Hide patch display
        self._presenter.hide()

        # Update session timing
        self._session.completed_at = datetime.now()

        logger.info(
            f"Session completed: {self._session.completed_patches} patches "
            f"in {self._session.total_patches} total"
        )

    def _save_checkpoint(self, reason: str) -> CheckpointData:
        """Save checkpoint data for resume capability."""
        if not self._session:
            return CheckpointData()

        self._checkpoint = CheckpointData(
            session_id=self._session.session_id,
            patch_queue=self._session.patch_queue.copy(),
            completed_results=self._session.results.copy(),
            current_patch_index=self._session.current_index,
            current_patch_rgb=self._session.current_patch[0:3] if self._session.current_patch else (0, 0, 0),
            config=self._config,
            created_at=datetime.now(),
            reason=reason
        )

        logger.info(f"Checkpoint saved: {self._checkpoint.current_patch_index} completed")

        return self._checkpoint

    def resume_from_checkpoint(
        self,
        checkpoint: Optional[CheckpointData] = None
    ) -> bool:
        """
        Resume measurement session from checkpoint.

        Args:
            checkpoint: Checkpoint to resume (uses saved checkpoint if None)

        Returns:
            True if resume successful

        Raises:
            MeasurementServiceError: If resume fails
        """
        effective_checkpoint = checkpoint or self._checkpoint
        if not effective_checkpoint:
            raise MeasurementServiceError(
                "No checkpoint available",
                error_code="NO_CHECKPOINT",
                state=self.state,
                recoverable=False
            )

        if self.state != MeasurementState.SUSPENDED:
            raise MeasurementServiceError(
                f"Cannot resume from state: {self.state}",
                error_code="WRONG_STATE",
                state=self.state,
                recoverable=True
            )

        # Update state machine
        resume_session(self._state_machine, effective_checkpoint.session_id)

        # Create resumed session
        remaining_patches = effective_checkpoint.patch_queue[
            effective_checkpoint.current_patch_index:
        ]

        self._session = MeasurementSession(
            session_id=effective_checkpoint.session_id,
            config=effective_checkpoint.config or self._config,
            patch_queue=remaining_patches,
            current_index=0,  # Index within remaining patches
            results=effective_checkpoint.completed_results.copy(),
            started_at=effective_checkpoint.created_at
        )

        # Connect instrument
        connect_result = self._connect_instrument()
        if not connect_result:
            return False

        logger.info(
            f"Session resumed: {effective_checkpoint.completed_results} "
            f"completed, {len(remaining_patches)} remaining"
        )

        return True

    def handle_instrument_disconnect(self) -> None:
        """
        Handle unexpected instrument disconnection.

        This method should be called when instrument disconnects
        unexpectedly during measurement.
        """
        if self.state == MeasurementState.MEASURING:
            # Save checkpoint
            self._save_checkpoint("disconnect")

            # Update state machine
            disconnect_instrument(
                self._state_machine,
                was_measuring=True,
                checkpoint_data={
                    "session_id": self._checkpoint.session_id if self._checkpoint else "",
                    "patch_index": self._checkpoint.current_patch_index if self._checkpoint else 0
                }
            )

            # Hide patch display
            self._presenter.hide()

            logger.warning("Instrument disconnected during measurement")

    def set_oled_config(self, config: OLEDConfig) -> None:
        """Update OLED configuration."""
        self._config.oled = config

        # Apply OLED window size to presenter
        if config.enabled:
            self._presenter.set_oled_window_size(config.window_size_percent)

    def set_dark_sample_config(self, config: DarkSampleConfig) -> None:
        """Update dark sample configuration."""
        self._config.dark_sample = config

    def reset(self) -> None:
        """Reset service to clean state."""
        self._state_machine.reset()
        self._session = None
        self._checkpoint = None
        self._dark_sample_measurements.clear()
        self._dark_sample_retry_count = 0
        self._last_patch_brightness = 0.0
        self._repeatability_records.clear()
        self._current_patch_measurements.clear()
        self._remeasure_attempts.clear()

        try:
            self._presenter.hide()
        except Exception:
            pass

        try:
            self._instrument.disconnect()
        except Exception:
            pass

    # ========== Repeatability Analysis Methods ==========

    def set_repeat_measure_config(self, config: RepeatMeasureConfig) -> None:
        """Update repeat measurement configuration."""
        self._config.repeat_measure = config

    @property
    def repeatability_records(self) -> List[PatchRepeatabilityRecord]:
        """Get all repeatability records for current session."""
        return self._repeatability_records.copy()

    def is_patch_requiring_repeat_measure(self, patch_index: int) -> bool:
        """
        Check if a patch requires repeat measurement based on config.

        Args:
            patch_index: Index of the patch in the queue

        Returns:
            bool: True if repeat measurement is required
        """
        if not self._config.repeat_measure.enabled:
            return False

        if self._config.repeat_measure.apply_to_all:
            return True

        if self._config.repeat_measure.key_patches_only:
            return patch_index in self._config.repeat_measure.key_patch_indices

        return False

    def measure_patch_with_repeatability(
        self,
        r: int, g: int, b: int,
        name: str,
        index: int,
        repeat_count: Optional[int] = None
    ) -> Tuple[MeasurementResult, PatchRepeatabilityRecord]:
        """
        Measure a patch with repeatability analysis.

        Takes multiple measurements and calculates statistics.

        Args:
            r, g, b: RGB values
            name: Patch name
            index: Patch index in queue
            repeat_count: Override repeat count (uses config if None)

        Returns:
            Tuple[MeasurementResult, PatchRepeatabilityRecord]: (average result, repeatability record)
        """
        effective_repeat_count = repeat_count or self._config.repeat_measure.repeat_count
        measurements: List[SingleMeasurement] = []

        # Display patch
        self._presenter.show_rgb(r, g, b)
        self._notify_patch_displayed(index, (r, g, b), name)

        # Wait for settling
        self._wait_for_settling(r, g, b)

        # Take multiple measurements
        for i in range(effective_repeat_count):
            result = self._instrument.measure()

            # Create single measurement record
            single = create_single_measurement(
                xyz=result.xyz,
                xyY=result.xyY,
                instrument_status={
                    "model": self._instrument.instrument_type,
                    "id": self._instrument.instrument_id,
                },
                metadata={
                    "measurement_index": i,
                    "rgb_requested": (r, g, b),
                }
            )
            measurements.append(single)

        # Calculate statistics
        luminance_level = get_luminance_level(measurements[0].Y)
        stats = calculate_measurement_statistics(
            measurements, AveragingMethod.XYZ_LINEAR
        )

        # Evaluate repeatability
        threshold = self._config.repeat_measure.threshold
        repeatability_result = evaluate_repeatability(stats, threshold, luminance_level)

        # Create repeatability record
        record = PatchRepeatabilityRecord(
            patch_index=index,
            patch_name=name,
            rgb=(r, g, b),
            measurements=measurements,
            statistics=stats,
            result=repeatability_result,
            was_remeasured=False,
            remeasure_count=0,
        )

        # Create averaged MeasurementResult
        avg_result = MeasurementResult(
            xyz=stats.mean_xyz,
            xyY=stats.mean_xyY,
            rgb_requested=(r, g, b),
            timestamp=datetime.now(),
            patch_index=index,
            patch_name=name,
            patch_id=f"{self._session.session_id}_{index}",
            is_retry=False,
            confidence=stats.confidence,
            metadata={
                "repeat_count": effective_repeat_count,
                "averaged": True,
                "repeatability_status": repeatability_result.status.value,
                "std_xyz": list(stats.std_xyz),
                "relative_std_Y_percent": stats.relative_std_Y,
            }
        )

        # Store record
        self._repeatability_records.append(record)

        # Notify if threshold exceeded
        if repeatability_result.status == RepeatabilityStatus.FAIL:
            logger.warning(f"Patch {index} ({name}) repeatability failed: {repeatability_result.violations}")
            self._notify_remeasure_required(index, record)
        elif repeatability_result.status == RepeatabilityStatus.WARN:
            logger.info(f"Patch {index} ({name}) repeatability warning: {repeatability_result.warnings}")
            self._notify_repeatability_warning(index, repeatability_result)

        # Hide patch
        self._presenter.hide()

        return (avg_result, record)

    def remeasure_patch(
        self,
        patch_index: int,
        additional_count: Optional[int] = None
    ) -> Tuple[MeasurementResult, PatchRepeatabilityRecord]:
        """
        Remeasure a specific patch (after threshold failure).

        Args:
            patch_index: Index of the patch to remeasure
            additional_count: Number of additional measurements (default from config)

        Returns:
            Tuple[MeasurementResult, PatchRepeatabilityRecord]: (new average result, updated record)

        Raises:
            MeasurementServiceError: If no session active or patch not found
        """
        if not self._session:
            raise MeasurementServiceError(
                "No active session",
                error_code="NO_SESSION",
                state=self.state,
                recoverable=True
            )

        # Find the existing record
        existing_record = None
        for record in self._repeatability_records:
            if record.patch_index == patch_index:
                existing_record = record
                break

        if not existing_record:
            raise MeasurementServiceError(
                f"No repeatability record found for patch {patch_index}",
                error_code="NO_RECORD",
                state=self.state,
                recoverable=True
            )

        # Check remeasure attempts
        attempts = self._remeasure_attempts.get(patch_index, 0)
        max_attempts = self._config.repeat_measure.max_remeasure_attempts
        if attempts >= max_attempts:
            logger.warning(f"Max remeasure attempts ({max_attempts}) reached for patch {patch_index}")

        # Get patch info
        r, g, b = existing_record.rgb
        name = existing_record.patch_name

        # Determine additional measurement count
        count = additional_count or self._config.repeat_measure.repeat_count

        # Display patch
        self._presenter.show_rgb(r, g, b)
        self._wait_for_settling(r, g, b)

        # Take additional measurements
        new_measurements: List[SingleMeasurement] = existing_record.measurements.copy()
        for i in range(count):
            result = self._instrument.measure()
            single = create_single_measurement(
                xyz=result.xyz,
                xyY=result.xyY,
                instrument_status={
                    "model": self._instrument.instrument_type,
                    "id": self._instrument.instrument_id,
                },
                metadata={
                    "measurement_index": len(new_measurements) + i,
                    "remeasure": True,
                    "rgb_requested": (r, g, b),
                }
            )
            new_measurements.append(single)

        # Recalculate statistics
        luminance_level = get_luminance_level(new_measurements[0].Y)
        stats = calculate_measurement_statistics(
            new_measurements, AveragingMethod.XYZ_LINEAR
        )

        # Evaluate repeatability
        threshold = self._config.repeat_measure.threshold
        repeatability_result = evaluate_repeatability(stats, threshold, luminance_level)

        # Update record
        updated_record = PatchRepeatabilityRecord(
            patch_index=patch_index,
            patch_name=name,
            rgb=(r, g, b),
            measurements=new_measurements,
            statistics=stats,
            result=repeatability_result,
            was_remeasured=True,
            remeasure_count=attempts + 1,
        )

        # Replace existing record
        for i, record in enumerate(self._repeatability_records):
            if record.patch_index == patch_index:
                self._repeatability_records[i] = updated_record
                break

        # Update attempt count
        self._remeasure_attempts[patch_index] = attempts + 1

        # Create new averaged result
        avg_result = MeasurementResult(
            xyz=stats.mean_xyz,
            xyY=stats.mean_xyY,
            rgb_requested=(r, g, b),
            timestamp=datetime.now(),
            patch_index=patch_index,
            patch_name=name,
            patch_id=f"{self._session.session_id}_{patch_index}",
            is_retry=True,
            confidence=stats.confidence,
            metadata={
                "total_measurements": len(new_measurements),
                "remeasure_count": attempts + 1,
                "averaged": True,
                "repeatability_status": repeatability_result.status.value,
                "std_xyz": list(stats.std_xyz),
                "relative_std_Y_percent": stats.relative_std_Y,
            }
        )

        # Hide patch
        self._presenter.hide()

        # Notify if still failing
        if repeatability_result.status == RepeatabilityStatus.FAIL:
            logger.warning(f"Remeasure patch {patch_index} still failing: {repeatability_result.violations}")
            self._notify_remeasure_required(patch_index, updated_record)

        return (avg_result, updated_record)

    def generate_session_repeatability_summary(self) -> SessionRepeatabilitySummary:
        """
        Generate repeatability summary for current session.

        Returns:
            SessionRepeatabilitySummary: Summary of all patch repeatability

        Raises:
            MeasurementServiceError: If no session active
        """
        if not self._session:
            raise MeasurementServiceError(
                "No active session",
                error_code="NO_SESSION",
                state=self.state,
                recoverable=True
            )

        return generate_repeatability_summary(
            session_id=self._session.session_id,
            patch_records=self._repeatability_records
        )

    def get_patch_repeatability(self, patch_index: int) -> Optional[PatchRepeatabilityRecord]:
        """
        Get repeatability record for a specific patch.

        Args:
            patch_index: Index of the patch

        Returns:
            Optional[PatchRepeatabilityRecord]: Record if found, None otherwise
        """
        for record in self._repeatability_records:
            if record.patch_index == patch_index:
                return record
        return None
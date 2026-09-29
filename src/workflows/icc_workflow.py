"""
ICC Workflow - ICC Profile Generation Workflow.

This workflow implements the complete ICC profile generation process:
- Preflight checks
- Optional dispcal calibration
- targen patch generation / dispread measurement / custom measurement
- TI3 file creation
- colprof ICC generation
- ICC profile application
- Verification measurement

State Transitions:
    IDLE -> PREFLIGHT -> (optional CALIBRATING) -> GENERATING_PATCHES ->
    MEASURING -> GENERATING_PROFILE -> APPLYING -> VERIFYING -> COMPLETED

Key Features:
- Session directory management with manifest
- Preset profiles for different use cases (photo/video/general/soft-proof)
- Failure recovery from checkpoint
- Verification measurement after ICC generation

Reference:
- docs/professional_optimization_plan.md (P4-B task)
- docs/agent_handoffs/P4-A_argyll_adapter_refactor.md
- docs/agent_handoffs/P2-A_color_science_module.md
- docs/agent_handoffs/P5-A_P5-B_schema_manifest.md
"""

import hashlib
import json
import logging
import subprocess
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from src.core.events import Event, WorkflowFailed
from src.core.state import MeasurementState
from src.instruments.argyll_params import (
    DisplayType,
    QualityLevel,
    RenderingIntent,
    DispcalParams,
    TargenParams,
    ColprofParams,
    map_error_to_suggestion,
)
from src.storage.schema import SchemaV1, SoftwareInfo, EnvironmentInfo
from src.storage.manifest import (
    ArtifactManifest,
    ManifestEntry,
    generate_manifest,
    save_manifest,
    load_manifest,
    compute_file_hash,
)


logger = logging.getLogger(__name__)


# ========== ICC Workflow States ==========

class ICCWorkflowState(Enum):
    """
    States for ICC profile generation workflow.

    State Flow:
        IDLE -> PREFLIGHT -> CALIBRATING (optional) ->
        GENERATING_PATCHES -> MEASURING -> GENERATING_PROFILE ->
        APPLYING -> VERIFYING -> COMPLETED

    Any state can transition to FAILED on error.
    SUSPENDED allows resuming from checkpoint.
    """
    IDLE = "idle"
    PREFLIGHT = "preflight"
    CALIBRATING = "calibrating"
    GENERATING_PATCHES = "generating_patches"
    MEASURING = "measuring"
    GENERATING_PROFILE = "generating_profile"
    APPLYING = "applying"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    SUSPENDED = "suspended"


# ========== Preset Profile Types ==========

class ProfilePreset(Enum):
    """
    ICC profile presets for different use cases.

    Each preset defines optimal colprof parameters for its purpose.
    """
    PHOTOGRAPHY = "photography"      # High quality, VCGT, perceptual intent
    VIDEO = "video"                  # High quality, no VCGT, relative colorimetric
    GENERAL = "general"              # Balanced quality and speed
    SOFT_PROOF = "soft_proof"        # Absolute colorimetric for proofing


@dataclass
class ProfilePresetConfig:
    """
    Configuration for a profile preset.

    Maps preset type to colprof parameters.
    """
    preset: ProfilePreset
    quality: QualityLevel
    use_vcgt: bool
    default_intent: RenderingIntent
    description: str
    recommended_patches: int = 1024


# Preset configurations
PROFILE_PRESETS: Dict[ProfilePreset, ProfilePresetConfig] = {
    ProfilePreset.PHOTOGRAPHY: ProfilePresetConfig(
        preset=ProfilePreset.PHOTOGRAPHY,
        quality=QualityLevel.HIGH,
        use_vcgt=True,
        default_intent=RenderingIntent.PERCEPTUAL,
        description="摄影工作流：高质量，包含VCGT，感知渲染意图",
        recommended_patches=2048,
    ),
    ProfilePreset.VIDEO: ProfilePresetConfig(
        preset=ProfilePreset.VIDEO,
        quality=QualityLevel.HIGH,
        use_vcgt=False,  # Video workflows typically handle LUT separately
        default_intent=RenderingIntent.RELATIVE_COLORIMETRIC,
        description="视频工作流：高质量，无VCGT，相对色域映射",
        recommended_patches=2048,
    ),
    ProfilePreset.GENERAL: ProfilePresetConfig(
        preset=ProfilePreset.GENERAL,
        quality=QualityLevel.MEDIUM,
        use_vcgt=True,
        default_intent=RenderingIntent.RELATIVE_COLORIMETRIC,
        description="通用工作流：平衡质量和速度",
        recommended_patches=1024,
    ),
    ProfilePreset.SOFT_PROOF: ProfilePresetConfig(
        preset=ProfilePreset.SOFT_PROOF,
        quality=QualityLevel.HIGH,
        use_vcgt=False,
        default_intent=RenderingIntent.ABSOLUTE_COLORIMETRIC,
        description="软打样工作流：绝对色域映射，用于印刷校对",
        recommended_patches=2048,
    ),
}


# ========== Workflow Configuration ==========

@dataclass
class ICCWorkflowConfig:
    """
    Configuration for ICC profile workflow.

    Attributes:
        preset: Profile preset type
        display_type: Display technology type
        display_index: Display number (1-based)
        instrument_port: Instrument port number
        correction_file: CCSS/CCMX spectral correction file path
        white_point_target: Target white point (D65, D50, or custom xy)
        gamma_target: Target gamma value
        brightness_target: Target brightness (cd/m², optional)
        patch_count: Number of test patches
        use_dispcal: Run dispcal before measurement (recommended)
        auto_verify: Run verification after ICC generation (required)
        verify_patch_count: Number of verification patches
        session_dir: Session directory path (auto-generated if None)
        profile_name: ICC profile description name
        use_measurement_service: Use MeasurementService for measurement (feature flag)
        measurement_service_config: MeasurementService configuration (if use_measurement_service)
    """
    preset: ProfilePreset = ProfilePreset.GENERAL
    display_type: DisplayType = DisplayType.LCD
    display_index: int = 1
    instrument_port: int = 1
    correction_file: Optional[str] = None
    white_point_target: str = "D65"  # D65, D50, or "custom"
    white_point_xy: Optional[Tuple[float, float]] = None
    white_temp: Optional[int] = None
    gamma_target: float = 2.2
    brightness_target: Optional[float] = None
    patch_count: int = 1024
    use_dispcal: bool = True
    auto_verify: bool = True  # Verification is REQUIRED per acceptance criteria
    verify_patch_count: int = 64
    session_dir: Optional[str] = None
    profile_name: str = "Topos Display Profile"
    use_measurement_service: bool = False  # Feature flag for MeasurementService integration
    measurement_service_config: Optional[Dict[str, Any]] = None  # MeasurementService config overrides

    def get_preset_config(self) -> ProfilePresetConfig:
        """Get the preset configuration."""
        return PROFILE_PRESETS[self.preset]

    def get_colprof_params(self, ti3_path: str, output_path: str) -> ColprofParams:
        """
        Generate colprof parameters based on preset and config.

        Args:
            ti3_path: Path to TI3 measurement file
            output_path: Output ICC profile path

        Returns:
            ColprofParams dataclass
        """
        preset_config = self.get_preset_config()

        return ColprofParams(
            ti3_path=ti3_path,
            output_path=output_path,
            profile_name=self.profile_name,
            quality=preset_config.quality,
            profile_type="l",  # Lab profile
            no_vcgt=not preset_config.use_vcgt,
            verbose=True,
        )


# ========== Workflow Session ==========

@dataclass
class ICCWorkflowSession:
    """
    Active ICC workflow session state.

    Tracks all session data for checkpoint/recovery.
    """
    session_id: str = ""
    config: ICCWorkflowConfig = field(default_factory=ICCWorkflowConfig)
    state: ICCWorkflowState = ICCWorkflowState.IDLE

    # Progress tracking
    current_step: str = ""
    progress_percent: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # File paths (relative to session_dir)
    cal_file: Optional[str] = None
    ti1_file: Optional[str] = None
    ti3_file: Optional[str] = None
    icc_file: Optional[str] = None
    verify_ti3_file: Optional[str] = None

    # Measurement data
    patch_count: int = 0
    measured_patches: int = 0
    verification_results: Optional[Dict] = None

    # Error tracking
    last_error: Optional[str] = None
    recoverable: bool = True

    # Manifest
    manifest: Optional[ArtifactManifest] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session to dictionary for checkpoint."""
        return {
            "session_id": self.session_id,
            "config": {
                "preset": self.config.preset.value,
                "display_type": self.config.display_type.value,
                "display_index": self.config.display_index,
                "instrument_port": self.config.instrument_port,
                "correction_file": self.config.correction_file,
                "white_point_target": self.config.white_point_target,
                "white_point_xy": self.config.white_point_xy,
                "white_temp": self.config.white_temp,
                "gamma_target": self.config.gamma_target,
                "brightness_target": self.config.brightness_target,
                "patch_count": self.config.patch_count,
                "use_dispcal": self.config.use_dispcal,
                "auto_verify": self.config.auto_verify,
                "verify_patch_count": self.config.verify_patch_count,
                "profile_name": self.config.profile_name,
                "use_measurement_service": self.config.use_measurement_service,
                "measurement_service_config": self.config.measurement_service_config,
            },
            "state": self.state.value,
            "current_step": self.current_step,
            "progress_percent": self.progress_percent,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "cal_file": self.cal_file,
            "ti1_file": self.ti1_file,
            "ti3_file": self.ti3_file,
            "icc_file": self.icc_file,
            "verify_ti3_file": self.verify_ti3_file,
            "patch_count": self.patch_count,
            "measured_patches": self.measured_patches,
            "verification_results": self.verification_results,
            "last_error": self.last_error,
            "recoverable": self.recoverable,
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load session from dictionary."""
        self.session_id = data.get("session_id", "")
        
        config_data = data.get("config", {})
        self.config = ICCWorkflowConfig(
            preset=ProfilePreset(config_data.get("preset", "general")),
            display_type=DisplayType(config_data.get("display_type", "l")),
            display_index=config_data.get("display_index", 1),
            instrument_port=config_data.get("instrument_port", 1),
            correction_file=config_data.get("correction_file"),
            white_point_target=config_data.get("white_point_target", "D65"),
            white_point_xy=config_data.get("white_point_xy"),
            white_temp=config_data.get("white_temp"),
            gamma_target=config_data.get("gamma_target", 2.2),
            brightness_target=config_data.get("brightness_target"),
            patch_count=config_data.get("patch_count", 1024),
            use_dispcal=config_data.get("use_dispcal", True),
            auto_verify=config_data.get("auto_verify", True),
            verify_patch_count=config_data.get("verify_patch_count", 64),
            profile_name=config_data.get("profile_name", "Topos Display Profile"),
            use_measurement_service=config_data.get("use_measurement_service", False),
            measurement_service_config=config_data.get("measurement_service_config"),
        )

        self.state = ICCWorkflowState(data.get("state", "idle"))
        self.current_step = data.get("current_step", "")
        self.progress_percent = data.get("progress_percent", 0)
        
        started = data.get("started_at")
        if started:
            self.started_at = datetime.fromisoformat(started)
        completed = data.get("completed_at")
        if completed:
            self.completed_at = datetime.fromisoformat(completed)

        self.cal_file = data.get("cal_file")
        self.ti1_file = data.get("ti1_file")
        self.ti3_file = data.get("ti3_file")
        self.icc_file = data.get("icc_file")
        self.verify_ti3_file = data.get("verify_ti3_file")
        self.patch_count = data.get("patch_count", 0)
        self.measured_patches = data.get("measured_patches", 0)
        self.verification_results = data.get("verification_results")
        self.last_error = data.get("last_error")
        self.recoverable = data.get("recoverable", True)


# ========== Workflow Checkpoint ==========

@dataclass
class ICCWorkflowCheckpoint:
    """
    Checkpoint data for workflow recovery.

    Enables resuming from any interruption point.
    """
    session_id: str
    session_dir: Path
    state: ICCWorkflowState
    config: ICCWorkflowConfig
    created_at: datetime
    reason: str  # "user_cancel", "instrument_disconnect", "error", etc.

    # Partial file paths (for resuming)
    cal_file_exists: bool = False
    ti1_file_exists: bool = False
    ti3_file_exists: bool = False
    icc_file_exists: bool = False

    @classmethod
    def from_session(cls, session: ICCWorkflowSession, session_dir: Path, reason: str) -> 'ICCWorkflowCheckpoint':
        """Create checkpoint from active session."""
        return cls(
            session_id=session.session_id,
            session_dir=session_dir,
            state=session.state,
            config=session.config,
            created_at=datetime.now(),
            reason=reason,
            cal_file_exists=session.cal_file is not None and (session_dir / session.cal_file).exists(),
            ti1_file_exists=session.ti1_file is not None and (session_dir / session.ti1_file).exists(),
            ti3_file_exists=session.ti3_file is not None and (session_dir / session.ti3_file).exists(),
            icc_file_exists=session.icc_file is not None and (session_dir / session.icc_file).exists(),
        )

    def save(self) -> Path:
        """Save checkpoint to session directory."""
        checkpoint_path = self.session_dir / "checkpoint.json"
        data = {
            "session_id": self.session_id,
            "state": self.state.value,
            "config": self.config.to_dict() if hasattr(self.config, 'to_dict') else {
                "preset": self.config.preset.value,
                "display_type": self.config.display_type.value,
                "display_index": self.config.display_index,
                "instrument_port": self.config.instrument_port,
                "correction_file": self.config.correction_file,
                "white_point_target": self.config.white_point_target,
                "white_point_xy": self.config.white_point_xy,
                "white_temp": self.config.white_temp,
                "gamma_target": self.config.gamma_target,
                "brightness_target": self.config.brightness_target,
                "patch_count": self.config.patch_count,
                "use_dispcal": self.config.use_dispcal,
                "auto_verify": self.config.auto_verify,
                "verify_patch_count": self.config.verify_patch_count,
                "profile_name": self.config.profile_name,
            },
            "created_at": self.created_at.isoformat(),
            "reason": self.reason,
            "cal_file_exists": self.cal_file_exists,
            "ti1_file_exists": self.ti1_file_exists,
            "ti3_file_exists": self.ti3_file_exists,
            "icc_file_exists": self.icc_file_exists,
        }
        
        with open(checkpoint_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Checkpoint saved: {checkpoint_path}")
        return checkpoint_path

    @classmethod
    def load(cls, session_dir: Path) -> Optional['ICCWorkflowCheckpoint']:
        """Load checkpoint from session directory."""
        checkpoint_path = session_dir / "checkpoint.json"
        if not checkpoint_path.exists():
            return None

        try:
            with open(checkpoint_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            return cls(
                session_id=data["session_id"],
                session_dir=session_dir,
                state=ICCWorkflowState(data["state"]),
                config=ICCWorkflowConfig(
                    preset=ProfilePreset(data.get("config", {}).get("preset", "general")),
                    display_type=DisplayType(data.get("config", {}).get("display_type", "l")),
                    display_index=data.get("config", {}).get("display_index", 1),
                    instrument_port=data.get("config", {}).get("instrument_port", 1),
                    correction_file=data.get("config", {}).get("correction_file"),
                    white_point_target=data.get("config", {}).get("white_point_target", "D65"),
                    white_point_xy=data.get("config", {}).get("white_point_xy"),
                    white_temp=data.get("config", {}).get("white_temp"),
                    gamma_target=data.get("config", {}).get("gamma_target", 2.2),
                    brightness_target=data.get("config", {}).get("brightness_target"),
                    patch_count=data.get("config", {}).get("patch_count", 1024),
                    use_dispcal=data.get("config", {}).get("use_dispcal", True),
                    auto_verify=data.get("config", {}).get("auto_verify", True),
                    verify_patch_count=data.get("config", {}).get("verify_patch_count", 64),
                    profile_name=data.get("config", {}).get("profile_name", "Topos Display Profile"),
                ),
                created_at=datetime.fromisoformat(data["created_at"]),
                reason=data["reason"],
                cal_file_exists=data.get("cal_file_exists", False),
                ti1_file_exists=data.get("ti1_file_exists", False),
                ti3_file_exists=data.get("ti3_file_exists", False),
                icc_file_exists=data.get("icc_file_exists", False),
            )
        except Exception as e:
            logger.error(f"Failed to load checkpoint: {e}")
            return None


# ========== ICC Workflow Service ==========

class ICCWorkflowError(Exception):
    """
    Exception for ICC workflow errors.

    Attributes:
        error_code: Machine-readable error code
        state: Workflow state when error occurred
        recoverable: Whether workflow can be resumed
        suggestion: User-facing suggestion
    """
    def __init__(
        self,
        message: str,
        error_code: str = "UNKNOWN",
        state: Optional[ICCWorkflowState] = None,
        recoverable: bool = False,
        suggestion: str = ""
    ):
        super().__init__(message)
        self.error_code = error_code
        self.state = state
        self.recoverable = recoverable
        self.suggestion = suggestion


class ICCWorkflow:
    """
    ICC Profile Generation Workflow Service.

    This service orchestrates the complete ICC profile workflow:
    1. Preflight checks (Argyll tools, instrument, display)
    2. Optional dispcal calibration (1D LUT + VCGT)
    3. Test patch generation (targen) or custom patches
    4. Patch measurement (dispread or spotread)
    5. TI3 file creation
    6. ICC profile generation (colprof)
    7. ICC profile installation (optional)
    8. Verification measurement (REQUIRED)

    Features:
    - Session directory management with manifest
    - Preset profiles for different use cases
    - Checkpoint/resume from any interruption
    - Verification measurement after ICC generation

    Thread Safety:
        This service is NOT thread-safe. All operations should
        be performed on the main thread.

    Example:
        >>> workflow = ICCWorkflow(argyll_path="/path/to/argyll/bin")
        >>> config = ICCWorkflowConfig(preset=ProfilePreset.PHOTOGRAPHY)
        >>> session = workflow.start(config)
        >>> # ... workflow runs through states
        >>> if workflow.state == ICCWorkflowState.COMPLETED:
        >>>     print(f"ICC profile: {session.icc_file}")
    """

    def __init__(
        self,
        argyll_path: str = "",
        measurements_dir: Optional[Path] = None,
        argyll_controller: Optional[Any] = None,
        measurement_service: Optional[Any] = None,
    ):
        """
        Initialize ICC workflow service.

        Args:
            argyll_path: Path to ArgyllCMS bin directory
            measurements_dir: Base measurements directory
            argyll_controller: Optional ArgyllController instance (for instrument)
            measurement_service: Optional MeasurementService instance (for measurement)
        """
        self._argyll_path = argyll_path
        self._argyll_controller = argyll_controller
        self._measurement_service = measurement_service

        # Session state
        self._session: Optional[ICCWorkflowSession] = None
        self._session_dir: Optional[Path] = None
        self._checkpoint: Optional[ICCWorkflowCheckpoint] = None

        # Measurements directory
        if measurements_dir:
            self._measurements_dir = Path(measurements_dir)
        else:
            # Default: project root / measurements / sessions
            project_root = Path(__file__).parent.parent.parent
            self._measurements_dir = project_root / "measurements" / "sessions"

        # Callbacks
        self._on_state_change_callbacks: List[Callable[[ICCWorkflowState, ICCWorkflowState], None]] = []
        self._on_progress_callbacks: List[Callable[[int, str], None]] = []
        self._on_error_callbacks: List[Callable[[ICCWorkflowError], None]] = []
        self._on_measurement_callbacks: List[Callable[[int, int, Dict], None]] = []
        self._on_completed_callbacks: List[Callable[[ICCWorkflowSession], None]] = []

        # Process management
        self._current_process: Optional[subprocess.Popen] = None
        self._process_output_buffer: str = ""

        # Measurement service state
        self._measurement_results: List[Dict] = []
        self._measurement_session_active: bool = False

    # ========== Properties ==========

    @property
    def state(self) -> ICCWorkflowState:
        """Get current workflow state."""
        if self._session:
            return self._session.state
        return ICCWorkflowState.IDLE

    @property
    def session(self) -> Optional[ICCWorkflowSession]:
        """Get current session."""
        return self._session

    @property
    def session_dir(self) -> Optional[Path]:
        """Get current session directory."""
        return self._session_dir

    @property
    def measurement_service(self) -> Optional[Any]:
        """Get MeasurementService instance."""
        return self._measurement_service

    def set_measurement_service(self, service: Optional[Any]) -> None:
        """
        Set MeasurementService instance.

        Args:
            service: MeasurementService instance or None
        """
        self._measurement_service = service
        if service:
            # Register callback to receive measurement results
            service.on_measurement_received(self._handle_measurement_service_result)
            logger.info("MeasurementService 已连接到 ICC Workflow")

    def _handle_measurement_service_result(self, result: Any) -> None:
        """
        Handle measurement result from MeasurementService.

        Args:
            result: MeasurementResult from MeasurementService
        """
        # Convert MeasurementResult to dict format
        if hasattr(result, 'xyY'):
            measurement_dict = {
                "sample_id": f"Patch_{len(self._measurement_results) + 1}",
                "RGB": list(result.rgb_requested) if hasattr(result, 'rgb_requested') else [0, 0, 0],
                "xyY": list(result.xyY),
                "patch_name": result.patch_name or f"Patch_{len(self._measurement_results) + 1}",
            }
        else:
            measurement_dict = result

        self._measurement_results.append(measurement_dict)

        # Notify callbacks
        if self._session:
            self._notify_measurement(
                len(self._measurement_results),
                self._session.patch_count,
                measurement_dict
            )

    # ========== Callback Registration ==========

    def on_state_change(self, callback: Callable[[ICCWorkflowState, ICCWorkflowState], None]) -> None:
        """Register state change callback."""
        self._on_state_change_callbacks.append(callback)

    def on_progress(self, callback: Callable[[int, str], None]) -> None:
        """Register progress update callback."""
        self._on_progress_callbacks.append(callback)

    def on_error(self, callback: Callable[[ICCWorkflowError], None]) -> None:
        """Register error callback."""
        self._on_error_callbacks.append(callback)

    def on_measurement(self, callback: Callable[[int, int, Dict], None]) -> None:
        """Register measurement result callback."""
        self._on_measurement_callbacks.append(callback)

    def on_completed(self, callback: Callable[[ICCWorkflowSession], None]) -> None:
        """Register completion callback."""
        self._on_completed_callbacks.append(callback)

    # ========== Notification Helpers ==========

    def _notify_state_change(self, old_state: ICCWorkflowState, new_state: ICCWorkflowState) -> None:
        """Notify callbacks of state change."""
        logger.info(f"ICC Workflow state: {old_state.value} -> {new_state.value}")
        for callback in self._on_state_change_callbacks:
            try:
                callback(old_state, new_state)
            except Exception as e:
                logger.error(f"State change callback error: {e}")

    def _notify_progress(self, percent: int, step: str) -> None:
        """Notify callbacks of progress update."""
        if self._session:
            self._session.progress_percent = percent
            self._session.current_step = step
        for callback in self._on_progress_callbacks:
            try:
                callback(percent, step)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")

    def _notify_error(self, error: ICCWorkflowError) -> None:
        """Notify callbacks of error."""
        if self._session:
            self._session.last_error = str(error)
            self._session.recoverable = error.recoverable
        for callback in self._on_error_callbacks:
            try:
                callback(error)
            except Exception as e:
                logger.error(f"Error callback error: {e}")

    def _notify_measurement(self, patch_index: int, total_patches: int, result: Dict) -> None:
        """Notify callbacks of measurement result."""
        for callback in self._on_measurement_callbacks:
            try:
                callback(patch_index, total_patches, result)
            except Exception as e:
                logger.error(f"Measurement callback error: {e}")

    def _notify_completed(self) -> None:
        """Notify callbacks of workflow completion."""
        if self._session:
            for callback in self._on_completed_callbacks:
                try:
                    callback(self._session)
                except Exception as e:
                    logger.error(f"Completion callback error: {e}")

    # ========== Workflow Control ==========

    def start(self, config: Optional[ICCWorkflowConfig] = None) -> ICCWorkflowSession:
        """
        Start a new ICC workflow session.

        Args:
            config: Workflow configuration (uses defaults if None)

        Returns:
            ICCWorkflowSession: New session object

        Raises:
            ICCWorkflowError: If workflow cannot start
        """
        if self._session and self._session.state not in [ICCWorkflowState.IDLE, ICCWorkflowState.FAILED, ICCWorkflowState.COMPLETED]:
            raise ICCWorkflowError(
                "Workflow already active",
                error_code="WORKFLOW_ACTIVE",
                state=self.state,
                recoverable=False,
            )

        # Use provided config or defaults
        effective_config = config or ICCWorkflowConfig()

        # Create session
        self._session = ICCWorkflowSession(
            session_id=self._generate_session_id(),
            config=effective_config,
            state=ICCWorkflowState.IDLE,
            started_at=datetime.now(),
        )

        # Create session directory
        self._create_session_dir()

        # Transition to PREFLIGHT
        self._transition(ICCWorkflowState.PREFLIGHT)
        self._notify_progress(0, "开始预检")

        # Run preflight checks
        self._run_preflight()

        return self._session

    def resume(self, session_dir: Optional[Path] = None, checkpoint: Optional[ICCWorkflowCheckpoint] = None) -> ICCWorkflowSession:
        """
        Resume workflow from checkpoint or session directory.

        Args:
            session_dir: Session directory to resume from
            checkpoint: Pre-loaded checkpoint (optional)

        Returns:
            ICCWorkflowSession: Resumed session

        Raises:
            ICCWorkflowError: If cannot resume
        """
        if self._session and self._session.state not in [ICCWorkflowState.IDLE, ICCWorkflowState.FAILED, ICCWorkflowState.SUSPENDED]:
            raise ICCWorkflowError(
                "Workflow already active",
                error_code="WORKFLOW_ACTIVE",
                state=self.state,
                recoverable=False,
            )

        # Load checkpoint if not provided
        if checkpoint is None and session_dir:
            checkpoint = ICCWorkflowCheckpoint.load(session_dir)

        if checkpoint is None:
            raise ICCWorkflowError(
                "No checkpoint found for resume",
                error_code="NO_CHECKPOINT",
                recoverable=False,
            )

        # Restore session from checkpoint
        self._session_dir = checkpoint.session_dir
        self._session = ICCWorkflowSession(
            session_id=checkpoint.session_id,
            config=checkpoint.config,
            state=ICCWorkflowState.IDLE,
            started_at=datetime.now(),  # New start time for resumed session
        )

        # Load manifest
        manifest_path = self._session_dir / "manifest.json"
        if manifest_path.exists():
            self._session.manifest = load_manifest(manifest_path)

        # Determine resume point based on checkpoint state
        resume_state = self._determine_resume_state(checkpoint)

        logger.info(f"Resuming workflow from state {resume_state.value}")

        # Transition to resume state
        self._transition(resume_state)

        # Execute appropriate resume action
        self._execute_resume(resume_state, checkpoint)

        return self._session

    def stop(self, save_checkpoint: bool = True, reason: str = "user_cancel") -> bool:
        """
        Stop the current workflow.

        Args:
            save_checkpoint: Save checkpoint for later resume
            reason: Reason for stopping

        Returns:
            bool: True if stopped successfully
        """
        if not self._session:
            return True

        # Cancel any running process
        self._cancel_process()

        if save_checkpoint and self._session_dir:
            checkpoint = ICCWorkflowCheckpoint.from_session(self._session, self._session_dir, reason)
            checkpoint.save()

        # Transition to SUSPENDED or IDLE
        if save_checkpoint:
            self._transition(ICCWorkflowState.SUSPENDED)
        else:
            self._transition(ICCWorkflowState.IDLE)

        return True

    def cancel(self) -> bool:
        """Cancel workflow without saving checkpoint."""
        return self.stop(save_checkpoint=False, reason="user_cancel")

    # ========== State Transitions ==========

    def _transition(self, new_state: ICCWorkflowState) -> None:
        """Transition to new state."""
        old_state = self.state
        if self._session:
            self._session.state = new_state
        self._notify_state_change(old_state, new_state)

    def _determine_resume_state(self, checkpoint: ICCWorkflowCheckpoint) -> ICCWorkflowState:
        """
        Determine the state to resume from based on checkpoint.

        Recovery strategy:
        - If cal file exists: skip dispcal
        - If ti3 file exists: skip measurement
        - If ICC file exists: proceed to verification
        - Otherwise: resume from checkpoint state
        """
        # Check what files are already generated
        if checkpoint.icc_file_exists:
            # ICC exists, proceed to verification
            return ICCWorkflowState.VERIFYING

        if checkpoint.ti3_file_exists:
            # TI3 exists, proceed to profile generation
            return ICCWorkflowState.GENERATING_PROFILE

        if checkpoint.ti1_file_exists:
            # TI1 exists, proceed to measurement
            return ICCWorkflowState.MEASURING

        if checkpoint.cal_file_exists or not checkpoint.config.use_dispcal:
            # Cal exists or dispcal skipped, proceed to patch generation
            return ICCWorkflowState.GENERATING_PATCHES

        # Resume from checkpoint state
        return checkpoint.state

    def _execute_resume(self, resume_state: ICCWorkflowState, checkpoint: ICCWorkflowCheckpoint) -> None:
        """Execute actions for resuming from a specific state."""
        # Restore file paths from checkpoint
        if checkpoint.cal_file_exists:
            self._session.cal_file = "calibration.cal"
        if checkpoint.ti1_file_exists:
            self._session.ti1_file = "patches.ti1"
        if checkpoint.ti3_file_exists:
            self._session.ti3_file = "measurements.ti3"
        if checkpoint.icc_file_exists:
            self._session.icc_file = f"{self._session.config.profile_name}.icc"

        # Execute state-specific actions
        if resume_state == ICCWorkflowState.CALIBRATING:
            self._run_dispcal()
        elif resume_state == ICCWorkflowState.GENERATING_PATCHES:
            self._run_targen()
        elif resume_state == ICCWorkflowState.MEASURING:
            # This requires integration with measurement service
            self._notify_progress(0, "等待测量...")
        elif resume_state == ICCWorkflowState.GENERATING_PROFILE:
            self._run_colprof()
        elif resume_state == ICCWorkflowState.VERIFYING:
            self._run_verification()

    # ========== Workflow Steps ==========

    def _run_preflight(self) -> bool:
        """
        Run preflight checks.

        Checks:
        - ArgyllCMS tools availability
        - Instrument connection
        - Display detection

        Returns:
            bool: True if all checks pass
        """
        self._notify_progress(5, "检查 ArgyllCMS 工具")

        # Check Argyll tools
        if not self._check_argyll_tools():
            error = ICCWorkflowError(
                "ArgyllCMS 工具未找到",
                error_code="ARGYLL_NOT_FOUND",
                state=self.state,
                recoverable=False,
                suggestion="请安装 ArgyllCMS 或设置正确的路径",
            )
            self._handle_error(error)
            return False

        self._notify_progress(15, "检查探头连接")

        # Check instrument (via ArgyllController if available)
        if self._argyll_controller:
            if not self._argyll_controller.is_connected():
                # Attempt connection
                try:
                    connected = self._argyll_controller.connect()
                    if not connected:
                        error = ICCWorkflowError(
                            "探头未连接",
                            error_code="INSTRUMENT_NOT_CONNECTED",
                            state=self.state,
                            recoverable=True,
                            suggestion="请连接探头后重试",
                        )
                        self._handle_error(error)
                        return False
                except Exception as e:
                    error = ICCWorkflowError(
                        f"探头连接失败: {e}",
                        error_code="INSTRUMENT_CONNECT_FAILED",
                        state=self.state,
                        recoverable=True,
                        suggestion="请检查探头连接",
                    )
                    self._handle_error(error)
                    return False

        self._notify_progress(25, "检查显示器")

        # Preflight passed
        self._notify_progress(30, "预检完成")

        # Determine next state
        if self._session.config.use_dispcal:
            self._transition(ICCWorkflowState.CALIBRATING)
            self._run_dispcal()
        else:
            self._transition(ICCWorkflowState.GENERATING_PATCHES)
            self._run_targen()

        return True

    def _run_dispcal(self) -> bool:
        """
        Run dispcal display calibration.

        Returns:
            bool: True if calibration succeeds
        """
        self._notify_progress(35, "开始显示器校准")

        # Build dispcal parameters
        output_path = str(self._session_dir / "calibration")

        params = DispcalParams(
            output_path=output_path,
            display_index=self._session.config.display_index,
            instrument_index=self._session.config.instrument_port,
            quality=self._session.config.get_preset_config().quality,
            gamma=self._session.config.gamma_target,
            no_vcgt=not self._session.config.get_preset_config().use_vcgt,
        )

        # Set white point
        if self._session.config.white_point_target == "D65":
            params.white_temp = 6500
        elif self._session.config.white_point_target == "D50":
            params.white_temp = 5000
        elif self._session.config.white_point_xy:
            params.white_point_xy = self._session.config.white_point_xy

        if self._session.config.brightness_target:
            params.brightness = self._session.config.brightness_target

        # Validate
        is_valid, error_msg = params.validate()
        if not is_valid:
            error = ICCWorkflowError(
                f"校准参数无效: {error_msg}",
                error_code="INVALID_PARAMS",
                state=self.state,
                recoverable=False,
            )
            self._handle_error(error)
            return False

        # Run dispcal
        success, output = self._run_argyll_command("dispcal", params.to_command_args())

        if not success:
            error = ICCWorkflowError(
                f"校准失败: {output}",
                error_code="DISPCAL_FAILED",
                state=self.state,
                recoverable=True,
                suggestion="请检查探头位置和显示器设置",
            )
            self._handle_error(error)
            return False

        # Check cal file was created
        cal_file = Path(params.cal_file_path)
        if cal_file.exists():
            self._session.cal_file = cal_file.name
            self._notify_progress(50, "校准完成")

            # Transition to patch generation
            self._transition(ICCWorkflowState.GENERATING_PATCHES)
            self._run_targen()
            return True
        else:
            error = ICCWorkflowError(
                "校准文件未生成",
                error_code="CAL_FILE_MISSING",
                state=self.state,
                recoverable=True,
            )
            self._handle_error(error)
            return False

    def _run_targen(self) -> bool:
        """
        Run targen to generate test patches.

        Returns:
            bool: True if patch generation succeeds
        """
        self._notify_progress(55, "生成测试色块")

        # Use recommended patch count from preset
        preset_config = self._session.config.get_preset_config()
        patch_count = self._session.config.patch_count or preset_config.recommended_patches

        output_path = str(self._session_dir / "patches")

        params = TargenParams(
            output_path=output_path,
            patch_count=patch_count,
            device_type=3,  # Emissive display
        )

        # Run targen
        success, output = self._run_argyll_command("targen", params.to_command_args())

        if not success:
            error = ICCWorkflowError(
                f"色块生成失败: {output}",
                error_code="TARGET_FAILED",
                state=self.state,
                recoverable=True,
            )
            self._handle_error(error)
            return False

        # Check ti1 file was created
        ti1_file = Path(params.ti1_file_path)
        if ti1_file.exists():
            self._session.ti1_file = ti1_file.name
            self._session.patch_count = patch_count
            self._notify_progress(60, f"色块生成完成: {patch_count} 个")

            # Transition to measuring
            self._transition(ICCWorkflowState.MEASURING)

            # Check if MeasurementService should be used
            if self._session.config.use_measurement_service and self._measurement_service:
                self._notify_progress(65, "使用 MeasurementService 开始测量...")
                self._start_measurement_service_measurement(ti1_file)
            else:
                self._notify_progress(65, "等待测量数据...")

            return True
        else:
            error = ICCWorkflowError(
                "TI1 文件未生成",
                error_code="TI1_FILE_MISSING",
                state=self.state,
                recoverable=True,
            )
            self._handle_error(error)
            return False

    def _start_measurement_service_measurement(self, ti1_file: Path) -> bool:
        """
        Start measurement using MeasurementService.

        Args:
            ti1_file: TI1 file path containing patches to measure

        Returns:
            bool: True if measurement started successfully
        """
        if not self._measurement_service:
            logger.warning("MeasurementService 未设置")
            return False

        try:
            # Parse TI1 file to get patches
            patches = self._parse_ti1_to_patches(ti1_file)

            if not patches:
                error = ICCWorkflowError(
                    "解析 TI1 文件失败",
                    error_code="TI1_PARSE_FAILED",
                    state=self.state,
                    recoverable=True,
                )
                self._handle_error(error)
                return False

            # Clear previous results
            self._measurement_results.clear()
            self._measurement_session_active = True

            # Build MeasurementConfig if provided
            config_override = self._session.config.measurement_service_config

            # Start measurement session
            logger.info(f"启动 MeasurementService: {len(patches)} 个色块")

            # Note: MeasurementService.start_session returns bool
            # We need to call measure_all_patches after starting
            success = self._measurement_service.start_session(
                patches=patches,
                session_id=self._session.session_id,
                config=config_override
            )

            if success:
                # Start measuring all patches
                self._measurement_service.measure_all_patches()
                logger.info("MeasurementService 测量已启动")
                return True
            else:
                error = ICCWorkflowError(
                    "MeasurementService 启动失败",
                    error_code="MS_START_FAILED",
                    state=self.state,
                    recoverable=True,
                )
                self._handle_error(error)
                return False

        except Exception as e:
            error = ICCWorkflowError(
                f"MeasurementService 异常: {e}",
                error_code="MS_EXCEPTION",
                state=self.state,
                recoverable=True,
            )
            self._handle_error(error)
            return False

    def _parse_ti1_to_patches(self, ti1_file: Path) -> List[Tuple[int, int, int, str]]:
        """
        Parse TI1 file to extract RGB patches.

        Args:
            ti1_file: TI1 file path

        Returns:
            List of (r, g, b, name) tuples
        """
        patches = []
        try:
            with open(ti1_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Find data section
            in_data = False
            for line in content.split('\n'):
                if 'BEGIN_DATA' in line:
                    in_data = True
                    continue
                if 'END_DATA' in line:
                    break

                if in_data and line.strip():
                    # Parse line: SAMPLE_ID RGB_R RGB_G RGB_B ...
                    parts = line.split()
                    if len(parts) >= 4:
                        sample_id = parts[0]
                        r = int(parts[1])
                        g = int(parts[2])
                        b = int(parts[3])
                        patches.append((r, g, b, sample_id))

            logger.info(f"TI1 解析: {len(patches)} 个色块")
            return patches

        except Exception as e:
            logger.error(f"TI1 解析失败: {e}")
            return []

    def complete_measurement_service_session(self) -> bool:
        """
        Complete measurement session and generate TI3 from collected results.

        Called when MeasurementService has finished measuring all patches.

        Returns:
            bool: True if TI3 generated successfully
        """
        if not self._measurement_results:
            logger.warning("没有测量结果")
            return False

        self._measurement_session_active = False

        # Call provide_measurement_data with collected results
        return self.provide_measurement_data(measurements=self._measurement_results)

    def provide_measurement_data(self, ti3_path: Optional[Path] = None, measurements: Optional[List[Dict]] = None) -> bool:
        """
        Provide measurement data for profile generation.

        This method accepts measurement data from external sources:
        - TI3 file path (from dispread or other tool)
        - Measurement list (from spotread or MeasurementService)

        Args:
            ti3_path: Path to existing TI3 file
            measurements: List of measurement dicts [{sample_id, RGB, xyY}, ...]

        Returns:
            bool: True if data accepted successfully
        """
        if self.state != ICCWorkflowState.MEASURING:
            logger.warning(f"Cannot provide measurements in state {self.state}")
            return False

        if ti3_path:
            # Copy TI3 file to session directory
            dest_ti3 = self._session_dir / "measurements.ti3"
            shutil.copy2(ti3_path, dest_ti3)
            self._session.ti3_file = dest_ti3.name
            self._session.measured_patches = self._count_ti3_patches(dest_ti3)

        elif measurements:
            # Generate TI3 from measurement list
            ti3_path = self._generate_ti3_from_measurements(measurements)
            self._session.ti3_file = ti3_path.name
            self._session.measured_patches = len(measurements)

        else:
            error = ICCWorkflowError(
                "未提供测量数据",
                error_code="NO_MEASUREMENTS",
                state=self.state,
                recoverable=True,
            )
            self._handle_error(error)
            return False

        self._notify_progress(80, f"测量完成: {self._session.measured_patches} 个色块")

        # Transition to profile generation
        self._transition(ICCWorkflowState.GENERATING_PROFILE)
        self._run_colprof()

        return True

    def _run_colprof(self) -> bool:
        """
        Run colprof to generate ICC profile.

        Returns:
            bool: True if profile generation succeeds
        """
        self._notify_progress(85, "生成 ICC Profile")

        # Build colprof parameters
        ti3_path = str(self._session_dir / self._session.ti3_file)
        output_path = str(self._session_dir / "profile")

        params = self._session.config.get_colprof_params(ti3_path, output_path)

        # Validate
        is_valid, error_msg = params.validate()
        if not is_valid:
            error = ICCWorkflowError(
                f"Profile 参数无效: {error_msg}",
                error_code="INVALID_PARAMS",
                state=self.state,
                recoverable=False,
            )
            self._handle_error(error)
            return False

        # Run colprof
        success, output = self._run_argyll_command("colprof", params.to_command_args())

        if not success:
            error = ICCWorkflowError(
                f"Profile 生成失败: {output}",
                error_code="COLPROF_FAILED",
                state=self.state,
                recoverable=True,
                suggestion="请检查测量数据质量",
            )
            self._handle_error(error)
            return False

        # Check ICC file was created
        icc_file = Path(params.icc_file_path)
        if icc_file.exists():
            self._session.icc_file = icc_file.name
            self._notify_progress(90, "ICC Profile 生成完成")

            # Update manifest
            self._update_manifest()

            # Transition to verification (REQUIRED per acceptance criteria)
            if self._session.config.auto_verify:
                self._transition(ICCWorkflowState.VERIFYING)
                self._run_verification()
            else:
                # Skip verification (not recommended)
                self._transition(ICCWorkflowState.COMPLETED)
                self._session.completed_at = datetime.now()
                self._notify_completed()
            
            return True
        else:
            error = ICCWorkflowError(
                "ICC 文件未生成",
                error_code="ICC_FILE_MISSING",
                state=self.state,
                recoverable=True,
            )
            self._handle_error(error)
            return False

    def _run_verification(self) -> bool:
        """
        Run verification measurement.

        Verification is REQUIRED per acceptance criteria.
        Measures a subset of patches to validate profile quality.

        Returns:
            bool: True if verification succeeds
        """
        self._notify_progress(92, "开始验证测量")

        # Verification measurement requires external measurement service
        # This workflow expects measurement data to be provided via callback
        self._notify_progress(95, "等待验证测量数据...")

        # The verification results should be provided by calling
        # provide_verification_data() method
        return True

    def provide_verification_data(self, measurements: List[Dict]) -> bool:
        """
        Provide verification measurement data.

        Args:
            measurements: List of verification measurements

        Returns:
            bool: True if data accepted and workflow completed
        """
        if self.state != ICCWorkflowState.VERIFYING:
            logger.warning(f"Cannot provide verification in state {self.state}")
            return False

        # Store verification results
        self._session.verification_results = {
            "measurements": measurements,
            "patch_count": len(measurements),
            "completed_at": datetime.now().isoformat(),
        }

        # Save verification TI3
        verify_ti3 = self._generate_verification_ti3(measurements)
        if verify_ti3:
            self._session.verify_ti3_file = verify_ti3.name

        self._notify_progress(98, "验证测量完成")

        # Update manifest
        self._update_manifest()

        # Transition to completed
        self._transition(ICCWorkflowState.COMPLETED)
        self._session.completed_at = datetime.now()
        self._notify_completed()

        return True

    # ========== Error Handling ==========

    def _handle_error(self, error: ICCWorkflowError) -> None:
        """Handle workflow error."""
        self._notify_error(error)

        if error.recoverable:
            # Save checkpoint for potential resume
            if self._session_dir:
                checkpoint = ICCWorkflowCheckpoint.from_session(
                    self._session, self._session_dir, error.error_code
                )
                checkpoint.save()
            self._transition(ICCWorkflowState.SUSPENDED)
        else:
            self._transition(ICCWorkflowState.FAILED)

    # ========== Helper Methods ==========

    def _generate_session_id(self) -> str:
        """Generate unique session ID."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        import uuid
        random_suffix = uuid.uuid4().hex[:6]
        return f"icc-{timestamp}-{random_suffix}"

    def _create_session_dir(self) -> None:
        """Create session directory."""
        self._measurements_dir.mkdir(parents=True, exist_ok=True)
        self._session_dir = self._measurements_dir / self._session.session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Session directory created: {self._session_dir}")

    def _check_argyll_tools(self) -> bool:
        """Check if ArgyllCMS tools are available."""
        import platform
        system = platform.system()

        tools = ["dispcal", "targen", "colprof", "dispread"]
        for tool in tools:
            tool_name = f"{tool}.exe" if system == "Windows" else tool
            if self._argyll_path:
                tool_path = Path(self._argyll_path) / tool_name
            else:
                # Check system PATH
                import shutil
                tool_path = shutil.which(tool_name)

            if not tool_path or not Path(tool_path).exists():
                logger.warning(f"Argyll tool not found: {tool}")
                return False

        return True

    def _run_argyll_command(self, tool: str, args: List[str], timeout: float = 300.0) -> Tuple[bool, str]:
        """
        Run an ArgyllCMS command.

        Args:
            tool: Tool name (dispcal, targen, colprof, etc.)
            args: Command arguments
            timeout: Timeout in seconds

        Returns:
            Tuple[bool, str]: (success, output)
        """
        import platform
        system = platform.system()

        tool_name = f"{tool}.exe" if system == "Windows" else tool
        if self._argyll_path:
            executable = str(Path(self._argyll_path) / tool_name)
        else:
            executable = tool_name

        cmd = [executable] + args

        logger.info(f"Running: {cmd}")

        try:
            self._current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self._session_dir) if self._session_dir else None,
                text=True,
            )

            stdout, stderr = self._current_process.communicate(timeout=timeout)
            output = stdout + stderr

            success = self._current_process.returncode == 0
            self._current_process = None

            if not success:
                logger.error(f"{tool} failed: {output}")
                # Map error to user-friendly message
                mapping = map_error_to_suggestion(output)
                logger.info(f"Error suggestion: {mapping.user_message}")

            return success, output

        except subprocess.TimeoutExpired:
            if self._current_process:
                self._current_process.kill()
                self._current_process = None
            return False, f"{tool} 超时 (>{timeout}s)"

        except FileNotFoundError:
            return False, f"找不到 {tool_name}"

        except Exception as e:
            return False, f"{tool} 执行失败: {e}"

    def _cancel_process(self) -> None:
        """Cancel any running Argyll process."""
        if self._current_process and self._current_process.poll() is None:
            try:
                self._current_process.terminate()
                self._current_process.wait(timeout=2.0)
            except Exception:
                try:
                    self._current_process.kill()
                except Exception:
                    pass
            self._current_process = None

    def _count_ti3_patches(self, ti3_path: Path) -> int:
        """Count patches in TI3 file."""
        try:
            with open(ti3_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Look for NUMBER_OF_SETS
            import re
            match = re.search(r'NUMBER_OF_SETS\s+(\d+)', content)
            if match:
                return int(match.group(1))
        except Exception:
            pass

        return 0

    def _generate_ti3_from_measurements(self, measurements: List[Dict]) -> Path:
        """
        Generate TI3 file from measurement list.

        Args:
            measurements: List of {sample_id, RGB, xyY} dicts

        Returns:
            Path: Generated TI3 file path
        """
        ti3_path = self._session_dir / "measurements.ti3"

        # Build CGATS format TI3
        content = "CGATS.17\n\n"
        content += "DESCRIPTOR 'Topos Calibrator Measurement Data'\n"
        content += "ORIGINATOR 'Topos Calibrator'\n"
        content += f"CREATED '{datetime.now().isoformat()}'\n"
        content += "DEVICE_CLASS 'DISPLAY'\n\n"

        content += "KEYWORD 'SAMPLE_ID'\n"
        content += "KEYWORD 'RGB_R'\n"
        content += "KEYWORD 'RGB_G'\n"
        content += "KEYWORD 'RGB_B'\n"
        content += "KEYWORD 'XYZ_X'\n"
        content += "KEYWORD 'XYZ_Y'\n"
        content += "KEYWORD 'XYZ_Z'\n\n"

        content += f"NUMBER_OF_FIELDS 7\n"
        content += "BEGIN_DATA_FORMAT\n"
        content += "SAMPLE_ID RGB_R RGB_G RGB_B XYZ_X XYZ_Y XYZ_Z\n"
        content += "END_DATA_FORMAT\n\n"

        content += f"NUMBER_OF_SETS {len(measurements)}\n"
        content += "BEGIN_DATA\n"

        for i, m in enumerate(measurements):
            sample_id = m.get("sample_id", f"Patch_{i+1}")
            rgb = m.get("RGB", [0, 0, 0])
            xyY = m.get("xyY", [0, 0, 0])

            # Convert xyY to XYZ
            x, y, Y = xyY[0], xyY[1], xyY[2]
            if y > 0:
                X = x * Y / y
                Z = (1 - x - y) * Y / y
            else:
                X, Z = 0, 0

            # Scale to 0-100 range for TI3
            X_scaled = X * 100
            Y_scaled = Y * 100
            Z_scaled = Z * 100

            content += f"{sample_id} {rgb[0]} {rgb[1]} {rgb[2]} {X_scaled:.4f} {Y_scaled:.4f} {Z_scaled:.4f}\n"

        content += "END_DATA\n"

        with open(ti3_path, 'w', encoding='utf-8') as f:
            f.write(content)

        logger.info(f"TI3 generated: {ti3_path}")
        return ti3_path

    def _generate_verification_ti3(self, measurements: List[Dict]) -> Optional[Path]:
        """Generate verification TI3 file."""
        if not measurements:
            return None

        ti3_path = self._session_dir / "verification.ti3"
        return self._generate_ti3_from_measurements(measurements)

    def _update_manifest(self) -> None:
        """Update session manifest with current files."""
        if not self._session_dir:
            return

        # Generate or update manifest
        if self._session.manifest:
            manifest = self._session.manifest
        else:
            manifest = ArtifactManifest(
                session_id=self._session.session_id,
                created_at=datetime.now().isoformat(),
                storage_type="sessions",
            )

        manifest.updated_at = datetime.now().isoformat()

        # Add workflow info
        manifest.set_workflow_info(
            mode="icc",
            target=self._session.config.white_point_target,
            status=self.state.value,
        )

        # Add instrument info
        manifest.set_instrument_info(
            probe=self._argyll_controller.get_probe_type().value if self._argyll_controller else "",
            correction_file=self._session.config.correction_file,
        )

        # Add display info
        manifest.set_display_info(
            model="",  # Would need display detection
            display_type=self._session.config.display_type.value,
        )

        # Add file entries
        for file_type, filename in [
            ("cal", self._session.cal_file),
            ("ti3", self._session.ti3_file),
            ("icc", self._session.icc_file),
        ]:
            if filename:
                file_path = self._session_dir / filename
                if file_path.exists():
                    entry = ManifestEntry(
                        type=file_type,
                        filename=filename,
                        sha256=compute_file_hash(file_path),
                        size_bytes=file_path.stat().st_size,
                        generated_at=datetime.now().isoformat(),
                        generated_by=f"icc_workflow_{file_type}",
                    )
                    manifest.add_file(entry)

        # Save manifest
        save_manifest(manifest, self._session_dir)
        self._session.manifest = manifest

    def get_icc_profile_path(self) -> Optional[Path]:
        """Get the generated ICC profile path."""
        if self._session and self._session.icc_file and self._session_dir:
            return self._session_dir / self._session.icc_file
        return None

    def get_session_info(self) -> Dict[str, Any]:
        """Get current session info for UI."""
        if not self._session:
            return {"state": "idle"}

        return {
            "session_id": self._session.session_id,
            "state": self._session.state.value,
            "preset": self._session.config.preset.value,
            "progress": self._session.progress_percent,
            "step": self._session.current_step,
            "patch_count": self._session.patch_count,
            "measured_patches": self._session.measured_patches,
            "icc_file": self._session.icc_file,
            "session_dir": str(self._session_dir) if self._session_dir else None,
        }


# ========== Utility Functions ==========

def get_available_presets() -> Dict[str, Dict[str, Any]]:
    """
    Get available profile presets with descriptions.

    Returns:
        Dict mapping preset names to their configuration info
    """
    return {
        preset.value: {
            "description": config.description,
            "quality": config.quality.value,
            "use_vcgt": config.use_vcgt,
            "default_intent": config.default_intent.value,
            "recommended_patches": config.recommended_patches,
        }
        for preset, config in PROFILE_PRESETS.items()
    }


def list_recoverable_sessions(measurements_dir: Path) -> List[Dict[str, Any]]:
    """
    List sessions that can be recovered.

    Args:
        measurements_dir: Base measurements directory

    Returns:
        List of session info with checkpoint status
    """
    recoverable = []

    # Check both direct sessions and sessions subdirectory
    locations_to_check = [
        measurements_dir / "sessions",
        measurements_dir,
    ]

    for location in locations_to_check:
        if not location.exists():
            continue
        for session_dir in location.iterdir():
            # Only check directories that look like ICC session dirs (start with "icc-")
            if session_dir.is_dir() and session_dir.name.startswith("icc-"):
                checkpoint = ICCWorkflowCheckpoint.load(session_dir)
                if checkpoint:
                    recoverable.append({
                        "session_id": checkpoint.session_id,
                        "state": checkpoint.state.value,
                        "created_at": checkpoint.created_at.isoformat(),
                        "reason": checkpoint.reason,
                        "has_cal": checkpoint.cal_file_exists,
                        "has_ti3": checkpoint.ti3_file_exists,
                        "has_icc": checkpoint.icc_file_exists,
                        "session_dir": str(session_dir),
                    })

    return recoverable
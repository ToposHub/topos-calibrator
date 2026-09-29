"""
Backend-MeasurementService Bridge - Integrates Backend with MeasurementService.

This module provides a bridge layer that:
1. Wraps Backend's ArgyllController as InstrumentAdapter
2. Wraps Backend's patch display as PatchPresenter
3. Configures MeasurementService callbacks to trigger Backend signals
4. Provides simplified interface for Backend to use MeasurementService

Design principles:
- Minimal changes to Backend (import and delegate, not rewrite)
- Backend retains all QWebChannel signal/slot interfaces
- MeasurementService handles measurement orchestration
- Bridge layer handles callback-to-signal translation

Reference:
- docs/agent_handoffs/P0-A_architecture_audit.md
- docs/agent_handoffs/P1-B_measurement_service.md
- docs/professional_optimization_plan.md P1-C
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QTimer

from src.instruments.argyll_adapter import ArgyllAdapter
from src.instruments.qt_patch_presenter import PyQtPatchPresenter, WebUIPatchPresenter
from src.instruments.base import MeasurementResult, InstrumentError
from src.workflows.measurement_service import (
    MeasurementService,
    MeasurementServiceError,
    MeasurementConfig,
    DarkSampleConfig,
    OLEDConfig,
    CheckpointData,
)
from src.core.state import MeasurementState
from src.core.session import MeasurementSessionState, MeasurementCheckpoint


logger = logging.getLogger(__name__)


@dataclass
class BridgeConfig:
    """
    Configuration for Backend-MeasurementService bridge.

    Attributes:
        use_measurement_service: Whether to use MeasurementService (True) or legacy code (False)
        auto_sync_state: Automatically sync Backend state with MeasurementService state
        log_transitions: Log all state transitions for debugging
    """
    use_measurement_service: bool = True
    auto_sync_state: bool = True
    log_transitions: bool = True


class BackendMeasurementBridge:
    """
    Bridge between Backend and MeasurementService.

    This class provides:
    1. Instrument adapter wrapping Backend's ArgyllController
    2. Patch presenter wrapping Backend's display mechanism
    3. MeasurementService instance with configured callbacks
    4. Methods that Backend can call to delegate measurement operations

    Usage in Backend:
        >>> bridge = BackendMeasurementBridge(self)
        >>> bridge.start_cycle(patches, name)  # Delegate to MeasurementService
        >>> bridge.stop_cycle()  # Stop via MeasurementService

    Thread Safety:
        All operations should be performed on Qt main thread.
    """

    def __init__(self, backend: 'Backend', config: Optional[BridgeConfig] = None):
        """
        Initialize bridge with Backend reference.

        Args:
            backend: Backend instance to integrate with
            config: Optional configuration
        """
        self._backend = backend
        self._config = config or BridgeConfig()

        # Measurement service (created lazily)
        self._service: Optional[MeasurementService] = None
        self._instrument_adapter: Optional[ArgyllAdapter] = None
        self._patch_presenter: Optional[PyQtPatchPresenter] = None

        # Measurement configuration (copied from Backend)
        self._measurement_config = MeasurementConfig()

        # Callback for Backend state sync
        self._on_state_change_callback: Optional[Callable] = None

    def _create_service(self) -> MeasurementService:
        """
        Create or recreate MeasurementService with current adapters.

        Returns:
            MeasurementService instance
        """
        # Create instrument adapter
        self._instrument_adapter = ArgyllAdapter(self._backend._argyll_controller)

        # Create patch presenter
        # Use PatchWindow if available and auto_clear_lut is enabled
        if self._backend._auto_clear_lut and self._backend._patch_window:
            self._patch_presenter = PyQtPatchPresenter(
                self._backend._patch_window,
                display_id=self._backend._get_patch_display_index()
            )
        else:
            # Use Web UI presenter
            self._patch_presenter = WebUIPatchPresenter(
                self._backend,
                display_id=self._backend._get_patch_display_index()
            )

        # Update config from Backend settings
        self._measurement_config = MeasurementConfig(
            measure_mode=self._backend._current_measure_mode,
            settling_time_ms=self._backend._current_delay_ms,
            dark_sample=DarkSampleConfig(
                threshold=self._backend._dark_sample_threshold,
                sample_count=self._backend._dark_sample_max_retries + 1,
                use_xyz_average=True
            ),
            oled=OLEDConfig(
                enabled=self._backend._oled_mode_enabled,
                black_frame_duration_ms=self._backend._oled_black_frame_delay_ms,
                black_frame_threshold=self._backend._oled_bfi_trigger_threshold,
                window_size_percent=self._backend._oled_window_size_percent
            ),
            auto_calibrate=True,
            auto_reconnect=self._backend._auto_reconnect_enabled,
            save_checkpoints=True
        )

        # Create service
        service = MeasurementService(
            self._instrument_adapter,
            self._patch_presenter,
            self._measurement_config
        )

        # Configure callbacks to trigger Backend signals
        service.on_patch_displayed(self._handle_patch_displayed)
        service.on_measurement_received(self._handle_measurement_received)
        service.on_progress(self._handle_progress)
        service.on_error(self._handle_error)
        service.on_state_change(self._handle_state_change)

        return service

    def _handle_patch_displayed(
        self, index: int, rgb: Tuple[int, int, int], name: str
    ) -> None:
        """Handle patch display event from MeasurementService."""
        # Update Backend's current patch info
        self._backend._current_patch_color = rgb
        self._backend._current_patch_name = name

        # Send signal to UI
        self._backend.measurementStarted.emit(name)
        self._backend.patchColorChanged.emit(json.dumps({
            "r": rgb[0], "g": rgb[1], "b": rgb[2]
        }))

        if self._config.log_transitions:
            logger.info(f"Patch displayed: {index} - {name} RGB({rgb})")

    def _handle_measurement_received(self, result: MeasurementResult) -> None:
        """Handle measurement result from MeasurementService."""
        # Update Backend's measurement data
        result_data = {
            "patchName": result.patch_name or self._backend._current_patch_name or "未知",
            "rgb": {
                "r": result.rgb_requested[0],
                "g": result.rgb_requested[1],
                "b": result.rgb_requested[2]
            },
            "x": result.xyY[0],
            "y": result.xyY[1],
            "Y": result.xyY[2],
            "cct": self._backend._analyzer.calculate_cct(result.xyY[0], result.xyY[1]),
            "deltaE": result.metadata.get("delta_e", 0.0)
        }

        # Store measurement in Backend's data structures
        self._backend._store_measurement(result_data)

        # Send result signal to UI
        self._backend._measurement_result_throttler.emit(json.dumps(result_data))

        if self._config.log_transitions:
            logger.info(f"Measurement received: {result.patch_name} Y={result.Y:.2f}")

    def _handle_progress(
        self, current: int, total: int, percent: float
    ) -> None:
        """Handle progress update from MeasurementService."""
        progress_data = {
            "current": current,
            "total": total,
            "patchName": self._backend._current_patch_name or ""
        }
        self._backend.cycleMeasurementProgress.emit(json.dumps(progress_data))

    def _handle_error(self, error: MeasurementServiceError) -> None:
        """Handle error from MeasurementService."""
        # Log error to Backend
        self._backend.logMessage.emit(f"MeasurementService error: {error}")

        # If recoverable, save checkpoint for resume
        if error.recoverable and self._service:
            checkpoint = self._service.checkpoint
            if checkpoint:
                self._backend._checkpoint = self._convert_checkpoint(checkpoint)

    def _handle_state_change(
        self, old_state: MeasurementState, new_state: MeasurementState
    ) -> None:
        """Handle state change from MeasurementService."""
        if self._config.auto_sync_state:
            # Sync Backend's session state with MeasurementService state
            # Note: Backend uses MeasurementSessionState enum (different from MeasurementState)
            # This is a simplified sync that updates key flags

            if new_state == MeasurementState.MEASURING:
                self._backend._cycle_running = True
                self._backend._session_state = MeasurementSessionState.RUNNING
            elif new_state == MeasurementState.SUSPENDED:
                self._backend._session_state = MeasurementSessionState.SUSPENDED
            elif new_state == MeasurementState.COMPLETED:
                self._backend._cycle_running = False
                self._backend._session_state = MeasurementSessionState.COMPLETED
            elif new_state == MeasurementState.FAILED:
                self._backend._cycle_running = False
                self._backend._session_state = MeasurementSessionState.FAILED

        if self._config.log_transitions:
            logger.info(f"State change: {old_state.value} -> {new_state.value}")

    def _convert_checkpoint(self, checkpoint: CheckpointData) -> MeasurementCheckpoint:
        """Convert MeasurementService checkpoint to Backend's MeasurementCheckpoint."""
        # MeasurementCheckpoint is imported from src.core.session at module level
        return MeasurementCheckpoint(
            cycle_queue=checkpoint.patch_queue,
            current_index=checkpoint.current_patch_index,
            completed_data=[],  # Would need conversion from MeasurementResult list
            measurement_name=checkpoint.session_id,
            reason=checkpoint.reason
        )

    # ========== Public API for Backend ==========

    def start_cycle(
        self,
        patches: List[Tuple[int, int, int, str]],
        name: str
    ) -> bool:
        """
        Start measurement cycle using MeasurementService.

        Args:
            patches: List of patches [(r, g, b, name), ...]
            name: Session name

        Returns:
            True if started successfully
        """
        try:
            # Create or recreate service
            self._service = self._create_service()

            # Start session
            success = self._service.start_session(
                patches=patches,
                session_id=name,
                config=self._measurement_config
            )

            if success:
                # Backend setup (LUT clearing, etc.) is handled by Backend
                # MeasurementService handles measurement orchestration
                self._backend.logMessage.emit(
                    f"使用 MeasurementService 开始测量: {name}, {len(patches)} 个色块"
                )

                # Start measuring all patches
                self._service.measure_all_patches()

            return success

        except MeasurementServiceError as e:
            self._backend.logMessage.emit(f"MeasurementService 启动失败: {e}")
            return False
        except Exception as e:
            self._backend.logMessage.emit(f"启动测量异常: {e}")
            logger.error(f"start_cycle error: {e}")
            return False

    def stop_cycle(self) -> None:
        """Stop measurement cycle."""
        if self._service:
            try:
                self._service.stop_session(save_checkpoint=True)
                self._backend.logMessage.emit("MeasurementService 已停止")
            except Exception as e:
                self._backend.logMessage.emit(f"停止测量异常: {e}")

        self._backend._cycle_running = False

    def resume_from_checkpoint(self) -> bool:
        """
        Resume measurement from checkpoint.

        Returns:
            True if resumed successfully
        """
        if not self._backend._checkpoint or not self._service:
            return False

        try:
            checkpoint = CheckpointData(
                session_id=self._backend._checkpoint.measurement_name or "",
                patch_queue=self._backend._checkpoint.cycle_queue,
                current_patch_index=self._backend._checkpoint.current_index,
                reason=self._backend._checkpoint.reason or "disconnect"
            )

            success = self._service.resume_from_checkpoint(checkpoint)

            if success:
                self._backend.logMessage.emit(
                    f"从断点恢复: 索引 {checkpoint.current_patch_index}"
                )
                self._service.measure_all_patches()

            return success

        except Exception as e:
            self._backend.logMessage.emit(f"断点恢复失败: {e}")
            return False

    def measure_single_patch(
        self,
        r: int, g: int, b: int,
        name: str
    ) -> Optional[MeasurementResult]:
        """
        Measure a single patch.

        Args:
            r, g, b: RGB values
            name: Patch name

        Returns:
            MeasurementResult if successful, None otherwise
        """
        if not self._service:
            self._service = self._create_service()

        try:
            # Start a single-patch session
            self._service.start_session(
                patches=[(r, g, b, name)],
                session_id=f"single_{name}",
                config=self._measurement_config
            )

            result = self._service.measure_next_patch()
            self._service.stop_session()

            return result

        except Exception as e:
            self._backend.logMessage.emit(f"单次测量失败: {e}")
            return None

    def update_config_from_backend(self) -> None:
        """
        Update MeasurementService configuration from Backend settings.

        Call this when Backend settings change (delay, OLED, dark sample, etc.)
        """
        self._measurement_config = MeasurementConfig(
            measure_mode=self._backend._current_measure_mode,
            settling_time_ms=self._backend._current_delay_ms,
            dark_sample=DarkSampleConfig(
                threshold=self._backend._dark_sample_threshold,
                sample_count=self._backend._dark_sample_max_retries + 1
            ),
            oled=OLEDConfig(
                enabled=self._backend._oled_mode_enabled,
                black_frame_duration_ms=self._backend._oled_black_frame_delay_ms
            )
        )

        if self._service:
            # Service would need a method to update config
            # For now, recreate service with new config
            pass

    @property
    def is_active(self) -> bool:
        """Check if MeasurementService is active."""
        if self._service is None:
            return False
        # MeasurementState is an Enum, check if state is in active states
        active_states = {
            MeasurementState.PRECHECK,
            MeasurementState.CONNECTING,
            MeasurementState.CALIBRATING,
            MeasurementState.MEASURING,
            MeasurementState.GENERATING_PROFILE,
        }
        return self._service.state in active_states

    @property
    def state(self) -> MeasurementState:
        """Get current MeasurementService state."""
        if self._service:
            return self._service.state
        return MeasurementState.IDLE

    @property
    def service(self) -> Optional[MeasurementService]:
        """Get MeasurementService instance."""
        return self._service


# ========== Integration Helper ==========

def create_bridge(backend: 'Backend', use_measurement_service: bool = True) -> BackendMeasurementBridge:
    """
    Create BackendMeasurementBridge with default configuration.

    Args:
        backend: Backend instance
        use_measurement_service: Whether to use MeasurementService

    Returns:
        BackendMeasurementBridge instance
    """
    config = BridgeConfig(use_measurement_service=use_measurement_service)
    return BackendMeasurementBridge(backend, config)
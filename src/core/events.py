"""
Domain events for the measurement workflow.

This module defines all events that can occur during a measurement session.
Events are immutable data containers that carry information about what happened.
They are used to trigger state transitions in the state machine.

Design principles:
- Events are pure data, no behavior
- Events are immutable (frozen dataclasses)
- Events carry minimal but sufficient context
- Event names are past tense (things that happened)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from enum import Enum


class EventType(Enum):
    """Enumeration of all event types for easy filtering and logging."""
    START_REQUESTED = "start_requested"
    PRECHECK_PASSED = "precheck_passed"
    PRECHECK_FAILED = "precheck_failed"
    INSTRUMENT_CONNECTED = "instrument_connected"
    PATCH_DISPLAYED = "patch_displayed"
    MEASUREMENT_RECEIVED = "measurement_received"
    INSTRUMENT_DISCONNECTED = "instrument_disconnected"
    RESUME_REQUESTED = "resume_requested"
    STOP_REQUESTED = "stop_requested"
    WORKFLOW_FAILED = "workflow_failed"
    CALIBRATION_COMPLETED = "calibration_completed"
    PROFILE_GENERATED = "profile_generated"
    ALL_PATCHES_COMPLETED = "all_patches_completed"


@dataclass(frozen=True)
class Event:
    """
    Base class for all domain events.
    
    All events are immutable and carry:
    - timestamp: when the event occurred
    - event_type: the type of event for filtering
    - Optional context data specific to each event type
    """
    timestamp: datetime = field(default_factory=datetime.now)
    
    @property
    def event_type(self) -> EventType:
        """Override in subclasses to return the specific event type."""
        raise NotImplementedError


@dataclass(frozen=True)
class StartRequested(Event):
    """
    User requested to start a measurement session.
    
    Carries:
    - measure_mode: the measurement mode (gamut, icc, lut, custom, etc.)
    - patch_count: number of patches to measure
    - session_name: optional name for this session
    """
    measure_mode: str = "gamut"
    patch_count: int = 0
    session_name: str = ""
    
    @property
    def event_type(self) -> EventType:
        return EventType.START_REQUESTED


@dataclass(frozen=True)
class PrecheckPassed(Event):
    """
    Pre-flight checks passed successfully.
    
    Precheck verifies:
    - ArgyllCMS tools available
    - Instrument detected
    - Display identified
    - System permissions granted
    - No conflicting software running
    """
    checks_passed: tuple = field(default_factory=tuple)
    
    @property
    def event_type(self) -> EventType:
        return EventType.PRECHECK_PASSED


@dataclass(frozen=True)
class PrecheckFailed(Event):
    """
    Pre-flight checks failed.
    
    Carries:
    - checks_failed: list of check names that failed
    - error_message: human-readable error description
    - is_blocker: whether this failure prevents proceeding
    """
    checks_failed: tuple = field(default_factory=tuple)
    error_message: str = ""
    is_blocker: bool = True
    
    @property
    def event_type(self) -> EventType:
        return EventType.PRECHECK_FAILED


@dataclass(frozen=True)
class InstrumentConnected(Event):
    """
    Measurement instrument has been successfully connected.
    
    Carries:
    - instrument_type: the type/model of the instrument
    - instrument_id: unique identifier if available
    """
    instrument_type: str = ""
    instrument_id: str = ""
    
    @property
    def event_type(self) -> EventType:
        return EventType.INSTRUMENT_CONNECTED


@dataclass(frozen=True)
class PatchDisplayed(Event):
    """
    A color patch has been displayed on screen.
    
    Carries:
    - patch_index: 0-based index in the patch sequence
    - patch_name: human-readable name (e.g., "Red", "Gray 50%")
    - rgb: tuple of (r, g, b) values 0-255
    - patch_id: unique identifier for this patch
    """
    patch_index: int = 0
    patch_name: str = ""
    rgb: tuple = field(default_factory=lambda: (0, 0, 0))
    patch_id: str = ""
    
    @property
    def event_type(self) -> EventType:
        return EventType.PATCH_DISPLAYED


@dataclass(frozen=True)
class MeasurementReceived(Event):
    """
    Measurement result received from the instrument.
    
    Carries:
    - patch_index: which patch was measured
    - xyz: measured XYZ values (X, Y, Z)
    - xyY: measured xyY values (x, y, Y)
    - delta_e: Delta E from expected (if applicable)
    - is_retry: whether this is a retry measurement
    - patch_id: unique identifier matching the patch
    """
    patch_index: int = 0
    xyz: tuple = field(default_factory=lambda: (0.0, 0.0, 0.0))
    xyY: tuple = field(default_factory=lambda: (0.0, 0.0, 0.0))
    delta_e: Optional[float] = None
    is_retry: bool = False
    patch_id: str = ""
    
    @property
    def event_type(self) -> EventType:
        return EventType.MEASUREMENT_RECEIVED


@dataclass(frozen=True)
class InstrumentDisconnected(Event):
    """
    Instrument was disconnected unexpectedly.
    
    Carries:
    - was_measuring: whether disconnection happened during measurement
    - checkpoint_data: data needed to resume (if available)
    """
    was_measuring: bool = False
    checkpoint_data: dict = field(default_factory=dict)
    error_message: str = ""
    
    @property
    def event_type(self) -> EventType:
        return EventType.INSTRUMENT_DISCONNECTED


@dataclass(frozen=True)
class ResumeRequested(Event):
    """
    User requested to resume from a suspended/checkpoint state.
    
    Carries:
    - checkpoint_id: identifier of the checkpoint to resume from
    """
    checkpoint_id: str = ""
    
    @property
    def event_type(self) -> EventType:
        return EventType.RESUME_REQUESTED


@dataclass(frozen=True)
class StopRequested(Event):
    """
    User requested to stop the measurement session.
    
    Carries:
    - save_checkpoint: whether to save current progress
    - reason: reason for stopping (user_cancel, error, etc.)
    """
    save_checkpoint: bool = False
    reason: str = "user_cancel"
    
    @property
    def event_type(self) -> EventType:
        return EventType.STOP_REQUESTED


@dataclass(frozen=True)
class WorkflowFailed(Event):
    """
    A workflow error occurred.
    
    Carries:
    - error_code: machine-readable error code
    - error_message: human-readable error description
    - recoverable: whether the error can be recovered from
    - context: additional context about the failure
    """
    error_code: str = "UNKNOWN"
    error_message: str = ""
    recoverable: bool = False
    context: dict = field(default_factory=dict)
    
    @property
    def event_type(self) -> EventType:
        return EventType.WORKFLOW_FAILED


@dataclass(frozen=True)
class CalibrationCompleted(Event):
    """
    Instrument calibration completed successfully.
    
    Carries:
    - calibration_type: type of calibration (white, dark, etc.)
    - calibration_data: calibration values if applicable
    """
    calibration_type: str = "standard"
    calibration_data: dict = field(default_factory=dict)
    
    @property
    def event_type(self) -> EventType:
        return EventType.CALIBRATION_COMPLETED


@dataclass(frozen=True)
class ProfileGenerated(Event):
    """
    ICC profile or LUT was generated successfully.
    
    Carries:
    - profile_type: "icc" or "lut"
    - profile_path: path to the generated file
    - profile_size: for LUT, the size (e.g., 33, 65)
    """
    profile_type: str = "icc"
    profile_path: str = ""
    profile_size: int = 0
    
    @property
    def event_type(self) -> EventType:
        return EventType.PROFILE_GENERATED


@dataclass(frozen=True)
class AllPatchesCompleted(Event):
    """
    All patches in the measurement sequence have been measured.
    
    Carries:
    - total_patches: total number of patches measured
    - successful_patches: number of successful measurements
    - failed_patches: number of failed measurements
    """
    total_patches: int = 0
    successful_patches: int = 0
    failed_patches: int = 0
    
    @property
    def event_type(self) -> EventType:
        return EventType.ALL_PATCHES_COMPLETED
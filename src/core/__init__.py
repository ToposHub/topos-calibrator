"""
Core module for Topos Calibrator.

This module contains pure business logic components that are independent
of UI frameworks (PyQt). Components here can be tested without GUI.

Key components:
- events: Domain event definitions for measurement workflow
- state: State machine for measurement session management
- session: Session state and checkpoint definitions
"""

from .events import (
    Event,
    StartRequested,
    PatchDisplayed,
    MeasurementReceived,
    InstrumentDisconnected,
    ResumeRequested,
    StopRequested,
    WorkflowFailed,
    CalibrationCompleted,
    ProfileGenerated,
    PrecheckPassed,
    PrecheckFailed,
    InstrumentConnected,
    AllPatchesCompleted,
)

from .state import (
    MeasurementState,
    MeasurementStateMachine,
    InvalidTransitionError,
    TransitionResult,
)

from .session import (
    MeasurementSessionState,
    MeasurementCheckpoint,
)

__all__ = [
    # Events
    "Event",
    "StartRequested",
    "PatchDisplayed",
    "MeasurementReceived",
    "InstrumentDisconnected",
    "ResumeRequested",
    "StopRequested",
    "WorkflowFailed",
    "CalibrationCompleted",
    "ProfileGenerated",
    "PrecheckPassed",
    "PrecheckFailed",
    "InstrumentConnected",
    "AllPatchesCompleted",
    # State
    "MeasurementState",
    "MeasurementStateMachine",
    "InvalidTransitionError",
    "TransitionResult",
    # Session
    "MeasurementSessionState",
    "MeasurementCheckpoint",
]
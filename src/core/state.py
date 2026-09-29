"""
State machine for measurement session management.

This module defines the measurement workflow state machine, which manages
the lifecycle of a measurement session. The state machine is pure Python
with no UI dependencies, allowing for easy unit testing.

State Transition Table:
=======================

| Current State        | Event                    | Next State          |
|----------------------|--------------------------|---------------------|
| IDLE                 | StartRequested           | PRECHECK            |
| IDLE                 | ResumeRequested          | CONNECTING          |
| PRECHECK             | PrecheckPassed           | CONNECTING          |
| PRECHECK             | PrecheckFailed           | FAILED              |
| PRECHECK             | StopRequested            | IDLE                |
| CONNECTING           | InstrumentConnected      | CALIBRATING/MEASURING |
| CONNECTING           | WorkflowFailed           | FAILED              |
| CONNECTING           | StopRequested            | IDLE                |
| CONNECTING           | ResumeRequested          | CONNECTING          |
| CALIBRATING          | CalibrationCompleted     | MEASURING           |
| CALIBRATING          | WorkflowFailed           | FAILED              |
| CALIBRATING          | StopRequested            | IDLE                |
| MEASURING            | PatchDisplayed           | MEASURING           |
| MEASURING            | MeasurementReceived      | MEASURING           |
| MEASURING            | AllPatchesCompleted      | GENERATING_PROFILE  |
| MEASURING            | InstrumentDisconnected   | SUSPENDED           |
| MEASURING            | WorkflowFailed           | FAILED              |
| MEASURING            | StopRequested            | IDLE                |
| SUSPENDED            | ResumeRequested          | CONNECTING          |
| SUSPENDED            | StopRequested            | IDLE                |
| GENERATING_PROFILE   | ProfileGenerated         | COMPLETED           |
| GENERATING_PROFILE   | WorkflowFailed           | FAILED              |
| GENERATING_PROFILE   | StopRequested            | IDLE                |
| COMPLETED            | StartRequested           | PRECHECK            |
| FAILED               | StartRequested           | PRECHECK            |
| FAILED               | StopRequested            | IDLE                |

Design principles:
- Pure Python, no PyQt dependencies
- Immutable events trigger transitions
- All transitions are logged for debugging
- Invalid transitions raise exceptions
- Supports multiple transitions per event type via guard conditions
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Set, Tuple, Any
import logging

from .events import (
    Event,
    EventType,
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


logger = logging.getLogger(__name__)


class MeasurementState(Enum):
    """
    Enumeration of all possible states in a measurement session.
    
    State descriptions:
    - IDLE: No active session, ready to start
    - PRECHECK: Running pre-flight checks (Argyll, instrument, display)
    - CONNECTING: Establishing connection with the measurement instrument
    - CALIBRATING: Performing instrument calibration (white reference, etc.)
    - MEASURING: Actively measuring color patches
    - SUSPENDED: Session paused (instrument disconnected or user breakpoint)
    - GENERATING_PROFILE: Creating ICC profile or 3D LUT
    - COMPLETED: Session finished successfully
    - FAILED: Session terminated due to error
    """
    IDLE = "idle"
    PRECHECK = "precheck"
    CONNECTING = "connecting"
    CALIBRATING = "calibrating"
    MEASURING = "measuring"
    SUSPENDED = "suspended"
    GENERATING_PROFILE = "generating_profile"
    COMPLETED = "completed"
    FAILED = "failed"


class InvalidTransitionError(Exception):
    """
    Raised when an invalid state transition is attempted.
    
    Attributes:
        current_state: The state the machine was in
        event_type: The event that was attempted
        valid_events: List of events that would be valid from current state
    """
    def __init__(
        self,
        current_state: MeasurementState,
        event_type: EventType,
        valid_events: List[EventType],
        message: Optional[str] = None
    ):
        self.current_state = current_state
        self.event_type = event_type
        self.valid_events = valid_events
        if message is None:
            message = (
                f"Invalid transition: cannot handle {event_type.value} "
                f"in state {current_state.value}. "
                f"Valid events: {[e.value for e in valid_events]}"
            )
        super().__init__(message)


@dataclass
class TransitionResult:
    """
    Result of a state transition attempt.
    
    Attributes:
        success: Whether the transition was successful
        previous_state: The state before the transition (or current if failed)
        new_state: The state after the transition (or same if failed)
        event: The event that triggered the transition
        error: Error message if transition failed
        timestamp: When the transition occurred
        context: Additional context data from the transition
    """
    success: bool
    previous_state: MeasurementState
    new_state: MeasurementState
    event: Event
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Transition:
    """
    Represents a valid state transition rule.
    
    Attributes:
        from_state: The state to transition from
        to_state: The state to transition to
        event_type: The event type that triggers this transition
        guard: Optional function to check if transition is allowed
        action: Optional function to execute during transition
    """
    from_state: MeasurementState
    to_state: MeasurementState
    event_type: EventType
    guard: Optional[Callable[[Event, 'MeasurementStateMachine'], bool]] = None
    action: Optional[Callable[[Event, 'MeasurementStateMachine'], None]] = None


class MeasurementStateMachine:
    """
    State machine for managing measurement session lifecycle.
    
    This state machine handles all transitions in a measurement workflow,
    from starting a session through completion or failure. It provides:
    
    - Clear state transition rules
    - Event-driven transitions
    - Transition logging for debugging
    - Checkpoint/resume support via SUSPENDED state
    - Guard functions for conditional transitions
    
    Thread Safety:
        This class is NOT thread-safe. In Qt applications, ensure all
        interactions happen on the main thread or use proper synchronization.
    
    Example:
        >>> sm = MeasurementStateMachine()
        >>> sm.state
        <MeasurementState.IDLE: 'idle'>
        >>> result = sm.handle_event(StartRequested(measure_mode="gamut"))
        >>> sm.state
        <MeasurementState.PRECHECK: 'precheck'>
    """
    
    # Define all valid transitions - use List to support multiple transitions per event type
    _TRANSITIONS: Dict[MeasurementState, List[Transition]] = {}
    
    def _register_transition(
        self,
        from_state: MeasurementState,
        event_type: EventType,
        to_state: MeasurementState,
        guard: Optional[Callable[[Event, 'MeasurementStateMachine'], bool]] = None,
        action: Optional[Callable[[Event, 'MeasurementStateMachine'], None]] = None
    ) -> None:
        """Register a valid state transition."""
        if from_state not in self._TRANSITIONS:
            self._TRANSITIONS[from_state] = []
        
        self._TRANSITIONS[from_state].append(Transition(
            from_state=from_state,
            to_state=to_state,
            event_type=event_type,
            guard=guard,
            action=action
        ))
    
    def __init__(self):
        """Initialize the state machine in IDLE state."""
        self._state = MeasurementState.IDLE
        self._transition_history: List[TransitionResult] = []
        self._context: Dict[str, Any] = {}
        self._on_state_change_callbacks: List[Callable[[MeasurementState, MeasurementState, Event], None]] = []
        
        # Initialize transition table
        self._init_transitions()
    
    def _init_transitions(self) -> None:
        """Initialize the state transition table."""
        # Clear any existing transitions
        self._TRANSITIONS.clear()

        # From IDLE
        self._register_transition(
            MeasurementState.IDLE, EventType.START_REQUESTED, MeasurementState.PRECHECK
        )
        self._register_transition(
            MeasurementState.IDLE, EventType.RESUME_REQUESTED, MeasurementState.CONNECTING
        )

        # From PRECHECK
        self._register_transition(
            MeasurementState.PRECHECK, EventType.PRECHECK_PASSED, MeasurementState.CONNECTING
        )
        self._register_transition(
            MeasurementState.PRECHECK, EventType.PRECHECK_FAILED, MeasurementState.FAILED
        )
        self._register_transition(
            MeasurementState.PRECHECK, EventType.STOP_REQUESTED, MeasurementState.IDLE
        )

        # From CONNECTING - two possible paths for INSTRUMENT_CONNECTED
        # First, check if calibration needed -> CALIBRATING
        self._register_transition(
            MeasurementState.CONNECTING, EventType.INSTRUMENT_CONNECTED, MeasurementState.CALIBRATING,
            guard=lambda e, sm: sm._needs_calibration(e)
        )
        # Second, if no calibration needed -> MEASURING
        self._register_transition(
            MeasurementState.CONNECTING, EventType.INSTRUMENT_CONNECTED, MeasurementState.MEASURING,
            guard=lambda e, sm: not sm._needs_calibration(e)
        )
        self._register_transition(
            MeasurementState.CONNECTING, EventType.WORKFLOW_FAILED, MeasurementState.FAILED
        )
        self._register_transition(
            MeasurementState.CONNECTING, EventType.STOP_REQUESTED, MeasurementState.IDLE
        )
        self._register_transition(
            MeasurementState.CONNECTING, EventType.RESUME_REQUESTED, MeasurementState.CONNECTING
        )

        # From CALIBRATING
        self._register_transition(
            MeasurementState.CALIBRATING, EventType.CALIBRATION_COMPLETED, MeasurementState.MEASURING
        )
        self._register_transition(
            MeasurementState.CALIBRATING, EventType.WORKFLOW_FAILED, MeasurementState.FAILED
        )
        self._register_transition(
            MeasurementState.CALIBRATING, EventType.STOP_REQUESTED, MeasurementState.IDLE
        )

        # From MEASURING
        self._register_transition(
            MeasurementState.MEASURING, EventType.PATCH_DISPLAYED, MeasurementState.MEASURING
        )
        self._register_transition(
            MeasurementState.MEASURING, EventType.MEASUREMENT_RECEIVED, MeasurementState.MEASURING
        )
        self._register_transition(
            MeasurementState.MEASURING, EventType.ALL_PATCHES_COMPLETED, MeasurementState.GENERATING_PROFILE
        )
        self._register_transition(
            MeasurementState.MEASURING, EventType.INSTRUMENT_DISCONNECTED, MeasurementState.SUSPENDED
        )
        self._register_transition(
            MeasurementState.MEASURING, EventType.WORKFLOW_FAILED, MeasurementState.FAILED
        )
        self._register_transition(
            MeasurementState.MEASURING, EventType.STOP_REQUESTED, MeasurementState.IDLE
        )

        # From SUSPENDED
        self._register_transition(
            MeasurementState.SUSPENDED, EventType.RESUME_REQUESTED, MeasurementState.CONNECTING
        )
        self._register_transition(
            MeasurementState.SUSPENDED, EventType.STOP_REQUESTED, MeasurementState.IDLE
        )

        # From GENERATING_PROFILE
        self._register_transition(
            MeasurementState.GENERATING_PROFILE, EventType.PROFILE_GENERATED, MeasurementState.COMPLETED
        )
        self._register_transition(
            MeasurementState.GENERATING_PROFILE, EventType.WORKFLOW_FAILED, MeasurementState.FAILED
        )
        self._register_transition(
            MeasurementState.GENERATING_PROFILE, EventType.STOP_REQUESTED, MeasurementState.IDLE
        )

        # From COMPLETED
        self._register_transition(
            MeasurementState.COMPLETED, EventType.START_REQUESTED, MeasurementState.PRECHECK
        )

        # From FAILED
        self._register_transition(
            MeasurementState.FAILED, EventType.START_REQUESTED, MeasurementState.PRECHECK
        )
        self._register_transition(
            MeasurementState.FAILED, EventType.STOP_REQUESTED, MeasurementState.IDLE
        )

    @property
    def state(self) -> MeasurementState:
        """Get the current state of the machine."""
        return self._state

    @property
    def context(self) -> Dict[str, Any]:
        """
        Get the current context dictionary.
        
        Context can store session-related data like:
        - measure_mode
        - patch_count
        - checkpoint_data
        - current_patch_index
        """
        return self._context

    @property
    def transition_history(self) -> List[TransitionResult]:
        """Get the history of all transitions."""
        return self._transition_history.copy()

    def _needs_calibration(self, event: Event) -> bool:
        """
        Check if instrument calibration is needed.
        
        This is a guard function for the CONNECTING -> CALIBRATING transition.
        It checks context for calibration requirement.
        """
        return self._context.get('needs_calibration', True)

    def can_handle(self, event: Event) -> bool:
        """
        Check if an event can be handled in the current state.

        Args:
            event: The event to check

        Returns:
            True if the event would cause a valid transition
        """
        if self._state not in self._TRANSITIONS:
            return False

        # Find all transitions matching this event type
        matching_transitions = [
            t for t in self._TRANSITIONS[self._state]
            if t.event_type == event.event_type
        ]

        if not matching_transitions:
            return False

        # Check if any transition's guard passes
        for transition in matching_transitions:
            if transition.guard:
                try:
                    if transition.guard(event, self):
                        return True
                except Exception:
                    continue
            else:
                return True

        return False

    def get_valid_events(self) -> List[EventType]:
        """
        Get list of valid events that can be handled in current state.

        Returns:
            List of event types that would cause valid transitions
        """
        if self._state not in self._TRANSITIONS:
            return []

        # Collect all event types from transitions
        event_types = set()
        for transition in self._TRANSITIONS[self._state]:
            event_types.add(transition.event_type)

        return list(event_types)

    def handle_event(self, event: Event) -> TransitionResult:
        """
        Handle an event and potentially transition to a new state.

        Args:
            event: The event to process

        Returns:
            TransitionResult containing the outcome of the transition

        Raises:
            InvalidTransitionError: If the event cannot be handled in current state
        """
        previous_state = self._state

        # Check if state has any transitions
        if self._state not in self._TRANSITIONS:
            valid_events = []
        else:
            # Get all valid event types for this state
            valid_events = self.get_valid_events()

        # Find all transitions matching this event type
        matching_transitions = [
            t for t in self._TRANSITIONS.get(self._state, [])
            if t.event_type == event.event_type
        ]

        if not matching_transitions:
            error = InvalidTransitionError(
                current_state=self._state,
                event_type=event.event_type,
                valid_events=valid_events
            )
            result = TransitionResult(
                success=False,
                previous_state=previous_state,
                new_state=previous_state,
                event=event,
                error=str(error)
            )
            self._transition_history.append(result)
            raise error

        # Try each transition until one passes its guard
        selected_transition = None
        for transition in matching_transitions:
            if transition.guard:
                try:
                    if transition.guard(event, self):
                        selected_transition = transition
                        break
                except Exception as e:
                    # Guard raised exception, try next transition
                    logger.debug(f"Guard raised exception: {e}")
                    continue
            else:
                # No guard means always valid
                selected_transition = transition
                break

        if selected_transition is None:
            # All guards rejected
            error = InvalidTransitionError(
                current_state=self._state,
                event_type=event.event_type,
                valid_events=valid_events,
                message=f"All guard conditions rejected transition from {self._state.value}"
            )
            result = TransitionResult(
                success=False,
                previous_state=previous_state,
                new_state=previous_state,
                event=event,
                error=str(error)
            )
            self._transition_history.append(result)
            raise error

        # Execute transition
        old_state = self._state
        self._state = selected_transition.to_state

        # Execute action if present
        if selected_transition.action:
            try:
                selected_transition.action(event, self)
            except Exception as e:
                logger.error(f"Transition action raised exception: {e}")
                # Continue with transition even if action fails

        # Log the transition
        logger.info(
            f"State transition: {old_state.value} -> {self._state.value} "
            f"(event: {event.event_type.value})"
        )

        # Create successful result
        result = TransitionResult(
            success=True,
            previous_state=old_state,
            new_state=self._state,
            event=event,
            context=self._context.copy()
        )
        self._transition_history.append(result)

        # Notify callbacks
        for callback in self._on_state_change_callbacks:
            try:
                callback(old_state, self._state, event)
            except Exception as e:
                logger.error(f"State change callback raised exception: {e}")

        return result

    def reset(self) -> None:
        """
        Reset the state machine to IDLE state.
        
        Clears context and transition history.
        """
        old_state = self._state
        self._state = MeasurementState.IDLE
        self._context.clear()
        self._transition_history.clear()
        logger.info(f"State machine reset from {old_state.value} to IDLE")

    def on_state_change(
        self, callback: Callable[[MeasurementState, MeasurementState, Event], None]
    ) -> None:
        """
        Register a callback to be called on state changes.
        
        Args:
            callback: Function taking (old_state, new_state, event)
        """
        self._on_state_change_callbacks.append(callback)

    def remove_callback(
        self, callback: Callable[[MeasurementState, MeasurementState, Event], None]
    ) -> None:
        """Remove a previously registered state change callback."""
        if callback in self._on_state_change_callbacks:
            self._on_state_change_callbacks.remove(callback)

    def is_active(self) -> bool:
        """Check if the machine is in an active measurement state."""
        return self._state in {
            MeasurementState.PRECHECK,
            MeasurementState.CONNECTING,
            MeasurementState.CALIBRATING,
            MeasurementState.MEASURING,
            MeasurementState.GENERATING_PROFILE,
        }

    def can_resume(self) -> bool:
        """Check if the session can be resumed from current state."""
        return self._state == MeasurementState.SUSPENDED

    def is_terminal(self) -> bool:
        """Check if the session is in a terminal state (completed or failed)."""
        return self._state in {
            MeasurementState.COMPLETED,
            MeasurementState.FAILED,
        }

    def __repr__(self) -> str:
        return f"MeasurementStateMachine(state={self._state.value})"


# Convenience functions for creating common transitions
def start_session(sm: MeasurementStateMachine, measure_mode: str = "gamut") -> TransitionResult:
    """
    Convenience function to start a new measurement session.
    
    Args:
        sm: The state machine instance
        measure_mode: The measurement mode to use
        
    Returns:
        The result of the transition
    """
    sm.context['measure_mode'] = measure_mode
    return sm.handle_event(StartRequested(measure_mode=measure_mode))


def complete_precheck(sm: MeasurementStateMachine, checks_passed: tuple = ()) -> TransitionResult:
    """
    Convenience function to signal precheck completion.
    
    Args:
        sm: The state machine instance
        checks_passed: Tuple of check names that passed
        
    Returns:
        The result of the transition
    """
    return sm.handle_event(PrecheckPassed(checks_passed=checks_passed))


def fail_precheck(sm: MeasurementStateMachine, checks_failed: tuple, message: str) -> TransitionResult:
    """
    Convenience function to signal precheck failure.
    
    Args:
        sm: The state machine instance
        checks_failed: Tuple of check names that failed
        message: Error message
        
    Returns:
        The result of the transition
    """
    return sm.handle_event(PrecheckFailed(checks_failed=checks_failed, error_message=message))


def connect_instrument(sm: MeasurementStateMachine, instrument_type: str = "", instrument_id: str = "") -> TransitionResult:
    """
    Convenience function to signal instrument connection.
    
    Args:
        sm: The state machine instance
        instrument_type: Type of instrument
        instrument_id: Unique identifier
        
    Returns:
        The result of the transition
    """
    sm.context['instrument_type'] = instrument_type
    sm.context['instrument_id'] = instrument_id
    return sm.handle_event(InstrumentConnected(
        instrument_type=instrument_type,
        instrument_id=instrument_id
    ))


def disconnect_instrument(sm: MeasurementStateMachine, was_measuring: bool = False, checkpoint_data: dict = None) -> TransitionResult:
    """
    Convenience function to signal instrument disconnection.
    
    Args:
        sm: The state machine instance
        was_measuring: Whether disconnection happened during measurement
        checkpoint_data: Data for resuming later
        
    Returns:
        The result of the transition
    """
    if checkpoint_data:
        sm.context['checkpoint_data'] = checkpoint_data
    return sm.handle_event(InstrumentDisconnected(
        was_measuring=was_measuring,
        checkpoint_data=checkpoint_data or {}
    ))


def resume_session(sm: MeasurementStateMachine, checkpoint_id: str = "") -> TransitionResult:
    """
    Convenience function to resume a suspended session.
    
    Args:
        sm: The state machine instance
        checkpoint_id: ID of checkpoint to resume from
        
    Returns:
        The result of the transition
    """
    return sm.handle_event(ResumeRequested(checkpoint_id=checkpoint_id))


def stop_session(sm: MeasurementStateMachine, save_checkpoint: bool = False, reason: str = "user_cancel") -> TransitionResult:
    """
    Convenience function to stop the current session.
    
    Args:
        sm: The state machine instance
        save_checkpoint: Whether to save progress
        reason: Reason for stopping
        
    Returns:
        The result of the transition
    """
    return sm.handle_event(StopRequested(
        save_checkpoint=save_checkpoint,
        reason=reason
    ))


def fail_workflow(sm: MeasurementStateMachine, error_code: str, message: str, recoverable: bool = False) -> TransitionResult:
    """
    Convenience function to signal workflow failure.
    
    Args:
        sm: The state machine instance
        error_code: Machine-readable error code
        message: Human-readable error message
        recoverable: Whether the error might be recoverable
        
    Returns:
        The result of the transition
    """
    sm.context['last_error_code'] = error_code
    sm.context['last_error_message'] = message
    return sm.handle_event(WorkflowFailed(
        error_code=error_code,
        error_message=message,
        recoverable=recoverable
    ))
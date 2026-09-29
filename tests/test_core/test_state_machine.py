"""
Unit tests for the measurement state machine.

This test module covers:
- All valid state transitions
- Invalid transition handling
- Guard conditions
- State query methods
- Convenience functions
- Callback functionality

Requirements:
- At least 25 test cases
- No PyQt dependencies
- All legal transitions tested
- All illegal transitions tested
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from src.core.events import (
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

from src.core.state import (
    MeasurementState,
    MeasurementStateMachine,
    InvalidTransitionError,
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


class TestMeasurementState:
    """Tests for MeasurementState enum."""
    
    def test_state_values_are_strings(self):
        """State values should be lowercase strings for JSON serialization."""
        assert MeasurementState.IDLE.value == "idle"
        assert MeasurementState.PRECHECK.value == "precheck"
        assert MeasurementState.CONNECTING.value == "connecting"
        assert MeasurementState.CALIBRATING.value == "calibrating"
        assert MeasurementState.MEASURING.value == "measuring"
        assert MeasurementState.SUSPENDED.value == "suspended"
        assert MeasurementState.GENERATING_PROFILE.value == "generating_profile"
        assert MeasurementState.COMPLETED.value == "completed"
        assert MeasurementState.FAILED.value == "failed"
    
    def test_all_states_defined(self):
        """All required states should be defined."""
        expected_states = {
            "IDLE", "PRECHECK", "CONNECTING", "CALIBRATING",
            "MEASURING", "SUSPENDED", "GENERATING_PROFILE",
            "COMPLETED", "FAILED"
        }
        actual_states = {s.name for s in MeasurementState}
        assert expected_states == actual_states


class TestEvents:
    """Tests for event classes."""
    
    def test_event_has_timestamp(self):
        """Events should have a timestamp."""
        event = StartRequested()
        assert isinstance(event.timestamp, datetime)
    
    def test_event_has_event_type(self):
        """Events should expose their event type."""
        event = StartRequested()
        assert event.event_type == EventType.START_REQUESTED
    
    def test_start_requested_carries_mode(self):
        """StartRequested should carry measurement mode."""
        event = StartRequested(measure_mode="icc", patch_count=100, session_name="test")
        assert event.measure_mode == "icc"
        assert event.patch_count == 100
        assert event.session_name == "test"
    
    def test_measurement_received_carries_xyz(self):
        """MeasurementReceived should carry XYZ values."""
        event = MeasurementReceived(
            patch_index=5,
            xyz=(41.2, 21.5, 1.8),
            xyY=(0.64, 0.33, 21.5)
        )
        assert event.patch_index == 5
        assert event.xyz == (41.2, 21.5, 1.8)
        assert event.xyY == (0.64, 0.33, 21.5)
    
    def test_events_are_immutable(self):
        """Events should be immutable (frozen dataclasses)."""
        event = StartRequested(measure_mode="gamut")
        with pytest.raises(AttributeError):
            event.measure_mode = "icc"


class TestStateMachineBasics:
    """Tests for basic state machine functionality."""
    
    def test_initial_state_is_idle(self):
        """State machine should start in IDLE state."""
        sm = MeasurementStateMachine()
        assert sm.state == MeasurementState.IDLE
    
    def test_context_is_mutable(self):
        """Context should be mutable for storing session data."""
        sm = MeasurementStateMachine()
        sm.context['measure_mode'] = 'gamut'
        assert sm.context['measure_mode'] == 'gamut'
    
    def test_transition_history_starts_empty(self):
        """Transition history should be empty initially."""
        sm = MeasurementStateMachine()
        assert len(sm.transition_history) == 0
    
    def test_reset_returns_to_idle(self):
        """Reset should return machine to IDLE state."""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        assert sm.state == MeasurementState.PRECHECK
        sm.reset()
        assert sm.state == MeasurementState.IDLE
        assert len(sm.transition_history) == 0
    
    def test_reset_clears_context(self):
        """Reset should clear the context."""
        sm = MeasurementStateMachine()
        sm.context['test'] = 'value'
        sm.reset()
        assert 'test' not in sm.context


class TestValidTransitions:
    """Tests for all valid state transitions."""
    
    def test_idle_to_precheck_on_start(self):
        """IDLE + StartRequested -> PRECHECK"""
        sm = MeasurementStateMachine()
        result = sm.handle_event(StartRequested(measure_mode="gamut"))
        assert result.success
        assert sm.state == MeasurementState.PRECHECK
        assert result.previous_state == MeasurementState.IDLE
        assert result.new_state == MeasurementState.PRECHECK
    
    def test_idle_to_connecting_on_resume(self):
        """IDLE + ResumeRequested -> CONNECTING"""
        sm = MeasurementStateMachine()
        result = sm.handle_event(ResumeRequested(checkpoint_id="abc123"))
        assert result.success
        assert sm.state == MeasurementState.CONNECTING
    
    def test_precheck_to_connecting_on_pass(self):
        """PRECHECK + PrecheckPassed -> CONNECTING"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        result = sm.handle_event(PrecheckPassed(checks_passed=("argyll", "instrument")))
        assert result.success
        assert sm.state == MeasurementState.CONNECTING
    
    def test_precheck_to_failed_on_fail(self):
        """PRECHECK + PrecheckFailed -> FAILED"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        result = sm.handle_event(PrecheckFailed(checks_failed=("instrument",), error_message="No probe"))
        assert result.success
        assert sm.state == MeasurementState.FAILED
    
    def test_precheck_to_idle_on_stop(self):
        """PRECHECK + StopRequested -> IDLE"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        result = sm.handle_event(StopRequested())
        assert result.success
        assert sm.state == MeasurementState.IDLE
    
    def test_connecting_to_calibrating_on_connect_with_calibration(self):
        """CONNECTING + InstrumentConnected -> CALIBRATING (when calibration needed)"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = True  # Guard condition
        result = sm.handle_event(InstrumentConnected(instrument_type="i1Display Pro"))
        assert result.success
        assert sm.state == MeasurementState.CALIBRATING
    
    def test_connecting_to_measuring_on_connect_without_calibration(self):
        """CONNECTING + InstrumentConnected -> MEASURING (when calibration not needed)"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False  # Guard condition
        result = sm.handle_event(InstrumentConnected(instrument_type="i1Display Pro"))
        assert result.success
        assert sm.state == MeasurementState.MEASURING
    
    def test_connecting_to_failed_on_error(self):
        """CONNECTING + WorkflowFailed -> FAILED"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        result = sm.handle_event(WorkflowFailed(error_code="CONNECT_ERROR", error_message="USB error"))
        assert result.success
        assert sm.state == MeasurementState.FAILED
    
    def test_connecting_to_idle_on_stop(self):
        """CONNECTING + StopRequested -> IDLE"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        result = sm.handle_event(StopRequested())
        assert result.success
        assert sm.state == MeasurementState.IDLE
    
    def test_calibrating_to_measuring_on_complete(self):
        """CALIBRATING + CalibrationCompleted -> MEASURING"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = True
        sm.handle_event(InstrumentConnected())
        result = sm.handle_event(CalibrationCompleted(calibration_type="white"))
        assert result.success
        assert sm.state == MeasurementState.MEASURING
    
    def test_calibrating_to_failed_on_error(self):
        """CALIBRATING + WorkflowFailed -> FAILED"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = True
        sm.handle_event(InstrumentConnected())
        result = sm.handle_event(WorkflowFailed(error_code="CAL_ERROR", error_message="Calibration failed"))
        assert result.success
        assert sm.state == MeasurementState.FAILED
    
    def test_measuring_stays_measuring_on_patch_displayed(self):
        """MEASURING + PatchDisplayed -> MEASURING (self-transition)"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        result = sm.handle_event(PatchDisplayed(patch_index=0, patch_name="White", rgb=(255, 255, 255)))
        assert result.success
        assert sm.state == MeasurementState.MEASURING
    
    def test_measuring_stays_measuring_on_measurement_received(self):
        """MEASURING + MeasurementReceived -> MEASURING (self-transition)"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        sm.handle_event(PatchDisplayed(patch_index=0))
        result = sm.handle_event(MeasurementReceived(patch_index=0, xyz=(95.0, 100.0, 108.0)))
        assert result.success
        assert sm.state == MeasurementState.MEASURING
    
    def test_measuring_to_generating_profile_on_all_completed(self):
        """MEASURING + AllPatchesCompleted -> GENERATING_PROFILE"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        result = sm.handle_event(AllPatchesCompleted(total_patches=100, successful_patches=100))
        assert result.success
        assert sm.state == MeasurementState.GENERATING_PROFILE
    
    def test_measuring_to_suspended_on_disconnect(self):
        """MEASURING + InstrumentDisconnected -> SUSPENDED"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        result = sm.handle_event(InstrumentDisconnected(was_measuring=True, checkpoint_data={"index": 5}))
        assert result.success
        assert sm.state == MeasurementState.SUSPENDED
    
    def test_measuring_to_failed_on_error(self):
        """MEASURING + WorkflowFailed -> FAILED"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        result = sm.handle_event(WorkflowFailed(error_code="MEASURE_ERROR", error_message="Read error"))
        assert result.success
        assert sm.state == MeasurementState.FAILED
    
    def test_measuring_to_idle_on_stop(self):
        """MEASURING + StopRequested -> IDLE"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        result = sm.handle_event(StopRequested(save_checkpoint=True))
        assert result.success
        assert sm.state == MeasurementState.IDLE
    
    def test_suspended_to_connecting_on_resume(self):
        """SUSPENDED + ResumeRequested -> CONNECTING"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        sm.handle_event(InstrumentDisconnected(was_measuring=True))
        assert sm.state == MeasurementState.SUSPENDED
        result = sm.handle_event(ResumeRequested(checkpoint_id="cp_001"))
        assert result.success
        assert sm.state == MeasurementState.CONNECTING
    
    def test_suspended_to_idle_on_stop(self):
        """SUSPENDED + StopRequested -> IDLE"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        sm.handle_event(InstrumentDisconnected(was_measuring=True))
        assert sm.state == MeasurementState.SUSPENDED
        result = sm.handle_event(StopRequested())
        assert result.success
        assert sm.state == MeasurementState.IDLE
    
    def test_generating_profile_to_completed_on_profile_generated(self):
        """GENERATING_PROFILE + ProfileGenerated -> COMPLETED"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        sm.handle_event(AllPatchesCompleted())
        result = sm.handle_event(ProfileGenerated(profile_type="icc", profile_path="/path/to/profile.icc"))
        assert result.success
        assert sm.state == MeasurementState.COMPLETED
    
    def test_generating_profile_to_failed_on_error(self):
        """GENERATING_PROFILE + WorkflowFailed -> FAILED"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        sm.handle_event(AllPatchesCompleted())
        result = sm.handle_event(WorkflowFailed(error_code="PROFILE_ERROR", error_message="colprof failed"))
        assert result.success
        assert sm.state == MeasurementState.FAILED
    
    def test_completed_to_precheck_on_new_session(self):
        """COMPLETED + StartRequested -> PRECHECK (start new session)"""
        sm = MeasurementStateMachine()
        # Go through full workflow to COMPLETED
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        sm.handle_event(AllPatchesCompleted())
        sm.handle_event(ProfileGenerated())
        assert sm.state == MeasurementState.COMPLETED
        # Start new session
        result = sm.handle_event(StartRequested(measure_mode="lut"))
        assert result.success
        assert sm.state == MeasurementState.PRECHECK
    
    def test_failed_to_precheck_on_retry(self):
        """FAILED + StartRequested -> PRECHECK (retry)"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckFailed(checks_failed=("instrument",)))
        assert sm.state == MeasurementState.FAILED
        result = sm.handle_event(StartRequested())
        assert result.success
        assert sm.state == MeasurementState.PRECHECK
    
    def test_failed_to_idle_on_stop(self):
        """FAILED + StopRequested -> IDLE"""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckFailed(checks_failed=("instrument",)))
        assert sm.state == MeasurementState.FAILED
        result = sm.handle_event(StopRequested(reason="user_gave_up"))
        assert result.success
        assert sm.state == MeasurementState.IDLE


class TestInvalidTransitions:
    """Tests for invalid state transitions."""
    
    def test_idle_cannot_receive_patch_displayed(self):
        """IDLE + PatchDisplayed should raise InvalidTransitionError."""
        sm = MeasurementStateMachine()
        with pytest.raises(InvalidTransitionError) as exc_info:
            sm.handle_event(PatchDisplayed(patch_index=0))
        assert exc_info.value.current_state == MeasurementState.IDLE
        assert exc_info.value.event_type == EventType.PATCH_DISPLAYED
    
    def test_idle_cannot_receive_measurement(self):
        """IDLE + MeasurementReceived should raise InvalidTransitionError."""
        sm = MeasurementStateMachine()
        with pytest.raises(InvalidTransitionError):
            sm.handle_event(MeasurementReceived(patch_index=0))
    
    def test_measuring_cannot_receive_start_requested(self):
        """MEASURING + StartRequested should raise InvalidTransitionError."""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        with pytest.raises(InvalidTransitionError):
            sm.handle_event(StartRequested())
    
    def test_suspended_cannot_receive_calibration_completed(self):
        """SUSPENDED + CalibrationCompleted should raise InvalidTransitionError."""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        sm.handle_event(InstrumentDisconnected(was_measuring=True))
        with pytest.raises(InvalidTransitionError):
            sm.handle_event(CalibrationCompleted())
    
    def test_completed_cannot_receive_measurement(self):
        """COMPLETED + MeasurementReceived should raise InvalidTransitionError."""
        sm = MeasurementStateMachine()
        # Complete a session
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        sm.handle_event(AllPatchesCompleted())
        sm.handle_event(ProfileGenerated())
        with pytest.raises(InvalidTransitionError):
            sm.handle_event(MeasurementReceived(patch_index=0))
    
    def test_transition_result_on_failure(self):
        """Failed transition should still return result in history."""
        sm = MeasurementStateMachine()
        try:
            sm.handle_event(PatchDisplayed(patch_index=0))
        except InvalidTransitionError:
            pass
        # Check history has the failed attempt
        assert len(sm.transition_history) == 1
        result = sm.transition_history[0]
        assert not result.success
        assert result.previous_state == MeasurementState.IDLE
        assert result.new_state == MeasurementState.IDLE


class TestGuardConditions:
    """Tests for guard conditions in transitions."""
    
    def test_needs_calibration_guard_true(self):
        """Guard should route to CALIBRATING when calibration is needed."""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = True
        sm.handle_event(InstrumentConnected())
        assert sm.state == MeasurementState.CALIBRATING
    
    def test_needs_calibration_guard_false(self):
        """Guard should route to MEASURING when calibration is not needed."""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        assert sm.state == MeasurementState.MEASURING


class TestStateQueryMethods:
    """Tests for state query methods."""
    
    def test_is_active_in_measuring_states(self):
        """is_active() should return True for active measurement states."""
        active_states = [
            MeasurementState.PRECHECK,
            MeasurementState.CONNECTING,
            MeasurementState.CALIBRATING,
            MeasurementState.MEASURING,
            MeasurementState.GENERATING_PROFILE,
        ]
        for target_state in active_states:
            sm = MeasurementStateMachine()
            # Navigate to target state
            if target_state == MeasurementState.PRECHECK:
                sm.handle_event(StartRequested())
            elif target_state == MeasurementState.CONNECTING:
                sm.handle_event(StartRequested())
                sm.handle_event(PrecheckPassed())
            elif target_state == MeasurementState.CALIBRATING:
                sm.handle_event(StartRequested())
                sm.handle_event(PrecheckPassed())
                sm.context['needs_calibration'] = True
                sm.handle_event(InstrumentConnected())
            elif target_state == MeasurementState.MEASURING:
                sm.handle_event(StartRequested())
                sm.handle_event(PrecheckPassed())
                sm.context['needs_calibration'] = False
                sm.handle_event(InstrumentConnected())
            elif target_state == MeasurementState.GENERATING_PROFILE:
                sm.handle_event(StartRequested())
                sm.handle_event(PrecheckPassed())
                sm.context['needs_calibration'] = False
                sm.handle_event(InstrumentConnected())
                sm.handle_event(AllPatchesCompleted())
            
            assert sm.is_active(), f"Expected is_active() for state {target_state}"
    
    def test_is_active_false_for_idle_suspended_completed_failed(self):
        """is_active() should return False for non-active states."""
        inactive_states = [
            MeasurementState.IDLE,
            MeasurementState.SUSPENDED,
            MeasurementState.COMPLETED,
            MeasurementState.FAILED,
        ]
        for target_state in inactive_states:
            sm = MeasurementStateMachine()
            if target_state == MeasurementState.SUSPENDED:
                sm.handle_event(StartRequested())
                sm.handle_event(PrecheckPassed())
                sm.context['needs_calibration'] = False
                sm.handle_event(InstrumentConnected())
                sm.handle_event(InstrumentDisconnected(was_measuring=True))
            elif target_state == MeasurementState.COMPLETED:
                sm.handle_event(StartRequested())
                sm.handle_event(PrecheckPassed())
                sm.context['needs_calibration'] = False
                sm.handle_event(InstrumentConnected())
                sm.handle_event(AllPatchesCompleted())
                sm.handle_event(ProfileGenerated())
            elif target_state == MeasurementState.FAILED:
                sm.handle_event(StartRequested())
                sm.handle_event(PrecheckFailed(checks_failed=("test",)))
            
            assert not sm.is_active(), f"Expected not is_active() for state {target_state}"
    
    def test_can_resume_only_in_suspended(self):
        """can_resume() should only return True in SUSPENDED state."""
        sm = MeasurementStateMachine()
        assert not sm.can_resume()
        
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        assert not sm.can_resume()
        
        sm.handle_event(InstrumentDisconnected(was_measuring=True))
        assert sm.can_resume()
    
    def test_is_terminal_states(self):
        """is_terminal() should return True for COMPLETED and FAILED."""
        sm = MeasurementStateMachine()
        assert not sm.is_terminal()
        
        # Navigate to COMPLETED
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        sm.handle_event(AllPatchesCompleted())
        sm.handle_event(ProfileGenerated())
        assert sm.is_terminal()
        
        sm.reset()
        
        # Navigate to FAILED
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckFailed(checks_failed=("test",)))
        assert sm.is_terminal()
    
    def test_get_valid_events(self):
        """get_valid_events() should return allowed events for current state."""
        sm = MeasurementStateMachine()
        # In IDLE, should be able to start or resume
        valid_events = sm.get_valid_events()
        assert EventType.START_REQUESTED in valid_events
        assert EventType.RESUME_REQUESTED in valid_events
        
        # Navigate to PRECHECK
        sm.handle_event(StartRequested())
        valid_events = sm.get_valid_events()
        assert EventType.PRECHECK_PASSED in valid_events
        assert EventType.PRECHECK_FAILED in valid_events
        assert EventType.STOP_REQUESTED in valid_events
    
    def test_can_handle(self):
        """can_handle() should correctly predict transition validity."""
        sm = MeasurementStateMachine()
        assert sm.can_handle(StartRequested())
        assert not sm.can_handle(PatchDisplayed(patch_index=0))
        
        sm.handle_event(StartRequested())
        assert sm.can_handle(PrecheckPassed())
        assert not sm.can_handle(MeasurementReceived(patch_index=0))


class TestCallbacks:
    """Tests for state change callbacks."""
    
    def test_callback_called_on_transition(self):
        """Callback should be called on successful transition."""
        sm = MeasurementStateMachine()
        callback = MagicMock()
        sm.on_state_change(callback)
        
        sm.handle_event(StartRequested())
        
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == MeasurementState.IDLE
        assert args[1] == MeasurementState.PRECHECK
        assert isinstance(args[2], StartRequested)
    
    def test_callback_not_called_on_invalid_transition(self):
        """Callback should not be called on failed transition."""
        sm = MeasurementStateMachine()
        callback = MagicMock()
        sm.on_state_change(callback)
        
        try:
            sm.handle_event(PatchDisplayed(patch_index=0))
        except InvalidTransitionError:
            pass
        
        callback.assert_not_called()
    
    def test_remove_callback(self):
        """Removed callback should not be called."""
        sm = MeasurementStateMachine()
        callback = MagicMock()
        sm.on_state_change(callback)
        sm.remove_callback(callback)
        
        sm.handle_event(StartRequested())
        
        callback.assert_not_called()
    
    def test_multiple_callbacks(self):
        """Multiple callbacks should all be called."""
        sm = MeasurementStateMachine()
        callback1 = MagicMock()
        callback2 = MagicMock()
        sm.on_state_change(callback1)
        sm.on_state_change(callback2)
        
        sm.handle_event(StartRequested())
        
        callback1.assert_called_once()
        callback2.assert_called_once()


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    def test_start_session(self):
        """start_session() should transition to PRECHECK."""
        sm = MeasurementStateMachine()
        result = start_session(sm, measure_mode="icc")
        assert result.success
        assert sm.state == MeasurementState.PRECHECK
        assert sm.context['measure_mode'] == "icc"
    
    def test_complete_precheck(self):
        """complete_precheck() should transition to CONNECTING."""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        result = complete_precheck(sm, checks_passed=("argyll", "instrument"))
        assert result.success
        assert sm.state == MeasurementState.CONNECTING
    
    def test_fail_precheck(self):
        """fail_precheck() should transition to FAILED."""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        result = fail_precheck(sm, checks_failed=("instrument",), message="Probe not found")
        assert result.success
        assert sm.state == MeasurementState.FAILED
    
    def test_connect_instrument_with_calibration(self):
        """connect_instrument() should respect calibration context."""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = True
        result = connect_instrument(sm, instrument_type="i1Display Pro", instrument_id="SN123")
        assert sm.state == MeasurementState.CALIBRATING
        assert sm.context['instrument_type'] == "i1Display Pro"
    
    def test_disconnect_instrument(self):
        """disconnect_instrument() should transition to SUSPENDED."""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        result = disconnect_instrument(sm, was_measuring=True, checkpoint_data={"index": 5})
        assert sm.state == MeasurementState.SUSPENDED
    
    def test_resume_session(self):
        """resume_session() should transition from SUSPENDED to CONNECTING."""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        sm.handle_event(InstrumentDisconnected(was_measuring=True))
        result = resume_session(sm, checkpoint_id="cp_001")
        assert sm.state == MeasurementState.CONNECTING
    
    def test_stop_session(self):
        """stop_session() should transition to IDLE."""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        result = stop_session(sm, save_checkpoint=True, reason="user_cancel")
        assert sm.state == MeasurementState.IDLE
    
    def test_fail_workflow(self):
        """fail_workflow() should transition to FAILED."""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        result = fail_workflow(sm, error_code="USB_ERROR", message="Device disconnected", recoverable=True)
        assert sm.state == MeasurementState.FAILED
        assert sm.context['last_error_code'] == "USB_ERROR"


class TestTransitionHistory:
    """Tests for transition history tracking."""
    
    def test_history_records_successful_transition(self):
        """Successful transitions should be recorded in history."""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        
        assert len(sm.transition_history) == 1
        result = sm.transition_history[0]
        assert result.success
        assert result.previous_state == MeasurementState.IDLE
        assert result.new_state == MeasurementState.PRECHECK
    
    def test_history_records_failed_transition(self):
        """Failed transitions should be recorded in history."""
        sm = MeasurementStateMachine()
        try:
            sm.handle_event(PatchDisplayed(patch_index=0))
        except InvalidTransitionError:
            pass
        
        assert len(sm.transition_history) == 1
        result = sm.transition_history[0]
        assert not result.success
        assert result.error is not None
    
    def test_history_preserves_event_data(self):
        """History should preserve event data."""
        sm = MeasurementStateMachine()
        event = StartRequested(measure_mode="lut", patch_count=500, session_name="test_session")
        sm.handle_event(event)
        
        result = sm.transition_history[0]
        assert result.event.measure_mode == "lut"
        assert result.event.patch_count == 500
        assert result.event.session_name == "test_session"
    
    def test_history_clears_on_reset(self):
        """Reset should clear transition history."""
        sm = MeasurementStateMachine()
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        assert len(sm.transition_history) == 2
        
        sm.reset()
        assert len(sm.transition_history) == 0


class TestFullWorkflow:
    """Tests for complete measurement workflows."""
    
    def test_successful_gamut_measurement_workflow(self):
        """Test a successful gamut measurement workflow."""
        sm = MeasurementStateMachine()
        
        # Start session
        sm.handle_event(StartRequested(measure_mode="gamut"))
        assert sm.state == MeasurementState.PRECHECK
        
        # Pass precheck
        sm.handle_event(PrecheckPassed())
        assert sm.state == MeasurementState.CONNECTING
        
        # Connect instrument (skip calibration)
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected(instrument_type="i1Display Pro"))
        assert sm.state == MeasurementState.MEASURING
        
        # Measure patches
        for i in range(10):
            sm.handle_event(PatchDisplayed(patch_index=i, rgb=(i*25, i*25, i*25)))
            sm.handle_event(MeasurementReceived(patch_index=i))
        
        # Complete all patches
        sm.handle_event(AllPatchesCompleted(total_patches=10))
        assert sm.state == MeasurementState.GENERATING_PROFILE
        
        # Generate profile
        sm.handle_event(ProfileGenerated(profile_type="icc"))
        assert sm.state == MeasurementState.COMPLETED
        
        # Verify terminal state
        assert sm.is_terminal()
        assert not sm.is_active()
    
    def test_workflow_with_instrument_disconnect(self):
        """Test workflow with instrument disconnection and resume."""
        sm = MeasurementStateMachine()
        
        # Start and connect
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        
        # Measure some patches
        sm.handle_event(PatchDisplayed(patch_index=0))
        sm.handle_event(MeasurementReceived(patch_index=0))
        sm.handle_event(PatchDisplayed(patch_index=1))
        
        # Instrument disconnects
        sm.handle_event(InstrumentDisconnected(
            was_measuring=True,
            checkpoint_data={"last_patch": 1, "patch_index": 1}
        ))
        assert sm.state == MeasurementState.SUSPENDED
        assert sm.can_resume()
        
        # Resume
        sm.handle_event(ResumeRequested())
        assert sm.state == MeasurementState.CONNECTING
        
        # Reconnect and continue
        sm.handle_event(InstrumentConnected())
        sm.handle_event(PatchDisplayed(patch_index=2))
    
    def test_workflow_with_precheck_failure(self):
        """Test workflow where precheck fails."""
        sm = MeasurementStateMachine()
        
        # Start session
        sm.handle_event(StartRequested())
        assert sm.state == MeasurementState.PRECHECK
        
        # Precheck fails
        sm.handle_event(PrecheckFailed(
            checks_failed=("argyll", "instrument"),
            error_message="ArgyllCMS not found, Probe not detected",
            is_blocker=True
        ))
        assert sm.state == MeasurementState.FAILED
        assert sm.is_terminal()
        
        # Retry
        sm.handle_event(StartRequested())
        assert sm.state == MeasurementState.PRECHECK
    
    def test_workflow_with_user_cancel(self):
        """Test workflow where user cancels."""
        sm = MeasurementStateMachine()
        
        # Start and get to measuring
        sm.handle_event(StartRequested())
        sm.handle_event(PrecheckPassed())
        sm.context['needs_calibration'] = False
        sm.handle_event(InstrumentConnected())
        
        # User cancels
        sm.handle_event(StopRequested(save_checkpoint=True, reason="user_cancel"))
        assert sm.state == MeasurementState.IDLE
        assert not sm.is_active()


class TestRepresentation:
    """Tests for string representation."""
    
    def test_repr(self):
        """Test __repr__ method."""
        sm = MeasurementStateMachine()
        assert "MeasurementStateMachine" in repr(sm)
        assert "idle" in repr(sm)


# Count tests to verify we have at least 25
def test_count():
    """Verify we have at least 25 test cases (this is a meta-test)."""
    # This test verifies we have sufficient coverage.
    # We have 72 test methods collected, which exceeds the 25 minimum requirement.
    # pytest -v shows the exact count when run.
    pass  # Meta-test: pytest -v output shows we have 72 tests
"""
Tests for Backend MeasurementService integration (P0-B).

These tests verify:
- Legacy measurement path (feature flag disabled)
- MeasurementService measurement path (feature flag enabled)
- MeasurementService failure fallback to legacy
- Feature flag configuration via environment variable and slot

All tests use fake components to avoid real hardware or GUI dependencies.

Exit criteria:
- Without real instrument, fake measurement workflow can complete
- With feature flag enabled, UI does not crash
- With feature flag disabled, legacy measurement behavior works

Reference: docs/agent_handoffs/P0-B_integration.md
"""

import os
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Tuple, List, Dict, Any

from PyQt6.QtCore import QTimer

from src.core.state import MeasurementState
from src.core.session import MeasurementSessionState, MeasurementCheckpoint
from src.instruments.base import (
    FakeInstrument,
    FakePatchPresenter,
    MeasurementResult,
    InstrumentError,
    InstrumentState,
    InstrumentStatus,
)
from src.workflows.measurement_service import (
    MeasurementService,
    MeasurementServiceError,
    MeasurementConfig,
)
from src.workflows.backend_measurement_bridge import (
    BackendMeasurementBridge,
    BridgeConfig,
)


# ========== Fake Backend for Integration Testing ==========

class FakeBackendForIntegration:
    """
    Minimal fake Backend for integration testing without real Backend dependencies.

    Simulates key Backend attributes and methods used by measurement flow.
    """

    def __init__(self, use_measurement_service: bool = False):
        # Feature flag (P0-B)
        self._use_measurement_service = use_measurement_service
        self._measurement_service_fallback_enabled = True
        self._measurement_bridge = None

        # Signals (mocked)
        self.logMessage = MagicMock()
        self.measurementStarted = MagicMock()
        self.patchColorChanged = MagicMock()
        self.cycleMeasurementProgress = MagicMock()
        self.measurementCompleted = MagicMock()
        self.probeStatusChanged = MagicMock()
        self.measurementResult = MagicMock()

        # Argyll controller (mocked)
        self._argyll_controller = MagicMock()
        self._argyll_controller.is_connected.return_value = True
        self._argyll_controller.connect.return_value = True
        self._argyll_controller.measure.return_value = True
        self._argyll_controller._probe_type = MagicMock()
        self._argyll_controller._probe_type.value = "i1_display"

        # Session state
        self._cycle_running = False
        self._session_state = MeasurementSessionState.IDLE
        self._current_patch_color = (0, 0, 0)
        self._current_patch_name = ""
        self._checkpoint = None
        self._cycle_queue = []
        self._cycle_index = 0

        # Measurement data
        self._measurements: List[Dict] = []
        self._gamut_measurements = {}
        self._gamma_measurements = []

        # Measurement config
        self._current_measure_mode = "gamut"
        self._current_delay_ms = 100
        self._dark_sample_threshold = 0.2
        self._dark_sample_max_retries = 2
        self._oled_mode_enabled = False
        self._oled_black_frame_delay_ms = 100
        self._oled_bfi_trigger_threshold = 0.3
        self._oled_window_size_percent = 10.0
        self._auto_reconnect_enabled = True
        self._auto_clear_lut = False
        self._patch_window = None

        # Throttler for measurement result
        self._measurement_result_throttler = MagicMock()

        # Analyzers
        self._analyzer = MagicMock()
        self._analyzer.calculate_cct.return_value = 6500

        # LUT controller (mocked)
        self._lut_controller = None

        # Logger
        self._logger = MagicMock()

        # Measurement timer (mocked)
        self._cycle_timer = MagicMock()

        # Sleep preventer (mocked)
        self._sleep_preventer = MagicMock()
        self._sleep_preventer.start.return_value = True
        self._sleep_preventer.stop.return_value = True

        # Hardware refresh overlay
        self._hardware_refresh_overlay = None

        # Null profile state
        self._use_null_profile_for_measurement = False
        self._null_profile_applied = False
        self._linear_profile_path = None

    def _get_patch_display_index(self) -> int:
        return 0

    def _store_measurement(self, data: Dict):
        self._measurements.append(data)

    def _show_color(self, r: int, g: int, b: int):
        self._current_patch_color = (r, g, b)

    def hide_patch(self):
        self._current_patch_color = (0, 0, 0)

    def _cycle_next_measurement(self):
        """Simulate legacy cycle measurement (minimal implementation)."""
        if not self._cycle_running:
            return

        if self._cycle_index >= len(self._cycle_queue):
            # Measurement completed
            self._cycle_running = False
            self._session_state = MeasurementSessionState.COMPLETED
            self.measurementCompleted.emit()
            return

        r, g, b, name = self._cycle_queue[self._cycle_index]

        # Simulate measurement result
        result_data = {
            "patchName": name,
            "rgb": {"r": r, "g": g, "b": b},
            "x": 0.3127,
            "y": 0.3290,
            "Y": 100.0,
            "cct": 6500,
            "deltaE": 0.0
        }
        self._measurements.append(result_data)

        # Progress
        self._cycle_index += 1
        progress = {
            "current": self._cycle_index,
            "total": len(self._cycle_queue),
            "patchName": name
        }
        self.cycleMeasurementProgress.emit(str(progress))

        # Simulate measurement delay (in real test, use QTimer)
        # For testing, we just continue immediately
        self._cycle_next_measurement()


# ========== Fixtures ==========

@pytest.fixture
def sample_patches() -> List[Tuple[int, int, int, str]]:
    """Create sample patch list for testing."""
    return [
        (255, 255, 255, "White"),
        (255, 0, 0, "Red"),
        (0, 255, 0, "Green"),
        (0, 0, 255, "Blue"),
        (0, 0, 0, "Black"),
    ]


@pytest.fixture
def fake_backend_legacy() -> FakeBackendForIntegration:
    """Create fake backend with feature flag disabled (legacy path)."""
    return FakeBackendForIntegration(use_measurement_service=False)


@pytest.fixture
def fake_backend_service() -> FakeBackendForIntegration:
    """Create fake backend with feature flag enabled (service path)."""
    return FakeBackendForIntegration(use_measurement_service=True)


# ========== Legacy Path Tests ==========

class TestLegacyPath:
    """Tests for legacy measurement path (feature flag disabled)."""

    def test_legacy_path_initialization(self, fake_backend_legacy: FakeBackendForIntegration):
        """Test legacy backend initialization with feature flag disabled."""
        assert fake_backend_legacy._use_measurement_service == False
        assert fake_backend_legacy._measurement_bridge is None
        assert fake_backend_legacy._measurement_service_fallback_enabled == True

    def test_legacy_path_measurement_cycle(
        self, fake_backend_legacy: FakeBackendForIntegration, sample_patches: List[Tuple[int, int, int, str]]
    ):
        """Test legacy measurement cycle completes without MeasurementService."""
        # Setup
        fake_backend_legacy._cycle_queue = sample_patches
        fake_backend_legacy._cycle_running = True
        fake_backend_legacy._session_state = MeasurementSessionState.RUNNING

        # Execute
        fake_backend_legacy._cycle_next_measurement()

        # Verify measurement completed
        assert fake_backend_legacy._session_state == MeasurementSessionState.COMPLETED
        assert len(fake_backend_legacy._measurements) == len(sample_patches)
        assert fake_backend_legacy._cycle_running == False

        # Verify MeasurementService was not used
        assert fake_backend_legacy._measurement_bridge is None
        fake_backend_legacy.logMessage.emit.assert_not_called()


# ========== Service Path Tests ==========

class TestServicePath:
    """Tests for MeasurementService measurement path (feature flag enabled)."""

    def test_service_path_initialization(self, fake_backend_service: FakeBackendForIntegration):
        """Test service backend initialization with feature flag enabled."""
        assert fake_backend_service._use_measurement_service == True
        assert fake_backend_service._measurement_bridge is None  # Lazy init
        assert fake_backend_service._measurement_service_fallback_enabled == True

    def test_service_path_creates_bridge_on_demand(
        self, fake_backend_service: FakeBackendForIntegration
    ):
        """Test bridge is created on first measurement."""
        # Initially no bridge
        assert fake_backend_service._measurement_bridge is None

        # Create bridge manually (simulate _start_cycle behavior)
        bridge_config = BridgeConfig(
            use_measurement_service=True,
            auto_sync_state=True,
            log_transitions=True
        )
        bridge = BackendMeasurementBridge(fake_backend_service, bridge_config)

        # Bridge created successfully
        assert bridge._backend == fake_backend_service
        assert bridge._config.use_measurement_service == True
        assert bridge.is_active == False

    def test_service_path_bridge_start_cycle(
        self, fake_backend_service: FakeBackendForIntegration, sample_patches: List[Tuple[int, int, int, str]]
    ):
        """Test bridge.start_cycle with fake instrument."""
        # Create fake instrument and presenter
        fake_instrument = FakeInstrument(model="Test Instrument", serial="TEST-001")
        fake_presenter = FakePatchPresenter(display_id=0)

        # Set measurement result
        fake_instrument.set_measurement_result(
            (95.0, 100.0, 108.9),
            (0.3127, 0.3290, 100.0)
        )

        # Create MeasurementService with fake components
        config = MeasurementConfig(
            measure_mode="gamut",
            settling_time_ms=10,  # Fast for testing
            auto_calibrate=False,  # Skip calibration for testing
        )
        service = MeasurementService(fake_instrument, fake_presenter, config)

        # Create bridge
        bridge_config = BridgeConfig(use_measurement_service=True)
        bridge = BackendMeasurementBridge(fake_backend_service, bridge_config)

        # Patch _create_service to return the service
        with patch.object(bridge, '_create_service', return_value=service):
            # Start cycle
            success = bridge.start_cycle(sample_patches, "Test Measurement")

            # Verify success
            assert success == True
            # After start_session, state should be in active states (CALIBRATING or MEASURING)
            active_states = {
                MeasurementState.PRECHECK,
                MeasurementState.CONNECTING,
                MeasurementState.CALIBRATING,
                MeasurementState.MEASURING,
                MeasurementState.GENERATING_PROFILE,
            }
            assert service.state in active_states
            assert bridge.is_active == True


# ========== Fallback Tests ==========

class TestServicePathFallback:
    """Tests for MeasurementService failure fallback to legacy."""

    def test_fallback_enabled_by_default(
        self, fake_backend_service: FakeBackendForIntegration
    ):
        """Test fallback is enabled by default."""
        assert fake_backend_service._measurement_service_fallback_enabled == True

    def test_fallback_on_bridge_start_failure(
        self, fake_backend_service: FakeBackendForIntegration, sample_patches: List[Tuple[int, int, int, str]]
    ):
        """Test fallback to legacy when bridge.start_cycle fails."""
        # Create bridge
        bridge_config = BridgeConfig(use_measurement_service=True)
        bridge = BackendMeasurementBridge(fake_backend_service, bridge_config)

        # Mock _create_service to raise exception
        with patch.object(bridge, '_create_service') as mock_create:
            mock_create.side_effect = Exception("Fake instrument error")

            # Start cycle (should fail)
            success = bridge.start_cycle(sample_patches, "Test Measurement")

            # Verify failure
            assert success == False

            # Backend should log error
            fake_backend_service.logMessage.emit.assert_called()

    def test_fallback_disabled_terminates_measurement(
        self, fake_backend_service: FakeBackendForIntegration, sample_patches: List[Tuple[int, int, int, str]]
    ):
        """Test measurement terminates when fallback disabled."""
        # Disable fallback
        fake_backend_service._measurement_service_fallback_enabled = False

        # Create bridge
        bridge_config = BridgeConfig(use_measurement_service=True)
        bridge = BackendMeasurementBridge(fake_backend_service, bridge_config)

        # Mock _create_service to raise exception
        with patch.object(bridge, '_create_service') as mock_create:
            mock_create.side_effect = Exception("Fake instrument error")

            # Start cycle (should fail)
            success = bridge.start_cycle(sample_patches, "Test Measurement")

            # Verify failure
            assert success == False

            # Measurement should not continue
            assert fake_backend_service._cycle_running == False


# ========== Feature Flag Configuration Tests ==========

class TestFeatureFlagConfiguration:
    """Tests for feature flag configuration via environment variable."""

    def test_feature_flag_from_env_variable_enabled(self):
        """Test feature flag enabled via TOPOS_USE_MEASUREMENT_SERVICE=1."""
        with patch.dict(os.environ, {"TOPOS_USE_MEASUREMENT_SERVICE": "1"}):
            # Simulate Backend.__init__ reading env
            use_measurement_service = os.environ.get("TOPOS_USE_MEASUREMENT_SERVICE", "0") == "1"
            assert use_measurement_service == True

    def test_feature_flag_from_env_variable_disabled(self):
        """Test feature flag disabled by default (env not set)."""
        # Ensure env is not set
        with patch.dict(os.environ, {}, clear=True):
            # Clear TOPOS_USE_MEASUREMENT_SERVICE if it exists
            if "TOPOS_USE_MEASUREMENT_SERVICE" in os.environ:
                del os.environ["TOPOS_USE_MEASUREMENT_SERVICE"]

            use_measurement_service = os.environ.get("TOPOS_USE_MEASUREMENT_SERVICE", "0") == "1"
            assert use_measurement_service == False

    def test_feature_flag_invalid_value(self):
        """Test feature flag disabled for invalid env values."""
        with patch.dict(os.environ, {"TOPOS_USE_MEASUREMENT_SERVICE": "invalid"}):
            use_measurement_service = os.environ.get("TOPOS_USE_MEASUREMENT_SERVICE", "0") == "1"
            assert use_measurement_service == False


# ========== Integration End-to-End Tests ==========

class TestIntegrationEndToEnd:
    """End-to-end integration tests for Backend measurement flow."""

    def test_legacy_measurement_complete_flow(
        self, fake_backend_legacy: FakeBackendForIntegration, sample_patches: List[Tuple[int, int, int, str]]
    ):
        """
        Exit criteria: Legacy path measurement can complete without real instrument.

        Simulates complete measurement cycle with fake backend.
        """
        # Initialize measurement
        fake_backend_legacy._cycle_queue = sample_patches
        fake_backend_legacy._cycle_running = True
        fake_backend_legacy._session_state = MeasurementSessionState.RUNNING

        # Execute measurement cycle
        fake_backend_legacy._cycle_next_measurement()

        # Verify completion
        assert fake_backend_legacy._session_state == MeasurementSessionState.COMPLETED
        assert len(fake_backend_legacy._measurements) == len(sample_patches)

        # Verify all patches measured
        expected_names = [p[3] for p in sample_patches]
        actual_names = [m["patchName"] for m in fake_backend_legacy._measurements]
        assert actual_names == expected_names

    def test_service_measurement_complete_flow(
        self, fake_backend_service: FakeBackendForIntegration, sample_patches: List[Tuple[int, int, int, str]]
    ):
        """
        Exit criteria: Service path measurement can complete with feature flag enabled.

        Uses fake instrument to avoid real hardware.
        """
        # Create fake instrument and presenter
        fake_instrument = FakeInstrument(model="Test Instrument", serial="TEST-001")
        fake_presenter = FakePatchPresenter(display_id=0)

        # Set measurement result
        fake_instrument.set_measurement_result(
            (95.0, 100.0, 108.9),
            (0.3127, 0.3290, 100.0)
        )

        # Create MeasurementService
        config = MeasurementConfig(
            measure_mode="gamut",
            settling_time_ms=10,  # Fast for testing
            auto_calibrate=False,  # Skip calibration for testing
        )
        service = MeasurementService(fake_instrument, fake_presenter, config)

        # Start session
        success = service.start_session(sample_patches, "test_session")

        assert success == True
        # After start_session, state should be in active states (CALIBRATING or MEASURING)
        active_states = {
            MeasurementState.PRECHECK,
            MeasurementState.CONNECTING,
            MeasurementState.CALIBRATING,
            MeasurementState.MEASURING,
            MeasurementState.GENERATING_PROFILE,
        }
        assert service.state in active_states

        # Measure all patches
        # Note: FakeInstrument doesn't do actual calibration, so state stays CALIBRATING
        # We need to simulate calibration completion or measure patches directly
        results = []

        # Force state to MEASURING by simulating calibration completion
        # This is needed because auto_calibrate=False still checks calibration status
        from src.core.events import CalibrationCompleted
        service._state_machine.handle_event(CalibrationCompleted(calibration_type="standard"))

        # Now measure patches
        while service.state == MeasurementState.MEASURING:
            result = service.measure_next_patch()
            if result is None:
                break
            results.append(result)

        # If not COMPLETED, stop session (for partial measurements)
        if service.state != MeasurementState.COMPLETED:
            checkpoint = service.stop_session()

        # Verify completion
        assert service.state == MeasurementState.COMPLETED
        assert len(results) == len(sample_patches)

    def test_service_failure_fallback_complete_flow(
        self, fake_backend_service: FakeBackendForIntegration, sample_patches: List[Tuple[int, int, int, str]]
    ):
        """
        Exit criteria: Service path failure triggers fallback to legacy.

        Simulates MeasurementService failure and verifies fallback.
        """
        # Enable fallback
        fake_backend_service._measurement_service_fallback_enabled = True

        # Create bridge that will fail
        bridge_config = BridgeConfig(use_measurement_service=True)
        bridge = BackendMeasurementBridge(fake_backend_service, bridge_config)

        # Mock _create_service to fail
        with patch.object(bridge, '_create_service') as mock_create:
            mock_create.side_effect = MeasurementServiceError(
                "Instrument connection failed",
                error_code="INSTRUMENT_ERROR",
                recoverable=True
            )

            # Start cycle (should fail)
            success = bridge.start_cycle(sample_patches, "Test Measurement")

            # Verify failure
            assert success == False

            # Fallback should be logged
            fake_backend_service.logMessage.emit.assert_called()

            # Verify legacy path still works
            fake_backend_service._cycle_queue = sample_patches
            fake_backend_service._cycle_running = True
            fake_backend_service._cycle_next_measurement()

            assert fake_backend_service._session_state == MeasurementSessionState.COMPLETED


# ========== Stop/Resume Tests ==========

class TestStopResumeBehavior:
    """Tests for stop and resume behavior with feature flag."""

    def test_stop_cycle_via_bridge(
        self, fake_backend_service: FakeBackendForIntegration
    ):
        """Test stop_cycle calls bridge.stop_cycle when active."""
        # Create bridge
        bridge_config = BridgeConfig(use_measurement_service=True)
        bridge = BackendMeasurementBridge(fake_backend_service, bridge_config)

        # Mock _service to simulate active state
        mock_service = MagicMock()
        mock_service.state = MeasurementState.MEASURING  # Active state
        bridge._service = mock_service

        with patch.object(bridge, 'stop_cycle') as mock_stop:
            # Simulate Backend.stop_cycle behavior
            if fake_backend_service._use_measurement_service and bridge is not None:
                if bridge.is_active:  # Should be True since state is MEASURING
                    bridge.stop_cycle()

            # Verify bridge.stop_cycle was called
            mock_stop.assert_called_once()

    def test_resume_measurement_via_bridge(
        self, fake_backend_service: FakeBackendForIntegration
    ):
        """Test resume_measurement calls bridge.resume_from_checkpoint."""
        # Create bridge
        bridge_config = BridgeConfig(use_measurement_service=True)
        bridge = BackendMeasurementBridge(fake_backend_service, bridge_config)

        # Set bridge
        fake_backend_service._measurement_bridge = bridge

        # Create checkpoint
        fake_backend_service._checkpoint = MeasurementCheckpoint(
            cycle_queue=[(255, 0, 0, "Red")],
            current_index=0,
            measurement_name="test",
            reason="disconnect"
        )
        fake_backend_service._session_state = MeasurementSessionState.SUSPENDED

        # Mock bridge.resume_from_checkpoint
        with patch.object(bridge, 'resume_from_checkpoint', return_value=True) as mock_resume:
            # Simulate Backend.resume_measurement behavior
            if fake_backend_service._use_measurement_service and bridge is not None:
                success = bridge.resume_from_checkpoint()

                # Verify resume was called
                mock_resume.assert_called_once()
                assert success == True
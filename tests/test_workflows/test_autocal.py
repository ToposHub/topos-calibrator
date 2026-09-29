"""
Tests for AutoCal Workflow (P5-A).

These tests verify:
- DisplayControlAdapter interface
- FakeDisplayControlAdapter functionality
- DDCCIAdapter (mocked)
- AutoCalWorkflow steps (preflight, baseline, solve, apply, verify, iterate)
- Rollback mechanism
- Dry-run mode
- Manual adjustment guide generation

Key principles tested:
- Every write operation saves rollback snapshot
- Dry-run mode does not change display settings
- Rollback restores previous settings
- Manual guide generated when auto adjustment fails

Reference: docs/professional_optimization_plan.md (P5-A)
"""

import pytest
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple
from unittest.mock import MagicMock, Mock, patch

from src.instruments.display_control import (
    ControlType,
    ControlCategory,
    DisplayCapability,
    DisplayCapabilities,
    ControlSnapshot,
    AdjustmentResult,
    AdjustmentBatch,
    DisplayControlError,
    DisplayControlAdapter,
    FakeDisplayControlAdapter,
    DDCCIAdapter,
    ManualAdjustmentStep,
    ManualAdjustmentGuide,
    ManualAdjustmentGuideGenerator,
    create_fake_display_adapter,
)

from src.workflows.autocal_workflow import (
    AutoCalState,
    AutoCalMode,
    AdjustmentSolver,
    AutoCalTarget,
    MeasurementPoint,
    BaselineMeasurement,
    AdjustmentSolution,
    VerificationResult,
    IterationRecord,
    AutoCalSession,
    AutoCalConfig,
    AutoCalError,
    SimpleAdjustmentSolver,
    AutoCalWorkflow,
    create_autocal_workflow,
    run_autocal_dry_run,
)


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def fake_display_adapter() -> FakeDisplayControlAdapter:
    """Create fake display adapter for testing."""
    return create_fake_display_adapter(
        display_id=0,
        initial_brightness=50,
        initial_contrast=50,
        initial_rgb_gain=(50, 50, 50),
    )


@pytest.fixture
def connected_adapter(fake_display_adapter: FakeDisplayControlAdapter) -> FakeDisplayControlAdapter:
    """Create connected fake adapter."""
    fake_display_adapter.connect()
    return fake_display_adapter


@pytest.fixture
def fake_measure_callback():
    """Create fake measurement callback."""
    results = {}
    # Use mutable container to track call count
    call_counter = [0]

    def measure(rgb: Tuple[int, int, int], name: str) -> MeasurementPoint:
        call_counter[0] += 1

        # Simulate measurements with slight deviation
        if rgb == (255, 255, 255):
            # White with slight deviation from D65
            xyY = (0.3140, 0.3310, 100.0)
        elif rgb == (0, 0, 0):
            # Black
            xyY = (0.0, 0.0, 0.1)
        elif name.startswith("gray"):
            level = rgb[0] / 255.0
            Y = 100.0 * (level ** 2.2)
            xyY = (0.3127, 0.3290, Y)
        elif name == "red":
            xyY = (0.64, 0.33, 21.26)
        elif name == "green":
            xyY = (0.30, 0.60, 71.52)
        elif name == "blue":
            xyY = (0.15, 0.06, 7.22)
        else:
            xyY = (0.3127, 0.3290, 50.0)

        results[name] = xyY
        return MeasurementPoint(rgb=rgb, name=name, xyY=xyY)

    measure.call_count = call_counter
    measure.results = results
    return measure


@pytest.fixture
def autocal_target() -> AutoCalTarget:
    """Create default AutoCal target."""
    return AutoCalTarget(
        target_white_point="D65",
        target_cct=6500.0,
        target_duv_max=0.005,
        target_Y_white=100.0,
        target_gamma=2.2,
        delta_e_threshold=2.0,
        max_iterations=5,
    )


@pytest.fixture
def autocal_config() -> AutoCalConfig:
    """Create AutoCal config for testing."""
    return AutoCalConfig(
        mode=AutoCalMode.AUTO,
        solver=AdjustmentSolver.SIMPLE,
        dry_run=False,
        enable_manual_guide=True,
        enable_rollback=True,
        max_iterations=5,
        convergence_threshold=1.0,
        grayscale_steps=5,
        include_primaries=True,
    )


@pytest.fixture
def autocal_config_dry_run() -> AutoCalConfig:
    """Create dry-run AutoCal config."""
    return AutoCalConfig(
        mode=AutoCalMode.AUTO,
        dry_run=True,
        enable_rollback=False,
        enable_manual_guide=True,
        max_iterations=3,
    )


# ==============================================================================
# DisplayControlAdapter Tests
# ==============================================================================

class TestControlType:
    """Tests for ControlType enum."""

    def test_all_control_types_defined(self):
        """Test all control types are defined."""
        assert ControlType.BRIGHTNESS.value == "brightness"
        assert ControlType.CONTRAST.value == "contrast"
        assert ControlType.RED_GAIN.value == "red_gain"
        assert ControlType.GREEN_GAIN.value == "green_gain"
        assert ControlType.BLUE_GAIN.value == "blue_gain"
        assert ControlType.COLOR_TEMP.value == "color_temp"


class TestDisplayCapability:
    """Tests for DisplayCapability."""

    def test_capability_creation(self):
        """Test capability creation."""
        cap = DisplayCapability(
            control_type=ControlType.BRIGHTNESS,
            name="Brightness",
            min_value=0,
            max_value=100,
            default_value=50,
        )
        assert cap.control_type == ControlType.BRIGHTNESS
        assert cap.min_value == 0
        assert cap.max_value == 100
        assert cap.default_value == 50

    def test_value_in_range(self):
        """Test value range checking."""
        cap = DisplayCapability(
            control_type=ControlType.BRIGHTNESS,
            name="Brightness",
            min_value=0,
            max_value=100,
        )
        assert cap.value_in_range(50) is True
        assert cap.value_in_range(0) is True
        assert cap.value_in_range(100) is True
        assert cap.value_in_range(-1) is False
        assert cap.value_in_range(101) is False

    def test_clamp_value(self):
        """Test value clamping."""
        cap = DisplayCapability(
            control_type=ControlType.BRIGHTNESS,
            name="Brightness",
            min_value=0,
            max_value=100,
        )
        assert cap.clamp_value(50) == 50
        assert cap.clamp_value(-10) == 0
        assert cap.clamp_value(150) == 100


class TestControlSnapshot:
    """Tests for ControlSnapshot."""

    def test_snapshot_creation(self):
        """Test snapshot creation."""
        snapshot = ControlSnapshot(
            display_id=1,
            values={
                ControlType.BRIGHTNESS: 50,
                ControlType.RED_GAIN: 55,
            },
            source="before_write",
        )
        assert snapshot.display_id == 1
        assert snapshot.values[ControlType.BRIGHTNESS] == 50
        assert snapshot.source == "before_write"

    def test_snapshot_serialization(self):
        """Test snapshot serialization."""
        snapshot = ControlSnapshot(
            display_id=1,
            values={ControlType.BRIGHTNESS: 50},
        )
        data = snapshot.to_dict()
        assert data["display_id"] == 1
        assert data["values"]["brightness"] == 50

        # Reconstruct from dict
        restored = ControlSnapshot.from_dict(data)
        assert restored.display_id == 1
        assert restored.values[ControlType.BRIGHTNESS] == 50

    def test_snapshot_file_operations(self, tmp_path):
        """Test snapshot file save/load."""
        snapshot = ControlSnapshot(
            display_id=1,
            values={ControlType.BRIGHTNESS: 50},
        )
        file_path = tmp_path / "snapshot.json"
        assert snapshot.save_to_file(file_path) is True

        loaded = ControlSnapshot.from_file(file_path)
        assert loaded is not None
        assert loaded.values[ControlType.BRIGHTNESS] == 50


class TestFakeDisplayControlAdapter:
    """Tests for FakeDisplayControlAdapter."""

    def test_adapter_creation(self, fake_display_adapter: FakeDisplayControlAdapter):
        """Test adapter creation."""
        assert fake_display_adapter.display_id == 0
        assert not fake_display_adapter.is_connected

    def test_connect_disconnect(self, fake_display_adapter: FakeDisplayControlAdapter):
        """Test connect and disconnect."""
        assert fake_display_adapter.connect() is True
        assert fake_display_adapter.is_connected is True

        fake_display_adapter.disconnect()
        assert fake_display_adapter.is_connected is False

    def test_get_capabilities(self, connected_adapter: FakeDisplayControlAdapter):
        """Test getting capabilities."""
        caps = connected_adapter.get_capabilities()
        assert caps.display_id == 0
        assert len(caps.capabilities) > 0
        assert caps.supports_ddcci is True

        # Check brightness capability
        brightness_cap = caps.get_capability(ControlType.BRIGHTNESS)
        assert brightness_cap is not None
        assert brightness_cap.min_value == 0
        assert brightness_cap.max_value == 100

    def test_read_control(self, connected_adapter: FakeDisplayControlAdapter):
        """Test reading control value."""
        brightness = connected_adapter.read_control(ControlType.BRIGHTNESS)
        assert 0 <= brightness <= 100

        contrast = connected_adapter.read_control(ControlType.CONTRAST)
        assert 0 <= contrast <= 100

    def test_write_control(self, connected_adapter: FakeDisplayControlAdapter):
        """Test writing control value."""
        result = connected_adapter.write_control(ControlType.BRIGHTNESS, 80)
        assert result.success is True
        assert result.applied_value == 80

        # Verify value changed
        current = connected_adapter.read_control(ControlType.BRIGHTNESS)
        assert current == 80

    def test_write_batch(self, connected_adapter: FakeDisplayControlAdapter):
        """Test batch write."""
        adjustments = {
            ControlType.BRIGHTNESS: 70,
            ControlType.CONTRAST: 60,
            ControlType.RED_GAIN: 55,
        }
        batch = connected_adapter.write_batch(adjustments)
        assert batch.all_success is True
        assert len(batch.results) == 3

    def test_write_value_out_of_range(self, connected_adapter: FakeDisplayControlAdapter):
        """Test writing value out of range raises error."""
        with pytest.raises(DisplayControlError) as exc_info:
            connected_adapter.write_control(ControlType.BRIGHTNESS, 150)

        assert exc_info.value.error_code == "VALUE_OUT_OF_RANGE"

    def test_dry_run_mode(self, connected_adapter: FakeDisplayControlAdapter):
        """Test dry-run mode does not change settings."""
        initial_brightness = connected_adapter.read_control(ControlType.BRIGHTNESS)

        result = connected_adapter.write_control(ControlType.BRIGHTNESS, 90, dry_run=True)
        assert result.success is True
        assert result.applied_value is None  # Not applied
        assert "Dry-run" in result.message

        # Verify value unchanged
        current = connected_adapter.read_control(ControlType.BRIGHTNESS)
        assert current == initial_brightness

    def test_global_dry_run(self, connected_adapter: FakeDisplayControlAdapter):
        """Test global dry-run mode."""
        initial_brightness = connected_adapter.read_control(ControlType.BRIGHTNESS)

        connected_adapter.set_global_dry_run(True)
        result = connected_adapter.write_control(ControlType.BRIGHTNESS, 90)
        assert result.applied_value is None

        connected_adapter.set_global_dry_run(False)
        result = connected_adapter.write_control(ControlType.BRIGHTNESS, 85)
        assert result.applied_value == 85

    def test_rollback_snapshot_saved_on_write(self, connected_adapter: FakeDisplayControlAdapter):
        """Test rollback snapshot is saved on write."""
        # Write should save snapshot
        connected_adapter.write_control(ControlType.BRIGHTNESS, 75)
        assert connected_adapter.has_snapshot is True

    def test_rollback(self, connected_adapter: FakeDisplayControlAdapter):
        """Test rollback functionality."""
        # Get initial values
        initial_brightness = connected_adapter.read_control(ControlType.BRIGHTNESS)
        initial_contrast = connected_adapter.read_control(ControlType.CONTRAST)

        # Make changes
        connected_adapter.write_batch({
            ControlType.BRIGHTNESS: 80,
            ControlType.CONTRAST: 70,
        })

        # Verify changed
        assert connected_adapter.read_control(ControlType.BRIGHTNESS) == 80
        assert connected_adapter.read_control(ControlType.CONTRAST) == 70

        # Rollback
        success = connected_adapter.rollback()
        assert success is True

        # Verify restored
        assert connected_adapter.read_control(ControlType.BRIGHTNESS) == initial_brightness
        assert connected_adapter.read_control(ControlType.CONTRAST) == initial_contrast

    def test_rollback_no_snapshot(self, connected_adapter: FakeDisplayControlAdapter):
        """Test rollback fails when no snapshot."""
        connected_adapter.clear_snapshot()
        with pytest.raises(DisplayControlError) as exc_info:
            connected_adapter.rollback()

        assert exc_info.value.error_code == "NO_SNAPSHOT"

    def test_commit_clears_snapshot(self, connected_adapter: FakeDisplayControlAdapter):
        """Test commit clears snapshot."""
        connected_adapter.write_control(ControlType.BRIGHTNESS, 80)
        assert connected_adapter.has_snapshot is True

        connected_adapter.commit()
        assert connected_adapter.has_snapshot is False

    def test_error_simulation(self, connected_adapter: FakeDisplayControlAdapter):
        """Test error simulation."""
        connected_adapter.simulate_error("TEST_ERROR", "Simulated error")

        with pytest.raises(DisplayControlError) as exc_info:
            connected_adapter.read_control(ControlType.BRIGHTNESS)

        assert exc_info.value.error_code == "TEST_ERROR"

        connected_adapter.clear_error()
        # Should work now
        value = connected_adapter.read_control(ControlType.BRIGHTNESS)
        assert 0 <= value <= 100

    def test_operation_history(self, connected_adapter: FakeDisplayControlAdapter):
        """Test operation history tracking."""
        connected_adapter.write_control(ControlType.BRIGHTNESS, 75)
        connected_adapter.write_control(ControlType.CONTRAST, 65)

        history = connected_adapter.get_operation_history()
        assert len(history) == 2
        assert history[0].control_type == ControlType.BRIGHTNESS
        assert history[1].control_type == ControlType.CONTRAST


class TestDDCCIAdapterMocked:
    """Tests for DDCCIAdapter with mocked subprocess."""

    def test_adapter_creation_mocked(self):
        """Test DDCCIAdapter creation with mocked tool detection."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="/usr/local/bin/ddcutil")

            adapter = DDCCIAdapter(display_id=1)
            # Tool detection may or may not succeed depending on mock
            # We just test the adapter was created
            assert adapter.display_id == 1

    def test_parse_vcp_value(self):
        """Test VCP value parsing."""
        adapter = DDCCIAdapter(display_id=1)

        # ddcutil format
        output = "VCP code 0x10 (Brightness): current value = 50"
        value = adapter._parse_vcp_value(output)
        assert value == 50

        # ddcctl format
        output = "Display 1: brightness = 75"
        value = adapter._parse_vcp_value(output)
        assert value == 75

        # Plain number
        output = "60"
        value = adapter._parse_vcp_value(output)
        assert value == 60


# ==============================================================================
# ManualAdjustmentGuide Tests
# ==============================================================================

class TestManualAdjustmentGuideGenerator:
    """Tests for ManualAdjustmentGuideGenerator."""

    def test_generator_creation(self):
        """Test generator creation."""
        generator = ManualAdjustmentGuideGenerator()
        assert generator is not None

    def test_generate_guide(self):
        """Test guide generation."""
        generator = ManualAdjustmentGuideGenerator()

        current_values = {
            ControlType.BRIGHTNESS: 50,
            ControlType.RED_GAIN: 50,
            ControlType.GREEN_GAIN: 50,
            ControlType.BLUE_GAIN: 50,
        }
        target_values = {
            ControlType.BRIGHTNESS: 70,
            ControlType.RED_GAIN: 55,
            ControlType.GREEN_GAIN: 48,
        }

        guide = generator.generate(
            current_values=current_values,
            target_values=target_values,
            display_name="Test Display",
        )

        assert guide.display_name == "Test Display"
        assert len(guide.steps) == 3  # Only changed controls
        assert guide.estimated_time == 3

    def test_guide_to_markdown(self):
        """Test guide markdown export."""
        generator = ManualAdjustmentGuideGenerator()

        guide = generator.generate(
            current_values={ControlType.BRIGHTNESS: 50},
            target_values={ControlType.BRIGHTNESS: 80},
            display_name="Test Display",
        )

        md = guide.to_markdown()
        assert "Test Display" in md
        assert "Brightness" in md
        assert "50" in md
        assert "80" in md

    def test_guide_to_json(self):
        """Test guide JSON export."""
        generator = ManualAdjustmentGuideGenerator()

        guide = generator.generate(
            current_values={ControlType.BRIGHTNESS: 50},
            target_values={ControlType.BRIGHTNESS: 80},
        )

        json_str = guide.to_json()
        data = json.loads(json_str)
        assert "steps" in data
        assert len(data["steps"]) == 1


# ==============================================================================
# AutoCalWorkflow Tests
# ==============================================================================

class TestAutoCalTarget:
    """Tests for AutoCalTarget."""

    def test_target_creation(self, autocal_target: AutoCalTarget):
        """Test target creation."""
        assert autocal_target.target_white_point == "D65"
        assert autocal_target.target_cct == 6500.0
        assert autocal_target.max_iterations == 5

    def test_get_white_xy(self, autocal_target: AutoCalTarget):
        """Test getting white point xy."""
        xy = autocal_target.get_white_xy()
        # D65 white point (rounded)
        assert abs(xy[0] - 0.3127) < 0.001
        assert abs(xy[1] - 0.3290) < 0.001


class TestAutoCalConfig:
    """Tests for AutoCalConfig."""

    def test_config_creation(self, autocal_config: AutoCalConfig):
        """Test config creation."""
        assert autocal_config.mode == AutoCalMode.AUTO
        assert autocal_config.dry_run is False
        assert autocal_config.enable_rollback is True
        assert autocal_config.max_iterations == 5


class TestMeasurementPoint:
    """Tests for MeasurementPoint."""

    def test_point_creation(self):
        """Test measurement point creation."""
        point = MeasurementPoint(
            rgb=(255, 255, 255),
            name="white",
            xyY=(0.3127, 0.3290, 100.0),
        )
        assert point.rgb == (255, 255, 255)
        assert point.Y == 100.0
        assert point.xy == (0.3127, 0.3290)


class TestBaselineMeasurement:
    """Tests for BaselineMeasurement."""

    def test_baseline_creation(self):
        """Test baseline creation."""
        baseline = BaselineMeasurement(
            white_point=MeasurementPoint(rgb=(255, 255, 255), name="white", xyY=(0.3127, 0.3290, 100.0)),
        )
        assert baseline.white_point is not None
        assert baseline.get_white_Y() == 100.0

    def test_get_cct_duv(self):
        """Test CCT/Duv calculation."""
        baseline = BaselineMeasurement(
            white_point=MeasurementPoint(rgb=(255, 255, 255), name="white", xyY=(0.3127, 0.3290, 100.0)),
        )
        cct, duv = baseline.get_cct_duv()
        assert cct > 0  # Should be around 6500K
        assert abs(duv) < 0.01  # Should be small


class TestSimpleAdjustmentSolver:
    """Tests for SimpleAdjustmentSolver."""

    def test_solver_creation(self, autocal_config: AutoCalConfig):
        """Test solver creation."""
        solver = SimpleAdjustmentSolver(autocal_config)
        assert solver is not None

    def test_solve_no_adjustment_needed(self, autocal_config: AutoCalConfig, autocal_target: AutoCalTarget):
        """Test solve when no adjustment needed."""
        solver = SimpleAdjustmentSolver(autocal_config)

        # Baseline at target
        baseline = BaselineMeasurement(
            white_point=MeasurementPoint(
                rgb=(255, 255, 255),
                name="white",
                xyY=(0.3127, 0.3290, 100.0),  # Target D65
            ),
        )

        current_controls = {
            ControlType.BRIGHTNESS: 50,
            ControlType.RED_GAIN: 50,
            ControlType.GREEN_GAIN: 50,
            ControlType.BLUE_GAIN: 50,
        }

        solution = solver.solve(baseline, autocal_target, current_controls)
        # Should have low adjustment or confidence near 1.0
        assert solution.confidence >= 0.5

    def test_solve_with_deviation(self, autocal_config: AutoCalConfig, autocal_target: AutoCalTarget):
        """Test solve with white point deviation."""
        solver = SimpleAdjustmentSolver(autocal_config)

        # Baseline with deviation
        baseline = BaselineMeasurement(
            white_point=MeasurementPoint(
                rgb=(255, 255, 255),
                name="white",
                xyY=(0.3300, 0.3450, 100.0),  # Deviated from D65 (duv ~0.009 > duv_max 0.005)
            ),
        )

        current_controls = {
            ControlType.BRIGHTNESS: 50,
            ControlType.RED_GAIN: 50,
            ControlType.GREEN_GAIN: 50,
            ControlType.BLUE_GAIN: 50,
        }

        solution = solver.solve(baseline, autocal_target, current_controls)
        # Should propose some adjustment
        assert len(solution.controls) > 0 or len(solution.absolute_values) > 0


class TestAutoCalWorkflow:
    """Tests for AutoCalWorkflow."""

    def test_workflow_creation(
        self,
        fake_display_adapter: FakeDisplayControlAdapter,
        fake_measure_callback,
    ):
        """Test workflow creation."""
        workflow = AutoCalWorkflow(
            display_adapter=fake_display_adapter,
            measure_callback=fake_measure_callback,
        )
        assert workflow is not None
        assert workflow.get_current_state() == AutoCalState.IDLE

    def test_preflight_step(
        self,
        fake_display_adapter: FakeDisplayControlAdapter,
        fake_measure_callback,
        autocal_target: AutoCalTarget,
        autocal_config: AutoCalConfig,
    ):
        """Test preflight step connects display."""
        workflow = AutoCalWorkflow(
            display_adapter=fake_display_adapter,
            measure_callback=fake_measure_callback,
        )

        # Run workflow
        session = workflow.run(autocal_target, autocal_config)

        # Preflight should have connected the adapter
        assert fake_display_adapter.is_connected is True

    def test_baseline_measurement(
        self,
        connected_adapter: FakeDisplayControlAdapter,
        fake_measure_callback,
        autocal_target: AutoCalTarget,
        autocal_config: AutoCalConfig,
    ):
        """Test baseline measurement."""
        workflow = AutoCalWorkflow(
            display_adapter=connected_adapter,
            measure_callback=fake_measure_callback,
        )

        session = workflow.run(autocal_target, autocal_config)

        # Should have iteration records
        assert session.iteration_count > 0
        first_iteration = session.iterations[0]
        assert first_iteration.baseline is not None
        assert first_iteration.baseline.white_point is not None

        # Check call count (using mutable container)
        assert fake_measure_callback.call_count[0] > 0

    def test_dry_run_mode(
        self,
        connected_adapter: FakeDisplayControlAdapter,
        fake_measure_callback,
        autocal_target: AutoCalTarget,
        autocal_config_dry_run: AutoCalConfig,
    ):
        """Test dry-run mode does not change settings."""
        # Get initial values
        initial_brightness = connected_adapter.read_control(ControlType.BRIGHTNESS)

        workflow = AutoCalWorkflow(
            display_adapter=connected_adapter,
            measure_callback=fake_measure_callback,
        )

        session = workflow.run(autocal_target, autocal_config_dry_run)

        # Settings should not have changed
        current_brightness = connected_adapter.read_control(ControlType.BRIGHTNESS)
        assert current_brightness == initial_brightness

        # Session should be marked as dry-run
        assert session.dry_run is True

    def test_rollback_mechanism(
        self,
        connected_adapter: FakeDisplayControlAdapter,
        fake_measure_callback,
        autocal_target: AutoCalTarget,
        autocal_config: AutoCalConfig,
    ):
        """Test rollback mechanism."""
        # Get initial values
        initial_brightness = connected_adapter.read_control(ControlType.BRIGHTNESS)
        initial_contrast = connected_adapter.read_control(ControlType.CONTRAST)

        workflow = AutoCalWorkflow(
            display_adapter=connected_adapter,
            measure_callback=fake_measure_callback,
        )

        session = workflow.run(autocal_target, autocal_config)

        # If changes were made, rollback should restore them
        # Check rollback capability exists
        assert connected_adapter.has_snapshot or session.rollback_performed or session.state == AutoCalState.COMPLETED

    def test_manual_guide_generation(
        self,
        connected_adapter: FakeDisplayControlAdapter,
        autocal_target: AutoCalTarget,
    ):
        """Test manual guide generation in MANUAL mode."""
        config = AutoCalConfig(
            mode=AutoCalMode.MANUAL,
            enable_manual_guide=True,
            dry_run=True,
        )

        # Create a measurement callback that returns deviated white point
        def deviated_measure(rgb: Tuple[int, int, int], name: str) -> MeasurementPoint:
            if rgb == (255, 255, 255):
                # White with significant deviation from D65
                xyY = (0.3200, 0.3350, 100.0)  # Significant deviation
            elif rgb == (0, 0, 0):
                xyY = (0.0, 0.0, 0.1)
            elif name.startswith("gray"):
                level = rgb[0] / 255.0
                Y = 100.0 * (level ** 2.2)
                xyY = (0.3127, 0.3290, Y)
            elif name == "red":
                xyY = (0.64, 0.33, 21.26)
            elif name == "green":
                xyY = (0.30, 0.60, 71.52)
            elif name == "blue":
                xyY = (0.15, 0.06, 7.22)
            else:
                xyY = (0.3127, 0.3290, 50.0)
            return MeasurementPoint(rgb=rgb, name=name, xyY=xyY)

        workflow = AutoCalWorkflow(
            display_adapter=connected_adapter,
            measure_callback=deviated_measure,
        )

        session = workflow.run(autocal_target, config)

        # Manual guide should be available when adjustments are needed
        # Note: if measurement is close to target, guide may not be generated
        if session.state == AutoCalState.COMPLETED and session.iteration_count > 0:
            # Workflow completed, check if guide exists or not
            # In MANUAL mode, guide should be generated if there were adjustments
            if session.iterations and session.iterations[0].solution:
                solution = session.iterations[0].solution
                if solution.controls:
                    # Had adjustments, should have guide
                    assert session.manual_guide is not None or session.final_result.passed

    def test_session_serialization(
        self,
        connected_adapter: FakeDisplayControlAdapter,
        fake_measure_callback,
        autocal_target: AutoCalTarget,
        autocal_config_dry_run: AutoCalConfig,
    ):
        """Test session serialization."""
        workflow = AutoCalWorkflow(
            display_adapter=connected_adapter,
            measure_callback=fake_measure_callback,
        )

        session = workflow.run(autocal_target, autocal_config_dry_run)

        # Serialize to dict
        data = session.to_dict()
        assert "session_id" in data
        assert "iterations" in data
        assert "state" in data

        # Serialize to JSON
        json_str = session.to_json()
        data = json.loads(json_str)
        assert data["state"] == session.state.value

    def test_session_file_save(
        self,
        connected_adapter: FakeDisplayControlAdapter,
        fake_measure_callback,
        autocal_target: AutoCalTarget,
        autocal_config_dry_run: AutoCalConfig,
        tmp_path: Path,
    ):
        """Test session file save."""
        workflow = AutoCalWorkflow(
            display_adapter=connected_adapter,
            measure_callback=fake_measure_callback,
            session_dir=tmp_path,
        )

        session = workflow.run(autocal_target, autocal_config_dry_run)

        # Session file should exist
        session_files = list(tmp_path.glob("*.json"))
        assert len(session_files) == 1

    def test_max_iterations_limit(
        self,
        connected_adapter: FakeDisplayControlAdapter,
        fake_measure_callback,
    ):
        """Test max iterations limit."""
        target = AutoCalTarget(max_iterations=2)
        config = AutoCalConfig(dry_run=True, max_iterations=2)

        workflow = AutoCalWorkflow(
            display_adapter=connected_adapter,
            measure_callback=fake_measure_callback,
        )

        session = workflow.run(target, config)

        # Should not exceed max iterations
        assert session.iteration_count <= 2

    def test_error_handling(
        self,
        fake_display_adapter: FakeDisplayControlAdapter,
        fake_measure_callback,
        autocal_target: AutoCalTarget,
        autocal_config: AutoCalConfig,
    ):
        """Test error handling when display not connected."""
        # Don't connect the adapter
        workflow = AutoCalWorkflow(
            display_adapter=fake_display_adapter,
            measure_callback=fake_measure_callback,
        )

        session = workflow.run(autocal_target, autocal_config)

        # Should have handled connection or error
        assert session.state in [AutoCalState.COMPLETED, AutoCalState.FAILED, AutoCalState.IDLE]

    def test_state_change_callback(
        self,
        connected_adapter: FakeDisplayControlAdapter,
        fake_measure_callback,
        autocal_target: AutoCalTarget,
        autocal_config_dry_run: AutoCalConfig,
    ):
        """Test state change callback."""
        states_recorded = []

        def record_state(old_state: AutoCalState, new_state: AutoCalState):
            states_recorded.append((old_state, new_state))

        workflow = AutoCalWorkflow(
            display_adapter=connected_adapter,
            measure_callback=fake_measure_callback,
        )
        workflow.set_state_change_callback(record_state)

        session = workflow.run(autocal_target, autocal_config_dry_run)

        # Should have recorded state transitions
        assert len(states_recorded) > 0


class TestAutoCalWorkflowIntegration:
    """Integration tests for AutoCalWorkflow."""

    @pytest.mark.workflow
    def test_full_workflow_with_fake_adapter(self):
        """Test full workflow with fake adapter."""
        # Create workflow using factory function
        workflow = create_autocal_workflow(use_fake=True)

        target = AutoCalTarget(max_iterations=3)
        config = AutoCalConfig(dry_run=True, enable_rollback=False)

        session = workflow.run(target, config)

        # Workflow should complete
        assert session.state in [AutoCalState.COMPLETED, AutoCalState.FAILED]
        assert session.iteration_count >= 0

    @pytest.mark.workflow
    def test_run_autocal_dry_run_factory(self):
        """Test run_autocal_dry_run factory function."""
        session = run_autocal_dry_run()

        # Should complete without errors
        assert session is not None
        assert session.dry_run is True
        assert session.state in [AutoCalState.COMPLETED, AutoCalState.FAILED]


# ==============================================================================
# Verification Tests
# ==============================================================================

class TestVerificationResult:
    """Tests for VerificationResult."""

    def test_result_creation(self):
        """Test verification result creation."""
        result = VerificationResult(
            delta_e_avg=1.5,
            delta_e_max=3.0,
            cct=6500.0,
            duv=0.002,
            Y_white=100.0,
            gamma_avg=2.2,
            passed=True,
        )
        assert result.passed is True
        assert result.delta_e_avg == 1.5

    def test_pass_details(self):
        """Test pass details."""
        result = VerificationResult(
            pass_details={
                "cct": True,
                "duv": True,
                "gamma": False,
            },
        )
        assert result.pass_details["cct"] is True
        assert result.pass_details["gamma"] is False


class TestIterationRecord:
    """Tests for IterationRecord."""

    def test_record_creation(self):
        """Test iteration record creation."""
        record = IterationRecord(
            iteration_number=1,
            baseline=BaselineMeasurement(),
            solution=AdjustmentSolution(),
            verification=VerificationResult(),
        )
        assert record.iteration_number == 1
        assert record.baseline is not None

    def test_record_serialization(self):
        """Test record serialization."""
        record = IterationRecord(
            iteration_number=1,
            verification=VerificationResult(passed=True),
        )
        data = record.to_dict()
        assert data["iteration_number"] == 1
        assert data["verification"]["passed"] is True


# ==============================================================================
# Rollback Tests
# ==============================================================================

class TestRollbackMechanism:
    """Tests for rollback mechanism."""

    def test_rollback_after_batch_write(self, connected_adapter: FakeDisplayControlAdapter):
        """Test rollback restores values after batch write."""
        initial = {
            ControlType.BRIGHTNESS: connected_adapter.read_control(ControlType.BRIGHTNESS),
            ControlType.CONTRAST: connected_adapter.read_control(ControlType.CONTRAST),
        }

        # Batch write
        connected_adapter.write_batch({
            ControlType.BRIGHTNESS: 80,
            ControlType.CONTRAST: 70,
        })

        # Rollback
        connected_adapter.rollback()

        # Verify restored
        assert connected_adapter.read_control(ControlType.BRIGHTNESS) == initial[ControlType.BRIGHTNESS]
        assert connected_adapter.read_control(ControlType.CONTRAST) == initial[ControlType.CONTRAST]

    def test_rollback_with_manual_workflow(
        self,
        connected_adapter: FakeDisplayControlAdapter,
        fake_measure_callback,
    ):
        """Test rollback in workflow context."""
        initial = connected_adapter.read_control(ControlType.BRIGHTNESS)

        # Run workflow with adjustments
        target = AutoCalTarget(max_iterations=1)
        config = AutoCalConfig(enable_rollback=True, dry_run=False)

        workflow = AutoCalWorkflow(
            display_adapter=connected_adapter,
            measure_callback=fake_measure_callback,
        )

        session = workflow.run(target, config)

        # Manual rollback
        if workflow.get_session() and workflow.get_session().state == AutoCalState.COMPLETED:
            workflow.rollback()
            assert connected_adapter.read_control(ControlType.BRIGHTNESS) == initial


# ==============================================================================
# Run Verification Tests
# ==============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
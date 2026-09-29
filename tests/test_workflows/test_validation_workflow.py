"""
Tests for Validation Workflow (P4-D).

These tests verify:
- MeasurementType enum (baseline, after_calibration, verification)
- ValidationThreshold and standard threshold presets
- VerificationPatchGenerator (independent patch generation)
- ValidationRun and ValidationSession (multi-run support)
- BeforeAfterComparison (before/after comparison)
- ValidationWorkflowService (workflow orchestration)
- Validation analysis functions in measurement_analyzer

Key principles tested:
- Verification patches are independent from modeling patches
- Verification data cannot overwrite modeling data
- sRGB/Rec.709 has default pass thresholds
- Multiple runs supported per display/session

Reference: docs/agent_handoffs/P4-D_validation_workflow.md
"""

import pytest
from datetime import datetime
from typing import Tuple, List, Dict
from unittest.mock import MagicMock

from src.workflows.validation_workflow import (
    MeasurementType,
    ValidationStatus,
    ValidationThreshold,
    STANDARD_THRESHOLDS,
    get_threshold_for_standard,
    VerificationPatchConfig,
    VerificationPatchGenerator,
    MeasurementPoint,
    ValidationRun,
    ValidationSession,
    BeforeAfterComparison,
    ValidationWorkflowService,
    calculate_target_xyY_for_rgb,
)

from src.measurement_analyzer import (
    calculate_validation_delta_e_statistics,
    compare_before_after_metrics,
    generate_validation_report,
)


# ========== Fixtures ==========

@pytest.fixture
def srgb_threshold() -> ValidationThreshold:
    """Get sRGB validation threshold."""
    return STANDARD_THRESHOLDS["sRGB"]


@pytest.fixture
def verification_config() -> VerificationPatchConfig:
    """Create verification patch config."""
    return VerificationPatchConfig(
        count=50,
        include_grayscale=True,
        include_primary_secondary=True,
        include_skin_tones=True,
        seed=42  # Fixed seed for reproducibility
    )


@pytest.fixture
def sample_gamut_data() -> Dict[str, MeasurementPoint]:
    """Create sample gamut measurement data."""
    return {
        "red": MeasurementPoint(
            rgb=(255, 0, 0),
            name="Red",
            xyz=(41.24, 21.26, 1.93),
            xyY=(0.64, 0.33, 21.26),
            measurement_type=MeasurementType.VERIFICATION,
        ),
        "green": MeasurementPoint(
            rgb=(0, 255, 0),
            name="Green",
            xyz=(13.75, 68.10, 1.05),
            xyY=(0.30, 0.60, 68.10),
            measurement_type=MeasurementType.VERIFICATION,
        ),
        "blue": MeasurementPoint(
            rgb=(0, 0, 255),
            name="Blue",
            xyz=(7.66, 2.57, 95.46),
            xyY=(0.15, 0.06, 2.57),
            measurement_type=MeasurementType.VERIFICATION,
        ),
        "white": MeasurementPoint(
            rgb=(255, 255, 255),
            name="White",
            xyz=(95.05, 100.00, 108.88),
            xyY=(0.3127, 0.3290, 100.00),
            measurement_type=MeasurementType.VERIFICATION,
        ),
        "black": MeasurementPoint(
            rgb=(0, 0, 0),
            name="Black",
            xyz=(0.0, 0.05, 0.0),
            xyY=(0.0, 0.0, 0.05),
            measurement_type=MeasurementType.VERIFICATION,
        ),
    }


@pytest.fixture
def sample_verification_points() -> List[MeasurementPoint]:
    """Create sample verification measurement points with Delta E."""
    points = []
    # Good points (Delta E < 2)
    for i in range(30):
        points.append(MeasurementPoint(
            rgb=(100 + i * 5, 100 + i * 5, 100 + i * 5),
            name=f"Gray_{i}",
            xyz=(50.0, 50.0, 50.0),
            xyY=(0.3127, 0.3290, 50.0),
            delta_e=0.5 + i * 0.03,  # Range 0.5 - 1.4
            measurement_type=MeasurementType.VERIFICATION,
        ))
    # Medium points (Delta E 2-4)
    for i in range(15):
        points.append(MeasurementPoint(
            rgb=(200, 50 + i * 10, 50),
            name=f"Color_{i}",
            xyz=(60.0, 30.0, 20.0),
            xyY=(0.45, 0.25, 30.0),
            delta_e=2.5 + i * 0.1,  # Range 2.5 - 3.9
            measurement_type=MeasurementType.VERIFICATION,
        ))
    # Poor points (Delta E > 4)
    for i in range(5):
        points.append(MeasurementPoint(
            rgb=(255, 0, 100 + i * 20),
            name=f"Problem_{i}",
            xyz=(80.0, 10.0, 30.0),
            xyY=(0.60, 0.10, 10.0),
            delta_e=5.0 + i * 0.5,  # Range 5.0 - 7.5
            measurement_type=MeasurementType.VERIFICATION,
        ))
    return points


@pytest.fixture
def validation_service() -> ValidationWorkflowService:
    """Create validation workflow service."""
    return ValidationWorkflowService(target_standard="sRGB")


# ========== MeasurementType Tests ==========

class TestMeasurementType:
    """Tests for MeasurementType enum."""

    def test_measurement_types_defined(self):
        """Test that all measurement types are defined."""
        assert MeasurementType.BASELINE.value == "baseline"
        assert MeasurementType.AFTER_CALIBRATION.value == "after_calibration"
        assert MeasurementType.VERIFICATION.value == "verification"

    def test_measurement_type_distinction(self):
        """Test that measurement types are distinct."""
        types = [MeasurementType.BASELINE, MeasurementType.AFTER_CALIBRATION, MeasurementType.VERIFICATION]
        assert len(set(types)) == 3


# ========== ValidationThreshold Tests ==========

class TestValidationThreshold:
    """Tests for validation thresholds."""

    def test_srgb_threshold_default(self, srgb_threshold: ValidationThreshold):
        """Test sRGB default threshold values."""
        assert srgb_threshold.delta_e_avg_threshold == 2.0
        assert srgb_threshold.delta_e_max_threshold == 6.0
        assert srgb_threshold.white_point_cct_tolerance == 200.0
        assert srgb_threshold.white_point_duv_tolerance == 0.005
        assert srgb_threshold.gamma_tolerance == 0.05
        assert srgb_threshold.gamut_coverage_threshold == 95.0

    def test_rec709_threshold_same_as_srgb(self):
        """Test Rec.709 threshold is same as sRGB."""
        rec709_threshold = STANDARD_THRESHOLDS["Rec.709"]
        assert rec709_threshold.delta_e_avg_threshold == 2.0
        assert rec709_threshold.delta_e_max_threshold == 6.0
        assert rec709_threshold.gamut_coverage_threshold == 95.0

    def test_get_threshold_for_standard(self):
        """Test getting threshold for standard."""
        threshold = get_threshold_for_standard("sRGB")
        assert threshold.delta_e_avg_threshold == 2.0

        threshold = get_threshold_for_standard("DCI-P3")
        assert threshold.delta_e_avg_threshold == 3.0

    def test_unknown_standard_returns_default(self):
        """Test unknown standard returns sRGB threshold."""
        threshold = get_threshold_for_standard("Unknown")
        assert threshold.delta_e_avg_threshold == 2.0

    def test_delta_e_pass_check(self, srgb_threshold: ValidationThreshold):
        """Test Delta E pass/fail check."""
        passed, reason = srgb_threshold.is_delta_e_passed(1.5, 3.0)
        assert passed == True

        passed, reason = srgb_threshold.is_delta_e_passed(3.0, 8.0)
        assert passed == False

    def test_white_point_pass_check(self, srgb_threshold: ValidationThreshold):
        """Test white point pass/fail check."""
        passed, reason = srgb_threshold.is_white_point_passed(100.0, 0.002)
        assert passed == True

        passed, reason = srgb_threshold.is_white_point_passed(500.0, 0.01)
        assert passed == False

    def test_gamma_pass_check(self, srgb_threshold: ValidationThreshold):
        """Test gamma pass/fail check."""
        passed, reason = srgb_threshold.is_gamma_passed(0.02)
        assert passed == True

        passed, reason = srgb_threshold.is_gamma_passed(0.1)
        assert passed == False

    def test_gamut_pass_check(self, srgb_threshold: ValidationThreshold):
        """Test gamut pass/fail check."""
        passed, reason = srgb_threshold.is_gamut_passed(98.0, 102.0)
        assert passed == True

        passed, reason = srgb_threshold.is_gamut_passed(85.0, 90.0)
        assert passed == False


# ========== VerificationPatchGenerator Tests ==========

class TestVerificationPatchGenerator:
    """Tests for verification patch generator."""

    def test_generate_patches(self, verification_config: VerificationPatchConfig):
        """Test generating verification patches."""
        generator = VerificationPatchGenerator(verification_config)
        patches = generator.generate()

        assert len(patches) > 0
        assert len(patches) <= verification_config.count + 20  # Allow extra for grayscale

    def test_patches_independent_from_modeling(self):
        """Test that verification patches are independent from modeling."""
        # Model patches
        model_patches = [
            (255, 0, 0, "R"),
            (0, 255, 0, "G"),
            (0, 0, 255, "B"),
            (255, 255, 255, "W"),
            (0, 0, 0, "K"),
        ]

        config = VerificationPatchConfig(count=20, seed=42)
        generator = VerificationPatchGenerator(config)
        patches = generator.generate(model_patches)

        # Check that verification patches don't overlap with model patches
        model_rgb_set = {(p[0], p[1], p[2]) for p in model_patches}

        for patch in patches:
            rgb = (patch[0], patch[1], patch[2])
            # Allow small tolerance for grayscale overlap
            if rgb != (255, 255, 255) and rgb != (0, 0, 0):
                assert rgb not in model_rgb_set or abs(patch[0] - patch[1]) > 3

    def test_includes_grayscale(self, verification_config: VerificationPatchConfig):
        """Test that grayscale patches are included."""
        generator = VerificationPatchGenerator(verification_config)
        patches = generator.generate()

        # Check for grayscale patches
        grayscale_found = False
        for patch in patches:
            if patch[0] == patch[1] == patch[2]:
                grayscale_found = True
                break

        assert grayscale_found == True

    def test_includes_primary_colors(self, verification_config: VerificationPatchConfig):
        """Test that primary colors are included."""
        generator = VerificationPatchGenerator(verification_config)
        patches = generator.generate()

        # Check for primary colors
        primary_found = False
        for patch in patches:
            name = patch[3].lower()
            if "red" in name or "green" in name or "blue" in name:
                primary_found = True
                break

        assert primary_found == True

    def test_reproducible_with_seed(self):
        """Test that patches are reproducible with same seed."""
        config1 = VerificationPatchConfig(count=30, seed=42)
        config2 = VerificationPatchConfig(count=30, seed=42)

        generator1 = VerificationPatchGenerator(config1)
        generator2 = VerificationPatchGenerator(config2)

        patches1 = generator1.generate()
        patches2 = generator2.generate()

        # First few patches should be identical
        for i in range(min(10, len(patches1), len(patches2))):
            assert patches1[i][0:3] == patches2[i][0:3]


# ========== ValidationRun Tests ==========

class TestValidationRun:
    """Tests for validation run."""

    def test_create_run(self):
        """Test creating a validation run."""
        run = ValidationRun(
            run_id="test_run_001",
            measurement_type=MeasurementType.VERIFICATION,
            target_standard="sRGB",
        )

        assert run.run_id == "test_run_001"
        assert run.measurement_type == MeasurementType.VERIFICATION
        assert run.status == ValidationStatus.PENDING

    def test_add_gamut_data(
        self,
        sample_gamut_data: Dict[str, MeasurementPoint]
    ):
        """Test adding gamut data to run."""
        run = ValidationRun()
        run.gamut_data = sample_gamut_data

        assert "red" in run.gamut_data
        assert "green" in run.gamut_data
        assert "blue" in run.gamut_data
        assert "white" in run.gamut_data

    def test_calculate_metrics(
        self,
        sample_gamut_data: Dict[str, MeasurementPoint],
        sample_verification_points: List[MeasurementPoint]
    ):
        """Test calculating validation metrics."""
        run = ValidationRun()
        run.gamut_data = sample_gamut_data
        run.verification_points = sample_verification_points

        run.calculate_metrics()

        assert run.delta_e_avg > 0
        assert run.delta_e_max > 0
        assert run.peak_luminance == 100.0
        assert run.black_luminance == 0.05

    def test_validate_and_get_status(
        self,
        sample_gamut_data: Dict[str, MeasurementPoint],
        sample_verification_points: List[MeasurementPoint]
    ):
        """Test validation and status determination."""
        run = ValidationRun()
        run.gamut_data = sample_gamut_data
        run.verification_points = sample_verification_points
        run.gamma_estimate = 2.22

        status, result = run.validate()

        # Check status
        assert status in [ValidationStatus.PASSED, ValidationStatus.WARNING, ValidationStatus.FAILED]
        assert run.status == status
        assert run.completed_at is not None

        # Check result structure
        assert "delta_e" in result
        assert "white_point" in result
        assert "overall" in result


# ========== ValidationSession Tests ==========

class TestValidationSession:
    """Tests for validation session."""

    def test_create_session(self):
        """Test creating a validation session."""
        session = ValidationSession(
            session_id="test_session_001",
            display_id=0,
            display_name="Test Display",
            target_standard="sRGB",
        )

        assert session.session_id == "test_session_001"
        assert session.display_id == 0
        assert session.target_standard == "sRGB"

    def test_add_multiple_runs(self):
        """Test adding multiple runs to session."""
        session = ValidationSession()

        # Add baseline run
        baseline_run = ValidationRun(
            run_id="baseline_001",
            measurement_type=MeasurementType.BASELINE,
        )
        session.add_run(baseline_run)

        # Add after calibration run
        after_run = ValidationRun(
            run_id="after_001",
            measurement_type=MeasurementType.AFTER_CALIBRATION,
        )
        session.add_run(after_run)

        # Add verification run
        verify_run = ValidationRun(
            run_id="verify_001",
            measurement_type=MeasurementType.VERIFICATION,
        )
        session.add_run(verify_run)

        assert len(session.all_runs) == 3
        assert session.baseline_run == baseline_run
        assert len(session.calibration_runs) == 1
        assert len(session.verification_runs) == 1

    def test_run_numbers_assigned(self):
        """Test that run numbers are assigned."""
        session = ValidationSession()

        for i in range(3):
            run = ValidationRun(measurement_type=MeasurementType.VERIFICATION)
            session.add_run(run)
            assert run.run_number == i + 1

    def test_get_latest_runs(self):
        """Test getting latest runs."""
        session = ValidationSession()

        # Add runs
        session.add_run(ValidationRun(measurement_type=MeasurementType.BASELINE))
        session.add_run(ValidationRun(measurement_type=MeasurementType.AFTER_CALIBRATION))
        session.add_run(ValidationRun(measurement_type=MeasurementType.AFTER_CALIBRATION))
        session.add_run(ValidationRun(measurement_type=MeasurementType.VERIFICATION))
        session.add_run(ValidationRun(measurement_type=MeasurementType.VERIFICATION))

        latest_cal = session.get_latest_calibration_run()
        latest_verify = session.get_latest_verification_run()

        assert latest_cal is not None
        assert latest_verify is not None


# ========== BeforeAfterComparison Tests ==========

class TestBeforeAfterComparison:
    """Tests for before/after comparison."""

    def test_compare_runs(
        self,
        sample_gamut_data: Dict[str, MeasurementPoint],
        sample_verification_points: List[MeasurementPoint]
    ):
        """Test comparing before and after runs."""
        # Before run (poor performance)
        before_run = ValidationRun()
        before_run.gamut_data = sample_gamut_data
        before_run.verification_points = sample_verification_points
        before_run.delta_e_avg = 4.0
        before_run.delta_e_max = 10.0
        before_run.white_point_cct = 7000.0
        before_run.white_point_duv = 0.01
        before_run.gamma_estimate = 2.0
        before_run.gamut_coverage = 85.0
        before_run.peak_luminance = 100.0
        before_run.black_luminance = 0.1

        # After run (good performance)
        after_run = ValidationRun()
        after_run.gamut_data = sample_gamut_data
        after_run.verification_points = sample_verification_points
        after_run.delta_e_avg = 1.5
        after_run.delta_e_max = 4.0
        after_run.white_point_cct = 6500.0
        after_run.white_point_duv = 0.002
        after_run.gamma_estimate = 2.2
        after_run.gamut_coverage = 98.0
        after_run.peak_luminance = 100.0
        after_run.black_luminance = 0.05

        comparison = BeforeAfterComparison(
            before_run=before_run,
            after_run=after_run,
        )

        result = comparison.compare()

        assert "before" in result
        assert "after" in result
        assert "improvement" in result
        assert result["improvement"]["delta_e_improved"] == True
        assert result["improvement"]["white_point_improved"] == True

    def test_comparison_without_runs(self):
        """Test comparison without runs."""
        comparison = BeforeAfterComparison()
        result = comparison.compare()

        assert "error" in result


# ========== ValidationWorkflowService Tests ==========

class TestValidationWorkflowService:
    """Tests for validation workflow service."""

    def test_create_service(self, validation_service: ValidationWorkflowService):
        """Test creating validation service."""
        assert validation_service.target_standard == "sRGB"
        assert validation_service.threshold.delta_e_avg_threshold == 2.0

    def test_create_session(self, validation_service: ValidationWorkflowService):
        """Test creating session."""
        session = validation_service.create_session(
            display_id=0,
            display_name="Test Display",
        )

        assert validation_service.session is not None
        assert session.display_id == 0
        assert session.display_name == "Test Display"

    def test_create_run(self, validation_service: ValidationWorkflowService):
        """Test creating run."""
        run = validation_service.create_run(
            measurement_type=MeasurementType.VERIFICATION
        )

        assert run.measurement_type == MeasurementType.VERIFICATION
        assert run.target_standard == "sRGB"

    def test_set_model_patches(self, validation_service: ValidationWorkflowService):
        """Test setting model patches."""
        model_patches = [
            (255, 0, 0, "R"),
            (0, 255, 0, "G"),
        ]

        validation_service.set_model_patches(model_patches)

        # Generate verification patches
        verify_patches = validation_service.generate_verification_patches()

        # They should be different from model patches
        assert len(verify_patches) > 0

    def test_add_measurement_point(self, validation_service: ValidationWorkflowService):
        """Test adding measurement point."""
        validation_service.create_session(display_id=0, display_name="Test")
        run = validation_service.create_run(MeasurementType.VERIFICATION)

        point = validation_service.add_measurement_point(
            run=run,
            rgb=(255, 255, 255),
            name="White",
            xyz=(95.05, 100.0, 108.88),
            xyY=(0.3127, 0.3290, 100.0),
            is_gamut_point=True,
        )

        assert point.rgb == (255, 255, 255)
        assert "white" in run.gamut_data

    def test_complete_run(self, validation_service: ValidationWorkflowService):
        """Test completing run."""
        validation_service.create_session(display_id=0, display_name="Test")
        run = validation_service.create_run(MeasurementType.VERIFICATION)

        # Add some data
        validation_service.add_measurement_point(
            run=run,
            rgb=(255, 255, 255),
            name="White",
            xyz=(95.05, 100.0, 108.88),
            xyY=(0.3127, 0.3290, 100.0),
            is_gamut_point=True,
        )

        status, result = validation_service.complete_run(run)

        assert status in [ValidationStatus.PASSED, ValidationStatus.WARNING, ValidationStatus.FAILED]
        assert validation_service.session is not None

    def test_export_session_summary(self, validation_service: ValidationWorkflowService):
        """Test exporting session summary."""
        validation_service.create_session(display_id=0, display_name="Test")
        run = validation_service.create_run(MeasurementType.VERIFICATION)
        validation_service.complete_run(run)

        summary = validation_service.export_session_summary()

        assert "session_id" in summary
        assert "display_id" in summary
        assert "target_standard" in summary


# ========== Measurement Analyzer Validation Tests ==========

class TestMeasurementAnalyzerValidation:
    """Tests for validation functions in measurement_analyzer."""

    def test_calculate_delta_e_statistics(self):
        """Test calculating Delta E statistics."""
        verification_points = [
            {"rgb": (100, 100, 100), "name": "Gray1", "xyY": (0.3127, 0.3290, 50.0)},
            {"rgb": (150, 150, 150), "name": "Gray2", "xyY": (0.3127, 0.3290, 75.0)},
            {"rgb": (200, 50, 50), "name": "Color1", "xyY": (0.45, 0.25, 30.0)},
        ]

        stats = calculate_validation_delta_e_statistics(verification_points)

        assert "delta_e_avg" in stats
        assert "delta_e_max" in stats
        assert "delta_e_95" in stats
        assert "passed_count" in stats
        assert "failed_count" in stats

    def test_compare_before_after_metrics(self):
        """Test comparing before/after metrics."""
        before_data = {
            "delta_e_avg": 4.0,
            "white_point": {"duv": 0.01},
            "gamma": 2.0,
            "gamut_coverage": 85.0,
            "contrast_ratio": 800.0,
        }

        after_data = {
            "delta_e_avg": 1.5,
            "white_point": {"duv": 0.002},
            "gamma": 2.2,
            "gamut_coverage": 98.0,
            "contrast_ratio": 1000.0,
        }

        comparison = compare_before_after_metrics(before_data, after_data)

        assert "improvements" in comparison
        assert comparison["improvements"]["delta_e_avg"]["improved"] == True
        assert comparison["overall_improvement_count"] >= 3

    def test_generate_validation_report(self):
        """Test generating validation report."""
        run_data = {
            "verification_points": [
                {"rgb": (100, 100, 100), "name": "Gray1", "xyY": (0.3127, 0.3290, 50.0)},
            ],
            "white_point": {"cct": 6500.0, "duv": 0.002},
            "gamma": 2.2,
            "gamut_coverage": 98.0,
            "peak_luminance": 100.0,
            "black_luminance": 0.05,
        }

        report = generate_validation_report(run_data)

        assert "target_standard" in report
        assert "threshold" in report
        assert "metrics" in report
        assert "validation" in report
        assert "summary" in report
        assert "status" in report["summary"]


# ========== Integration Tests ==========

class TestValidationWorkflowIntegration:
    """Integration tests for complete validation workflow."""

    def test_complete_validation_workflow(self, validation_service: ValidationWorkflowService):
        """Test complete validation workflow."""
        # 1. Create session
        session = validation_service.create_session(
            display_id=0,
            display_name="Test Display",
        )

        # 2. Set model patches
        model_patches = [(255, 0, 0, "R"), (0, 255, 0, "G")]
        validation_service.set_model_patches(model_patches)

        # 3. Create baseline run
        baseline_run = validation_service.create_run(MeasurementType.BASELINE)
        validation_service.add_measurement_point(
            run=baseline_run,
            rgb=(255, 255, 255),
            name="White",
            xyz=(95.05, 100.0, 108.88),
            xyY=(0.3127, 0.3290, 100.0),
            is_gamut_point=True,
        )
        validation_service.complete_run(baseline_run)

        # 4. Create verification run
        verify_run = validation_service.create_run(MeasurementType.VERIFICATION)
        validation_service.add_measurement_point(
            run=verify_run,
            rgb=(255, 255, 255),
            name="White",
            xyz=(95.05, 100.0, 108.88),
            xyY=(0.3127, 0.3290, 100.0),
            is_gamut_point=True,
        )
        validation_service.complete_run(verify_run)

        # 5. Verify session has multiple runs
        assert len(session.all_runs) == 2
        assert session.baseline_run is not None

    def test_threshold_validation(
        self,
        srgb_threshold: ValidationThreshold
    ):
        """Test threshold validation against good/bad data."""
        # Good data should pass
        good_delta_e = srgb_threshold.is_delta_e_passed(1.5, 4.0)
        assert good_delta_e[0] == True

        # Bad data should fail
        bad_delta_e = srgb_threshold.is_delta_e_passed(5.0, 10.0)
        assert bad_delta_e[0] == False
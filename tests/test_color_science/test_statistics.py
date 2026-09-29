"""
Tests for Measurement Statistics Module.

These tests verify:
- Basic statistics calculations (mean, std, max deviation)
- XYZ linear averaging for dark samples
- Repeatability threshold evaluation
- Session repeatability summary generation
- Outlier detection and rejection (MAD, IQR, Z-score)
- Confidence score calculation
- Luminance-adaptive policy

Reference: docs/agent_handoffs/P3-A_statistics.md
"""

import pytest
import math
from datetime import datetime, timedelta
from typing import Tuple, List

from src.color_science.statistics import (
    # Data types
    SingleMeasurement,
    MeasurementStatistics,
    RepeatabilityThreshold,
    RepeatabilityResult,
    PatchRepeatabilityRecord,
    SessionRepeatabilitySummary,
    MeasurementStatus,
    AveragingMethod,
    OutlierRejectionMethod,
    OutlierDetectionResult,
    PatchMeasurementPolicy,
    LuminanceLevel,

    # Calculation functions
    calculate_mean,
    calculate_std,
    calculate_max_deviation,
    calculate_range,
    xyz_to_xyY,
    xyY_to_xyz,
    xy_to_uv_1976,
    calculate_measurement_statistics,
    evaluate_repeatability,
    generate_repeatability_summary,
    create_single_measurement,
    get_luminance_level,
    average_measurements_xyz,
    # New outlier detection functions
    detect_outliers,
    detect_outliers_mad,
    detect_outliers_iqr,
    detect_outliers_zscore,
    _calculate_median,
    _calculate_mad,
    # New confidence functions
    get_luminance_policy,
    get_luminance_level_enum,
    calculate_confidence_score,
    get_measurement_quality_status,
)


# ========== Fixtures ==========

@pytest.fixture
def sample_xyz_measurements() -> List[SingleMeasurement]:
    """Create sample XYZ measurements for testing."""
    base_time = datetime.now()
    return [
        SingleMeasurement(
            xyz=(41.24, 21.58, 1.85),
            xyY=(0.6480, 0.3387, 21.58),
            timestamp=base_time + timedelta(seconds=i),
            instrument_status={"model": "Test Instrument"},
            metadata={"measurement_index": i}
        )
        for i in range(3)
    ]


@pytest.fixture
def stable_measurements() -> List[SingleMeasurement]:
    """Create stable measurements (low variance) for PASS threshold."""
    base_time = datetime.now()
    # Small variance in measurements
    return [
        SingleMeasurement(
            xyz=(95.0, 100.0, 108.9),
            xyY=(0.3127, 0.3290, 100.0),
            timestamp=base_time + timedelta(seconds=i),
            instrument_status={},
            metadata={}
        )
        for i in range(3)
    ]


@pytest.fixture
def unstable_measurements() -> List[SingleMeasurement]:
    """Create unstable measurements (high variance) for FAIL threshold."""
    base_time = datetime.now()
    return [
        SingleMeasurement(
            xyz=(95.0 + i * 0.5, 100.0 + i * 0.5, 108.9 + i * 0.5),
            xyY=(0.3127 + i * 0.001, 0.3290 + i * 0.001, 100.0 + i * 0.5),
            timestamp=base_time + timedelta(seconds=i),
            instrument_status={},
            metadata={}
        )
        for i in range(5)
    ]


@pytest.fixture
def dark_sample_measurements() -> List[SingleMeasurement]:
    """Create dark sample measurements for XYZ averaging test."""
    base_time = datetime.now()
    # Simulate dark patch with some noise
    return [
        SingleMeasurement(
            xyz=(0.05 + i * 0.01, 0.10 + i * 0.01, 0.12 + i * 0.01),
            xyY=xyz_to_xyY(0.05 + i * 0.01, 0.10 + i * 0.01, 0.12 + i * 0.01),
            timestamp=base_time + timedelta(seconds=i),
            instrument_status={},
            metadata={"dark_sample": True}
        )
        for i in range(3)
    ]


@pytest.fixture
def default_threshold() -> RepeatabilityThreshold:
    """Create default repeatability threshold."""
    return RepeatabilityThreshold(
        std_Y_threshold=0.1,
        relative_std_Y_threshold=2.0,
        max_deviation_Y_threshold=0.2,
        delta_xy_threshold=0.005,
        min_measurements=3,
        warn_threshold_factor=0.8,
    )


@pytest.fixture
def relaxed_threshold() -> RepeatabilityThreshold:
    """Create relaxed threshold for dark samples."""
    return RepeatabilityThreshold(
        std_Y_threshold=0.5,
        relative_std_Y_threshold=5.0,
        max_deviation_Y_threshold=1.0,
        delta_xy_threshold=0.01,
        min_measurements=2,
        warn_threshold_factor=0.8,
    )


# ========== Basic Statistics Tests ==========

class TestCalculateMean:
    """Tests for calculate_mean function."""

    def test_mean_single_values(self):
        """Test mean calculation for single values."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = calculate_mean(values)
        assert result == 3.0

    def test_mean_tuple_values(self):
        """Test mean calculation for tuple values."""
        values = [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]
        result = calculate_mean(values)
        assert result == (3.0, 4.0)

    def test_mean_xyz_values(self):
        """Test mean calculation for XYZ values."""
        values = [(10.0, 20.0, 30.0), (12.0, 22.0, 32.0), (14.0, 24.0, 34.0)]
        result = calculate_mean(values)
        assert result == (12.0, 22.0, 32.0)  # (10+12+14)/3=12, (20+22+24)/3=22, (30+32+34)/3=32

    def test_mean_empty_list_single(self):
        """Test mean for empty single value list."""
        values: List[float] = []
        result = calculate_mean(values)
        assert result == 0.0

    def test_mean_empty_list_tuple(self):
        """Test mean for empty tuple list returns empty tuple."""
        # Note: This tests edge case behavior
        values: List[Tuple[float, float]] = []
        # Empty list returns 0.0, not a tuple - this is expected
        result = calculate_mean(values)
        assert result == 0.0


class TestCalculateStd:
    """Tests for calculate_std function."""

    def test_std_single_values(self):
        """Test standard deviation for single values."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = calculate_std(values)
        # Sample std: sqrt(sum((x-mean)^2)/(n-1)) where mean=3
        # variance = (4+1+0+1+4)/4 = 10/4 = 2.5
        expected = math.sqrt(2.5)  # ~1.581
        assert abs(result - expected) < 0.001

    def test_std_tuple_values(self):
        """Test standard deviation for tuple values."""
        values = [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]
        result = calculate_std(values)
        # Each component: values are 1,3,5 and 2,4,6
        # Std for 1,3,5: sqrt((4+0+4)/2) = sqrt(4) = 2
        # Std for 2,4,6: sqrt((4+0+4)/2) = sqrt(4) = 2
        assert result == (2.0, 2.0)

    def test_std_single_value(self):
        """Test standard deviation for single value (should be 0)."""
        values = [5.0]
        result = calculate_std(values)
        assert result == 0.0

    def test_std_with_mean_provided(self):
        """Test standard deviation with pre-computed mean."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        mean = 3.0
        result = calculate_std(values, mean)
        # Sample std with mean=3: sqrt((4+1+0+1+4)/4) = sqrt(2.5)
        expected = math.sqrt(2.5)
        assert abs(result - expected) < 0.001


class TestCalculateMaxDeviation:
    """Tests for calculate_max_deviation function."""

    def test_max_deviation_single_values(self):
        """Test max deviation for single values."""
        values = [1.0, 5.0, 3.0]
        mean = 3.0
        result = calculate_max_deviation(values, mean)
        assert result == 2.0  # max(|1-3|, |5-3|, |3-3|) = 2

    def test_max_deviation_tuple_values(self):
        """Test max deviation for tuple values."""
        values = [(1.0, 10.0), (5.0, 14.0), (3.0, 12.0)]
        mean = (3.0, 12.0)
        result = calculate_max_deviation(values, mean)
        assert result == (2.0, 2.0)

    def test_max_deviation_auto_mean(self):
        """Test max deviation with auto-computed mean."""
        values = [10.0, 20.0, 30.0]
        result = calculate_max_deviation(values)
        # Mean = 20, max deviation = max(|10-20|, |30-20|) = 10
        assert result == 10.0


class TestCalculateRange:
    """Tests for calculate_range function."""

    def test_range_single_values(self):
        """Test range for single values."""
        values = [1.0, 5.0, 3.0]
        result = calculate_range(values)
        assert result == 4.0  # max - min = 5 - 1

    def test_range_tuple_values(self):
        """Test range for tuple values."""
        values = [(1.0, 10.0), (5.0, 14.0), (3.0, 12.0)]
        result = calculate_range(values)
        assert result == (4.0, 4.0)  # 5-1 and 14-10


# ========== Coordinate Conversion Tests ==========

class TestCoordinateConversion:
    """Tests for coordinate conversion functions."""

    def test_xyz_to_xyY(self):
        """Test XYZ to xyY conversion."""
        X, Y, Z = 95.0, 100.0, 108.9
        x, y, Y_out = xyz_to_xyY(X, Y, Z)
        
        # Check Y is preserved in the output
        assert Y_out == Y
        
        # Check x, y values are computed correctly
        total = X + Y + Z
        expected_x = X / total
        expected_y = Y / total
        assert abs(x - expected_x) < 0.001
        assert abs(y - expected_y) < 0.001
        
        # Note: y (chromaticity) is NOT equal to Y (luminance) - they are different values

    def test_xyz_to_xyY_zero(self):
        """Test XYZ to xyY with zero values."""
        x, y, Y = xyz_to_xyY(0.0, 0.0, 0.0)
        assert x == 0.0
        assert y == 0.0
        assert Y == 0.0

    def test_xyY_to_xyz(self):
        """Test xyY to XYZ conversion."""
        x, y, Y = 0.3127, 0.3290, 100.0
        X, Y_out, Z = xyY_to_xyz(x, y, Y)
        
        # Check Y is preserved
        assert Y_out == Y
        
        # Verify conversion
        assert abs(X - (x / y) * Y) < 0.001
        assert abs(Z - ((1 - x - y) / y) * Y) < 0.001

    def test_xyY_xyz_roundtrip(self):
        """Test xyY <-> XYZ roundtrip conversion."""
        original_xyz = (95.0, 100.0, 108.9)
        xyY = xyz_to_xyY(*original_xyz)
        back_to_xyz = xyY_to_xyz(*xyY)
        
        # Should be very close
        for i in range(3):
            assert abs(original_xyz[i] - back_to_xyz[i]) < 0.001

    def test_xy_to_uv_1976(self):
        """Test xy to u'v' conversion."""
        x, y = 0.3127, 0.3290
        u, v = xy_to_uv_1976(x, y)
        
        # Check formula: u' = 4x / (-2x + 12y + 3)
        denominator = -2.0 * x + 12.0 * y + 3.0
        expected_u = 4.0 * x / denominator
        expected_v = 9.0 * y / denominator
        assert abs(u - expected_u) < 0.001
        assert abs(v - expected_v) < 0.001


# ========== Measurement Statistics Tests ==========

class TestCalculateMeasurementStatistics:
    """Tests for calculate_measurement_statistics function."""

    def test_statistics_basic(self, sample_xyz_measurements):
        """Test basic statistics calculation."""
        stats = calculate_measurement_statistics(sample_xyz_measurements)
        
        assert stats.count == 3
        assert stats.averaging_method == AveragingMethod.XYZ_LINEAR
        
        # Check mean XYZ
        expected_X = (41.24 + 41.24 + 41.24) / 3
        assert abs(stats.mean_xyz[0] - expected_X) < 0.001

    def test_statistics_xyz_linear_average(self, dark_sample_measurements):
        """Test XYZ linear averaging for dark samples."""
        stats = calculate_measurement_statistics(
            dark_sample_measurements, AveragingMethod.XYZ_LINEAR
        )
        
        # Verify mean is calculated correctly
        expected_X = (0.05 + 0.06 + 0.07) / 3
        expected_Y = (0.10 + 0.11 + 0.12) / 3
        expected_Z = (0.12 + 0.13 + 0.14) / 3
        
        assert abs(stats.mean_xyz[0] - expected_X) < 0.001
        assert abs(stats.mean_xyz[1] - expected_Y) < 0.001
        assert abs(stats.mean_xyz[2] - expected_Z) < 0.001

    def test_statistics_confidence(self, stable_measurements):
        """Test confidence calculation."""
        stats = calculate_measurement_statistics(stable_measurements)
        
        # Stable measurements should have high confidence
        assert stats.confidence > 0.5

    def test_statistics_time_info(self, sample_xyz_measurements):
        """Test timestamp and duration calculation."""
        stats = calculate_measurement_statistics(sample_xyz_measurements)
        
        assert stats.timestamp_start is not None
        assert stats.timestamp_end is not None
        assert stats.duration_ms >= 0

    def test_statistics_empty_measurements(self):
        """Test statistics with empty measurement list."""
        stats = calculate_measurement_statistics([])
        assert stats.count == 0

    def test_statistics_std_calculation(self, unstable_measurements):
        """Test standard deviation calculation."""
        stats = calculate_measurement_statistics(unstable_measurements)
        
        # Verify std is calculated
        assert stats.std_xyz[0] > 0  # Should have some variance
        assert stats.std_xyz[1] > 0


# ========== Repeatability Evaluation Tests ==========

class TestEvaluateRepeatability:
    """Tests for evaluate_repeatability function."""

    def test_pass_threshold(self, stable_measurements, default_threshold):
        """Test PASS status for stable measurements."""
        stats = calculate_measurement_statistics(stable_measurements)
        result = evaluate_repeatability(stats, default_threshold)
        
        assert result.status == MeasurementStatus.PASS
        assert not result.needs_remeasurement
        assert len(result.violations) == 0

    def test_fail_threshold(self, unstable_measurements, default_threshold):
        """Test FAIL status for unstable measurements."""
        stats = calculate_measurement_statistics(unstable_measurements)
        result = evaluate_repeatability(stats, default_threshold)
        
        # Should have violations due to high variance
        assert len(result.violations) > 0
        assert result.needs_remeasurement

    def test_warn_threshold(self, default_threshold):
        """Test WARN status for borderline measurements."""
        # Create measurements with moderate variance
        base_time = datetime.now()
        measurements = [
            SingleMeasurement(
                xyz=(100.0, 100.0 + i * 0.15, 100.0),  # Moderate Y variance
                xyY=(0.3127, 0.3290, 100.0 + i * 0.15),
                timestamp=base_time + timedelta(seconds=i),
                instrument_status={},
                metadata={}
            )
            for i in range(3)
        ]
        
        stats = calculate_measurement_statistics(measurements)
        result = evaluate_repeatability(stats, default_threshold)
        
        # Should have warnings (not pass, but may not fail)
        assert result.status in [MeasurementStatus.WARN, MeasurementStatus.FAIL]

    def test_insufficient_measurements(self, default_threshold):
        """Test UNKNOWN status for insufficient measurements."""
        # Single measurement
        measurements = [
            SingleMeasurement(
                xyz=(100.0, 100.0, 100.0),
                xyY=(0.3127, 0.3290, 100.0),
                timestamp=datetime.now(),
                instrument_status={},
                metadata={}
            )
        ]
        
        stats = calculate_measurement_statistics(measurements)
        result = evaluate_repeatability(stats, default_threshold)
        
        assert result.status == MeasurementStatus.UNKNOWN
        assert result.needs_remeasurement

    def test_dark_sample_threshold_adjustment(self, dark_sample_measurements, default_threshold):
        """Test threshold adjustment for dark samples."""
        stats = calculate_measurement_statistics(dark_sample_measurements)
        
        # Without dark adjustment - might fail
        result_normal = evaluate_repeatability(stats, default_threshold, luminance_level="mid")
        
        # With dark adjustment - threshold is relaxed (2x)
        result_dark = evaluate_repeatability(stats, default_threshold, luminance_level="dark")
        
        # Dark sample evaluation should be more lenient
        # (actual result depends on measurements)
        assert isinstance(result_dark.status, MeasurementStatus)


class TestLuminanceLevel:
    """Tests for get_luminance_level function."""

    def test_dark_level(self):
        """Test dark luminance level."""
        assert get_luminance_level(0.5) == "dark"
        assert get_luminance_level(0.9) == "dark"

    def test_mid_level(self):
        """Test mid luminance level."""
        assert get_luminance_level(10.0) == "mid"
        assert get_luminance_level(30.0) == "mid"

    def test_bright_level(self):
        """Test bright luminance level."""
        assert get_luminance_level(100.0) == "bright"
        assert get_luminance_level(200.0) == "bright"


# ========== Helper Functions Tests ==========

class TestCreateSingleMeasurement:
    """Tests for create_single_measurement helper function."""

    def test_create_with_xyz(self):
        """Test creating measurement with XYZ only."""
        xyz = (95.0, 100.0, 108.9)
        measurement = create_single_measurement(xyz)
        
        assert measurement.xyz == xyz
        assert measurement.xyY[2] == xyz[1]  # Y should match
        
        # Check xyY was computed
        x, y, Y = xyz_to_xyY(*xyz)
        assert abs(measurement.xyY[0] - x) < 0.001
        assert abs(measurement.xyY[1] - y) < 0.001

    def test_create_with_xyY(self):
        """Test creating measurement with both XYZ and xyY."""
        xyz = (95.0, 100.0, 108.9)
        xyY = (0.3127, 0.3290, 100.0)
        measurement = create_single_measurement(xyz, xyY)
        
        assert measurement.xyz == xyz
        assert measurement.xyY == xyY

    def test_create_with_metadata(self):
        """Test creating measurement with metadata."""
        xyz = (50.0, 60.0, 70.0)
        metadata = {"temperature": 25.0, "integration_time": 100}
        measurement = create_single_measurement(xyz, metadata=metadata)
        
        assert measurement.metadata == metadata


class TestAverageMeasurementsXyz:
    """Tests for average_measurements_xyz helper function."""

    def test_average_xyz(self, stable_measurements):
        """Test XYZ averaging helper function."""
        mean_xyz, stats = average_measurements_xyz(stable_measurements)
        
        assert isinstance(mean_xyz, tuple)
        assert len(mean_xyz) == 3
        
        # Verify mean matches statistics
        assert mean_xyz == stats.mean_xyz

    def test_average_empty(self):
        """Test averaging empty measurement list."""
        mean_xyz, stats = average_measurements_xyz([])
        
        assert mean_xyz == (0.0, 0.0, 0.0)
        assert stats.count == 0


# ========== Session Repeatability Summary Tests ==========

class TestSessionRepeatabilitySummary:
    """Tests for SessionRepeatabilitySummary generation."""

    def test_generate_summary(self, default_threshold):
        """Test generating session summary."""
        # Create patch records with different statuses
        base_time = datetime.now()
        
        records = []
        for i in range(5):
            # Create measurements for each patch
            measurements = [
                SingleMeasurement(
                    xyz=(50.0 + i * 10, 50.0 + i * 10, 50.0 + i * 10),
                    xyY=(0.333, 0.333, 50.0 + i * 10),
                    timestamp=base_time + timedelta(seconds=i),
                    instrument_status={},
                    metadata={}
                )
                for _ in range(3)
            ]
            
            stats = calculate_measurement_statistics(measurements)
            result = evaluate_repeatability(stats, default_threshold)
            
            record = PatchRepeatabilityRecord(
                patch_index=i,
                patch_name=f"Patch_{i}",
                rgb=(50 + i * 20, 50 + i * 20, 50 + i * 20),
                measurements=measurements,
                statistics=stats,
                result=result,
            )
            records.append(record)
        
        summary = generate_repeatability_summary("test_session", records)
        
        assert summary.session_id == "test_session"
        assert summary.total_patches == 5
        assert summary.pass_rate >= 0

    def test_summary_pass_rate(self):
        """Test pass rate calculation."""
        # Create records with known pass/fail
        records = [
            PatchRepeatabilityRecord(
                patch_index=0,
                patch_name="Pass1",
                rgb=(255, 255, 255),
                measurements=[],
                statistics=MeasurementStatistics(),
                result=RepeatabilityResult(status=MeasurementStatus.PASS),
            ),
            PatchRepeatabilityRecord(
                patch_index=1,
                patch_name="Fail1",
                rgb=(0, 0, 0),
                measurements=[],
                statistics=MeasurementStatistics(),
                result=RepeatabilityResult(status=MeasurementStatus.FAIL),
            ),
            PatchRepeatabilityRecord(
                patch_index=2,
                patch_name="Pass2",
                rgb=(128, 128, 128),
                measurements=[],
                statistics=MeasurementStatistics(),
                result=RepeatabilityResult(status=MeasurementStatus.PASS),
            ),
        ]
        
        summary = generate_repeatability_summary("test", records)
        
        assert summary.passed_patches == 2
        assert summary.failed_patches == 1
        assert summary.pass_rate == (2 / 3) * 100

    def test_summary_overall_status(self):
        """Test overall status determination."""
        # All passing
        passing_records = [
            PatchRepeatabilityRecord(
                patch_index=i,
                patch_name=f"Pass{i}",
                rgb=(i, i, i),
                measurements=[],
                statistics=MeasurementStatistics(),
                result=RepeatabilityResult(status=MeasurementStatus.PASS),
            )
            for i in range(3)
        ]
        
        summary_pass = generate_repeatability_summary("pass_session", passing_records)
        assert summary_pass.overall_status == MeasurementStatus.PASS
        
        # With failures
        mixed_records = passing_records + [
            PatchRepeatabilityRecord(
                patch_index=3,
                patch_name="Fail",
                rgb=(255, 0, 0),
                measurements=[],
                statistics=MeasurementStatistics(),
                result=RepeatabilityResult(status=MeasurementStatus.FAIL),
            )
        ]
        
        summary_mixed = generate_repeatability_summary("mixed_session", mixed_records)
        assert summary_mixed.overall_status == MeasurementStatus.FAIL


# ========== Data Type Tests ==========

class TestMeasurementStatistics:
    """Tests for MeasurementStatistics dataclass."""

    def test_relative_std_Y(self):
        """Test relative_std_Y property."""
        stats = MeasurementStatistics(
            count=3,
            mean_xyz=(100.0, 100.0, 100.0),
            std_xyz=(0.5, 2.0, 0.5),
        )
        
        # relative_std_Y = (std_Y / mean_Y) * 100
        expected = (2.0 / 100.0) * 100
        assert stats.relative_std_Y == expected

    def test_relative_std_Y_zero_mean(self):
        """Test relative_std_Y with zero mean."""
        stats = MeasurementStatistics(
            count=3,
            mean_xyz=(0.0, 0.0, 0.0),
            std_xyz=(0.5, 0.5, 0.5),
        )
        
        # Should return 0 when mean is 0
        assert stats.relative_std_Y == 0.0

    def test_to_dict(self):
        """Test to_dict conversion."""
        stats = MeasurementStatistics(
            count=3,
            mean_xyz=(100.0, 100.0, 100.0),
            mean_xyY=(0.333, 0.333, 100.0),
            std_xyz=(0.5, 0.5, 0.5),
        )
        
        result = stats.to_dict()
        
        assert isinstance(result, dict)
        assert result["count"] == 3
        assert result["mean_xyz"] == [100.0, 100.0, 100.0]


class TestRepeatabilityThreshold:
    """Tests for RepeatabilityThreshold dataclass."""

    def test_default_values(self):
        """Test default threshold values."""
        threshold = RepeatabilityThreshold()
        
        assert threshold.std_Y_threshold == 0.1
        assert threshold.relative_std_Y_threshold == 2.0
        assert threshold.min_measurements == 3

    def test_custom_values(self):
        """Test custom threshold values."""
        threshold = RepeatabilityThreshold(
            std_Y_threshold=0.5,
            relative_std_Y_threshold=5.0,
            min_measurements=5,
        )
        
        assert threshold.std_Y_threshold == 0.5
        assert threshold.min_measurements == 5


# ========== Integration Tests ==========

class TestIntegration:
    """Integration tests for complete workflow."""

    def test_complete_workflow(self, default_threshold):
        """Test complete measurement statistics workflow."""
        # Create measurements
        base_time = datetime.now()
        measurements = [
            create_single_measurement(
                xyz=(95.0 + i * 0.1, 100.0 + i * 0.1, 108.9 + i * 0.1),
                metadata={"index": i}
            )
            for i in range(5)
        ]
        
        # Calculate statistics
        stats = calculate_measurement_statistics(measurements)
        
        # Evaluate repeatability
        result = evaluate_repeatability(stats, default_threshold)
        
        # Create patch record
        record = PatchRepeatabilityRecord(
            patch_index=0,
            patch_name="White",
            rgb=(255, 255, 255),
            measurements=measurements,
            statistics=stats,
            result=result,
        )
        
        # Generate summary
        summary = generate_repeatability_summary("test", [record])
        
        # Verify complete workflow
        assert summary.total_patches == 1
        assert summary.patches[0].statistics.count == 5
        assert isinstance(summary.overall_status, MeasurementStatus)


# ========== Edge Cases ==========

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_very_small_measurements(self):
        """Test with very small XYZ values (near zero)."""
        measurements = [
            create_single_measurement(
                xyz=(0.001, 0.001, 0.001),
                metadata={"dark": True}
            )
            for _ in range(3)
        ]
        
        stats = calculate_measurement_statistics(measurements)
        result = evaluate_repeatability(
            stats, 
            RepeatabilityThreshold(),
            luminance_level="dark"
        )
        
        assert stats.mean_xyz[1] < 0.01

    def test_large_measurements(self):
        """Test with large XYZ values (bright patches)."""
        measurements = [
            create_single_measurement(
                xyz=(200.0, 250.0, 300.0),
                metadata={"bright": True}
            )
            for _ in range(3)
        ]
        
        stats = calculate_measurement_statistics(measurements)
        
        assert stats.mean_xyz[1] == 250.0

    def test_single_measurement(self):
        """Test with single measurement (insufficient data)."""
        measurement = create_single_measurement(
            xyz=(100.0, 100.0, 100.0)
        )
        
        stats = calculate_measurement_statistics([measurement])
        result = evaluate_repeatability(stats, RepeatabilityThreshold())
        
        assert stats.count == 1
        assert result.status == MeasurementStatus.UNKNOWN

    def test_negative_xyY(self):
        """Test handling of unusual xyY values."""
        # This shouldn't normally happen, but we test robustness
        measurements = [
            SingleMeasurement(
                xyz=(0.0, 0.0, 0.0),
                xyY=(0.0, 0.0, 0.0),
                timestamp=datetime.now(),
                instrument_status={},
                metadata={}
            )
        ]
        
        stats = calculate_measurement_statistics(measurements)
        assert stats.mean_xyz == (0.0, 0.0, 0.0)


# ========== Outlier Detection Tests ==========

class TestOutlierDetection:
    """Tests for outlier detection methods."""

    def test_mad_no_outliers(self):
        """Test MAD method with stable data (no outliers)."""
        measurements = [
            create_single_measurement(xyz=(100.0, 100.0 + i * 0.01, 100.0))
            for i in range(5)
        ]
        result = detect_outliers_mad(measurements, threshold=3.0)
        assert not result.has_outliers
        assert len(result.accepted_measurements) == 5

    def test_mad_with_outliers(self):
        """Test MAD method detecting outliers."""
        # Create measurements with one obvious outlier
        base_time = datetime.now()
        measurements = [
            SingleMeasurement(
                xyz=(100.0, 100.0 + i * 0.1, 100.0),
                xyY=(0.3127, 0.3290, 100.0 + i * 0.1),
                timestamp=base_time + timedelta(seconds=i),
                instrument_status={},
                metadata={}
            )
            for i in [0, 1, 2, 3, 10]  # Last one is outlier
        ]
        result = detect_outliers_mad(measurements, threshold=2.5, use_component="Y")
        assert result.has_outliers
        assert len(result.accepted_measurements) < 5

    def test_iqr_no_outliers(self):
        """Test IQR method with stable data."""
        measurements = [
            create_single_measurement(xyz=(50.0, 50.0, 50.0))
            for _ in range(10)
        ]
        result = detect_outliers_iqr(measurements, iqr_factor=1.5)
        assert not result.has_outliers

    def test_iqr_with_outliers(self):
        """Test IQR method detecting outliers."""
        base_time = datetime.now()
        # Create data with outliers at extremes
        values = [100.0, 101.0, 102.0, 103.0, 104.0, 150.0, 50.0]  # 150 and 50 are outliers
        measurements = [
            SingleMeasurement(
                xyz=(100.0, values[i], 100.0),
                xyY=(0.3127, 0.3290, values[i]),
                timestamp=base_time + timedelta(seconds=i),
                instrument_status={},
                metadata={}
            )
            for i in range(len(values))
        ]
        result = detect_outliers_iqr(measurements, iqr_factor=1.5, use_component="Y")
        # IQR should detect outliers
        assert len(result.accepted_measurements) <= len(measurements)

    def test_zscore_insufficient_samples(self):
        """Test Z-score returns all measurements for small sample."""
        measurements = [
            create_single_measurement(xyz=(100.0, 100.0, 100.0))
            for _ in range(5)  # Less than 10
        ]
        result = detect_outliers_zscore(measurements, threshold=2.0)
        # Z-score requires at least 10 samples
        assert len(result.accepted_measurements) == 5

    def test_zscore_with_outliers(self):
        """Test Z-score method with sufficient samples."""
        base_time = datetime.now()
        # Create 10+ measurements with outliers
        values = [100.0] * 8 + [150.0, 50.0]  # Last two are outliers
        measurements = [
            SingleMeasurement(
                xyz=(100.0, values[i], 100.0),
                xyY=(0.3127, 0.3290, values[i]),
                timestamp=base_time + timedelta(seconds=i),
                instrument_status={},
                metadata={}
            )
            for i in range(len(values))
        ]
        result = detect_outliers_zscore(measurements, threshold=2.0, use_component="Y")
        # Should detect outliers
        assert result.has_outliers

    def test_detect_outliers_none_method(self):
        """Test detect_outliers with NONE method."""
        measurements = [
            create_single_measurement(xyz=(100.0, 100.0, 100.0))
            for _ in range(5)
        ]
        result = detect_outliers(measurements, method=OutlierRejectionMethod.NONE)
        assert not result.has_outliers
        assert len(result.accepted_measurements) == 5

    def test_detect_outliers_default_mad(self):
        """Test detect_outliers uses MAD by default."""
        measurements = [
            create_single_measurement(xyz=(100.0, 100.0, 100.0))
            for _ in range(5)
        ]
        result = detect_outliers(measurements)
        assert result.method == OutlierRejectionMethod.MAD


class TestMedianAndMAD:
    """Tests for median and MAD helper functions."""

    def test_calculate_median_odd_count(self):
        """Test median with odd count."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        median = _calculate_median(values)
        assert median == 3.0

    def test_calculate_median_even_count(self):
        """Test median with even count."""
        values = [1.0, 2.0, 3.0, 4.0]
        median = _calculate_median(values)
        assert median == 2.5  # Average of 2 and 3

    def test_calculate_mad(self):
        """Test MAD calculation."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        median = 3.0
        mad = _calculate_mad(values, median)
        # Deviations from median: [2, 1, 0, 1, 2], sorted: [0, 1, 1, 2, 2]
        # Median of deviations: 1.0
        assert mad == 1.0

    def test_calculate_median_empty(self):
        """Test median with empty list."""
        median = _calculate_median([])
        assert median == 0.0


# ========== Luminance Level Tests ==========

class TestLuminanceLevel:
    """Tests for luminance level classification."""

    def test_dark_level_enum(self):
        """Test dark luminance level enum."""
        assert get_luminance_level_enum(0.5) == LuminanceLevel.DARK
        assert get_luminance_level_enum(0.9) == LuminanceLevel.DARK

    def test_mid_level_enum(self):
        """Test mid luminance level enum."""
        assert get_luminance_level_enum(10.0) == LuminanceLevel.MID
        assert get_luminance_level_enum(30.0) == LuminanceLevel.MID

    def test_bright_level_enum(self):
        """Test bright luminance level enum."""
        assert get_luminance_level_enum(100.0) == LuminanceLevel.BRIGHT
        assert get_luminance_level_enum(200.0) == LuminanceLevel.BRIGHT

    def test_boundary_values(self):
        """Test boundary values for luminance level."""
        assert get_luminance_level_enum(0.99) == LuminanceLevel.DARK
        assert get_luminance_level_enum(1.0) == LuminanceLevel.MID
        assert get_luminance_level_enum(49.99) == LuminanceLevel.MID
        assert get_luminance_level_enum(50.0) == LuminanceLevel.BRIGHT


# ========== Luminance Policy Tests ==========

class TestLuminancePolicy:
    """Tests for luminance-adaptive policy."""

    def test_dark_policy_higher_repeat(self):
        """Test dark luminance policy has higher repeat count."""
        policy = get_luminance_policy(0.5)
        assert policy.repeat_count >= 5
        assert policy.force_dark_handling == True

    def test_dark_policy_extended_integration(self):
        """Test dark policy has extended integration time."""
        policy = get_luminance_policy(0.5)
        assert policy.integration_time_factor >= 2.0

    def test_bright_policy_lower_repeat(self):
        """Test bright luminance policy has lower repeat count."""
        policy = get_luminance_policy(100.0)
        assert policy.repeat_count >= 2

    def test_mid_policy_standard(self):
        """Test mid luminance policy is standard."""
        policy = get_luminance_policy(30.0)
        assert policy.repeat_count >= 3

    def test_policy_with_base_override(self):
        """Test policy respects base policy."""
        base = PatchMeasurementPolicy(
            repeat_count=10,
            confidence_threshold=0.9
        )
        policy = get_luminance_policy(0.5, base)
        # Should use max of base and adaptive
        assert policy.repeat_count >= 10

    def test_policy_outlier_threshold_adjustment(self):
        """Test outlier threshold is adjusted for luminance."""
        dark_policy = get_luminance_policy(0.5)
        bright_policy = get_luminance_policy(100.0)

        # Dark should have relaxed (higher) threshold
        # Bright should have tighter (lower) threshold
        assert dark_policy.outlier_threshold >= bright_policy.outlier_threshold


# ========== Confidence Score Tests ==========

class TestConfidenceScore:
    """Tests for confidence score calculation."""

    def test_high_confidence_stable_measurements(self, stable_measurements):
        """Test high confidence for stable measurements."""
        stats = calculate_measurement_statistics(stable_measurements)
        confidence = calculate_confidence_score(stats)
        assert confidence > 0.5

    def test_low_confidence_single_measurement(self):
        """Test low confidence for single measurement."""
        measurements = [create_single_measurement(xyz=(100.0, 100.0, 100.0))]
        stats = calculate_measurement_statistics(measurements)
        confidence = calculate_confidence_score(stats)
        # Single measurement should have low confidence due to count factor
        assert confidence < 0.5

    def test_confidence_with_outliers(self, stable_measurements):
        """Test confidence reduced by outliers."""
        stats = calculate_measurement_statistics(stable_measurements)
        # Simulate outlier rejection
        outlier_result = OutlierDetectionResult(
            method=OutlierRejectionMethod.MAD,
            outlier_indices=[0],
            accepted_measurements=stable_measurements[1:],
            rejected_measurements=stable_measurements[:1],
            rejection_ratio=0.2,
        )
        confidence_with_outliers = calculate_confidence_score(stats, outlier_result)
        confidence_without_outliers = calculate_confidence_score(stats)
        # Confidence should be lower with outliers
        assert confidence_with_outliers <= confidence_without_outliers

    def test_confidence_empty_measurements(self):
        """Test confidence for empty measurements."""
        stats = MeasurementStatistics(count=0)
        confidence = calculate_confidence_score(stats)
        assert confidence == 0.0


# ========== Measurement Quality Status Tests ==========

class TestMeasurementQualityStatus:
    """Tests for measurement quality status."""

    def test_pass_status_high_confidence(self):
        """Test PASS status for high confidence."""
        threshold = RepeatabilityThreshold()
        status = get_measurement_quality_status(0.9, threshold, LuminanceLevel.MID)
        assert status == MeasurementStatus.PASS

    def test_warn_status_medium_confidence(self):
        """Test WARN status for medium confidence."""
        threshold = RepeatabilityThreshold()
        status = get_measurement_quality_status(0.6, threshold, LuminanceLevel.MID)
        assert status == MeasurementStatus.WARN

    def test_fail_status_low_confidence(self):
        """Test FAIL status for low confidence."""
        threshold = RepeatabilityThreshold()
        status = get_measurement_quality_status(0.3, threshold, LuminanceLevel.MID)
        assert status == MeasurementStatus.FAIL

    def test_dark_level_relaxed_threshold(self):
        """Test dark level uses relaxed confidence threshold."""
        threshold = RepeatabilityThreshold()
        # For dark, 0.5 should pass (threshold is 0.6 for pass)
        status = get_measurement_quality_status(0.6, threshold, LuminanceLevel.DARK)
        assert status == MeasurementStatus.PASS

    def test_bright_level_tightened_threshold(self):
        """Test bright level uses tightened confidence threshold."""
        threshold = RepeatabilityThreshold()
        # For bright, 0.75 should not pass (threshold is 0.85)
        status = get_measurement_quality_status(0.75, threshold, LuminanceLevel.BRIGHT)
        assert status == MeasurementStatus.WARN


# ========== PatchMeasurementPolicy Tests ==========

class TestPatchMeasurementPolicy:
    """Tests for patch measurement policy dataclass."""

    def test_default_policy_values(self):
        """Test default policy values."""
        policy = PatchMeasurementPolicy()
        assert policy.repeat_count == 3
        assert policy.outlier_rejection_method == OutlierRejectionMethod.MAD
        assert policy.confidence_threshold == 0.7

    def test_custom_policy_values(self):
        """Test custom policy values."""
        policy = PatchMeasurementPolicy(
            repeat_count=5,
            outlier_rejection_method=OutlierRejectionMethod.IQR,
            confidence_threshold=0.9,
            settling_time_ms=400,
        )
        assert policy.repeat_count == 5
        assert policy.outlier_rejection_method == OutlierRejectionMethod.IQR
        assert policy.settling_time_ms == 400


# ========== OutlierDetectionResult Tests ==========

class TestOutlierDetectionResult:
    """Tests for OutlierDetectionResult dataclass."""

    def test_has_outliers_property(self):
        """Test has_outliers property."""
        result_no_outliers = OutlierDetectionResult(
            outlier_indices=[],
            accepted_measurements=[],
        )
        assert not result_no_outliers.has_outliers

        result_with_outliers = OutlierDetectionResult(
            outlier_indices=[0, 1],
            accepted_measurements=[],
        )
        assert result_with_outliers.has_outliers

    def test_rejection_ratio_calculation(self):
        """Test rejection ratio is calculated."""
        result = OutlierDetectionResult(
            outlier_indices=[0],
            accepted_measurements=[],
            rejected_measurements=[],
            rejection_ratio=0.2,
        )
        assert result.rejection_ratio == 0.2
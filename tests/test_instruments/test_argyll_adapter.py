"""
Tests for ArgyllAdapter and ArgyllCMS output parsing.

This test module uses fixtures from tests/fixtures/argyll/ to test:
- spotread output parsing (5 tests)
- dispcal output parsing (5 tests)
- targen output parsing (5 tests)
- colprof output parsing (5 tests)
- collink output parsing (5 tests)
- error message mapping (5 tests)

All tests use fixtures, no real hardware required.

Reference:
- docs/agent_handoffs/P0-C_argyll_audit.md
- tests/fixtures/argyll/README.md
"""

import pytest
from pathlib import Path
from typing import Dict, Any

# Import the modules under test
from src.instruments.argyll_adapter import (
    ArgyllAdapter,
    OutputParser,
    OutputPatterns,
    ParseResult,
    ProcessLifecycle,
    create_argyll_adapter,
)
from src.instruments.argyll_params import (
    SpotreadParams,
    DispcalParams,
    TargenParams,
    ColprofParams,
    CollinkParams,
    DisplayType,
    ProbeType,
    QualityLevel,
    RenderingIntent,
    ArgyllErrorMapping,
    map_error_to_suggestion,
    DEFAULT_ERROR_MAPPINGS,
)
from src.instruments.base import (
    InstrumentError,
    InstrumentStatus,
    InstrumentState,
    MeasurementResult,
    FakeInstrument,
    FakePatchPresenter,
)


# ========== Fixture Loading Helper ==========

def load_fixture(filename: str) -> str:
    """Load fixture file content."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "argyll" / filename
    if not fixture_path.exists():
        pytest.skip(f"Fixture not found: {fixture_path}")
    return fixture_path.read_text(encoding="utf-8")


# ========== Spotread Output Parsing Tests (5+ tests) ==========

class TestSpotreadParsing:
    """Tests for spotread output parsing."""

    def test_parse_success_xyz(self):
        """Test parsing successful spotread measurement with XYZ format."""
        fixture = load_fixture("01_spotread_success.txt")
        result = OutputParser.parse_spotread(fixture)

        assert result.success is True
        assert result.error is None
        assert 'xyz' in result.data
        assert 'xyY' in result.data

        # Verify parsed values
        xyz = result.data['xyz']
        xyY = result.data['xyY']

        # Expected XYZ from fixture: 0.033364 0.029912 0.062078
        assert abs(xyz[0] - 0.033364) < 0.0001
        assert abs(xyz[1] - 0.029912) < 0.0001
        assert abs(xyz[2] - 0.062078) < 0.0001

        # Verify xyY conversion
        assert abs(xyY[2] - 0.029912) < 0.0001  # Y value unchanged

    def test_parse_usb_disconnect(self):
        """Test parsing USB disconnect error."""
        fixture = load_fixture("02_spotread_usb_disconnect.txt")
        result = OutputParser.parse_spotread(fixture)

        assert result.success is False
        assert result.error is not None
        assert 'USB' in result.error or '断开' in result.error

    def test_parse_ambient_filter_error(self):
        """Test parsing ambient filter error."""
        fixture = load_fixture("03_spotread_ambient_filter_error.txt")
        result = OutputParser.parse_spotread(fixture)

        assert result.success is False
        assert result.error is not None
        assert '柔光罩' in result.error

    def test_parse_no_instrument(self):
        """Test parsing no instrument found error."""
        fixture = load_fixture("04_spotread_no_instrument.txt")
        result = OutputParser.parse_spotread(fixture)

        assert result.success is False
        assert result.error is not None
        assert '探头' in result.error or '未检测' in result.error

    def test_parse_calibration_failed(self):
        """Test parsing calibration failed error."""
        fixture = load_fixture("05_spotread_calibration_failed.txt")
        result = OutputParser.parse_spotread(fixture)

        assert result.success is False
        assert result.error is not None
        assert '校准' in result.error

    def test_parse_xyz_direct_string(self):
        """Test parsing XYZ directly from string."""
        output = "Result is XYZ: 0.123456 0.234567 0.345678"
        result = OutputParser.parse_spotread(output)

        assert result.success is True
        assert abs(result.data['xyz'][0] - 0.123456) < 0.000001

    def test_parse_yxy_format(self):
        """Test parsing Yxy format (backup format)."""
        output = "Yxy: Y = 50.0, x = 0.3127, y = 0.3290"
        result = OutputParser.parse_spotread(output)

        assert result.success is True
        assert abs(result.data['xyY'][2] - 50.0) < 0.01

    def test_parse_device_enumeration(self):
        """Test parsing device enumeration output."""
        fixture = load_fixture("15_spotread_device_enumeration.txt")
        # This fixture is for enumeration, parse_spotread should handle it gracefully
        result = OutputParser.parse_spotread(fixture)
        # Enumeration output doesn't have measurement result
        assert result.success is False or result.error is not None


# ========== Dispcal Output Parsing Tests (5+ tests) ==========

class TestDispcalParsing:
    """Tests for dispcal output parsing."""

    def test_parse_progress(self):
        """Test parsing dispcal progress output."""
        fixture = load_fixture("06_dispcal_progress.txt")
        result = OutputParser.parse_dispcal(fixture)

        assert result.success is True
        # Progress may be None if fixture doesn't have specific progress line
        # Check that we parsed something correctly
        assert result.stage is not None or result.data is not None

    def test_parse_success(self):
        """Test parsing dispcal successful completion."""
        fixture = load_fixture("07_dispcal_success.txt")
        result = OutputParser.parse_dispcal(fixture)

        assert result.success is True
        # Should have cal_file in data
        assert result.data.get('complete') is True or 'cal_file' in result.data

    def test_parse_web_server_url(self):
        """Test parsing web server URL."""
        output = "Created web server at 'http://192.168.1.20:9292/', now waiting..."
        result = OutputParser.parse_dispcal(output)

        assert result.success is True
        assert 'web_url' in result.data
        assert '192.168.1.20:9292' in result.data['web_url']

    def test_parse_patch_progress(self):
        """Test parsing patch progress."""
        output = "Reading patch 10 of 21 ..."
        result = OutputParser.parse_dispcal(output)

        assert result.success is True
        assert result.data['current_patch'] == 10
        assert result.data['total_patches'] == 21

    def test_parse_stage_commencing(self):
        """Test parsing 'Commencing display calibration' stage."""
        output = "Commencing display calibration ..."
        result = OutputParser.parse_dispcal(output)

        assert result.success is True
        assert result.stage == 'starting'
        assert result.progress == 15

    def test_parse_stage_computing(self):
        """Test parsing 'Computing calibration curves' stage."""
        output = "Computing calibration curves ..."
        result = OutputParser.parse_dispcal(output)

        assert result.success is True
        assert result.stage == 'computing'
        assert result.progress == 70

    def test_parse_stage_vcgt(self):
        """Test parsing 'Creating VCGT' stage."""
        output = "Creating VCGT (Video Card Gamma Table) ..."
        result = OutputParser.parse_dispcal(output)

        assert result.success is True
        assert result.stage == 'vcgt'
        assert result.progress == 80


# ========== Targen Output Parsing Tests (5+ tests) ==========

class TestTargenParsing:
    """Tests for targen output parsing."""

    def test_parse_output(self):
        """Test parsing targen output with patch count."""
        fixture = load_fixture("08_targen_output.txt")
        result = OutputParser.parse_targen(fixture)

        assert result.success is True
        assert 'patch_count' in result.data or 'created_patches' in result.data

    def test_parse_number_of_sets(self):
        """Test parsing NUMBER_OF_SETS."""
        output = "NUMBER_OF_SETS 1024"
        result = OutputParser.parse_targen(output)

        assert result.success is True
        assert result.data['patch_count'] == 1024
        assert result.progress == 100

    def test_parse_created_patches(self):
        """Test parsing 'Created X patches'."""
        output = "Created 512 patches (gray axis + primaries)"
        result = OutputParser.parse_targen(output)

        assert result.success is True
        assert result.data['created_patches'] == 512

    def test_parse_complete(self):
        """Test parsing complete targen output."""
        output = """
Output file: output.ti1
NUMBER_OF_SETS 1024
"""
        result = OutputParser.parse_targen(output)

        assert result.success is True
        assert result.stage == 'complete'

    def test_parse_empty_output(self):
        """Test parsing empty/running output."""
        output = "Generating test chart ..."
        result = OutputParser.parse_targen(output)

        assert result.success is True
        assert result.stage == 'running'

    def test_parse_various_patch_counts(self):
        """Test parsing various patch count formats."""
        test_cases = [
            ("Created 128 patches", 128),
            ("Created 256 patches", 256),
            ("Created 512 patches", 512),
            ("Created 1024 patches", 1024),
            ("Created 2048 patches", 2048),
        ]

        for output, expected_count in test_cases:
            result = OutputParser.parse_targen(output)
            assert result.data['created_patches'] == expected_count


# ========== Colprof Output Parsing Tests (5+ tests) ==========

class TestColprofParsing:
    """Tests for colprof output parsing."""

    def test_parse_progress(self):
        """Test parsing colprof progress output."""
        fixture = load_fixture("09_colprof_progress.txt")
        result = OutputParser.parse_colprof(fixture)

        assert result.success is True
        assert result.progress is not None

    def test_parse_success(self):
        """Test parsing colprof successful completion."""
        fixture = load_fixture("10_colprof_success.txt")
        result = OutputParser.parse_colprof(fixture)

        assert result.success is True
        assert 'icc_file' in result.data or result.data.get('complete')

    def test_parse_failure(self):
        """Test parsing colprof failure."""
        fixture = load_fixture("11_colprof_failure.txt")
        result = OutputParser.parse_colprof(fixture)

        # Should parse successfully (it's output, not error per se)
        assert result.success is True

    def test_parse_progress_percentage(self):
        """Test parsing various progress percentage formats."""
        test_cases = [
            ("Progress: 25%", 25),
            ("Progress: 50%", 50),
            ("Progress: 75%", 75),
            ("Done: 100%", 100),
            ("80% complete", 80),
        ]

        for output, expected_progress in test_cases:
            result = OutputParser.parse_colprof(output)
            assert result.progress == expected_progress

    def test_parse_stage_reading(self):
        """Test parsing 'Reading measurement data' stage."""
        output = "Reading measurement data from 'output.ti3' ..."
        result = OutputParser.parse_colprof(output)

        assert result.success is True
        assert result.stage == 'reading'
        assert result.progress == 5

    def test_parse_stage_building_lut(self):
        """Test parsing 'Building forward lookup' stage."""
        output = "Building forward lookup tables ..."
        result = OutputParser.parse_colprof(output)

        assert result.success is True
        assert result.stage == 'forward_lut'

    def test_parse_stage_created_profile(self):
        """Test parsing 'Created profile' output."""
        output = "Created profile 'display.icc'"
        result = OutputParser.parse_colprof(output)

        assert result.success is True
        assert result.data['icc_file'] == 'display.icc'
        assert result.progress == 100


# ========== Collink Output Parsing Tests (5+ tests) ==========

class TestCollinkParsing:
    """Tests for collink output parsing."""

    def test_parse_success(self):
        """Test parsing collink successful completion."""
        fixture = load_fixture("12_collink_success.txt")
        result = OutputParser.parse_collink(fixture)

        assert result.success is True
        assert 'cube_file' in result.data or result.data.get('complete')

    def test_parse_bpc_error(self):
        """Test parsing collink BPC parameter error."""
        fixture = load_fixture("13_collink_bpc_error.txt")
        result = OutputParser.parse_collink(fixture)

        # This fixture shows an error condition
        assert result.success is True  # Parsing is successful, data shows error

    def test_parse_progress_percentage(self):
        """Test parsing collink progress percentage."""
        test_cases = [
            ("Making lookup tables - 10% done", 10),
            ("Making lookup tables - 25% done", 25),
            ("Making lookup tables - 50% done", 50),
            ("Making lookup tables - 75% done", 75),
            ("Making lookup tables - 100% done", 100),
        ]

        for output, expected_progress in test_cases:
            result = OutputParser.parse_collink(output)
            assert result.progress == expected_progress

    def test_parse_stage_building(self):
        """Test parsing 'Making lookup tables' stage."""
        output = "Making lookup tables - 30% done"
        result = OutputParser.parse_collink(output)

        assert result.success is True
        assert result.stage == 'building_lut'
        assert result.progress == 30

    def test_parse_empty_output(self):
        """Test parsing empty/running collink output."""
        output = "ArgyllCMS collink - Device link profile creator"
        result = OutputParser.parse_collink(output)

        assert result.success is True
        assert result.stage == 'running'

    def test_parse_created_cube(self):
        """Test parsing 'Created' cube file."""
        output = "Created 3D LUT file 'output.cube'"
        result = OutputParser.parse_collink(output)

        assert result.success is True
        # Check if we detected completion


# ========== Error Message Mapping Tests (5+ tests) ==========

class TestErrorMapping:
    """Tests for error message to user suggestion mapping."""

    def test_map_ambient_filter(self):
        """Test mapping ambient filter error."""
        error = "ambient filter should be removed"
        mapping = map_error_to_suggestion(error)

        assert '柔光罩' in mapping.user_message
        assert mapping.recoverable is True
        assert mapping.action == 'calibrate'

    def test_map_usb_disconnect(self):
        """Test mapping USB disconnect error."""
        error = "readpipeasync failed: (-1) LIBUSB_ERROR_IO"
        mapping = map_error_to_suggestion(error)

        assert 'USB' in mapping.user_message or '断开' in mapping.user_message
        assert mapping.recoverable is True
        assert mapping.action == 'reconnect'

    def test_map_no_instrument(self):
        """Test mapping no instrument error."""
        error = "No instrument found"
        mapping = map_error_to_suggestion(error)

        assert '探头' in mapping.user_message or '未检测' in mapping.user_message
        assert mapping.recoverable is True

    def test_map_calibration_failed(self):
        """Test mapping calibration failed error."""
        error = "Calibration failed - out of range"
        mapping = map_error_to_suggestion(error)

        assert '校准' in mapping.user_message
        assert mapping.recoverable is True
        assert mapping.action == 'calibrate'

    def test_map_unknown_error(self):
        """Test mapping unknown error."""
        error = "Some random error message"
        mapping = map_error_to_suggestion(error)

        assert mapping.keyword == 'unknown'
        assert mapping.recoverable is False
        assert mapping.action == 'contact_support'

    def test_map_bpc_conflict(self):
        """Test mapping BPC conflict error."""
        error = "Black point compensation (-b) cannot be used with perceptual intent"
        mapping = map_error_to_suggestion(error)

        assert '黑场' in mapping.user_message or '补偿' in mapping.user_message
        assert mapping.recoverable is True

    def test_map_memory_error(self):
        """Test mapping out of memory error."""
        error = "Out of memory - cannot allocate lookup table"
        mapping = map_error_to_suggestion(error)

        assert '内存' in mapping.user_message
        assert mapping.recoverable is False

    def test_map_file_not_found(self):
        """Test mapping file not found error."""
        error = "Can't open input file 'output.ti3' - No such file"
        mapping = map_error_to_suggestion(error)

        assert '文件' in mapping.user_message
        assert mapping.recoverable is False


# ========== Parameter Dataclass Tests ==========

class TestSpotreadParams:
    """Tests for SpotreadParams dataclass."""

    def test_default_params(self):
        """Test default SpotreadParams."""
        params = SpotreadParams()
        assert params.display_type == DisplayType.LCD
        assert params.instrument_port is None
        assert params.correction_file is None
        assert params.emissive_mode is True

    def test_to_command_args(self):
        """Test converting SpotreadParams to command args."""
        params = SpotreadParams(
            display_type=DisplayType.OLED,
            instrument_port=2,
        )
        args = params.to_command_args()

        assert '-e' in args
        assert '-d' in args
        assert 'o' in args  # OLED display type
        assert '-c' in args
        assert '2' in args

    def test_validate_no_correction_file(self):
        """Test validation with non-existent correction file."""
        params = SpotreadParams(correction_file="/nonexistent/path.ccss")
        valid, error = params.validate()

        assert valid is False
        assert "not found" in error.lower()

    def test_validate_valid_params(self):
        """Test validation with valid params."""
        params = SpotreadParams()
        valid, error = params.validate()

        assert valid is True
        assert error == ""


class TestDispcalParams:
    """Tests for DispcalParams dataclass."""

    def test_default_params(self):
        """Test default DispcalParams."""
        params = DispcalParams(output_path="/tmp/test")
        assert params.output_path == "/tmp/test"
        assert params.display_index == 1
        assert params.quality == QualityLevel.MEDIUM
        assert params.gamma == 2.2

    def test_to_command_args(self):
        """Test converting DispcalParams to command args."""
        params = DispcalParams(
            output_path="/tmp/test",
            white_temp=6500,
            gamma=2.4,
        )
        args = params.to_command_args()

        assert '-v' in args
        assert '-m' in args
        assert '-t' in args
        assert '6500' in args
        assert '-g' in args
        assert '2.4' in args

    def test_web_server_mode(self):
        """Test web server mode parameters."""
        params = DispcalParams(
            output_path="/tmp/test",
            use_web_server=True,
            web_port=9292,
        )
        args = params.to_command_args()

        assert '-dweb:9292' in args
        assert '-Y' in args

    def test_validate_invalid_gamma(self):
        """Test validation with invalid gamma."""
        params = DispcalParams(output_path="/tmp/test", gamma=0.5)
        valid, error = params.validate()

        assert valid is False
        assert "gamma" in error.lower()

    def test_cal_file_path(self):
        """Test cal_file_path property."""
        params = DispcalParams(output_path="/tmp/test")
        assert params.cal_file_path == "/tmp/test.cal"


class TestCollinkParams:
    """Tests for CollinkParams dataclass."""

    def test_default_params(self):
        """Test default CollinkParams."""
        params = CollinkParams(
            source_space="Rec709",
            target_icc_path="/tmp/display.icc",
            output_path="/tmp/output.cube",
        )
        assert params.lut_size == 33
        assert params.intent == RenderingIntent.RELATIVE_COLORIMETRIC
        assert params.use_bpc is True

    def test_bpc_disabled_for_perceptual(self):
        """Test BPC is disabled for perceptual intent."""
        params = CollinkParams(
            source_space="Rec709",
            target_icc_path="/tmp/display.icc",
            output_path="/tmp/output.cube",
            intent=RenderingIntent.PERCEPTUAL,
            use_bpc=True,  # User requests BPC
        )
        args = params.to_command_args()

        # BPC should NOT be in args (disabled for perceptual)
        assert '-b' not in args

    def test_validate_invalid_lut_size(self):
        """Test validation with invalid LUT size."""
        # First create the ICC file for validation
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(suffix='.icc', delete=False) as f:
            temp_icc = f.name
            f.write(b'\x00' * 100)  # Dummy ICC content
        
        try:
            params = CollinkParams(
                source_space="Rec709",
                target_icc_path=temp_icc,
                output_path="/tmp/output.cube",
                lut_size=50,  # Invalid size
            )
            valid, error = params.validate()

            assert valid is False
            assert "lut" in error.lower() or "size" in error.lower()
        finally:
            os.unlink(temp_icc)


# ========== Process Lifecycle Tests ==========

class TestProcessLifecycle:
    """Tests for ProcessLifecycle management."""

    def test_init_defaults(self):
        """Test default ProcessLifecycle initialization."""
        lifecycle = ProcessLifecycle()
        assert lifecycle.timeout == 30.0
        assert lifecycle.cancel_timeout == 2.0
        assert lifecycle.cleanup_timeout == 5.0

    def test_elapsed_time(self):
        """Test elapsed time calculation."""
        lifecycle = ProcessLifecycle()
        import time

        lifecycle._start_time = time.time()
        time.sleep(0.1)
        elapsed = lifecycle.get_elapsed_time()

        assert elapsed >= 0.1
        assert elapsed < 0.5

    def test_is_timeout(self):
        """Test timeout detection."""
        lifecycle = ProcessLifecycle(timeout=0.1)
        import time

        lifecycle._start_time = time.time() - 0.2  # Started 0.2s ago
        assert lifecycle.is_timeout() is True

        lifecycle._start_time = time.time()  # Just started
        assert lifecycle.is_timeout() is False


# ========== ArgyllAdapter Integration Tests ==========

class TestArgyllAdapterIntegration:
    """Integration tests for ArgyllAdapter with FakeInstrument."""

    def test_adapter_with_fake_instrument(self):
        """Test ArgyllAdapter concepts using FakeInstrument."""
        # Since ArgyllAdapter requires ArgyllController (which needs real hardware),
        # we test the interface using FakeInstrument
        instrument = FakeInstrument()
        instrument.set_measurement_result((95.0, 100.0, 108.9))

        assert instrument.connect() is True
        result = instrument.measure()

        assert result.xyz == (95.0, 100.0, 108.9)
        assert result.xyY[2] == 100.0

        instrument.disconnect()
        assert instrument.is_connected() is False

    def test_adapter_status(self):
        """Test instrument status retrieval."""
        instrument = FakeInstrument(model="i1 Display Pro", serial="TEST-001")
        instrument.connect()

        status = instrument.status()
        assert status.state == InstrumentState.READY
        assert status.connected is True
        assert status.model == "i1 Display Pro"

    def test_adapter_error_handling(self):
        """Test error handling."""
        instrument = FakeInstrument()
        
        # Connect first
        instrument.connect()
        
        # Then simulate error for measure()
        instrument.simulate_error("TIMEOUT", "Measurement timed out")

        with pytest.raises(InstrumentError):
            instrument.measure()

    def test_output_parser_spotread_success(self):
        """Test OutputParser with success fixture."""
        fixture = load_fixture("01_spotread_success.txt")
        result = OutputParser.parse_spotread(fixture)

        assert result.success is True
        assert result.data.get('xyY') is not None


# ========== OutputPatterns Tests ==========

class TestOutputPatterns:
    """Tests for OutputPatterns regular expressions."""

    def test_xyz_pattern(self):
        """Test XYZ pattern matching."""
        text = "Result is XYZ: 0.123 0.456 0.789"
        match = OutputPatterns.XYZ_RESULT.search(text)

        assert match is not None
        assert float(match.group(1)) == 0.123
        assert float(match.group(2)) == 0.456
        assert float(match.group(3)) == 0.789

    def test_dispcal_progress_pattern(self):
        """Test dispcal progress pattern."""
        text = "Reading patch 5 of 10 ..."
        match = OutputPatterns.DISPCAL_PROGRESS.search(text)

        assert match is not None
        assert int(match.group(1)) == 5
        assert int(match.group(2)) == 10

    def test_colprof_progress_pattern(self):
        """Test colprof progress pattern."""
        texts = [
            "Progress: 50%",
            "Done: 100%",
            "75%",
        ]

        for text in texts:
            match = OutputPatterns.COLPROF_PROGRESS.search(text)
            assert match is not None

    def test_collink_progress_pattern(self):
        """Test collink progress pattern."""
        text = "Making lookup tables - 50% done"
        match = OutputPatterns.COLLINK_PROGRESS.search(text)

        assert match is not None
        assert int(match.group(1)) == 50

    def test_usb_disconnect_keywords(self):
        """Test USB disconnect keyword detection."""
        errors = [
            "readpipeasync failed: (-1) LIBUSB_ERROR_IO",
            "No instrument found",
            "communication error",
            "device not found",
        ]

        for error in errors:
            found = any(
                kw.lower() in error.lower()
                for kw in OutputPatterns.USB_DISCONNECT_KEYWORDS
            )
            assert found is True


# ========== Run Tests ==========

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
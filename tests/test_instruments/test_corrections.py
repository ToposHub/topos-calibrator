"""
Unit tests for correction file management module.

Tests cover:
- CCSS/CCMX file parsing
- Metadata extraction
- Compatibility checking
- Hash calculation
- CCMX creation wizard

Reference: docs/professional_optimization_plan.md - Task P3-D
"""

import json
import os
import tempfile
import hashlib
from datetime import datetime
from pathlib import Path
from unittest import TestCase

from src.instruments.corrections import (
    CorrectionType,
    CorrectionMetadata,
    CorrectionFileParser,
    CorrectionManager,
    CCMXCreationWizard,
    DisplayTechnology,
    ProbeInfo,
    CompatibilityResult,
    create_correction_manager,
    parse_correction_file,
)


class TestCorrectionType(TestCase):
    """Test CorrectionType enum."""

    def test_ccss_type(self):
        """Test CCSS type identification."""
        self.assertEqual(CorrectionType.CCSS.value, "ccss")

    def test_ccmx_type(self):
        """Test CCMX type identification."""
        self.assertEqual(CorrectionType.CCMX.value, "ccmx")


class TestDisplayTechnology(TestCase):
    """Test DisplayTechnology enum and conversions."""

    def test_from_argyll_code(self):
        """Test conversion from ArgyllCMS code."""
        self.assertEqual(
            DisplayTechnology.from_argyll_code("l"),
            DisplayTechnology.LCD_GENERIC
        )
        self.assertEqual(
            DisplayTechnology.from_argyll_code("o"),
            DisplayTechnology.OLED
        )
        self.assertEqual(
            DisplayTechnology.from_argyll_code("e"),
            DisplayTechnology.LCD_WHITE_LED
        )

    def test_from_argyll_code_unknown(self):
        """Test unknown ArgyllCMS code."""
        self.assertIsNone(DisplayTechnology.from_argyll_code("x"))

    def test_from_display_name_oled(self):
        """Test OLED detection from name."""
        self.assertEqual(
            DisplayTechnology.from_display_name("OLED"),
            DisplayTechnology.OLED
        )
        self.assertEqual(
            DisplayTechnology.from_display_name("LG OLED TV"),
            DisplayTechnology.WOLED
        )
        self.assertEqual(
            DisplayTechnology.from_display_name("AMOLED display"),
            DisplayTechnology.AMOLED
        )

    def test_from_display_name_lcd(self):
        """Test LCD detection from name."""
        self.assertEqual(
            DisplayTechnology.from_display_name("LCD"),
            DisplayTechnology.LCD_GENERIC
        )
        self.assertEqual(
            DisplayTechnology.from_display_name("LCD RGB LED"),
            DisplayTechnology.LCD_RGB_LED
        )
        self.assertEqual(
            DisplayTechnology.from_display_name("IPS White LED"),
            DisplayTechnology.LCD_WHITE_LED
        )
        self.assertEqual(
            DisplayTechnology.from_display_name("Quantum Dot LCD"),
            DisplayTechnology.LCD_PFS_PHOSPHOR
        )

    def test_get_display_name(self):
        """Test display name generation."""
        self.assertEqual(
            DisplayTechnology.OLED.get_display_name(),
            "OLED"
        )
        self.assertEqual(
            DisplayTechnology.LCD_GENERIC.get_display_name(),
            "LCD (通用)"
        )
        self.assertEqual(
            DisplayTechnology.WOLED.get_display_name(),
            "WOLED (LG OLED)"
        )


class TestProbeInfo(TestCase):
    """Test ProbeInfo class."""

    def test_spectrophotometer_detection(self):
        """Test spectrophotometer probe detection."""
        info = ProbeInfo.from_argyll_type("i1pro2")
        self.assertEqual(info.name, "i1 Pro 2")
        self.assertTrue(info.is_spectrophotometer)
        self.assertFalse(info.is_colorimeter)

    def test_colorimeter_detection(self):
        """Test colorimeter probe detection."""
        info = ProbeInfo.from_argyll_type("i1d3")
        self.assertEqual(info.name, "i1 Display Pro")
        self.assertFalse(info.is_spectrophotometer)
        self.assertTrue(info.is_colorimeter)

    def test_unknown_probe(self):
        """Test unknown probe type."""
        info = ProbeInfo.from_argyll_type("unknown_probe")
        self.assertEqual(info.name, "unknown_probe")
        self.assertFalse(info.is_spectrophotometer)
        self.assertFalse(info.is_colorimeter)


class TestCorrectionFileParser(TestCase):
    """Test correction file parser."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = CorrectionFileParser()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def _create_ccmx_file(self, content: str) -> str:
        """Create temporary CCMX file."""
        path = os.path.join(self.temp_dir, "test.ccmx")
        with open(path, 'w') as f:
            f.write(content)
        return path

    def _create_ccss_file(self, content: str) -> str:
        """Create temporary CCSS file."""
        path = os.path.join(self.temp_dir, "test.ccss")
        with open(path, 'w') as f:
            f.write(content)
        return path

    def test_parse_ccmx_file(self):
        """Test parsing valid CCMX file."""
        content = """CCMX

DESCRIPTOR "i1d3 & LCD"
INSTRUMENT "i1d3"
TECHNOLOGY "l"
DISPLAY_TYPE_BASE_ID "1"
DISPLAY_TYPE_REFRESH "NO"
REFERENCE "i1pro2"
ORIGINATOR "Argyll ccmx"
CREATED "Sun Apr  5 07:45:00 2026"
COLOR_REP "XYZ"

NUMBER_OF_FIELDS 3
BEGIN_DATA_FORMAT
XYZ_X XYZ_Y XYZ_Z
END_DATA_FORMAT

NUMBER_OF_SETS 3
BEGIN_DATA
1.051322 -0.0242306 -0.0119285
0.0144179 0.990586 -0.00333015
0.0172358 -0.0122439 0.987409
END_DATA
"""
        path = self._create_ccmx_file(content)
        metadata = self.parser.parse_file(path)

        self.assertTrue(metadata.is_valid)
        self.assertEqual(metadata.correction_type, CorrectionType.CCMX)
        self.assertEqual(metadata.descriptor, "i1d3 & LCD")
        self.assertEqual(metadata.instrument, "i1d3")
        self.assertEqual(metadata.technology, "l")
        self.assertEqual(metadata.reference_instrument, "i1pro2")
        self.assertIsNotNone(metadata.created)
        self.assertIsNotNone(metadata.matrix)
        self.assertEqual(len(metadata.matrix), 3)
        self.assertEqual(len(metadata.matrix[0]), 3)

    def test_parse_ccss_file(self):
        """Test parsing valid CCSS file."""
        content = """CCSS

DESCRIPTOR "i1 Display Pro, LCD White LED"
INSTRUMENT "i1d3"
TECHNOLOGY "e"
ORIGINATOR "Argyll ccss"
CREATED "Mon Jan  1 10:00:00 2025"
COLOR_REP "SPECTRAL"

NUMBER_OF_FIELDS 36
BEGIN_DATA_FORMAT
SPECTRAL_NM_380 SPECTRAL_NM_390 ... SPECTRAL_NM_730
END_DATA_FORMAT

NUMBER_OF_SETS 1
BEGIN_DATA
0.01 0.02 0.03 ...
END_DATA
"""
        path = self._create_ccss_file(content)
        metadata = self.parser.parse_file(path)

        self.assertTrue(metadata.is_valid)
        self.assertEqual(metadata.correction_type, CorrectionType.CCSS)
        self.assertEqual(metadata.descriptor, "i1 Display Pro, LCD White LED")
        self.assertEqual(metadata.instrument, "i1d3")
        self.assertEqual(metadata.technology, "e")

    def test_parse_file_hash(self):
        """Test file hash calculation."""
        content = """CCMX

DESCRIPTOR "Test"
INSTRUMENT "i1d3"
REFERENCE "i1pro2"

BEGIN_DATA
1.0 0.0 0.0
0.0 1.0 0.0
0.0 0.0 1.0
END_DATA
"""
        path = self._create_ccmx_file(content)
        metadata = self.parser.parse_file(path)

        # Verify hash is calculated
        self.assertTrue(len(metadata.file_hash) == 64)  # SHA-256 hex length

        # Verify hash is correct
        with open(path, 'rb') as f:
            expected_hash = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(metadata.file_hash, expected_hash)

    def test_parse_invalid_file(self):
        """Test parsing invalid/corrupt file."""
        content = """INVALID FORMAT

NO VALID STRUCTURE
"""
        path = self._create_ccmx_file(content)
        metadata = self.parser.parse_file(path)

        self.assertFalse(metadata.is_valid)
        self.assertTrue(len(metadata.parse_errors) > 0)

    def test_parse_missing_fields(self):
        """Test parsing file with missing required fields."""
        content = """CCMX

DESCRIPTOR "Incomplete"

BEGIN_DATA
1.0 0.0 0.0
END_DATA
"""
        path = self._create_ccmx_file(content)
        metadata = self.parser.parse_file(path)

        self.assertFalse(metadata.is_valid)
        # Should have errors about missing instrument and reference

    def test_parse_created_timestamp(self):
        """Test parsing various timestamp formats."""
        # Test ArgyllCMS format
        ts1 = self.parser._parse_created_timestamp("Sun Apr  5 07:45:00 2026")
        self.assertIsNotNone(ts1)
        self.assertEqual(ts1.year, 2026)

        # Test ISO format
        ts2 = self.parser._parse_created_timestamp("2026-04-05 07:45:00")
        self.assertIsNotNone(ts2)

        # Test compact format
        ts3 = self.parser._parse_created_timestamp("20260405_074500")
        self.assertIsNotNone(ts3)


class TestCorrectionMetadata(TestCase):
    """Test CorrectionMetadata dataclass."""

    def test_to_dict(self):
        """Test serialization to dictionary."""
        metadata = CorrectionMetadata(
            file_path="/path/to/file.ccmx",
            file_hash="abc123",
            correction_type=CorrectionType.CCMX,
            descriptor="Test CCMX",
            instrument="i1d3",
            technology="l",
            reference_instrument="i1pro2",
            created=datetime(2026, 4, 5, 7, 45, 0),
            is_valid=True,
        )

        data = metadata.to_dict()

        self.assertEqual(data["filename"], "file.ccmx")
        self.assertEqual(data["correction_type"], "ccmx")
        self.assertEqual(data["descriptor"], "Test CCMX")
        self.assertEqual(data["instrument"], "i1d3")
        self.assertEqual(data["technology_display"], "LCD (通用)")
        self.assertTrue(data["is_valid"])

    def test_filename_property(self):
        """Test filename extraction."""
        metadata = CorrectionMetadata(file_path="/path/to/test.ccmx")
        self.assertEqual(metadata.filename, "test.ccmx")

    def test_display_technology_property(self):
        """Test display technology conversion."""
        metadata = CorrectionMetadata(technology="o")
        tech = metadata.display_technology
        self.assertEqual(tech, DisplayTechnology.OLED)


class TestCorrectionManager(TestCase):
    """Test CorrectionManager class."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = CorrectionManager(self.temp_dir)

        # Create sample correction files
        self._create_sample_ccmx()
        self._create_sample_ccss()

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def _create_sample_ccmx(self) -> str:
        """Create sample CCMX file."""
        content = """CCMX

DESCRIPTOR "i1d3 & LCD"
INSTRUMENT "i1d3"
TECHNOLOGY "l"
REFERENCE "i1pro2"
ORIGINATOR "Argyll ccmx"
CREATED "Sun Apr  5 07:45:00 2026"
COLOR_REP "XYZ"

NUMBER_OF_FIELDS 3
BEGIN_DATA_FORMAT
XYZ_X XYZ_Y XYZ_Z
END_DATA_FORMAT

NUMBER_OF_SETS 3
BEGIN_DATA
1.051322 -0.0242306 -0.0119285
0.0144179 0.990586 -0.00333015
0.0172358 -0.0122439 0.987409
END_DATA
"""
        path = os.path.join(self.temp_dir, "sample.ccmx")
        with open(path, 'w') as f:
            f.write(content)
        return path

    def _create_sample_ccss(self) -> str:
        """Create sample CCSS file."""
        content = """CCSS

DESCRIPTOR "i1 Display Pro, OLED"
INSTRUMENT "i1d3"
TECHNOLOGY "o"
ORIGINATOR "Argyll ccss"
CREATED "Mon Jan  1 10:00:00 2025"
COLOR_REP "SPECTRAL"

NUMBER_OF_FIELDS 36
BEGIN_DATA_FORMAT
NM_380 NM_390 NM_400
END_DATA_FORMAT

NUMBER_OF_SETS 1
BEGIN_DATA
0.01 0.02 0.03
END_DATA
"""
        path = os.path.join(self.temp_dir, "sample.ccss")
        with open(path, 'w') as f:
            f.write(content)
        return path

    def test_scan_correction_files(self):
        """Test scanning correction files."""
        files = self.manager.scan_correction_files()

        self.assertEqual(len(files), 2)

        # Check file types
        ccmx_found = False
        ccss_found = False
        for f in files:
            if f.correction_type == CorrectionType.CCMX:
                ccmx_found = True
            elif f.correction_type == CorrectionType.CCSS:
                ccss_found = True

        self.assertTrue(ccmx_found)
        self.assertTrue(ccss_found)

    def test_get_correction_by_path(self):
        """Test getting correction by path."""
        path = os.path.join(self.temp_dir, "sample.ccmx")
        metadata = self.manager.get_correction_by_path(path)

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.correction_type, CorrectionType.CCMX)

    def test_get_correction_by_hash(self):
        """Test getting correction by hash."""
        # First scan to populate hash index
        self.manager.scan_correction_files()

        path = os.path.join(self.temp_dir, "sample.ccmx")
        metadata = self.manager.get_correction_by_path(path)

        if metadata:
            hash_lookup = self.manager.get_correction_by_hash(metadata.file_hash)
            self.assertIsNotNone(hash_lookup)
            self.assertEqual(hash_lookup.file_path, path)

    def test_check_compatibility_matching_probe(self):
        """Test compatibility check with matching probe."""
        path = os.path.join(self.temp_dir, "sample.ccmx")
        metadata = self.manager.get_correction_by_path(path)

        result = self.manager.check_compatibility(metadata, "i1d3")

        # Should be compatible (matching probe)
        self.assertTrue(result.is_compatible)

    def test_check_compatibility_mismatched_probe(self):
        """Test compatibility check with mismatched probe."""
        path = os.path.join(self.temp_dir, "sample.ccmx")
        metadata = self.manager.get_correction_by_path(path)

        result = self.manager.check_compatibility(metadata, "spydx")

        # Should not be compatible (mismatched probe)
        self.assertFalse(result.is_compatible)
        self.assertTrue(len(result.errors) > 0)

    def test_check_compatibility_matching_display(self):
        """Test compatibility check with matching display technology."""
        path = os.path.join(self.temp_dir, "sample.ccmx")
        metadata = self.manager.get_correction_by_path(path)

        result = self.manager.check_compatibility(
            metadata, "i1d3", DisplayTechnology.LCD_GENERIC
        )

        self.assertTrue(result.is_compatible)

    def test_check_compatibility_mismatched_display(self):
        """Test compatibility check with mismatched display technology."""
        # Use OLED CCSS file
        path = os.path.join(self.temp_dir, "sample.ccss")
        metadata = self.manager.get_correction_by_path(path)

        # Check against LCD display
        result = self.manager.check_compatibility(
            metadata, "i1d3", DisplayTechnology.LCD_GENERIC
        )

        # Should have warning about mismatched display
        self.assertTrue(len(result.warnings) > 0)

    def test_check_compatibility_spectrophotometer(self):
        """Test that spectrophotometer gets warning for CCMX."""
        path = os.path.join(self.temp_dir, "sample.ccmx")
        metadata = self.manager.get_correction_by_path(path)

        # Spectrophotometer doesn't need CCMX
        result = self.manager.check_compatibility(metadata, "i1pro2")

        self.assertTrue(len(result.warnings) > 0)

    def test_get_correction_files_json(self):
        """Test JSON output format."""
        json_str = self.manager.get_correction_files_json()

        # Should be valid JSON
        data = json.loads(json_str)

        # Should have expected structure
        self.assertTrue(len(data) == 2)
        for item in data:
            self.assertIn("name", item)
            self.assertIn("path", item)
            self.assertIn("type", item)
            self.assertIn("descriptor", item)
            self.assertIn("instrument", item)
            self.assertIn("technology", item)
            self.assertIn("hash", item)


class TestCCMXCreationWizard(TestCase):
    """Test CCMX creation wizard."""

    def setUp(self):
        """Set up wizard instance."""
        self.wizard = CCMXCreationWizard()

    def test_start_wizard_valid(self):
        """Test starting wizard with valid probes."""
        result = self.wizard.start_wizard(
            reference_probe="i1pro2",
            target_probe="i1d3",
            display_technology="l",
            display_name="LCD Monitor"
        )

        self.assertTrue(result)
        self.assertEqual(self.wizard.state, CCMXCreationWizard.WizardState.IDLE)
        self.assertEqual(self.wizard.config.reference_probe_type, "i1pro2")
        self.assertEqual(self.wizard.config.target_probe_type, "i1d3")

    def test_start_wizard_invalid_reference(self):
        """Test starting wizard with non-spectrophotometer reference."""
        result = self.wizard.start_wizard(
            reference_probe="i1d3",  # Colorimeter, not spectrophotometer
            target_probe="spydx"
        )

        self.assertFalse(result)

    def test_start_wizard_invalid_target(self):
        """Test starting wizard with spectrophotometer as target."""
        result = self.wizard.start_wizard(
            reference_probe="i1pro2",
            target_probe="i1pro3"  # Spectrophotometer, not colorimeter
        )

        self.assertFalse(result)

    def test_set_reference_measurements_valid(self):
        """Test setting valid reference measurements."""
        self.wizard.start_wizard("i1pro2", "i1d3")

        measurements = {
            "white": {"xyY": (0.3127, 0.329, 100.0)},
            "red": {"xyY": (0.64, 0.33, 20.0)},
            "green": {"xyY": (0.30, 0.60, 50.0)},
            "blue": {"xyY": (0.15, 0.06, 10.0)},
        }

        result = self.wizard.set_reference_measurements(measurements)

        self.assertTrue(result)
        self.assertEqual(
            self.wizard.state,
            CCMXCreationWizard.WizardState.REFERENCE_COMPLETE
        )

    def test_set_reference_measurements_incomplete(self):
        """Test setting incomplete reference measurements."""
        self.wizard.start_wizard("i1pro2", "i1d3")

        measurements = {
            "white": {"xyY": (0.3127, 0.329, 100.0)},
            "red": {"xyY": (0.64, 0.33, 20.0)},
            # Missing green and blue
        }

        result = self.wizard.set_reference_measurements(measurements)

        self.assertFalse(result)

    def test_set_target_measurements_valid(self):
        """Test setting valid target measurements."""
        self.wizard.start_wizard("i1pro2", "i1d3")
        self.wizard.set_reference_measurements({
            "white": {"xyY": (0.3127, 0.329, 100.0)},
            "red": {"xyY": (0.64, 0.33, 20.0)},
            "green": {"xyY": (0.30, 0.60, 50.0)},
            "blue": {"xyY": (0.15, 0.06, 10.0)},
        })

        measurements = {
            "white": {"xyY": (0.310, 0.325, 98.0)},
            "red": {"xyY": (0.62, 0.32, 18.0)},
            "green": {"xyY": (0.28, 0.58, 48.0)},
            "blue": {"xyY": (0.14, 0.05, 9.0)},
        }

        result = self.wizard.set_target_measurements(measurements)

        self.assertTrue(result)
        self.assertEqual(
            self.wizard.state,
            CCMXCreationWizard.WizardState.TARGET_COMPLETE
        )

    def test_can_generate_ccmx(self):
        """Test CCMX generation readiness check."""
        self.wizard.start_wizard("i1pro2", "i1d3")

        # Not ready at start
        self.assertFalse(self.wizard.can_generate_ccmx())

        # Set reference
        self.wizard.set_reference_measurements({
            "white": {"xyY": (0.3127, 0.329, 100.0)},
            "red": {"xyY": (0.64, 0.33, 20.0)},
            "green": {"xyY": (0.30, 0.60, 50.0)},
            "blue": {"xyY": (0.15, 0.06, 10.0)},
        })
        self.assertFalse(self.wizard.can_generate_ccmx())

        # Set target
        self.wizard.set_target_measurements({
            "white": {"xyY": (0.310, 0.325, 98.0)},
            "red": {"xyY": (0.62, 0.32, 18.0)},
            "green": {"xyY": (0.28, 0.58, 48.0)},
            "blue": {"xyY": (0.14, 0.05, 9.0)},
        })
        self.assertTrue(self.wizard.can_generate_ccmx())

    def test_get_ccmx_creation_params(self):
        """Test getting CCMX creation parameters."""
        self.wizard.start_wizard("i1pro2", "i1d3", display_technology="o")
        self.wizard.set_reference_measurements({
            "white": {"xyY": (0.3127, 0.329, 100.0)},
            "red": {"xyY": (0.64, 0.33, 20.0)},
            "green": {"xyY": (0.30, 0.60, 50.0)},
            "blue": {"xyY": (0.15, 0.06, 10.0)},
        })
        self.wizard.set_target_measurements({
            "white": {"xyY": (0.310, 0.325, 98.0)},
            "red": {"xyY": (0.62, 0.32, 18.0)},
            "green": {"xyY": (0.28, 0.58, 48.0)},
            "blue": {"xyY": (0.14, 0.05, 9.0)},
        })

        params = self.wizard.get_ccmx_creation_params()

        self.assertEqual(params["reference_probe"], "i1pro2")
        self.assertEqual(params["target_probe"], "i1d3")
        self.assertEqual(params["display_technology"], "o")
        self.assertIn("reference_measurements", params)
        self.assertIn("target_measurements", params)

    def test_reset(self):
        """Test wizard reset."""
        self.wizard.start_wizard("i1pro2", "i1d3")
        self.wizard.set_reference_measurements({
            "white": {"xyY": (0.3127, 0.329, 100.0)},
            "red": {"xyY": (0.64, 0.33, 20.0)},
            "green": {"xyY": (0.30, 0.60, 50.0)},
            "blue": {"xyY": (0.15, 0.06, 10.0)},
        })

        self.wizard.reset()

        self.assertEqual(self.wizard.state, CCMXCreationWizard.WizardState.IDLE)
        self.assertEqual(self.wizard.config.reference_probe_type, "")


class TestCompatibilityResult(TestCase):
    """Test CompatibilityResult dataclass."""

    def test_to_dict(self):
        """Test serialization."""
        result = CompatibilityResult(
            is_compatible=False,
            warnings=["Warning 1"],
            errors=["Error 1"],
            suggestions=["Suggestion 1"]
        )

        data = result.to_dict()

        self.assertFalse(data["is_compatible"])
        self.assertEqual(data["warnings"], ["Warning 1"])
        self.assertEqual(data["errors"], ["Error 1"])


class TestProbeRelation(TestCase):
    """Test probe family relationship detection."""

    def test_i1d3_family(self):
        """Test i1 Display family probes are related."""
        manager = CorrectionManager(tempfile.mkdtemp())

        self.assertTrue(manager._are_probes_related("i1d3", "i1d3"))
        self.assertTrue(manager._are_probes_related("i1d3", "i1d2"))
        self.assertFalse(manager._are_probes_related("i1d3", "spydx"))

    def test_spyder_family(self):
        """Test Spyder family probes are related."""
        manager = CorrectionManager(tempfile.mkdtemp())

        self.assertTrue(manager._are_probes_related("spydx", "spydx"))
        self.assertTrue(manager._are_probes_related("spydx", "spyd5"))
        self.assertFalse(manager._are_probes_related("spydx", "i1d3"))

    def test_i1pro_family(self):
        """Test i1 Pro family probes are related."""
        manager = CorrectionManager(tempfile.mkdtemp())

        self.assertTrue(manager._are_probes_related("i1pro", "i1pro2"))
        self.assertTrue(manager._are_probes_related("i1pro2", "i1pro3"))


class TestTechnologyCompatibility(TestCase):
    """Test display technology compatibility."""

    def test_lcd_generic_compatibility(self):
        """Test generic LCD is compatible with all LCD variants (but not OLED/CRT)."""
        manager = CorrectionManager(tempfile.mkdtemp())

        self.assertTrue(manager._are_technologies_compatible("l", "e"))
        self.assertTrue(manager._are_technologies_compatible("l", "b"))
        self.assertFalse(manager._are_technologies_compatible("l", "o"))  # OLED is separate
        self.assertFalse(manager._are_technologies_compatible("l", "c"))  # CRT

    def test_oled_compatibility(self):
        """Test OLED variants are compatible (WOLED only, AMOLED is separate)."""
        manager = CorrectionManager(tempfile.mkdtemp())

        self.assertTrue(manager._are_technologies_compatible("o", "o"))
        self.assertTrue(manager._are_technologies_compatible("o", "w"))  # WOLED
        # AMOLED 'a' is separate from generic OLED 'o' in ArgyllCMS
        self.assertFalse(manager._are_technologies_compatible("o", "a"))  # AMOLED

    def test_exact_match(self):
        """Test exact match is compatible."""
        manager = CorrectionManager(tempfile.mkdtemp())

        self.assertTrue(manager._are_technologies_compatible("e", "e"))
        self.assertTrue(manager._are_technologies_compatible("b", "b"))


class TestConvenienceFunctions(TestCase):
    """Test convenience functions."""

    def test_create_correction_manager(self):
        """Test correction manager creation."""
        manager = create_correction_manager(tempfile.mkdtemp())
        self.assertIsInstance(manager, CorrectionManager)

    def test_parse_correction_file(self):
        """Test single file parsing."""
        # Create temp file
        temp_dir = tempfile.mkdtemp()
        content = """CCMX

DESCRIPTOR "Test"
INSTRUMENT "i1d3"
REFERENCE "i1pro2"

BEGIN_DATA
1.0 0.0 0.0
0.0 1.0 0.0
0.0 0.0 1.0
END_DATA
"""
        path = os.path.join(temp_dir, "test.ccmx")
        with open(path, 'w') as f:
            f.write(content)

        metadata = parse_correction_file(path)

        self.assertIsInstance(metadata, CorrectionMetadata)
        self.assertEqual(metadata.correction_type, CorrectionType.CCMX)

        # Cleanup
        import shutil
        shutil.rmtree(temp_dir)


if __name__ == '__main__':
    import unittest
    unittest.main()
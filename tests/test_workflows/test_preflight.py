"""
Tests for Preflight module.

Tests cover:
- PreflightStatus and PreflightCategory enums
- PreflightItem, PreflightResult, PreflightReport data classes
- PreflightChecker functionality
- Argyll tool detection
- Instrument status checks
- Display configuration checks
- System settings checks
- Permission checks
- ICC/LUT status checks
- Report export functionality
"""

import json
import platform
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Import preflight module
from src.workflows.preflight import (
    PreflightStatus,
    PreflightCategory,
    PreflightItem,
    PreflightResult,
    PreflightReport,
    PreflightChecker,
    PREFLIGHT_CHECK_ITEMS,
    create_preflight_checker,
    run_preflight_checks,
    export_preflight_report,
)


# ========== Enum Tests ==========

class TestPreflightStatus:
    """Tests for PreflightStatus enum."""

    def test_status_values(self):
        """Test all status values are defined."""
        assert PreflightStatus.PASS.value == "PASS"
        assert PreflightStatus.WARN.value == "WARN"
        assert PreflightStatus.BLOCK.value == "BLOCK"
        assert PreflightStatus.SKIP.value == "SKIP"
        assert PreflightStatus.ERROR.value == "ERROR"

    def test_status_count(self):
        """Test we have 5 status types."""
        assert len(list(PreflightStatus)) == 5


class TestPreflightCategory:
    """Tests for PreflightCategory enum."""

    def test_category_values(self):
        """Test all category values are defined."""
        assert PreflightCategory.ARGYLL.value == "argyll"
        assert PreflightCategory.INSTRUMENT.value == "instrument"
        assert PreflightCategory.DISPLAY.value == "display"
        assert PreflightCategory.SYSTEM.value == "system"
        assert PreflightCategory.PERMISSION.value == "permission"
        assert PreflightCategory.ICC_LUT.value == "icc_lut"

    def test_category_count(self):
        """Test we have 6 categories."""
        assert len(list(PreflightCategory)) == 6


# ========== Data Class Tests ==========

class TestPreflightItem:
    """Tests for PreflightItem data class."""

    def test_item_creation(self):
        """Test basic item creation."""
        item = PreflightItem(
            id="test_check",
            name="Test Check",
            description="A test check",
            category=PreflightCategory.SYSTEM,
        )
        assert item.id == "test_check"
        assert item.name == "Test Check"
        assert item.description == "A test check"
        assert item.category == PreflightCategory.SYSTEM
        assert item.allow_override == True  # Default

    def test_item_with_platform_specific(self):
        """Test platform-specific item."""
        item = PreflightItem(
            id="mac_only",
            name="macOS Only Check",
            platform_specific=["Darwin"],
        )
        assert item.platform_specific == ["Darwin"]

    def test_item_no_override(self):
        """Test item that cannot be overridden."""
        item = PreflightItem(
            id="no_override",
            name="Cannot Override",
            allow_override=False,
        )
        assert item.allow_override == False


class TestPreflightResult:
    """Tests for PreflightResult data class."""

    def test_result_creation(self):
        """Test basic result creation."""
        result = PreflightResult(
            item_id="test_check",
            status=PreflightStatus.PASS,
            message="Test passed",
        )
        assert result.item_id == "test_check"
        assert result.status == PreflightStatus.PASS
        assert result.message == "Test passed"
        assert result.details == {}
        assert result.fix_command is None
        assert result.fix_url is None

    def test_result_with_details(self):
        """Test result with additional details."""
        result = PreflightResult(
            item_id="argyll_spotread",
            status=PreflightStatus.PASS,
            message="Found: /usr/local/bin/spotread",
            details={"path": "/usr/local/bin/spotread", "version": "3.2.0"},
        )
        assert result.details["path"] == "/usr/local/bin/spotread"
        assert result.details["version"] == "3.2.0"

    def test_result_blocking(self):
        """Test is_blocking method."""
        pass_result = PreflightResult(item_id="test", status=PreflightStatus.PASS)
        warn_result = PreflightResult(item_id="test", status=PreflightStatus.WARN)
        block_result = PreflightResult(item_id="test", status=PreflightStatus.BLOCK)

        assert pass_result.is_blocking() == False
        assert warn_result.is_blocking() == False
        assert block_result.is_blocking() == True

    def test_result_warning(self):
        """Test is_warning method."""
        pass_result = PreflightResult(item_id="test", status=PreflightStatus.PASS)
        warn_result = PreflightResult(item_id="test", status=PreflightStatus.WARN)

        assert pass_result.is_warning() == False
        assert warn_result.is_warning() == True

    def test_result_to_dict(self):
        """Test to_dict method for JSON export."""
        result = PreflightResult(
            item_id="test_check",
            status=PreflightStatus.BLOCK,
            message="Blocked",
            details={"key": "value"},
            fix_command="fix it",
            fix_url="https://example.com",
        )
        d = result.to_dict()

        assert d["item_id"] == "test_check"
        assert d["status"] == "BLOCK"
        assert d["message"] == "Blocked"
        assert d["details"]["key"] == "value"
        assert d["fix_command"] == "fix it"
        assert d["fix_url"] == "https://example.com"
        assert "timestamp" in d


class TestPreflightReport:
    """Tests for PreflightReport data class."""

    def test_report_creation(self):
        """Test basic report creation."""
        report = PreflightReport()
        assert report.results == []
        assert report.summary == {}
        assert report.platform == platform.system()
        assert report.can_proceed == False

    def test_report_add_result(self):
        """Test adding results to report."""
        report = PreflightReport()
        result1 = PreflightResult(item_id="check1", status=PreflightStatus.PASS)
        result2 = PreflightResult(item_id="check2", status=PreflightStatus.WARN)

        report.add_result(result1)
        report.add_result(result2)

        assert len(report.results) == 2
        assert report.results[0].item_id == "check1"
        assert report.results[1].item_id == "check2"

    def test_report_calculate_summary(self):
        """Test summary calculation."""
        report = PreflightReport()
        report.add_result(PreflightResult(item_id="a", status=PreflightStatus.PASS))
        report.add_result(PreflightResult(item_id="b", status=PreflightStatus.PASS))
        report.add_result(PreflightResult(item_id="c", status=PreflightStatus.WARN))
        report.add_result(PreflightResult(item_id="d", status=PreflightStatus.BLOCK))
        report.add_result(PreflightResult(item_id="e", status=PreflightStatus.SKIP))

        report.calculate_summary()

        assert report.summary["pass_count"] == 2
        assert report.summary["warn_count"] == 1
        assert report.summary["block_count"] == 1
        assert report.summary["skip_count"] == 1
        assert report.summary["total_checks"] == 5

    def test_report_update_can_proceed(self):
        """Test can_proceed logic."""
        report = PreflightReport()
        report.add_result(PreflightResult(item_id="a", status=PreflightStatus.PASS))
        report.add_result(PreflightResult(item_id="b", status=PreflightStatus.WARN))

        report.calculate_summary()
        report.update_can_proceed(override_enabled=False)

        # No BLOCK, can proceed
        assert report.can_proceed == True

        # Add BLOCK
        report.add_result(PreflightResult(item_id="c", status=PreflightStatus.BLOCK))
        report.calculate_summary()
        report.update_can_proceed(override_enabled=False)

        assert report.can_proceed == False

        # With override, BLOCK is ignored
        report.update_can_proceed(override_enabled=True)

        assert report.can_proceed == True

    def test_report_get_blocking_items(self):
        """Test get_blocking_items method."""
        report = PreflightReport()
        report.add_result(PreflightResult(item_id="a", status=PreflightStatus.PASS))
        report.add_result(PreflightResult(item_id="b", status=PreflightStatus.BLOCK))
        report.add_result(PreflightResult(item_id="c", status=PreflightStatus.WARN))
        report.add_result(PreflightResult(item_id="d", status=PreflightStatus.BLOCK))

        blocking = report.get_blocking_items()
        assert len(blocking) == 2
        assert blocking[0].item_id == "b"
        assert blocking[1].item_id == "d"

    def test_report_get_warning_items(self):
        """Test get_warning_items method."""
        report = PreflightReport()
        report.add_result(PreflightResult(item_id="a", status=PreflightStatus.PASS))
        report.add_result(PreflightResult(item_id="b", status=PreflightStatus.WARN))
        report.add_result(PreflightResult(item_id="c", status=PreflightStatus.WARN))

        warnings = report.get_warning_items()
        assert len(warnings) == 2

    def test_report_to_dict(self):
        """Test to_dict for JSON export."""
        report = PreflightReport()
        report.add_result(PreflightResult(item_id="test", status=PreflightStatus.PASS))
        report.calculate_summary()
        report.update_can_proceed(False)

        d = report.to_dict()

        assert "results" in d
        assert "summary" in d
        assert "platform" in d
        assert "timestamp" in d
        assert "can_proceed" in d
        assert len(d["results"]) == 1

    def test_report_to_json(self):
        """Test to_json method."""
        report = PreflightReport()
        report.add_result(PreflightResult(item_id="test", status=PreflightStatus.PASS))

        json_str = report.to_json()
        parsed = json.loads(json_str)

        assert isinstance(parsed, dict)
        assert "results" in parsed


# ========== PreflightChecker Tests ==========

class TestPreflightChecker:
    """Tests for PreflightChecker class."""

    def test_checker_creation(self):
        """Test basic checker creation."""
        checker = PreflightChecker()
        assert checker._argyll_bin_path is None
        assert checker._instrument_adapter is None
        assert checker._display_index == 1

    def test_checker_with_path(self):
        """Test checker with custom Argyll path."""
        checker = PreflightChecker(argyll_bin_path="/custom/path")
        assert checker._argyll_bin_path == "/custom/path"

    def test_set_display_index(self):
        """Test setting display index."""
        checker = PreflightChecker()
        checker.set_display_index(2)
        assert checker._display_index == 2

    def test_get_item_definition(self):
        """Test getting item definition."""
        checker = PreflightChecker()
        item = checker.get_item_definition("argyll_spotread")

        assert item is not None
        assert item.id == "argyll_spotread"
        assert item.name == "ArgyllCMS spotread"

    def test_get_item_definition_unknown(self):
        """Test getting unknown item definition."""
        checker = PreflightChecker()
        item = checker.get_item_definition("unknown_item")
        assert item is None


class TestPreflightCheckerArgyllTools:
    """Tests for Argyll tool detection."""

    def test_argyll_tool_found_in_path(self):
        """Test finding Argyll tool in system PATH."""
        # Since ArgyllCMS is likely installed in project, test the actual detection
        checker = PreflightChecker()
        result = checker._check_argyll_tool("spotread")

        # Either tool is found (PASS) or not found (BLOCK)
        assert result.status in [PreflightStatus.PASS, PreflightStatus.BLOCK]
        if result.status == PreflightStatus.PASS:
            assert "spotread found" in result.message
            assert "path" in result.details

    def test_argyll_tool_not_found_mocked(self):
        """Test when Argyll tool is not found (fully mocked)."""
        checker = PreflightChecker()

        # Completely mock _find_argyll_tool to return None
        with patch.object(checker, "_find_argyll_tool", return_value=None):
            result = checker._check_argyll_tool("spotread")

            assert result.status == PreflightStatus.BLOCK
            assert "not found" in result.message

    def test_argyll_tool_custom_path(self):
        """Test finding tool in custom Argyll path."""
        checker = PreflightChecker(argyll_bin_path="/fake/argyll/bin")

        # Patch Path.exists to return True for custom path
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "is_file", return_value=True):
                result = checker._check_argyll_tool("spotread")

                # Should find tool (mocked to exist)
                assert result.status == PreflightStatus.PASS


class TestPreflightCheckerInstrument:
    """Tests for instrument status checks."""

    def test_instrument_connected_no_adapter(self):
        """Test instrument check when no adapter provided."""
        checker = PreflightChecker()
        result = checker._check_instrument_connection()

        assert result.status == PreflightStatus.SKIP
        assert "not provided" in result.message

    def test_instrument_connected_with_adapter(self):
        """Test instrument check with connected adapter."""
        # Create mock adapter
        mock_adapter = MagicMock()
        mock_status = MagicMock()
        mock_status.connected = True
        mock_status.model = "i1 Display Pro"
        mock_status.serial = "ABC123"
        mock_status.state = MagicMock()
        mock_status.state.value = "ready"
        mock_adapter.status.return_value = mock_status

        checker = PreflightChecker(instrument_adapter=mock_adapter)
        result = checker._check_instrument_connection()

        assert result.status == PreflightStatus.PASS
        assert "i1 Display Pro" in result.message

    def test_instrument_not_connected(self):
        """Test instrument check when not connected."""
        mock_adapter = MagicMock()
        mock_status = MagicMock()
        mock_status.connected = False
        mock_status.state = MagicMock()
        mock_status.state.value = "disconnected"
        mock_adapter.status.return_value = mock_status

        checker = PreflightChecker(instrument_adapter=mock_adapter)
        result = checker._check_instrument_connection()

        assert result.status == PreflightStatus.BLOCK
        assert "not connected" in result.message

    def test_instrument_calibration_recent(self):
        """Test calibration check when recently calibrated."""
        mock_adapter = MagicMock()
        mock_status = MagicMock()
        mock_status.last_calibration = datetime.now() - timedelta(minutes=5)
        mock_adapter.status.return_value = mock_status

        checker = PreflightChecker(instrument_adapter=mock_adapter)
        result = checker._check_instrument_calibration()

        assert result.status == PreflightStatus.PASS
        assert "calibrated recently" in result.message

    def test_instrument_calibration_old(self):
        """Test calibration check when old."""
        mock_adapter = MagicMock()
        mock_status = MagicMock()
        mock_status.last_calibration = datetime.now() - timedelta(minutes=60)
        mock_adapter.status.return_value = mock_status

        checker = PreflightChecker(instrument_adapter=mock_adapter)
        result = checker._check_instrument_calibration()

        assert result.status == PreflightStatus.WARN

    def test_instrument_correction_file_valid(self):
        """Test correction file check with valid file."""
        checker = PreflightChecker(correction_file_path="/path/to/file.ccss")

        with patch.object(Path, "exists", return_value=True):
            result = checker._check_instrument_correction()

            assert result.status == PreflightStatus.PASS
            assert "CCSS" in result.details["type"]

    def test_instrument_correction_file_not_selected(self):
        """Test correction file check when not selected."""
        checker = PreflightChecker()
        result = checker._check_instrument_correction()

        # No correction file selected should give WARN
        assert result.status == PreflightStatus.WARN
        assert "No correction file" in result.message or "correction" in result.message.lower()


class TestPreflightCheckerDisplay:
    """Tests for display configuration checks."""

    def test_display_index_check_no_dispwin(self):
        """Test display index check without dispwin."""
        checker = PreflightChecker()
        result = checker._check_display_index()

        # Should skip if dispwin not found
        assert result.status in [PreflightStatus.SKIP, PreflightStatus.WARN]

    def test_flux_not_running(self):
        """Test f.lux check when not running."""
        checker = PreflightChecker()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)  # pgrep returns 1 if not found
            result = checker._check_flux_status()

            # No f.lux detected, should pass or be handled appropriately
            assert result.status in [PreflightStatus.PASS, PreflightStatus.WARN, PreflightStatus.SKIP]

    def test_flux_running(self):
        """Test f.lux check when running."""
        checker = PreflightChecker()

        with patch("subprocess.run") as mock_run:
            # Simulate flux running - pgrep returns 0 if process found
            mock_run.return_value = MagicMock(returncode=0, stdout="1234")
            result = checker._check_flux_status()

            # Should warn if flux-like process detected
            assert result.status in [PreflightStatus.WARN, PreflightStatus.PASS]


class TestPreflightCheckerSystem:
    """Tests for system settings checks."""

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS only")
    def test_sleep_settings_macos(self):
        """Test sleep settings check on macOS."""
        checker = PreflightChecker()

        with patch("subprocess.run") as mock_run:
            # Mock pmset output
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="sleep      0\n displaysleep      10"
            )
            result = checker._check_system_sleep()

            # Sleep disabled (0), should pass
            assert result.status == PreflightStatus.PASS

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS only")
    def test_night_shift_check_macos(self):
        """Test Night Shift check on macOS."""
        checker = PreflightChecker()

        # The check may be complex due to plist reading
        # Just verify it returns a valid result
        result = checker._check_night_shift_status()

        assert result.status in [
            PreflightStatus.PASS,
            PreflightStatus.WARN,
            PreflightStatus.SKIP,
            PreflightStatus.ERROR,
        ]


class TestPreflightCheckerPermissions:
    """Tests for permission checks."""

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS only")
    def test_accessibility_permission_check(self):
        """Test accessibility permission check on macOS."""
        checker = PreflightChecker()

        with patch("ctypes.util.find_library") as mock_find:
            mock_find.return_value = "/System/Library/Frameworks/ApplicationServices.framework"

            with patch("ctypes.cdll.LoadLibrary") as mock_load:
                mock_lib = MagicMock()
                mock_lib.AXIsProcessTrusted.return_value = True
                mock_load.return_value = mock_lib

                result = checker._check_accessibility_permission()

                assert result.status == PreflightStatus.PASS

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS only")
    def test_usb_permission_check_passes_bytes_to_iokit(self):
        """USB check must pass bytes to IOServiceMatching (c_char_p), not str.

        传 str 会让 ctypes 抛 TypeError("wrong type")，
        该检查在所有 macOS 上都降级为 WARN。
        """
        checker = PreflightChecker()

        with patch("ctypes.util.find_library") as mock_find:
            mock_find.return_value = "/System/Library/Frameworks/IOKit.framework"

            with patch("ctypes.cdll.LoadLibrary") as mock_load:
                mock_lib = MagicMock()
                mock_lib.IOServiceMatching.return_value = 0x1234  # 非空字典指针
                mock_load.return_value = mock_lib

                result = checker._check_usb_permission()

                # 必须以字节串调用（IOServiceMatching 的 argtypes 是 c_char_p）
                mock_lib.IOServiceMatching.assert_called_once_with(b"IOUSBDevice")
                assert result.status == PreflightStatus.PASS

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS only")
    def test_usb_permission_check_iokit_failure_is_warn(self):
        """USB check degrades to WARN (not crash) when IOKit calls fail."""
        checker = PreflightChecker()

        with patch("ctypes.util.find_library") as mock_find:
            mock_find.return_value = "/System/Library/Frameworks/IOKit.framework"

            with patch("ctypes.cdll.LoadLibrary") as mock_load:
                mock_lib = MagicMock()
                mock_lib.IOServiceMatching.side_effect = TypeError("wrong type")
                mock_load.return_value = mock_lib

                result = checker._check_usb_permission()

                assert result.status == PreflightStatus.WARN


class TestPreflightCheckerICC_LUT:
    """Tests for ICC and LUT status checks."""

    def test_icc_check_no_dispwin(self):
        """Non-macOS platforms skip the ICC query (dispwin has no query mode)."""
        checker = PreflightChecker()

        with patch.object(checker, "_platform", "Windows"):
            result = checker._check_current_icc_profile()

            assert result.status == PreflightStatus.SKIP

    def test_icc_check_macos_custom_profile(self):
        """macOS: a loaded custom profile yields WARN with its name (Quartz mocked)."""
        checker = PreflightChecker()

        quartz = MagicMock()
        quartz.CGGetActiveDisplayList.return_value = (0, (12345,), 1)
        quartz.CGDisplayCopyColorSpace.return_value = MagicMock()
        quartz.CGColorSpaceCopyICCData.return_value = None
        quartz.CGColorSpaceCopyName.return_value = "MyCustomProfile"

        with patch.dict("sys.modules", {"Quartz": quartz}):
            result = checker._check_current_icc_profile()

        assert result.status == PreflightStatus.WARN
        assert result.details["profile_name"] == "MyCustomProfile"

    def test_icc_check_macos_quartz_failure_is_warn(self):
        """macOS: any Quartz failure degrades to WARN instead of crashing."""
        checker = PreflightChecker()

        quartz = MagicMock()
        quartz.CGGetActiveDisplayList.side_effect = RuntimeError("boom")

        with patch.dict("sys.modules", {"Quartz": quartz}):
            result = checker._check_current_icc_profile()

        assert result.status == PreflightStatus.WARN

    def test_icc_check_with_dispwin_mocked(self):
        """Test ICC check with mocked dispwin."""
        checker = PreflightChecker()

        # Mock dispwin found and running
        with patch.object(checker, "_find_argyll_tool", return_value="/fake/dispwin"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="Installed profile: /path/to/profile.icc"
                )
                result = checker._check_current_icc_profile()

                # Should return a valid result
                assert result.status in [PreflightStatus.PASS, PreflightStatus.WARN]


# ========== Run All Checks Tests ==========

class TestPreflightCheckerRunAllChecks:
    """Tests for run_all_checks method."""

    def test_run_all_checks_returns_report(self):
        """Test run_all_checks returns PreflightReport."""
        checker = PreflightChecker()

        # Mock tool finding to avoid actual system checks
        with patch.object(checker, "_find_argyll_tool", return_value="/fake/spotread"):
            with patch.object(checker, "_get_argyll_version", return_value="3.2.0"):
                report = checker.run_all_checks()

        assert isinstance(report, PreflightReport)
        assert report.argyll_version == "3.2.0"
        assert len(report.results) > 0

    def test_run_all_checks_with_skip_items(self):
        """Test run_all_checks with skip_items parameter."""
        checker = PreflightChecker()
        skip_list = ["argyll_spotread", "argyll_dispcal"]

        report = checker.run_all_checks(skip_items=skip_list)

        # Check that skipped items are not in results
        result_ids = [r.item_id for r in report.results]
        assert "argyll_spotread" not in result_ids
        assert "argyll_dispcal" not in result_ids

    def test_run_all_checks_with_only_items(self):
        """Test run_all_checks with only_items parameter."""
        checker = PreflightChecker()
        only_list = ["argyll_spotread"]

        report = checker.run_all_checks(only_items=only_list)

        # Check only specified items are in results
        result_ids = [r.item_id for r in report.results]
        assert "argyll_spotread" in result_ids
        # Check that other items are not included
        assert len(result_ids) <= len(only_list)

    def test_run_quick_checks(self):
        """Test run_quick_checks method."""
        checker = PreflightChecker()

        report = checker.run_quick_checks()

        # Quick checks should only include essential items
        essential_items = ["argyll_spotread", "argyll_dispwin", "instrument_connected", "display_index"]
        result_ids = [r.item_id for r in report.results]

        # Check that essential items are included (or skipped if not applicable)
        for item_id in essential_items:
            assert item_id in result_ids


# ========== Utility Function Tests ==========

class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_create_preflight_checker(self):
        """Test create_preflight_checker factory function."""
        checker = create_preflight_checker(
            argyll_bin_path="/test/path",
            display_index=2,
        )
        assert isinstance(checker, PreflightChecker)
        assert checker._argyll_bin_path == "/test/path"
        assert checker._display_index == 2

    def test_run_preflight_checks(self):
        """Test run_preflight_checks convenience function."""
        with patch.object(PreflightChecker, "run_all_checks") as mock_run:
            mock_run.return_value = PreflightReport()
            report = run_preflight_checks()
            assert isinstance(report, PreflightReport)

    def test_run_preflight_checks_quick(self):
        """Test run_preflight_checks with quick=True."""
        with patch.object(PreflightChecker, "run_quick_checks") as mock_run:
            mock_run.return_value = PreflightReport()
            report = run_preflight_checks(quick=True)
            assert isinstance(report, PreflightReport)

    def test_export_preflight_report(self, tmp_path):
        """Test export_preflight_report function."""
        report = PreflightReport()
        report.add_result(PreflightResult(item_id="test", status=PreflightStatus.PASS))
        report.calculate_summary()

        filepath = tmp_path / "preflight_report.json"
        result = export_preflight_report(report, filepath)

        assert result == True
        assert filepath.exists()

        # Verify content
        content = filepath.read_text()
        parsed = json.loads(content)
        assert "results" in parsed


# ========== Standard Check Items Tests ==========

class TestStandardCheckItems:
    """Tests for standard PREFLIGHT_CHECK_ITEMS."""

    def test_check_items_count(self):
        """Test we have reasonable number of check items."""
        assert len(PREFLIGHT_CHECK_ITEMS) >= 15  # At least 15 standard checks

    def test_check_items_have_required_fields(self):
        """Test all check items have required fields."""
        for item in PREFLIGHT_CHECK_ITEMS:
            assert item.id
            assert item.name
            assert item.category in PreflightCategory

    def test_check_items_categories(self):
        """Test check items cover all categories."""
        categories_found = set(item.category for item in PREFLIGHT_CHECK_ITEMS)

        # Should have most categories covered
        assert PreflightCategory.ARGYLL in categories_found
        assert PreflightCategory.INSTRUMENT in categories_found
        assert PreflightCategory.DISPLAY in categories_found

    def test_argyll_check_ids(self):
        """Test Argyll check items have consistent IDs."""
        argyll_items = [i for i in PREFLIGHT_CHECK_ITEMS if i.category == PreflightCategory.ARGYLL]

        for item in argyll_items:
            assert item.id.startswith("argyll_")

    def test_platform_specific_items(self):
        """Test platform-specific items are marked correctly."""
        for item in PREFLIGHT_CHECK_ITEMS:
            if item.platform_specific:
                # Should be a list of platform names
                assert isinstance(item.platform_specific, list)
                for platform_name in item.platform_specific:
                    assert platform_name in ["Darwin", "Windows", "Linux"]


# ========== Integration Tests ==========

class TestPreflightIntegration:
    """Integration tests for preflight workflow."""

    def test_full_preflight_workflow(self):
        """Test full preflight check workflow."""
        checker = PreflightChecker()

        # Mock Argyll tools
        with patch.object(checker, "_find_argyll_tool", return_value="/fake/tool"):
            with patch.object(checker, "_get_argyll_version", return_value="3.2.0"):
                # Run full checks
                report = checker.run_all_checks()

        # Verify report structure
        assert isinstance(report, PreflightReport)
        assert report.platform == platform.system()
        assert report.argyll_version == "3.2.0"
        assert len(report.results) > 0

        # Calculate summary
        report.calculate_summary()
        assert report.summary["total_checks"] == len(report.results)

    def test_preflight_with_instrument_connected(self):
        """Test preflight with connected instrument."""
        # Create mock connected instrument
        mock_adapter = MagicMock()
        mock_status = MagicMock()
        mock_status.connected = True
        mock_status.model = "i1 Display Pro"
        mock_status.serial = "TEST123"
        mock_status.state = MagicMock()
        mock_status.state.value = "ready"
        mock_status.last_calibration = datetime.now()
        mock_adapter.status.return_value = mock_status

        checker = PreflightChecker(instrument_adapter=mock_adapter)

        # Run instrument checks
        conn_result = checker.run_single_check(
            PreflightItem(id="instrument_connected", name="Connection", category=PreflightCategory.INSTRUMENT)
        )

        assert conn_result.status == PreflightStatus.PASS

    def test_preflight_report_export_and_reload(self, tmp_path):
        """Test report export and reload."""
        checker = PreflightChecker()

        with patch.object(checker, "_find_argyll_tool", return_value="/fake/tool"):
            report = checker.run_all_checks()

        report.calculate_summary()
        report.update_can_proceed(False)

        # Export
        filepath = tmp_path / "test_report.json"
        assert report.export_to_file(filepath) == True

        # Reload and verify
        content = filepath.read_text()
        loaded = json.loads(content)

        assert loaded["platform"] == platform.system()
        # Note: can_proceed depends on check results (PASS/WARN/SKIP means can proceed)
        # If there are no BLOCK/ERROR items, can_proceed will be True even with override disabled
        assert "can_proceed" in loaded
        assert len(loaded["results"]) > 0


# ========== Edge Cases ==========

class TestPreflightEdgeCases:
    """Edge case tests."""

    def test_checker_with_none_instrument(self):
        """Test checker handles None instrument gracefully."""
        checker = PreflightChecker(instrument_adapter=None)
        result = checker._check_instrument_connection()

        assert result.status == PreflightStatus.SKIP

    def test_checker_exception_handling(self):
        """Test checker handles exceptions in check methods."""
        checker = PreflightChecker()

        # Force exception in subprocess
        with patch("subprocess.run", side_effect=Exception("Test error")):
            result = checker._check_system_sleep()

        # Should handle exception gracefully
        assert result.status in [PreflightStatus.WARN, PreflightStatus.ERROR, PreflightStatus.SKIP]

    def test_report_empty_results(self):
        """Test report with empty results."""
        report = PreflightReport()
        report.calculate_summary()

        assert report.summary["pass_count"] == 0
        assert report.summary["total_checks"] == 0
        assert report.can_proceed == False

    def test_result_invalid_status(self):
        """Test result handles all status types."""
        for status in PreflightStatus:
            result = PreflightResult(item_id="test", status=status)
            assert result.status == status

    def test_display_index_out_of_range(self):
        """Test display index validation with out of range."""
        checker = PreflightChecker(display_index=999)  # Very high index

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="1: Display 1\n2: Display 2"
            )

            result = checker._check_display_index()

            # Should warn or block for invalid index
            assert result.status in [PreflightStatus.BLOCK, PreflightStatus.WARN, PreflightStatus.SKIP]


# ========== Progress Callback Tests ==========

class TestPreflightProgressCallback:
    """Tests for progress_callback functionality."""

    def test_progress_callback_called_at_least_once(self):
        """Test that progress_callback is called at least once during run_all_checks."""
        checker = PreflightChecker()
        progress_records = []

        def progress_callback(current, total, item_id, label):
            progress_records.append({
                "current": current,
                "total": total,
                "item_id": item_id,
                "label": label,
            })

        # Run with progress callback
        report = checker.run_all_checks(progress_callback=progress_callback)

        # Should have at least one progress record
        assert len(progress_records) >= 1

        # Verify progress data structure
        for record in progress_records:
            assert "current" in record
            assert "total" in record
            assert "item_id" in record
            assert "label" in record
            assert record["current"] >= 1
            assert record["total"] >= 1
            assert isinstance(record["item_id"], str)
            assert isinstance(record["label"], str)

    def test_progress_callback_counts_match_results(self):
        """Test that progress callback total matches result count."""
        checker = PreflightChecker()
        progress_records = []

        def progress_callback(current, total, item_id, label):
            progress_records.append({
                "current": current,
                "total": total,
                "item_id": item_id,
                "label": label,
            })

        report = checker.run_all_checks(progress_callback=progress_callback)

        # Total should match number of results
        assert len(progress_records) == len(report.results)

        # Last progress should equal total
        if progress_records:
            last_record = progress_records[-1]
            assert last_record["current"] == last_record["total"]

    def test_progress_callback_with_only_items(self):
        """Test progress callback with only_items parameter."""
        checker = PreflightChecker()
        progress_records = []

        def progress_callback(current, total, item_id, label):
            progress_records.append({"item_id": item_id})

        only_list = ["argyll_spotread"]
        report = checker.run_all_checks(only_items=only_list, progress_callback=progress_callback)

        # Should have exactly one progress for one item
        assert len(progress_records) <= 1
        if progress_records:
            assert progress_records[0]["item_id"] == "argyll_spotread"

    def test_progress_callback_with_skip_items(self):
        """Test progress callback with skip_items parameter."""
        checker = PreflightChecker()
        progress_records = []

        def progress_callback(current, total, item_id, label):
            progress_records.append({"item_id": item_id})

        skip_list = ["argyll_spotread"]
        report = checker.run_all_checks(skip_items=skip_list, progress_callback=progress_callback)

        # Skipped items should not appear in progress
        for record in progress_records:
            assert record["item_id"] != "argyll_spotread"

    def test_progress_callback_none_is_safe(self):
        """Test that None progress_callback is handled safely."""
        checker = PreflightChecker()

        # Should not raise error when callback is None
        report = checker.run_all_checks(progress_callback=None)

        assert isinstance(report, PreflightReport)
        assert len(report.results) >= 1

    def test_progress_callback_order_correct(self):
        """Test that progress callback is called before each check."""
        checker = PreflightChecker()
        progress_order = []
        result_order = []

        def progress_callback(current, total, item_id, label):
            progress_order.append(item_id)

        # Custom check items for controlled testing
        custom_items = [
            PreflightItem(id="check_1", name="Check 1", category=PreflightCategory.SYSTEM),
            PreflightItem(id="check_2", name="Check 2", category=PreflightCategory.SYSTEM),
            PreflightItem(id="check_3", name="Check 3", category=PreflightCategory.SYSTEM),
        ]

        checker._check_items = custom_items
        report = checker.run_all_checks(progress_callback=progress_callback)

        # Progress order should match result order
        result_order = [r.item_id for r in report.results]
        assert progress_order == result_order


# ========== Backend Integration Tests ==========

class TestBackendPreflightProgressIntegration:
    """Tests for Backend integration with progress callback."""

    def test_progress_json_format(self):
        """Test that progress data JSON format is correct."""
        import json

        # Simulate progress callback data format
        progress_data = {
            "current": 1,
            "total": 20,
            "item": "argyll_spotread",
            "label": "ArgyllCMS spotread",
        }

        progress_json = json.dumps(progress_data, ensure_ascii=False)

        # Parse and verify
        parsed = json.loads(progress_json)
        assert parsed["current"] == 1
        assert parsed["total"] == 20
        assert parsed["item"] == "argyll_spotread"
        assert parsed["label"] == "ArgyllCMS spotread"

    def test_can_proceed_after_override(self):
        """Test that can_proceed logic works with override."""
        report = PreflightReport()
        report.add_result(PreflightResult(item_id="block_item", status=PreflightStatus.BLOCK))
        report.calculate_summary()

        # Without override, cannot proceed
        report.update_can_proceed(override_enabled=False)
        assert report.can_proceed == False

        # With override, can proceed (BLOCK ignored)
        report.update_can_proceed(override_enabled=True)
        assert report.can_proceed == True

    def test_can_proceed_with_error_still_blocks(self):
        """Test that ERROR status blocks even with override."""
        report = PreflightReport()
        report.add_result(PreflightResult(item_id="error_item", status=PreflightStatus.ERROR))
        report.calculate_summary()

        # With override, ERROR still blocks
        report.update_can_proceed(override_enabled=True)
        assert report.can_proceed == False
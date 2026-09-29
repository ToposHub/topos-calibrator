"""
Preflight - Environment Pre-flight Check Module

This module implements comprehensive environment checks before professional
color measurements can proceed. Each check yields PASS/WARN/BLOCK status.

Key features:
- ArgyllCMS tool availability checks (spotread/dispcal/targen/colprof/collink)
- Instrument connection status
- Display index validation
- HDR/ACM (Automatic Color Management) status detection
- Night Shift/True Tone status detection (macOS)
- System sleep settings check
- System permissions check (USB, Accessibility, etc.)
- ICC Profile/VCGT LUT current state check
- Pre-flight report export for troubleshooting

Reference:
- docs/professional_optimization_plan.md (Task P3-C)
- docs/agent_handoffs/P1-C_backend_refactor.md (Backend integration)
"""

import json
import logging
import os
import platform
import re
import subprocess
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


# ========== Enums ==========

class PreflightStatus(Enum):
    """Status level for pre-flight check results."""
    PASS = "PASS"      # OK, can proceed
    WARN = "WARN"      # Risk exists but can proceed
    BLOCK = "BLOCK"    # Must fix before proceeding
    SKIP = "SKIP"      # Check skipped (not applicable)
    ERROR = "ERROR"    # Check failed to execute


class PreflightCategory(Enum):
    """Categories for organizing pre-flight checks."""
    ARGYLL = "argyll"           # ArgyllCMS tools
    INSTRUMENT = "instrument"   # Measurement instrument
    DISPLAY = "display"         # Display configuration
    SYSTEM = "system"           # System settings (HDR, Night Shift, sleep)
    PERMISSION = "permission"   # System permissions
    ICC_LUT = "icc_lut"         # ICC profile and LUT state


# ========== Data Classes ==========

@dataclass
class PreflightItem:
    """
    Single pre-flight check item definition.

    Attributes:
        id: Unique identifier for this check
        name: Human-readable check name
        description: Detailed description of what is being checked
        category: Category for grouping
        impact: What happens if this check fails
        suggestion: How to fix if check fails
        platform_specific: Platforms this check applies to (None = all platforms)
        allow_override: Whether user can override BLOCK status with advanced setting
    """
    id: str
    name: str
    description: str = ""
    category: PreflightCategory = PreflightCategory.SYSTEM
    impact: str = ""
    suggestion: str = ""
    platform_specific: Optional[List[str]] = None  # ['Darwin', 'Windows', 'Linux']
    allow_override: bool = True


@dataclass
class PreflightResult:
    """
    Result of a single pre-flight check.

    Attributes:
        item_id: ID of the checked item
        status: PASS/WARN/BLOCK/SKIP/ERROR
        message: Human-readable result message
        details: Additional technical details (paths, versions, etc.)
        timestamp: When the check was performed
        fix_command: Optional command to fix the issue
        fix_url: Optional URL with fix instructions
        suggestion: Optional suggestion for how to fix the issue
    """
    item_id: str
    status: PreflightStatus
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    fix_command: Optional[str] = None
    fix_url: Optional[str] = None
    suggestion: Optional[str] = None

    def is_blocking(self) -> bool:
        """Check if this result blocks proceeding."""
        return self.status == PreflightStatus.BLOCK

    def is_warning(self) -> bool:
        """Check if this result is a warning."""
        return self.status == PreflightStatus.WARN

    def is_pass(self) -> bool:
        """Check if this result is passing."""
        return self.status == PreflightStatus.PASS

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON export."""
        return {
            "item_id": self.item_id,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "fix_command": self.fix_command,
            "fix_url": self.fix_url,
            "suggestion": self.suggestion,
        }


@dataclass
class PreflightReport:
    """
    Complete pre-flight check report.

    Attributes:
        results: List of all check results
        summary: Overall summary (pass_count, warn_count, block_count, etc.)
        platform: Platform the check was run on
        timestamp: When the report was generated
        argyll_version: ArgyllCMS version if detected
        environment_info: Additional environment information
        can_proceed: Whether all checks allow proceeding (no BLOCK or user override enabled)
        override_enabled: Whether user has enabled override for BLOCK items
    """
    results: List[PreflightResult] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    platform: str = field(default_factory=lambda: platform.system())
    timestamp: datetime = field(default_factory=datetime.now)
    argyll_version: Optional[str] = None
    environment_info: Dict[str, Any] = field(default_factory=dict)
    can_proceed: bool = False
    override_enabled: bool = False

    def add_result(self, result: PreflightResult) -> None:
        """Add a check result to the report."""
        self.results.append(result)

    def calculate_summary(self) -> None:
        """Calculate summary statistics from results."""
        self.summary = {
            "pass_count": sum(1 for r in self.results if r.status == PreflightStatus.PASS),
            "warn_count": sum(1 for r in self.results if r.status == PreflightStatus.WARN),
            "block_count": sum(1 for r in self.results if r.status == PreflightStatus.BLOCK),
            "skip_count": sum(1 for r in self.results if r.status == PreflightStatus.SKIP),
            "error_count": sum(1 for r in self.results if r.status == PreflightStatus.ERROR),
            "total_checks": len(self.results),
        }

    def update_can_proceed(self, override_enabled: bool = False) -> None:
        """Update can_proceed based on results and override setting."""
        self.override_enabled = override_enabled

        # If override is enabled, only ERROR blocks proceeding
        if override_enabled:
            self.can_proceed = not any(
                r.status == PreflightStatus.ERROR for r in self.results
            )
        else:
            # Without override, BLOCK also blocks proceeding
            self.can_proceed = not any(
                r.status in [PreflightStatus.BLOCK, PreflightStatus.ERROR]
                for r in self.results
            )

    def get_blocking_items(self) -> List[PreflightResult]:
        """Get list of blocking check results."""
        return [r for r in self.results if r.is_blocking()]

    def get_warning_items(self) -> List[PreflightResult]:
        """Get list of warning check results."""
        return [r for r in self.results if r.is_warning()]

    def get_failed_items(self) -> List[PreflightResult]:
        """Get list of non-passing check results (WARN, BLOCK, ERROR)."""
        return [r for r in self.results if not r.is_pass()]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON export."""
        return {
            "results": [r.to_dict() for r in self.results],
            "summary": self.summary,
            "platform": self.platform,
            "timestamp": self.timestamp.isoformat(),
            "argyll_version": self.argyll_version,
            "environment_info": self.environment_info,
            "can_proceed": self.can_proceed,
            "override_enabled": self.override_enabled,
        }

    def to_json(self) -> str:
        """Convert to JSON string for export."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def export_to_file(self, filepath: Union[str, Path]) -> bool:
        """Export report to a JSON file."""
        try:
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.to_json(), encoding="utf-8")
            logger.info(f"Pre-flight report exported to: {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export pre-flight report: {e}")
            return False


# ========== Pre-flight Check Definitions ==========

# Standard pre-flight check items
PREFLIGHT_CHECK_ITEMS: List[PreflightItem] = [
    # ArgyllCMS Tools
    PreflightItem(
        id="argyll_spotread",
        name="ArgyllCMS spotread",
        description="Check if spotread tool is available for spot measurements",
        category=PreflightCategory.ARGYLL,
        impact="Cannot perform any color measurements",
        suggestion="Install ArgyllCMS or add it to PATH",
        allow_override=False,
    ),
    PreflightItem(
        id="argyll_dispcal",
        name="ArgyllCMS dispcal",
        description="Check if dispcal tool is available for display calibration",
        category=PreflightCategory.ARGYLL,
        impact="Cannot perform display calibration workflow",
        suggestion="Install ArgyllCMS or add it to PATH",
        allow_override=True,
    ),
    PreflightItem(
        id="argyll_targen",
        name="ArgyllCMS targen",
        description="Check if targen tool is available for test chart generation",
        category=PreflightCategory.ARGYLL,
        impact="Cannot generate custom test charts for ICC/LUT profiling",
        suggestion="Install ArgyllCMS or add it to PATH",
        allow_override=True,
    ),
    PreflightItem(
        id="argyll_colprof",
        name="ArgyllCMS colprof",
        description="Check if colprof tool is available for ICC profile generation",
        category=PreflightCategory.ARGYLL,
        impact="Cannot create ICC profiles from measurement data",
        suggestion="Install ArgyllCMS or add it to PATH",
        allow_override=True,
    ),
    PreflightItem(
        id="argyll_collink",
        name="ArgyllCMS collink",
        description="Check if collink tool is available for 3D LUT generation",
        category=PreflightCategory.ARGYLL,
        impact="Cannot create 3D LUTs from ICC profiles",
        suggestion="Install ArgyllCMS or add it to PATH",
        allow_override=True,
    ),
    PreflightItem(
        id="argyll_dispwin",
        name="ArgyllCMS dispwin",
        description="Check if dispwin tool is available for LUT/ICC manipulation",
        category=PreflightCategory.ARGYLL,
        impact="Cannot apply or clear ICC profiles/VCGT LUT",
        suggestion="Install ArgyllCMS or add it to PATH",
        allow_override=False,
    ),
    PreflightItem(
        id="argyll_ccxxmake",
        name="ArgyllCMS ccxxmake",
        description="Check if ccxxmake tool is available for correction matrix creation",
        category=PreflightCategory.ARGYLL,
        impact="Cannot create CCSS/CCMX correction files",
        suggestion="Install ArgyllCMS or add it to PATH",
        allow_override=True,
    ),

    # Instrument
    PreflightItem(
        id="instrument_connected",
        name="Instrument Connection",
        description="Check if measurement instrument is connected and responding",
        category=PreflightCategory.INSTRUMENT,
        impact="Cannot perform any measurements",
        suggestion="Connect the instrument via USB and restart the application",
        allow_override=False,
    ),
    PreflightItem(
        id="instrument_calibrated",
        name="Instrument Calibration",
        description="Check if instrument has been calibrated recently",
        category=PreflightCategory.INSTRUMENT,
        impact="Measurements may be inaccurate",
        suggestion="Perform instrument calibration before measurements",
        allow_override=True,
    ),
    PreflightItem(
        id="instrument_correction",
        name="Instrument Correction File",
        description="Check if appropriate correction file (CCSS/CCMX) is selected",
        category=PreflightCategory.INSTRUMENT,
        impact="Color measurements may have significant errors for certain display types",
        suggestion="Select appropriate correction file for your display technology",
        allow_override=True,
    ),

    # Display
    PreflightItem(
        id="display_index",
        name="Display Index",
        description="Verify target display index is valid and accessible",
        category=PreflightCategory.DISPLAY,
        impact="Measurements may target wrong display",
        suggestion="Select correct display index from the list",
        allow_override=False,
    ),
    PreflightItem(
        id="display_hdr_acm",
        name="HDR/ACM Status",
        description="Check if HDR mode or Automatic Color Management is active",
        category=PreflightCategory.DISPLAY,
        impact="HDR/ACM may alter color output unexpectedly",
        suggestion="Disable HDR mode and ACM for accurate measurements",
        platform_specific=['Darwin', 'Windows'],
        allow_override=True,
    ),
    PreflightItem(
        id="display_night_shift",
        name="Night Shift/True Tone",
        description="Check if Night Shift (macOS) or similar features are active",
        category=PreflightCategory.DISPLAY,
        impact="Color temperature adjustment will affect measurements",
        suggestion="Disable Night Shift/True Tone before measurements",
        platform_specific=['Darwin'],
        allow_override=True,
    ),
    PreflightItem(
        id="display_f lux",
        name="f.lux Software",
        description="Check if f.lux or similar color-adjusting software is running",
        category=PreflightCategory.DISPLAY,
        impact="External color management software will interfere with measurements",
        suggestion="Quit f.lux, Redshift, or similar software",
        allow_override=True,
    ),

    # System
    PreflightItem(
        id="system_sleep",
        name="System Sleep Settings",
        description="Check if system sleep timeout is too short for measurements",
        category=PreflightCategory.SYSTEM,
        impact="System may sleep during long measurements",
        suggestion="Increase sleep timeout or use sleep prevention feature",
        allow_override=True,
    ),
    PreflightItem(
        id="system_display_sleep",
        name="Display Sleep Settings",
        description="Check if display sleep timeout is too short",
        category=PreflightCategory.SYSTEM,
        impact="Display may turn off during measurements",
        suggestion="Increase display sleep timeout",
        allow_override=True,
    ),

    # Permissions - macOS
    PreflightItem(
        id="permission_usb",
        name="USB Device Access",
        description="Check if application has USB device access permission",
        category=PreflightCategory.PERMISSION,
        impact="Cannot communicate with measurement instrument",
        suggestion="Grant USB device access in System Settings",
        platform_specific=['Darwin'],
        allow_override=False,
    ),
    PreflightItem(
        id="permission_screen_capture",
        name="Screen Recording Permission",
        description="Check if application has screen recording permission for LUT verification",
        category=PreflightCategory.PERMISSION,
        impact="Cannot verify display output or perform LUT validation",
        suggestion="Grant screen recording permission in System Settings",
        platform_specific=['Darwin'],
        allow_override=True,
    ),
    PreflightItem(
        id="permission_accessibility",
        name="Accessibility Permission",
        description="Check if application has accessibility permission for DDC/CI",
        category=PreflightCategory.PERMISSION,
        impact="Cannot control display brightness/settings via DDC/CI",
        suggestion="Grant accessibility permission in System Settings",
        platform_specific=['Darwin'],
        allow_override=True,
    ),

    # Permissions - Windows
    PreflightItem(
        id="permission_usb_windows",
        name="USB HID Device Access",
        description="Check if application can access USB HID measurement devices",
        category=PreflightCategory.PERMISSION,
        impact="Cannot communicate with measurement instrument",
        suggestion="Ensure HID drivers are installed and instrument is not in use by other software",
        platform_specific=['Windows'],
        allow_override=False,
    ),
    PreflightItem(
        id="permission_ddc_ci_windows",
        name="DDC/CI Communication",
        description="Check if DDC/CI protocol is available for display control",
        category=PreflightCategory.PERMISSION,
        impact="Cannot automatically control display brightness/contrast",
        suggestion="Enable DDC/CI in display OSD menu",
        platform_specific=['Windows'],
        allow_override=True,
    ),

    # Permissions - Linux
    PreflightItem(
        id="permission_usb_linux",
        name="USB HID Device Permissions",
        description="Check read/write permissions for USB HID devices",
        category=PreflightCategory.PERMISSION,
        impact="Cannot communicate with measurement instrument",
        suggestion="Add udev rules or join uucp group",
        platform_specific=['Linux'],
        allow_override=False,
    ),
    PreflightItem(
        id="permission_i2c_linux",
        name="i2c-dev Device Permissions",
        description="Check i2c-dev module and device permissions for DDC/CI",
        category=PreflightCategory.PERMISSION,
        impact="Cannot control display via DDC/CI protocol",
        suggestion="Load i2c-dev module and configure permissions",
        platform_specific=['Linux'],
        allow_override=True,
    ),
    PreflightItem(
        id="permission_backlight_linux",
        name="Backlight Control Permissions",
        description="Check write permissions for backlight control",
        category=PreflightCategory.PERMISSION,
        impact="Cannot adjust display brightness automatically",
        suggestion="Join video group for backlight control",
        platform_specific=['Linux'],
        allow_override=True,
    ),

    # ICC/LUT
    PreflightItem(
        id="icc_current_profile",
        name="Current ICC Profile",
        description="Check which ICC profile is currently loaded",
        category=PreflightCategory.ICC_LUT,
        impact="Existing ICC profile affects displayed colors",
        suggestion="Clear or document current ICC profile before measurements",
        allow_override=True,
    ),
    PreflightItem(
        id="lut_vcgt_status",
        name="VCGT LUT Status",
        description="Check if video card gamma table (VCGT) is modified",
        category=PreflightCategory.ICC_LUT,
        impact="Modified LUT affects color output",
        suggestion="Clear VCGT LUT for accurate measurements",
        allow_override=True,
    ),
]


# ========== Preflight Checker Class ==========

class PreflightChecker:
    """
    Environment pre-flight check executor.

    This class executes all defined pre-flight checks and generates
    a comprehensive report. Checks are platform-aware and can be
    selectively enabled/disabled.

    Usage:
        checker = PreflightChecker(argyll_bin_path="/path/to/argyll/bin")
        report = checker.run_all_checks()
        if report.can_proceed:
            # Start measurements
            pass
        else:
            # Show blocking issues to user
            for result in report.get_blocking_items():
                print(f"BLOCK: {result.message}")
    """

    def __init__(
        self,
        argyll_bin_path: Optional[str] = None,
        instrument_adapter: Optional[Any] = None,  # InstrumentAdapter
        display_index: int = 1,
        correction_file_path: Optional[str] = None,
        check_items: Optional[List[PreflightItem]] = None,
    ):
        """
        Initialize pre-flight checker.

        Args:
            argyll_bin_path: Path to ArgyllCMS bin directory
            instrument_adapter: Connected instrument adapter for status checks
            display_index: Target display index (1-based for Argyll)
            correction_file_path: Path to selected correction file
            check_items: Custom list of check items (default: PREFLIGHT_CHECK_ITEMS)
        """
        self._argyll_bin_path = argyll_bin_path
        self._instrument_adapter = instrument_adapter
        self._display_index = display_index
        self._correction_file_path = correction_file_path
        self._check_items = check_items or PREFLIGHT_CHECK_ITEMS.copy()
        self._platform = platform.system()

        # Cache for detected Argyll paths
        self._detected_argyll_paths: Dict[str, str] = {}

        # Detect Argyll version
        self._argyll_version: Optional[str] = None

        logger.info(f"PreflightChecker initialized for platform: {self._platform}")

    def set_argyll_bin_path(self, path: Optional[str]) -> None:
        """Set ArgyllCMS bin directory path."""
        self._argyll_bin_path = path
        self._detected_argyll_paths.clear()

    def set_instrument_adapter(self, adapter: Optional[Any]) -> None:
        """Set instrument adapter for connection checks."""
        self._instrument_adapter = adapter

    def set_display_index(self, index: int) -> None:
        """Set target display index."""
        self._display_index = index

    def set_correction_file_path(self, path: Optional[str]) -> None:
        """Set correction file path."""
        self._correction_file_path = path

    # ========== Check Methods ==========

    def _find_argyll_tool(self, tool_name: str) -> Optional[str]:
        """
        Find an ArgyllCMS tool executable.

        Search order:
        1. Provided argyll_bin_path
        2. Project ArgyllCMS directory
        3. System PATH

        Args:
            tool_name: Name of the tool (e.g., "spotread", "dispcal")

        Returns:
            Full path to the tool executable, or None if not found
        """
        # Check cache
        if tool_name in self._detected_argyll_paths:
            return self._detected_argyll_paths[tool_name]

        # Windows needs .exe extension
        if self._platform == "Windows":
            tool_name_exe = f"{tool_name}.exe"
        else:
            tool_name_exe = tool_name

        # 1. Check provided argyll_bin_path
        if self._argyll_bin_path:
            path = Path(self._argyll_bin_path) / tool_name_exe
            if path.exists() and path.is_file():
                self._detected_argyll_paths[tool_name] = str(path)
                return str(path)

        # 2. Check project ArgyllCMS directory
        # Get project root relative to this module
        module_dir = Path(__file__).parent.parent.parent
        argyll_dir = module_dir / "ArgyllCMS" / "bin"

        for possible_dir in [argyll_dir, module_dir / "ArgyllCMS"]:
            path = possible_dir / tool_name_exe
            if path.exists() and path.is_file():
                self._detected_argyll_paths[tool_name] = str(path)
                return str(path)
            # Also check if there's a bin subdirectory
            bin_dir = possible_dir / "bin"
            if bin_dir.exists():
                path = bin_dir / tool_name_exe
                if path.exists() and path.is_file():
                    self._detected_argyll_paths[tool_name] = str(path)
                    return str(path)

        # 3. Check system PATH
        tool_path = shutil.which(tool_name)
        if tool_path:
            self._detected_argyll_paths[tool_name] = tool_path
            return tool_path

        # Also try with .exe on non-Windows for cross-platform
        tool_path_exe = shutil.which(tool_name_exe)
        if tool_path_exe:
            self._detected_argyll_paths[tool_name] = tool_path_exe
            return tool_path_exe

        return None

    def _get_argyll_version(self) -> Optional[str]:
        """
        Detect ArgyllCMS version from a tool's `-?` usage header.

        注意：不能用 spotread/dispcal——它们启动时即枚举串口（蓝牙串口探测
        在部分机器上耗时 20s+），且 -V 是真实工作模式而非版本参数；
        版本号只打印在 -? 帮助输出的首行。dispwin/targen 的 -? 立即返回。
        """
        if self._argyll_version:
            return self._argyll_version

        for tool_name in ["dispwin", "targen", "colprof"]:
            tool_path = self._find_argyll_tool(tool_name)
            if tool_path:
                try:
                    result = subprocess.run(
                        [tool_path, "-?"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    # usage 可能输出到 stdout 或 stderr，且退出码非 0，只看内容
                    output = (result.stdout or "") + (result.stderr or "")
                    match = re.search(r"Version\s+([\d.]+)", output)
                    if match:
                        self._argyll_version = match.group(1)
                        return self._argyll_version
                except Exception as e:
                    logger.debug(f"Failed to get Argyll version from {tool_name}: {e}")

        return None

    def _check_argyll_tool(self, tool_name: str) -> PreflightResult:
        """
        Check availability of a specific ArgyllCMS tool.

        Args:
            tool_name: Name of the tool

        Returns:
            PreflightResult with tool status
        """
        item_id = f"argyll_{tool_name}"

        tool_path = self._find_argyll_tool(tool_name)

        if tool_path:
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.PASS,
                message=f"{tool_name} found: {tool_path}",
                details={"path": tool_path},
            )
        else:
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.BLOCK,
                message=f"{tool_name} not found - Install ArgyllCMS or add it to PATH",
                details={"searched_paths": [
                    self._argyll_bin_path or "(not specified)",
                    "ArgyllCMS/",
                    "PATH",
                ]},
                fix_url="https://www.argyllcms.com/",
            )

    def _check_instrument_connection(self) -> PreflightResult:
        """
        Check if instrument is connected and responding.

        Returns:
            PreflightResult with connection status
        """
        item_id = "instrument_connected"

        if self._instrument_adapter:
            try:
                status = self._instrument_adapter.status()
                if status.connected:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.PASS,
                        message=f"Instrument connected: {status.model or 'Unknown'}",
                        details={
                            "model": status.model,
                            "serial": status.serial,
                            "state": status.state.value if hasattr(status.state, 'value') else str(status.state),
                        },
                    )
                else:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.BLOCK,
                        message="Instrument not connected",
                        details={"state": status.state.value if hasattr(status.state, 'value') else str(status.state)},
                    )
            except Exception as e:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.ERROR,
                    message=f"Failed to check instrument status: {e}",
                    details={"error": str(e)},
                )
        else:
            # No adapter provided, skip this check
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.SKIP,
                message="Instrument adapter not provided, check skipped",
            )

    def _check_instrument_calibration(self) -> PreflightResult:
        """
        Check if instrument has been calibrated recently.

        Returns:
            PreflightResult with calibration status
        """
        item_id = "instrument_calibrated"

        if self._instrument_adapter:
            try:
                status = self._instrument_adapter.status()
                if status.last_calibration:
                    # Check if calibration is recent (within 30 minutes)
                    age = datetime.now() - status.last_calibration
                    age_minutes = age.total_seconds() / 60

                    if age_minutes > 30:
                        return PreflightResult(
                            item_id=item_id,
                            status=PreflightStatus.WARN,
                            message=f"Last calibration: {int(age_minutes)} minutes ago",
                            details={
                                "last_calibration": status.last_calibration.isoformat(),
                                "age_minutes": int(age_minutes),
                            },
                        )
                    else:
                        return PreflightResult(
                            item_id=item_id,
                            status=PreflightStatus.PASS,
                            message=f"Instrument calibrated recently",
                            details={
                                "last_calibration": status.last_calibration.isoformat(),
                                "age_minutes": int(age_minutes),
                            },
                        )
                else:
                    # No calibration recorded
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.WARN,
                        message="No calibration recorded",
                        details={},
                    )
            except Exception as e:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.ERROR,
                    message=f"Failed to check calibration: {e}",
                    details={"error": str(e)},
                )
        else:
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.SKIP,
                message="Instrument adapter not provided",
            )

    def _check_instrument_correction(self) -> PreflightResult:
        """
        Check if appropriate correction file is selected.

        Returns:
            PreflightResult with correction file status
        """
        item_id = "instrument_correction"

        if self._correction_file_path:
            path = Path(self._correction_file_path)
            if path.exists():
                # Determine correction file type
                suffix = path.suffix.lower()
                file_type = "Unknown"
                if suffix == ".ccss":
                    file_type = "CCSS (Spectral Sample)"
                elif suffix == ".ccmx":
                    file_type = "CCMX (Correction Matrix)"

                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.PASS,
                    message=f"Correction file selected: {path.name}",
                    details={
                        "path": str(path),
                        "type": file_type,
                    },
                )
            else:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.WARN,
                    message=f"Correction file path invalid: {self._correction_file_path}",
                    details={"path": self._correction_file_path},
                )
        else:
            # No correction file selected
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message="No correction file selected (recommended for colorimeters) - Select a CCSS/CCMX file appropriate for your display technology",
                details={},
            )

    def _check_display_index(self) -> PreflightResult:
        """
        Verify display index is valid.

        Returns:
            PreflightResult with display index status
        """
        item_id = "display_index"

        # Use dispwin to enumerate displays if available
        dispwin_path = self._find_argyll_tool("dispwin")

        if dispwin_path:
            try:
                # dispwin -d list enumerates available displays
                result = subprocess.run(
                    [dispwin_path, "-d"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    # Parse display list from output
                    output = result.stdout.strip()
                    display_count = 0

                    # Argyll display list format:
                    # "1: 'Display 1' [...]"
                    import re
                    matches = re.findall(r"^\s*(\d+):", output, re.MULTILINE)
                    if matches:
                        display_count = len(matches)

                    if display_count > 0:
                        if 1 <= self._display_index <= display_count:
                            return PreflightResult(
                                item_id=item_id,
                                status=PreflightStatus.PASS,
                                message=f"Display index {self._display_index} valid ({display_count} displays available)",
                                details={
                                    "display_index": self._display_index,
                                    "display_count": display_count,
                                    "raw_output": output[:500],  # Limit output size
                                },
                            )
                        else:
                            return PreflightResult(
                                item_id=item_id,
                                status=PreflightStatus.BLOCK,
                                message=f"Display index {self._display_index} invalid (only {display_count} displays)",
                                details={
                                    "display_index": self._display_index,
                                    "display_count": display_count,
                                },
                                suggestion="Select a valid display index",
                            )
                    else:
                        # Could not parse display count, but tool ran
                        return PreflightResult(
                            item_id=item_id,
                            status=PreflightStatus.WARN,
                            message=f"Could not verify display count",
                            details={"raw_output": output[:200]},
                        )
                else:
                    # Tool ran but returned non-zero
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.WARN,
                        message="Could not enumerate displays",
                        details={"stderr": result.stderr[:200] if result.stderr else ""},
                    )
            except Exception as e:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.WARN,
                    message=f"Display enumeration failed: {e}",
                    details={"error": str(e)},
                )
        else:
            # No dispwin available, skip
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.SKIP,
                message="dispwin not available, display index check skipped",
                details={"display_index": self._display_index},
            )

    def _check_hdr_acm_status(self) -> PreflightResult:
        """
        Check HDR and Automatic Color Management status.

        macOS: HDR mode can be detected via CoreGraphics API
        Windows: HDR can be detected via DirectX API

        Returns:
            PreflightResult with HDR/ACM status
        """
        item_id = "display_hdr_acm"

        if self._platform == "Darwin":
            # macOS: Check if HDR mode is active
            try:
                # Use CoreGraphics to check display capabilities
                import ctypes
                import ctypes.util

                cg_path = ctypes.util.find_library("CoreGraphics")
                if cg_path:
                    cg_lib = ctypes.cdll.LoadLibrary(cg_path)

                    # Check if HDR is supported/active
                    # This is a simplified check - full HDR detection requires more API calls
                    # For now, we check if any display has HDR capability

                    # Try to get display list and check HDR
                    # CGGetActiveDisplayList
                    cg_lib.CGGetActiveDisplayList.restype = ctypes.c_uint32
                    cg_lib.CGGetActiveDisplayList.argtypes = [
                        ctypes.c_uint32,
                        ctypes.POINTER(ctypes.c_uint32),
                        ctypes.POINTER(ctypes.c_uint32)
                    ]

                    max_displays = 32
                    displays = (ctypes.c_uint32 * max_displays)()
                    count = ctypes.c_uint32()

                    result = cg_lib.CGGetActiveDisplayList(max_displays, displays, ctypes.byref(count))

                    if result == 0 and count.value > 0:
                        # Found displays, check for HDR
                        # This is a placeholder - actual HDR detection requires
                        # CGDisplayCopyDisplayMode and checking for HDR properties
                        # For now, assume WARN because we can't definitively detect HDR
                        return PreflightResult(
                            item_id=item_id,
                            status=PreflightStatus.WARN,
                            message="HDR/ACM status not fully detectable on macOS",
                            details={
                                "display_count": count.value,
                                "note": "Please manually verify HDR is disabled in System Settings",
                            },
                            suggestion="Disable HDR mode in System Settings > Displays",
                        )
                    else:
                        return PreflightResult(
                            item_id=item_id,
                            status=PreflightStatus.SKIP,
                            message="Could not query display list",
                        )
                else:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.SKIP,
                        message="CoreGraphics not available",
                    )
            except Exception as e:
                logger.debug(f"HDR check failed: {e}")
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.SKIP,
                    message=f"HDR check skipped: {e}",
                )

        elif self._platform == "Windows":
            # Windows: Check HDR status via PowerShell or Win32 API
            try:
                # PowerShell command to check HDR status
                cmd = [
                    "powershell",
                    "-Command",
                    "Get-WmiObject -Namespace root\\wmi -Class WmiMonitorBrightness | Select-Object -Property CurrentBrightness"
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

                # This is simplified - actual HDR detection requires DirectX API
                # For now, return WARN with manual verification suggestion
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.WARN,
                    message="HDR/ACM status requires manual verification on Windows",
                    details={"note": "Disable HDR in Windows Settings > System > Display"},
                    suggestion="Disable HDR mode in Windows Settings",
                )
            except Exception as e:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.SKIP,
                    message=f"Windows HDR check skipped: {e}",
                )

        else:
            # Linux: HDR detection not standardized
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.SKIP,
                message="HDR check not available on Linux",
            )

    def _check_night_shift_status(self) -> PreflightResult:
        """
        Check Night Shift/True Tone status (macOS).

        Returns:
            PreflightResult with Night Shift status
        """
        item_id = "display_night_shift"

        if self._platform != "Darwin":
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.SKIP,
                message="Night Shift check only applicable on macOS",
            )

        try:
            # Check Night Shift status via CoreBrightness framework
            # This requires private framework access, which is complex
            # Alternative: Check via system preferences plist

            # Simplified approach: read plist if accessible
            plist_path = Path("~/Library/Preferences/com.apple.CoreBrightness.plist").expanduser()

            if plist_path.exists():
                # Try to read plist (requires plistlib)
                import plistlib
                try:
                    with open(plist_path, 'rb') as f:
                        plist_data = plistlib.load(f)

                    # Look for Night Shift related keys
                    # CBBlueLightReductionStatusID or similar
                    night_shift_active = False

                    # Check common keys
                    for key in ['CBBlueLightReductionStatusID', 'CBBlueLightActive']:
                        if key in plist_data and plist_data[key]:
                            night_shift_active = True
                            break

                    if night_shift_active:
                        return PreflightResult(
                            item_id=item_id,
                            status=PreflightStatus.WARN,
                            message="Night Shift may be active",
                            details={"plist_path": str(plist_path)},
                            suggestion="Disable Night Shift in System Settings > Displays",
                        )
                    else:
                        return PreflightResult(
                            item_id=item_id,
                            status=PreflightStatus.PASS,
                            message="Night Shift appears to be disabled",
                            details={"plist_path": str(plist_path)},
                        )
                except Exception as e:
                    logger.debug(f"Could not read plist: {e}")
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.WARN,
                        message="Could not determine Night Shift status",
                        suggestion="Manually verify Night Shift is disabled",
                    )
            else:
                # Plist not found
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.WARN,
                    message="Night Shift status unknown",
                    suggestion="Manually disable Night Shift in System Settings",
                )
        except Exception as e:
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message=f"Night Shift check failed: {e}",
            )

    def _check_flux_status(self) -> PreflightResult:
        """
        Check if f.lux or similar color-adjusting software is running.

        Returns:
            PreflightResult with f.lux status
        """
        item_id = "display_f lux"

        # List of known color-adjusting software processes
        conflicting_processes = [
            "flux",
            "f.lux",
            "Redshift",
            "redshift",
            "Redshift-gtk",
            "redshift-gtk",
        ]

        active_processes = []

        try:
            # Check running processes
            if self._platform == "Darwin":
                # Use ps to check running processes
                for process_name in conflicting_processes:
                    result = subprocess.run(
                        ["pgrep", "-x", process_name],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if result.returncode == 0:
                        active_processes.append(process_name)

            elif self._platform == "Windows":
                # Use tasklist on Windows
                result = subprocess.run(
                    ["tasklist"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    output = result.stdout.lower()
                    for process_name in conflicting_processes:
                        if process_name.lower() in output:
                            active_processes.append(process_name)

            elif self._platform == "Linux":
                # Use pgrep on Linux
                for process_name in conflicting_processes:
                    result = subprocess.run(
                        ["pgrep", "-x", process_name],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if result.returncode == 0:
                        active_processes.append(process_name)

            if active_processes:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.WARN,
                    message=f"Color-adjusting software detected: {', '.join(active_processes)}",
                    details={"active_processes": active_processes},
                    suggestion="Quit f.lux, Redshift, or similar color-adjusting software",
                )
            else:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.PASS,
                    message="No color-adjusting software detected",
                    details={"checked_processes": conflicting_processes},
                )
        except Exception as e:
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message=f"f.lux check failed: {e}",
                details={"error": str(e)},
            )

    def _check_system_sleep(self) -> PreflightResult:
        """
        Check system sleep timeout settings.

        Returns:
            PreflightResult with sleep settings status
        """
        item_id = "system_sleep"

        try:
            if self._platform == "Darwin":
                # macOS: Use pmset to check sleep settings
                result = subprocess.run(
                    ["pmset", "-g"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode == 0:
                    output = result.stdout
                    # Parse sleep time from pmset output
                    # Format: "sleep      10" (minutes)
                    import re

                    # Look for sleep setting
                    sleep_match = re.search(r"sleep\s+(\d+)", output)
                    displaysleep_match = re.search(r"displaysleep\s+(\d+)", output)

                    sleep_minutes = int(sleep_match.group(1)) if sleep_match else 0
                    display_sleep_minutes = int(displaysleep_match.group(1)) if displaysleep_match else 0

                    # WARN if sleep is less than 30 minutes (typical measurement time)
                    if sleep_minutes < 30 and sleep_minutes > 0:
                        return PreflightResult(
                            item_id=item_id,
                            status=PreflightStatus.WARN,
                            message=f"System sleep timeout: {sleep_minutes} minutes",
                            details={
                                "sleep_minutes": sleep_minutes,
                                "display_sleep_minutes": display_sleep_minutes,
                            },
                            suggestion="Increase sleep timeout or use sleep prevention feature",
                        )
                    elif sleep_minutes == 0:
                        # Sleep disabled (good)
                        return PreflightResult(
                            item_id=item_id,
                            status=PreflightStatus.PASS,
                            message="System sleep disabled",
                            details={
                                "sleep_minutes": sleep_minutes,
                                "display_sleep_minutes": display_sleep_minutes,
                            },
                        )
                    else:
                        return PreflightResult(
                            item_id=item_id,
                            status=PreflightStatus.PASS,
                            message=f"System sleep timeout: {sleep_minutes} minutes (adequate)",
                            details={
                                "sleep_minutes": sleep_minutes,
                                "display_sleep_minutes": display_sleep_minutes,
                            },
                        )
                else:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.WARN,
                        message="Could not read sleep settings",
                    )

            elif self._platform == "Windows":
                # Windows: Use powercfg to check sleep settings
                result = subprocess.run(
                    ["powercfg", "/query"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode == 0:
                    # Parse sleep timeout from powercfg output
                    # This is complex, simplified to WARN with suggestion
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.WARN,
                        message="Sleep settings require manual verification on Windows",
                        suggestion="Set sleep timeout to at least 30 minutes in Power Settings",
                    )
                else:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.SKIP,
                        message="Could not read sleep settings",
                    )

            elif self._platform == "Linux":
                # Linux: Check systemd sleep settings
                # Simplified check
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.WARN,
                    message="Sleep settings require manual verification on Linux",
                    suggestion="Disable auto-suspend in power settings",
                )

            else:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.SKIP,
                    message="Sleep check not available on this platform",
                )
        except Exception as e:
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message=f"Sleep check failed: {e}",
            )

    def _check_display_sleep(self) -> PreflightResult:
        """
        Check display sleep timeout settings.

        Returns:
            PreflightResult with display sleep status
        """
        item_id = "system_display_sleep"

        # This is often covered by system_sleep check
        # For simplicity, we can reuse the logic or skip if already checked
        # Here we provide a separate check focusing on display sleep

        try:
            if self._platform == "Darwin":
                # Already captured in system_sleep check
                result = subprocess.run(
                    ["pmset", "-g"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode == 0:
                    import re
                    displaysleep_match = re.search(r"displaysleep\s+(\d+)", result.stdout)
                    display_sleep_minutes = int(displaysleep_match.group(1)) if displaysleep_match else 0

                    if display_sleep_minutes < 15 and display_sleep_minutes > 0:
                        return PreflightResult(
                            item_id=item_id,
                            status=PreflightStatus.WARN,
                            message=f"Display sleep: {display_sleep_minutes} minutes",
                            details={"display_sleep_minutes": display_sleep_minutes},
                            suggestion="Increase display sleep timeout",
                        )
                    elif display_sleep_minutes == 0:
                        return PreflightResult(
                            item_id=item_id,
                            status=PreflightStatus.PASS,
                            message="Display sleep disabled",
                            details={"display_sleep_minutes": display_sleep_minutes},
                        )
                    else:
                        return PreflightResult(
                            item_id=item_id,
                            status=PreflightStatus.PASS,
                            message=f"Display sleep: {display_sleep_minutes} minutes (adequate)",
                            details={"display_sleep_minutes": display_sleep_minutes},
                        )

            elif self._platform == "Windows":
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.WARN,
                    message="Display sleep requires manual verification",
                    suggestion="Set display timeout to at least 15 minutes",
                )

            else:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.SKIP,
                    message="Display sleep check not available",
                )
        except Exception as e:
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message=f"Display sleep check failed: {e}",
            )

    def _check_usb_permission(self) -> PreflightResult:
        """
        Check USB device access permission (macOS).

        Returns:
            PreflightResult with USB permission status
        """
        item_id = "permission_usb"

        if self._platform != "Darwin":
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.SKIP,
                message="USB permission check only applicable on macOS",
            )

        # On macOS, USB permission is required for HID devices
        # Actual permission check requires attempting device access
        # This is a simplified check

        try:
            # Try to check if we can access USB devices
            # Use IOKit to enumerate USB devices
            import ctypes
            import ctypes.util

            iokit_path = ctypes.util.find_library("IOKit")
            if iokit_path:
                iokit = ctypes.cdll.LoadLibrary(iokit_path)

                # IOKitMasterPort
                iokit.IOMasterPort.restype = ctypes.c_uint32
                iokit.IOMasterPort.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]

                # IOServiceMatching
                iokit.IOServiceMatching.restype = ctypes.c_void_p
                iokit.IOServiceMatching.argtypes = [ctypes.c_char_p]

                master_port = ctypes.c_uint32()
                iokit.IOMasterPort(ctypes.c_uint32(0), ctypes.byref(master_port))

                # Try to match USB devices
                # 注意 argtypes 声明为 c_char_p，必须传字节串；传 str 会
                # 抛 TypeError("wrong type")，导致该检查在所有 macOS 上都失败
                matching = iokit.IOServiceMatching(b"IOUSBDevice")
                if matching:
                    # Can create USB matching dictionary, permissions likely OK
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.PASS,
                        message="USB device access appears available",
                        details={"note": "Full permission check requires actual device access"},
                    )
                else:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.WARN,
                        message="Could not verify USB permission",
                        details={"suggestion": "Grant USB device access in System Settings > Privacy & Security"},
                        fix_command="open 'x-apple.systempreferences:com.apple.preference.security?Privacy_USB'",
                    )
            else:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.SKIP,
                    message="IOKit not available",
                )
        except Exception as e:
            logger.debug(f"USB permission check failed: {e}")
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message=f"Could not verify USB permission: {e}",
                details={"suggestion": "If instrument fails to connect, grant USB access in System Settings"},
            )

    def _check_accessibility_permission(self) -> PreflightResult:
        """
        Check accessibility permission for DDC/CI control (macOS).

        Returns:
            PreflightResult with accessibility status
        """
        item_id = "permission_accessibility"

        if self._platform != "Darwin":
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.SKIP,
                message="Accessibility check only applicable on macOS",
            )

        try:
            # Use AXIsProcessTrusted to check accessibility permission
            import ctypes

            # Load ApplicationServices framework
            app_services_path = ctypes.util.find_library("ApplicationServices")
            if app_services_path:
                app_services = ctypes.cdll.LoadLibrary(app_services_path)

                # AXIsProcessTrusted
                app_services.AXIsProcessTrusted.restype = ctypes.c_bool
                app_services.AXIsProcessTrusted.argtypes = []

                is_trusted = app_services.AXIsProcessTrusted()

                if is_trusted:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.PASS,
                        message="Accessibility permission granted",
                    )
                else:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.WARN,
                        message="Accessibility permission not granted",
                        details={"note": "Required for DDC/CI display control", "suggestion": "Grant accessibility permission in System Settings > Privacy & Security"},
                        fix_command="open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'",
                    )
            else:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.SKIP,
                    message="ApplicationServices not available",
                )
        except Exception as e:
            logger.debug(f"Accessibility check failed: {e}")
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message=f"Could not verify accessibility permission: {e}",
                details={"suggestion": "Grant accessibility permission if DDC/CI control is needed"},
            )

    def _check_screen_capture_permission(self) -> PreflightResult:
        """
        Check screen recording permission for LUT verification (macOS).

        Returns:
            PreflightResult with screen capture status
        """
        item_id = "permission_screen_capture"

        if self._platform != "Darwin":
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.SKIP,
                message="Screen capture check only applicable on macOS",
            )

        try:
            # Use CoreGraphics to check screen capture capability
            import ctypes
            import ctypes.util

            cg_path = ctypes.util.find_library("CoreGraphics")
            if cg_path:
                cg_lib = ctypes.cdll.LoadLibrary(cg_path)

                # Try to get window list - this requires screen recording permission
                cg_lib.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
                cg_lib.CGWindowListCopyWindowInfo.argtypes = [
                    ctypes.c_uint32, ctypes.c_uint32
                ]

                # kCGWindowListOptionOnScreenOnly = 1
                window_list = cg_lib.CGWindowListCopyWindowInfo(
                    ctypes.c_uint32(1), ctypes.c_uint32(0)
                )

                if window_list:
                    # Can access window list, permission likely granted
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.PASS,
                        message="Screen recording permission appears available",
                        details={"note": "Required for LUT verification"},
                    )
                else:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.WARN,
                        message="Screen recording permission may not be granted",
                        details={"note": "Required for display output verification"},
                        suggestion="Grant screen recording permission in System Settings > Privacy & Security",
                        fix_command="open 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'",
                    )
            else:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.SKIP,
                    message="CoreGraphics not available",
                )
        except Exception as e:
            logger.debug(f"Screen capture check failed: {e}")
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message=f"Could not verify screen recording permission: {e}",
                suggestion="If LUT verification fails, grant screen recording permission",
            )

    def _check_usb_permission_windows(self) -> PreflightResult:
        """
        Check USB HID device access on Windows.

        Returns:
            PreflightResult with USB permission status
        """
        item_id = "permission_usb_windows"

        if self._platform != "Windows":
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.SKIP,
                message="USB Windows check only applicable on Windows",
            )

        try:
            # Windows: Check HID device availability via PowerShell
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-PnpDevice -Class 'HIDClass' | Where-Object {$_.Status -eq 'OK'} | Select-Object -First 5"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0 and result.stdout.strip():
                # HID devices are available
                # Parse to check if any measurement device might be present
                output = result.stdout.strip()
                hid_count = len(output.split('\n')) - 1  # Subtract header

                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.PASS,
                    message=f"HID devices available ({hid_count} devices found)",
                    details={"hid_devices": hid_count},
                )
            else:
                # Check if HID driver is blocked
                result2 = subprocess.run(
                    ["powershell", "-Command",
                     "Get-PnpDevice -Class 'HIDClass' | Where-Object {$_.Status -ne 'OK'}"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result2.returncode == 0 and result2.stdout.strip():
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.WARN,
                        message="Some HID devices have issues",
                        details={"raw_output": result2.stdout[:200]},
                        suggestion="Check Device Manager for HID device status",
                        fix_command="devmgmt.msc",
                    )
                else:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.WARN,
                        message="Could not verify HID device status",
                        suggestion="Connect measurement instrument and check Device Manager",
                    )
        except Exception as e:
            logger.debug(f"Windows USB check failed: {e}")
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message=f"USB permission check failed: {e}",
                suggestion="Ensure instrument is connected and drivers installed",
            )

    def _check_ddc_ci_windows(self) -> PreflightResult:
        """
        Check DDC/CI availability on Windows.

        Returns:
            PreflightResult with DDC/CI status
        """
        item_id = "permission_ddc_ci_windows"

        if self._platform != "Windows":
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.SKIP,
                message="DDC/CI Windows check only applicable on Windows",
            )

        try:
            # Windows: Check if WmiMonitorBrightness is available (indicates DDC/CI support)
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-WmiObject -Namespace root\\wmi -Class WmiMonitorBrightness -ErrorAction SilentlyContinue"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0 and result.stdout.strip():
                # DDC/CI brightness control is available
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.PASS,
                    message="DDC/CI brightness control available",
                    details={"note": "Monitor supports MCCS/DDC/CI"},
                )
            else:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.WARN,
                    message="DDC/CI not available or monitor doesn't support MCCS",
                    details={"note": "Brightness control may require manual adjustment"},
                    suggestion="Enable DDC/CI in monitor OSD settings",
                )
        except Exception as e:
            logger.debug(f"Windows DDC/CI check failed: {e}")
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message=f"DDC/CI check failed: {e}",
                suggestion="If display control is needed, enable DDC/CI in monitor OSD",
            )

    def _check_usb_permission_linux(self) -> PreflightResult:
        """
        Check USB HID device permissions on Linux.

        Returns:
            PreflightResult with USB permission status
        """
        item_id = "permission_usb_linux"

        if self._platform != "Linux":
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.SKIP,
                message="USB Linux check only applicable on Linux",
            )

        try:
            # Linux: Check HID device permissions
            import glob

            hid_devices = glob.glob("/dev/hidraw*")
            if not hid_devices:
                hid_devices = glob.glob("/dev/usb/hid*")

            if hid_devices:
                # Check if we have read/write access
                accessible_devices = []
                inaccessible_devices = []

                for device in hid_devices:
                    if os.access(device, os.R_OK | os.W_OK):
                        accessible_devices.append(device)
                    else:
                        inaccessible_devices.append(device)

                if accessible_devices:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.PASS,
                        message=f"HID devices accessible ({len(accessible_devices)} devices)",
                        details={
                            "accessible_devices": accessible_devices[:5],
                            "inaccessible_devices": inaccessible_devices[:5],
                        },
                    )
                else:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.BLOCK,
                        message="No HID devices accessible",
                        details={
                            "found_devices": hid_devices[:5],
                            "permissions": "Need read/write access",
                        },
                        suggestion="Add udev rules or join uucp group",
                        fix_command="sudo usermod -a -G uucp $USER",
                    )
            else:
                # No HID devices found - might mean instrument not connected
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.WARN,
                    message="No HID devices found - instrument may not be connected",
                    details={"note": "Connect instrument and check /dev/hidraw*"},
                    suggestion="Connect measurement instrument via USB",
                )
        except Exception as e:
            logger.debug(f"Linux USB check failed: {e}")
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message=f"USB permission check failed: {e}",
                suggestion="If instrument fails to connect, configure udev rules",
                fix_command="sudo tee /etc/udev/rules.d/99-argyll.rules <<< 'SUBSYSTEM==\"hidraw\", MODE=\"0666\"'",
            )

    def _check_i2c_permission_linux(self) -> PreflightResult:
        """
        Check i2c-dev module and permissions on Linux for DDC/CI.

        Returns:
            PreflightResult with i2c permission status
        """
        item_id = "permission_i2c_linux"

        if self._platform != "Linux":
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.SKIP,
                message="i2c Linux check only applicable on Linux",
            )

        try:
            import glob

            # Check if i2c-dev module is loaded
            result = subprocess.run(
                ["lsmod"],
                capture_output=True,
                text=True,
                timeout=5
            )

            i2c_loaded = "i2c_dev" in result.stdout

            # Check i2c device permissions
            i2c_devices = glob.glob("/dev/i2c-*")

            if not i2c_loaded:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.WARN,
                    message="i2c-dev module not loaded",
                    details={"note": "Required for DDC/CI communication"},
                    suggestion="Load i2c-dev module: sudo modprobe i2c-dev",
                    fix_command="sudo modprobe i2c-dev",
                )

            if i2c_devices:
                # Check access permissions
                accessible_devices = []
                inaccessible_devices = []

                for device in i2c_devices:
                    if os.access(device, os.R_OK | os.W_OK):
                        accessible_devices.append(device)
                    else:
                        inaccessible_devices.append(device)

                if accessible_devices:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.PASS,
                        message=f"i2c-dev accessible ({len(accessible_devices)} devices)",
                        details={
                            "accessible_devices": accessible_devices[:5],
                            "module_loaded": i2c_loaded,
                        },
                    )
                else:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.WARN,
                        message="i2c-dev module loaded but no device access",
                        details={
                            "found_devices": i2c_devices[:5],
                            "module_loaded": i2c_loaded,
                        },
                        suggestion="Join i2c group or configure device permissions",
                        fix_command="sudo usermod -a -G i2c $USER",
                    )
            else:
                # No i2c devices - DDC/CI may not be available
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.WARN,
                    message="No i2c devices found",
                    details={
                        "module_loaded": i2c_loaded,
                        "note": "DDC/CI may not be available on this system",
                    },
                    suggestion="If DDC/CI is needed, check monitor and kernel support",
                )
        except Exception as e:
            logger.debug(f"Linux i2c check failed: {e}")
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message=f"i2c permission check failed: {e}",
                suggestion="Configure i2c-dev for DDC/CI support",
            )

    def _check_backlight_permission_linux(self) -> PreflightResult:
        """
        Check backlight control permissions on Linux.

        Returns:
            PreflightResult with backlight permission status
        """
        item_id = "permission_backlight_linux"

        if self._platform != "Linux":
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.SKIP,
                message="Backlight Linux check only applicable on Linux",
            )

        try:
            import glob

            # Check backlight devices
            backlight_devices = glob.glob("/sys/class/backlight/*")

            if backlight_devices:
                # Check write permission to brightness file
                accessible_devices = []
                inaccessible_devices = []

                for device in backlight_devices:
                    brightness_file = os.path.join(device, "brightness")
                    if os.path.exists(brightness_file):
                        if os.access(brightness_file, os.W_OK):
                            accessible_devices.append(os.path.basename(device))
                        else:
                            inaccessible_devices.append(os.path.basename(device))

                if accessible_devices:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.PASS,
                        message=f"Backlight control accessible ({len(accessible_devices)} devices)",
                        details={"accessible_devices": accessible_devices},
                    )
                else:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.WARN,
                        message="Backlight control not accessible",
                        details={
                            "found_devices": inaccessible_devices,
                            "note": "Need write permission to /sys/class/backlight/*/brightness",
                        },
                        suggestion="Join video group for backlight control",
                        fix_command="sudo usermod -a -G video $USER",
                    )
            else:
                # No backlight devices - may not be applicable (external monitor)
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.SKIP,
                    message="No backlight devices found (external monitor or not applicable)",
                )
        except Exception as e:
            logger.debug(f"Linux backlight check failed: {e}")
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message=f"Backlight permission check failed: {e}",
                suggestion="If brightness control is needed, join video group",
            )

    def _check_current_icc_profile(self) -> PreflightResult:
        """
        Check which ICC profile is currently loaded on the target display.

        macOS: use the ColorSync/Quartz API directly (fast, no subprocess).
        Other platforms: skipped (dispwin has no query mode; the previous
        `dispwin -d n -i` here was wrong — `-i` means "run forever with
        random values", which hung until the 10s timeout).
        """
        item_id = "icc_current_profile"

        if self._platform == "Darwin":
            return self._check_current_icc_profile_macos(item_id)

        return PreflightResult(
            item_id=item_id,
            status=PreflightStatus.SKIP,
            message="Automatic ICC profile query not supported on this platform",
        )

    def _check_current_icc_profile_macos(self, item_id: str) -> PreflightResult:
        """Query current display color space via Quartz ColorSync API."""
        try:
            import Quartz

            # 注意：CGGetDisplaysWithRect 在 pyobjc 下以 None 回调调用会直接
            # abort 进程（非异常），必须用 CGGetActiveDisplayList 枚举显示器
            err, display_ids, _count = Quartz.CGGetActiveDisplayList(16, None, None)
            if err != 0 or not display_ids:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.WARN,
                    message="Could not enumerate displays for ICC check",
                )
            index = max(1, int(self._display_index or 1))
            display_id = display_ids[min(index, len(display_ids)) - 1]

            space = Quartz.CGDisplayCopyColorSpace(display_id)
            if space is None:
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.WARN,
                    message="Could not read display color space",
                )

            # 优先从 ICC 数据解析 profile 描述名；系统色彩空间则退回其常量名
            name = None
            icc_ref = Quartz.CGColorSpaceCopyICCData(space)
            if icc_ref is not None:
                name = self._icc_description_from_bytes(bytes(icc_ref))
            if not name:
                cs_name = Quartz.CGColorSpaceCopyName(space)
                name = str(cs_name) if cs_name else "Unknown"

            lowered = name.lower()
            if "linear" in lowered or "null" in lowered or lowered.startswith("kcgcolorspace"):
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.PASS,
                    message=f"Null/system color space in use: {name}",
                    details={"profile_name": name},
                )
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message=f"Custom ICC profile loaded: {name}",
                details={"profile_name": name},
                suggestion="Clear ICC profile for accurate measurements",
            )
        except Exception as e:
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.WARN,
                message=f"ICC profile check failed: {e}",
            )

    @staticmethod
    def _icc_description_from_bytes(data: bytes) -> Optional[str]:
        """
        Parse the profile description name from ICC binary data.

        Supports the v2 'desc' tag and the v4 'mluc' tag; returns None if
        neither is present or the data is malformed.
        """
        import struct

        if len(data) < 132:
            return None
        try:
            tag_count = struct.unpack_from(">I", data, 128)[0]
            for i in range(min(tag_count, 256)):
                off = 128 + 4 + i * 12
                if off + 12 > len(data):
                    return None
                sig, toff, _tsize = struct.unpack_from(">4sII", data, off)
                if sig == b"desc" and toff + 12 <= len(data):
                    count = struct.unpack_from(">I", data, toff + 8)[0]
                    raw = data[toff + 12: toff + 12 + count]
                    return raw.split(b"\x00")[0].decode("ascii", "replace").strip()
                if sig == b"mluc" and toff + 28 <= len(data):
                    rec_count, rec_size = struct.unpack_from(">II", data, toff + 8)
                    if rec_count >= 1:
                        _lang, _country, slen, soff = struct.unpack_from(
                            ">HHII", data, toff + 16)
                        raw = data[toff + soff: toff + soff + slen]
                        return raw.decode("utf-16-be", "replace").strip("\x00 ").strip()
        except (struct.error, UnicodeDecodeError):
            return None
        return None

    def _check_vcgt_lut_status(self) -> PreflightResult:
        """
        Check video card gamma table (VCGT) status.

        Returns:
            PreflightResult with VCGT status
        """
        item_id = "lut_vcgt_status"

        dispwin_path = self._find_argyll_tool("dispwin")

        if dispwin_path:
            try:
                # Try to read VCGT using dispwin or other method
                # dispwin doesn't have a direct "query VCGT" command
                # We can use the LUT controller's internal methods if available

                # For now, use a simplified approach
                # If a linear profile is loaded, VCGT should be linear

                # Check if we can query the gamma table
                if self._platform == "Darwin":
                    import ctypes
                    import ctypes.util

                    cg_path = ctypes.util.find_library("CoreGraphics")
                    if cg_path:
                        cg_lib = ctypes.cdll.LoadLibrary(cg_path)

                        # CGGetDisplayTransferByTable
                        cg_lib.CGMainDisplayID.restype = ctypes.c_uint32
                        cg_lib.CGMainDisplayID.argtypes = []
                        cg_lib.CGGetDisplayTransferByTable.restype = ctypes.c_int32
                        cg_lib.CGGetDisplayTransferByTable.argtypes = [
                            ctypes.c_uint32, ctypes.c_uint32,
                            ctypes.POINTER(ctypes.c_float),
                            ctypes.POINTER(ctypes.c_float),
                            ctypes.POINTER(ctypes.c_float),
                            ctypes.POINTER(ctypes.c_uint32)
                        ]

                        display_id = cg_lib.CGMainDisplayID()
                        table_size = 256

                        red = (ctypes.c_float * table_size)()
                        green = (ctypes.c_float * table_size)()
                        blue = (ctypes.c_float * table_size)()
                        count = ctypes.c_uint32()

                        result = cg_lib.CGGetDisplayTransferByTable(
                            display_id, table_size, red, green, blue, ctypes.byref(count)
                        )

                        if result == 0 and count.value > 0:
                            # Check if gamma table is linear
                            # Linear: y = x for all channels
                            is_linear = True
                            tolerance = 0.01  # 1% tolerance

                            for i in range(min(count.value, table_size)):
                                x = i / (table_size - 1)
                                expected = x
                                # Check each channel
                                if abs(red[i] - expected) > tolerance:
                                    is_linear = False
                                    break
                                if abs(green[i] - expected) > tolerance:
                                    is_linear = False
                                    break
                                if abs(blue[i] - expected) > tolerance:
                                    is_linear = False
                                    break

                            if is_linear:
                                return PreflightResult(
                                    item_id=item_id,
                                    status=PreflightStatus.PASS,
                                    message="VCGT LUT is linear",
                                    details={"table_entries": count.value},
                                )
                            else:
                                return PreflightResult(
                                    item_id=item_id,
                                    status=PreflightStatus.WARN,
                                    message="VCGT LUT is modified (non-linear)",
                                    details={"table_entries": count.value},
                                    suggestion="Clear VCGT LUT for accurate measurements",
                                )
                        else:
                            return PreflightResult(
                                item_id=item_id,
                                status=PreflightStatus.WARN,
                                message="Could not read VCGT",
                            )

                elif self._platform == "Windows":
                    # Windows: Check gamma table via Win32 API
                    # Simplified for now
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.WARN,
                        message="VCGT check requires manual verification on Windows",
                        suggestion="Verify display gamma settings",
                    )

                else:
                    return PreflightResult(
                        item_id=item_id,
                        status=PreflightStatus.SKIP,
                        message="VCGT check not available on this platform",
                    )

            except Exception as e:
                logger.debug(f"VCGT check failed: {e}")
                return PreflightResult(
                    item_id=item_id,
                    status=PreflightStatus.WARN,
                    message=f"VCGT check failed: {e}",
                )
        else:
            return PreflightResult(
                item_id=item_id,
                status=PreflightStatus.SKIP,
                message="VCGT check skipped (dispwin not available)",
            )

    # ========== Main Check Execution ==========

    def run_single_check(self, item: PreflightItem) -> PreflightResult:
        """
        Run a single pre-flight check.

        Args:
            item: The check item to execute

        Returns:
            PreflightResult with check outcome
        """
        # Check platform applicability
        if item.platform_specific:
            if self._platform not in item.platform_specific:
                return PreflightResult(
                    item_id=item.id,
                    status=PreflightStatus.SKIP,
                    message=f"Check skipped (not applicable on {self._platform})",
                )

        # Map item ID to check method
        check_method_map = {
            "argyll_spotread": lambda: self._check_argyll_tool("spotread"),
            "argyll_dispcal": lambda: self._check_argyll_tool("dispcal"),
            "argyll_targen": lambda: self._check_argyll_tool("targen"),
            "argyll_colprof": lambda: self._check_argyll_tool("colprof"),
            "argyll_collink": lambda: self._check_argyll_tool("collink"),
            "argyll_dispwin": lambda: self._check_argyll_tool("dispwin"),
            "argyll_ccxxmake": lambda: self._check_argyll_tool("ccxxmake"),
            "instrument_connected": self._check_instrument_connection,
            "instrument_calibrated": self._check_instrument_calibration,
            "instrument_correction": self._check_instrument_correction,
            "display_index": self._check_display_index,
            "display_hdr_acm": self._check_hdr_acm_status,
            "display_night_shift": self._check_night_shift_status,
            "display_f lux": self._check_flux_status,
            "system_sleep": self._check_system_sleep,
            "system_display_sleep": self._check_display_sleep,
            # macOS permissions
            "permission_usb": self._check_usb_permission,
            "permission_screen_capture": self._check_screen_capture_permission,
            "permission_accessibility": self._check_accessibility_permission,
            # Windows permissions
            "permission_usb_windows": self._check_usb_permission_windows,
            "permission_ddc_ci_windows": self._check_ddc_ci_windows,
            # Linux permissions
            "permission_usb_linux": self._check_usb_permission_linux,
            "permission_i2c_linux": self._check_i2c_permission_linux,
            "permission_backlight_linux": self._check_backlight_permission_linux,
            # ICC/LUT
            "icc_current_profile": self._check_current_icc_profile,
            "lut_vcgt_status": self._check_vcgt_lut_status,
        }

        check_method = check_method_map.get(item.id)

        if check_method:
            try:
                return check_method()
            except Exception as e:
                logger.error(f"Pre-flight check {item.id} failed with exception: {e}")
                return PreflightResult(
                    item_id=item.id,
                    status=PreflightStatus.ERROR,
                    message=f"Check execution failed: {e}",
                    details={"error": str(e)},
                )
        else:
            logger.warning(f"No check method defined for item: {item.id}")
            return PreflightResult(
                item_id=item.id,
                status=PreflightStatus.SKIP,
                message=f"Check method not implemented",
            )

    def run_all_checks(
        self,
        skip_items: Optional[List[str]] = None,
        only_items: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
    ) -> PreflightReport:
        """
        Run all defined pre-flight checks and generate report.

        Args:
            skip_items: List of item IDs to skip
            only_items: List of item IDs to run (if specified, skip others)
            progress_callback: Optional callback for progress updates.
                Signature: (current, total, item_id, label)
                - current: Current check index (1-based)
                - total: Total number of checks
                - item_id: ID of the current check item
                - label: Human-readable name of the current check

        Returns:
            PreflightReport with all check results
        """
        report = PreflightReport()
        report.argyll_version = self._get_argyll_version()

        # Add environment info
        report.environment_info = {
            "platform": self._platform,
            "python_version": platform.python_version(),
            "argyll_bin_path": self._argyll_bin_path,
            "display_index": self._display_index,
            "correction_file": self._correction_file_path,
        }

        # Determine which items to run
        items_to_run = self._check_items

        if only_items:
            items_to_run = [i for i in items_to_run if i.id in only_items]

        if skip_items:
            items_to_run = [i for i in items_to_run if i.id not in skip_items]

        total_checks = len(items_to_run)

        # Run each check
        for current_index, item in enumerate(items_to_run, start=1):
            # Emit progress before running check (if callback provided)
            if progress_callback:
                progress_callback(current_index, total_checks, item.id, item.name)

            result = self.run_single_check(item)
            report.add_result(result)

        # Calculate summary
        report.calculate_summary()

        logger.info(
            f"Pre-flight check completed: "
            f"{report.summary['pass_count']} PASS, "
            f"{report.summary['warn_count']} WARN, "
            f"{report.summary['block_count']} BLOCK, "
            f"{report.summary['skip_count']} SKIP"
        )

        return report

    def run_quick_checks(self) -> PreflightReport:
        """
        Run only essential checks (Argyll tools + instrument).

        Returns:
            PreflightReport with essential check results
        """
        essential_items = [
            "argyll_spotread",
            "argyll_dispwin",
            "instrument_connected",
            "display_index",
        ]
        return self.run_all_checks(only_items=essential_items)

    def get_item_definition(self, item_id: str) -> Optional[PreflightItem]:
        """Get definition of a specific check item."""
        for item in self._check_items:
            if item.id == item_id:
                return item
        return None


# ========== Utility Functions ==========

def create_preflight_checker(
    argyll_bin_path: Optional[str] = None,
    instrument_adapter: Optional[Any] = None,
    display_index: int = 1,
    correction_file_path: Optional[str] = None,
) -> PreflightChecker:
    """
    Factory function to create a PreflightChecker.

    Args:
        argyll_bin_path: Path to ArgyllCMS bin directory
        instrument_adapter: Instrument adapter instance
        display_index: Target display index
        correction_file_path: Path to correction file

    Returns:
        PreflightChecker instance
    """
    return PreflightChecker(
        argyll_bin_path=argyll_bin_path,
        instrument_adapter=instrument_adapter,
        display_index=display_index,
        correction_file_path=correction_file_path,
    )


def run_preflight_checks(
    argyll_bin_path: Optional[str] = None,
    instrument_adapter: Optional[Any] = None,
    display_index: int = 1,
    correction_file_path: Optional[str] = None,
    quick: bool = False,
) -> PreflightReport:
    """
    Convenience function to run pre-flight checks.

    Args:
        argyll_bin_path: Path to ArgyllCMS bin directory
        instrument_adapter: Instrument adapter instance
        display_index: Target display index
        correction_file_path: Path to correction file
        quick: Run only essential checks

    Returns:
        PreflightReport with check results
    """
    checker = create_preflight_checker(
        argyll_bin_path=argyll_bin_path,
        instrument_adapter=instrument_adapter,
        display_index=display_index,
        correction_file_path=correction_file_path,
    )

    if quick:
        return checker.run_quick_checks()
    else:
        return checker.run_all_checks()


def export_preflight_report(report: PreflightReport, filepath: Union[str, Path]) -> bool:
    """
    Export pre-flight report to a JSON file.

    Args:
        report: The report to export
        filepath: Destination file path

    Returns:
        True if export successful
    """
    return report.export_to_file(filepath)


# ========== Permission Status Functions ==========

def get_permission_status_summary(report: PreflightReport) -> Dict[str, Any]:
    """
    Extract permission check results from a preflight report.

    This function is designed for diagnostic package generation,
    providing a focused summary of permission status for troubleshooting.

    Args:
        report: PreflightReport containing all check results

    Returns:
        Dictionary with permission status summary:
        - platform: Current platform
        - permissions: List of permission check results
        - blocking_permissions: List of blocking permission issues
        - warning_permissions: List of warning permission issues
        - fix_commands: Available fix commands for issues
    """
    # Permission check item IDs
    permission_item_ids = [
        # macOS
        "permission_usb",
        "permission_screen_capture",
        "permission_accessibility",
        # Windows
        "permission_usb_windows",
        "permission_ddc_ci_windows",
        # Linux
        "permission_usb_linux",
        "permission_i2c_linux",
        "permission_backlight_linux",
    ]

    permissions = []
    blocking_permissions = []
    warning_permissions = []
    fix_commands = []

    for result in report.results:
        if result.item_id in permission_item_ids:
            perm_data = {
                "item_id": result.item_id,
                "status": result.status.value,
                "message": result.message,
                "details": result.details,
            }

            if result.fix_command:
                perm_data["fix_command"] = result.fix_command
                fix_commands.append({
                    "item_id": result.item_id,
                    "command": result.fix_command,
                })

            if result.fix_url:
                perm_data["fix_url"] = result.fix_url

            permissions.append(perm_data)

            if result.status == PreflightStatus.BLOCK:
                blocking_permissions.append(perm_data)
            elif result.status == PreflightStatus.WARN:
                warning_permissions.append(perm_data)

    return {
        "platform": report.platform,
        "timestamp": report.timestamp.isoformat(),
        "permissions": permissions,
        "blocking_permissions": blocking_permissions,
        "warning_permissions": warning_permissions,
        "fix_commands": fix_commands,
        "summary": {
            "total_permissions_checked": len(permissions),
            "blocking_count": len(blocking_permissions),
            "warning_count": len(warning_permissions),
            "pass_count": sum(1 for p in permissions if p["status"] == "PASS"),
        },
    }


def run_permission_checks_only(
    argyll_bin_path: Optional[str] = None,
    display_index: int = 1,
) -> PreflightReport:
    """
    Run only permission-related checks for quick diagnostics.

    This is useful for generating diagnostic packages when users
    report permission-related issues.

    Args:
        argyll_bin_path: Path to ArgyllCMS bin directory
        display_index: Target display index

    Returns:
        PreflightReport with only permission check results
    """
    permission_item_ids = [
        "permission_usb",
        "permission_screen_capture",
        "permission_accessibility",
        "permission_usb_windows",
        "permission_ddc_ci_windows",
        "permission_usb_linux",
        "permission_i2c_linux",
        "permission_backlight_linux",
    ]

    checker = create_preflight_checker(
        argyll_bin_path=argyll_bin_path,
        display_index=display_index,
    )

    return checker.run_all_checks(only_items=permission_item_ids)


def export_permission_status_report(filepath: Union[str, Path]) -> bool:
    """
    Run permission checks and export results to a JSON file.

    This function is designed to be called from diagnostic package
    generation to include permission status in the diagnostic data.

    Args:
        filepath: Destination file path for the permission report

    Returns:
        True if export successful
    """
    try:
        report = run_permission_checks_only()
        summary = get_permission_status_summary(report)

        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        logger.info(f"Permission status report exported to: {path}")
        return True
    except Exception as e:
        logger.error(f"Failed to export permission status report: {e}")
        return False
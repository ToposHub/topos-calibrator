"""
Correction file management for measurement instruments.

This module provides:
- CCSS/CCMX file parsing and metadata extraction
- Correction file compatibility checking
- Hash calculation for measurement association
- CCMX creation wizard support

Correction file types:
- CCSS: Spectral correction from spectrophotometer, for specific display technology
- CCMX: Matrix correction requiring spectrophotometer as reference

Reference: docs/professional_optimization_plan.md - Task P3-D
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class CorrectionType(Enum):
    """Type of correction file."""
    CCSS = "ccss"  # Spectral correction (from spectrophotometer)
    CCMX = "ccmx"  # Matrix correction (requires spectrophotometer reference)


class DisplayTechnology(Enum):
    """Display technology types for correction compatibility.

    Maps to ArgyllCMS ccxxmake -t parameter values.
    """
    # Generic types
    LCD_GENERIC = "l"
    CRT = "c"
    OLED = "o"
    PLASMA = "m"
    PROJECTOR = "p"

    # LCD by backlight
    LCD_CCFL = "1"
    LCD_WHITE_LED = "e"
    LCD_RGB_LED = "b"
    LCD_RG_PHOSPHOR = "h"
    LCD_PFS_PHOSPHOR = "r"
    LCD_GB_R_PHOSPHOR = "i"

    # OLED variants
    AMOLED = "a"
    WOLED = "w"

    @classmethod
    def from_argyll_code(cls, code: str) -> Optional['DisplayTechnology']:
        """Convert ArgyllCMS technology code to DisplayTechnology."""
        for tech in cls:
            if tech.value == code.lower():
                return tech
        return None

    @classmethod
    def from_display_name(cls, name: str) -> Optional['DisplayTechnology']:
        """Convert display name/type string to DisplayTechnology.

        Handles common names like 'OLED', 'LCD', 'IPS', etc.
        """
        name_lower = name.lower()

        # OLED detection
        if 'oled' in name_lower:
            if 'woled' in name_lower or 'lg' in name_lower:
                return cls.WOLED
            if 'amoled' in name_lower:
                return cls.AMOLED
            return cls.OLED

        # Plasma detection
        if 'plasma' in name_lower:
            return cls.PLASMA

        # Projector detection
        if 'projector' in name_lower or 'dlp' in name_lower:
            return cls.PROJECTOR

        # CRT detection
        if 'crt' in name_lower:
            return cls.CRT

        # LCD detection with backlight type
        if 'lcd' in name_lower or 'ips' in name_lower or 'tft' in name_lower:
            if 'rgb led' in name_lower or 'rgb-led' in name_lower:
                return cls.LCD_RGB_LED
            if 'white led' in name_lower or 'led' in name_lower:
                return cls.LCD_WHITE_LED
            if 'rg phosphor' in name_lower:
                return cls.LCD_RG_PHOSPHOR
            if 'pfs phosphor' in name_lower or 'quantum dot' in name_lower:
                return cls.LCD_PFS_PHOSPHOR
            if 'gb-r' in name_lower or 'gb r' in name_lower:
                return cls.LCD_GB_R_PHOSPHOR
            if 'ccfl' in name_lower:
                return cls.LCD_CCFL
            return cls.LCD_GENERIC

        return None

    def get_display_name(self) -> str:
        """Get human-readable display name."""
        names = {
            self.LCD_GENERIC: "LCD (通用)",
            self.CRT: "CRT",
            self.OLED: "OLED",
            self.PLASMA: "等离子",
            self.PROJECTOR: "投影仪",
            self.LCD_CCFL: "LCD CCFL",
            self.LCD_WHITE_LED: "LCD White LED",
            self.LCD_RGB_LED: "LCD RGB LED",
            self.LCD_RG_PHOSPHOR: "LCD RG Phosphor",
            self.LCD_PFS_PHOSPHOR: "LCD PFS Phosphor (量子点)",
            self.LCD_GB_R_PHOSPHOR: "LCD GB-R Phosphor",
            self.AMOLED: "AMOLED",
            self.WOLED: "WOLED (LG OLED)",
        }
        return names.get(self, self.value)


@dataclass
class ProbeInfo:
    """Information about a measurement probe/instrument.

    Attributes:
        name: Probe name (e.g., "i1 Display Pro", "i1 Pro 2")
        argyll_type: ArgyllCMS instrument type code
        is_spectrophotometer: Whether this is a spectrophotometer
        is_colorimeter: Whether this is a colorimeter
    """
    name: str = ""
    argyll_type: str = ""
    is_spectrophotometer: bool = False
    is_colorimeter: bool = False

    @classmethod
    def from_argyll_type(cls, argyll_type: str) -> 'ProbeInfo':
        """Create ProbeInfo from ArgyllCMS instrument type code."""
        # ArgyllCMS instrument type mapping
        spectrophotometers = {
            "i1pro": ("i1 Pro", True, False),
            "i1pro2": ("i1 Pro 2", True, False),
            "i1pro3": ("i1 Pro 3", True, False),
            "colormunki": ("ColorMunki", True, False),
            "colormunki_smile": ("ColorMunki Smile", True, False),
            "spectrolino": ("Spectrolino", True, False),
            "spectroscan": ("SpectroScan", True, False),
            "specbos": ("JETI specbos", True, False),
            "spectraval": ("JETI spectraval", True, False),
        }

        colorimeters = {
            "i1d3": ("i1 Display Pro", False, True),
            "i1d3revb": ("i1 Display Pro RevB", False, True),
            "i1d2": ("Eye-One Display 2", False, True),
            "dtp94": ("DTP94", False, True),
            "huey": ("Huey", False, True),
            "monaco": ("MonacoOPTIX", False, True),
            "spydx": ("SpyderX", False, True),
            "spydx2": ("SpyderX2", False, True),
            "spyder": ("Spyder", False, True),
            "spyd5": ("Spyder5", False, True),
            "spyd4": ("Spyder4", False, True),
            "spyd3": ("Spyder3", False, True),
            "k10a": ("Klein K10-A", False, True),
            "ex1": ("EX1", False, True),
            "colorhug": ("ColorHug", False, True),
            "hcfr": ("HCFR", False, True),
            "cube": ("Cube", False, True),
        }

        type_lower = argyll_type.lower().replace("-", "").replace("_", "")

        if type_lower in spectrophotometers:
            name, is_spec, is_col = spectrophotometers[type_lower]
            return cls(name=name, argyll_type=argyll_type,
                       is_spectrophotometer=is_spec, is_colorimeter=is_col)

        if type_lower in colorimeters:
            name, is_spec, is_col = colorimeters[type_lower]
            return cls(name=name, argyll_type=argyll_type,
                       is_spectrophotometer=is_spec, is_colorimeter=is_col)

        # Unknown probe
        return cls(name=argyll_type, argyll_type=argyll_type,
                   is_spectrophotometer=False, is_colorimeter=False)


@dataclass
class CorrectionMetadata:
    """
    Metadata extracted from a correction file (CCSS/CCMX).

    Attributes:
        file_path: Absolute path to the correction file
        file_hash: SHA-256 hash of file content (for measurement association)
        correction_type: CCSS or CCMX
        descriptor: Human-readable description
        instrument: Target instrument/probe type (for CCMX)
        technology: Target display technology code
        reference_instrument: Reference spectrophotometer (for CCMX)
        created: Creation timestamp
        display_type_base_id: Display type base ID (ArgyllCMS)
        display_type_refresh: Whether display has refresh technology
        color_rep: Color representation (XYZ, RGB, etc.)
        originator: Tool that created this file
        matrix: 3x3 correction matrix (for CCMX)
        spectral_data: Spectral data (for CCSS)
        is_valid: Whether file was parsed successfully
        parse_errors: List of errors encountered during parsing
    """
    file_path: str = ""
    file_hash: str = ""
    correction_type: CorrectionType = CorrectionType.CCMX
    descriptor: str = ""
    instrument: str = ""
    technology: str = ""
    reference_instrument: str = ""
    created: Optional[datetime] = None
    display_type_base_id: str = ""
    display_type_refresh: str = ""
    color_rep: str = "XYZ"
    originator: str = ""
    matrix: Optional[List[List[float]]] = None
    spectral_data: Optional[Dict[str, Any]] = None
    is_valid: bool = True
    parse_errors: List[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        """Get filename without path."""
        return os.path.basename(self.file_path)

    @property
    def display_technology(self) -> Optional[DisplayTechnology]:
        """Get DisplayTechnology enum from technology code."""
        if self.technology:
            return DisplayTechnology.from_argyll_code(self.technology)
        return None

    @property
    def target_probe(self) -> ProbeInfo:
        """Get ProbeInfo for target instrument."""
        return ProbeInfo.from_argyll_type(self.instrument)

    @property
    def reference_probe(self) -> ProbeInfo:
        """Get ProbeInfo for reference instrument."""
        return ProbeInfo.from_argyll_type(self.reference_instrument)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "file_path": self.file_path,
            "filename": self.filename,
            "file_hash": self.file_hash,
            "correction_type": self.correction_type.value,
            "descriptor": self.descriptor,
            "instrument": self.instrument,
            "technology": self.technology,
            "technology_display": self.display_technology.get_display_name() if self.display_technology else self.technology,
            "reference_instrument": self.reference_instrument,
            "created": self.created.isoformat() if self.created else None,
            "created_display": self.created.strftime("%Y-%m-%d %H:%M:%S") if self.created else None,
            "originator": self.originator,
            "is_valid": self.is_valid,
            "parse_errors": self.parse_errors,
        }


@dataclass
class CompatibilityResult:
    """Result of correction file compatibility check.

    Attributes:
        is_compatible: Whether correction can be used
        warnings: Non-blocking warnings
        errors: Blocking errors
        suggestions: Suggestions for user
    """
    is_compatible: bool = True
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "is_compatible": self.is_compatible,
            "warnings": self.warnings,
            "errors": self.errors,
            "suggestions": self.suggestions,
        }


class CorrectionFileParser:
    """Parser for CCSS and CCMX correction files.

    CCSS files contain spectral correction data from spectrophotometer.
    CCMX files contain matrix correction requiring spectrophotometer reference.

    Both formats use CGATS-style text format similar to TI3 files.
    """

    # Regex patterns for CGATS-style metadata
    DESCRIPTOR_PATTERN = re.compile(r'DESCRIPTOR\s+"([^"]+)"')
    INSTRUMENT_PATTERN = re.compile(r'INSTRUMENT\s+"([^"]+)"')
    TECHNOLOGY_PATTERN = re.compile(r'TECHNOLOGY\s+"([^"]+)"')
    REFERENCE_PATTERN = re.compile(r'REFERENCE\s+"([^"]+)"')
    CREATED_PATTERN = re.compile(r'CREATED\s+"([^"]+)"')
    ORIGINATOR_PATTERN = re.compile(r'ORIGINATOR\s+"([^"]+)"')
    COLOR_REP_PATTERN = re.compile(r'COLOR_REP\s+"([^"]+)"')
    DISPLAY_TYPE_BASE_PATTERN = re.compile(r'DISPLAY_TYPE_BASE_ID\s+"([^"]+)"')
    DISPLAY_TYPE_REFRESH_PATTERN = re.compile(r'DISPLAY_TYPE_REFRESH\s+"([^"]+)"')

    def parse_file(self, file_path: str) -> CorrectionMetadata:
        """
        Parse a correction file and extract metadata.

        Args:
            file_path: Absolute path to CCSS or CCMX file

        Returns:
            CorrectionMetadata with extracted information
        """
        metadata = CorrectionMetadata(file_path=file_path)
        errors = []

        # Calculate file hash
        try:
            metadata.file_hash = self._calculate_hash(file_path)
        except Exception as e:
            errors.append(f"无法计算文件哈希: {str(e)}")

        # Determine file type
        ext = Path(file_path).suffix.lower()
        if ext == ".ccss":
            metadata.correction_type = CorrectionType.CCSS
        elif ext == ".ccmx":
            metadata.correction_type = CorrectionType.CCMX
        else:
            errors.append(f"未知文件类型: {ext}")
            metadata.is_valid = False
            metadata.parse_errors = errors
            return metadata

        # Read file content
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            errors.append(f"无法读取文件: {str(e)}")
            metadata.is_valid = False
            metadata.parse_errors = errors
            return metadata

        # Parse metadata fields
        metadata.descriptor = self._extract_field(content, self.DESCRIPTOR_PATTERN, "")
        metadata.instrument = self._extract_field(content, self.INSTRUMENT_PATTERN, "")
        metadata.technology = self._extract_field(content, self.TECHNOLOGY_PATTERN, "")
        metadata.reference_instrument = self._extract_field(content, self.REFERENCE_PATTERN, "")
        metadata.originator = self._extract_field(content, self.ORIGINATOR_PATTERN, "")
        metadata.color_rep = self._extract_field(content, self.COLOR_REP_PATTERN, "XYZ")
        metadata.display_type_base_id = self._extract_field(content, self.DISPLAY_TYPE_BASE_PATTERN, "")
        metadata.display_type_refresh = self._extract_field(content, self.DISPLAY_TYPE_REFRESH_PATTERN, "")

        # Parse created timestamp
        created_str = self._extract_field(content, self.CREATED_PATTERN, "")
        if created_str:
            metadata.created = self._parse_created_timestamp(created_str)
            if not metadata.created:
                errors.append(f"无法解析创建时间: {created_str}")

        # Parse matrix data for CCMX
        if metadata.correction_type == CorrectionType.CCMX:
            matrix = self._parse_matrix(content)
            if matrix:
                metadata.matrix = matrix
            else:
                errors.append("无法解析校正矩阵数据")

        # Validate essential fields
        if metadata.correction_type == CorrectionType.CCMX:
            if not metadata.instrument:
                errors.append("CCMX 缺少目标探头类型 (INSTRUMENT)")
            if not metadata.reference_instrument:
                errors.append("CCMX 缺少基准探头类型 (REFERENCE)")

        if errors:
            metadata.is_valid = False
            metadata.parse_errors = errors

        return metadata

    def _calculate_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of file content."""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _extract_field(self, content: str, pattern: re.Pattern, default: str) -> str:
        """Extract field value using regex pattern."""
        match = pattern.search(content)
        if match:
            return match.group(1)
        return default

    def _parse_created_timestamp(self, created_str: str) -> Optional[datetime]:
        """Parse ArgyllCMS-created timestamp string.

        Format: "Sun Apr  5 07:45:00 2026" or similar.
        """
        # Common ArgyllCMS timestamp formats
        formats = [
            "%a %b %d %H:%M:%S %Y",  # "Sun Apr  5 07:45:00 2026"
            "%a %b  %d %H:%M:%S %Y",  # "Sun Apr  5 07:45:00 2026" (with extra space)
            "%Y-%m-%d %H:%M:%S",     # ISO format fallback
            "%Y%m%d_%H%M%S",         # Compact format
        ]

        # Normalize string (handle double spaces)
        normalized = created_str.strip()
        normalized = re.sub(r'\s+', ' ', normalized)

        for fmt in formats:
            try:
                return datetime.strptime(normalized, fmt)
            except ValueError:
                continue

        # Try to extract year and construct approximate date
        year_match = re.search(r'\d{4}', created_str)
        if year_match:
            try:
                year = int(year_match.group())
                # Use filename timestamp if available
                filename_ts = re.search(r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})',
                                        created_str)
                if filename_ts:
                    return datetime(
                        int(filename_ts.group(1)),
                        int(filename_ts.group(2)),
                        int(filename_ts.group(3)),
                        int(filename_ts.group(4)),
                        int(filename_ts.group(5)),
                        int(filename_ts.group(6))
                    )
                return datetime(year, 1, 1)
            except Exception:
                pass

        return None

    def _parse_matrix(self, content: str) -> Optional[List[List[float]]]:
        """Parse 3x3 correction matrix from CCMX file."""
        # Find the actual BEGIN_DATA block (not BEGIN_DATA_FORMAT)
        # Use newline + BEGIN_DATA to avoid matching BEGIN_DATA_FORMAT
        import re

        # Find BEGIN_DATA that is on its own line (followed by newline or preceded by newline)
        begin_match = re.search(r'\nBEGIN_DATA\s*\n', content)
        if not begin_match:
            # Try alternative: BEGIN_DATA at end of line
            begin_match = re.search(r'BEGIN_DATA\n', content)

        if not begin_match:
            return None

        data_start = begin_match.end()

        # Find END_DATA that is on its own line (preceded by newline)
        # Must find END_DATA after BEGIN_DATA position
        end_match = re.search(r'\nEND_DATA', content[data_start:])
        if not end_match:
            return None

        data_end = data_start + end_match.start()

        # Extract content between markers
        data_block = content[data_start:data_end]

        # Extract numeric lines
        lines = []
        for line in data_block.split('\n'):
            line = line.strip()
            # Skip empty lines and headers
            if not line:
                continue
            # Try to parse as numbers
            parts = line.split()
            if len(parts) >= 3:
                try:
                    # Check if all parts are numeric
                    row = [float(p) for p in parts[:3]]
                    lines.append(row)
                except ValueError:
                    # Skip non-numeric lines
                    continue

        # Expect exactly 3 rows for 3x3 matrix
        # Also accept if we got more rows (some CCMX files may have extra data)
        if len(lines) >= 3:
            return lines[:3]

        return None


class CorrectionManager:
    """
    Manager for correction files (CCSS/CCMX).

    Provides:
    - Loading and scanning correction file directory
    - Compatibility checking between correction and probe/display
    - Hash tracking for measurement association
    - CCMX creation wizard support

    Usage:
        manager = CorrectionManager("/path/to/corrections")
        files = manager.scan_correction_files()
        compat = manager.check_compatibility(metadata, probe_type, display_tech)
    """

    # Probe type compatibility mapping
    # Key: probe argyll type, Value: list of compatible probe types for correction
    COLORIMETER_PROBES = [
        "i1d3", "i1d3revb", "i1d2", "dtp94", "huey", "monaco",
        "spydx", "spydx2", "spyder", "spyd5", "spyd4", "spyd3",
        "k10a", "ex1", "colorhug", "hcfr", "cube"
    ]

    SPECTROPHOTOMETER_PROBES = [
        "i1pro", "i1pro2", "i1pro3", "colormunki", "colormunki_smile",
        "spectrolino", "spectroscan", "specbos", "spectraval"
    ]

    def __init__(self, corrections_dir: str):
        """
        Initialize correction manager.

        Args:
            corrections_dir: Path to directory containing CCSS/CCMX files
        """
        self._corrections_dir = corrections_dir
        self._parser = CorrectionFileParser()
        self._corrections: Dict[str, CorrectionMetadata] = {}  # path -> metadata
        self._hash_index: Dict[str, str] = {}  # hash -> path

    def scan_correction_files(self) -> List[CorrectionMetadata]:
        """
        Scan corrections directory and parse all CCSS/CCMX files.

        Returns:
            List of CorrectionMetadata for all found files
        """
        corrections = []

        if not os.path.exists(self._corrections_dir):
            return corrections

        for filename in os.listdir(self._corrections_dir):
            if filename.lower().endswith('.ccss') or filename.lower().endswith('.ccmx'):
                file_path = os.path.join(self._corrections_dir, filename)
                try:
                    metadata = self._parser.parse_file(file_path)
                    corrections.append(metadata)
                    self._corrections[file_path] = metadata
                    self._hash_index[metadata.file_hash] = file_path
                except Exception as e:
                    # Create invalid metadata for failed parse
                    metadata = CorrectionMetadata(
                        file_path=file_path,
                        is_valid=False,
                        parse_errors=[str(e)]
                    )
                    corrections.append(metadata)

        # Sort by filename
        corrections.sort(key=lambda m: m.filename)
        return corrections

    def get_correction_by_path(self, file_path: str) -> Optional[CorrectionMetadata]:
        """Get correction metadata by file path."""
        if file_path in self._corrections:
            return self._corrections[file_path]

        # Parse if not cached
        if os.path.exists(file_path):
            metadata = self._parser.parse_file(file_path)
            self._corrections[file_path] = metadata
            self._hash_index[metadata.file_hash] = file_path
            return metadata

        return None

    def get_correction_by_hash(self, file_hash: str) -> Optional[CorrectionMetadata]:
        """Get correction metadata by file hash."""
        if file_hash in self._hash_index:
            file_path = self._hash_index[file_hash]
            return self._corrections.get(file_path)
        return None

    def check_compatibility(
        self,
        correction: CorrectionMetadata,
        probe_type: str,
        display_technology: Optional[Union[str, DisplayTechnology]] = None
    ) -> CompatibilityResult:
        """
        Check if a correction file is compatible with probe and display.

        Args:
            correction: CorrectionMetadata to check
            probe_type: ArgyllCMS probe type (e.g., "i1d3", "i1pro2")
            display_technology: Display technology (code, enum, or name)

        Returns:
            CompatibilityResult with compatibility status and messages
        """
        result = CompatibilityResult()

        # Check if correction file is valid
        if not correction.is_valid:
            result.is_compatible = False
            result.errors.append("修正文件无效或解析失败")
            result.suggestions.append("请检查修正文件格式是否正确")
            return result

        # Normalize probe type
        probe_type_lower = probe_type.lower().replace("-", "").replace("_", "")

        # Check instrument compatibility
        if correction.instrument:
            correction_probe = correction.instrument.lower().replace("-", "").replace("_", "")

            if correction_probe != probe_type_lower:
                # Check if probes are related (same family)
                if not self._are_probes_related(correction_probe, probe_type_lower):
                    result.is_compatible = False
                    result.errors.append(
                        f"修正文件为 {correction.instrument} 创建，"
                        f"当前探头为 {probe_type}，不兼容"
                    )
                    result.suggestions.append(
                        f"请使用为 {probe_type} 创建的修正文件，"
                        f"或使用分光仪制作新的修正文件"
                    )

        # Check display technology compatibility
        if display_technology and correction.technology:
            # Normalize display technology
            if isinstance(display_technology, DisplayTechnology):
                tech_code = display_technology.value
            elif isinstance(display_technology, str):
                # Try to convert string to technology
                tech_enum = DisplayTechnology.from_argyll_code(display_technology)
                if tech_enum:
                    tech_code = tech_enum.value
                else:
                    tech_enum = DisplayTechnology.from_display_name(display_technology)
                    if tech_enum:
                        tech_code = tech_enum.value
                    else:
                        tech_code = display_technology.lower()
            else:
                tech_code = ""

            correction_tech = correction.technology.lower()

            if tech_code and correction_tech:
                if not self._are_technologies_compatible(tech_code, correction_tech):
                    # This is a warning, not an error - user can override
                    result.warnings.append(
                        f"修正文件针对 {correction.display_technology.get_display_name() if correction.display_technology else correction_tech} 创建，"
                        f"当前显示器可能不匹配"
                    )
                    result.suggestions.append(
                        "使用不匹配的修正文件可能影响测量精度"
                    )

        # Check correction type vs probe type
        if correction.correction_type == CorrectionType.CCMX:
            # CCMX requires colorimeter as target
            if probe_type_lower in self.SPECTROPHOTOMETER_PROBES:
                result.warnings.append(
                    "分光仪不需要 CCMX 修正文件（分光仪本身即为基准）"
                )
                result.suggestions.append(
                    "分光仪测量结果可直接用于创建 CCMX，不需要应用修正"
                )

        elif correction.correction_type == CorrectionType.CCSS:
            # CCSS can be used with colorimeters
            if probe_type_lower in self.SPECTROPHOTOMETER_PROBES:
                result.warnings.append(
                    "分光仪不需要 CCSS 修正文件"
                )

        return result

    def _are_probes_related(self, probe1: str, probe2: str) -> bool:
        """Check if two probes are from the same family/compatible."""
        # Probe family mapping
        families = {
            "i1d": ["i1d3", "i1d3revb", "i1d2", "i1display", "i1displaypro"],
            "i1pro": ["i1pro", "i1pro2", "i1pro3"],
            "colormunki": ["colormunki", "colormunkismile"],
            "spyder": ["spyder", "spydx", "spydx2", "spyd1", "spyd2", "spyd3", "spyd4", "spyd5"],
        }

        for family, members in families.items():
            if probe1 in members and probe2 in members:
                return True

        return False

    def _are_technologies_compatible(self, tech1: str, tech2: str) -> bool:
        """Check if two display technologies are compatible.

        Generic types (like 'l' for LCD) are compatible with specific types.
        """
        # Exact match
        if tech1 == tech2:
            return True

        # Generic LCD 'l' is compatible with all LCD variants
        # Note: 'c' is CRT in ArgyllCMS, NOT LCD. 'a' is AMOLED.
        # LCD variants: 'l', 'e', 'b', 'h', 'r', 'i' + their sub-variants
        # Also include numbered variants: '1'-'9' and lettered sub-variants
        lcd_variants = ['l', 'L', '1', '2', '3', '4', '5', '6', '7', '8', '9',
                        'e', 'b', 'h', 'r', 'i', 'f', 'g', 's', 't', 'v', 'x', 'y', 'z']

        if tech1 == 'l' and tech2 in lcd_variants:
            return True
        if tech2 == 'l' and tech1 in lcd_variants:
            return True

        # OLED generic 'o' compatible with AMOLED/WOLED
        # Note: 'a' is AMOLED, but also used for LCD White LED TFT in some contexts
        # We keep OLED variants separate from LCD
        oled_variants = ['o', 'w']  # OLED and WOLED only
        if tech1 == 'o' and tech2 in oled_variants:
            return True
        if tech2 == 'o' and tech1 in oled_variants:
            return True

        return False

    def get_correction_files_json(self) -> str:
        """Get correction files list as JSON string.

        Returns format compatible with backend.get_correction_files().
        """
        corrections = self.scan_correction_files()
        files = []

        for meta in corrections:
            files.append({
                "name": meta.filename,
                "path": meta.file_path,
                "type": meta.correction_type.value,
                "descriptor": meta.descriptor,
                "instrument": meta.instrument,
                "technology": meta.technology,
                "technology_display": meta.display_technology.get_display_name() if meta.display_technology else "",
                "created": meta.created.strftime("%Y-%m-%d") if meta.created else "",
                "reference": meta.reference_instrument,
                "is_valid": meta.is_valid,
                "hash": meta.file_hash[:16] if meta.file_hash else "",  # Short hash for display
            })

        return json.dumps(files)

    def get_detailed_metadata_json(self, file_path: str) -> str:
        """Get detailed metadata for a single correction file as JSON."""
        metadata = self.get_correction_by_path(file_path)
        if metadata:
            return json.dumps(metadata.to_dict(), indent=2)
        return json.dumps({"error": "File not found or invalid"})


class CCMXCreationWizard:
    """
    Wizard for creating CCMX correction files.

    Workflow:
    1. Reference probe (spectrophotometer) measurements
    2. Target probe (colorimeter) measurements
    3. Generate CCMX using ccxxmake
    4. Validate and verify

    This class provides state management and validation for the wizard.
    """

    class WizardState(Enum):
        """Wizard state."""
        IDLE = "idle"
        REFERENCE_MEASURING = "reference_measuring"
        REFERENCE_COMPLETE = "reference_complete"
        TARGET_MEASURING = "target_measuring"
        TARGET_COMPLETE = "target_complete"
        GENERATING = "generating"
        VALIDATING = "validating"
        COMPLETE = "complete"
        FAILED = "failed"

    @dataclass
    class WizardConfig:
        """Configuration for CCMX creation."""
        reference_probe_type: str = ""
        target_probe_type: str = ""
        display_technology: str = "l"  # Default to LCD generic
        display_name: str = ""
        output_filename: str = ""

    def __init__(self):
        """Initialize wizard."""
        self._state = self.WizardState.IDLE
        self._config = self.WizardConfig()
        self._reference_measurements: Dict[str, Any] = {}
        self._target_measurements: Dict[str, Any] = {}

    @property
    def state(self) -> WizardState:
        """Get current wizard state."""
        return self._state

    @property
    def config(self) -> WizardConfig:
        """Get wizard configuration."""
        return self._config

    def start_wizard(
        self,
        reference_probe: str,
        target_probe: str,
        display_technology: str = "l",
        display_name: str = ""
    ) -> bool:
        """
        Start CCMX creation wizard.

        Args:
            reference_probe: Spectrophotometer type (e.g., "i1pro2")
            target_probe: Colorimeter type (e.g., "i1d3")
            display_technology: Display technology code
            display_name: Human-readable display name

        Returns:
            True if wizard started successfully
        """
        # Validate probes
        ref_info = ProbeInfo.from_argyll_type(reference_probe)
        target_info = ProbeInfo.from_argyll_type(target_probe)

        if not ref_info.is_spectrophotometer:
            return False  # Reference must be spectrophotometer

        if not target_info.is_colorimeter:
            return False  # Target must be colorimeter

        self._config.reference_probe_type = reference_probe
        self._config.target_probe_type = target_probe
        self._config.display_technology = display_technology
        self._config.display_name = display_name

        self._state = self.WizardState.IDLE
        self._reference_measurements = {}
        self._target_measurements = {}

        return True

    def set_reference_measurements(self, measurements: Dict[str, Any]) -> bool:
        """
        Set reference probe measurements.

        Args:
            measurements: Dict with color patch measurements
                        {"white": {...}, "red": {...}, "green": {...}, "blue": {...}}

        Returns:
            True if measurements are valid
        """
        required_colors = ["white", "red", "green", "blue"]

        for color in required_colors:
            if color not in measurements:
                return False
            if "xyY" not in measurements[color]:
                return False

        self._reference_measurements = measurements
        self._state = self.WizardState.REFERENCE_COMPLETE
        return True

    def set_target_measurements(self, measurements: Dict[str, Any]) -> bool:
        """
        Set target probe measurements.

        Args:
            measurements: Dict with color patch measurements

        Returns:
            True if measurements are valid
        """
        required_colors = ["white", "red", "green", "blue"]

        for color in required_colors:
            if color not in measurements:
                return False
            if "xyY" not in measurements[color]:
                return False

        self._target_measurements = measurements
        self._state = self.WizardState.TARGET_COMPLETE
        return True

    def can_generate_ccmx(self) -> bool:
        """Check if wizard can generate CCMX."""
        return (
            self._state == self.WizardState.TARGET_COMPLETE and
            self._reference_measurements and
            self._target_measurements
        )

    def get_ccmx_creation_params(self) -> Dict[str, Any]:
        """Get parameters for CCMX creation."""
        if not self.can_generate_ccmx():
            return {}

        # Generate output filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if self._config.output_filename:
            filename = self._config.output_filename
        else:
            filename = f"{self._config.target_probe_type}_matrix_{timestamp}.ccmx"

        return {
            "reference_probe": self._config.reference_probe_type,
            "target_probe": self._config.target_probe_type,
            "display_technology": self._config.display_technology,
            "display_name": self._config.display_name,
            "output_filename": filename,
            "reference_measurements": self._reference_measurements,
            "target_measurements": self._target_measurements,
        }

    def reset(self) -> None:
        """Reset wizard to initial state."""
        self._state = self.WizardState.IDLE
        self._config = self.WizardConfig()
        self._reference_measurements = {}
        self._target_measurements = {}


# Convenience function for backend integration
def create_correction_manager(corrections_dir: str) -> CorrectionManager:
    """Create a CorrectionManager instance."""
    return CorrectionManager(corrections_dir)


def parse_correction_file(file_path: str) -> CorrectionMetadata:
    """Parse a single correction file."""
    parser = CorrectionFileParser()
    return parser.parse_file(file_path)
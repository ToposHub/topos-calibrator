"""
Instruments module - Measurement instrument adapters and interfaces.

This module provides:
- InstrumentAdapter: Abstract interface for measurement instruments
- PatchPresenter: Abstract interface for displaying color patches
- Fake implementations for testing without hardware
- ArgyllAdapter: Real ArgyllCMS hardware adapter
- PyQtPatchPresenter: PyQt patch window adapter
- ArgyllParams: Parameter dataclasses for ArgyllCMS commands
- OutputParser: Parser for ArgyllCMS tool output
- CorrectionManager: CCSS/CCMX correction file management

Design principles:
- All instrument interactions go through InstrumentAdapter interface
- All patch display goes through PatchPresenter interface
- All correction file management through CorrectionManager
- Implementations can be swapped for testing or different hardware
- Command parameters use dataclasses for type safety

Reference: docs/agent_handoffs/P0-A_architecture_audit.md
Reference: docs/agent_handoffs/P3-D_corrections_management.md
"""

from .base import (
    InstrumentAdapter,
    InstrumentStatus,
    InstrumentError,
    InstrumentState,
    MeasurementResult,
    PatchPresenter,
    PatchDisplayError,
    FakeInstrument,
    FakePatchPresenter,
)

# Parameter dataclasses (no heavy dependencies)
from .argyll_params import (
    SpotreadParams,
    DispcalParams,
    TargenParams,
    ColprofParams,
    CollinkParams,
    DisplayType,
    ProbeType,
    QualityLevel,
    RenderingIntent,
    SourceSpace,
    ArgyllErrorMapping,
    map_error_to_suggestion,
    DEFAULT_ERROR_MAPPINGS,
)

# Output parser (no heavy dependencies)
from .argyll_adapter import (
    OutputParser,
    OutputPatterns,
    ParseResult,
    ProcessLifecycle,
)

# Correction file management (P3-D)
from .corrections import (
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

# Real adapters (may import heavy dependencies)
# Lazy import to avoid PyQt dependency in tests
def get_argyll_adapter():
    """Lazy import ArgyllAdapter (requires ArgyllController)."""
    from .argyll_adapter import ArgyllAdapter, create_argyll_adapter
    return ArgyllAdapter, create_argyll_adapter

def get_qt_patch_presenter():
    """Lazy import PyQtPatchPresenter (requires PyQt6)."""
    from .qt_patch_presenter import PyQtPatchPresenter, WebUIPatchPresenter
    return PyQtPatchPresenter, WebUIPatchPresenter

__all__ = [
    # Base interfaces
    "InstrumentAdapter",
    "InstrumentStatus",
    "InstrumentError",
    "InstrumentState",
    "MeasurementResult",
    "PatchPresenter",
    "PatchDisplayError",
    "FakeInstrument",
    "FakePatchPresenter",
    # Parameter dataclasses
    "SpotreadParams",
    "DispcalParams",
    "TargenParams",
    "ColprofParams",
    "CollinkParams",
    "DisplayType",
    "ProbeType",
    "QualityLevel",
    "RenderingIntent",
    "SourceSpace",
    "ArgyllErrorMapping",
    "map_error_to_suggestion",
    "DEFAULT_ERROR_MAPPINGS",
    # Output parser
    "OutputParser",
    "OutputPatterns",
    "ParseResult",
    "ProcessLifecycle",
    # Correction file management (P3-D)
    "CorrectionType",
    "CorrectionMetadata",
    "CorrectionFileParser",
    "CorrectionManager",
    "CCMXCreationWizard",
    "DisplayTechnology",
    "ProbeInfo",
    "CompatibilityResult",
    "create_correction_manager",
    "parse_correction_file",
    # Lazy imports
    "get_argyll_adapter",
    "get_qt_patch_presenter",
    # Display Control (P5-A)
    "ControlType",
    "ControlCategory",
    "DisplayCapability",
    "DisplayCapabilities",
    "ControlSnapshot",
    "AdjustmentResult",
    "AdjustmentBatch",
    "DisplayControlError",
    "DisplayControlAdapter",
    "FakeDisplayControlAdapter",
    "DDCCIAdapter",
    "ManualAdjustmentStep",
    "ManualAdjustmentGuide",
    "ManualAdjustmentGuideGenerator",
    "create_fake_display_adapter",
    "create_display_adapter",
]

# Display Control imports (P5-A)
from .display_control import (
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
    create_display_adapter,
)
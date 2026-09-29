"""
Workflows module - Measurement and calibration workflow services.

This module provides:
- MeasurementService: Core service for orchestrating color measurements
- ICCWorkflow: ICC profile generation workflow (P4-B)
- ValidationWorkflow: Calibration validation workflow (P4-D)
- SettlingPolicy: Display stabilization strategy for accurate measurements
- BackendMeasurementBridge: Integration between Backend and MeasurementService
- Integration with state machine (src/core/state.py)
- Support for dark sample multi-sampling
- Support for OLED black frame logic
- Support for checkpoint/resume

Design principles:
- Pure business logic, no UI dependencies
- All UI interactions delegated to PatchPresenter interface
- All instrument interactions delegated to InstrumentAdapter interface
- State machine drives workflow lifecycle
- Bridge layer handles Backend-to-Service integration

Reference:
- docs/agent_handoffs/P1-C_backend_refactor.md
- docs/agent_handoffs/P4-B_icc_workflow.md
- docs/agent_handoffs/P4-D_validation_workflow.md
"""

from .measurement_service import (
    MeasurementService,
    MeasurementServiceError,
    MeasurementConfig,
    MeasurementSession,
    CheckpointData,
    DarkSampleConfig,
    OLEDConfig,
)

from .settling import (
    DisplayTechnology,
    ProbeType,
    SettlingDecision,
    PatchContext,
    SettlingPolicy,
    LCDSettlingPolicy,
    OLEDSettlingPolicy,
    WOLEDSettlingPolicy,
    MiniLEDSettlingPolicy,
    ProjectorSettlingPolicy,
    CRTSettlingPolicy,
    UnknownSettlingPolicy,
    SettlingPolicyFactory,
    evaluate_settling,
)

# Backend bridge (lazy import to avoid circular dependency)
def get_backend_measurement_bridge():
    """Lazy import BackendMeasurementBridge (requires Backend)."""
    from .backend_measurement_bridge import BackendMeasurementBridge, BridgeConfig, create_bridge
    return BackendMeasurementBridge, BridgeConfig, create_bridge

# Preflight module (lazy import for optional dependencies)
def get_preflight():
    """Lazy import preflight module."""
    from .preflight import (
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
        get_permission_status_summary,
        run_permission_checks_only,
        export_permission_status_report,
    )
    return (
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
        get_permission_status_summary,
        run_permission_checks_only,
        export_permission_status_report,
    )


# PreflightService facade for Backend integration
from .preflight_service import PreflightService


# ICC Workflow module (P4-B)
def get_icc_workflow():
    """Lazy import ICC workflow module."""
    from .icc_workflow import (
        ICCWorkflowState,
        ProfilePreset,
        ProfilePresetConfig,
        ICCWorkflowConfig,
        ICCWorkflowSession,
        ICCWorkflowCheckpoint,
        ICCWorkflowError,
        ICCWorkflow,
        get_available_presets,
        list_recoverable_sessions,
        PROFILE_PRESETS,
    )
    return (
        ICCWorkflowState,
        ProfilePreset,
        ProfilePresetConfig,
        ICCWorkflowConfig,
        ICCWorkflowSession,
        ICCWorkflowCheckpoint,
        ICCWorkflowError,
        ICCWorkflow,
        get_available_presets,
        list_recoverable_sessions,
        PROFILE_PRESETS,
    )


# Direct imports for common usage
from .icc_workflow import (
    ICCWorkflowState,
    ProfilePreset,
    ICCWorkflowConfig,
    ICCWorkflowSession,
    ICCWorkflowCheckpoint,
    ICCWorkflowError,
    ICCWorkflow,
    get_available_presets,
    list_recoverable_sessions,
)

# Validation Workflow module (P4-D)
from .validation_workflow import (
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
    # 统一验收层新增
    WorkflowType,
    SamplePoint,
    GrayscalePoint,
    GamutPoint,
    ValidationInput,
    GrayscaleTrackingPoint,
    PassFailResult,
    ValidationOutput,
    validate_from_input,
)

# Validation workflow lazy import
def get_validation_workflow():
    """Lazy import validation workflow module."""
    return (
        MeasurementType,
        ValidationStatus,
        ValidationThreshold,
        ValidationRun,
        ValidationSession,
        ValidationWorkflowService,
        BeforeAfterComparison,
    )


# LUT Workflow module (P4-C)
def get_lut_workflow():
    """Lazy import LUT workflow module."""
    from .lut_workflow import (
        LUTType,
        GridSize,
        InterpolationMethod,
        TargetSpace,
        LUTFormat,
        LUTSpec,
        LUTWorkflowConfig,
        LUTWorkflowState,
        LUTWorkflowSession,
        LUTGenerationReport,
        LUTValidationResult,
        DensityCheckResult,
        check_measurement_density,
        LUTWorkflow,
        SourceSpacePreset,
        SourceSpaceDefinition,
        SOURCE_SPACE_DEFINITIONS,
        get_source_space_list,
        get_source_space_by_name,
        validate_intent_bpc_combination,
        GRID_SIZE_CATEGORY,
        MIN_MEASUREMENT_DENSITY,
    )
    return (
        LUTType,
        GridSize,
        InterpolationMethod,
        TargetSpace,
        LUTFormat,
        LUTSpec,
        LUTWorkflowConfig,
        LUTWorkflowState,
        LUTWorkflowSession,
        LUTGenerationReport,
        LUTValidationResult,
        DensityCheckResult,
        check_measurement_density,
        LUTWorkflow,
        SourceSpacePreset,
        SourceSpaceDefinition,
        SOURCE_SPACE_DEFINITIONS,
        get_source_space_list,
        get_source_space_by_name,
        validate_intent_bpc_combination,
        GRID_SIZE_CATEGORY,
        MIN_MEASUREMENT_DENSITY,
    )


# Direct imports for LUT workflow common usage
from .lut_workflow import (
    LUTType,
    GridSize,
    InterpolationMethod,
    TargetSpace,
    LUTFormat,
    LUTSpec,
    LUTWorkflowConfig,
    LUTWorkflowState,
    LUTWorkflowSession,
    LUTGenerationReport,
    LUTValidationResult,
    DensityCheckResult,
    check_measurement_density,
    LUTWorkflow,
    SourceSpacePreset,
    get_source_space_list,
    get_source_space_by_name,
    validate_intent_bpc_combination,
)


__all__ = [
    # MeasurementService
    "MeasurementService",
    "MeasurementServiceError",
    "MeasurementConfig",
    "MeasurementSession",
    "CheckpointData",
    "DarkSampleConfig",
    "OLEDConfig",
    # SettlingPolicy
    "DisplayTechnology",
    "ProbeType",
    "SettlingDecision",
    "PatchContext",
    "SettlingPolicy",
    "LCDSettlingPolicy",
    "OLEDSettlingPolicy",
    "WOLEDSettlingPolicy",
    "MiniLEDSettlingPolicy",
    "ProjectorSettlingPolicy",
    "CRTSettlingPolicy",
    "UnknownSettlingPolicy",
    "SettlingPolicyFactory",
    "evaluate_settling",
    # Backend bridge
    "get_backend_measurement_bridge",
    # Preflight
    "get_preflight",
    # PreflightService facade
    "PreflightService",
    # ICC Workflow (P4-B)
    "ICCWorkflowState",
    "ProfilePreset",
    "ProfilePresetConfig",
    "ICCWorkflowConfig",
    "ICCWorkflowSession",
    "ICCWorkflowCheckpoint",
    "ICCWorkflowError",
    "ICCWorkflow",
    "get_available_presets",
    "list_recoverable_sessions",
    "get_icc_workflow",
    # Validation Workflow (P4-D)
    "MeasurementType",
    "ValidationStatus",
    "ValidationThreshold",
    "STANDARD_THRESHOLDS",
    "get_threshold_for_standard",
    "VerificationPatchConfig",
    "VerificationPatchGenerator",
    "MeasurementPoint",
    "ValidationRun",
    "ValidationSession",
    "BeforeAfterComparison",
    "ValidationWorkflowService",
    "calculate_target_xyY_for_rgb",
    "get_validation_workflow",
    # 统一验收层新增
    "WorkflowType",
    "SamplePoint",
    "GrayscalePoint",
    "GamutPoint",
    "ValidationInput",
    "GrayscaleTrackingPoint",
    "PassFailResult",
    "ValidationOutput",
    "validate_from_input",
    # LUT Workflow (P4-C)
    "LUTType",
    "GridSize",
    "InterpolationMethod",
    "TargetSpace",
    "LUTFormat",
    "LUTSpec",
    "LUTWorkflowConfig",
    "LUTWorkflowState",
    "LUTWorkflowSession",
    "LUTGenerationReport",
    "LUTValidationResult",
    "DensityCheckResult",
    "check_measurement_density",
    "LUTWorkflow",
    "SourceSpacePreset",
    "get_source_space_list",
    "get_source_space_by_name",
    "validate_intent_bpc_combination",
    "get_lut_workflow",
    # AutoCal Workflow (P5-A)
    "AutoCalState",
    "AutoCalMode",
    "AdjustmentSolver",
    "AutoCalTarget",
    "MeasurementPoint",
    "BaselineMeasurement",
    "AdjustmentSolution",
    "VerificationResult",
    "IterationRecord",
    "AutoCalSession",
    "AutoCalConfig",
    "AutoCalError",
    "SimpleAdjustmentSolver",
    "AutoCalWorkflow",
    "create_autocal_workflow",
    "run_autocal_dry_run",
]


# AutoCal Workflow module (P5-A)
from .autocal_workflow import (
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
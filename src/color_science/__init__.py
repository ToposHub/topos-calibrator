"""
色彩科学模块 - 专业校色算法与标准数据

本模块提供：
    - spaces: RGB色彩空间、白点、转换矩阵
    - transfer: EOTF/OETF曲线（Gamma/sRGB/BT.1886/PQ/HLG）
    - colorimetry: 色度学计算（Chromatic Adaptation、Delta E、CCT/Duv）
    - gamut_sampling: 色域计算与采样策略
    - statistics: 测量统计分析（重复性评估、XYZ平均、阈值判断）
    - patch_sets: 色块集合生成（灰阶、色域、记忆色等）
    - target_profile: 统一目标Profile定义（所有ICC/LUT/Validation使用）

核心设计原则：
    - 所有workflow必须引用统一TargetProfile，不允许硬编码D65/gamma
    - 每个color space有golden fixture测试
    - 数值转换有容差验证

所有算法均使用标准公式，并有对应的测试向量验证。
"""

from .spaces import (
    # 白点
    WHITE_POINTS,
    ILLUMINANTS,
    get_white_point_xyz,
    get_white_point_xy,

    # 色彩空间
    COLOR_SPACES,
    COLOR_SPACE_ALIASES,
    RGB_TO_XYZ_MATRIX,
    XYZ_TO_RGB_MATRIX,

    # 色彩空间名称标准化
    normalize_color_space_name,

    # 转换函数
    rgb_to_xyz,
    xyz_to_rgb,
    xyz_to_lab,
    lab_to_xyz,
    rgb_to_lab,
    lab_to_rgb,
    xyY_to_xyz,
    xyz_to_xyY,

    # sRGB 特定
    srgb_to_xyz,
    xyz_to_srgb,
    srgb_linearize,
    srgb_gamma_correct,
)

from .transfer import (
    # EOTF（电-光转换函数）
    eotf_gamma,
    eotf_srgb,
    eotf_bt1886,
    eotf_pq,
    eotf_hlg,
    eotf_bt709,
    oetf_bt709,

    # OETF（光-电转换函数）- BT.1886/PQ/HLG 的逆向函数
    oetf_gamma,
    oetf_srgb,
    eotf_bt1886_inverse,
    eotf_pq_inverse,
    eotf_hlg_inverse,

    # 通用接口
    apply_eotf,
    apply_oetf,

    # 曲线名称
    TRANSFER_FUNCTIONS,

    # 误差计算
    calculate_gamma_from_measurements,
    calculate_eotf_errors,

    # 黑场/白场识别
    identify_black_patch,
    identify_white_patch,
    prepare_measurements_for_eotf,
    calculate_bt1886_with_measured_black,
    generate_target_curve_data,
)

from .colorimetry import (
    # Chromatic Adaptation
    BRADFORD_MATRIX,
    CAT02_MATRIX,
    chromatic_adaptation,
    adapt_to_white_point,
    
    # Delta E 计算
    delta_e_cie76,
    delta_e_cie94,
    delta_e_ciede2000,
    delta_e_itp,
    delta_e_itp_components,
    delta_e_itp_from_xyY,
    xyz_to_itp,
    
    # CCT/Duv 计算
    cct_to_xy,
    xy_to_cct_mccamy,
    xy_to_cct_robertson,
    calculate_duv,
    cct_duv_from_xy,
    
    # 辅助函数
    lab_to_lch,
    lch_to_lab,
)

from .gamut_sampling import (
    # 多边形运算
    polygon_area,
    polygon_intersection,
    polygon_intersection_area,
    polygon_vertices_from_rgbw,
    point_in_polygon,

    # 色域计算
    get_gamut_vertices,
    gamut_coverage_percent,
    gamut_area_ratio,
    gamut_metrics,

    # 色块采样
    GamutSampler,
    SamplingStrategy,
    generate_patch_list,
)

from .patch_sets import (
    # 数据类型
    PatchPurpose,
    PatchSetType,
    Patch,
    PatchSet,

    # 预定义生成器
    generate_quick_check_patch_set,
    generate_grayscale_patch_set,
    generate_gamma_ramp_patch_set,
    generate_colorchecker_patch_set,
    generate_memory_colors_patch_set,
    generate_saturation_sweep_patch_set,
    generate_hue_sweep_patch_set,
    generate_lut_cube_patch_set,
    generate_adaptive_patch_set,
    generate_full_calibration_patch_set,

    # 工厂函数
    create_patch_set,
)

from .statistics import (
    # 数据类型
    SingleMeasurement,
    MeasurementStatistics,
    RepeatabilityThreshold,
    RepeatabilityResult,
    PatchRepeatabilityRecord,
    SessionRepeatabilitySummary,
    MeasurementStatus as RepeatabilityStatus,
    AveragingMethod,

    # 统计计算函数
    calculate_mean,
    calculate_std,
    calculate_max_deviation,
    calculate_range,
    calculate_measurement_statistics,
    evaluate_repeatability,
    generate_repeatability_summary,
    create_single_measurement,
    get_luminance_level,
    average_measurements_xyz,
)

from .target_profile import (
    # 统一目标Profile - 所有workflow必须使用
    TargetProfile,
    PRESET_TARGET_PROFILES,
    get_target_profile,
    list_target_profile_names,

    # 类型枚举
    ColorSpaceCategory,
    TransferFunctionType,
    DeltaEMethod,
    WhitePointType,

    # 定义数据类
    TransferFunctionDefinition,
    WhitePointDefinition,
    WHITE_POINT_DEFINITIONS,
    TRANSFER_FUNCTION_DEFINITIONS,

    # 容差验证辅助函数
    assert_color_value_tolerance,
    assert_xyz_tolerance,
    assert_lab_tolerance,
    assert_rgb_tolerance,
    assert_delta_e_tolerance,
    assert_white_point_tolerance,
)

from .lut3d import (
    # 类型枚举
    GamutMappingStrategy,
    SmoothingMethod,

    # 数据类
    LUT3DSpec,
    BlackWhitePoint,
    SyntheticDisplaySpec,

    # LUT3D 核心
    LUT3D,

    # Synthetic Display Model
    SyntheticDisplayModel,

    # Fixture 生成函数
    create_identity_display_fixture,
    create_gamma_deviation_fixture,
    create_gamut_deviation_fixture,
    create_nonlinearity_fixture,

    # 性能测试
    benchmark_lut_performance,
)

__all__ = [
    # spaces
    'WHITE_POINTS', 'ILLUMINANTS', 'get_white_point_xyz', 'get_white_point_xy',
    'COLOR_SPACES', 'COLOR_SPACE_ALIASES', 'RGB_TO_XYZ_MATRIX', 'XYZ_TO_RGB_MATRIX',
    'normalize_color_space_name',
    'rgb_to_xyz', 'xyz_to_rgb', 'xyz_to_lab', 'lab_to_xyz',
    'rgb_to_lab', 'lab_to_rgb', 'xyY_to_xyz', 'xyz_to_xyY',
    'srgb_to_xyz', 'xyz_to_srgb', 'srgb_linearize', 'srgb_gamma_correct',

    # transfer
    'eotf_gamma', 'eotf_srgb', 'eotf_bt1886', 'eotf_pq', 'eotf_hlg', 'eotf_bt709', 'oetf_bt709',
    'oetf_gamma', 'oetf_srgb', 'eotf_bt1886_inverse', 'eotf_pq_inverse', 'eotf_hlg_inverse',
    'apply_eotf', 'apply_oetf', 'TRANSFER_FUNCTIONS',
    'calculate_gamma_from_measurements', 'calculate_eotf_errors',
    'identify_black_patch', 'identify_white_patch', 'prepare_measurements_for_eotf',
    'calculate_bt1886_with_measured_black', 'generate_target_curve_data',

    # colorimetry
    'BRADFORD_MATRIX', 'CAT02_MATRIX',
    'chromatic_adaptation', 'adapt_to_white_point',
    'delta_e_cie76', 'delta_e_cie94', 'delta_e_ciede2000',
    'delta_e_itp', 'delta_e_itp_components', 'delta_e_itp_from_xyY', 'xyz_to_itp',
    'cct_to_xy', 'xy_to_cct_mccamy', 'xy_to_cct_robertson',
    'calculate_duv', 'cct_duv_from_xy',
    'lab_to_lch', 'lch_to_lab',

    # gamut_sampling
    'polygon_area', 'polygon_intersection', 'polygon_intersection_area', 'polygon_vertices_from_rgbw',
    'point_in_polygon',
    'get_gamut_vertices', 'gamut_coverage_percent', 'gamut_area_ratio', 'gamut_metrics',
    'GamutSampler', 'SamplingStrategy', 'generate_patch_list',

    # patch_sets
    'PatchPurpose', 'PatchSetType', 'Patch', 'PatchSet',
    'generate_quick_check_patch_set', 'generate_grayscale_patch_set',
    'generate_gamma_ramp_patch_set', 'generate_colorchecker_patch_set',
    'generate_memory_colors_patch_set', 'generate_saturation_sweep_patch_set',
    'generate_hue_sweep_patch_set', 'generate_lut_cube_patch_set',
    'generate_adaptive_patch_set', 'generate_full_calibration_patch_set',
    'create_patch_set',

    # statistics
    'SingleMeasurement', 'MeasurementStatistics', 'RepeatabilityThreshold',
    'RepeatabilityResult', 'PatchRepeatabilityRecord', 'SessionRepeatabilitySummary',
    'RepeatabilityStatus', 'AveragingMethod',
    'calculate_mean', 'calculate_std', 'calculate_max_deviation', 'calculate_range',
    'calculate_measurement_statistics', 'evaluate_repeatability', 'generate_repeatability_summary',
    'create_single_measurement', 'get_luminance_level', 'average_measurements_xyz',

    # target_profile - 统一目标Profile
    'TargetProfile', 'PRESET_TARGET_PROFILES', 'get_target_profile', 'list_target_profile_names',
    'ColorSpaceCategory', 'TransferFunctionType', 'DeltaEMethod', 'WhitePointType',
    'TransferFunctionDefinition', 'WhitePointDefinition',
    'WHITE_POINT_DEFINITIONS', 'TRANSFER_FUNCTION_DEFINITIONS',
    'assert_color_value_tolerance', 'assert_xyz_tolerance', 'assert_lab_tolerance',
    'assert_rgb_tolerance', 'assert_delta_e_tolerance', 'assert_white_point_tolerance',

    # lut3d - 3D LUT 核心算法
    'GamutMappingStrategy', 'SmoothingMethod',
    'LUT3DSpec', 'BlackWhitePoint', 'SyntheticDisplaySpec',
    'LUT3D', 'SyntheticDisplayModel',
    'create_identity_display_fixture', 'create_gamma_deviation_fixture',
    'create_gamut_deviation_fixture', 'create_nonlinearity_fixture',
    'benchmark_lut_performance',
]
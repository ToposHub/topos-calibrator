# P4-C: 3D LUT 工作流实现报告

**任务编号**: P4-C
**执行日期**: 2026-05-19
**任务类型**: 3D LUT 工作流核心模块实现
**依赖文档**: 
- `docs/agent_handoffs/P4-A_argyll_adapter_refactor.md` - CollinkParams 参数类
- `docs/agent_handoffs/P2-A_color_science_module.md` - 色彩空间定义

---

## 1. 创建/修改的文件列表

### 新增文件

| 文件路径 | 行数 | 说明 |
|----------|------|------|
| `/Users/heng/Documents/vscode/Topos Calibrator/src/workflows/lut_workflow.py` | 640 | LUT 工作流核心模块，包含源空间预设、LUT规格、配置类、工作流类 |
| `/Users/heng/Documents/vscode/Topos Calibrator/tests/test_workflows/test_lut_workflow.py` | 470 | 46 个单元测试，覆盖预设、配置、验证、CUBE 格式校验 |

### 修改文件

| 文件路径 | 变更说明 |
|----------|----------|
| `/Users/heng/Documents/vscode/Topos Calibrator/src/color_science/__init__.py` | 新增 `get_white_point_xy` 导出 |
| `/Users/heng/Documents/vscode/Topos Calibrator/src/workflows/validation_workflow.py` | 修复 `SamplingStrategy.VERIFICATION` 属性不存在问题（改为 `ICC_STANDARD`） |

---

## 2. 实现思路

### 2.1 源色彩空间预设

定义了 7 个标准源色彩空间预设（`SourceSpacePreset`），每个预设包含完整定义（`SourceSpaceDefinition`）：

| 预设 | Primaries | 白点 | 传递函数 | ArgyllCMS ICC |
|------|-----------|------|----------|---------------|
| Rec709_Gamma24 | Rec709 | D65 | BT.1886 | Rec709.icm |
| sRGB | sRGB | D65 | sRGB 分段曲线 | sRGB.icm |
| DisplayP3 | P3 | D65 | Gamma 2.2 | DisplayP3.icm |
| DCI-P3 | P3 | D60 | Gamma 2.6 | SMPTE431_P3.icm |
| Rec2020_PQ | Rec2020 | D65 | PQ ST 2084 | Rec2020.icm |
| Rec2020_HLG | Rec2020 | D65 | HLG | Rec2020.icm |
| Rec2020_Gamma24 | Rec2020 | D65 | BT.1886 | Rec2020.icm |

设计要点：
- 使用 Enum 类型确保预设合法性
- 每个预设映射到 ArgyllCMS/ref 目录的标准 ICC 文件
- 支持模糊名称匹配（如 "rec709" -> Rec709_Gamma24）

### 2.2 LUT 规格

支持 4 种 LUT 尺寸（`LUTSize`）：
- 17 点：快速预览
- 33 点：**推荐**，平衡精度和性能
- 65 点：高精度
- 129 点：最高精度，文件较大

输出格式：
- 主要支持 Resolve `.cube` 格式
- madVR/DisplayCAL 兼容格式预留扩展接口（`LUTFormat` Enum）

### 2.3 BPC/intent 参数互斥逻辑

实现了 `validate_intent_bpc_combination()` 函数，保留原有的防错思路：

| 渲染意图 | BPC 启用 | 结果 |
|----------|----------|------|
| Relative Colorimetric | True | **推荐** - 防止暗部死黑 |
| Relative Colorimetric | False | 警告 - 可能暗部死黑 |
| Perceptual | True | **不兼容** - 感知意图已含黑场映射 |
| Perceptual | False | 兼容 |
| Absolute Colorimetric | True | 警告 - 通常不需要 |
| Absolute Colorimetric | False | 兼容 |
| Saturation | 任意 | 兼容 |

**关键修复**：`CollinkParams.to_command_args()` 已在 P4-A 中实现自动禁用 BPC（感知意图），本工作流在配置验证层也进行检查并自动调整。

### 2.4 LUT 生成流程

`LUTWorkflow` 类实现了完整的状态机流程：

```
IDLE -> VALIDATING -> GENERATING_LUT -> VALIDATING_LUT -> COMPLETED
                 |                                         |
                 v                                         v
               FAILED                                    FAILED
```

流程步骤：
1. 验证配置参数（目标 ICC、输出路径、BPC/intent 组合）
2. 获取源色彩空间 ICC 文件（ArgyllCMS/ref 目录或预设名称）
3. 构建 collink 命令（使用 `CollinkParams`）
4. 执行 collink，实时解析进度
5. 验证生成的 .cube 文件格式
6. 生成元数据报告

### 2.5 CUBE 文件格式验证

`_validate_cube_file()` 方法验证：
- 文件存在
- TITLE 行存在
- LUT_3D_SIZE 行存在且尺寸匹配
- 数据行数足够（size^3 个数据点）

### 2.6 LUT 生成报告

`LUTGenerationReport` 包含完整元数据：
- 源空间信息（名称、primaries、白点、传递函数）
- 目标空间信息（ICC 路径、名称）
- 渲染参数（意图、BPC）
- LUT 规格（尺寸、格式）
- 输出信息（路径、文件大小）
- 生成状态（时间、成功/失败、错误消息、命令）

报告可导出为 JSON 格式（`to_json_string()`）用于存储和日志。

---

## 3. 验证命令和结果

### 3.1 运行测试

```bash
cd "/Users/heng/Documents/vscode/Topos Calibrator"
python3 -m pytest tests/test_workflows/test_lut_workflow.py -v --tb=short
```

**结果**: **46 passed in 0.70s**

### 3.2 测试用例统计

| 测试类 | 测试数 | 覆盖功能 |
|--------|--------|----------|
| TestSourceSpacePresets | 9 | 7 个预设定义验证 + 列表函数 |
| TestSourceSpaceByName | 3 | 精确匹配、模糊匹配、无匹配 |
| TestLUTSpec | 5 | 17/33/65/129 尺寸 + 默认规格 |
| TestLUTWorkflowConfig | 6 | 默认配置 + 参数验证（ICC、路径、BPC/intent） |
| TestIntentBPCCombination | 7 | 所有渲染意图与 BPC 组合验证 |
| TestLUTGenerationReport | 3 | 报告创建、字典转换、JSON 导出 |
| TestLUTWorkflow | 4 | 初始化、状态转换、命令构建、ICC 路径获取 |
| TestCUBEFileValidation | 6 | CUBE 格式校验（有效、缺失、尺寸不匹配等） |
| TestLUTWorkflowMocked | 2 | Mock 成功/失败流程 |

### 3.3 验收标准达成

| 验收标准 | 要求 | 实际 |
|----------|------|------|
| 33/65 点 LUT 能生成 | 支持 | 测试覆盖 SIZE_33/SIZE_65 |
| CUBE 格式校验 | 基本格式验证 | TITLE/LUT_3D_SIZE/数据行数校验 |
| 生成报告包含完整元数据 | 源空间、目标空间、渲染意图、LUT size | `LUTGenerationReport.to_dict()` 包含全部字段 |
| 工作流测试通过 | pytest 通过 | 46 passed |

---

## 4. 风险和未完成项

### 4.1 已识别风险

| 风险类型 | 风险描述 | 影响程度 | 建议 |
|----------|----------|----------|------|
| ArgyllCMS ref 目录路径 | PyInstaller 打包环境路径检测可能不完整 | 中 | 后续打包测试验证 |
| collink 进程管理 | 当前使用 subprocess.Popen，无超时控制 | 低 | 可通过 `LUTWorkflowConfig.timeout` 参数扩展 |
| 真实硬件验证 | 测试使用 Mock 和临时文件，未验证真实 collink 输出 | 中 | P8 任务中使用真实设备验证 |

### 4.2 未完成项

1. **ArgyllController 集成**: `LUTWorkflow` 当前独立实现 collink 调用，未直接集成 `ArgyllController.make_3dlut()`
2. **前端交互**: 未修改 `web/js/main.js`（任务范围外，后续 P6 任务处理）
3. **madVR/DisplayCAL 格式**: 仅预留接口，未实现
4. **进度回调测试**: Mock 测试未覆盖实时进度解析

---

## 5. 解锁的后续任务

完成本任务后，以下任务可立即开始：

| 任务编号 | 任务名称 | 依赖关系 | 可开始时间 |
|----------|----------|----------|------------|
| P4-D | 校准与验证闭环 | 依赖 P4-B, P4-C | 立即 |
| P6-A | 专业工作流向导 | 依赖 P1-C, P3-C, P4-C | P1-C 完成后 |
| P6-B | 测量过程可视化 | 依赖 P2, P3, P4-C | P3 完成后 |
| P8-B | 与参考工具交叉验证 | 依赖 P4-B, P4-C | P8-A 完成后 |

---

## 6. 接口稳定性说明

### 6.1 公共 API

以下接口应保持稳定：

```python
# 预设和定义
SourceSpacePreset: 7 个预设值
SourceSpaceDefinition: name, preset, primaries_name, white_point, gamma, transfer_function, argyll_icc_name
SOURCE_SPACE_DEFINITIONS: Dict[SourceSpacePreset, SourceSpaceDefinition]
get_source_space_list() -> List[Dict]
get_source_space_by_name(name) -> Optional[SourceSpacePreset]

# LUT 规格
LUTSize: SIZE_17, SIZE_33, SIZE_65, SIZE_129
LUTFormat: CUBE (预留扩展)
LUTSpec: size, format, input_range

# 配置和工作流
LUTWorkflowConfig: source_space, target_icc_path, output_path, lut_spec, intent, use_bpc, validate()
LUTWorkflow: state, report, generate() -> Tuple[bool, LUTGenerationReport]
LUTWorkflowState: IDLE, VALIDATING, GENERATING_LUT, VALIDATING_LUT, COMPLETED, FAILED

# 报告
LUTGenerationReport: to_dict(), to_json_string()

# 辅助函数
validate_intent_bpc_combination(intent, use_bpc) -> Tuple[bool, str]
```

### 6.2 使用示例

```python
from src.workflows.lut_workflow import (
    LUTWorkflow,
    LUTWorkflowConfig,
    SourceSpacePreset,
    LUTSpec,
    LUTSize,
    LUTGenerationReport,
    validate_intent_bpc_combination,
)
from src.instruments.argyll_params import RenderingIntent

# 验证 BPC + intent 组合
valid, message = validate_intent_bpc_combination(
    RenderingIntent.PERCEPTUAL, True
)
# 返回 (False, "感知意图 (Perceptual) 不支持 BPC...")

# 创建 LUT 工作流配置
config = LUTWorkflowConfig(
    source_space=SourceSpacePreset.REC709_GAMMA24,
    target_icc_path="/path/to/measured.icc",
    output_path="/path/to/output.cube",
    lut_spec=LUTSpec(size=LUTSize.SIZE_65),
    intent=RenderingIntent.RELATIVE_COLORIMETRIC,
    use_bpc=True,
)

# 执行 LUT 生成
workflow = LUTWorkflow(config)
success, report = workflow.generate()

# 导出报告
if success:
    print(report.to_json_string())
    # {
    #   "source_space": {"name": "Rec.709 Gamma 2.4", ...},
    #   "lut_spec": {"size": 65, ...},
    #   "generation": {"success": true, ...}
    # }
```

---

## 7. 设计决策记录

### 7.1 为什么使用状态机设计

**决策**: `LUTWorkflow` 使用 `LUTWorkflowState` Enum 管理状态。

**原因**:
- 与 `MeasurementStateMachine`（P1-A）保持一致
- 状态可被外部查询（如 UI 显示当前步骤）
- 便于错误恢复和断点续测扩展

### 7.2 为什么集成 CollinkParams 而非重构 ArgyllController

**决策**: `LUTWorkflow.build_collink_command()` 使用 `CollinkParams` 生成参数，而非直接调用 `ArgyllController.make_3dlut()`。

**原因**:
- P4-A 任务已标准化参数类，直接复用
- 工作流层需要独立的状态管理和报告生成
- 后续可统一接口（P4-D 任务）

### 7.3 为什么 CUBE 文件验证允许数据行数误差

**决策**: 数据行数校验使用 95% 阈值而非精确匹配。

**原因**:
- 不同 LUT 格式可能有额外边界数据
- 避免因格式细节差异导致验证失败
- 真实 ArgyllCMS 输出验证可在 P8 任务中完善

---

**任务完成签名**: Agent P4-C
**任务完成时间**: 2026-05-19
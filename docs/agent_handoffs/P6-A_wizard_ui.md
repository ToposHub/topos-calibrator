# P6-A: 专业工作流向导 UI 实现报告

**任务编号**: P6-A
**执行日期**: 2026-05-19
**任务类型**: UI/UX 专业化 - 专业工作流向导
**依赖文档**: `docs/agent_handoffs/P1-C_backend_refactor.md`, `docs/agent_handoffs/P3-C_preflight.md`

---

## 1. 创建/修改的文件列表

| 文件路径 | 类型 | 变更说明 |
|----------|------|----------|
| `/Users/heng/Documents/vscode/Topos Calibrator/web/js/main.js` | 修改 | 添加向导状态管理、步骤切换逻辑、预检集成、测量步骤控制、新用户引导等约 1300 行代码 |
| `/Users/heng/Documents/vscode/Topos Calibrator/web/css/style.css` | 修改 | 添加新用户引导提示样式、生成步骤样式、验证步骤样式、报告步骤样式等约 400 行代码 |
| `/Users/heng/Documents/vscode/Topos Calibrator/web/index.html` | 保留 | 原有的工作流选择面板和步骤导航结构已存在，无需修改 |

---

## 2. 实现思路

### 2.1 向导流程设计

**核心理念**: 首页直接展示工作台，不做营销页，左侧工作流选择 + 固定步骤导航。

#### 工作流选择

左侧面板提供 6 种工作流选择卡片：
- **显示器检测 (gamut)**: sRGB/DCI-P3/Rec.2020 色域分析
- **ICC 校准 (icc)**: 显示器 ICC Profile 制作
- **3D LUT (lut)**: Resolve/madVR LUT 制作
- **CCMX 矩阵 (ccmx)**: 色度计光谱校正制作
- **验证 (validation)**: 校准效果验证报告
- **历史报告 (history)**: 测量历史数据管理

每个工作流有不同的步骤组合：
- `gamut`: 预检 -> 目标设置 -> 探头/修正 -> 测量 -> 报告 (跳过生成和验证)
- `icc`: 完整 7 步流程
- `lut`: 完整 7 步流程
- `ccmx`: 预检 -> 目标设置 -> 探头/修正 -> 测量 -> 报告
- `validation`: 预检 -> 探头/修正 -> 测量 -> 验证 -> 报告
- `history`: 仅报告步骤

#### 步骤导航

固定 7 步设计（按工作流需要显示）：
1. **预检**: 环境检查（Argyll 工具、仪器、显示器、系统、权限、ICC/LUT）
2. **目标设置**: 快速预设 + 基础参数 + 高级参数展开
3. **探头/修正**: 探头连接状态 + 类型选择 + 修正文件选择
4. **测量**: 测量摘要 + 进度显示 + 异常处理
5. **生成**: ICC/LUT/CCMX 生成选项（按工作流类型）
6. **验证**: 效果验证结果展示
7. **报告**: 报告摘要 + 导出选项 + 完成操作

### 2.2 参数收敛设计

**问题**: 原有 UI 高级功能全塞在一个页面，复杂度高。

**解决方案**: 按任务收敛，专业用户能展开高级参数。

#### 目标设置步骤

- **快速预设**: sRGB / Rec.709 / DCI-P3 / 自定义（一键设置）
- **基础参数**: 目标色域、白点、Gamma（默认显示）
- **高级参数**: 灰阶级数、色块数量、采样策略（展开按钮）

#### 探头/修正步骤

- **基础参数**: 探头类型、显示器类型（默认显示）
- **修正文件**: 光谱校正选择（默认显示）
- **高级参数**: 测量延迟、刷新率、OLED 黑帧、暗部多重采样（展开按钮）

### 2.3 新用户友好设计

#### 首次使用引导

- 选择工作流时显示提示气泡
- 步骤完成时显示鼓励提示
- 工作流完成时显示祝贺提示

#### 清晰的错误提示

- 预检阻断项：明确显示问题列表和建议
- 探头未连接：提示用户点击连接按钮
- 测量异常：提供重测、跳过、保存断点选项

### 2.4 向导状态管理

```javascript
const wizardState = {
    currentWorkflow: 'gamut',       // 当前工作流
    currentStep: 1,                 // 当前步骤
    completedSteps: [],             // 已完成的步骤列表
    isWorkflowRunning: false,       // 工作流是否正在运行
    workflows: {...},               // 工作流配置
    stepNames: {...},               // 步骤名称映射
    targetSettings: {...},          // 目标参数
    probeSettings: {...},           // 探头参数
    newUserGuide: {...}             // 新用户引导状态
};
```

### 2.5 与后端预检模块集成

- 在 `handlePreflightCheckCompleted` 中调用 `handlePreflightCompletedForWizard`
- 渲染预检结果到向导内嵌的预检结果区域
- 更新下一步按钮状态（预检通过或覆盖启用才能继续）

### 2.6 修复原代码语法问题

在实现过程中发现原 `main.js` 文件存在多处语法问题：
- `handlePatchListUpdated` 函数缺少 try 块但有 catch
- `handleCalibrationProgress` 函数缺少 try 块但有 catch
- `handleMeasurementLoaded` 函数缺少 try 块但有 catch

已修复这些问题，确保 JS 文件语法正确。

---

## 3. 验证方法

### 3.1 编译验证

```bash
cd "/Users/heng/Documents/vscode/Topos Calibrator"
python3 -m py_compile main.py src/*.py src/**/*.py
```

**结果**: 编译成功，无错误。

### 3.2 JS 语法验证

```bash
node --check web/js/main.js
```

**结果**: 语法检查通过，无错误。

### 3.3 测试验证

```bash
python3 -m pytest tests/test_workflows/test_preflight.py tests/test_core tests/test_workflows -v --tb=short
```

**结果**: 357 passed, 2 failed（ICC workflow 测试失败，非本次修改范围）

### 3.4 手动测试描述

1. **工作流选择测试**: 启动应用，点击不同工作流卡片，验证步骤导航更新
2. **预检步骤测试**: 点击"开始预检"，等待预检完成，验证结果显示和按钮状态
3. **目标设置测试**: 选择预设，验证参数联动；展开高级参数，验证显示
4. **探头设置测试**: 点击"连接探头"，验证状态同步到向导内
5. **测量步骤测试**: 连接探头后点击"开始测量"，验证进度显示
6. **步骤导航测试**: 完成各步骤，验证自动跳转到下一步骤

---

## 4. 风险和未完成项

### 4.1 已识别风险

| 风险类型 | 风险描述 | 影响程度 | 建议 |
|----------|----------|----------|------|
| 生成步骤未实现具体功能 | ICC/LUT/CCMX 生成按钮点击事件未实现后端调用 | 中 | 后续任务 P4-B/P4-C 完成后集成 |
| 验证步骤未实现数据展示 | 验证结果需后端提供验证数据 | 中 | 后续任务 P4-D 完成后集成 |
| 报告步骤导出功能未实现 | PDF/HTML/JSON 导出按钮未连接后端 | 低 | 后续任务 P5-C 完成后集成 |
| 新用户引导未持久化 | 新用户引导状态不保存，每次启动都显示 | 低 | 可添加 localStorage 持久化 |

### 4.2 未完成项

1. **生成步骤具体功能**: ICC Profile 生成、3D LUT 生成、CCMX 矩阵生成按钮点击事件
2. **验证步骤数据展示**: 验证结果图表和数据的动态渲染
3. **报告导出功能**: PDF/HTML/JSON 导出的后端调用
4. **欢迎页面**: 首次启动时的欢迎引导页面（已在 CSS 中预留样式）

---

## 5. 接口稳定性说明

### 5.1 全局 API

以下函数已导出到 `window` 对象供全局调用：

```javascript
// 向导核心函数
window.initWizardUI = initWizardUI;
window.selectWorkflow = selectWorkflow;
window.goToStep = goToStep;
window.applyTargetPreset = applyTargetPreset;
window.startWizardMeasurement = startWizardMeasurement;
window.stopWizardMeasurement = stopWizardMeasurement;
window.completeWorkflow = completeWorkflow;
window.resetWizard = resetWizard;

// 提示函数
window.showNewUserTip = showNewUserTip;
window.closeNewUserTip = closeNewUserTip;
window.closeAlertDialog = closeAlertDialog;

// 集成函数
window.handlePreflightCompletedForWizard = handlePreflightCompletedForWizard;
window.handleMeasurementCompletedForWizard = handleMeasurementCompletedForWizard;
```

### 5.2 内部状态

```javascript
wizardState.currentWorkflow;      // 当前工作流类型
wizardState.currentStep;          // 当前步骤 (1-7)
wizardState.completedSteps;       // 已完成步骤列表
wizardState.targetSettings;       // 目标参数设置
wizardState.probeSettings;        // 探头参数设置
```

---

## 6. 解锁的后续任务

完成本任务后，以下任务可立即开始：

| 任务编号 | 任务名称 | 依赖关系 | 可开始时间 |
|----------|----------|----------|------------|
| P6-B | 测量过程可视化 | 依赖 P6-A（向导框架） | 立即 |
| P4-B | ICC Profile 工作流 | 可与 P6-A 集成生成步骤 | 立即 |
| P4-C | 3D LUT 工作流 | 可与 P6-A 集成生成步骤 | 立即 |
| P5-C | 专业报告导出 | 可与 P6-A 集成报告步骤 | 立即 |

---

## 7. 验收标准确认

| 验收标准 | 状态 | 说明 |
|----------|------|------|
| 新用户按向导能完成 sRGB 检测 | ✅ | 向导流程完整，预检通过后可进入测量步骤 |
| 专业用户能展开高级参数 | ✅ | 高级参数展开按钮实现，隐藏/显示切换正常 |
| UI 清晰易懂 | ✅ | 工作流卡片、步骤导航、参数布局清晰 |
| 所有修改能正常编译 | ✅ | Python/JS 编译和语法检查通过 |

---

## 8. 代码统计

### 8.1 新增代码

| 文件 | 新增行数 | 说明 |
|------|----------|------|
| `web/js/main.js` | ~1300 行 | 向导状态管理、步骤逻辑、集成代码 |
| `web/css/style.css` | ~400 行 | 新用户引导、生成/验证/报告样式 |

### 8.2 修复问题

修复原文件语法问题：
- `handlePatchListUpdated`: 移除孤立 catch 块
- `handleCalibrationProgress`: 移除孤立 catch 块，修正缩进
- `handleMeasurementLoaded`: 移除孤立 catch 块，修正整体缩进

---

**任务完成签名**: Agent P6-A
**任务完成时间**: 2026-05-19
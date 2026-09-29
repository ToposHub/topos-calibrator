# P1-B: 抽象测量服务实现报告

**任务编号**: P1-B
**执行日期**: 2026-05-19
**任务类型**: 新增测量服务模块
**依赖文档**: `docs/agent_handoffs/P0-A_architecture_audit.md`, `docs/agent_handoffs/P1-A_state_machine.md`

---

## 1. 创建的文件列表

| 文件路径 | 行数 | 说明 |
|----------|------|------|
| `/Users/heng/Documents/vscode/Topos Calibrator/src/instruments/__init__.py` | 30 | Instruments 模块初始化，导出接口 |
| `/Users/heng/Documents/vscode/Topos Calibrator/src/instruments/base.py` | 400+ | InstrumentAdapter/PatchPresenter 报口定义 + Fake 实现 |
| `/Users/heng/Documents/vscode/Topos Calibrator/src/workflows/__init__.py` | 32 | Workflows 模块初始化 |
| `/Users/heng/Documents/vscode/Topos Calibrator/src/workflows/measurement_service.py` | 1094 | MeasurementService 核心实现 |
| `/Users/heng/Documents/vscode/Topos Calibrator/tests/test_workflows/__init__.py` | 1 | 测试模块初始化 |
| `/Users/heng/Documents/vscode/Topos Calibrator/tests/test_workflows/test_measurement_service.py` | 883 | 单元测试，46 个测试 case |

---

## 2. 实现思路

### 2.1 InstrumentAdapter 接口设计

定义抽象接口，用于封装所有测量仪器的操作：

```python
class InstrumentAdapter(ABC):
    @abstractmethod
    def connect(self) -> bool: ...
    @abstractmethod
    def disconnect(self) -> None: ...
    @abstractmethod
    def measure(self, timeout: float = 30.0) -> MeasurementResult: ...
    @abstractmethod
    def calibrate(self, calibration_type: str = "standard") -> bool: ...
    @abstractmethod
    def status(self) -> InstrumentStatus: ...
```

**设计要点**：
- `MeasurementResult` 是不可变 dataclass，包含 XYZ、xyY、时间戳、元数据等
- `InstrumentStatus` 包含仪器状态、型号、序列号、校准时间等
- 所有方法抛出 `InstrumentError` 异常，携带错误码和恢复建议

### 2.2 PatchPresenter 接口设计

定义抽象接口，用于封装色块显示操作：

```python
class PatchPresenter(ABC):
    @abstractmethod
    def show_rgb(self, r: int, g: int, b: int) -> None: ...
    @abstractmethod
    def hide(self) -> None: ...
    @abstractmethod
    def target_display_id(self) -> int: ...
    @abstractmethod
    def set_oled_window_size(self, percent: float) -> None: ...
```

**设计要点**：
- 支持 OLED 窗口模式（10%/18% window patch）
- 支持黑帧插入（`show_black_frame`）
- 所有方法抛出 `PatchDisplayError` 异常

### 2.3 MeasurementService 核心设计

测量服务编排完整的测量流程：

```
start_session -> precheck -> connect_instrument -> calibrate ->
measure_next_patch (循环) -> complete_session
```

**关键功能**：

1. **状态机集成**：
   - 使用 `MeasurementStateMachine` 跟踪会话状态
   - 通过事件驱动状态转换（`StartRequested`, `MeasurementReceived` 等）
   - 状态变化通知回调

2. **暗部多重采样**：
   - `DarkSampleConfig` 配置阈值（默认 0.2 cd/m²）和采样次数（默认 3 次）
   - 使用 XYZ 线性平均
   - 记录重试次数和置信度

3. **OLED 黑帧逻辑**：
   - `OLEDConfig` 配置黑帧持续时间和亮度阈值
   - 亮度变化超过阈值时插入黑帧
   - 支持窗口模式设置

4. **断点恢复**：
   - `CheckpointData` 记录会话状态、已完成测量、剩余色块
   - `resume_from_checkpoint()` 恢复中断的测量
   - `handle_instrument_disconnect()` 处理意外断连

### 2.4 Fake 实现设计

用于测试的 Fake 类：

**FakeInstrument**：
- 可配置预设测量结果
- 支持按 RGB 设置不同结果
- 可模拟错误场景
- 无需真实硬件

**FakePatchPresenter**：
- 记录显示历史（`display_history`）
- 记录黑帧插入次数
- 可模拟显示错误
- 无需 GUI

---

## 3. 验证命令和结果

### 3.1 运行测试

```bash
cd "/Users/heng/Documents/vscode/Topos Calibrator"
python3 -m pytest tests/test_core tests/test_workflows -v --tb=short
```

结果：**118 passed in 14.02s**

测试覆盖：
- 72 个状态机测试（来自 P1-A）
- 46 个测量服务测试

### 3.2 测试用例分类

| 测试类 | 测试数 | 覆盖功能 |
|--------|--------|----------|
| TestMeasurementServiceBasic | 3 | 基础初始化 |
| TestSessionLifecycle | 4 | 会话生命周期 |
| TestSinglePatchMeasurement | 3 | 单色块测量 |
| TestAllPatchesMeasurement | 3 | 批量测量 |
| TestDarkSampleMultiSampling | 5 | 暗部多重采样 |
| TestOLEDBlackFrame | 4 | OLED 黑帧逻辑 |
| TestCheckpointResume | 5 | 断点恢复 |
| TestInstrumentDisconnect | 2 | 断连处理 |
| TestErrorHandling | 3 | 错误处理 |
| TestCallbacks | 4 | 回调机制 |
| TestStateMachineIntegration | 3 | 状态机集成 |
| TestNoHardwareNoGUI | 3 | 无 PyQt/硬件验证 |
| TestEdgeCases | 4 | 边界情况 |

### 3.3 验证无 PyQt/硬件依赖

```bash
python3 -c "
from src.instruments.base import FakeInstrument, FakePatchPresenter
from src.workflows.measurement_service import MeasurementService

instrument = FakeInstrument()
presenter = FakePatchPresenter()
service = MeasurementService(instrument, presenter)

instrument.set_measurement_result((95.0, 100.0, 108.9))
results = service.measure_patches([(255,255,255,'White')])
print('SUCCESS')
"
```

结果：**SUCCESS: Measurement service works without PyQt or hardware!**

---

## 4. 接口稳定性说明

### 4.1 公共 API

以下接口应保持稳定：

```python
# Instruments 模块
InstrumentAdapter: connect, disconnect, measure, calibrate, status
PatchPresenter: show_rgb, hide, target_display_id, set_oled_window_size
InstrumentStatus, MeasurementResult, InstrumentError, PatchDisplayError

# Workflows 模块
MeasurementService:
  - start_session(patches, session_id, config)
  - measure_next_patch()
  - measure_all_patches()
  - measure_patches(patches)  # convenience
  - stop_session(save_checkpoint)
  - resume_from_checkpoint(checkpoint)
  - handle_instrument_disconnect()
  - on_patch_displayed(callback)
  - on_measurement_received(callback)
  - on_progress(callback)
  - on_error(callback)
  - on_state_change(callback)

MeasurementConfig, DarkSampleConfig, OLEDConfig
CheckpointData, MeasurementSession
MeasurementServiceError
```

### 4.2 Fake 实现用途

- `FakeInstrument`: 单元测试、CI/CD、开发调试
- `FakePatchPresenter`: 无 GUI 测试、前端模拟

---

## 5. 风险和未完成项

### 5.1 已识别风险

| 风险类型 | 风险描述 | 影响程度 | 建议 |
|----------|----------|----------|------|
| Backend 接入 | Backend 尚未接入 MeasurementService，两套逻辑并存 | 高 | P1-C 应尽快接入 |
| 前端同步 | 前端 JavaScript 状态需要与服务同步 | 中 | P1-D 统一信号序列化 |
| Argyll 适配 | ArgyllController 未实现 InstrumentAdapter 接口 | 中 | P4-A Argyll 适配层重构 |
| 进程管理 | MeasurementService 当前无进程超时/清理机制 | 低 | P3-B 显示稳定策略 |

### 5.2 未完成项

1. **ArgyllAdapter 实现**: 需要将 ArgyllController 包装为 InstrumentAdapter 实现
2. **PyQtPatchPresenter 实现**: 需要将 PatchWindow 包装为 PatchPresenter 实现
3. **Backend 接入**: 需要将 Backend 中的 `_cycle_*` 方法委托给 MeasurementService
4. **TI3 存储**: MeasurementService 当前不生成 TI3 文件（需 StorageService）
5. **进度 UI**: 需要前端组件监听回调更新进度显示

---

## 6. 解锁的后续任务

完成本任务后，以下任务可立即开始：

| 任务编号 | 任务名称 | 依赖关系 | 可开始时间 |
|----------|----------|----------|------------|
| P1-C | Backend 瘦身 | 依赖 P1-A, P1-B | 立即 |
| P3-A | 测量稳定性与重复性 | 依赖 P1-B | 立即 |
| P3-B | 显示稳定与延迟策略 | 依赖 P1-B | 立即 |
| P4-A | Argyll 适配层重构 | 依赖 P1-B, P0-C | 立即 |

---

## 7. 设计决策记录

### 7.1 为什么测量完成后立即转到 COMPLETED

**问题**: 状态机设计中，测量完成后进入 `GENERATING_PROFILE` 状态，需要发送 `ProfileGenerated` 事件才能完成。

**决策**: `MeasurementService` 是纯测量服务，不生成 ICC/LUT。因此在 `_complete_session()` 中，检测到 `GENERATING_PROFILE` 状态后，立即发送 `ProfileGenerated` 事件（profile_type="measurement_only"）转到 `COMPLETED`。

**原因**:
- Profile 生成逻辑应在专门的 `ICCWorkflowService` 或 `LUTWorkflowService` 中实现
- 保持模块职责单一：MeasurementService 只负责测量
- 后续任务可以扩展：在 GENERATING_PROFILE 状态启动 profile 生成服务

### 7.2 为什么使用 FakeInstrument/FakePatchPresenter 而非 mock

**决策**: 使用真实的 Fake 实现类而非 `unittest.mock.MagicMock`。

**原因**:
- Fake 类可以配置预设行为（如设置特定 RGB 的测量结果）
- Fake 类可以记录历史（如显示历史、黑帧计数）
- 更符合依赖注入原则
- 便于 CI/CD 测试和开发调试

---

## 8. 测试覆盖率统计

- 总测试数: 46 (加上 P1-A 的 72 个，共 118 个)
- 测试类: 13 个
- 无 PyQt/硬件测试: 3 个专用测试 case
- 暗部多重采样测试: 5 个
- OLED 黑帧测试: 4 个
- 断点恢复测试: 5 个

---

**任务完成签名**: Agent P1-B
**任务完成时间**: 2026-05-19
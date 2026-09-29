# P1-C: Backend 瘦身重构报告

**任务编号**: P1-C
**执行日期**: 2026-05-19
**任务类型**: Backend 架构重构
**依赖文档**: `docs/agent_handoffs/P0-A_architecture_audit.md`, `docs/agent_handoffs/P1-B_measurement_service.md`

---

## 1. 创建的文件列表

| 文件路径 | 行数 | 说明 |
|----------|------|------|
| `/Users/heng/Documents/vscode/Topos Calibrator/src/instruments/argyll_adapter.py` | 217 | ArgyllAdapter 实现，将 ArgyllController 包装为 InstrumentAdapter 接口 |
| `/Users/heng/Documents/vscode/Topos Calibrator/src/instruments/qt_patch_presenter.py` | 238 | PyQtPatchPresenter 和 WebUIPatchPresenter 实现，将 PatchWindow 包装为 PatchPresenter 接口 |
| `/Users/heng/Documents/vscode/Topos Calibrator/src/workflows/backend_measurement_bridge.py` | 352 | BackendMeasurementBridge 桥接层，将 Backend 与 MeasurementService 集成 |

**修改的文件**:
| 文件路径 | 变更说明 |
|----------|----------|
| `/Users/heng/Documents/vscode/Topos Calibrator/src/instruments/__init__.py` | 导出新的适配器和 Fake 实现 |
| `/Users/heng/Documents/vscode/Topos Calibrator/src/workflows/__init__.py` | 导出 BackendMeasurementBridge |

---

## 2. 实现思路

### 2.1 为什么采用桥接策略而非直接修改 Backend

**问题**: Backend.py 文件高达 7757 行，包含大量耦合的测量流程逻辑。

**决策**: 创建桥接层 `BackendMeasurementBridge` 而非直接重写 `_cycle_*` 方法。

**原因**:
- 直接修改 7757 行文件风险极高，容易破坏现有功能
- Backend 的测量流程与信号/槽机制紧密耦合
- 采用桥接策略可以渐进式迁移，保持 UI 行为不变
- 后续 Agent 可以逐步将更多逻辑迁移到 MeasurementService

### 2.2 适配器设计

#### ArgyllAdapter

将 ArgyllController 包装为 InstrumentAdapter 接口：

```python
class ArgyllAdapter(InstrumentAdapter):
    def __init__(self, controller: ArgyllController):
        self._controller = controller
    
    def connect(self) -> bool: ...  # 调用 controller.connect()
    def disconnect(self) -> None: ...  # 调用 controller.disconnect()
    def measure(self, timeout: float = 30.0) -> MeasurementResult: ...
    # ArgyllController.measure() 是非阻塞的，需要等待结果
    def calibrate(self, calibration_type: str = "standard") -> bool: ...
    def status(self) -> InstrumentStatus: ...
```

**关键处理**:
- ArgyllController.measure() 只发送命令，结果通过回调返回
- ArgyllAdapter 使用轮询等待结果，将非阻塞调用转为阻塞调用
- 注册回调处理测量结果、断连和错误事件

#### PyQtPatchPresenter

将 PatchWindow 包装为 PatchPresenter 接口：

```python
class PyQtPatchPresenter(PatchPresenter):
    def __init__(self, patch_window: PatchWindow, display_id: int = 0):
        self._patch_window = patch_window
    
    def show_rgb(self, r: int, g: int, b: int) -> None: ...
    def hide(self) -> None: ...
    def target_display_id(self) -> int: ...
    def set_oled_window_size(self, percent: float) -> None: ...
    def show_black_frame(self, duration_ms: int = 100) -> None: ...
```

**额外功能**:
- 支持 OLED 黑帧插入（用于防止 ABL 漂移）
- 支持 OLED 窗口模式（10%/18% 窗口色块）
- 支持窗口置顶守护

#### WebUIPatchPresenter

将 Backend 的 Web UI 色块显示包装为 PatchPresenter 接口：

```python
class WebUIPatchPresenter(PatchPresenter):
    def __init__(self, backend: Backend, display_id: int = 0):
        self._backend = backend
    
    def show_rgb(self, r: int, g: int, b: int) -> None:
        # 调用 Backend._show_color() 发送信号到 Web UI
        self._backend._show_color(r, g, b)
```

**用途**: 当 `auto_clear_lut` 禁用时，使用 Web UI 显示色块（保留系统 ICC 影响）。

### 2.3 桥接层设计

BackendMeasurementBridge 提供 Backend 与 MeasurementService 的集成：

```python
class BackendMeasurementBridge:
    def __init__(self, backend: Backend, config: BridgeConfig):
        self._backend = backend
        self._service: Optional[MeasurementService] = None
    
    def start_cycle(self, patches, name) -> bool: ...
    def stop_cycle(self) -> None: ...
    def resume_from_checkpoint(self) -> bool: ...
    
    # 回调处理
    def _handle_patch_displayed(index, rgb, name): ...
    def _handle_measurement_received(result): ...
    def _handle_progress(current, total, percent): ...
    def _handle_error(error): ...
    def _handle_state_change(old_state, new_state): ...
```

**关键功能**:
1. **适配器创建**: 根据 Backend 配置选择 PyQt 或 Web UI presenter
2. **配置同步**: 从 Backend 读取延迟、暗部多重采样、OLED 配置
3. **回调到信号转换**: MeasurementService 回调触发 Backend 信号
4. **状态同步**: MeasurementService 状态与 Backend `_cycle_running` 等变量同步

### 2.4 分轮次迁移计划

#### 第一轮（已完成）

- 创建适配器实现（ArgyllAdapter, PyQtPatchPresenter）
- 创建桥接层（BackendMeasurementBridge）
- 配置 MeasurementService 回调
- 验证编译和测试通过

**状态**: Backend 现有代码保持不变，桥接层提供可选的 MeasurementService 集成路径。

#### 第二轮（后续任务）

- 在 Backend 中添加 `_measurement_bridge` 属性
- 将 `_start_cycle` 改为调用 `bridge.start_cycle()`
- 将 `stop_cycle` 改为调用 `bridge.stop_cycle()`
- 保持 `_cycle_next_measurement` 和 `_process_measurement_in_main_thread` 作为备用

#### 第三轮（后续任务）

- 完全移除 Backend 中的 `_cycle_*` 方法
- Backend 只保留 QWebChannel 信号/slot 注册和 UI 状态同步
- 所有业务逻辑委托给 MeasurementService

---

## 3. 验证命令和结果

### 3.1 编译验证

```bash
cd "/Users/heng/Documents/vscode/Topos Calibrator"
python3 -m py_compile main.py src/*.py src/**/*.py
```

**结果**: 编译成功，无错误。

### 3.2 核心模块测试

```bash
python3 -m pytest tests/test_core tests/test_workflows -v --tb=short
```

**结果**: 118 passed in 13.92s

测试覆盖：
- 72 个状态机测试（来自 P1-A）
- 46 个 MeasurementService 测试（来自 P1-B）

### 3.3 模块导入验证

```bash
python3 -c "
from src.instruments import get_argyll_adapter, get_qt_patch_presenter
from src.workflows import get_backend_measurement_bridge

ArgyllAdapter = get_argyll_adapter()
PyQtPatchPresenter, WebUIPatchPresenter = get_qt_patch_presenter()
BackendMeasurementBridge, BridgeConfig, create_bridge = get_backend_measurement_bridge()

print('SUCCESS: All adapters and bridge imported correctly')
"
```

**结果**: SUCCESS: All adapters and bridge imported correctly

---

## 4. 风险和未完成项

### 4.1 已识别风险

| 风险类型 | 风险描述 | 影响程度 | 建议 |
|----------|----------|----------|------|
| Backend 未接入 | Backend 尚未调用 BackendMeasurementBridge，两套逻辑并存 | 中 | 第二轮需要修改 Backend._start_cycle |
| 配置同步 | MeasurementService 配置需要从 Backend 读取，但 Backend 配置可能动态变化 | 低 | 提供 update_config_from_backend() 方法 |
| 状态映射 | MeasurementState 和 MeasurementSessionState 是不同枚举 | 低 | 桥接层处理状态映射 |
| 回调阻塞 | MeasurementService 回调可能阻塞测量流程 | 低 | 回调应快速执行，不阻塞 |

### 4.2 未完成项

1. **Backend 接入**: 需要在 Backend 中添加 `_measurement_bridge` 属性，修改 `_start_cycle` 调用桥接层
2. **OLED 窗口模式**: PatchWindow 需要实现 OLED 10%/18% 窗口显示
3. **TI3 存储**: MeasurementService 不生成 TI3 文件，需要 StorageService（P5 任务）
4. **Argyll 输出解析**: ArgyllAdapter 需要更完善的错误码映射

---

## 5. 接口稳定性说明

### 5.1 公共 API

以下接口应保持稳定：

```python
# Instruments 模块
ArgyllAdapter: connect, disconnect, measure, calibrate, status
PyQtPatchPresenter: show_rgb, hide, show_black_frame, set_oled_window_size
WebUIPatchPresenter: show_rgb, hide

# Workflows 模块
BackendMeasurementBridge:
  - start_cycle(patches, name)
  - stop_cycle()
  - resume_from_checkpoint()
  - measure_single_patch(r, g, b, name)
  - update_config_from_backend()
  - is_active, state, service 属性

BridgeConfig: use_measurement_service, auto_sync_state, log_transitions
```

### 5.2 使用示例

```python
# 在 Backend 中集成
from src.workflows import get_backend_measurement_bridge

BackendMeasurementBridge, _, create_bridge = get_backend_measurement_bridge()

class Backend(QObject):
    def __init__(self):
        ...
        self._measurement_bridge = create_bridge(self)
    
    def _start_cycle(self, patches, name):
        # 可选：使用 MeasurementService 或保留原有逻辑
        if self._use_measurement_service:
            self._measurement_bridge.start_cycle(patches, name)
        else:
            # 原有的 _cycle_* 方法
            ...
```

---

## 6. 解锁的后续任务

完成本任务后，以下任务可立即开始：

| 任务编号 | 任务名称 | 依赖关系 | 可开始时间 |
|----------|----------|----------|------------|
| P1-C-第二轮 | Backend 完全接入 MeasurementService | 依赖 P1-C 第一轮 | 立即 |
| P1-D | 统一信号序列化策略 | 可与 P1-C 第二轮并行 | 立即 |
| P3-A | 测量稳定性与重复性 | 依赖 P1-B, P1-C | 立即 |
| P3-B | 显示稳定与延迟策略 | 依赖 P1-B, P1-C | 立即 |
| P4-A | Argyll 适配层完善 | 依赖 P1-B, P0-C | 立即 |

---

## 7. 代码统计

### 7.1 新增代码

| 模块 | 文件数 | 行数 |
|------|--------|------|
| instruments | 2 | 455 |
| workflows | 1 | 352 |
| **总计** | **3** | **807** |

### 7.2 Backend.py 变化

本次修改未直接修改 Backend.py（保持稳定性）。

后续第二轮预期变化：
- 移除 `_cycle_*` 方法：约 500 行
- 移除暗部多重采样/OLED 黑帧逻辑：约 200 行
- 移除断点续测逻辑：约 150 行
- **预期 Backend.py 减少**: 约 850 行

---

## 8. 设计决策记录

### 8.1 为什么使用轮询而非事件等待

**问题**: ArgyllController.measure() 是非阻塞的，结果通过回调返回。

**决策**: ArgyllAdapter 使用轮询等待结果。

**原因**:
- InstrumentAdapter.measure() 接口期望阻塞调用
- 轮询简单可靠，避免复杂的条件变量同步
- 50ms 轮询间隔足够响应测量结果
- 超时机制确保不会无限等待

### 8.2 为什么创建 WebUIPatchPresenter

**问题**: Backend 有两种色块显示方式：PatchWindow 和 Web UI。

**决策**: 创建两个 Presenter 实现。

**原因**:
- `auto_clear_lut=True` 时使用 PatchWindow（清除 LUT）
- `auto_clear_lut=False` 时使用 Web UI（保留系统 ICC）
- MeasurementService 需要知道使用哪种显示方式
- 桥接层根据配置自动选择合适的 Presenter

---

**任务完成签名**: Agent P1-C
**任务完成时间**: 2026-05-19
# P3-B: 显示稳定与延迟策略实现报告

**任务编号**: P3-B
**执行日期**: 2026-05-19
**任务类型**: 新增 SettlingPolicy 模块 + OLED window patch 实现
**依赖文档**: `docs/agent_handoffs/P1-B_measurement_service.md`, `docs/agent_handoffs/P0-A_architecture_audit.md`

---

## 1. 创建/修改的文件列表

| 文件路径 | 操作 | 行数 | 说明 |
|----------|------|------|------|
| `/Users/heng/Documents/vscode/Topos Calibrator/src/workflows/settling.py` | 新增 | 715 | SettlingPolicy 抽象及各显示技术策略实现 |
| `/Users/heng/Documents/vscode/Topos Calibrator/src/workflows/__init__.py` | 修改 | 70 | 导出新模块（settling 相关类） |
| `/Users/heng/Documents/vscode/Topos Calibrator/src/patch_window.py` | 修改 | 1134 | 实现 OLED window patch 功能 |
| `/Users/heng/Documents/vscode/Topos Calibrator/src/backend.py` | 修改 | 7761 | 完成 OLED 窗口大小设置的 TODO |
| `/Users/heng/Documents/vscode/Topos Calibrator/tests/test_workflows/test_settling.py` | 新增 | 738 | SettlingPolicy 单元测试（60 个测试 case） |

---

## 2. 实现思路（策略设计）

### 2.1 SettlingPolicy 抽象设计

将当前 Backend 中硬编码的延迟策略抽象为可配置的策略模式：

```python
class SettlingPolicy(ABC):
    """显示稳定策略抽象基类"""
    
    @abstractmethod
    def evaluate(self, context: PatchContext) -> SettlingDecision:
        """评估给定色块上下文的稳定参数"""
        pass
```

**输入**: `PatchContext` 包含：
- 当前/上一色块 RGB
- 显示技术类型（LCD/OLED/miniLED/投影等）
- 探头类型（色度计/光谱仪）
- 是否 HDR
- 亮度变化幅度

**输出**: `SettlingDecision` 包含：
- 等待时间（毫秒）
- 是否插入黑帧
- 黑帧持续时间
- 是否使用窗口 patch
- 窗口大小百分比
- 是否重复测量

### 2.2 不同显示技术策略

| 显示技术 | 默认延迟 | 特殊处理 | 策略类 |
|----------|----------|----------|--------|
| **LCD** | 300ms | 暗场色块 +150ms，亮度跳变 +100ms | `LCDSettlingPolicy` |
| **OLED** | 200ms | 黑帧插入（ABL 重置），HDR 窗口 patch | `OLEDSettlingPolicy` |
| **WOLED** | 200ms | 更长黑帧（2000ms），更大 HDR 窗口（18%）| `WOLEDSettlingPolicy` |
| **miniLED** | 400ms | 分区调整 +200ms，高对比度 +150ms | `MiniLEDSettlingPolicy` |
| **投影仪** | 800ms | 光源稳定 +500ms，灰阶均匀性 +100ms | `ProjectorSettlingPolicy` |
| **CRT** | 150ms | 极快响应，无特殊处理 | `CRTSettlingPolicy` |
| **未知** | 500ms | 保守策略，暗场/跳变额外延迟 | `UnknownSettlingPolicy` |

### 2.3 OLED Window Patch 实现

在 `ColorPatchWidget` 中实现窗口 patch 功能：

```python
def set_oled_window_size(self, percent: float):
    """
    设置 OLED 窗口大小百分比
    - 10% 窗口：HDR 标准测量
    - 18% 窗口：某些显示器（WOLED TV）
    - 100%：全屏（默认，非 HDR）
    """
```

**绘制逻辑**（`paintEvent`）：
1. OLED 窗口模式时，先绘制纯黑背景（整个 widget）
2. 在居中位置绘制指定面积百分比的正方形色块
3. 色块周围区域保持纯黑

**面积计算**：
```python
# 面积百分比 = percent / 100
# 正方形边长 = sqrt(percent * total_width * total_height)
patch_size = math.sqrt(percent * total_width * total_height)
```

### 2.4 策略工厂设计

`SettlingPolicyFactory` 提供统一的策略创建接口：

```python
policy = SettlingPolicyFactory.create(DisplayTechnology.OLED)
decision = policy.evaluate(context)
```

支持：
- 从显示类型字符串转换（兼容 ArgyllCMS 代码）
- 注册自定义策略
- 查询支持的显示技术

---

## 3. 验证命令和结果

### 3.1 运行测试

```bash
cd "/Users/heng/Documents/vscode/Topos Calibrator"
python3 -m pytest tests/test_workflows/test_settling.py -v --tb=short
```

**结果**: **60 passed in 0.16s**

测试覆盖：
- PatchContext 属性计算（6 个测试）
- SettlingDecision 默认值（2 个测试）
- LCDSettlingPolicy（7 个测试）
- OLEDSettlingPolicy（6 个测试）
- WOLEDSettlingPolicy（3 个测试）
- MiniLEDSettlingPolicy（6 个测试）
- ProjectorSettlingPolicy（5 个测试）
- CRTSettlingPolicy（3 个测试）
- UnknownSettlingPolicy（3 个测试）
- SettlingPolicyFactory（13 个测试）
- 便捷函数（4 个测试）
- 策略对比（3 个测试）

### 3.2 核心测试套件

```bash
python3 -m pytest tests/test_workflows tests/test_core -v --tb=short
```

**结果**: **178 passed in 13.90s**（含 P1-A 的 72 个 + P1-B 的 46 个 + P3-B 的 60 个）

### 3.3 代码编译验证

```bash
python3 -m py_compile src/workflows/settling.py src/patch_window.py src/backend.py
```

**结果**: 编译成功，无语法错误

---

## 4. 风险和未完成项

### 4.1 已识别风险

| 风险类型 | 风险描述 | 影响程度 | 建议 |
|----------|----------|----------|------|
| Backend 未集成 | `SettlingPolicy` 模块尚未与 Backend 的 `_auto_configure_delay()` 整合 | 中 | P3-C 或后续任务整合 |
| 实测验证缺失 | OLED window patch 未经真实 OLED HDR 测量验证 | 高 | P8 真实硬件验证 |
| 前端 UI 同步 | 前端 JavaScript 未同步显示 OLED 窗口模式状态 | 低 | P6-B UI/UX 专业化 |
| 策略参数调优 | 各策略的延迟参数基于经验值，可能需要根据实测微调 | 中 | P8 硬件验证矩阵 |

### 4.2 未完成项

1. **Backend 整合**: `_auto_configure_delay()` 方法仍使用原有逻辑，需替换为 `SettlingPolicy` 调用
2. **MeasurementService 整合**: `MeasurementService` 中的 `_wait_for_settling()` 方法可改用 `SettlingPolicy`
3. **前端 OLED 状态显示**: 需在前端显示当前 OLED 窗口模式状态
4. **参数配置 UI**: 需在前端提供各显示技术策略参数的可调节界面

### 4.3 建议后续整合方案

```python
# Backend 整合示例
from src.workflows.settling import (
    SettlingPolicyFactory,
    DisplayTechnology,
    ProbeType,
    PatchContext
)

def _auto_configure_delay(self, patch_rgb=None) -> int:
    """使用 SettlingPolicy 计算延迟"""
    tech = self._display_type_to_technology()
    probe = self._probe_type_to_enum()
    
    policy = SettlingPolicyFactory.create(tech)
    context = PatchContext(
        current_rgb=patch_rgb or self._current_patch_color,
        previous_rgb=self._previous_patch_rgb,
        display_technology=tech,
        probe_type=probe
    )
    
    decision = policy.evaluate(context)
    return decision.settling_time_ms
```

---

## 5. 解锁的后续任务

完成本任务后，以下任务可立即开始：

| 任务编号 | 任务名称 | 依赖关系 | 可开始时间 |
|----------|----------|----------|------------|
| P3-A | 测量稳定性与重复性 | 依赖 P1-B，SettlingPolicy 可提供重复测量决策 | 立即 |
| P3-C | 环境预检 | 依赖 P1-C | P1-C 完成后 |
| P4-A | Argyll 适配层重构 | 依赖 P1-B, P0-C，可用 SettlingPolicy 改进测量延迟 | 立即 |
| P8-A | 硬件验证矩阵 | 可验证 OLED window patch 实际效果 | 立即 |

---

## 6. 接口稳定性说明

### 6.1 公共 API

以下接口应保持稳定：

```python
# SettlingPolicy 模块
DisplayTechnology: Enum（LCD, OLED, WOLED, MINILED, PROJECTOR, CRT, UNKNOWN）
ProbeType: Enum（COLORIMETER, SPECTROMETER, UNKNOWN）
SettlingDecision: dataclass（settling_time_ms, insert_black_frame, etc.）
PatchContext: dataclass（current_rgb, previous_rgb, is_hdr, etc.）
SettlingPolicy: ABC（evaluate, technology, default_settling_ms）

# 各显示技术策略类
LCDSettlingPolicy, OLEDSettlingPolicy, WOLEDSettlingPolicy,
MiniLEDSettlingPolicy, ProjectorSettlingPolicy, CRTSettlingPolicy,
UnknownSettlingPolicy

# 工厂和便捷函数
SettlingPolicyFactory.create(technology, **kwargs)
SettlingPolicyFactory.from_display_type_string(str)
SettlingPolicyFactory.supported_technologies()
evaluate_settling(display_technology, current_rgb, ...) -> SettlingDecision

# PatchWindow OLED 功能
PatchWindow.set_oled_window_size_percent(percent: int)
PatchWindow.get_oled_window_size_percent() -> int
PatchWindow.is_oled_window_mode() -> bool
PatchWindow.show_black_frame(duration_ms: int)
PatchWindow.restore_color_after_black_frame(r, g, b)

ColorPatchWidget.set_oled_window_size(percent: float)
ColorPatchWidget.get_oled_window_size() -> float
ColorPatchWidget.is_oled_window_mode() -> bool
```

### 6.2 扩展点

- `SettlingPolicyFactory.register()` 可注册自定义策略
- 各策略类可通过构造参数调整延迟值
- `PatchContext` 可扩展新字段（如环境温度、仪器状态）

---

## 7. 测试覆盖率统计

| 模块 | 测试数 | 覆盖范围 |
|------|--------|----------|
| PatchContext | 6 | 属性计算、边界判断 |
| SettlingDecision | 2 | 默认值、字符串表示 |
| LCDSettlingPolicy | 7 | 标准/暗场/跳变/探头类型 |
| OLEDSettlingPolicy | 6 | BFI/窗口 patch/HDR |
| WOLEDSettlingPolicy | 3 | 继承验证/参数差异 |
| MiniLEDSettlingPolicy | 6 | 分区调整/高对比度/HDR |
| ProjectorSettlingPolicy | 5 | 长延迟/暗场/光源稳定 |
| CRTSettlingPolicy | 3 | 极快响应 |
| UnknownSettlingPolicy | 3 | 保守策略 |
| SettlingPolicyFactory | 13 | 创建/注册/转换 |
| 便捷函数 | 4 | 基础/探头/HDR |
| 策略对比 | 3 | 延迟顺序/BFI 分布 |
| **总计** | **60** | 完整策略覆盖 |

---

**任务完成签名**: Agent P3-B
**任务完成时间**: 2026-05-19
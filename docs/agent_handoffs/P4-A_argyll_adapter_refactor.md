# P4-A: Argyll 适配层重构报告

**任务编号**: P4-A
**执行日期**: 2026-05-19
**任务类型**: Argyll 适配层重构
**依赖文档**: `docs/agent_handoffs/P0-C_argyll_audit.md`, `docs/agent_handoffs/P1-B_measurement_service.md`, `docs/agent_handoffs/P1-C_backend_refactor.md`

---

## 1. 创建的文件列表

| 文件路径 | 行数 | 说明 |
|----------|------|------|
| `/Users/heng/Documents/vscode/Topos Calibrator/src/instruments/argyll_params.py` | 350 | 参数 dataclass 定义，标准化命令构造 |
| `/Users/heng/Documents/vscode/Topos Calibrator/tests/test_instruments/__init__.py` | 1 | 测试模块初始化 |
| `/Users/heng/Documents/vscode/Topos Calibrator/tests/test_instruments/test_argyll_adapter.py` | 796 | 66 个解析和参数测试 |

**修改的文件**:
| 文件路径 | 变更说明 |
|----------|----------|
| `/Users/heng/Documents/vscode/Topos Calibrator/src/instruments/argyll_adapter.py` | 完善 adapter 实现，添加 OutputParser、ProcessLifecycle、参数支持 |
| `/Users/heng/Documents/vscode/Topos Calibrator/src/instruments/__init__.py` | 导出新的参数类和解析器 |

---

## 2. 实现思路

### 2.1 参数类设计（dataclass）

设计 5 个参数 dataclass 来标准化命令构造，避免业务代码散乱拼凑字符串：

```python
@dataclass
class SpotreadParams:
    display_type: DisplayType = DisplayType.LCD
    instrument_port: Optional[int] = None
    correction_file: Optional[str] = None
    emissive_mode: bool = True
    
    def to_command_args(self) -> list: ...
    def validate(self) -> Tuple[bool, str]: ...

@dataclass
class DispcalParams:
    output_path: str
    white_point_xy: Optional[Tuple[float, float]] = None
    white_temp: Optional[int] = None
    gamma: float = 2.2
    use_web_server: bool = False
    ...

@dataclass
class TargenParams:
    output_path: str
    patch_count: int = 1024
    ...

@dataclass
class ColprofParams:
    ti3_path: str
    output_path: str
    quality: QualityLevel = QualityLevel.MEDIUM
    ...

@dataclass
class CollinkParams:
    source_space: str
    target_icc_path: str
    output_path: str
    lut_size: int = 33
    intent: RenderingIntent = RenderingIntent.RELATIVE_COLORIMETRIC
    use_bpc: bool = True  # 注意：感知意图自动禁用 BPC
```

**设计要点**：
- 所有参数类都有 `to_command_args()` 方法，生成 ArgyllCMS 命令参数列表
- 所有参数类都有 `validate()` 方法，检查参数有效性
- 使用 Enum 类型（DisplayType, ProbeType, QualityLevel, RenderingIntent）确保参数合法

### 2.2 输出解析器设计

创建 `OutputParser` 类，提供 5 个解析方法，每个方法返回 `ParseResult`：

```python
class ParseResult:
    success: bool      # 是否成功解析
    data: Dict         # 解析数据（xyz, xyY, cal_file, icc_file 等）
    error: str         # 错误消息（如解析失败）
    progress: int      # 进度百分比（如适用）
    stage: str         # 当前阶段（starting, measuring, complete 等）

class OutputParser:
    @staticmethod
    def parse_spotread(output: str) -> ParseResult: ...
    @staticmethod
    def parse_dispcal(output: str) -> ParseResult: ...
    @staticmethod
    def parse_targen(output: str) -> ParseResult: ...
    @staticmethod
    def parse_colprof(output: str) -> ParseResult: ...
    @staticmethod
    def parse_collink(output: str) -> ParseResult: ...
```

### 2.3 错误消息映射

创建 `ArgyllErrorMapping` dataclass 和 `map_error_to_suggestion()` 函数：

```python
@dataclass
class ArgyllErrorMapping:
    keyword: str           # 错误关键词（如 "ambient filter should be removed"）
    user_message: str      # 用户友好提示（如 "柔光罩未移除..."）
    recoverable: bool      # 是否可恢复
    action: str            # 建议动作（reconnect, calibrate, restart）

DEFAULT_ERROR_MAPPINGS = [
    ArgyllErrorMapping("ambient filter", "柔光罩未移除...", recoverable=True, action="calibrate"),
    ArgyllErrorMapping("no instrument found", "未检测到探头...", recoverable=True, action="reconnect"),
    ArgyllErrorMapping("readpipeasync failed", "USB 设备已断开...", recoverable=True, action="reconnect"),
    ...
]
```

### 2.4 进程生命周期管理

创建 `ProcessLifecycle` 类，统一管理进程状态：

```python
class ProcessLifecycle:
    def __init__(self, timeout=30.0, cancel_timeout=2.0, cleanup_timeout=5.0): ...
    def start(self, process) -> None: ...      # 开始追踪进程
    def is_timeout(self) -> bool: ...          # 检查是否超时
    def cancel(self) -> bool: ...              # 取消进程
    def cleanup(self) -> None: ...             # 清理资源
    def get_elapsed_time(self) -> float: ...   # 获取运行时间
    def is_running(self) -> bool: ...          # 检查是否运行
    @property
    def was_cancelled(self) -> bool: ...       # 是否被用户取消
```

---

## 3. 验证命令和结果

### 3.1 运行测试

```bash
cd "/Users/heng/Documents/vscode/Topos Calibrator"
python3 -m pytest tests/test_instruments/test_argyll_adapter.py -v --tb=short
```

**结果**: **66 passed in 0.25s**

### 3.2 测试用例统计

| 测试类 | 测试数 | 覆盖功能 |
|--------|--------|----------|
| TestSpotreadParsing | 8 | spotread 输出解析（超出要求的 5 个） |
| TestDispcalParsing | 7 | dispcal 输出解析（超出要求的 5 个） |
| TestTargenParsing | 6 | targen 输出解析（超出要求的 5 个） |
| TestColprofParsing | 7 | colprof 输出解析（超出要求的 5 个） |
| TestCollinkParsing | 6 | collink 输出解析（超出要求的 5 个） |
| TestErrorMapping | 8 | 错误消息映射测试 |
| TestSpotreadParams | 4 | SpotreadParams 参数类测试 |
| TestDispcalParams | 5 | DispcalParams 参数类测试 |
| TestCollinkParams | 3 | CollinkParams 参数类测试 |
| TestProcessLifecycle | 3 | 进程生命周期测试 |
| TestArgyllAdapterIntegration | 4 | Adapter 集成测试 |
| TestOutputPatterns | 5 | 正则表达式测试 |

**总计**: 66 个测试，使用 fixture 文件（无硬件依赖）

### 3.3 验证 Fixture 测试

所有测试使用 `tests/fixtures/argyll/` 目录下的 fixture 文件：
- `01_spotread_success.txt` - 成功测量
- `02_spotread_usb_disconnect.txt` - USB 断开
- `03_spotread_ambient_filter_error.txt` - 柔光罩错误
- `04_spotread_no_instrument.txt` - 无设备
- `05_spotread_calibration_failed.txt` - 校准失败
- `06_dispcal_progress.txt` - 校准进度
- `07_dispcal_success.txt` - 校准成功
- `08_targen_output.txt` - 色块生成
- `09_colprof_progress.txt` - Profile 进度
- `10_colprof_success.txt` - Profile 成功
- `11_colprof_failure.txt` - Profile 失败
- `12_collink_success.txt` - LUT 成功
- `13_collink_bpc_error.txt` - BPC 参数错误
- `15_spotread_device_enumeration.txt` - 设备列表

---

## 4. 风险和未完成项

### 4.1 已识别风险

| 风险类型 | 风险描述 | 影响程度 | 建议 |
|----------|----------|----------|------|
| 已有测试失败 | `tests/test_instruments/test_corrections.py` 有 6 个失败 | 低 | 这是已有测试，非本次任务引入 |
| 真实硬件差异 | fixture 是手写样本，可能与真实输出有差异 | 中 | 后续用真实硬件捕获更多样本 |
| 版本兼容性 | fixture 基于 ArgyllCMS v2.2.x/v3.x | 低 | 后续添加版本检测 |

### 4.2 未完成项

1. **ArgyllController 接入**: ArgyllAdapter 当前包装 ArgyllController，尚未修改 Controller 使用参数类
2. **更多 fixture**: 可添加更多边界情况 fixture（如权限错误、驱动缺失）
3. **实际 ti1/ti3 文件**: 可添加实际的 .ti1 和 .ti3 文件样本 fixture

---

## 5. 解锁的后续任务

完成本任务后，以下任务可立即开始：

| 任务编号 | 任务名称 | 依赖关系 | 可开始时间 |
|----------|----------|----------|------------|
| P4-B | ArgyllController 参数类接入 | 依赖 P4-A | 立即 |
| P4-C | ArgyllAdapter 完整集成 | 依赖 P4-A, P4-B | P4-B 完成后 |
| P3-A | 测量稳定性与重复性 | 依赖 P1-B | 立即 |
| P3-B | 显示稳定与延迟策略 | 依赖 P1-B | 立即 |

---

## 6. 接口稳定性说明

### 6.1 公共 API

以下接口应保持稳定：

```python
# 参数类
SpotreadParams: display_type, instrument_port, correction_file, to_command_args(), validate()
DispcalParams: output_path, white_point_xy, white_temp, gamma, use_web_server, to_command_args(), validate()
TargenParams: output_path, patch_count, to_command_args(), validate()
ColprofParams: ti3_path, output_path, quality, to_command_args(), validate()
CollinkParams: source_space, target_icc_path, lut_size, intent, use_bpc, to_command_args(), validate()

# 解析器
OutputParser: parse_spotread(), parse_dispcal(), parse_targen(), parse_colprof(), parse_collink()
ParseResult: success, data, error, progress, stage

# 错误映射
ArgyllErrorMapping: keyword, user_message, recoverable, action
map_error_to_suggestion(error_message)

# 进程生命周期
ProcessLifecycle: start(), cancel(), cleanup(), is_timeout(), is_running(), was_cancelled

# Enums
DisplayType, ProbeType, QualityLevel, RenderingIntent, SourceSpace
```

### 6.2 使用示例

```python
from src.instruments import (
    SpotreadParams, DispcalParams, CollinkParams,
    OutputParser, DisplayType, RenderingIntent,
    map_error_to_suggestion,
)

# 构造参数
params = SpotreadParams(
    display_type=DisplayType.OLED,
    instrument_port=1,
    correction_file="/path/to/ccss.ccss"
)
args = params.to_command_args()  # ['-e', '-d', 'o', '-c', '1', '-X', '/path/...']

# 解析输出
output = "Result is XYZ: 0.123 0.456 0.789"
result = OutputParser.parse_spotread(output)
if result.success:
    print(result.data['xyY'])

# 错误映射
error = "No instrument found"
mapping = map_error_to_suggestion(error)
print(mapping.user_message)  # "未检测到探头..."
```

---

## 7. 设计决策记录

### 7.1 为什么使用 dataclass 而不是 dict

**决策**: 使用 Python dataclass 定义参数类。

**原因**:
- 类型安全：IDE 和静态分析工具可检测类型错误
- 文档清晰：参数名和默认值一目了然
- 验证内置：`validate()` 方法可在构造时检查有效性
- 易于序列化：dataclass 可轻松转换为 dict 用于 checkpoint

### 7.2 为什么感知意图自动禁用 BPC

**问题**: collink 的 `-b` (BPC) 参数与 `-np` (感知意图) 不兼容。

**决策**: `CollinkParams.to_command_args()` 自动处理此互斥。

**原因**:
- ArgyllCMS 会报错：感知意图已包含黑场映射，叠加 BPC 会冲突
- 用户可能不知道此限制，自动处理避免运行时错误
- 参考 fixture `13_collink_bpc_error.txt`

### 7.3 为什么返回 ParseResult 而不是直接返回数据

**决策**: 所有解析方法返回 `ParseResult` 结构体。

**原因**:
- 统一格式：不同工具的解析结果结构一致
- 进度信息：dispcal/colprof/collink 有进度，spotread/targen 无进度
- 错误信息：解析失败时有详细错误描述
- 阶段信息：可区分 "starting", "measuring_patches", "complete" 等

---

**任务完成签名**: Agent P4-A
**任务完成时间**: 2026-05-19
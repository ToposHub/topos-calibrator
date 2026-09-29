# P0-C Argyll 命令与输出夹具审计报告

**任务 ID**: P0-C  
**负责人**: AI Agent  
**完成日期**: 2026-05-19  
**依赖任务**: 无（可独立执行）

---

## 1. 创建的文件列表

### Fixture 目录结构

```
tests/fixtures/argyll/
├── README.md                          # Fixture 使用说明
├── FAKE_ARGYLL_IMPLEMENTATION.md      # Fake Argyll 实现指南
├── 01_spotread_success.txt            # spotread 成功测量
├── 02_spotread_usb_disconnect.txt     # spotread USB 断开
├── 03_spotread_ambient_filter_error.txt # spotread 柔光罩错误
├── 04_spotread_no_instrument.txt      # spotread 仪器未找到
├── 05_spotread_calibration_failed.txt # spotread 校准失败
├── 06_dispcal_progress.txt            # dispcal 校准进度
├── 07_dispcal_success.txt             # dispcal 校准成功
├── 08_targen_output.txt               # targen 色块生成
├── 09_colprof_progress.txt            # colprof 进度输出
├── 10_colprof_success.txt             # colprof 成功
├── 11_colprof_failure.txt             # colprof 失败场景
├── 12_collink_success.txt             # collink 成功
├── 13_collink_bpc_error.txt           # collink BPC 参数错误
├── 14_ccxxmake_success.txt            # ccxxmake 成功
├── 15_spotread_device_enumeration.txt # 设备枚举列表
```

**总计**: 17 个文件（15 个 fixture + 2 个说明文档）

---

## 2. Fixture 文件说明

### spotread 系列 (5 个)

| 文件 | 场景 | 关键输出特征 | 预期解析结果 |
|------|------|-------------|-------------|
| `01_spotread_success.txt` | 成功测量 | `Result is XYZ: 0.033364 0.029912 0.062078` | xyY: (0.2662, 0.2387, 0.029912) |
| `02_spotread_usb_disconnect.txt` | USB 断开 | `readpipeasync failed: (-1) LIBUSB_ERROR_IO` | 触发 `USB_DISCONNECT_KEYWORDS`，自动断开 |
| `03_spotread_ambient_filter_error.txt` | 柔光罩未移除 | `ambient filter should be removed` | 触发 `ERROR_MESSAGE_MAP['ambient filter']` |
| `04_spotread_no_instrument.txt` | 无设备 | `No instrument found` | 连接失败，返回 False |
| `05_spotread_calibration_failed.txt` | 校准失败 | `Calibration failed - out of range` | 返回校准失败，需要重新校准 |

### dispcal 系列 (2 个)

| 文件 | 场景 | 关键输出特征 | 预期解析结果 |
|------|------|-------------|-------------|
| `06_dispcal_progress.txt` | 进度输出 | `patch X of Y`, Web Server URL | 进度 15-70%，URL 正则提取 |
| `07_dispcal_success.txt` | 成功完成 | `Written calibration file 'output.cal'` | .cal 文件存在，返回 True |

### 其他工具系列 (8 个)

| 文件 | 工具 | 场景 | 关键输出特征 |
|------|------|------|-------------|
| `08_targen_output.txt` | targen | 色块生成 | `Created X patches`, `NUMBER_OF_SETS Y` |
| `09_colprof_progress.txt` | colprof | 进度输出 | `Progress: X%`, 阶段信息 |
| `10_colprof_success.txt` | colprof | 成功完成 | `Created profile 'output.icc'` |
| `11_colprof_failure.txt` | colprof | 多种失败 | 文件不存在、数据无效、内存不足 |
| `12_collink_success.txt` | collink | 成功完成 | `Making lookup tables - X% done` |
| `13_collink_bpc_error.txt` | collink | BPC 参数错误 | BPC + 感知意图冲突报错 |
| `14_ccxxmake_success.txt` | ccxxmake | CCMX 成功 | `Created correction matrix` |
| `15_spotread_device_enumeration.txt` | spotread | 设备列表 | `1 = 'hid:111 (i1 DisplayPro)'` |

---

## 3. ArgyllController 审计结果

### 3.1 命令参数审计

审查 `src/argyll_controller.py` 的命令参数构建，结论：**基本符合 ArgyllCMS 预期**。

#### spotread 命令构建 (`_build_command`)

```python
cmd = [spotread_name]
cmd.extend(["-e"])          # 自发光模式 ✓
cmd.extend(["-c", str(port)])  # 设备端口 ✓
cmd.extend(["-d", display_type.value])  # 显示器类型 ✓
cmd.extend(["-X", correction_file])  # 光谱校正文件 ✓
```

**审计结论**: 参数格式正确，符合 ArgyllCMS 官方文档。

#### dispcal 命令构建 (`calibrate_display`)

```python
cmd = [dispcal_path, "-v", "-m"]
cmd.extend(["-dweb:port"])  # Web Server 模式 ✓
cmd.extend(["-c", str(port)])
cmd.extend(["-q", quality])
cmd.extend(["-w", f"{x:.4f},{y:.4f}"])  # 白点坐标 ✓
cmd.extend(["-t", str(white_temp)])  # 色温 ✓
cmd.extend(["-g", str(gamma)])
cmd.extend(["-b", str(brightness)])  # 亮度 ✓
```

**审计结论**: Web Server 模式参数 `-dweb:port` 格式正确（必须紧凑，不能有空格）。

#### collink 命令构建 (`make_3dlut`)

```python
# 已修复的参数互斥逻辑
if intent == 'r':  # 相对色度
    if use_bpc:
        cmd.append("-b")  # 可启用 BPC ✓
elif intent == 'p':  # 感知
    # 强制禁用 BPC，避免报错 ✓
```

**审计结论**: BPC 与渲染意图互斥逻辑已正确处理，避免了 fixture `13_collink_bpc_error.txt` 中的错误。

### 3.2 输出解析审计

#### spotread XYZ 解析

```python
XYZ_PATTERN = re.compile(
    r'Result is XYZ:\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)',
    re.IGNORECASE
)
```

**审计结论**: 正则正确匹配 ArgyllCMS 实际输出格式（空格分隔的 XYZ 值）。

#### dispcal 进度解析

```python
patch_match = re.search(r'patch\s+(\d+)\s+of\s+(\d+)', stripped, re.IGNORECASE)
```

**审计结论**: 正则正确匹配进度输出。

#### colprof 进度解析

```python
progress_match = re.search(r'(?:(?:Progress|Done)[:\s]+)?(\d+)%', stripped, re.IGNORECASE)
```

**审计结论**: 正则可匹配多种进度格式。

### 3.3 发现的问题

#### 问题 1: ccxxmake 交互式死锁（已修复）

`make_ccmx()` 方法已使用延迟注入线程破解 ArgyllCMS 的"清空缓存后等待"机制：

```python
def auto_confirm():
    for _ in range(6):
        time.sleep(0.5)
        if process.poll() is not None:
            break
        process.stdin.write("y\n")
        process.stdin.flush()
```

**状态**: 已修复 ✓

#### 问题 2: collink BPC 参数互斥（已修复）

`make_3dlut()` 方法已正确处理 BPC 与渲染意图的互斥：

- intent='r': 可启用 BPC
- intent='p': 强制禁用 BPC（感知意图已包含黑场映射）
- intent='a': 禁用 BPC（绝对映射无需补偿）

**状态**: 已修复 ✓

#### 问题 3: TTY ioctl 错误刷屏（已处理）

代码已过滤 macOS 的 `tcgetattr failed` / `tcsetattr failed` 错误：

```python
if "tcgetattr failed" in line or "tcsetattr failed" in line:
    continue  # 不打印无害警告
```

**状态**: 已处理 ✓

### 3.4 审计总结

| 检查项 | 状态 | 说明 |
|--------|------|------|
| spotread 命令参数 | ✓ | 格式正确 |
| dispcal 命令参数 | ✓ | Web Server 模式正确 |
| targen 命令参数 | ✓ | 输出文件命名正确 |
| colprof 命令参数 | ✓ | `-yc` 禁用 VCGT 正确 |
| collink 命令参数 | ✓ | BPC 互斥已处理 |
| ccxxmake 命令参数 | ✓ | 交互式确认已处理 |
| spotread 输出解析 | ✓ | XYZ 正则正确 |
| dispcal 输出解析 | ✓ | 进度和 URL 正则正确 |
| colprof 输出解析 | ✓ | 进度正则覆盖多种格式 |
| collink 输出解析 | ✓ | 进度正则正确 |
| ti1/ti3 解析 | ✓ | CGATS 格式解析正确 |
| 设备枚举解析 | ✓ | 设备列表正则正确 |

---

## 4. Fake Argyll 实现建议

详见 `tests/fixtures/argyll/FAKE_ARGYLL_IMPLEMENTATION.md`。

### 推荐方案

采用**混合方案**：

1. **短期（P1-B 开始前）**: 使用 monkeypatch 拦截 `subprocess.Popen`，直接测试现有 `ArgyllController` 的解析逻辑。

2. **中期（P1-B 完成后）**: 使用依赖注入 `InstrumentAdapter` 接口，测试 `MeasurementService` 的业务逻辑。

3. **长期（P4-A 完成后）**: 创建 `ArgyllAdapter` 封装层，两者并存覆盖不同测试层次。

### 核心实现要点

```python
# tests/conftest.py
def load_fixture_output(filename: str) -> str:
    """加载 fixture 文件，过滤注释和 TTY 错误"""
    ...

class FakePopen:
    """模拟 subprocess.Popen"""
    def __init__(self, cmd, **kwargs):
        self._fixture = self._select_fixture(cmd)
        self.stdout = MockStdout(self._fixture.split('\n'))
        self.stdin = MockStdin()
        self.returncode = 0
```

---

## 5. 解锁的后续任务

本任务完成后，以下任务可以开始：

### P1-B 测量服务抽象

- **依赖**: P1-A（状态机）+ P0-C（本任务）
- **解锁内容**: 
  - 可使用 fixture 测试 `MeasurementService` 的测量流程编排
  - 可使用 `FakeInstrumentAdapter` 模拟无硬件测试环境
  - 明确了 `InstrumentAdapter` 接口的测量返回格式 `(x, y, Y)`

### P4-A Argyll 适配层重构

- **依赖**: P1-B + P0-C（本任务）
- **解锁内容**:
  - 可使用 fixture 测试 `ArgyllAdapter` 的命令参数构建
  - 可使用 fixture 测试输出解析逻辑
  - 已有 15 个 fixture 文件覆盖各种场景
  - 已明确 fake Argyll 实现方式

### P7-A 测试体系

- **依赖**: P1 + P2 + P0-C（本任务）
- **解锁内容**:
  - 已有 fixture 文件可用于单元测试
  - 已有 fake Argyll 实现说明
  - 可开始编写 pytest 测试配置

---

## 6. 验证命令

```bash
# 检查 fixture 目录结构
ls -la tests/fixtures/argyll/

# 验证 fixture 文件数量
find tests/fixtures/argyll -name "*.txt" | wc -l
# 预期: 15

# 验证代码可编译（不破坏现有功能）
python3 -m py_compile src/argyll_controller.py

# 验证 fixture 格式正确
head -20 tests/fixtures/argyll/01_spotread_success.txt
```

---

## 7. 风险与未完成项

### 风险

1. **真实硬件差异**: fixture 是手写样本，可能与真实 ArgyllCMS 输出有细微差异。建议后续用真实硬件捕获更多输出样本。

2. **版本兼容性**: fixture 基于 ArgyllCMS v2.2.x/v3.x，不同版本的输出格式可能有差异。

3. **线程同步**: spotread 使用后台线程读取输出，monkeypatch 测试需要处理线程同步问题。

### 未完成项

1. **更多错误场景**: 当前 fixture 覆盖了主要场景，但可添加更多边界情况（如权限错误、驱动缺失等）。

2. **多设备测试**: fixture `15_spotread_device_enumeration.txt` 只有一种设备列表格式，可添加更多变体。

3. **实际 ti1/ti3 文件**: 当前 fixture 只有输出文本，可添加实际的 .ti1 和 .ti3 文件样本。

---

## 8. 附录：正则表达式汇总

```python
# spotread XYZ 解析
XYZ_PATTERN = r'Result is XYZ:\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)'

# spotread Yxy 解析（备用）
YXY_PATTERN = r'Yxy:\s*Y\s*=\s*([\d.]+),\s*x\s*=\s*([\d.]+),\s*y\s*=\s*([\d.]+)'

# dispcal 进度
DISPCAL_PROGRESS = r'patch\s+(\d+)\s+of\s+(\d+)'

# dispcal Web Server URL
DISPCAL_URL = r"'(http://[^']+)'"

# colprof/collink 进度
PROGRESS = r'(?:(?:Progress|Done)[:\s]+)?(\d+)%'
COLLINK_PROGRESS = r'Making lookup tables - (\d+)% done'

# targen 色块数量
TARGET_PATCHES = r'Created\s+(\d+)\s+patches'
TI1_COUNT = r'NUMBER_OF_SETS\s+(\d+)'

# 设备枚举
DEVICE_ENUM = r"^\s*(\d+)\s*=\s*['\"]?([^'\"\n]+)['\"]?\s*$"
```

---

**报告完成。后续 Agent 可直接使用本报告和 fixture 文件开始 P1-B 和 P4-A 任务。**
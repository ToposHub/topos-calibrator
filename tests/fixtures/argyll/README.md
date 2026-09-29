# ArgyllCMS 输出 Fixture 目录

本目录包含 ArgyllCMS 工具的典型输出样本，用于测试 `src/argyll_controller.py` 的命令参数和输出解析逻辑。

## 目录结构

```
tests/fixtures/argyll/
├── README.md                          # 本文件
├── FAKE_ARGYLL_IMPLEMENTATION.md      # Fake Argyll 实现说明
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

## Fixture 文件格式

每个 fixture 文件使用注释格式：

```text
# Fixture: <标题>
# 来源: <来源说明>
# 工具版本: ArgyllCMS vX.X
# 命令: <实际命令>

# ========== 输出内容 ==========
<实际输出内容>

# ========== 预期解析结果 ==========
<解析正则和提取值说明>
```

## Fixture 文件列表

| 文件 | 工具 | 场景 | 关键检测点 |
|------|------|------|-----------|
| 01_spotread_success.txt | spotread | 成功测量 | `Result is XYZ:` 正则匹配 |
| 02_spotread_usb_disconnect.txt | spotread | USB 断开 | `readpipeasync failed` USB 错误 |
| 03_spotread_ambient_filter_error.txt | spotread | 柔光罩错误 | `ambient filter should be removed` |
| 04_spotread_no_instrument.txt | spotread | 无设备 | `No instrument found` |
| 05_spotread_calibration_failed.txt | spotread | 校准失败 | `Calibration failed` |
| 06_dispcal_progress.txt | dispcal | 进度输出 | `patch X of Y` 进度正则 |
| 07_dispcal_success.txt | dispcal | 成功完成 | `Written calibration file` |
| 08_targen_output.txt | targen | 色块生成 | `Created X patches` |
| 09_colprof_progress.txt | colprof | 进度输出 | `Progress: X%` |
| 10_colprof_success.txt | colprof | 成功完成 | `Created profile` |
| 11_colprof_failure.txt | colprof | 失败场景 | `Error:` + `Fatal error` |
| 12_collink_success.txt | collink | 成功完成 | `Making lookup tables - X% done` |
| 13_collink_bpc_error.txt | collink | 参数错误 | BPC + 感知意图冲突 |
| 14_ccxxmake_success.txt | ccxxmake | 成功完成 | `Created correction matrix` |
| 15_spotread_device_enumeration.txt | spotread | 设备列表 | `序号 = '设备信息'` 正则 |

## 使用方式

### 方案一：monkeypatch 拦截 subprocess.Popen

```python
import subprocess
from unittest.mock import MagicMock, patch

def load_fixture(filename):
    """加载 fixture 文件内容"""
    path = Path(__file__).parent / "fixtures" / "argyll" / filename
    with open(path, 'r') as f:
        # 过滤注释行，提取实际输出
        lines = []
        for line in f:
            if not line.startswith('#') and line.strip():
                lines.append(line)
        return ''.join(lines)

class FakePopen:
    """模拟 subprocess.Popen"""
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.returncode = 0
        # 根据 cmd 选择对应的 fixture
        tool = cmd[0].split('/')[-1].replace('.exe', '')
        self.stdout = MagicMock()
        self.stderr = MagicMock()
        self.stdin = MagicMock()

        # 设置预设输出
        if 'spotread' in tool:
            self._output = load_fixture('01_spotread_success.txt')
        elif 'dispcal' in tool:
            self._output = load_fixture('07_dispcal_success.txt')
        # ... 其他工具

    def poll(self):
        return self.returncode is not None

    def communicate(self, timeout=None):
        return (self._output, '')

    def wait(self, timeout=None):
        return self.returncode

@patch('subprocess.Popen', FakePopen)
def test_spotread_connect():
    controller = ArgyllController()
    assert controller.connect() == True
```

### 方案二：依赖注入替换 ArgyllController

```python
class FakeArgyllController:
    """Fake ArgyllController 用于无硬件测试"""

    def __init__(self, fixture_dir='tests/fixtures/argyll'):
        self.fixture_dir = fixture_dir
        self._is_connected = False
        self._measurements = []

    def connect(self):
        self._is_connected = True
        return True

    def disconnect(self):
        self._is_connected = False

    def measure(self):
        if not self._is_connected:
            return False
        # 从 fixture 加载预设测量结果
        output = self._load_fixture('01_spotread_success.txt')
        xyz = self._parse_xyz(output)
        self._measurements.append(xyz)
        return True

    def get_last_measurement(self):
        return self._measurements[-1] if self._measurements else None

# 在测试中使用
def test_measurement_workflow():
    controller = FakeArgyllController()
    # ... 测试流程
```

## 注意事项

1. **TTY 错误过滤**：ArgyllCMS 在 macOS 上会输出 `tcgetattr failed` / `tcsetattr failed` 错误，这是无害的终端 ioctl 警告，测试时需要过滤。

2. **stderr 合并**：`argyll_controller.py` 使用 `stderr=subprocess.STDOUT`，所以 fixture 中只需要模拟 stdout。

3. **交互式命令**：spotread、dispcal、ccxxmake 等工具是交互式的，需要模拟 stdin.write() 和 stdin.flush()。

4. **异步读取**：spotread 使用后台线程读取输出，测试时需要处理线程同步。
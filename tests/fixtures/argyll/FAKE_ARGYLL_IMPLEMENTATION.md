# Fake Argyll 实现说明

本文档说明如何在测试中使用 fake Argyll 实现来模拟 ArgyllCMS 工具的行为，无需真实硬件。

## 目标

1. **P1-B 测量服务测试**：测试测量流程编排逻辑，不依赖真实探头
2. **P4-A Argyll 适配层测试**：测试命令参数构建和输出解析逻辑

## 实现方案

### 方案一：monkeypatch 拦截 subprocess.Popen

**优点**：
- 不需要修改现有 ArgyllController
- 直接拦截系统调用，测试覆盖率最高
- 可以精确控制每次调用的行为

**缺点**：
- 需要处理线程同步（spotread 使用后台读取线程）
- 需要模拟 stdin/stdout 的交互式读写

**适用场景**：
- 测试 ArgyllController 的内部解析逻辑
- 测试错误处理和重连机制

**实现示例**：

```python
# tests/conftest.py
import subprocess
import threading
import queue
from pathlib import Path
from unittest.mock import MagicMock, patch
import time

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "argyll"

def load_fixture_output(filename: str) -> str:
    """加载 fixture 文件，过滤注释行"""
    path = FIXTURE_DIR / filename
    with open(path, 'r') as f:
        output_lines = []
        for line in f:
            stripped = line.strip()
            # 过滤注释行和空行
            if stripped.startswith('#') or not stripped:
                continue
            # 过滤 TTY 错误（测试中不需要）
            if 'tcgetattr' in stripped or 'tcsetattr' in stripped:
                continue
            output_lines.append(line.rstrip('\n'))
        return '\n'.join(output_lines) + '\n'

class MockStdout:
    """模拟 Popen.stdout 的 readline() 行为"""
    def __init__(self, output_lines: list):
        self._lines = output_lines
        self._index = 0

    def readline(self):
        if self._index < len(self._lines):
            line = self._lines[self._index] + '\n'
            self._index += 1
            return line
        return ''  # EOF

    def read(self):
        remaining = '\n'.join(self._lines[self._index:]) + '\n'
        self._index = len(self._lines)
        return remaining

class MockStdin:
    """模拟 Popen.stdin"""
    def __init__(self):
        self._buffer = []

    def write(self, data):
        self._buffer.append(data)

    def flush(self):
        pass

class FakePopen:
    """模拟 subprocess.Popen"""
    def __init__(self, cmd, stdin=None, stdout=None, stderr=None,
                 text=False, bufsize=-1, **kwargs):
        self.cmd = cmd
        self._returncode = None

        # 根据命令选择 fixture
        self._fixture = self._select_fixture(cmd)
        self._output_lines = self._fixture.split('\n')

        # 模拟 stdin/stdout/stderr
        self.stdin = MockStdin()
        self.stdout = MockStdout(self._output_lines)
        self.stderr = subprocess.PIPE if stderr == subprocess.STDOUT else MockStdout([])

        # 用于测试控制
        self._poll_count = 0

    def _select_fixture(self, cmd: list) -> str:
        """根据命令选择对应的 fixture"""
        tool_name = cmd[0].split('/')[-1].replace('.exe', '')

        # spotread
        if 'spotread' in tool_name:
            # 检查是否是设备枚举
            if '-c' in cmd and '?' in cmd:
                return load_fixture_output('15_spotread_device_enumeration.txt')
            return load_fixture_output('01_spotread_success.txt')

        # dispcal
        if 'dispcal' in tool_name:
            return load_fixture_output('07_dispcal_success.txt')

        # targen
        if 'targen' in tool_name:
            return load_fixture_output('08_targen_output.txt')

        # colprof
        if 'colprof' in tool_name:
            return load_fixture_output('10_colprof_success.txt')

        # collink
        if 'collink' in tool_name:
            return load_fixture_output('12_collink_success.txt')

        # ccxxmake
        if 'ccxxmake' in tool_name:
            return load_fixture_output('14_ccxxmake_success.txt')

        return ''

    def poll(self):
        """模拟进程状态检查"""
        self._poll_count += 1
        # 在读取完所有输出后"退出"
        if self._poll_count > len(self._output_lines):
            self._returncode = 0
        return self._returncode

    def wait(self, timeout=None):
        self._returncode = 0
        return self._returncode

    def communicate(self, input=None, timeout=None):
        """模拟 communicate() 方法"""
        if input:
            self.stdin.write(input)
        output = self._fixture
        self._returncode = 0
        return (output, '')

    def terminate(self):
        self._returncode = -15

    def kill(self):
        self._returncode = -9

@pytest.fixture
def mock_subprocess_popen():
    """pytest fixture: 拦截 subprocess.Popen"""
    with patch('subprocess.Popen', FakePopen):
        yield FakePopen
```

### 方案二：依赖注入 InstrumentAdapter 接口

**优点**：
- 符合 P1-B 的架构设计
- 可以完全控制测量流程行为
- 不需要处理 subprocess 细节

**缺点**：
- 需要先完成 P1-A 状态机和 P1-B 接口抽象
- 需要修改现有代码（但这是计划中的重构）

**适用场景**：
- 测试测量服务（MeasurementService）的业务逻辑
- 测试工作流编排

**接口定义**（P1-B 实现）：

```python
# src/instruments/base.py
from abc import ABC, abstractmethod
from typing import Optional, Tuple, Callable
from enum import Enum

class InstrumentState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    MEASURING = "measuring"
    ERROR = "error"

class InstrumentAdapter(ABC):
    """仪器适配器接口"""
    
    @abstractmethod
    def connect(self) -> bool:
        """连接仪器"""
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """断开仪器"""
        pass
    
    @abstractmethod
    def calibrate(self) -> bool:
        """校准仪器"""
        pass
    
    @abstractmethod
    def measure(self) -> Optional[Tuple[float, float, float]]:
        """执行测量，返回 (x, y, Y)"""
        pass
    
    @abstractmethod
    def get_state(self) -> InstrumentState:
        """获取当前状态"""
        pass
    
    @abstractmethod
    def set_callbacks(self, on_measurement: Callable, on_error: Callable):
        """设置回调"""
        pass
```

**Fake 实现**：

```python
# tests/fakes/fake_instrument.py
from src.instruments.base import InstrumentAdapter, InstrumentState
from tests.fixtures.argyll import load_fixture_output

class FakeInstrumentAdapter(InstrumentAdapter):
    """Fake 仪器适配器用于测试"""
    
    def __init__(self, fixture: str = '01_spotread_success.txt'):
        self._fixture = fixture
        self._state = InstrumentState.DISCONNECTED
        self._measurements = []
        self._on_measurement = None
        self._on_error = None
        self._measure_count = 0
    
    def connect(self) -> bool:
        self._state = InstrumentState.CONNECTING
        # 模拟连接延迟
        time.sleep(0.1)
        self._state = InstrumentState.READY
        return True
    
    def disconnect(self) -> None:
        self._state = InstrumentState.DISCONNECTED
    
    def calibrate(self) -> bool:
        if self._state != InstrumentState.READY:
            return False
        return True
    
    def measure(self) -> Optional[Tuple[float, float, float]]:
        if self._state != InstrumentState.READY:
            return None
        
        self._state = InstrumentState.MEASURING
        
        # 从 fixture 解析预设结果
        output = load_fixture_output(self._fixture)
        xyz_match = re.search(
            r'Result is XYZ:\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)',
            output
        )
        if xyz_match:
            X = float(xyz_match.group(1))
            Y = float(xyz_match.group(2))
            Z = float(xyz_match.group(3))
            # XYZ -> xyY
            sum_xyz = X + Y + Z
            x = X / sum_xyz
            y = Y / sum_xyz
            result = (x, y, Y)
            self._measurements.append(result)
            
            # 触发回调
            if self._on_measurement:
                self._on_measurement(result)
            
            self._measure_count += 1
            
            # 模拟测量延迟
            time.sleep(0.05)
            
            self._state = InstrumentState.READY
            return result
        
        self._state = InstrumentState.ERROR
        if self._on_error:
            self._on_error("解析失败")
        return None
    
    def get_state(self) -> InstrumentState:
        return self._state
    
    def set_callbacks(self, on_measurement, on_error):
        self._on_measurement = on_measurement
        self._on_error = on_error
    
    # === 测试辅助方法 ===
    
    def set_error_fixture(self, fixture: str):
        """切换到错误 fixture"""
        self._fixture = fixture
    
    def get_measure_count(self) -> int:
        """获取测量次数"""
        return self._measure_count
```

### 方案三：混合方案（推荐）

结合方案一和方案二：

1. **短期（P1-B 开始前）**：使用 monkeypatch 测试现有 ArgyllController
2. **中期（P1-B 完成后）**：使用依赖注入测试 MeasurementService
3. **长期（P4-A 完成后）**：两者并存，覆盖不同测试层次

```python
# tests/test_argyll_parser.py - 使用 monkeypatch
@patch('subprocess.Popen', FakePopen)
def test_spotread_parse_xyz():
    controller = ArgyllController()
    controller.connect()
    # 测试解析逻辑

# tests/test_measurement_service.py - 使用依赖注入
def test_measurement_workflow():
    instrument = FakeInstrumentAdapter()
    service = MeasurementService(instrument)
    # 测试业务逻辑
```

## 测试示例

```python
# tests/test_argyll_parser.py
import pytest
from unittest.mock import patch
from src.argyll_controller import ArgyllController

class TestSpotreadParser:
    """测试 spotread 输出解析"""
    
    @patch('subprocess.Popen')
    def test_parse_xyz_success(self, mock_popen):
        """测试成功测量结果的 XYZ 解析"""
        # 设置 fixture 输出
        mock_popen.return_value = FakePopen(['spotread', '-e'])
        
        controller = ArgyllController()
        # 直接测试解析方法
        output = load_fixture_output('01_spotread_success.txt')
        result = controller._parse_measurement(output)
        
        assert result is not None
        x, y, Y = result
        # 验证 xyY 转换
        assert abs(x - 0.2662) < 0.001
        assert abs(y - 0.2387) < 0.001
        assert abs(Y - 0.029912) < 0.001
    
    def test_detect_usb_disconnect(self):
        """测试 USB 断开关键词检测"""
        output = load_fixture_output('02_spotread_usb_disconnect.txt')
        
        controller = ArgyllController()
        # 检测 USB 断开关键词
        is_disconnect = any(
            keyword in output.lower()
            for keyword in ['readpipeasync failed', 'usb error']
        )
        assert is_disconnect
    
    def test_detect_ambient_filter_error(self):
        """测试柔光罩错误检测"""
        output = load_fixture_output('03_spotread_ambient_filter_error.txt')
        
        controller = ArgyllController()
        # 检测柔光罩关键词
        has_filter_error = 'ambient filter' in output.lower()
        assert has_filter_error
        # 获取友好提示
        friendly_msg = controller.ERROR_MESSAGE_MAP.get('ambient filter should be removed')
        assert '柔光罩' in friendly_msg

class TestDispcalParser:
    """测试 dispcal 输出解析"""
    
    def test_parse_progress(self):
        """测试进度解析"""
        output = load_fixture_output('06_dispcal_progress.txt')
        
        # 提取进度信息
        import re
        matches = re.findall(r'patch\s+(\d+)\s+of\s+(\d+)', output)
        assert len(matches) > 0
        current, total = matches[0]
        assert int(current) > 0
        assert int(total) > 0
    
    def test_detect_web_server_url(self):
        """测试 Web Server URL 解析"""
        output = load_fixture_output('06_dispcal_progress.txt')
        
        import re
        url_match = re.search(r"'(http://[^']+)'", output)
        assert url_match is not None
        url = url_match.group(1)
        assert url.startswith('http://')

class TestColprofParser:
    """测试 colprof 输出解析"""
    
    def test_parse_progress_percentage(self):
        """测试百分比进度解析"""
        output = load_fixture_output('09_colprof_progress.txt')
        
        import re
        matches = re.findall(r'(?:(?:Progress|Done)[:\s]+)?(\d+)%', output)
        assert len(matches) > 0
        progress_values = [int(m) for m in matches]
        assert max(progress_values) == 100

class TestCollinkParser:
    """测试 collink 输出解析"""
    
    def test_detect_bpc_error(self):
        """测试 BPC 参数错误检测"""
        output = load_fixture_output('13_collink_bpc_error.txt')
        
        # 检测错误关键词
        has_bpc_error = 'Black point compensation' in output and 'cannot be used' in output
        assert has_bpc_error
```

## 推荐实现路径

1. **立即**：创建 `tests/conftest.py` 实现 `load_fixture_output()` 和 `FakePopen`
2. **P1-B 开始时**：创建 `src/instruments/base.py` 定义接口
3. **P1-B 完成后**：创建 `tests/fakes/fake_instrument.py` 实现 FakeInstrumentAdapter
4. **P4-A 完成后**：添加更多 fixture 和测试覆盖 ArgylAdapter
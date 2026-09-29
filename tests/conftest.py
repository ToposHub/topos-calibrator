"""
Pytest 配置和共享 fixtures

为 Topos Calibrator 测试提供：
- Argyll 输出 fixture 加载
- Mock subprocess（用于无硬件测试）
- Mock instrument 适配器
- 临时测试目录

参考: docs/agent_handoffs/P0-C_argyll_audit.md
"""

import os
import sys
import tempfile
import threading
import time
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional
from unittest.mock import MagicMock, Mock, patch

import pytest

# 将项目根目录添加到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ========== Fixture 目录路径 ==========
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
ARGYLL_FIXTURES_DIR = FIXTURES_DIR / "argyll"


# ========== Argyll Fixture 加载工具 ==========

def load_argyll_fixture(filename: str) -> str:
    """
    加载 Argyll 输出 fixture 文件内容。
    
    Args:
        filename: fixture 文件名，如 "01_spotread_success.txt"
    
    Returns:
        fixture 文件内容
    
    Raises:
        FileNotFoundError: fixture 文件不存在
    """
    fixture_path = ARGYLL_FIXTURES_DIR / filename
    if not fixture_path.exists():
        raise FileNotFoundError(f"Argyll fixture not found: {fixture_path}")
    return fixture_path.read_text(encoding="utf-8")


def get_argyll_fixture_path(filename: str) -> Path:
    """
    获取 Argyll fixture 文件路径。
    
    Args:
        filename: fixture 文件名
    
    Returns:
        fixture 文件完整路径
    """
    return ARGYLL_FIXTURES_DIR / filename


# ========== Mock Subprocess 类 ==========

class MockPopen:
    """
    模拟 subprocess.Popen 的 Mock 类。
    
    根据 P0-C 审计报告，用于测试 ArgyllController 的输出解析逻辑。
    """
    
    # 命令关键词到 fixture 文件的映射
    COMMAND_FIXTURE_MAP = {
        "spotread": "01_spotread_success.txt",
        "dispcal": "07_dispcal_success.txt",
        "targen": "08_targen_output.txt",
        "colprof": "10_colprof_success.txt",
        "collink": "12_collink_success.txt",
        "ccxxmake": "14_ccxxmake_success.txt",
    }
    
    def __init__(
        self,
        cmd: List[str],
        stdout: Any = None,
        stderr: Any = None,
        stdin: Any = None,
        text: bool = True,
        **kwargs,
    ):
        """初始化 Mock Popen"""
        self.cmd = cmd
        self._cmd_name = self._extract_cmd_name(cmd)
        
        # 确定 fixture 文件
        fixture_file = self._select_fixture(cmd)
        
        # 加载 fixture 内容
        self._fixture_content = ""
        if fixture_file:
            try:
                self._fixture_content = load_argyll_fixture(fixture_file)
            except FileNotFoundError:
                pass
        
        # 模拟流输出
        self._output_lines = self._fixture_content.strip().split("\n")
        self._output_index = 0
        
        # 设置标准流
        self.stdout = self._create_mock_stdout() if stdout == -1 else stdout
        self.stderr = MagicMock() if stderr == -1 else stderr
        self.stdin = MagicMock() if stdin else None
        
        self.returncode = 0
        self.pid = 12345
        self._terminated = False
        self._killed = False
    
    def _extract_cmd_name(self, cmd: List[str]) -> str:
        """从命令中提取工具名称"""
        if not cmd:
            return ""
        # 获取命令路径的最后一个部分
        cmd_path = cmd[0].lower()
        for name in ["spotread", "dispcal", "targen", "colprof", "collink", "ccxxmake"]:
            if name in cmd_path:
                return name
        return ""
    
    def _select_fixture(self, cmd: List[str]) -> Optional[str]:
        """根据命令选择 fixture 文件"""
        for keyword, fixture in self.COMMAND_FIXTURE_MAP.items():
            if keyword in " ".join(cmd).lower():
                return fixture
        return None
    
    def _create_mock_stdout(self) -> MagicMock:
        """创建模拟 stdout"""
        mock_stdout = MagicMock()
        
        def readlines():
            return self._output_lines
        
        def readline():
            if self._output_index < len(self._output_lines):
                line = self._output_lines[self._output_index]
                self._output_index += 1
                return line
            return ""
        
        mock_stdout.readlines = readlines
        mock_stdout.readline = readline
        mock_stdout.__iter__ = lambda self: iter(self._output_lines)
        
        return mock_stdout
    
    def poll(self) -> Optional[int]:
        """检查进程状态"""
        return None if not self._terminated else self.returncode
    
    def wait(self, timeout: Optional[float] = None) -> int:
        """等待进程结束"""
        self._terminated = True
        return self.returncode
    
    def terminate(self) -> None:
        """终止进程"""
        self._terminated = True
    
    def kill(self) -> None:
        """杀死进程"""
        self._killed = True
        self._terminated = True
    
    def communicate(self, input: Optional[bytes] = None, timeout: Optional[float] = None) -> tuple:
        """与进程交互"""
        return (self._fixture_content, "")


class MockPopenFactory:
    """
    Mock Popen 工厂类。
    
    用于创建可配置的 Mock Popen 实例，支持：
    - 自定义输出内容
    - 模拟错误场景
    - 模拟进度输出
    """
    
    def __init__(self):
        self._custom_fixtures: Dict[str, str] = {}
        self._custom_returncodes: Dict[str, int] = {}
        self._calls: List[List[str]] = []
    
    def set_fixture(self, cmd_keyword: str, content: str, returncode: int = 0) -> None:
        """设置特定命令的自定义 fixture"""
        self._custom_fixtures[cmd_keyword] = content
        self._custom_returncodes[cmd_keyword] = returncode
    
    def create_popen(self, cmd: List[str], **kwargs) -> MockPopen:
        """创建 Mock Popen 实例"""
        self._calls.append(cmd)
        
        popen = MockPopen(cmd, **kwargs)
        
        # 应用自定义 fixture
        for keyword, content in self._custom_fixtures.items():
            if keyword in " ".join(cmd).lower():
                popen._fixture_content = content
                popen._output_lines = content.strip().split("\n")
                popen._output_index = 0
                popen.returncode = self._custom_returncodes.get(keyword, 0)
                break
        
        return popen
    
    @property
    def calls(self) -> List[List[str]]:
        """获取所有调用记录"""
        return self._calls
    
    def reset(self) -> None:
        """重置工厂状态"""
        self._custom_fixtures.clear()
        self._custom_returncodes.clear()
        self._calls.clear()


# ========== Fixtures ==========

@pytest.fixture
def project_root() -> Path:
    """项目根目录"""
    return PROJECT_ROOT


@pytest.fixture
def fixtures_dir() -> Path:
    """Fixture 目录路径"""
    return FIXTURES_DIR


@pytest.fixture
def argyll_fixtures_dir() -> Path:
    """Argyll fixture 目录路径"""
    return ARGYLL_FIXTURES_DIR


@pytest.fixture
def load_fixture() -> Callable[[str], str]:
    """加载 Argyll fixture 的函数 fixture"""
    return load_argyll_fixture


@pytest.fixture
def mock_popen_factory() -> MockPopenFactory:
    """Mock Popen 工厂 fixture"""
    return MockPopenFactory()


@pytest.fixture
def mock_subprocess(mock_popen_factory: MockPopenFactory):
    """
    Mock subprocess.Popen 的 fixture。
    
    使用方法：
        def test_something(mock_subprocess):
            mock_subprocess.set_fixture("spotread", "custom output")
            # 测试代码...
            assert "spotread" in str(mock_subprocess.calls)
    """
    with patch("subprocess.Popen", side_effect=mock_popen_factory.create_popen):
        yield mock_popen_factory


@pytest.fixture
def mock_instrument():
    """
    Mock 测量仪器 fixture。
    
    提供模拟的仪器连接和测量功能。
    """
    instrument = MagicMock()
    instrument.connect.return_value = True
    instrument.disconnect.return_value = None
    instrument.measure.return_value = (0.3127, 0.3290, 100.0)  # D65 白点
    instrument.calibrate.return_value = True
    instrument.status.return_value = {"connected": True, "model": "i1 Display Pro"}
    return instrument


@pytest.fixture
def mock_display():
    """
    Mock 显示器 fixture。
    
    提供模拟的显示器和色块显示功能。
    """
    display = MagicMock()
    display.show_rgb.return_value = None
    display.hide.return_value = None
    display.target_display_id.return_value = 0
    display.width = 1920
    display.height = 1080
    return display


@pytest.fixture
def temp_session_dir() -> Generator[Path, None, None]:
    """
    临时会话目录 fixture。
    
    创建临时目录用于测试会话数据存储。
    测试结束后自动清理。
    """
    with tempfile.TemporaryDirectory(prefix="topos_test_") as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_ti3_file(temp_session_dir: Path) -> Path:
    """
    创建临时 TI3 文件 fixture。
    """
    ti3_content = """CTI3

DESCRIPTOR "Argyll Calibration Target chart information 3"
ORIGINATOR "Topos Calibrator Test"
KEYWORD "SAMPLE_ID"
KEYWORD "RGB_R"
KEYWORD "RGB_G"  
KEYWORD "RGB_B"
KEYWORD "XYZ_X"
KEYWORD "XYZ_Y"
KEYWORD "XYZ_Z"
NUMBER_OF_FIELDS 7
BEGIN_DATA_FORMAT
SAMPLE_ID RGB_R RGB_G RGB_B XYZ_X XYZ_Y XYZ_Z
END_DATA_FORMAT
NUMBER_OF_SETS 3
BEGIN_DATA
1 100.0 100.0 100.0 95.047 100.000 108.883
2 0.0 0.0 0.0 0.0 0.0 0.0
3 100.0 0.0 0.0 41.24 21.26 1.93
END_DATA
"""
    ti3_path = temp_session_dir / "test.ti3"
    ti3_path.write_text(ti3_content)
    return ti3_path


@pytest.fixture
def sample_measurement_data() -> Dict[str, Any]:
    """
    示例测量数据 fixture。
    
    提供标准格式的测量数据用于测试数据分析和报告生成。
    """
    return {
        "white_point": {"x": 0.3127, "y": 0.3290, "Y": 100.0},
        "black_point": {"x": 0.3127, "y": 0.3290, "Y": 0.05},
        "gray_ramp": [
            {"level": 0, "Y": 0.05, "x": 0.3127, "y": 0.3290},
            {"level": 25, "Y": 2.5, "x": 0.3130, "y": 0.3295},
            {"level": 50, "Y": 18.0, "x": 0.3132, "y": 0.3298},
            {"level": 75, "Y": 50.0, "x": 0.3129, "y": 0.3292},
            {"level": 100, "Y": 100.0, "x": 0.3127, "y": 0.3290},
        ],
        "primaries": {
            "red": {"x": 0.640, "y": 0.330, "Y": 21.26},
            "green": {"x": 0.300, "y": 0.600, "Y": 71.52},
            "blue": {"x": 0.150, "y": 0.060, "Y": 7.22},
        },
    }


# ========== Pytest 钩子 ==========

def pytest_configure(config: pytest.Config) -> None:
    """Pytest 配置钩子"""
    # 注册测试分层 markers
    config.addinivalue_line(
        "markers", "unit: 不依赖 GUI/硬件/打包的快速单元测试"
    )
    config.addinivalue_line(
        "markers", "workflow: fake adapter 下跑 workflow 测试"
    )
    config.addinivalue_line(
        "markers", "integration: 可依赖 Argyll fake 或本机工具的集成测试"
    )
    config.addinivalue_line(
        "markers", "package: 依赖 dist app 的打包测试"
    )
    config.addinivalue_line(
        "markers", "hardware: 真实设备手动/实验室执行测试"
    )
    # 兼容旧 markers
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "gui: marks tests requiring GUI/display"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: List[pytest.Item]) -> None:
    """修改测试收集钩子"""
    # 为需要 GUI 的测试添加跳过条件
    skip_gui = pytest.mark.skip(reason="GUI tests require display (set DISPLAY env)")
    skip_hardware = pytest.mark.skip(reason="Hardware tests require physical instrument")
    skip_package = pytest.mark.skip(reason="Package tests require built dist app")

    for item in items:
        # 检查 GUI 测试
        if "gui" in item.keywords:
            if not os.environ.get("DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
                item.add_marker(skip_gui)

        # 检查硬件测试
        if "hardware" in item.keywords:
            if not os.environ.get("TOPOS_HARDWARE_TEST"):
                item.add_marker(skip_hardware)

        # 检查打包测试
        if "package" in item.keywords:
            if not os.environ.get("TOPOS_PACKAGE_TEST"):
                item.add_marker(skip_package)


# ========== 命令行选项 ==========

def pytest_addoption(parser: pytest.Parser) -> None:
    """添加命令行选项"""
    parser.addoption(
        "--run-hardware",
        action="store_true",
        default=False,
        help="Run tests requiring physical hardware",
    )
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run slow tests",
    )
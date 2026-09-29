"""
基础测试 - 验证测试框架可工作

测试内容：
- pytest 配置正确加载
- fixtures 可正常使用
- 项目模块可导入
- 基本功能验证

验收标准：
- pytest 可在无 GUI/无硬件环境通过
"""

import sys
from pathlib import Path

import pytest


# ========== 测试框架验证 ==========

class TestPytestFramework:
    """验证 pytest 框架正常工作"""
    
    def test_pytest_minimal(self):
        """最简单的 pytest 测试"""
        assert True
    
    def test_pytest_assertion(self):
        """pytest 断言测试"""
        value = 1 + 1
        assert value == 2
    
    def test_pytest_exception_handling(self):
        """pytest 异常处理测试"""
        with pytest.raises(ValueError):
            raise ValueError("test exception")
    
    def test_pytest_fixture_available(self, project_root: Path):
        """验证 fixture 可加载"""
        assert project_root.exists()
        assert project_root.is_dir()


class TestFixtures:
    """验证 fixtures 正常工作"""
    
    def test_project_root_fixture(self, project_root: Path):
        """验证 project_root fixture（目录名随仓库更名调整过，做包含性断言）"""
        assert project_root.name.lower().replace("-", "").replace(" ", "") == "toposcalibrator"
    
    def test_fixtures_dir_fixture(self, fixtures_dir: Path):
        """验证 fixtures_dir fixture"""
        assert fixtures_dir.exists()
        assert fixtures_dir.name == "fixtures"
    
    def test_argyll_fixtures_dir_fixture(self, argyll_fixtures_dir: Path):
        """验证 argyll_fixtures_dir fixture"""
        assert argyll_fixtures_dir.exists()
        assert argyll_fixtures_dir.name == "argyll"
    
    def test_load_fixture_function(self, load_fixture):
        """验证 load_fixture 函数"""
        content = load_fixture("01_spotread_success.txt")
        assert "Result is XYZ" in content
        assert len(content) > 0
    
    def test_temp_session_dir_fixture(self, temp_session_dir: Path):
        """验证临时目录 fixture"""
        assert temp_session_dir.exists()
        assert temp_session_dir.is_dir()
        
        # 可以写入文件
        test_file = temp_session_dir / "test.txt"
        test_file.write_text("test content")
        assert test_file.exists()
        assert test_file.read_text() == "test content"
    
    def test_temp_ti3_file_fixture(self, temp_ti3_file: Path):
        """验证 TI3 文件 fixture"""
        assert temp_ti3_file.exists()
        assert temp_ti3_file.suffix == ".ti3"
        
        content = temp_ti3_file.read_text()
        assert "CTI3" in content
        assert "BEGIN_DATA" in content
    
    def test_sample_measurement_data_fixture(self, sample_measurement_data):
        """验证测量数据 fixture"""
        assert "white_point" in sample_measurement_data
        assert "black_point" in sample_measurement_data
        assert "primaries" in sample_measurement_data
        
        # 验证数据结构
        wp = sample_measurement_data["white_point"]
        assert "x" in wp and "y" in wp and "Y" in wp


class TestMockFixtures:
    """验证 Mock fixtures 正常工作"""
    
    def test_mock_instrument_fixture(self, mock_instrument):
        """验证 mock_instrument fixture"""
        # 连接
        result = mock_instrument.connect()
        assert result is True
        
        # 测量
        x, y, Y = mock_instrument.measure()
        assert isinstance(x, float)
        assert isinstance(y, float)
        assert isinstance(Y, float)
        
        # 校准
        result = mock_instrument.calibrate()
        assert result is True
        
        # 状态
        status = mock_instrument.status()
        assert status["connected"] is True
    
    def test_mock_display_fixture(self, mock_display):
        """验证 mock_display fixture"""
        mock_display.show_rgb(255, 0, 0)
        mock_display.hide()
        
        assert mock_display.width == 1920
        assert mock_display.height == 1080
    
    def test_mock_popen_factory_fixture(self, mock_popen_factory):
        """验证 mock_popen_factory fixture"""
        # 设置自定义 fixture
        mock_popen_factory.set_fixture(
            "spotread",
            "Result is XYZ: 0.05 0.05 0.05",
            returncode=0
        )
        
        # 创建 Popen
        popen = mock_popen_factory.create_popen(["spotread", "-e"])
        
        assert popen.returncode == 0
        assert "XYZ" in popen._fixture_content
        
        # 检查调用记录
        assert len(mock_popen_factory.calls) == 1
        assert "spotread" in mock_popen_factory.calls[0]


class TestArgyllFixtureFiles:
    """验证 Argyll fixture 文件存在和格式正确"""
    
    def test_spotread_success_fixture(self, load_fixture):
        """验证 spotread 成功 fixture"""
        content = load_fixture("01_spotread_success.txt")
        assert "Result is XYZ:" in content
    
    def test_spotread_usb_disconnect_fixture(self, load_fixture):
        """验证 USB 断开 fixture"""
        content = load_fixture("02_spotread_usb_disconnect.txt")
        assert "LIBUSB_ERROR_IO" in content
    
    def test_dispcal_success_fixture(self, load_fixture):
        """验证 dispcal 成功 fixture"""
        content = load_fixture("07_dispcal_success.txt")
        assert "Written calibration file" in content
    
    def test_colprof_success_fixture(self, load_fixture):
        """验证 colprof 成功 fixture"""
        content = load_fixture("10_colprof_success.txt")
        assert "Created profile" in content or "Progress" in content
    
    def test_fixture_count(self, argyll_fixtures_dir: Path):
        """验证 fixture 文件数量"""
        txt_files = list(argyll_fixtures_dir.glob("*.txt"))
        assert len(txt_files) >= 15, "应该至少有 15 个 fixture 文件"


# ========== 项目模块导入验证 ==========

class TestModuleImports:
    """验证项目模块可正常导入"""
    
    def test_import_src_package(self):
        """验证 src 包可导入"""
        import src
        assert src is not None
    
    def test_import_argyll_controller(self):
        """验证 argyll_controller 可导入"""
        from src.argyll_controller import ArgyllController, ProbeType, DisplayType
        assert ArgyllController is not None
        assert ProbeType is not None
        assert DisplayType is not None
    
    def test_import_data_storage(self):
        """验证 data_storage 可导入"""
        from src.data_storage import DataStorage
        assert DataStorage is not None
    
    def test_import_measurement_analyzer(self):
        """验证 measurement_analyzer 可导入"""
        from src.measurement_analyzer import MeasurementAnalyzer
        assert MeasurementAnalyzer is not None
    
    def test_import_lab_sampler(self):
        """验证 lab_sampler 可导入"""
        from src.lab_sampler import LABSampler
        assert LABSampler is not None
    
    def test_import_backend(self):
        """验证 backend 可导入"""
        from src.backend import Backend
        assert Backend is not None


# ========== 基本功能验证 ==========

class TestBasicFunctionality:
    """验证基本功能"""
    
    def test_probe_type_enum(self):
        """验证探头类型枚举"""
        from src.argyll_controller import ProbeType
        
        # 常用探头类型
        assert ProbeType.I1_DISPLAY_PRO.value == "i1d3"
        assert ProbeType.I1_PRO.value == "i1pro"
        assert ProbeType.SPYDERX.value == "spydx"
    
    def test_display_type_enum(self):
        """验证显示器类型枚举"""
        from src.argyll_controller import DisplayType
        
        # 常用显示器类型
        assert DisplayType.LCD.value == "l"
        assert DisplayType.OLED.value == "o"
        assert DisplayType.LCD_WHITE_LED.value == "e"
    
    def test_probe_delay_config(self):
        """验证探头延迟配置"""
        from src.argyll_controller import PROBE_RECOMMENDED_DELAYS, ProbeType
        
        # 应有延迟配置
        assert ProbeType.I1_DISPLAY_PRO in PROBE_RECOMMENDED_DELAYS
        assert "default" in PROBE_RECOMMENDED_DELAYS
        
        # 延迟值应合理（100-2000ms）
        for probe, delay in PROBE_RECOMMENDED_DELAYS.items():
            if isinstance(probe, str):
                continue
            assert 100 <= delay <= 2000, f"{probe} 延迟值不合理"


# ========== 标记测试 ==========

@pytest.mark.slow
class TestSlowTests:
    """慢速测试标记验证"""
    
    def test_slow_marker(self):
        """验证 slow 标记"""
        # 这个测试会被标记为 slow
        pass


@pytest.mark.integration
class TestIntegrationTests:
    """集成测试标记验证"""
    
    def test_integration_marker(self):
        """验证 integration 标记"""
        # 这个测试会被标记为 integration
        pass


@pytest.mark.gui
class TestGUITests:
    """GUI 测试标记验证"""
    
    def test_gui_marker(self):
        """验证 gui 标记"""
        # 这个测试会被标记为 gui（可能在无显示环境被跳过）
        pass


@pytest.mark.hardware
class TestHardwareTests:
    """硬件测试标记验证"""
    
    def test_hardware_marker(self):
        """验证 hardware 标记"""
        # 这个测试会被标记为 hardware（需要物理仪器）
        pass
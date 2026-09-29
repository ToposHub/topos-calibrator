"""
AutoCalService 集成测试 (P1 集成)

验证服务门面的核心链路：
    - DDC 模拟适配器连接 / 能力查询 / 控制项读写 / 快照回滚
    - 自动校准闭环启动（dry-run）/ 状态回调 / 取消
    - 目标与配置解析的约束
"""

import sys
import threading
import time
from pathlib import Path

import pytest

# 保证从项目根目录导入
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.workflows.autocal_service import AutoCalService, AutoCalServiceError
from src.workflows.autocal_workflow import MeasurementPoint


def _fake_measure(rgb, name):
    """模拟测量：白点略偏，其余接近 D65"""
    if rgb == (255, 255, 255):
        return MeasurementPoint(rgb=rgb, name=name, xyY=(0.3140, 0.3310, 95.0))
    if rgb == (0, 0, 0):
        return MeasurementPoint(rgb=rgb, name=name, xyY=(0.0, 0.0, 0.1))
    level = rgb[0] / 255.0
    return MeasurementPoint(rgb=rgb, name=name, xyY=(0.3127, 0.3290, 50.0 * level))


@pytest.fixture
def connected_service():
    """已连接模拟适配器的服务"""
    svc = AutoCalService()
    result = svc.connect_display(display_id=1, allow_fake=True)
    assert result["success"] is True
    assert result["is_fake"] is True
    return svc


class TestDisplayControl:
    """显示器控制通道"""

    def test_capabilities(self, connected_service):
        caps = connected_service.get_capabilities()
        assert caps is not None
        writable = [c for c in caps["capabilities"] if c["writable"]]
        assert any(c["control_type"] == "brightness" for c in writable)

    def test_write_and_rollback(self, connected_service):
        result = connected_service.write_control("brightness", 75)
        assert result["success"] is True
        assert result["value"] == 75

        rb = connected_service.rollback()
        assert rb["success"] is True

    def test_unknown_control(self, connected_service):
        with pytest.raises(AutoCalServiceError):
            connected_service.write_control("nonexistent", 10)

    def test_not_connected_raises(self):
        svc = AutoCalService()
        with pytest.raises(AutoCalServiceError):
            svc.write_control("brightness", 50)


class TestAutoCalRun:
    """自动校准闭环"""

    def test_dry_run_completes(self, connected_service):
        states = []
        connected_service.on_state = lambda o, n: states.append((o, n))

        session = connected_service.start(
            _fake_measure,
            {"white_point": "D65", "target_Y_white": 95.0},
            {"dry_run": True, "max_iterations": 2},
        )

        assert session["state"] == "completed"
        assert session["dry_run"] is True
        assert ("preflight", "baseline") in states

    def test_progress_callback_fires(self, connected_service):
        progress = []
        connected_service.on_progress = lambda msg, pct: progress.append((msg, pct))

        connected_service.start(
            _fake_measure,
            {"white_point": "D65"},
            {"dry_run": True, "max_iterations": 1, "grayscale_steps": 3},
        )

        assert len(progress) > 0
        # 进度值应在 0-95 区间（完成前封顶 95）
        assert all(0 <= pct <= 95 for _, pct in progress)

    def test_running_flag(self, connected_service):
        """运行标志在执行期间为 True，结束后复位"""
        flags = []

        def slow_measure(rgb, name):
            flags.append(connected_service.is_running)
            time.sleep(0.01)
            return _fake_measure(rgb, name)

        assert connected_service.is_running is False
        connected_service.start(
            slow_measure,
            {"white_point": "D65"},
            {"dry_run": True, "max_iterations": 1, "grayscale_steps": 3},
        )
        assert connected_service.is_running is False
        assert any(flags)

    def test_double_start_rejected(self, connected_service):
        """已在运行时再次 start 应报 ALREADY_RUNNING"""
        release = threading.Event()
        started = threading.Event()

        def blocking_measure(rgb, name):
            started.set()
            release.wait(timeout=5)
            return _fake_measure(rgb, name)

        worker = threading.Thread(
            target=connected_service.start,
            args=(blocking_measure, {"white_point": "D65"}, {"dry_run": True}),
            daemon=True,
        )
        worker.start()
        assert started.wait(timeout=5)

        with pytest.raises(AutoCalServiceError) as exc_info:
            connected_service.start(
                _fake_measure, {"white_point": "D65"}, {"dry_run": True}
            )
        assert exc_info.value.error_code == "ALREADY_RUNNING"

        release.set()
        worker.join(timeout=10)

    def test_cancel(self, connected_service):
        """cancel() 应在安全点停止工作流"""
        cancelled_states = []
        connected_service.on_state = lambda o, n: cancelled_states.append(n)

        def measure_that_cancels(rgb, name):
            # 第一次测量后请求取消
            if not measure_that_cancels.triggered:
                measure_that_cancels.triggered = True
                connected_service.stop()
            return _fake_measure(rgb, name)
        measure_that_cancels.triggered = False

        session = connected_service.start(
            measure_that_cancels,
            {"white_point": "D65"},
            {"dry_run": True, "max_iterations": 3},
        )
        assert "cancelled" in cancelled_states
        assert session["state"] == "cancelled"

    def test_stop_when_not_running(self):
        svc = AutoCalService()
        result = svc.stop()
        assert result["success"] is False


class TestConfigParsing:
    """目标/配置解析约束（经 start 路径间接验证不崩溃并收敛到默认）"""

    def test_invalid_values_fall_back(self, connected_service):
        """非法输入应回落默认值而不抛异常"""
        session = connected_service.start(
            _fake_measure,
            {
                "white_point": "INVALID",
                "target_Y_white": "not-a-number",
                "target_gamma": None,
            },
            {"dry_run": True, "max_iterations": 1, "grayscale_steps": 3},
        )
        # 白点回落 D65，会尝试调整（dry-run 下直接完成或达到迭代上限）
        assert session["state"] in ("completed", "failed")

    def test_get_status(self, connected_service):
        status = connected_service.get_status()
        assert status["running"] is False
        assert status["display_connected"] is True
        assert status["capabilities"] is not None

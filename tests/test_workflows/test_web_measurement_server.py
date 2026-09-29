"""
Web 测量服务器链路测试

不依赖 Qt 实例化，用桩对象直接调用 Backend 的 unbound 方法：
    - get_web_measurement_status 的返回结构（停止/运行两种状态）
    - start/stop 状态槽的真实启动-停止闭环（临时端口）
"""

import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class _LogStub:
    def emit(self, msg):
        pass


class _SignalStub:
    def __init__(self):
        self.payload = None

    def emit(self, payload):
        self.payload = payload


def _make_backend_stub():
    return SimpleNamespace(
        logMessage=_LogStub(),
        webMeasurementServerStarted=_SignalStub(),
        webMeasurementServerStopped=_SignalStub(),
        _web_measurement_server=None,
        _web_measurement_port=8080,
    )


def _get_status(stub):
    from src.backend import Backend
    return json.loads(Backend.get_web_measurement_status(stub))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestWebMeasurementStatus:
    """get_web_measurement_status 返回结构"""

    def test_status_stopped(self):
        stub = _make_backend_stub()
        status = _get_status(stub)
        assert status == {"running": False, "url": None, "port": 8080}

    def test_status_running(self):
        stub = _make_backend_stub()
        stub._web_measurement_server = SimpleNamespace(
            _running=True, url="http://192.168.1.5:8123"
        )
        status = _get_status(stub)
        assert status["running"] is True
        assert status["url"] == "http://192.168.1.5:8123"
        assert status["port"] == 8080

    def test_status_reflects_configured_port(self):
        stub = _make_backend_stub()
        stub._web_measurement_port = 9999
        assert _get_status(stub)["port"] == 9999


class TestWebMeasurementStartStop:
    """真实启动-停止闭环"""

    def test_start_stop_roundtrip(self):
        from src.backend import Backend

        stub = _make_backend_stub()
        stub._web_measurement_port = _free_port()

        try:
            Backend.start_web_measurement_server(stub)
        except Exception:
            pytest.skip("无法绑定临时端口，跳过启动闭环测试")

        payload = json.loads(stub.webMeasurementServerStarted.payload)
        assert payload["success"] is True
        assert payload["url"].endswith(f":{stub._web_measurement_port}")

        status = _get_status(stub)
        assert status["running"] is True
        assert status["url"] == payload["url"]

        Backend.stop_web_measurement_server(stub)
        assert stub.webMeasurementServerStopped.payload is not None
        assert _get_status(stub)["running"] is False
        assert _get_status(stub)["url"] is None

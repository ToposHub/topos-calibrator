"""
启动自动连接探头 & 多探头切换测试

验证 Backend 新增槽的行为（全部使用 mock，不依赖真实硬件）：
- auto_connect_probe: 未连接时触发后台连接；已连接时仅同步状态；
                      连接失败（auto 模式）静默降级不发 error
- get_instrument_list: 立即返回缓存 JSON，并触发后台刷新推送信号
- select_and_connect_instrument: 按缓存列表切换探头类型与端口
"""

import json

import pytest
from unittest.mock import MagicMock, patch

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QObject

from src.backend import Backend


@pytest.fixture
def backend(qtbot=None):
    """构造 Backend 实例（跳过重量级 __init__，仅初始化 QObject 基类）"""
    with patch.object(Backend, "__init__", lambda self: QObject.__init__(self)):
        b = Backend()
    # 手动初始化被跳过的最小状态
    b._probe_connecting = False
    b._last_instrument_list = []
    b._instrument_list_refreshing = False
    b._argyll_controller = MagicMock()
    b._argyll_controller.is_connected.return_value = False
    b._probe_type = None
    b.logMessage = MagicMock()
    b.logMessage.emit = MagicMock()
    return b


class TestAutoConnectProbe:
    def test_auto_connect_starts_background_connect(self, backend):
        backend._argyll_controller.is_connected.return_value = False

        with patch("src.backend.threading.Thread") as mock_thread:
            backend.auto_connect_probe()

        mock_thread.assert_called_once()

    def test_auto_connect_skips_when_already_connected(self, backend):
        backend._argyll_controller.is_connected.return_value = True
        backend._argyll_controller._probe_type = MagicMock(value="i1d3")
        backend.probeStatusChanged = MagicMock()
        backend.probeStatusChanged.emit = MagicMock()

        with patch("src.backend.threading.Thread") as mock_thread:
            backend.auto_connect_probe()

        # 不应启动连接线程，只重发已连接状态供前端同步
        mock_thread.assert_not_called()
        payload = json.loads(backend.probeStatusChanged.emit.call_args[0][0])
        assert payload["connected"] is True
        assert payload["status"] == "connected"

    def test_auto_connect_silent_on_failure(self, backend):
        """auto 模式连接失败时静默降级：不发 error 状态"""
        backend._argyll_controller.connect.return_value = False
        backend._argyll_controller.get_error_message.return_value = "no instrument"
        backend.probeStatusChanged = MagicMock()
        backend.probeStatusChanged.emit = MagicMock()

        # 捕获后台线程 target 直接执行（不起真线程）
        captured = {}

        def fake_thread(target=None, name=None, daemon=None):
            captured["target"] = target
            return MagicMock()

        with patch("src.backend.threading.Thread", side_effect=fake_thread):
            backend.auto_connect_probe()
        captured["target"]()

        statuses = [json.loads(c[0][0]) for c in backend.probeStatusChanged.emit.call_args_list]
        assert all(s.get("status") != "error" for s in statuses), statuses


class TestGetInstrumentList:
    def test_returns_cached_list_and_triggers_refresh(self, backend):
        backend._last_instrument_list = [
            {"index": 1, "name": "X-Rite i1 DisplayPro", "probe_type": "i1d3"}
        ]

        with patch("src.backend.threading.Thread") as mock_thread:
            result = backend.get_instrument_list()

        assert json.loads(result) == [
            {"index": 1, "name": "X-Rite i1 DisplayPro", "probe_type": "i1d3"}
        ]
        mock_thread.assert_called_once()  # 后台刷新已触发

    def test_empty_cache_returns_empty_array(self, backend):
        result = backend.get_instrument_list()
        assert json.loads(result) == []


class TestSelectAndConnectInstrument:
    def test_switch_sets_port_and_probe_type(self, backend):
        from src.argyll_controller import ProbeType

        backend._last_instrument_list = [
            {"index": 1, "name": "i1 DisplayPro", "probe_type": "i1d3"},
            {"index": 2, "name": "SpyderX", "probe_type": "spydx"},
        ]
        backend._argyll_controller.is_connected.return_value = True
        backend._argyll_controller._instrument_port = 1

        with patch("src.backend.threading.Thread"):
            backend.select_and_connect_instrument(2)

        assert backend._argyll_controller._instrument_port == 2
        assert backend._argyll_controller._probe_type == ProbeType("spydx")
        backend._argyll_controller.disconnect.assert_called_once()

    def test_switch_unknown_type_keeps_current(self, backend):
        """缓存列表里找不到该端口时不改动探头类型"""
        backend._last_instrument_list = []
        original_type = object()  # 哨兵：MagicMock 属性访问会自动创建，需用哨兵对比
        backend._argyll_controller._probe_type = original_type
        with patch("src.backend.threading.Thread"):
            backend.select_and_connect_instrument(3)
        assert backend._argyll_controller._instrument_port == 3
        assert backend._argyll_controller._probe_type is original_type  # 未被改动

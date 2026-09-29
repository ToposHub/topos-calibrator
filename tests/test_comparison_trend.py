"""
历史趋势数据链路测试

验证 ComparisonWindow 的趋势指标计算：
    - McCamy CCT 近似（D65 白点 ≈ 6500K）
    - 灰阶 Gamma log-log 拟合
    - get_trend_data 的指标提取与排序（绕开 Qt 实例化）
"""

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.comparison_window import ComparisonBackend


class TestMcCamyCCT:
    def test_d65_xy_is_6500k(self):
        # D65 (0.3127, 0.3290) → 约 6504K
        cct = ComparisonBackend._mccamy_cct(0.3127, 0.3290)
        assert cct is not None
        assert abs(cct - 6500) < 50

    def test_warm_white_lower_cct(self):
        warm = ComparisonBackend._mccamy_cct(0.3451, 0.3516)   # ~5000K
        d65 = ComparisonBackend._mccamy_cct(0.3127, 0.3290)
        assert warm < 5100
        assert warm < d65

    def test_degenerate_returns_none(self):
        assert ComparisonBackend._mccamy_cct(0.33, 0.1858) is None


class TestFitGamma:
    def _perfect_gamma_series(self, g=2.2, levels=(5, 10, 20, 30, 50, 70, 80, 90)):
        return [{"input": lvl, "Y": (lvl / 100.0) ** g * 100.0} for lvl in levels]

    def test_perfect_2p2(self):
        assert ComparisonBackend._fit_gamma(self._perfect_gamma_series(2.2)) == pytest.approx(2.2, abs=0.001)

    def test_perfect_2p4(self):
        assert ComparisonBackend._fit_gamma(self._perfect_gamma_series(2.4)) == pytest.approx(2.4, abs=0.001)

    def test_too_few_points(self):
        assert ComparisonBackend._fit_gamma([{"input": 50, "Y": 21.9}]) is None
        assert ComparisonBackend._fit_gamma([]) is None

    def test_black_points_ignored(self):
        # 0% 黑（Y=0）与 <5% 电平不参与拟合
        series = [{"input": 0, "Y": 0.0}, {"input": 2, "Y": 0.02}] + self._perfect_gamma_series(2.2)
        assert ComparisonBackend._fit_gamma(series) == pytest.approx(2.2, abs=0.001)


class _FakeMeasurement:
    """duck-type MeasurementData"""

    def __init__(self, metadata, measurements, valid=True):
        self.metadata = metadata
        self.measurements = measurements
        self._valid = valid

    def is_valid(self):
        return self._valid


class _FakeStorage:
    def __init__(self, mapping):
        self._mapping = mapping

    def load_measurement(self, mid):
        return self._mapping.get(mid)


class TestGetTrendData:
    """get_trend_data 指标提取与排序（__new__ 绕开 Qt 实例化）"""

    def _window(self, storage):
        win = ComparisonBackend.__new__(ComparisonBackend)
        win._data_storage = storage
        return win

    def test_extracts_and_sorts(self):
        m1 = _FakeMeasurement(
            metadata={"timestamp": "2026-08-01T10:00:00", "display_model": "DELL U2722D"},
            measurements={
                "gamut": {"white": {"RGB": [255, 255, 255], "xyY": [0.3127, 0.3290, 120.5]}},
                "gamma": [{"input": lvl, "Y": (lvl / 100.0) ** 2.2 * 120.5} for lvl in (10, 30, 50, 70, 90)],
            },
        )
        m2 = _FakeMeasurement(
            metadata={"timestamp": "2026-08-20T10:00:00", "display_model": "DELL U2722D"},
            measurements={
                "gamut": {"white": {"RGB": [255, 255, 255], "xyY": [0.3140, 0.3280, 118.2]}},
                "gamma": [{"input": lvl, "Y": (lvl / 100.0) ** 2.3 * 118.2} for lvl in (10, 30, 50, 70, 90)],
            },
        )
        # 传入乱序 ID，输出应按时间升序
        win = self._window(_FakeStorage({"b": m2, "a": m1}))
        result = json.loads(ComparisonBackend.get_trend_data(win, json.dumps(["b", "a"])))

        assert result["success"] is True
        points = result["points"]
        assert [p["id"] for p in points] == ["a", "b"]

        assert points[0]["whiteY"] == 120.5
        assert points[0]["whiteCCT"] is not None
        assert abs(points[0]["gamma"] - 2.2) < 0.01
        assert abs(points[1]["gamma"] - 2.3) < 0.01

    def test_invalid_sessions_skipped(self):
        empty = _FakeMeasurement({}, {"gamut": {}, "gamma": []}, valid=True)
        invalid = _FakeMeasurement({}, {}, valid=False)
        win = self._window(_FakeStorage({"x": empty, "y": invalid}))
        result = json.loads(ComparisonBackend.get_trend_data(win, json.dumps(["x", "y"])))
        assert result["success"] is True
        assert result["points"] == []

    def test_bad_json_returns_error(self):
        win = self._window(_FakeStorage({}))
        result = json.loads(ComparisonBackend.get_trend_data(win, "not-json"))
        assert result["success"] is False

"""
均匀性持久化与报告链路测试

覆盖：
    - MeasurementData.update_uniformity_measurement 存储/覆盖/NaN 容错 + is_valid
    - 报告生成器：均匀性段落渲染（含摘要计算）、无数据时隐藏
    - Backend._locate_oeminst 定位（含项目内置 ArgyllCMS/bin/oeminst）
"""

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.data_storage import MeasurementData
from src.reports.generator import ReportGenerator, ReportType, ReportConfig


class _LogStub:
    def emit(self, msg):
        pass


class TestUniformityPersistence:
    def test_store_and_overwrite(self):
        m = MeasurementData()
        assert not m.is_valid()

        m.update_uniformity_measurement(0, 0, 0.31, 0.33, 100.0, 6500)
        assert m.is_valid()  # 均匀性数据即可构成有效会话

        m.update_uniformity_measurement(0, 0, 0.32, 0.34, 101.0, 6510)  # 同点覆盖
        pts = m.measurements["uniformity"]
        assert len(pts) == 1
        assert pts[0]["xyY"][2] == 101.0
        assert pts[0]["cct"] == 6510

        m.update_uniformity_measurement(2, 2, 0.31, 0.33, 99.0)
        assert len(m.measurements["uniformity"]) == 2

    def test_nan_cct_dropped(self):
        m = MeasurementData()
        m.update_uniformity_measurement(0, 0, 0.31, 0.33, 100.0, float("nan"))
        assert "cct" not in m.measurements["uniformity"][0]

    def test_json_roundtrip(self):
        m = MeasurementData()
        m.update_uniformity_measurement(1, 1, 0.3127, 0.3290, 120.0, 6504)
        m2 = MeasurementData()
        m2.from_json(m.to_json())
        assert m2.measurements["uniformity"][0]["row"] == 1
        assert m2.is_valid()


def _uni_data(dev_map=None):
    """3×3 均匀性数据（中心 r1c1=100 nit，其他按 dev_map 偏差百分比）"""
    pts = []
    for r in range(3):
        for c in range(3):
            dev = (dev_map or {}).get((r, c), 0.0)
            pts.append({
                "row": r, "col": c,
                "xyY": [0.3127, 0.3290, 100.0 * (1 + dev / 100.0)],
                "cct": 6500,
            })
    return {"metadata": {"display_model": "T"}, "measurements": {"uniformity": pts}}


class TestUniformityReport:
    def _gen(self):
        return ReportGenerator(ReportConfig())

    def test_section_rendered_with_summary(self):
        html = self._gen().generate_from_dict(
            _uni_data({(0, 0): -5, (2, 2): 8}), ReportType.FULL_REPORT)
        assert "均匀性分析（3×3 网格）" in html
        assert "亮度均匀性" in html
        # Ymin=95, Ymax=108 → 均匀性 = (1-13/108)*100 ≈ 87.96
        assert "88.0%" in html or "87.9%" in html
        # 中心白框标记恰好 1 个
        assert html.count("2px solid #ffffff") == 1

    def test_section_hidden_without_data(self):
        html = self._gen().generate_from_dict(
            {"metadata": {}, "measurements": {"gamma": []}}, ReportType.FULL_REPORT)
        assert "<h2>均匀性分析" not in html
        assert "{{UNIFORMITY_SECTION}}" not in html

    def test_deviation_colors(self):
        html = self._gen().generate_from_dict(
            _uni_data({(0, 0): -2, (0, 1): -4, (0, 2): -7, (1, 0): -12}), ReportType.FULL_REPORT)
        assert html.count("#10b981") >= 6   # ≤3% 绿
        assert "#84cc16" in html            # ≤5% 黄绿
        assert "#f59e0b" in html            # ≤10% 橙
        assert "#ef4444" in html            # >10% 红


class TestOeminstLocator:
    def test_locates_bundled_oeminst(self):
        from src.backend import Backend
        stub = SimpleNamespace(_argyll_controller=None, logMessage=_LogStub())
        path = Backend._locate_oeminst(stub)
        # 项目内置 ArgyllCMS/bin/oeminst 存在时应能定位
        assert path != ""
        assert Path(path).is_file()
        assert "oeminst" in Path(path).name

    def test_prefers_controller_path(self):
        from src.backend import Backend
        bundled = Path(__file__).resolve().parents[2] / "ArgyllCMS" / "bin"
        stub = SimpleNamespace(
            _argyll_controller=SimpleNamespace(_argyll_path=str(bundled)),
            logMessage=_LogStub(),
        )
        path = Backend._locate_oeminst(stub)
        assert Path(path).parent == bundled

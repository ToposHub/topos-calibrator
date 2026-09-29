"""
HDR EOTF 追踪链路测试 (P3 集成)

不依赖 Qt，用最小桩验证：
    - HDR 灰阶梯生成（PQ 对数分布 / HLG 线性分布）
    - analyze_hdr_eotf 的核心分析逻辑（亮度误差 + ΔE ITP）
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.color_science.transfer import apply_eotf, apply_oetf


class _LogStub:
    def emit(self, msg):
        pass


def _make_backend_stub(eotf="PQ", peak=1000.0):
    """构造带 HDR 状态的最小桩（duck-type Backend 的相关属性）"""
    return SimpleNamespace(
        _hdr_eotf=eotf,
        _hdr_peak_nits=peak,
        logMessage=_LogStub(),
    )


def _generate_hdr_patches(stub):
    """直接调用 Backend._generate_hdr_patches（unbound，绕开 Qt 实例化）"""
    from src.backend import Backend
    return Backend._generate_hdr_patches(stub)


class TestHdrPatchGeneration:
    """HDR 灰阶梯生成"""

    def test_pq_ramp_covers_peak(self):
        result = _generate_hdr_patches(_make_backend_stub("PQ", 1000.0))
        assert result["mode"] == "hdr"
        assert result["eotf"] == "PQ"
        patches = result["groups"][0]["patches"]
        assert len(patches) >= 10

        # 最高点目标亮度应接近峰值（8-bit PQ 量化可上取整 ~1%）
        max_target = max(p["target_nits"] for p in patches)
        assert 950 <= max_target <= 1000 * 1.05

        # 最低点应在暗部（< 10 nits）
        min_target = min(p["target_nits"] for p in patches)
        assert min_target < 10

        # 码值唯一且单调
        codes = [p["rgb"][0] for p in patches]
        assert codes == sorted(codes)
        assert len(set(codes)) == len(codes)

    def test_pq_ramp_respects_lower_peak(self):
        """峰值 400 nits 时 ramp 不应包含超过 400+ 的目标点"""
        result = _generate_hdr_patches(_make_backend_stub("PQ", 400.0))
        patches = result["groups"][0]["patches"]
        assert max(p["target_nits"] for p in patches) <= 400

    def test_hlg_ramp_linear(self):
        result = _generate_hdr_patches(_make_backend_stub("HLG", 1000.0))
        assert result["eotf"] == "HLG"
        patches = result["groups"][0]["patches"]

        # HLG 满码值 255 → Lw=1000 nits
        full = [p for p in patches if p["rgb"][0] == 255]
        assert len(full) == 1
        assert full[0]["target_nits"] == pytest.approx(1000.0, rel=0.01)

        # 命名格式 HDR-<code>
        assert all(p["name"].startswith("HDR-") for p in patches)

    def test_patch_rgb_is_gray(self):
        for eotf in ("PQ", "HLG"):
            result = _generate_hdr_patches(_make_backend_stub(eotf, 1000.0))
            for p in result["groups"][0]["patches"]:
                r, g, b = p["rgb"]
                assert r == g == b
                assert 0 <= r <= 255


class TestAnalyzeCore:
    """分析逻辑核心（PQ/HLG 目标计算 + ΔE ITP 集成）"""

    def test_perfect_display_zero_error(self):
        """完美显示器（测量 = 目标，白点 = D65）→ 误差与 ΔE ITP 为零"""
        from src.color_science import delta_e_itp_from_xyY

        result = _generate_hdr_patches(_make_backend_stub("PQ", 1000.0))
        for p in result["groups"][0]["patches"]:
            L = p["target_nits"]
            itp = delta_e_itp_from_xyY((0.3127, 0.3290, L), (0.3127, 0.3290, L))
            assert itp["itp"] == pytest.approx(0.0, abs=1e-9)
            assert itp["i"] == pytest.approx(0.0, abs=1e-9)

    def test_luminance_error_propagates(self):
        """+10% 亮度误差 → I 分量增大、误差为正"""
        from src.color_science import delta_e_itp_from_xyY

        target = 100.0
        itp = delta_e_itp_from_xyY(
            (0.3127, 0.3290, target * 1.1), (0.3127, 0.3290, target)
        )
        assert itp["i"] > 0
        assert itp["i"] > itp["ct"]

    def test_pq_eotf_roundtrip(self):
        """PQ 编解码往返一致（色块生成的自洽性）"""
        for L in [2.0, 50.0, 300.0, 1000.0, 4000.0]:
            V = apply_oetf(L, "PQ")  # apply_oetf 接收绝对 nits
            L_back = apply_eotf(V, "PQ", L_max=10000.0)
            assert L_back == pytest.approx(L, rel=1e-6)

    def test_hlg_full_signal_equals_lw(self):
        assert apply_eotf(1.0, "HLG", Lw=1000.0, Lb=0.0) == pytest.approx(1000.0, rel=1e-6)


class TestAnalyzeSlotLogic:
    """analyze_hdr_eotf 的纯逻辑部分（不经过 Qt）"""

    def _analyze(self, measurements, eotf="PQ", peak=1000.0):
        """复刻 backend.analyze_hdr_eotf 的核心计算（验证逻辑正确性）"""
        from src.color_science import delta_e_itp_from_xyY

        points = []
        for m in measurements:
            name = str(m.get("patchName", ""))
            if not name.startswith("HDR-"):
                continue
            code8 = int(name.split("-", 1)[1])
            V = code8 / 255.0
            if eotf == "PQ":
                L_target = apply_eotf(V, "PQ", L_max=10000.0)
            else:
                L_target = apply_eotf(V, "HLG", Lw=peak, Lb=0.0)
            Y = float(m.get("Y", 0.0))
            itp = delta_e_itp_from_xyY(
                (m.get("x", 0.3127), m.get("y", 0.3290), Y),
                (0.3127, 0.3290, L_target),
            )
            points.append({
                "code": code8,
                "target_nits": round(L_target, 2),
                "measured_nits": round(Y, 2),
                "error_nits": round(Y - L_target, 2),
                "delta_e_itp": round(itp["itp"], 2),
            })
        return sorted(points, key=lambda p: p["code"])

    def test_report_points_sorted_and_consistent(self):
        # 构造带 +10 nits 偏置的模拟测量
        result = _generate_hdr_patches(_make_backend_stub("PQ", 1000.0))
        measurements = []
        for p in result["groups"][0]["patches"]:
            measurements.append({
                "patchName": p["name"],
                "x": 0.3127, "y": 0.3290,
                "Y": p["target_nits"] + 10.0,
            })
        # 打乱顺序输入
        measurements.reverse()

        points = self._analyze(measurements)
        assert len(points) > 5
        codes = [p["code"] for p in points]
        assert codes == sorted(codes)
        for p in points:
            assert p["error_nits"] == pytest.approx(10.0, abs=0.05)
            assert p["delta_e_itp"] >= 0

    def test_non_hdr_names_ignored(self):
        points = self._analyze([
            {"patchName": "红", "x": 0.64, "y": 0.33, "Y": 21.0},
            {"patchName": "HDR-255", "x": 0.3127, "y": 0.3290, "Y": 990.0},
        ])
        assert len(points) == 1
        assert points[0]["code"] == 255

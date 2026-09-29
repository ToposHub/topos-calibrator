"""
均匀性检测链路测试

不依赖 Qt，用最小桩验证：
    - 均匀性网格色块生成（3×3 / 5×5、测点中心坐标、色块面积）
    - set_uniformity_config 的参数钳制
    - start_custom_cycle 的 zone 扩展解析逻辑
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class _LogStub:
    def emit(self, msg):
        pass


def _make_backend_stub():
    return SimpleNamespace(logMessage=_LogStub())


def _generate_uniformity_patches(stub):
    """直接调用 Backend._generate_uniformity_patches（unbound，绕开 Qt 实例化）"""
    from src.backend import Backend
    return Backend._generate_uniformity_patches(stub)


def _set_uniformity_config(stub, grid, level, size):
    from src.backend import Backend
    return Backend.set_uniformity_config(stub, grid, level, size)


def _convert_custom_patches(patches):
    """直接调用 Backend._convert_custom_patches（start_custom_cycle / start_guided_cycle 共用）"""
    from src.backend import Backend
    return Backend._convert_custom_patches(patches)


class TestUniformityPatchGeneration:
    """均匀性网格色块生成"""

    def test_default_3x3_grid(self):
        result = _generate_uniformity_patches(_make_backend_stub())
        assert result["mode"] == "uniformity"
        patches = result["groups"][0]["patches"]
        assert len(patches) == 9

        names = [p["name"] for p in patches]
        assert "U-r0c0" in names
        assert "U-r1c1" in names
        assert "U-r2c2" in names

    def test_zone_centers_3x3(self):
        """3×3 网格的测点中心应位于 1/6, 3/6, 5/6"""
        result = _generate_uniformity_patches(_make_backend_stub())
        patches = {p["name"]: p for p in result["groups"][0]["patches"]}

        assert patches["U-r0c0"]["zone"][0] == pytest.approx(1 / 6, abs=1e-3)
        assert patches["U-r0c0"]["zone"][1] == pytest.approx(1 / 6, abs=1e-3)
        assert patches["U-r1c1"]["zone"][0] == pytest.approx(0.5, abs=1e-3)
        assert patches["U-r2c2"]["zone"][0] == pytest.approx(5 / 6, abs=1e-3)

    def test_default_white_level(self):
        result = _generate_uniformity_patches(_make_backend_stub())
        for p in result["groups"][0]["patches"]:
            assert p["rgb"] == [255, 255, 255]

    def test_5x5_grid_and_gray_level(self):
        stub = _make_backend_stub()
        _set_uniformity_config(stub, 5, 50, 20)
        result = _generate_uniformity_patches(stub)
        patches = result["groups"][0]["patches"]
        assert len(patches) == 25
        for p in patches:
            # 50% 电平 → 127/128
            assert p["rgb"][0] in (127, 128)
            assert p["zone"][2] == 20.0

    def test_config_clamping(self):
        stub = _make_backend_stub()
        _set_uniformity_config(stub, 99, 500, 500)   # 超上限
        result = _generate_uniformity_patches(stub)
        assert len(result["groups"][0]["patches"]) == 81  # 9×9
        for p in result["groups"][0]["patches"]:
            assert p["rgb"] == [255, 255, 255]  # 100% 钳制
            assert p["zone"][2] == 50.0

        _set_uniformity_config(stub, 1, 0, 0)     # 超下限
        result = _generate_uniformity_patches(stub)
        assert len(result["groups"][0]["patches"]) == 4    # 2×2
        for p in result["groups"][0]["patches"]:
            assert p["zone"][2] == 3.0


class TestCustomCycleZoneExtension:
    """start_custom_cycle / start_guided_cycle 的 zone 扩展解析规则"""

    def test_plain_patch_keeps_4_tuple(self):
        out = _convert_custom_patches([[255, 0, 0, "红"]])
        assert out == [(255, 0, 0, "红")]

    def test_zone_patch_appends_tuple(self):
        out = _convert_custom_patches([[200, 200, 200, "U-r0c0", 0.17, 0.17, 15.0]])
        assert out == [(200, 200, 200, "U-r0c0", (0.17, 0.17, 15.0))]

    def test_invalid_zone_dropped(self):
        # 第 5-7 位非法时退回普通 4 元组（与 backend 容错一致）
        out = _convert_custom_patches([[10, 10, 10, "U-r0c0", "x", None, []]])
        assert out == [(10, 10, 10, "U-r0c0")]

    def test_short_entries_ignored(self):
        out = _convert_custom_patches([[1, 2, 3], ["nope"], [1, 2, 3, "n", 0.5]])
        assert out == [(1, 2, 3, "n")]

"""
PDF 报告导出测试 (P4 修复)

验证 generate_pdf_report：
    - 正常渲染（weasyprint 可用时）
    - CJK 字体注入逻辑
    - 失败路径返回 False 而非抛异常
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.reports.generator import generate_pdf_report


SAMPLE_HTML = """<html><head><meta charset="utf-8">
<title>校准报告</title></head>
<body><h1>显示器校准报告</h1><p>ΔE ITP = 2.36，白点 D65</p></body></html>"""


class TestGeneratePdfReport:
    def test_renders_pdf(self):
        """weasyprint 可用时生成有效 PDF（以 %PDF 魔数校验）"""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            out = f.name
        try:
            assert generate_pdf_report(SAMPLE_HTML, out) is True
            assert os.path.exists(out) and os.path.getsize(out) > 1000
            with open(out, "rb") as f:
                assert f.read(4) == b"%PDF"
        finally:
            os.unlink(out)

    def test_cjk_font_injection(self):
        """无 CJK 字体声明的 HTML 会被注入字体栈"""
        head = SAMPLE_HTML.split("</head>", 1)[0]
        assert "PingFang" not in head  # 原始模板无 CJK 字体

        captured = {}
        import src.reports.generator as gen_mod

        class _FakeHTML:
            def __init__(self, string=None, **kw):
                captured["html"] = string

            def write_pdf(self, path):
                Path(path).write_bytes(b"%PDF-fake")

        original = getattr(gen_mod, "HTML", None)
        # weasyprint 的 HTML 经函数内 import，直接打桩 sys.modules
        import types
        fake_module = types.ModuleType("weasyprint")
        fake_module.HTML = _FakeHTML
        original_modules = sys.modules.get("weasyprint")
        sys.modules["weasyprint"] = fake_module
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                out = f.name
            try:
                assert generate_pdf_report(SAMPLE_HTML, out) is True
                assert "PingFang SC" in captured["html"]
            finally:
                os.unlink(out)
        finally:
            if original_modules is not None:
                sys.modules["weasyprint"] = original_modules
            else:
                sys.modules.pop("weasyprint", None)

    def test_failure_returns_false(self):
        """渲染异常时返回 False 而非抛异常"""
        import types
        fake_module = types.ModuleType("weasyprint")

        class _Boom:
            def __init__(self, string=None, **kw):
                raise RuntimeError("boom")

        fake_module.HTML = _Boom
        original_modules = sys.modules.get("weasyprint")
        sys.modules["weasyprint"] = fake_module
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                out = f.name
            try:
                assert generate_pdf_report(SAMPLE_HTML, out) is False
            finally:
                os.unlink(out)
        finally:
            if original_modules is not None:
                sys.modules["weasyprint"] = original_modules
            else:
                sys.modules.pop("weasyprint", None)

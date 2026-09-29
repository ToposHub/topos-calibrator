"""
预检结果翻译测试

验证 web/js/preflight-i18n.js 的结构与集成：
- 定义了 PREFLIGHT_I18N 接口（translateMessage / translateItemName）
- 关键后端消息有中文翻译（精确或正则覆盖）
- 检查项 item_id 均有中文名称
- index.html 在 main.js 之前引入该脚本
"""

import re
from pathlib import Path

WEB_DIR = Path(__file__).parent.parent.parent / "web"


def _read_js() -> str:
    return (WEB_DIR / "js" / "preflight-i18n.js").read_text(encoding="utf-8")


def _parse_message_keys(js: str):
    """提取 MESSAGES 字典的 key（单引号字符串行）"""
    keys = set()
    for m in re.finditer(r"^\s*'((?:[^'\\]|\\.)*)':\s*'", js, re.M):
        keys.add(m.group(1))
    return keys


def _parse_item_name_keys(js: str) -> set:
    keys = set()
    for m in re.finditer(r"^\s*'([a-z_0-9]+)':\s*'", js, re.M):
        keys.add(m.group(1))
    return keys


def _backend_messages() -> set:
    text = (WEB_DIR.parent / "src" / "workflows" / "preflight.py").read_text(encoding="utf-8")
    msgs = set()
    for m in re.finditer(r"message=f?\"((?:[^\"\\]|\\.)*)\"", text):
        msgs.add(m.group(1))
    for m in re.finditer(r"message=f?'((?:[^'\\]|\\.)*)'", text):
        msgs.add(m.group(1))
    return msgs


class TestPreflightI18nStructure:
    def test_defines_api(self):
        js = _read_js()
        assert "translateMessage" in js
        assert "translateItemName" in js
        assert "PREFLIGHT_I18N" in js

    def test_index_html_loads_script_before_main(self):
        text = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert text.find("js/preflight-i18n.js") != -1
        assert text.find("js/preflight-i18n.js") < text.find("js/main.js")

    def test_key_messages_translated(self):
        js = _read_js()
        keys = _parse_message_keys(js)
        # 用户可见的高频静态消息必须有翻译
        for required in (
            "Night Shift status unknown",
            "Could not enumerate displays",
            "Accessibility permission not granted",
            "System sleep disabled",
            "VCGT LUT is linear",
            "HDR/ACM status not fully detectable on macOS",
            "No correction file selected (recommended for colorimeters) - "
            "Select a CCSS/CCMX file appropriate for your display technology",
        ):
            assert required in keys, f"缺少静态翻译: {required}"

    def test_dynamic_patterns_present(self):
        js = _read_js()
        # 高频动态消息必须有正则覆盖
        for pattern in (
            r"Custom ICC profile loaded",
            r"Display index",
            r"USB permission",
            r"found: ",
        ):
            assert pattern in js, f"缺少正则覆盖: {pattern}"

    def test_item_names_cover_backend_items(self):
        js = _read_js()
        names = _parse_item_name_keys(js)
        backend_ids = set(re.findall(
            r'item_id = "([a-z_0-9]+)"',
            (WEB_DIR.parent / "src" / "workflows" / "preflight.py").read_text(encoding="utf-8"),
        ))
        argyll_ids = {"argyll_spotread", "argyll_dispcal", "argyll_targen",
                      "argyll_colprof", "argyll_collink", "argyll_dispwin",
                      "argyll_ccxxmake", "argyll_version"}
        missing = (backend_ids | argyll_ids) - names
        assert not missing, f"检查项缺少中文名称: {missing}"

    def test_backend_messages_have_exact_or_pattern_coverage(self):
        """静态后端消息应被精确翻译覆盖（含插值的走正则，不在此强制）"""
        js = _read_js()
        keys = _parse_message_keys(js)
        uncovered = []
        for msg in _backend_messages():
            if "{" in msg:
                continue  # 动态消息由正则覆盖，人工维护
            if msg not in keys:
                uncovered.append(msg)
        # 允许少量遗漏，但核心集合必须覆盖（防止回归）
        critical = [m for m in uncovered if m in (
            "Instrument adapter not provided",
            "Instrument adapter not provided, check skipped",
            "Night Shift status unknown",
            "System sleep disabled",
            "Could not verify USB permission",
        )]
        assert not critical, f"关键消息未覆盖: {critical}"

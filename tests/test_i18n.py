"""
i18n 模块单元测试

验证 src/i18n 的核心行为：
- 中文原文为 key 的翻译查找
- 缺词条时优雅回退（返回中文原文）
- {name} 占位符插值
- 语言切换与持久化隔离（测试中不写 QSettings）
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).parent.parent / "src"


def _load_i18n_module():
    """以独立模块方式加载 src/i18n/__init__.py（persist=False 隔离 QSettings）"""
    spec = importlib.util.spec_from_file_location(
        "topos_i18n_test", SRC_DIR / "i18n" / "__init__.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def i18n():
    module = _load_i18n_module()
    module.set_language("zh-CN", persist=False)
    yield module
    module.set_language("zh-CN", persist=False)


class TestLanguageAvailability:
    def test_default_language_is_zh(self, i18n):
        assert i18n.get_language() == "zh-CN"

    def test_supported_languages(self, i18n):
        codes = [code for code, _ in i18n.SUPPORTED_LANGUAGES]
        assert "zh-CN" in codes
        assert "en" in codes

    def test_unavailable_language_rejected(self, i18n):
        assert i18n.set_language("xx-YY", persist=False) is False
        assert i18n.get_language() == "zh-CN"

    def test_available_language_accepted(self, i18n):
        assert i18n.set_language("en", persist=False) is True
        assert i18n.get_language() == "en"

    def test_detect_system_language_returns_supported_code(self, i18n):
        assert i18n.detect_system_language() in {"zh-CN", "en"}

    def test_first_launch_uses_detected_language_and_persists(self, i18n, monkeypatch):
        class FakeSettings:
            def __init__(self):
                self.values = {}

            def value(self, key, default=None):
                return self.values.get(key, default)

            def setValue(self, key, value):
                self.values[key] = value

        settings = FakeSettings()
        monkeypatch.setattr(i18n, "_settings", lambda: settings)
        monkeypatch.setattr(i18n, "detect_system_language", lambda: "en")

        i18n.init_from_settings()

        assert i18n.get_language() == "en"
        assert settings.values["language"] == "en"

    def test_saved_language_overrides_system_detection(self, i18n, monkeypatch):
        class FakeSettings:
            def value(self, key, default=None):
                return "zh-CN"

            def setValue(self, key, value):
                raise AssertionError("saved language should not be rewritten")

        monkeypatch.setattr(i18n, "_settings", lambda: FakeSettings())
        monkeypatch.setattr(i18n, "detect_system_language", lambda: "en")

        i18n.init_from_settings()

        assert i18n.get_language() == "zh-CN"


class TestTranslation:
    def test_chinese_is_identity_in_zh(self, i18n):
        assert i18n.t("已连接到后端") == "已连接到后端"

    def test_translates_in_en(self, i18n):
        i18n.set_language("en", persist=False)
        result = i18n.t("已连接到后端")
        assert result == "Connected to backend"

    def test_missing_key_falls_back_to_chinese(self, i18n):
        i18n.set_language("en", persist=False)
        # 任何未收录的中文原文都应原样返回，而不是报错或显示 key 名
        assert i18n.t("这是一个不存在的词条XYZ") == "这是一个不存在的词条XYZ"

    def test_placeholder_interpolation(self, i18n):
        assert i18n.t("已加载 {n} 条记录", n=5) == "已加载 5 条记录"

    def test_placeholder_in_en(self, i18n):
        i18n.set_language("en", persist=False)
        result = i18n.t("已加载 {n} 条记录", n=5)
        assert "{n}" not in result

    def test_non_string_passthrough(self, i18n):
        assert i18n.t(123) == 123
        assert i18n.t(None) is None


class TestLocaleFiles:
    def test_en_locale_file_exists(self):
        assert (SRC_DIR / "i18n" / "locales" / "en.json").exists()

    def test_en_locale_is_valid_json_dict(self):
        import json

        data = json.loads((SRC_DIR / "i18n" / "locales" / "en.json").read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in data.items())

    def test_web_en_locale_is_valid_js_dict(self):
        """Web 端语言包必须能被解析为 {中文: 英文} 映射（用括号配对粗校验）"""
        text = (Path(__file__).parent.parent / "web" / "js" / "locales" / "en.js").read_text(
            encoding="utf-8"
        )
        assert "I18N.register('en'" in text
        assert text.count("{") == text.count("}")


class TestWebI18nJs:
    def test_i18n_core_exists(self):
        path = Path(__file__).parent.parent / "web" / "js" / "i18n.js"
        text = path.read_text(encoding="utf-8")
        for api in ("register", "setLanguage", "getLanguage", "t(", "onChange", "MutationObserver"):
            assert api in text, f"i18n.js 缺少 API: {api}"
        assert "var DEFAULT_LANG = 'en'" in text
        assert "data-tooltip" in text

    def test_native_language_sync_hooks_exist(self):
        text = (Path(__file__).parent.parent / "web" / "js" / "main.js").read_text(encoding="utf-8")
        assert "languageReady" in text
        assert "requestLanguage" in text

    def test_index_html_loads_i18n(self):
        text = (Path(__file__).parent.parent / "web" / "index.html").read_text(encoding="utf-8")
        # i18n 核心必须先于语言包与业务脚本加载
        assert text.find("js/i18n.js") < text.find("js/locales/en.js")
        assert text.find("js/i18n.js") < text.find("js/main.js")

    def test_comparison_html_loads_i18n(self):
        text = (Path(__file__).parent.parent / "web" / "comparison.html").read_text(encoding="utf-8")
        assert "js/i18n.js" in text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

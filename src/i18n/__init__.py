"""
Topos Calibrator - 轻量国际化 (i18n) 模块

与 Web 端 (web/js/i18n.js) 同一套设计：
- 以「中文原文」为翻译 key，缺词条时优雅回退显示中文原文；
- 语言包为 JSON 文件，位于 src/i18n/locales/<lang>.json；
- 语言偏好通过 QSettings 持久化，Web 端切换语言时经 backend.setLanguage 同步到这里。

用法：
    from src import i18n
    i18n.set_language('en')
    i18n.t('已连接到后端')            # => 'Connected to backend'
    i18n.t('已加载 {n} 条记录', n=3)  # => 'Loaded 3 records'

新增语言：在 src/i18n/locales/ 下新增 <lang>.json（{ "中文原文": "译文" }），
并在 SUPPORTED_LANGUAGES 登记，再同步到 web/js/i18n.js 的 supportedLanguages。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

LOCALES_DIR = Path(__file__).parent / "locales"

# 支持的语言（代码, 显示名）。新增语言时在此登记。
SUPPORTED_LANGUAGES: list[tuple[str, str]] = [
    ("zh-CN", "简体中文"),
    ("en", "English"),
]

DEFAULT_LANGUAGE = "zh-CN"

_lock = threading.Lock()
_current_lang: str = DEFAULT_LANGUAGE
_current_dict: dict[str, str] = {}
_loaded: dict[str, dict[str, str]] = {}


def _settings():
    """延迟导入 QSettings，方便无 GUI 环境下做单元测试。"""
    try:
        from PyQt6.QtCore import QSettings

        return QSettings("topos", "ToposCalibrator")
    except ImportError:
        return None


def detect_system_language() -> str:
    """Return Chinese for Chinese system locales and English for everything else."""
    try:
        from PyQt6.QtCore import QLocale

        locale_name = QLocale.system().name().lower()
    except ImportError:
        locale_name = ""

    if locale_name.startswith("zh"):
        return "zh-CN"
    return "en"


def _load_locale(lang: str) -> dict[str, str]:
    """加载语言包文件；zh-CN（源语言）或缺失文件返回空字典。"""
    if lang in _loaded:
        return _loaded[lang]
    path = LOCALES_DIR / f"{lang}.json"
    data: dict[str, str] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    _loaded[lang] = data
    return data


def is_language_available(lang: str) -> bool:
    return any(code == lang for code, _ in SUPPORTED_LANGUAGES)


def get_language() -> str:
    return _current_lang


def set_language(lang: str, persist: bool = True) -> bool:
    """切换语言；persist=False 时仅影响当前进程（供测试使用）。"""
    global _current_lang, _current_dict
    if not is_language_available(lang):
        return False
    with _lock:
        _current_lang = lang
        _current_dict = _load_locale(lang)
    if persist:
        s = _settings()
        if s is not None:
            s.setValue("language", lang)
    return True


def init_from_settings() -> None:
    """Restore a saved language, or detect the system language on first launch."""
    s = _settings()
    if s is None:
        set_language(detect_system_language(), persist=False)
        return

    stored = s.value("language", None)
    if isinstance(stored, str) and is_language_available(stored):
        set_language(stored, persist=False)
        return

    # Persist the first-launch decision so a later manual language choice is stable.
    set_language(detect_system_language(), persist=True)


def t(text: str, **params: Any) -> str:
    """
    翻译一个字符串。key 即中文原文；缺词条时原样返回（优雅回退）。

    占位符采用 {name} 形式（与 Web 端一致）：t('已加载 {n} 条', n=3)。
    """
    if not isinstance(text, str):
        return text
    translated = _current_dict.get(text, text)
    if params:
        for key, value in params.items():
            translated = translated.replace("{" + key + "}", str(value))
    return translated

"""
使用文档内容测试

验证 web/js/docs-content.js 的结构与中英一致性：
- 两种语言都定义了章节
- 章节按 id 一一对应（语言切换时按 id 恢复阅读位置）
- 每章必填字段齐全（id / icon / title / html）
- index.html 正确引入弹窗与脚本
"""

import re
from pathlib import Path

WEB_DIR = Path(__file__).parent.parent.parent / "web"


def _parse_docs_content():
    """从 docs-content.js 提取章节结构（不依赖 JS 运行时，用正则粗解析）"""
    text = (WEB_DIR / "js" / "docs-content.js").read_text(encoding="utf-8")
    assert "DOCS_CONTENT" in text

    books = {}
    # 语言块以 'zh-CN': { / 'en': { 开始，章节以 id: 'xxx', 描述
    for lang_match in re.finditer(r"'(zh-CN|en)':\s*\{", text):
        lang = lang_match.group(1)
        # 在该语言块内收集所有章节 id 与标题（顺序出现）
        tail = text[lang_match.end():]
        # 语言块在下一语言块或文件尾结束
        next_lang = re.search(r"'(?:zh-CN|en)':\s*\{", tail)
        block = tail[: next_lang.start()] if next_lang else tail
        chapters = re.findall(
            r"id:\s*'([\w-]+)',\s*\n\s*icon:\s*'(?:[^']*)',\s*\n\s*title:\s*'((?:[^'\\]|\\.)*)'",
            block,
        )
        books[lang] = chapters
    return books


class TestDocsContentStructure:
    def test_both_languages_present(self):
        books = _parse_docs_content()
        assert set(books.keys()) == {"zh-CN", "en"}

    def test_chapters_not_empty(self):
        books = _parse_docs_content()
        assert len(books["zh-CN"]) >= 10, "中文文档章节过少"
        assert len(books["en"]) >= 10, "英文文档章节过少"

    def test_chapter_ids_match_across_languages(self):
        books = _parse_docs_content()
        zh_ids = [cid for cid, _ in books["zh-CN"]]
        en_ids = [cid for cid, _ in books["en"]]
        assert zh_ids == en_ids, "中英章节 id 或顺序不一致"

    def test_chapter_ids_unique(self):
        books = _parse_docs_content()
        for lang, chapters in books.items():
            ids = [cid for cid, _ in chapters]
            assert len(ids) == len(set(ids)), f"{lang} 存在重复章节 id"


class TestDocsContentIntegration:
    def test_index_html_has_docs_modal(self):
        text = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert 'id="docs-modal-overlay"' in text
        assert 'id="docs-sidebar"' in text
        assert 'id="docs-content"' in text
        # 标题旁的语言选择框
        assert 'id="docs-lang-select"' in text

    def test_index_html_loads_docs_scripts(self):
        text = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        # docs-content.js 必须先于 main.js 加载
        assert text.find("js/docs-content.js") != -1
        assert text.find("js/docs-content.js") < text.find("js/main.js")

    def test_main_js_wires_docs(self):
        text = (WEB_DIR / "js" / "main.js").read_text(encoding="utf-8")
        for fn in ("showDocsModal", "closeDocsModal", "renderDocsSidebar",
                   "renderDocsChapter", "initDocsModalEvents", "getDocsLanguage"):
            assert f"function {fn}" in text, f"main.js 缺少函数: {fn}"
        # 菜单「使用文档」必须打开弹窗（而非开发中提示）
        assert "showDocsModal();" in text
        assert "使用文档功能开发中" not in text
        # 语言选择框必须联动界面语言切换
        assert "docs-lang-select" in text
        assert "switchLanguage(this.value)" in text

    def test_css_has_docs_styles(self):
        text = (WEB_DIR / "css" / "style.css").read_text(encoding="utf-8")
        for cls in (".docs-modal", ".docs-sidebar", ".docs-nav-item", ".docs-chapter-body",
                    ".doc-tip", ".doc-warn", ".docs-footer-nav", ".docs-lang-select"):
            assert cls in text, f"style.css 缺少样式: {cls}"

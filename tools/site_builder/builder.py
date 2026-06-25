"""build_site — 純函數：Brief 語料 → in-memory {path: html} map。

無 git / LLM / 網路 / 檔案副作用。markdown→HTML 用 Python（markdown + Jinja2）。

report_md 源自 pipeline 對**外部文章標題/URL**的 LLM 摘要（不可信內容），且站台
公開可見，故 markdown 輸出在進模板前先過 nh3 sanitizer（allowlist 標籤 + 限定
http/https/mailto scheme），杜絕 raw HTML 注入與 javascript: href 造成的 stored XSS。
python-markdown 官方明言它不是 sanitizer，消毒責任在此。
"""

from __future__ import annotations

import markdown as _markdown
import nh3

from .template import render_index

# markdown('extra') 可產生的結構標籤；不含 img（避免 onerror/追蹤像素）。
_ALLOWED_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "a", "code", "pre", "blockquote",
    "em", "strong", "br", "hr",
    "table", "thead", "tbody", "tr", "th", "td",
}
_ALLOWED_ATTRS = {"a": {"href", "title"}}
_ALLOWED_SCHEMES = {"http", "https", "mailto"}


def _sanitize(body_html: str) -> str:
    """以 allowlist 消毒 markdown 輸出，移除非白名單標籤/屬性與危險 URL scheme。"""
    return nh3.clean(
        body_html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        url_schemes=_ALLOWED_SCHEMES,
    )


def build_site(report_md: str, date: str) -> dict[str, str]:
    """給定最新一天的 Brief report markdown 與日期，回傳含首頁的站台 map。

    此切片只產出單一首頁（index.html）。回傳純記憶體 dict，不落盤。
    """
    body_html = _sanitize(_markdown.markdown(report_md or "", extensions=["extra"]))
    index_html = render_index(body_html=body_html, date=date)
    return {"index.html": index_html}

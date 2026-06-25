"""build_site — 純函數：Brief 語料 → in-memory {path: html} map。

無 git / LLM / 網路 / 檔案副作用。markdown→HTML 用 Python（markdown + Jinja2）。
"""

from __future__ import annotations

import markdown as _markdown

from .template import render_index


def build_site(report_md: str, date: str) -> dict[str, str]:
    """給定最新一天的 Brief report markdown 與日期，回傳含首頁的站台 map。

    此切片只產出單一首頁（index.html）。回傳純記憶體 dict，不落盤。
    """
    body_html = _markdown.markdown(report_md or "", extensions=["extra"])
    index_html = render_index(body_html=body_html, date=date)
    return {"index.html": index_html}

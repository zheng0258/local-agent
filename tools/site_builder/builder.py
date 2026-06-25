"""build_site_archive / build_site — 純函數：Brief 語料 → in-memory {path: html} map。

build_site_archive 吃完整歷史天（newest first），產首頁 + 每天一頁存檔頁（全量重建）；
build_site 為單天便利包裝。無 git / LLM / 網路 / 檔案副作用。markdown→HTML 用
Python（markdown + Jinja2）。

report_md 源自 pipeline 對**外部文章標題/URL**的 LLM 摘要（不可信內容），且站台
公開可見，故 markdown 輸出在進模板前先過 nh3 sanitizer（allowlist 標籤 + 限定
http/https/mailto scheme），杜絕 raw HTML 注入與 javascript: href 造成的 stored XSS。
python-markdown 官方明言它不是 sanitizer，消毒責任在此。
"""

from __future__ import annotations

from typing import Iterable, Tuple

import markdown as _markdown
import nh3

from .template import ArchiveLink, render_archive, render_index

# (date, report_md) 對；newest first。純記憶體語料，不碰檔案。
DayBrief = Tuple[str, str]

# markdown('extra') 可產生的結構標籤；不含 img（避免 onerror/追蹤像素）。
_ALLOWED_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "a",
    "code",
    "pre",
    "blockquote",
    "em",
    "strong",
    "br",
    "hr",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
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


def _render_body(report_md: str) -> str:
    """markdown → sanitized HTML（所有 report 內文唯一渲染路徑）。"""
    return _sanitize(_markdown.markdown(report_md or "", extensions=["extra"]))


def _archive_href(date: str) -> str:
    """單天存檔頁相對路徑（index.html 與 archive map key 共用此規則）。"""
    return f"archive/{date}.html"


def build_site(report_md: str, date: str) -> dict[str, str]:
    """給定最新一天的 Brief report markdown 與日期，回傳含首頁的站台 map。

    單天便利包裝：等同 build_site_archive([(date, report_md)]) 但不產存檔頁。
    回傳純記憶體 dict，不落盤。
    """
    index_html = render_index(body_html=_render_body(report_md), date=date)
    return {"index.html": index_html}


def build_site_archive(days: Iterable[DayBrief]) -> dict[str, str]:
    """純函數：完整歷史語料 → in-memory 站台 map（首頁 + 每天一頁存檔頁）。

    `days` 為 (date, report_md) 串，newest first。回傳：
      - index.html：最新天內文 + 定位句 + 連往全部存檔天的導覽列
      - archive/<date>.html：每天一頁，標示日期、渲染該天 report.md
    存檔頁數 == 輸入天數。空語料則只回首頁。無 git / LLM / 網路 / 檔案副作用。
    """
    day_list = list(days)
    site: dict[str, str] = {}

    for date, report_md in day_list:
        site[_archive_href(date)] = render_archive(
            body_html=_render_body(report_md), date=date
        )

    links = [ArchiveLink(date=d, href=_archive_href(d)) for d, _ in day_list]
    if day_list:
        latest_date, latest_md = day_list[0]
        latest_body = _render_body(latest_md)
    else:
        latest_date, latest_body = "", ""
    site["index.html"] = render_index(
        body_html=latest_body, date=latest_date, archive_links=links
    )
    return site

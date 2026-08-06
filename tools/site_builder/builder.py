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

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

import markdown as _markdown
import nh3

from .status import SystemStatus, render_status_section
from .template import ArchiveLink, render_archive, render_archive_index, render_index

# (date, report_md) 對；newest first。純記憶體語料，不碰檔案。
DayBrief = Tuple[str, str]


@dataclass(frozen=True)
class Narrative:
    """手寫雙語專案敘事的 in-memory 載體（純資料，非內容本身）。

    `zh_md` / `en_md` 為兩版手寫 markdown。純 builder 收它為記憶體引數（不碰檔案）；
    薄 loader (load_narrative) 才從 config 檔讀出並切成這個型別。
    """

    zh_md: str
    en_md: str


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


# 首頁存檔清單只列近 N 筆（最新），其餘移到「全部存檔」頁（archive/index.html）。
_HOME_ARCHIVE_LIMIT = 30


def _group_by_month(dates: list[str]) -> list[tuple[str, list[ArchiveLink]]]:
    """日期串（newest first）按 YYYY-MM 分組 → [(月份, [ArchiveLink])]（newest first）。

    「全部存檔」頁位於 archive/ 目錄內，故每日連結為同目錄相對路徑 `<date>.html`
    （非首頁用的 `archive/<date>.html`）。
    """
    groups: list[tuple[str, list[ArchiveLink]]] = []
    index: dict[str, list[ArchiveLink]] = {}
    for d in dates:
        month = d[:7]
        if month not in index:
            index[month] = []
            groups.append((month, index[month]))
        index[month].append(ArchiveLink(date=d, href=f"{d}.html"))
    return groups


def build_site(report_md: str, date: str) -> dict[str, str]:
    """給定最新一天的 Brief report markdown 與日期，回傳含首頁的站台 map。

    單天便利包裝：等同 build_site_archive([(date, report_md)]) 但不產存檔頁。
    回傳純記憶體 dict，不落盤。
    """
    index_html = render_index(body_html=_render_body(report_md), date=date)
    return {"index.html": index_html}


def build_site_archive(
    days: Iterable[DayBrief],
    narrative: Optional[Narrative] = None,
    latest_tldr: Optional[str] = None,
    status: Optional[SystemStatus] = None,
) -> dict[str, str]:
    """純函數：完整歷史語料 → in-memory 站台 map（首頁 + 每天一頁存檔頁）。

    `days` 為 (date, report_md) 串，newest first。`narrative` 為手寫雙語專案敘事
    （in-memory；None 時首頁不含敘事區，向後相容 #6/#7）。
    `status` 為已計算的系統狀態 DTO（in-memory；None 時首頁不含系統狀態區，歷史缺失時
    優雅降級，向後相容）。回傳：
      - index.html：定位句 hero（含「關於本專案」按鈕 → overlay 專案描述）+ 今日重點 +
        最新天內文 + 存檔導覽列（只列近 30 筆 + 「查看全部存檔」入口）
      - archive/index.html：全部存檔頁，按月分組列出每一天
      - archive/<date>.html：每天一頁，標示日期、渲染該天 report.md（維持繁中）
    單天存檔頁數 == 輸入天數。空語料則只回首頁。無 git / LLM / 網路 / 檔案副作用。
    """
    day_list = list(days)
    site: dict[str, str] = {}

    for date, report_md in day_list:
        site[_archive_href(date)] = render_archive(
            body_html=_render_body(report_md), date=date
        )

    links = [ArchiveLink(date=d, href=_archive_href(d)) for d, _ in day_list]
    home_links = links[:_HOME_ARCHIVE_LIMIT]  # 首頁只列近 30 筆
    if day_list:
        latest_date, latest_md = day_list[0]
        latest_body = _render_body(latest_md)
        # 全部存檔頁（按月分組）；首頁「查看全部存檔」導向它
        site["archive/index.html"] = render_archive_index(
            _group_by_month([d for d, _ in day_list])
        )
    else:
        latest_date, latest_body = "", ""

    # 專案描述以繁中為主（不再中英切換）；收進 overlay，不直接顯示於頁面主流程。
    narrative_html = (
        _render_body(narrative.zh_md) if narrative is not None else ""
    )

    # 今日重點（繁中）：走與 report 一致的消毒路徑（源自 LLM 對不可信內容的摘要）。
    tldr_html = _render_body(latest_tldr) if latest_tldr else ""

    # 系統狀態區為**內部產生**的可信 markup（非外部不可信內容），不過 markdown／消毒。
    status_html = render_status_section(status) if status is not None else ""

    site["index.html"] = render_index(
        body_html=latest_body,
        date=latest_date,
        archive_links=home_links,
        full_archive_href="archive/index.html" if day_list else "",
        narrative_html=narrative_html,
        tldr_html=tldr_html,
        status_html=status_html,
    )
    return site

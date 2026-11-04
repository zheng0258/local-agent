"""community_view — 「💬 社群觀點」確定性組裝（純函數，無 LLM、無 I/O）。

核心原則與 links.py 相同：**社群觀點是資料，不是 LLM 輸出。** 唯一來源是 enrich 依
真實留言產生的 comment_summary，由 Python 依文章附上，LLM 寫的一律丟棄。

10-19 至 11-04 掃描：digest 有 53 則社群觀點沒有依據——替無留言的文章編造、外洩
`[comment_summary 的內容]` 等佔位字、貼上別篇的留言（11-04 OpenAI Codex ← Gitbook）；
另有 8 則有留言卻漏掉（見 ADR 0006 修訂）。
"""

from __future__ import annotations

import re

from .config import FETCH_STEPS
from .schemas import SourceCompress

VIEW_PREFIX = "💬 社群觀點："
_REPORT_VIEW_INDENT = "   "
# 容忍 LLM 的各種寫法：有無 emoji / 粗體 / 清單標記、全半形冒號；從標記刪到行尾。
_VIEW_RE = re.compile(
    r"[ \t]*(?:[-*•][ \t]+)?\**(?:💬[ \t]*)?\**社群觀點\**[ \t]*[：:].*$"
)
# 報告的文章列：數字或符號清單項內的第一個 http(s) 連結（表格列不算）。
_LIST_ITEM_LINK_RE = re.compile(
    r"^\s*(?:\d+\.|[-*•])\s+.*?\]\((https?://[^)\s]+)\)"
)


def _strip_line(line: str) -> str | None:
    """移除單行內的社群觀點；整行都是社群觀點時回 None（代表刪除該行）。"""
    stripped, count = _VIEW_RE.subn("", line)
    if not count:
        return line
    return stripped.rstrip() or None


def strip_community_view(text: str) -> str:
    """移除文字中 LLM 寫的社群觀點（純函數）。"""
    kept = (_strip_line(line) for line in text.split("\n"))
    return "\n".join(line for line in kept if line is not None).rstrip()


def attach_community_view(summary: str, comment_summary: str) -> str:
    """丟棄 summary 內 LLM 寫的社群觀點，有真實留言摘要才由程式附上（純函數）。"""
    body = strip_community_view(summary)
    return f"{body}\n{VIEW_PREFIX}{comment_summary}" if comment_summary else body


def comments_by_url(enrich_data: dict | None) -> dict[str, str]:
    """從 enrich 結果取出 {url: comment_summary}（只收有留言摘要的文章）。"""
    data = enrich_data or {}
    return {
        article.url: article.comment_summary
        for src in FETCH_STEPS
        for article in SourceCompress.from_dict(data.get(src, {})).articles
        if article.url and article.comment_summary
    }


def reconcile_report_views(report_md: str, comments: dict[str, str]) -> str:
    """讓 report 的社群觀點只反映 comments（純函數、冪等）。

    刪除 LLM 寫的所有社群觀點行，再把真實留言摘要插到該 URL 第一個清單項的下一行。
    表格列不動（備註欄不是社群觀點行，改寫會破壞表格）。
    """
    output: list[str] = []
    placed: set[str] = set()
    for line in report_md.split("\n"):
        if line.lstrip().startswith("|"):
            output.append(line)
            continue
        kept = _strip_line(line)
        if kept is None:
            continue
        output.append(kept)
        match = _LIST_ITEM_LINK_RE.match(kept)
        url = match.group(1) if match else ""
        if url in comments and url not in placed:
            placed.add(url)
            output.append(f"{_REPORT_VIEW_INDENT}{VIEW_PREFIX}{comments[url]}")
    return "\n".join(output)

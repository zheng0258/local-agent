"""report_repair — report.md 連結的確定性修復（純函數，無 LLM）。

資料品質關卡（deploy_gate）偵測到 leftover_token / unlinked_articles 時的第一道
修復：URL 是資料不是 LLM 輸出（見 links.py），所以壞掉的連結幾乎都能從可信輸入
找回來，不必動用 LLM。

1. **token 重替換**：以 ReportStep 同一套確定性 id 枚舉（`_index_urls(enrich, 去重
   digests)`）重算 url_by_id，對 report.md 重跑 `substitute_md_link_tokens` +
   `strip_invalid_md_links`——修好舊版 links 漏接的形狀（標題含 [..]、漏寫 [ 等）。
2. **標題比對**：已被降級成純文字、沒有 token 可依的文章列，以列內標題比對
   enrich / digest 的 title（含 original_title），找到**唯一** URL 才補成
   `[標題](url)`；不唯一或比不到就不動（寧缺勿錯）。

10-17 以同一套邏輯手動修好 09-24 / 09-28 / 10-16 三份報告，id 對照全數吻合。
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from . import links
from .invariants import ARTICLE_MARKER_RE, is_unlinked_article_row
from .schemas import Digest
from .steps.report import _index_urls

# 清單項：標記之後、熱度標記之前的文字即標題
_LIST_TITLE_RE = re.compile(r"^(\s*(?:\d+\.|[-*•])\s+)(.+?)(\s*" + ARTICLE_MARKER_RE.pattern + ")")
# 表格列：第一個儲存格（去掉熱度標記）即標題
_TABLE_FIRST_CELL_RE = re.compile(r"^(\s*\|\s*)([^|]+?)(\s*\|)")
# 子字串比對的最短標題長度：太短的標題（如「AI」）容易誤中別篇
_MIN_CONTAIN_CHARS = 8


def _dedupe_digests(digests: list[dict]) -> list[dict]:
    """與 ReportStep._produce 相同的去重（同 URL 只留第一筆），確保 id 枚舉一致。"""
    seen: set[str] = set()
    out: list[dict] = []
    for d in digests:
        url = Digest.from_dict(d).url
        if url and url not in seen:
            seen.add(url)
            out.append(d)
    return out


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[\s*\[\]`_]+", "", folded)


def _title_index(enrich: dict, digests: list[dict]) -> list[tuple[str, str]]:
    """(正規化標題, url) 清單：enrich 各來源文章的 title / original_title + digest title。"""
    pairs: list[tuple[str, str]] = []
    for section in enrich.values():
        if not isinstance(section, dict):
            continue
        for art in section.get("articles", []):
            if not isinstance(art, dict) or not links.is_valid_url(art.get("url", "")):
                continue
            for key in ("title", "original_title"):
                title = art.get(key)
                if isinstance(title, str) and title.strip():
                    pairs.append((_norm(title), art["url"]))
    for d in digests:
        view = Digest.from_dict(d)
        title = d.get("title") if isinstance(d, dict) else None
        if isinstance(title, str) and title.strip() and links.is_valid_url(view.url):
            pairs.append((_norm(title), view.url))
    return [(t, u) for t, u in pairs if t]


def _match_url(raw_title: str, index: list[tuple[str, str]]) -> str | None:
    """完全相符優先；否則退回子字串相符。任一層唯一才回傳 URL。"""
    key = _norm(raw_title)
    if not key:
        return None
    exact = {u for t, u in index if t == key}
    if exact:
        return exact.pop() if len(exact) == 1 else None
    if len(key) < _MIN_CONTAIN_CHARS:
        return None
    contained = {
        u for t, u in index if len(t) >= _MIN_CONTAIN_CHARS and (t in key or key in t)
    }
    return contained.pop() if len(contained) == 1 else None


def _relink_line(line: str, index: list[tuple[str, str]]) -> str:
    if not is_unlinked_article_row(line):
        return line
    m = _LIST_TITLE_RE.match(line)
    if m:
        prefix, title = m.group(1), m.group(2).strip()
    else:
        m = _TABLE_FIRST_CELL_RE.match(line)
        if not m:
            return line
        prefix = m.group(1)
        title = ARTICLE_MARKER_RE.sub("", m.group(2)).strip()
    url = _match_url(title, index)
    if not url or not title:
        return line
    start = line.find(title, len(prefix))
    if start < 0:
        return line
    return f"{line[:start]}[{title}]({url}){line[start + len(title):]}"


def relink_report(report_md: str, enrich: dict, digests: list[dict]) -> str:
    """回傳修復後的 report markdown（不 mutate 輸入；無可修處則原樣回傳）。"""
    deduped = _dedupe_digests(digests)
    url_by_id = {i: u for u, i in _index_urls(enrich, deduped).items()}
    substituted = links.substitute_md_link_tokens(report_md, url_by_id)
    cleaned, _removed = links.strip_invalid_md_links(substituted)
    index = _title_index(enrich, deduped)
    # splitlines(keepends) 保留原行尾，未變動的行逐字不變
    return "".join(
        _relink_line(line.rstrip("\n"), index) + ("\n" if line.endswith("\n") else "")
        for line in cleaned.splitlines(keepends=True)
    )


def load_link_sources(steps_dir: Path) -> tuple[dict, list[dict]] | None:
    """讀修復依據：enrich.json + digest.json["digests"]（缺檔 / 壞檔 → None）。"""
    try:
        enrich = json.loads((steps_dir / "enrich.json").read_text(encoding="utf-8"))
        digest_doc = json.loads((steps_dir / "digest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    digests = digest_doc.get("digests") if isinstance(digest_doc, dict) else None
    if not isinstance(enrich, dict) or not isinstance(digests, list):
        return None
    return enrich, digests

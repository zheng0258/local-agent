"""Hatena Bookmark IT fetcher。使用 RSS feed 取得文章清單。"""

from __future__ import annotations

import defusedxml.ElementTree as ET

from . import rss_common

# RSS 端點（AI 子類別無獨立 RSS，ai.rss 為 404，統一用 IT 類別）
_RSS_URLS = [
    "https://b.hatena.ne.jp/hotentry/it.rss",
]

_NS = {
    "rss": "",
    "hatena": "http://www.hatena.ne.jp/info/xmlns#",
}


def fetch() -> list[dict]:
    """
    抓取 Hatena Bookmark IT 熱門文章（RSS）。
    回傳格式：[{"title", "url", "bookmarks", "description"}, ...]
    共用 rss_common（certifi SSL + defusedxml），不再用 CERT_NONE / xml.etree。
    """
    articles: list[dict] = []
    for url in _RSS_URLS:
        try:
            articles.extend(_parse_rss(rss_common.fetch_feed(url)))
        except Exception as e:
            articles.append({"error": str(e), "source": url})
    return articles


_HATENA_NS = "http://www.hatena.ne.jp/info/xmlns#"
_RSS1_NS = "http://purl.org/rss/1.0/"   # Hatena 使用 RSS 1.0 (RDF)
_ATOM_NS = "http://www.w3.org/2005/Atom"


def _parse_rss(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    articles = []

    # 依優先順序嘗試各格式的 item/entry 元素
    candidates = [
        f"{{{_RSS1_NS}}}item",   # RSS 1.0 (RDF) — Hatena 使用
        "item",                  # RSS 2.0（無 namespace）
        f"{{{_ATOM_NS}}}entry",  # Atom
        "entry",
    ]
    items = []
    for tag in candidates:
        items = list(root.iter(tag))
        if items:
            break

    for item in items:
        def _text(*tags: str) -> str:
            for tag in tags:
                v = item.findtext(tag)
                if v:
                    return v.strip()
            return ""

        title = _text(f"{{{_RSS1_NS}}}title", "title", f"{{{_ATOM_NS}}}title")
        link = _text(f"{{{_RSS1_NS}}}link", "link")
        if not link:
            link_el = item.find(f"{{{_ATOM_NS}}}link")
            if link_el is not None:
                link = link_el.get("href", "")

        bk_el = item.find(f"{{{_HATENA_NS}}}bookmarkcount")
        bookmarks = int(bk_el.text) if bk_el is not None and bk_el.text else 0

        desc = _text(
            f"{{{_RSS1_NS}}}description", "description",
            f"{{{_ATOM_NS}}}summary",
        )
        articles.append({
            "title": title,
            "url": link,
            "bookmarks": bookmarks,
            "description": desc[:rss_common.DESCRIPTION_MAX_CHARS],
        })
    return articles

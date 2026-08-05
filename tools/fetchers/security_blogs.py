"""Security blogs fetcher（aikido.dev、wiz.io）。使用 RSS feed 取得文章清單。

兩站皆提供標準 RSS 2.0 feed（調查見 docs/adr/0003），
不再依賴 playwright DOM 抓取。
"""

from __future__ import annotations

import defusedxml.ElementTree as ET

from . import rss_common

_SOURCES: list[dict] = [
    {"feed_url": "https://www.aikido.dev/blog/rss.xml", "source": "aikido.dev"},
    {"feed_url": "https://www.wiz.io/feed/rss.xml", "source": "wiz.io"},
]

_MAX_ARTICLES_PER_SOURCE = 10
_DESCRIPTION_MAX_CHARS = rss_common.DESCRIPTION_MAX_CHARS


def _fetch_articles(source: dict) -> list[dict]:
    try:
        xml_bytes = rss_common.fetch_feed(source["feed_url"])
        articles = _parse_rss(xml_bytes)[:_MAX_ARTICLES_PER_SOURCE]
        return [{**a, "source": source["source"]} for a in articles]
    except Exception as e:
        return [{"source": source["source"], "error": str(e)}]


def _parse_rss(xml_bytes: bytes) -> list[dict]:
    """解析 RSS 2.0 feed，回傳 [{"title", "url", "description"}, ...]。"""
    root = ET.fromstring(xml_bytes)
    articles: list[dict] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        articles.append(
            {
                "title": title,
                "url": link,
                "description": description[:_DESCRIPTION_MAX_CHARS],
            }
        )
    return articles


def fetch() -> list[dict]:
    """
    抓取 aikido.dev 與 wiz.io 最新文章（RSS feed）。
    回傳格式：[{"title", "url", "source", "description"}, ...]
    """
    articles: list[dict] = []
    for source in _SOURCES:
        articles.extend(_fetch_articles(source))
    return articles

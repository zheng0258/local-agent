"""Security blogs fetcher（aikido.dev、wiz.io）。使用 RSS feed 取得文章清單。

兩站皆提供標準 RSS 2.0 feed（調查見 docs/adr/0003），
不再依賴 playwright DOM 抓取。
"""

from __future__ import annotations

import ssl
import urllib.request

import defusedxml.ElementTree as ET

_SOURCES: list[dict] = [
    {"feed_url": "https://www.aikido.dev/blog/rss.xml", "source": "aikido.dev"},
    {"feed_url": "https://www.wiz.io/feed/rss.xml", "source": "wiz.io"},
]

_MAX_ARTICLES_PER_SOURCE = 10
_DESCRIPTION_MAX_CHARS = 200


def _ssl_context() -> ssl.SSLContext:
    """優先用 certifi 憑證（繞過 macOS python.org 安裝的 SSL 問題）。"""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _fetch_articles(source: dict) -> list[dict]:
    req = urllib.request.Request(
        source["feed_url"], headers={"User-Agent": "daily-brief/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            xml_bytes = resp.read()
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

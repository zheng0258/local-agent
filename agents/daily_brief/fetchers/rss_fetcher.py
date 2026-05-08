"""RSS feed fetcher — reads agents/daily_brief/config/rss_sources.yaml.

純函數，無 LLM，回傳原始文章清單供 agent 送 LLM 評分。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_FILE = Path(__file__).parent.parent / "config" / "rss_sources.yaml"
_DEFAULT_MAX_ITEMS = 20


def fetch(max_items: int = _DEFAULT_MAX_ITEMS) -> list[dict[str, Any]]:
    """從 rss_sources.yaml 所有 feed 抓取最近文章。

    Returns list of dicts: title, url, summary, published_at, source, category
    """
    import feedparser
    import yaml

    _install_certifi_ssl()

    if not _CONFIG_FILE.exists():
        logger.error("RSS config not found: %s", _CONFIG_FILE)
        return []

    config = yaml.safe_load(_CONFIG_FILE.read_text(encoding="utf-8"))
    feeds = config.get("feeds", [])

    articles: list[dict[str, Any]] = []
    for feed_cfg in feeds:
        name = feed_cfg.get("name", "Unknown")
        url = feed_cfg.get("url", "")
        category = feed_cfg.get("category", "Tech")
        limit = feed_cfg.get("max_items", max_items)

        if not url:
            logger.warning("RSS feed '%s' has no URL, skipping", name)
            continue

        try:
            raw_content = _fetch_url(url)
            if raw_content is None:
                continue
            feed = feedparser.parse(raw_content)
            if feed.bozo and not feed.entries:
                logger.warning("RSS '%s' parse error: %s", name, feed.bozo_exception)
                continue

            for entry in feed.entries[:limit]:
                articles.append({
                    "title": entry.get("title", "").strip(),
                    "url": entry.get("link", ""),
                    "summary": _extract_summary(entry),
                    "published_at": _parse_published(entry),
                    "source": name,
                    "category": category,
                })
            logger.info("RSS '%s': fetched %d articles", name, min(len(feed.entries), limit))
        except Exception as exc:
            logger.warning("RSS '%s' fetch failed: %s", name, exc)

    return articles


def _fetch_url(url: str) -> bytes | None:
    """手動 fetch URL 內容，使用 certifi 憑證繞過 macOS SSL 問題。

    feedparser 有自己的 HTTPS handler，不吃全域 opener，需先 fetch 再 parse。
    """
    import ssl
    import urllib.request

    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 feedparser/6.0"},
        )
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            return resp.read()
    except Exception as exc:
        logger.warning("RSS fetch URL failed '%s': %s", url, exc)
        return None


def _install_certifi_ssl() -> None:
    pass  # 已改為 _fetch_url 方案，保留供相容


def _extract_summary(entry: Any) -> str:
    raw = entry.get("summary") or entry.get("description") or ""
    # 去除 HTML tag，截斷至 500 字元
    clean = re.sub(r"<[^>]+>", "", str(raw))
    return clean[:500].strip()


def _parse_published(entry: Any) -> str:
    from email.utils import parsedate_to_datetime

    published = entry.get("published") or entry.get("updated") or ""
    if not published:
        return ""
    try:
        return parsedate_to_datetime(published).isoformat()
    except Exception:
        return str(published)

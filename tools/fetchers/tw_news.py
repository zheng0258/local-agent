# tools/fetchers/tw_news.py
"""台灣財經新聞 RSS 抓取（鉅亨網）。"""
from __future__ import annotations

import ssl
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any

NEWS_FEEDS: list[dict[str, str]] = [
    {
        "name": "cnyes_tw_stock",
        "url": "https://news.cnyes.com/rss/category/hot_taiwan_stock",
        "source": "鉅亨",
    },
    {
        "name": "cnyes_ai",
        "url": "https://news.cnyes.com/rss/category/ai",
        "source": "鉅亨AI",
    },
]


def fetch(
    feeds: list[dict[str, str]] | None = None,
    max_age_hours: int = 24,
) -> list[dict[str, Any]]:
    """抓取 RSS 新聞，回傳今日文章清單。"""
    if feeds is None:
        feeds = NEWS_FEEDS

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=max_age_hours)
    articles: list[dict[str, Any]] = []

    for feed in feeds:
        try:
            items = _fetch_feed(feed["url"], feed["source"], cutoff)
            articles.extend(items)
        except Exception as e:
            print(f"⚠️ RSS 抓取失敗 {feed['name']}: {e}")

    return articles


def _fetch_feed(url: str, source: str, cutoff: datetime) -> list[dict[str, Any]]:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        content = resp.read()

    root = ET.fromstring(content)
    items: list[dict[str, Any]] = []

    channel = root.find("channel")
    if channel is None:
        return items

    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date_str = item.findtext("pubDate") or ""
        description = (item.findtext("description") or "").strip()[:300]

        pub_date = _parse_pubdate(pub_date_str)
        if pub_date and pub_date < cutoff:
            continue

        if title and link:
            items.append({
                "title": title,
                "url": link,
                "source": source,
                "published_at": pub_date.isoformat() if pub_date else "",
                "description": description,
            })

    return items


def _parse_pubdate(s: str) -> datetime | None:
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT"):
        try:
            dt = datetime.strptime(s.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None

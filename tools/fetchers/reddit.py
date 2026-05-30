"""Reddit fetcher — 使用 RSS（Atom feed），繞過 OAuth 封鎖。

Reddit 的 .json API 自 2026-05-29 起封鎖非 OAuth 請求，
但 .rss endpoint 仍可透過 iPhone User-Agent 存取。
"""

from __future__ import annotations

import html as html_lib
import re
import subprocess

import defusedxml.ElementTree as ET

from agents.daily_brief.config import REDDIT_SUBREDDITS

_USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
_ATOM_NS = "http://www.w3.org/2005/Atom"
TOP_N = 10


def fetch() -> list[dict]:
    """
    抓取熱門文章，回傳 list[dict]，每篇含 category 欄位。
    回傳格式：[{"category": "資安類", "subreddit": "r/netsec", "title": ..., ...}, ...]
    """
    result: list[dict] = []
    for category, subreddits in REDDIT_SUBREDDITS.items():
        for sub in subreddits:
            try:
                posts = _fetch_subreddit(sub)
                for p in posts:
                    p["category"] = category
                result.extend(posts)
            except Exception:
                continue
    return result


def _fetch_subreddit(sub: str) -> list[dict]:
    url = f"https://www.reddit.com/r/{sub}/.rss?limit={TOP_N}"
    proc = subprocess.run(
        ["curl", "-s", "--max-time", "10", "-H", f"User-Agent: {_USER_AGENT}", url],
        capture_output=True, text=True, timeout=15,
    )
    return _parse_rss(proc.stdout, sub)


def _parse_rss(xml_text: str, sub: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    ns = _ATOM_NS
    posts: list[dict] = []
    for entry in root.findall(f"{{{ns}}}entry"):
        title_el = entry.find(f"{{{ns}}}title")
        link_el = entry.find(f"{{{ns}}}link")
        content_el = entry.find(f"{{{ns}}}content")

        title = title_el.text or "" if title_el is not None else ""
        reddit_url = link_el.get("href", "") if link_el is not None else ""

        # content HTML 內的 [link] 是原始文章 URL；純討論文章則與 reddit_url 相同
        orig_url = reddit_url
        if content_el is not None:
            content_html = html_lib.unescape(content_el.text or "")
            m = re.search(r'href="([^"]+)">\[link\]', content_html)
            if m:
                orig_url = m.group(1)

        posts.append({
            "subreddit": f"r/{sub}",
            "title": title.strip(),
            "score": 0,
            "num_comments": 0,
            "url": reddit_url,
            "orig_url": orig_url,
        })
    return posts

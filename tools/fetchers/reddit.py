"""Reddit fetcher（Bash curl，不用 WebFetch）。"""

from __future__ import annotations

import json
import subprocess

from agents.daily_brief.config import REDDIT_SUBREDDITS

HEADERS = "-H 'User-Agent: daily-brief/1.0'"
TOP_N = 5


def fetch() -> dict[str, list[dict]]:
    """
    抓取 16 個子版的熱門文章，依類別分組。
    回傳格式：{"資安類": [...], "AI 類": [...], ...}
    """
    result: dict[str, list[dict]] = {}

    for category, subreddits in REDDIT_SUBREDDITS.items():
        posts: list[dict] = []
        for sub in subreddits:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit={TOP_N}"
            raw = subprocess.run(
                f"curl -s {HEADERS} '{url}'",
                shell=True, capture_output=True, text=True, timeout=30,
            ).stdout

            try:
                data = json.loads(raw)
                for child in data.get("data", {}).get("children", []):
                    p = child.get("data", {})
                    if p.get("stickied"):
                        continue
                    posts.append({
                        "subreddit": f"r/{sub}",
                        "title": p.get("title", ""),
                        "score": p.get("score", 0),
                        "num_comments": p.get("num_comments", 0),
                        "url": f"https://www.reddit.com{p.get('permalink', '')}",
                    })
            except (json.JSONDecodeError, KeyError):
                continue

        result[category] = posts

    return result

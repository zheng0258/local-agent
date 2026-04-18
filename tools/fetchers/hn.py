"""Hacker News fetcher — 使用 playwright-cli 渲染頁面並解析文章。"""

from __future__ import annotations

import re

from tools.fetchers.browser import fetch_page

HN_URL = "https://news.ycombinator.com/"


def fetch() -> list[dict]:
    """
    抓取 HN 首頁，解析後回傳結構化文章列表。
    回傳格式：[{"title", "url", "hn_url", "score", "comments"}, ...]
    """
    result = fetch_page(HN_URL, max_chars=36000)
    if "error" in result:
        return [{"error": result["error"]}]
    return _parse_hn(result["html"])


def _parse_hn(html: str) -> list[dict]:
    # 提取文章 id + 標題 + 原文 URL
    submissions = re.findall(
        r'<tr class="athing submission" id="(\d+)">.*?'
        r'<span class="titleline"><a href="([^"]+)">([^<]+)</a>',
        html,
        re.DOTALL,
    )

    # 提取分數（對應 id）
    scores: dict[str, int] = {}
    for item_id, pts in re.findall(
        r'<span class="score" id="score_(\d+)">(\d+) points</span>', html
    ):
        scores[item_id] = int(pts)

    # 提取留言數（對應 id），格式：88&nbsp;comments
    comments: dict[str, int] = {}
    for item_id, cnt in re.findall(
        r'href="item\?id=(\d+)">(\d+)&nbsp;comment', html
    ):
        comments[item_id] = int(cnt)

    articles = []
    for item_id, orig_url, title in submissions:
        hn_url = f"https://news.ycombinator.com/item?id={item_id}"
        # 相對 URL（Ask HN / Show HN）補全
        if not orig_url.startswith("http"):
            orig_url = hn_url
        articles.append({
            "title": title.strip(),
            "url": orig_url,
            "hn_url": hn_url,
            "score": scores.get(item_id, 0),
            "comments": comments.get(item_id, 0),
        })

    return articles

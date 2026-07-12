"""Reddit fetcher — 使用 RSS（Atom feed），繞過 OAuth 封鎖。

Reddit 的 .json API 自 2026-05-29 起封鎖非 OAuth 請求，
但 .rss endpoint 仍可透過 iPhone User-Agent 存取。

未授權 RSS 為每 IP 每 ~60s 固定視窗只給 1 次請求（`x-ratelimit-remaining`
一發即歸 0，`x-ratelimit-reset` = 視窗重置剩餘秒數）。若無間隔連打，
只有第一個子版拿到 200、其餘全 429 被吞掉。因此請求間依上一次回應的
reset header 自適應等待，並對 429 退避重試，確保各子版都抓得到。
"""

from __future__ import annotations

import html as html_lib
import re
import subprocess
import time

import defusedxml.ElementTree as ET

from agents.daily_brief.config import REDDIT_SUBREDDITS

_USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
_ATOM_NS = "http://www.w3.org/2005/Atom"
TOP_N = 3  # 每子版取前 N 篇

_WAIT_BUFFER = 2.0  # reset 之外的緩衝秒數
_MAX_WAIT = 70.0  # 單次等待上限，避免異常 reset 值卡死
_MAX_RETRIES = 1  # 429 退避重試次數


def fetch() -> list[dict]:
    """
    抓取熱門文章，回傳 list[dict]，每篇含 category 欄位。
    回傳格式：[{"category": "資安類", "subreddit": "r/netsec", "title": ..., ...}, ...]

    依序走訪各 subreddit；受 Reddit 每 IP ~1 req/60s 限流，請求間依上一次
    回應的 rate-limit reset 自適應等待（全 15 子版最壞約 15 分鐘）。
    """
    result: list[dict] = []
    wait = 0.0  # 下次請求前需等待的秒數（由前次 reset 推得）
    for category, subreddits in REDDIT_SUBREDDITS.items():
        for sub in subreddits:
            posts, wait = _fetch_subreddit(sub, wait)
            for p in posts:
                p["category"] = category
            result.extend(posts)
    return result


def _fetch_subreddit(sub: str, wait: float) -> tuple[list[dict], float]:
    """抓單一 subreddit。

    參數 wait：本次請求前需等待的秒數（由前次 reset 推得）。
    回傳 (posts, 下次請求前建議等待秒數)。429/錯誤時依 reset 退避重試。
    """
    next_wait = 0.0
    for _ in range(_MAX_RETRIES + 1):
        _pause(wait)
        status, body, reset = _request(sub)
        next_wait = (reset + _WAIT_BUFFER) if reset is not None else 0.0
        if status in (200, None):  # None = 無狀態行（測試 mock / fallback）
            try:
                return _parse_rss(body, sub), next_wait
            except Exception:
                return [], next_wait
        wait = next_wait  # 429/5xx：退避後重試
    return [], next_wait


def _pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(min(seconds, _MAX_WAIT))


def _request(sub: str) -> tuple[int | None, str, float | None]:
    url = f"https://www.reddit.com/r/{sub}/.rss?limit={TOP_N}"
    proc = subprocess.run(
        ["curl", "-s", "-D", "-", "--max-time", "10", "-H", f"User-Agent: {_USER_AGENT}", url],
        capture_output=True, text=True, timeout=15,
    )
    return _split_response(proc.stdout)


def _split_response(raw: str) -> tuple[int | None, str, float | None]:
    """拆解 `curl -D -` 輸出為 (status, body, ratelimit_reset)。

    無 HTTP 狀態行時（測試 mock / fallback）視整段為 body、status=None。
    """
    m_status = re.search(r"HTTP/\S+\s+(\d{3})", raw)
    if not m_status:
        return None, raw, None
    parts = re.split(r"\r?\n\r?\n", raw, maxsplit=1)
    head = parts[0]
    body = parts[1] if len(parts) > 1 else ""
    reset = None
    m_reset = re.search(r"(?im)^x-ratelimit-reset:\s*([\d.]+)", head)
    if m_reset:
        reset = float(m_reset.group(1))
    return int(m_status.group(1)), body, reset


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

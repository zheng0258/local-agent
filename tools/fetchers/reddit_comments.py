"""Reddit 留言抓取 — 使用 Reddit JSON API（Bash curl）。"""

from __future__ import annotations

import json
import subprocess

_COMMENT_MAX_CHARS: int = 300
_DEFAULT_TOP_N: int = 10
_DELETED: frozenset[str] = frozenset({"[deleted]", "[removed]"})
_HEADERS: list[str] = ["User-Agent: daily-brief/1.0"]


def fetch_comments(post_url: str, top_n: int = _DEFAULT_TOP_N) -> list[str]:
    """
    呼叫 Reddit JSON API 取 top N 留言文字。
    失敗時回傳空列表（不 raise）。
    """
    try:
        url = post_url.rstrip("/") + ".json?limit=10&sort=best"
        raw = _curl_get(url)
        data = json.loads(raw)
    except Exception:
        return []

    try:
        children = data[1]["data"]["children"]
    except (IndexError, KeyError, TypeError):
        return []

    result: list[str] = []
    for child in children[:top_n]:
        body = child.get("data", {}).get("body", "")
        if body in _DELETED or not body:
            continue
        result.append(body[:_COMMENT_MAX_CHARS])
    return result


def _curl_get(url: str, timeout: int = 15) -> str:
    header_flags: list[str] = []
    for h in _HEADERS:
        header_flags += ["-H", h]
    proc = subprocess.run(
        ["curl", "-s", "--max-time", str(timeout)] + header_flags + [url],
        capture_output=True, text=True, timeout=timeout + 5,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"curl failed: {proc.stderr[:100]}")
    return proc.stdout

"""Reddit 留言抓取 — 使用 Reddit OAuth API（Bash curl）。"""

from __future__ import annotations

import json
import os
import subprocess

from config.utils import load_project_env

_COMMENT_MAX_CHARS: int = 300
_DEFAULT_TOP_N: int = 10
_DEFAULT_SORT: str = "best"
_STDERR_TRIM: int = 100
_DELETED: frozenset[str] = frozenset({"[deleted]", "[removed]"})
_USER_AGENT = "linux:daily-brief:v1.0 (by /u/daily_brief_bot)"
_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_API_BASE = "https://oauth.reddit.com"


def fetch_comments(post_url: str, top_n: int = _DEFAULT_TOP_N) -> list[str]:
    """
    呼叫 Reddit OAuth API 取 top N 留言文字。
    失敗時回傳空列表（不 raise）。
    """
    load_project_env()
    client_id = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return []

    try:
        token = _get_token(client_id, client_secret)
        # www.reddit.com → oauth.reddit.com；移除 .json（OAuth API 不加副檔名）
        path = post_url.replace("https://www.reddit.com", "").rstrip("/")
        url = f"{_API_BASE}{path}?limit={top_n}&sort={_DEFAULT_SORT}"
        raw = _curl_get(url, token)
        data = json.loads(raw)
    except (json.JSONDecodeError, RuntimeError, OSError, subprocess.TimeoutExpired):
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


def _get_token(client_id: str, client_secret: str) -> str:
    proc = subprocess.run(
        [
            "curl", "-s", "-X", "POST",
            "-H", f"User-Agent: {_USER_AGENT}",
            "--user", f"{client_id}:{client_secret}",
            "--data", "grant_type=client_credentials",
            _TOKEN_URL,
        ],
        capture_output=True, text=True, timeout=15,
    )
    token = json.loads(proc.stdout).get("access_token", "")
    if not token:
        raise RuntimeError(f"Reddit token 失敗：{proc.stdout[:200]}")
    return token


def _curl_get(url: str, token: str, timeout: int = 15) -> str:
    proc = subprocess.run(
        [
            "curl", "-s", "--max-time", str(timeout),
            "-H", f"Authorization: bearer {token}",
            "-H", f"User-Agent: {_USER_AGENT}",
            url,
        ],
        capture_output=True, text=True, timeout=timeout + 5,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"curl failed: {proc.stderr[:_STDERR_TRIM]}")
    return proc.stdout

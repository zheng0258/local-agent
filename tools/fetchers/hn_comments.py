"""HN 留言抓取 — 使用 HN Algolia API。"""

from __future__ import annotations

import json
import re
import subprocess

_COMMENT_MAX_CHARS: int = 300
_DEFAULT_TOP_N: int = 10


def parse_item_id(hn_url: str) -> str | None:
    """從 HN 討論頁 URL 提取 item id。"""
    m = re.search(r"item\?id=(\d+)", hn_url)
    return m.group(1) if m else None


def fetch_comments(item_id: str, top_n: int = _DEFAULT_TOP_N) -> list[str]:
    """
    呼叫 HN Algolia API 取 top N 留言文字。
    失敗時回傳空列表（不 raise）。
    """
    try:
        raw = _curl_get(f"https://hn.algolia.com/api/v1/items/{item_id}")
        data = json.loads(raw)
    except Exception:
        return []

    children = data.get("children") or []
    result: list[str] = []
    for child in children[:top_n]:
        text = child.get("text")
        if not text:
            continue
        clean = re.sub(r"<[^>]+>", "", text).strip()[:_COMMENT_MAX_CHARS]
        if clean:
            result.append(clean)
    return result


def _curl_get(url: str, timeout: int = 15) -> str:
    proc = subprocess.run(
        ["curl", "-s", "--max-time", str(timeout), url],
        capture_output=True, text=True, timeout=timeout + 5,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"curl failed: {proc.stderr[:100]}")
    return proc.stdout

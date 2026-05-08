"""Daily Brief MCP Server — 將 daily-brief artifact JSON 包裝為可查詢的 MCP tools。

啟動方式：
    python agents/daily_brief/mcp_server/server.py

或透過 Claude Code 設定作為 MCP server（詳見同目錄 README.md）。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_OUTPUTS_DIR = _PROJECT_ROOT / "outputs" / "daily-brief"

mcp = FastMCP("daily-brief")


@mcp.tool()
def list_recent_briefs(days: int = 7) -> list[dict[str, Any]]:
    """列出最近 N 天有哪些 daily brief，回傳每日摘要元數據。

    Args:
        days: 往回查詢的天數（預設 7）

    Returns:
        每天的 brief 元數據清單，含日期、是否有 digest/report、摘要篇數與主題。
    """
    cutoff = date.today() - timedelta(days=days)
    results: list[dict[str, Any]] = []

    if not _OUTPUTS_DIR.exists():
        return results

    for day_dir in sorted(_OUTPUTS_DIR.iterdir(), reverse=True):
        if not day_dir.is_dir() or day_dir.name.startswith("_") or day_dir.name.startswith("."):
            continue
        try:
            day_date = date.fromisoformat(day_dir.name)
        except ValueError:
            continue
        if day_date < cutoff:
            break

        digest_file = day_dir / "steps" / "digest.json"
        report_file = day_dir / "report.md"
        compress_file = day_dir / "steps" / "compress.json"

        digest_count = 0
        themes: list[str] = []

        if digest_file.exists():
            try:
                digest_data = json.loads(digest_file.read_text(encoding="utf-8"))
                digest_count = len(digest_data.get("digests", []))
            except (json.JSONDecodeError, OSError):
                pass

        if compress_file.exists():
            try:
                compress_data = json.loads(compress_file.read_text(encoding="utf-8"))
                for src, data in compress_data.items():
                    if isinstance(data, dict):
                        themes.extend(data.get("themes", []))
            except (json.JSONDecodeError, OSError):
                pass

        results.append({
            "date": day_dir.name,
            "has_digest": digest_file.exists(),
            "has_report": report_file.exists(),
            "digest_count": digest_count,
            "themes": themes[:10],
        })

    return results


@mcp.tool()
def search_recent_digests(query: str, days: int = 7) -> list[dict[str, Any]]:
    """在最近 N 天的 digest 內容中進行關鍵字搜尋。

    Args:
        query: 搜尋關鍵字（不區分大小寫），支援空格分隔的多關鍵字（AND 邏輯）
        days: 往回查詢的天數（預設 7）

    Returns:
        符合條件的 digest 條目清單，含日期、標題、URL、來源與摘要。
    """
    if not query.strip():
        return []

    keywords = [kw.lower() for kw in query.split()]
    cutoff = date.today() - timedelta(days=days)
    results: list[dict[str, Any]] = []

    if not _OUTPUTS_DIR.exists():
        return results

    for day_dir in sorted(_OUTPUTS_DIR.iterdir(), reverse=True):
        if not day_dir.is_dir() or day_dir.name.startswith("_") or day_dir.name.startswith("."):
            continue
        try:
            day_date = date.fromisoformat(day_dir.name)
        except ValueError:
            continue
        if day_date < cutoff:
            break

        digest_file = day_dir / "steps" / "digest.json"
        if not digest_file.exists():
            continue

        try:
            digest_data = json.loads(digest_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        for entry in digest_data.get("digests", []):
            if not isinstance(entry, dict):
                continue
            haystack = " ".join([
                str(entry.get("title", "")),
                str(entry.get("summary", "")),
                str(entry.get("source", "")),
            ]).lower()
            if all(kw in haystack for kw in keywords):
                results.append({
                    "date": day_dir.name,
                    "title": entry.get("title", ""),
                    "url": entry.get("url", ""),
                    "source": entry.get("source", ""),
                    "interest": entry.get("interest", ""),
                    "summary": entry.get("summary", ""),
                })

    return results


if __name__ == "__main__":
    mcp.run()

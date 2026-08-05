"""alerts — Alert（警報）的單一 owner：alerts.json 的讀取 / 記錄 / 去重 / 收尾彙總。

CONTEXT.md「系統訊號 / Alert」：條件觸發的例外訊號，單次事件、發生當下發送。
三個觸發面原各自 open/parse alerts.json：
  - supervisor 逐步即時（某 step 重試耗盡 → 記錄 + 即時發送）
  - pipeline 收尾彙總（今日整體失敗摘要，每天一次）
  - health 跨天 roll-up（唯讀 alerts 推導 Health Record）
此模組把 alerts.json 的 store I/O + 去重 + 彙總格式集中一處（唯一讀寫點），
telegram.py 仍為 transport adapter（send-only），逐步/彙總的訊息文字各自為不同 Alert。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from config import get_logger

logger = get_logger(__name__)

_ERROR_MAX_CHARS = 300
_SUMMARY_SENTINEL = "alerts_summary.done"

# 失敗不進 Telegram 摘要的步驟：仍寫 alerts.json / 入 health 記錄，只是不彙總推播。
# deploy（gh-pages push）尚未驗證穩定，transient 失敗常見；驗證穩定後移出此集合。
_QUIET_STEPS: frozenset[str] = frozenset({"deploy"})


def _alerts_path(steps_dir: Path) -> Path:
    return steps_dir / "alerts.json"


def load_alerts(steps_dir: Path) -> dict:
    """讀 alerts.json（不存在 / 壞檔 → {}）。三個消費面唯一的讀取點。"""
    path = _alerts_path(steps_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def already_recorded(steps_dir: Path, name: str) -> bool:
    """該步驟今日是否已記過失敗（供逐步發送的去重判定）。"""
    return name in load_alerts(steps_dir)


def record_failure(steps_dir: Path, name: str, error: str) -> None:
    """記一筆步驟失敗（覆寫同名）；去重由呼叫端以 already_recorded 決定。"""
    alerts = load_alerts(steps_dir)
    alerts[name] = {
        "failed_at": datetime.now().isoformat(timespec="seconds"),
        "error": error[:_ERROR_MAX_CHARS],
    }
    _alerts_path(steps_dir).write_text(
        json.dumps(alerts, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def send_summary(steps_dir: Path, today: str, notify_fn: Callable[[str], bool]) -> None:
    """pipeline 收尾彙總（每天一次，summary sentinel 去重）。

    逐步失敗時 supervisor 只記 alerts.json 不即時推播；此處把當日失敗彙總成
    單封 Telegram（_QUIET_STEPS 除外），一眼看清哪些步驟缺失。
    """
    summary_done = steps_dir / _SUMMARY_SENTINEL
    if summary_done.exists():
        return
    alerts = {
        k: v for k, v in load_alerts(steps_dir).items() if k not in _QUIET_STEPS
    }
    if not alerts:
        return

    lines = [
        f"📋 Daily Brief 失敗摘要（{today}）",
        "",
        "以下步驟全部重試後仍失敗，今日 brief 可能不完整：",
    ]
    for step, info in alerts.items():
        if isinstance(info, dict):
            lines.append(f"• <b>{step}</b>：{info.get('error', '')[:120]}")
        else:
            lines.append(f"• <b>{step}</b>")
    lines += [
        "",
        "補跑指令：",
        f"  python3 main.py \"/daily-brief --force {' '.join(alerts.keys())}\"",
    ]
    notify_fn("\n".join(lines))
    summary_done.touch()
    logger.info("alerts_summary 已發送（%d 個失敗步驟）", len(alerts))

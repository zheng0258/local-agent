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
_QUALITY_MAX_CHARS = 400

# 失敗不進 Telegram 摘要的步驟：仍寫 alerts.json / 入 health 記錄，只是不彙總推播。
# 目前為空——摘要只在「重試全部耗盡仍失敗」時才記錄，transient blip 多在 retry 恢復，
# 故不再靜默任何步驟。deploy 曾因 DEPLOY_GITHUB_TOKEN 過期 push 失敗卻靜默 18 天
# （gh-pages 停更），教訓：遞送失敗一律要能被看見（見 CONTEXT.md「系統訊號」）。
_QUIET_STEPS: frozenset[str] = frozenset()

# 非步驟的 alert（deploy 前資料品質關卡的 invariants / ledger）：照常列入摘要，但
# `--force` 補跑它沒有意義（不是 step 名），不放進補跑指令。
_NON_STEP_ALERTS: frozenset[str] = frozenset({"invariants", "ledger"})


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


def clear_failure(steps_dir: Path, name: str) -> None:
    """移除一筆失敗（不存在則不動檔案）。

    只給「狀態型」alert 用：如 invariants——同日稍早 run 的違規在後一次 run 修好、
    順利發佈後，殘留的 alert 會讓 health 把今天的 deploy 誤判為被擋。
    """
    alerts = load_alerts(steps_dir)
    if name not in alerts:
        return
    remaining = {k: v for k, v in alerts.items() if k != name}
    _alerts_path(steps_dir).write_text(
        json.dumps(remaining, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def send_summary(
    steps_dir: Path,
    today: str,
    notify_fn: Callable[[str], bool],
    quality_reason: str = "",
) -> None:
    """pipeline 收尾彙總（每天一次，summary sentinel 去重）。

    兩種當日訊號合成單封 Telegram：
    1. **步驟失敗** —— supervisor 逐步只記 alerts.json 不即時推播，此處彙總
       （_QUIET_STEPS 除外），並附補跑指令。
    2. **品質不合格** —— judge 的 quality_alert_reason。品質不合格不是步驟失敗、
       也無從「補跑」，故獨立成一段、不套用補跑指令。此前 quality_alert 寫完就
       沒有任何消費者，連兩天 faithfulness=2 無聲通過（見 judge.py 門檻註解）。

    兩者皆無才靜默。
    """
    summary_done = steps_dir / _SUMMARY_SENTINEL
    if summary_done.exists():
        return
    alerts = {
        k: v for k, v in load_alerts(steps_dir).items() if k not in _QUIET_STEPS
    }
    if not alerts and not quality_reason:
        return

    lines = [f"📋 Daily Brief 當日摘要（{today}）"]
    if alerts:
        lines += [
            "",
            "以下步驟全部重試後仍失敗，今日 brief 可能不完整：",
        ]
        for step, info in alerts.items():
            if isinstance(info, dict):
                lines.append(f"• <b>{step}</b>：{info.get('error', '')[:120]}")
            else:
                lines.append(f"• <b>{step}</b>")
        rerun = [k for k in alerts if k not in _NON_STEP_ALERTS]
        if rerun:
            lines += [
                "",
                "補跑指令：",
                f"  python3 main.py \"/daily-brief --force {' '.join(rerun)}\"",
            ]
    if quality_reason:
        lines += [
            "",
            "⚠️ 品質評分未達門檻：",
            f"• {quality_reason[:_QUALITY_MAX_CHARS]}",
        ]
    notify_fn("\n".join(lines))
    summary_done.touch()
    logger.info(
        "alerts_summary 已發送（%d 個失敗步驟%s）",
        len(alerts),
        "，含品質告警" if quality_reason else "",
    )

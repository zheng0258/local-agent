"""Run manifest —— 單次 pipeline 執行的耗時 / 步驟 / 觸發 / 版本紀錄。

鏡射 usage_meter.py / health.py 的可觀測性紀律：
- RunManifest 是「執行邊界」——記錄本次 run 的開始時間、每步耗時與結果、觸發源、
  git commit。Step.run 在每步結束後呼叫 record_step()。
- summarize() 為純函數 roll-up；append_history 落跨天 `_run-history.json`。
- 與 Step 解耦：pipeline 結尾一次落盤，包在 try/except，絕不反噬 pipeline。

on-disk 形狀（steps/_run.json 與 _run-history.json 每列同形）：
    {"date", "trigger", "git_sha", "started_at", "ended_at",
     "duration_seconds", "steps": {name: {"status", "duration_seconds"}}}
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path


def git_sha(repo_root: Path | str) -> str | None:
    """短 git commit SHA（HEAD）；非 git / 失敗回 None（絕不拋）。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    sha = out.stdout.strip()
    return sha or None


def detect_trigger(args: str) -> str:
    """由呼叫參數推觸發源：帶旗標（--force/--only 等）視為手動補跑，否則排程。"""
    return (
        "manual" if args.strip().startswith("-") or " -" in f" {args}" else "scheduled"
    )


class RunManifest:
    """單次 run 的執行帳本（本模組唯一可變邊界）；record_step thread-safe。"""

    def __init__(self, trigger: str = "", sha: str | None = None) -> None:
        self.trigger = trigger
        self.git_sha = sha
        self.started_at = datetime.now()
        self._t0 = time.monotonic()
        self._steps: dict[str, dict] = {}
        self._lock = threading.Lock()

    def record_step(self, name: str, status: str, duration_seconds: float) -> None:
        """記一步的結果與耗時（同名後者覆寫；重跑取最後一次）。"""
        with self._lock:
            self._steps[name] = {
                "status": status,
                "duration_seconds": round(float(duration_seconds), 3),
            }

    def summarize(self, today: str) -> dict:
        """組成 steps/_run.json 的當日 on-disk 形狀。"""
        ended = datetime.now()
        with self._lock:
            steps = dict(self._steps)
        return {
            "date": today,
            "trigger": self.trigger,
            "git_sha": self.git_sha,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "ended_at": ended.isoformat(timespec="seconds"),
            "duration_seconds": round(time.monotonic() - self._t0, 3),
            "steps": steps,
        }


# ── 跨天歷史（形狀鏡射 _usage-history.json）────────────────────────


def load_history(history_file: Path) -> list[dict]:
    """讀跨天 run 歷史；缺檔 / 壞檔回空 list（唯讀，永不拋）。"""
    if not history_file.exists():
        return []
    try:
        data = json.loads(history_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def append_history(history_file: Path, summary: dict) -> None:
    """把當日 manifest 追加到跨天歷史；同日重跑則覆寫（idempotent）。"""
    today = summary.get("date", "")
    kept = [r for r in load_history(history_file) if r.get("date") != today]
    kept.append(summary)
    kept.sort(key=lambda r: r.get("date", ""))
    history_file.write_text(
        json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8"
    )

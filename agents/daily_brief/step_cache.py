"""Cache-or-force gating verdict — 步驟化執行（Idempotent Steps）的共用門檻判定。

被 8 個 `_phase_*` 重抄的「該跑、該載入、還是該略過」決策集中於此。
純函數、零 I/O：phase 自行讀 `artifact.exists()` 與 `name in steps_to_run/force_steps`，
把三個 bool 餵進來，依回傳的 Verdict 決定 RUN / LOAD / SKIP 各自的動作。
"""

from __future__ import annotations

from enum import Enum


class Verdict(Enum):
    RUN = "run"  # 跑 producer 並寫 artifact
    LOAD = "load"  # 用既有 artifact
    SKIP = "skip"  # 無 artifact 可載，回 default


def decide(in_steps: bool, exists: bool, forced: bool) -> Verdict:
    """依 (在 steps_to_run, artifact 存在, 被 force) 三個 bool 決定門檻動作。"""
    if not in_steps:
        return Verdict.LOAD if exists else Verdict.SKIP
    if exists and not forced:
        return Verdict.LOAD
    return Verdict.RUN

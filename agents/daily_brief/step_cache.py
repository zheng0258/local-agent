"""Cache-or-force gating verdict — 步驟化執行（Idempotent Steps）的共用門檻判定。

被 8 個 `_phase_*` 重抄的「該跑、該載入、還是該略過」決策集中於此。
純函數、零 I/O：phase 自行讀 `artifact.exists()` 與 `name in steps_to_run/force_steps`，
把三個 bool 餵進來，依回傳的 Verdict 決定 RUN / LOAD / SKIP 各自的動作。

同一次 run 內的上游失效（`upstream_ran`）：Fix C 只在 run 開始時以 mtime 比對一次，
看不到 run 中途才 RUN 的上游（2026-10-17：rss 下午才成功，dedup 卻 LOAD 舊 kept_urls
濾掉整個 rss）。故 Step 另記本次 run 已 RUN 的步驟，任一上游 RUN 則下游視同 force。
"""

from __future__ import annotations

from collections.abc import Collection
from enum import Enum

from .config import FETCH_STEPS


class Verdict(Enum):
    RUN = "run"  # 跑 producer 並寫 artifact
    LOAD = "load"  # 用既有 artifact
    SKIP = "skip"  # 無 artifact 可載，回 default


# 上游失效的傳播序：鏡射 agent.run() 的接線順序，同層為並列兄弟（互不失效）。
# save / notify 為使用者決定的副作用步（同 Fix C 不列入自動過期），不參與傳播。
INVALIDATION_TIERS: tuple[tuple[str, ...], ...] = (
    tuple(FETCH_STEPS),
    ("dedup",),
    ("compress",),
    ("enrich",),
    ("digest",),
    ("tldr", "judge", "report", "compose_tg"),  # 皆吃 digest，彼此不消費
    ("deploy",),  # 讀 report.md + 全部歷史建站
)


def decide(
    in_steps: bool, exists: bool, forced: bool, upstream_ran: bool = False
) -> Verdict:
    """依 (在 steps_to_run, artifact 存在, 被 force, 上游本次已 RUN) 決定門檻動作。

    upstream_ran 等同 forced：既有 artifact 已過期，不得 LOAD。不在 steps_to_run
    （`--only` 收窄）時仍尊重使用者意圖，不因上游而跑。
    """
    if not in_steps:
        return Verdict.LOAD if exists else Verdict.SKIP
    if exists and not (forced or upstream_ran):
        return Verdict.LOAD
    return Verdict.RUN


def upstream_ran(name: str, ran: Collection[str]) -> bool:
    """本次 run 中，name 所在層之前的任一步驟是否已 RUN（遞移性由逐步記錄自然帶出）。"""
    if not any(name in tier for tier in INVALIDATION_TIERS):
        return False
    for tier in INVALIDATION_TIERS:
        if name in tier:
            return False
        if any(step in ran for step in tier):
            return True
    return False

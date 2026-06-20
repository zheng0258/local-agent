"""Step — 步驟化執行的深模組：gating + artifact I/O + supervisor 接線藏在 run() 後面。

公開介面只有 run(ctx, input) -> StepOutcome。_produce / _load / _guard / _default
是內部 seam，子類只 override 自己不一樣的那塊。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class StepStatus(Enum):
    RAN = "ran"        # 跑了 producer 並寫 artifact
    LOADED = "loaded"  # 用既有 artifact
    SKIPPED = "skipped"  # 不在 steps_to_run / guard 不過 → 回 default
    FAILED = "failed"  # producer 重試耗盡 → 回 default


@dataclass(frozen=True)
class StepOutput:
    """_produce 的回傳：要落盤的物件 + 要傳給下游的 value（兩者可不同）。"""

    persist: Any
    value: Any


@dataclass(frozen=True)
class StepOutcome:
    """Step.run() 的回傳：狀態 + 傳給下游的 value。status 只供 logging/alert，不驅動 cascade。"""

    status: StepStatus
    value: Any

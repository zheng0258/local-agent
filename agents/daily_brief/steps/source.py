"""SourceStep — 單一來源（Source）的評分 + 落盤 {name}.json。

fetch 是 orchestrator；本 Step 只負責「對已抓取的 raw 評分並持久化」這一段（serial 階段）。
raw 由 orchestrator 並行預抓後當 input 餵入：None = 抓取失敗 → guard 略過；[] = 空 → 仍評分。
score_fn 注入自 DailyBriefAgent._score_raw_data。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from ..step import Step, StepOutput


class SourceStep(Step):
    def __init__(self, name: str, score_fn: Callable[[str, list], dict]) -> None:
        self.name = name
        self._score = score_fn

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / f"{self.name}.json"

    def _guard(self, ctx, input) -> bool:
        return input is not None

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        result = self._score(self.name, input)
        result["fetched_at"] = datetime.now().isoformat(timespec="seconds")
        return StepOutput(persist=result, value=result)

    def _default(self, input):
        return None

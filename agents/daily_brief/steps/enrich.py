"""EnrichStep — 對 HN/Reddit *** 文章抓留言並 LLM 摘要社群觀點（best-effort）。

producer 注入自 _run_enrich（無 reflect_context；_produce 忽略它）。
LOAD 直接回 artifact（identity）；_default pass-through 上游 compress_data。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..step import Step, StepOutput


class EnrichStep(Step):
    name = "enrich"

    def __init__(self, run_enrich: Callable[[dict], dict]) -> None:
        self._run_enrich = run_enrich

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "enrich.json"

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        enriched = self._run_enrich(input)
        return StepOutput(persist=enriched, value=enriched)

    def _default(self, input):
        return input

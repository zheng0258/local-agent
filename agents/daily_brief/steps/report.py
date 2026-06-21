"""ReportStep — 最終趨勢報告（純 markdown，寫 report.md）。

input 是 (compress_data, digests) 二元組；producer 注入自 _run_report。
artifact 在 day_dir（非 steps_dir），用 TextCodec。value 為 None（終端步）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..codecs import TextCodec
from ..step import Step, StepOutput


class ReportStep(Step):
    name = "report"
    codec = TextCodec()

    def __init__(self, run_report: Callable[..., str], today: str) -> None:
        self._run_report = run_report
        self._today = today

    def artifact_path(self, ctx) -> Path:
        return ctx.day_dir / "report.md"

    def _guard(self, ctx, input) -> bool:
        _compress, digests = input
        return bool(digests)

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        compress_data, digests = input
        md = self._run_report(compress_data, digests, self._today, reflect_context=reflect_context)
        return StepOutput(persist=md, value=None)

    def _default(self, input):
        return None

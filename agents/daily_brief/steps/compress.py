"""CompressStep — 各來源 *** 文章語義壓縮。

producer 與 source-health 檢查注入自 DailyBriefAgent（_run_compress / _check_source_health），
本檔只負責 gating + artifact I/O 的 Step 包裝。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..step import Step, StepOutput


class CompressStep(Step):
    name = "compress"

    def __init__(
        self,
        run_compress: Callable[..., dict],
        check_health: Callable[[dict], None],
    ) -> None:
        self._run_compress = run_compress
        self._check_health = check_health

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "compress.json"

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        result = self._run_compress(input, reflect_context=reflect_context)
        self._check_health(result)
        return StepOutput(persist=result, value=result)

    def _default(self, input):
        return {}

"""TldrStep — 當日英文 TL;DR（吃 digests，產 tldr.json）。

producer 注入自 DailyBriefAgent._run_tldr（回傳純文字英文 TL;DR）；本檔負責
gating + artifact I/O。persist 為 {"tldr": <text>}，下游（builder）只拿純文字。
置於 DigestStep 之後：input 是 digests list，無摘要時 guard 擋下優雅略過。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..step import Step, StepOutput


class TldrStep(Step):
    name = "tldr"

    def __init__(self, run_tldr: Callable[..., str]) -> None:
        self._run_tldr = run_tldr

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "tldr.json"

    def _guard(self, ctx, input) -> bool:
        return bool(input)

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        text = self._run_tldr(input, reflect_context=reflect_context)
        return StepOutput(persist={"tldr": text}, value=text)

    def _load(self, decoded, input):
        return decoded.get("tldr", "")

    def _default(self, input):
        return None

"""DigestStep — 跨來源深度摘要。

producer 注入自 DailyBriefAgent._run_digest（回傳 (digests, digest_data)）；
本檔負責 gating + artifact I/O。persist 全份 digest_data，下游只拿 digests list。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..step import Step, StepOutput


class DigestStep(Step):
    name = "digest"

    def __init__(self, run_digest: Callable[..., tuple]) -> None:
        self._run_digest = run_digest

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "digest.json"

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        digests, digest_data = self._run_digest(input, reflect_context=reflect_context)
        return StepOutput(persist=digest_data, value=digests)

    def _load(self, decoded, input):
        return decoded.get("digests", [])

    def _default(self, input):
        return []

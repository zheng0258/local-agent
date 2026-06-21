"""SaveStep — 把 report.md + digest 存進 Obsidian vault。

SentinelCodec：成功後 touch vault.done（存在 = 已存過 → 下次 LOAD 略過）。
guard：需有 digests 且 report.md 已存在。producer 注入自 _run_save（純副作用）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..codecs import SentinelCodec
from ..step import Step, StepOutput


class SaveStep(Step):
    name = "save"
    codec = SentinelCodec()

    def __init__(self, run_save: Callable[..., None], today: str) -> None:
        self._run_save = run_save
        self._today = today

    def artifact_path(self, ctx) -> Path:
        return ctx.day_dir / "vault.done"

    def _guard(self, ctx, input) -> bool:
        return bool(input) and (ctx.day_dir / "report.md").exists()

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        self._run_save(ctx.day_dir, self._today, input)
        return StepOutput(persist=None, value=None)

    def _default(self, input):
        return None

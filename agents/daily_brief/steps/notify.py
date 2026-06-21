"""NotifyStep — 發送 Telegram 推播（兩封）。

SentinelCodec：成功後 touch telegram.done。guard：需 digests 且 report.md。
producer 注入自 _notify（回 bool）；回 False 視為失敗 → raise，讓 supervisor 記 FAILED、
sentinel 不寫入（與舊 _phase_notify 一致：失敗用 --force notify 重試）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..codecs import SentinelCodec
from ..step import Step, StepOutput


class NotifyStep(Step):
    name = "notify"
    codec = SentinelCodec()

    def __init__(self, notify: Callable[..., bool], today: str) -> None:
        self._notify = notify
        self._today = today

    def artifact_path(self, ctx) -> Path:
        return ctx.day_dir / "telegram.done"

    def _guard(self, ctx, input) -> bool:
        return bool(input) and (ctx.day_dir / "report.md").exists()

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        ok = self._notify(input, self._today, steps_dir=ctx.steps_dir, reflect_context=reflect_context)
        if not ok:
            raise RuntimeError("Telegram 訊息發送失敗")
        return StepOutput(persist=None, value=None)

    def _default(self, input):
        return None

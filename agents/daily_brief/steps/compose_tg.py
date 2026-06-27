"""ComposeTgStep — 生成兩封 Telegram 訊息文字並持久化（不發送）。

JsonCodec：落盤 {"overview": str, "digest": str}（純文字）。重跑有 artifact 時 LOAD，
不呼叫 LLM；納入 stale 偵測（digest 下游）。發送由 send-only 的 NotifyStep 負責。
producer 注入自 DailyBriefAgent._run_compose_tg（兩次 27b LLM 生成）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..step import Step, StepOutput


class ComposeTgStep(Step):
    name = "compose_tg"

    def __init__(self, run_compose: Callable[..., dict], today: str) -> None:
        self._run_compose = run_compose
        self._today = today

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "compose_tg.json"

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        composed = self._run_compose(
            input, self._today, reflect_context=reflect_context
        )
        return StepOutput(persist=composed, value=composed)

    def _default(self, input):
        return {}

"""TldrStep — 當日今日重點（繁體中文，吃 digests，產 tldr.json）。

producer 邏輯住 _produce（讀 ctx.llm）；gating + artifact I/O 由 Step 基底處理。
persist 為 {"tldr": <text>}，下游（builder）只拿純文字。
置於 DigestStep 之後：input 是 digests list，無摘要時 guard 擋下優雅略過。
"""

from __future__ import annotations

import json
from pathlib import Path

from config import get_logger

from .. import prompts
from ..step import Step, StepOutput

logger = get_logger(__name__)


class TldrStep(Step):
    name = "tldr"

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "tldr.json"

    def _guard(self, ctx, input) -> bool:
        return bool(input)

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        digests_json = json.dumps({"digests": input}, ensure_ascii=False)
        prompt = self._with_reflect(
            prompts.build_tldr_prompt(digests_json), reflect_context
        )
        text = self._complete(ctx, prompt).strip()
        logger.info("TL;DR LLM 完成：%d 字元", len(text))
        return StepOutput(persist={"tldr": text}, value=text)

    def _load(self, decoded, input):
        return decoded.get("tldr", "")

    def _default(self, input):
        return None

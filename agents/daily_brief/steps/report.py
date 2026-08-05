"""ReportStep — 最終趨勢報告（純 markdown，寫 report.md）。

producer 邏輯住 _produce（讀 ctx.llm、ctx.today）；input 是 (compress_data, digests)。
LLM 直接輸出純 markdown（不包 JSON）；_produce 剝除 LLM 可能加上的 markdown fence。
artifact 在 day_dir（非 steps_dir），用 TextCodec。value 為 None（終端步）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .. import prompts
from ..codecs import TextCodec
from ..schemas import Digest
from ..step import Step, StepOutput


class ReportStep(Step):
    name = "report"
    codec = TextCodec()

    def artifact_path(self, ctx) -> Path:
        return ctx.day_dir / "report.md"

    def _guard(self, ctx, input) -> bool:
        _compress, digests = input
        return bool(digests)

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        compress_data, digests = input
        seen: set[str] = set()
        deduped: list[dict] = []
        for d in digests:
            url = Digest.from_dict(d).url
            if url and url not in seen:
                seen.add(url)
                deduped.append(d)

        compress_json = json.dumps(compress_data, ensure_ascii=False)
        prompt = self._with_reflect(
            prompts.build_report_prompt_from_compress(
                compress_json=compress_json,
                digests_json=json.dumps(deduped, ensure_ascii=False),
                today=ctx.today,
            ),
            reflect_context,
        )
        content = self._complete(ctx, prompt).strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?", "", content).rstrip("`").strip()
        return StepOutput(persist=content or "（報告生成失敗）", value=None)

    def _default(self, input):
        return None

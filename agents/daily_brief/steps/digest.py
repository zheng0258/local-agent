"""DigestStep — 跨來源深度摘要。

producer 邏輯住 _produce（讀 ctx.llm）：逐來源分批呼叫 LLM，確保每個來源都被處理。
persist 全份 digest_data，下游只拿 digests list。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from config import get_logger, parse_llm_json

from .. import prompts
from ..schemas import SourceCompress
from ..step import Step, StepOutput

logger = get_logger(__name__)


class DigestStep(Step):
    name = "digest"

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "digest.json"

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        compress_data = input
        sources = [k for k in compress_data if k != "_meta"]
        all_digests: list[dict] = []
        url_by_title: dict[str, str] = {}

        for src in sources:
            src_data = compress_data.get(src, {})
            src_compress = SourceCompress.from_dict(src_data)
            if not src_compress.articles:
                continue
            for art in src_compress.articles:
                if art.title and art.url:
                    url_by_title[art.title] = art.url
            per_src = {src: src_data}
            compress_json = json.dumps(per_src, ensure_ascii=False)
            prompt = self._with_reflect(
                prompts.build_digest_prompt_from_compress(compress_json), reflect_context
            )
            result = parse_llm_json(self._complete(ctx, prompt))
            src_digests = result.get("digests", [])
            for d in src_digests:
                d["_source"] = src
            logger.info("Digest %s：%d 篇", src, len(src_digests))
            all_digests.extend(src_digests)

        # URL 補回（LLM 有時不複製 URL）
        for d in all_digests:
            if not d.get("url"):
                restored = url_by_title.get(d.get("title", ""), "")
                if restored:
                    d["url"] = restored

        digest_data = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "digests": all_digests,
        }
        logger.info("Digest LLM 完成：%d 篇摘要", len(all_digests))
        return StepOutput(persist=digest_data, value=all_digests)

    def _load(self, decoded, input):
        return decoded.get("digests", [])

    def _default(self, input):
        return []

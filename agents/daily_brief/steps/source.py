"""SourceStep — 單一來源（Source）的 LLM 評分 + 落盤 {name}.json。

fetch 是 orchestrator；本 Step 只負責「對已抓取的 raw 評分並持久化」這一段（serial 階段）。
raw 由 orchestrator 並行預抓後當 input 餵入：None = 抓取失敗 → guard 略過；[] = 空 → 仍評分。
producer 邏輯住 _produce/_score（讀 ctx.llm）；reddit 文章過多時分批評分。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from config import get_logger, parse_llm_json

from .. import prompts
from ..step import Step, StepOutput

logger = get_logger(__name__)

_REDDIT_BATCH_SIZE = 25


class SourceStep(Step):
    def __init__(self, name: str) -> None:
        self.name = name

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / f"{self.name}.json"

    def _guard(self, ctx, input) -> bool:
        return input is not None

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        result = self._score(ctx, self.name, input)
        result["fetched_at"] = datetime.now().isoformat(timespec="seconds")
        return StepOutput(persist=result, value=result)

    def _default(self, input):
        return None

    # ── 評分 producer ────────────────────────────────────────────────
    def _score(self, ctx, name: str, raw: list) -> dict:
        from tools.fetchers.schema import clean_articles

        from ..agent import _attach_original_fields

        if name == "reddit" and len(raw) > _REDDIT_BATCH_SIZE:
            return self._score_reddit_batched(ctx, raw)

        raw_json = json.dumps(raw, ensure_ascii=False)
        prompt_dispatch = {
            "hatena": lambda: prompts.build_hatena_prompt(raw_json),
            "hn": lambda: prompts.build_hn_prompt(raw_json),
            "reddit": lambda: prompts.build_reddit_prompt(raw_json),
            "security": lambda: prompts.build_security_blogs_prompt(raw_json),
            "rss": lambda: prompts.build_rss_prompt(raw_json),
        }
        min_interest = "***" if name == "security" else None

        logger.info("%s LLM 評分：%d 篇文章", name, len(raw))
        result = parse_llm_json(self._complete(ctx, prompt_dispatch[name]()))
        cleaned = (
            clean_articles(result.get("articles", []), min_interest=min_interest)
            if min_interest
            else clean_articles(result.get("articles", []))
        )
        result["articles"] = _attach_original_fields(
            [article.to_dict() for article in cleaned], raw
        )
        logger.info("%s LLM + 清洗完成：%d 篇", name, len(result["articles"]))
        return result

    def _score_reddit_batched(self, ctx, raw: list) -> dict:
        """Reddit 文章數量過多時分批評分，每批 _REDDIT_BATCH_SIZE 篇。"""
        from tools.fetchers.schema import clean_articles

        from ..agent import _attach_original_fields

        batch_size = _REDDIT_BATCH_SIZE
        all_cleaned = []
        n_batches = (len(raw) + batch_size - 1) // batch_size
        logger.info("reddit LLM 評分（分批）：%d 篇 → %d 批", len(raw), n_batches)
        for i in range(0, len(raw), batch_size):
            batch = raw[i : i + batch_size]
            batch_json = json.dumps(batch, ensure_ascii=False)
            result = parse_llm_json(
                self._complete(ctx, prompts.build_reddit_prompt(batch_json))
            )
            cleaned = clean_articles(result.get("articles", []))
            all_cleaned.extend(cleaned)
            logger.info(
                "reddit 批次 %d/%d：%d 篇 → %d 篇保留",
                i // batch_size + 1,
                n_batches,
                len(batch),
                len(cleaned),
            )
        logger.info("reddit LLM + 清洗完成（分批）：%d 篇", len(all_cleaned))
        return {
            "articles": _attach_original_fields(
                [a.to_dict() for a in all_cleaned], raw
            )
        }

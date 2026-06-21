"""DedupStep — 語義去重（向量 embedding + cosine）。

無 LLM、無 agent 狀態：production 邏輯直接住 _produce。persist 的 kept_urls 等指標
維持原 on-disk schema；_load 用 kept_urls 重濾上游 source_data；_default 直接 pass-through。
向量庫相依以模組層 import 暴露，便於測試 patch。
"""

from __future__ import annotations

from pathlib import Path

from ..config import DEDUP_SIMILARITY_THRESHOLD, DEDUP_WINDOW_DAYS, VECTOR_DB_PATH
from ..step import Step, StepOutput
from tools.vector_store.client import cleanup_old_records, get_collection
from tools.vector_store.dedup import dedup_source_data
from tools.vector_store.embedder import Qwen3Embedder


class DedupStep(Step):
    name = "dedup"

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "dedup.json"

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        VECTOR_DB_PATH.mkdir(parents=True, exist_ok=True)
        collection = get_collection(VECTOR_DB_PATH)
        cleanup_old_records(collection, DEDUP_WINDOW_DAYS)
        embedder = Qwen3Embedder()
        filtered_data, result = dedup_source_data(
            source_data=input,
            collection=collection,
            embedder=embedder,
            today=ctx.today,
            window_days=DEDUP_WINDOW_DAYS,
            threshold=DEDUP_SIMILARITY_THRESHOLD,
        )
        artifact_data = {
            "total": result.total,
            "kept": result.kept,
            "filtered_url": result.filtered_url,
            "filtered_semantic": result.filtered_semantic,
            "kept_urls": result.kept_urls,
            "filtered_items": result.filtered_items,
        }
        return StepOutput(persist=artifact_data, value=filtered_data)

    def _load(self, decoded, input):
        from ..agent import _filter_source_data_by_urls
        return _filter_source_data_by_urls(input, set(decoded.get("kept_urls", [])))

    def _default(self, input):
        return input

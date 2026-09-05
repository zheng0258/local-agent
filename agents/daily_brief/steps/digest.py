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
from ..step import Step, StepOutput

logger = get_logger(__name__)

# src key → Obsidian/呈現用顯示名（source_label）；reddit/security 另有更細的 per-item label
_SOURCE_LABELS = {
    "hatena": "Hatena",
    "hn": "HN",
    "reddit": "Reddit",
    "security": "Security",
    "rss": "RSS",
}


def _source_label(src: str, art: dict) -> str:
    return art.get("subreddit") or art.get("source") or _SOURCE_LABELS.get(src, src)


def _summaries_by_id(llm_digests: list, n: int) -> dict[int, str]:
    """從 LLM 回傳解析出 {id: summary}；越界 / 重複 / 空摘要一律忽略。"""
    out: dict[int, str] = {}
    for d in llm_digests:
        idx = d.get("id") if isinstance(d, dict) else None
        if isinstance(idx, int) and 0 <= idx < n and idx not in out:
            summary = (d.get("summary") or "").strip()
            if summary:
                out[idx] = summary
    return out


class DigestStep(Step):
    name = "digest"

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "digest.json"

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        compress_data = input
        sources = [k for k in compress_data if k != "_meta"]
        all_digests: list[dict] = []

        for src in sources:
            src_data = compress_data.get(src, {})
            raw_articles = src_data.get("articles", [])
            if not raw_articles:
                continue
            # 每篇帶唯一 id 送 LLM；LLM 只回 {id, summary}，title/url 依 id 從
            # compress（可信輸入）重建，URL 永不經 LLM 之手（見 links.py 原則）。
            payload = {
                src: {
                    **src_data,
                    "articles": [{"id": i, **a} for i, a in enumerate(raw_articles)],
                }
            }
            compress_json = json.dumps(payload, ensure_ascii=False)
            prompt = self._with_reflect(
                prompts.build_digest_prompt_from_compress(compress_json), reflect_context
            )
            result = parse_llm_json(self._complete(ctx, prompt))
            summary_by_id = _summaries_by_id(
                result.get("digests", []), len(raw_articles)
            )
            for i, art in enumerate(raw_articles):
                # LLM 漏掉的 id 以 one_liner/標題退回，禁止丟棄（維持 completeness）
                summary = summary_by_id.get(i) or art.get("one_liner") or art.get(
                    "title", ""
                )
                all_digests.append(
                    {
                        "title": art.get("title", ""),
                        "url": art.get("url", ""),
                        "source": _source_label(src, art),
                        "_source": src,
                        "interest": art.get("interest", "***"),
                        "summary": summary,
                    }
                )
            logger.info("Digest %s：%d 篇", src, len(raw_articles))

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

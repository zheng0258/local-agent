"""EnrichStep — 對 HN/Reddit *** 文章抓留言並 LLM 摘要社群觀點（best-effort）。

producer 邏輯住 _produce/_enrich_article（讀 ctx.llm）：並行抓留言 → LLM 摘要 →
注入 comment_summary 欄位。單篇失敗回 None（不 block 其他）。
LOAD 直接回 artifact（identity）；_default pass-through 上游 compress_data。
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path

from config import get_logger, parse_llm_json

from .. import prompts
from ..step import Step, StepOutput

logger = get_logger(__name__)


def sanitize_comment_summary(text: str) -> str:
    """移除 comment_summary 中可能的注入內容（URL、HTML、markdown 連結、控制序列）。"""
    text = text[:60]  # 強制 60 字元上限
    text = re.sub(r"<[^>]+>", "", text)  # 移除 HTML tag
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # 移除 markdown 連結
    text = re.sub(r"https?://\S+", "", text)  # 移除裸 URL
    text = text.replace("```", "")  # 移除 fence
    return text.strip()


class EnrichStep(Step):
    name = "enrich"

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "enrich.json"

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        result = copy.deepcopy(input)
        result["_meta"] = {"enriched_at": datetime.now().isoformat(timespec="seconds")}

        to_enrich: list[tuple[str, int]] = []
        for src in ["hn", "reddit"]:
            for idx, article in enumerate(result.get(src, {}).get("articles", [])):
                if isinstance(article, dict):
                    to_enrich.append((src, idx))

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(
                    self._enrich_article, ctx, src, result[src]["articles"][idx]
                ): (src, idx)
                for src, idx in to_enrich
            }
            for future in as_completed(futures):
                src, idx = futures[future]
                comment_summary = future.result()
                if comment_summary:
                    result[src]["articles"][idx]["comment_summary"] = comment_summary

        return StepOutput(persist=result, value=result)

    def _default(self, input):
        return input

    def _enrich_article(self, ctx, src: str, article: dict) -> str | None:
        """對單篇文章抓留言並 LLM 摘要，失敗時回傳 None（best-effort）。"""
        from tools.fetchers import hn_comments, reddit_comments

        try:
            url = article.get("url", "")
            if src == "hn":
                item_id = hn_comments.parse_item_id(url)
                if not item_id:
                    logger.debug("HN URL 無法解析 item_id: %s", url)
                    return None
                comments = hn_comments.fetch_comments(item_id, top_n=10)
            else:
                comments = reddit_comments.fetch_comments(url, top_n=10)

            if not comments:
                return None

            sanitized_comments = [c.replace("```", "") for c in comments]
            prompt = prompts.build_comment_summary_prompt(
                source=src,
                title=article.get("title", ""),
                comments_json=json.dumps(sanitized_comments, ensure_ascii=False),
            )
            parsed = parse_llm_json(self._complete(ctx, prompt))
            summary = sanitize_comment_summary(parsed.get("comment_summary", "").strip())
            return summary if summary else None
        except Exception as exc:
            logger.warning("enrich %s 失敗: %s", src, exc)
            return None

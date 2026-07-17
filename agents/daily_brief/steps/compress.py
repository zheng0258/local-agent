"""CompressStep — 各來源 *** 文章語義壓縮（themes + one-liners）。

producer 邏輯住 _produce（讀 ctx.llm）：Python 層先過濾 interest == "***" 才送 LLM，
來源無 *** 文章時直接略過 LLM 呼叫。壓縮後就地檢查各來源健康（0 篇 → warning）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from config import get_logger, parse_llm_json

from .. import prompts
from ..config import FETCH_STEPS
from ..schemas import SourceCompress
from ..step import Step, StepOutput

logger = get_logger(__name__)


def check_source_health(compress_data: dict) -> list[str]:
    """回傳 compress 後 articles 為空的來源名稱列表（純函數，供觀測/告警參考）。"""
    empty_sources: list[str] = []
    for name in FETCH_STEPS:
        if not SourceCompress.from_dict(compress_data.get(name, {})).articles:
            empty_sources.append(name)
            logger.warning("Source health: %s compress 後為 0 篇", name)
    return empty_sources


class CompressStep(Step):
    name = "compress"

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "compress.json"

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        source_data = input
        result: dict = {
            "_meta": {"compressed_at": datetime.now().isoformat(timespec="seconds")}
        }
        for name in FETCH_STEPS:
            articles = source_data.get(name, {}).get("articles", [])
            starred = [
                a
                for a in articles
                if isinstance(a, dict) and a.get("interest") == "***"
            ]
            if not starred:
                result[name] = {"themes": [], "articles": []}
                logger.info("Step compress  : %s 無 *** 文章，略過 LLM", name)
                continue
            articles_json = json.dumps(starred, ensure_ascii=False)
            prompt = self._with_reflect(
                prompts.build_compress_prompt(name, articles_json), reflect_context
            )
            parsed = parse_llm_json(self._complete(ctx, prompt))
            if isinstance(parsed, dict) and "themes" in parsed:
                # LLM 有時不複製 URL；用原始 starred 的 title→url 補回
                url_by_title = {a.get("title", ""): a.get("url", "") for a in starred}
                for art in parsed.get("articles", []):
                    if not art.get("url"):
                        restored = url_by_title.get(art.get("title", ""), "")
                        if restored:
                            art["url"] = restored
                result[name] = parsed
            else:
                logger.warning(
                    "Step compress  : %s LLM 回傳無效（缺 themes），使用原始 starred 資料",
                    name,
                )
                result[name] = {"themes": [], "articles": starred}
        check_source_health(result)
        return StepOutput(persist=result, value=result)

    def _default(self, input):
        return {}

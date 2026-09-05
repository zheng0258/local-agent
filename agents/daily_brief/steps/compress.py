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


def _rebuild_articles(starred: list[dict], llm_articles: list[dict]) -> list[dict]:
    """依 id 用可信的 starred 輸入重建每篇文章，只採納 LLM 的 one_liner。

    title/url/score 等結構欄位一律來自 starred（絕不採信 LLM 回吐），確保 URL
    永不遺失、任何一篇都不被丟棄（保序）；LLM 漏掉的 id 以標題退回為 one_liner。
    純函數、不變性：回傳全新 dict，不 mutate 輸入。
    """
    one_liner_by_id: dict[int, str] = {}
    for art in llm_articles:
        idx = art.get("id") if isinstance(art, dict) else None
        if isinstance(idx, int) and 0 <= idx < len(starred) and idx not in one_liner_by_id:
            one_liner = (art.get("one_liner") or "").strip()
            if one_liner:
                one_liner_by_id[idx] = one_liner
    return [
        {**base, "one_liner": one_liner_by_id.get(idx) or base.get("title", "")}
        for idx, base in enumerate(starred)
    ]


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
            # 每篇帶唯一 id 送 LLM；LLM 只回 {id, one_liner}，title/url/score
            # 一律由程式依 id 從 starred（可信輸入）重建，杜絕 LLM 丟欄位/丟整篇
            # 導致下游連結遺失（見 issue：09-05 TG HN 條目無連結）。
            payload = [{"id": i, **a} for i, a in enumerate(starred)]
            articles_json = json.dumps(payload, ensure_ascii=False)
            prompt = self._with_reflect(
                prompts.build_compress_prompt(name, articles_json), reflect_context
            )
            parsed = parse_llm_json(self._complete(ctx, prompt))
            if isinstance(parsed, dict) and "themes" in parsed:
                result[name] = {
                    "themes": parsed.get("themes", []),
                    "articles": _rebuild_articles(starred, parsed.get("articles", [])),
                }
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

"""JudgeStep — LLM-as-Judge 品質評分（只評分，不含回饋迴圈）。

producer 邏輯住 _produce（讀 ctx.judge_llm）：只傳 url + one_liner 給 judge（slim context）；
faithfulness 對照 fetch 階段原始 title（去循環化）。server 無回應時 raise → supervisor retry/FAILED。
value = judge_result dict；run() 用它的 status==RAN + QualityScore 決定是否觸發 completeness 回饋。
每次評分後把當日分數 append 到 _judge-history.json。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from config import get_logger, parse_llm_json
from config.settings import (
    DEFAULT_JUDGE_LLM_MODEL,
    DEFAULT_LOCAL_LLM_URL,
    check_local_llm,
)

from .. import prompts
from ..config import FETCH_STEPS
from ..schemas import QualityScore
from ..step import Step, StepOutput

logger = get_logger(__name__)


class JudgeStep(Step):
    name = "judge"

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "judge.json"

    def _guard(self, ctx, input) -> bool:
        compress_data, digests, _source_data = input
        return bool(compress_data) and bool(digests)

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        compress_data, digests, source_data = input
        # fail-fast：judge server 無回應時 raise，讓 supervisor 走 retry/FAILED。
        judge_url = os.environ.get("JUDGE_LLM_URL", DEFAULT_LOCAL_LLM_URL)
        if not check_local_llm(judge_url, timeout=3):
            raise RuntimeError("judge LLM server 無回應")
        result = self._judge(ctx, compress_data, digests, source_data, date=ctx.today)
        return StepOutput(persist=result, value=result)

    def _default(self, input):
        return None

    # ── 評分 producer ────────────────────────────────────────────────
    def _judge(
        self,
        ctx,
        compress_data: dict,
        digests: list[dict],
        source_data: dict | None = None,
        date: str | None = None,
    ) -> dict:
        from ..agent import _original_pairs_for_digests

        # 只傳 url + one_liner 給 judge LLM，省 60-70% token
        slim_compress = {
            src: {
                "themes": data.get("themes", []),
                "articles": [
                    {"url": a["url"], "one_liner": a.get("one_liner", "")}
                    for a in data.get("articles", [])
                    if isinstance(a, dict) and "url" in a
                ],
            }
            for src, data in compress_data.items()
            if src in FETCH_STEPS
        }
        if not slim_compress:
            logger.warning("Step judge     : slim_compress 為空，judge 結果可能不可靠")
        compress_json = json.dumps(slim_compress, ensure_ascii=False)
        digest_json = json.dumps({"digests": digests}, ensure_ascii=False)
        original_pairs = _original_pairs_for_digests(digests, source_data or {})
        raw = ctx.judge_llm.complete(
            prompts.build_judge_prompt(
                compress_json,
                digest_json,
                json.dumps(original_pairs, ensure_ascii=False),
            ),
            system=prompts.SYSTEM,
        )
        result = parse_llm_json(raw)
        scores = result.get("scores", {})
        # missed_urls 在新 schema 位於頂層；回寫進 completeness 維持下游介面不變
        missed_urls = result.get("missed_urls") or []
        completeness = scores.get("completeness")
        if isinstance(completeness, dict):
            completeness["missed_urls"] = missed_urls
        dimensions = ["relevance", "completeness", "faithfulness"]
        valid_scores = [
            scores[dim]["score"]
            for dim in dimensions
            if dim in scores
            and isinstance(scores.get(dim, {}).get("score"), (int, float))
        ]
        result["overall"] = (
            round(sum(valid_scores) / len(valid_scores), 1) if valid_scores else 0.0
        )
        result["judged_at"] = datetime.now().isoformat(timespec="seconds")
        result["judge_model"] = os.environ.get(
            "JUDGE_LLM_MODEL", DEFAULT_JUDGE_LLM_MODEL
        )

        completeness_score = scores.get("completeness", {}).get("score")
        if isinstance(completeness_score, (int, float)) and completeness_score < 3:
            result["quality_alert"] = True
            result["quality_alert_reason"] = (
                f"completeness={completeness_score}，"
                f"遺漏：{scores['completeness'].get('missed_urls', [])}"
            )
            logger.warning("Judge quality_alert: %s", result["quality_alert_reason"])

        _append_judge_history(result, date or datetime.now().strftime("%Y-%m-%d"))
        return result


def _append_judge_history(judge_result: dict, date: str) -> None:
    from ..config import OUTPUT_DIR

    history_file = OUTPUT_DIR / "_judge-history.json"
    history: list[dict] = []
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            history = []
    # 同一天重跑時替換舊記錄
    history = [r for r in history if r.get("date") != date]
    quality = QualityScore.from_dict(judge_result)
    history.append(
        {
            "date": date,
            "overall": quality.overall,
            "scores": {
                "relevance": quality.relevance,
                "completeness": quality.completeness,
                "faithfulness": quality.faithfulness,
            },
            "quality_alert": quality.quality_alert,
        }
    )
    history.sort(key=lambda r: r["date"])
    history_file.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )

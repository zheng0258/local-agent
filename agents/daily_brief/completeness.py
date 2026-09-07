"""完整性校正（Completeness Reconciliation）—— judge → 不足則 reflect 重生 digest → 重評。

這段迴圈原本攤在 agent.run() 裡：orchestrator 得知道 completeness 門檻、missed_urls
plumbing、prompt 重建、要 force 重跑哪兩步。收進單一 seam 後，run() 回歸純地圖，
迴圈本身也有了可直接測的 interface（不必驅動整條 pipeline）。

不變式：judge 一次 → 只在 completeness 有效且 < 門檻、digest 未被使用者 --force、
且已有 digest 的情況下，才 reflect 重生 digest 並重評；其餘一律回傳原 digests。
純編排——不吞例外，不自行落盤（各 Step 自理 artifact I/O）。
"""

from __future__ import annotations

import json

from config import get_logger

from . import prompts
from .schemas import QualityScore
from .step import StepStatus

logger = get_logger(__name__)

# completeness 低於此門檻即觸發 digest 重生（1–5 分制）。
COMPLETENESS_FLOOR = 3


def reconcile_completeness(ctx, enrich_data, digests, source_data) -> list:
    """評 Brief；completeness 不足則 reflect 重生 Digest 再重評，回傳最終 digests。

    completeness 為 None（judge 未給有效分）→ 不校正；digest 在 force_steps（使用者
    明示重跑）→ 不校正，避免與使用者意圖打架；無 digest → 無從校正。
    """
    from .steps.digest import DigestStep
    from .steps.judge import JudgeStep

    judge_outcome = JudgeStep().run(ctx, (enrich_data, digests, source_data))
    if judge_outcome.status is not StepStatus.RAN:
        return digests

    quality = QualityScore.from_dict(judge_outcome.value)
    if not _needs_reconcile(quality, digests, ctx.force_steps):
        return digests

    logger.warning(
        "Judge completeness=%.1f，觸發 digest 重跑（missed: %s）",
        quality.completeness,
        list(quality.missed_urls),
    )
    hint = ctx.supervisor.reflect_for_completeness(
        list(quality.missed_urls),
        prompts.build_digest_prompt_from_compress(
            json.dumps(enrich_data, ensure_ascii=False)
        ),
    )
    digests = DigestStep().run(ctx, enrich_data, reflect=hint, force=True).value
    JudgeStep().run(ctx, (enrich_data, digests, source_data), force=True)
    logger.info("Judge 回饋 digest 重跑完成")
    return digests


def _needs_reconcile(quality: QualityScore, digests, force_steps) -> bool:
    return (
        quality.completeness is not None
        and quality.completeness < COMPLETENESS_FLOOR
        and "digest" not in force_steps
        and bool(digests)
    )

"""JudgeStep — LLM-as-Judge 品質評分（只評分，不含回饋迴圈）。

input 是 (compress_data, digests, source_data) 三元組；source_data 供 faithfulness
對照 fetch 階段原始 title（去循環化）。server 無回應時 raise（讓 supervisor 走 retry/FAILED）。
value = judge_result dict；run() 用它的 status==RAN + QualityScore 決定是否觸發 completeness 回饋。
_judge-history 的側寫由注入的 _run_judge 內部處理（維持不變）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from config.settings import DEFAULT_LOCAL_LLM_URL, check_local_llm

from ..step import Step, StepOutput


class JudgeStep(Step):
    name = "judge"

    def __init__(self, run_judge: Callable[..., dict]) -> None:
        self._run_judge = run_judge

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "judge.json"

    def _guard(self, ctx, input) -> bool:
        compress_data, digests, _source_data = input
        return bool(compress_data) and bool(digests)

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        compress_data, digests, source_data = input
        # fail-fast：judge server 無回應時 raise，讓 supervisor 走 retry/FAILED。
        # 直接用共用工具 check_local_llm，不穿 supervisor seam（Supervisor Protocol = 只有 run_step）。
        judge_url = os.environ.get("JUDGE_LLM_URL", DEFAULT_LOCAL_LLM_URL)
        if not check_local_llm(judge_url, timeout=3):
            raise RuntimeError("judge LLM server 無回應")
        result = self._run_judge(compress_data, digests, source_data, date=ctx.today)
        return StepOutput(persist=result, value=result)

    def _default(self, input):
        return None

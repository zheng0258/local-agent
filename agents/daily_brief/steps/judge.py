"""JudgeStep — LLM-as-Judge 品質評分（只評分，不含回饋迴圈）。

input 是 (compress_data, digests) 二元組。server 無回應時 raise（讓 supervisor 走 retry/FAILED）。
value = judge_result dict；run() 用它的 status==RAN + QualityScore 決定是否觸發 completeness 回饋。
_judge-history 的側寫由注入的 _run_judge 內部處理（維持不變）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..step import Step, StepOutput


class JudgeStep(Step):
    name = "judge"

    def __init__(self, run_judge: Callable[..., dict]) -> None:
        self._run_judge = run_judge

    def artifact_path(self, ctx) -> Path:
        return ctx.steps_dir / "judge.json"

    def _guard(self, ctx, input) -> bool:
        compress_data, digests = input
        return bool(compress_data) and bool(digests)

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        compress_data, digests = input
        if not ctx.supervisor._is_judge_server_available():
            raise RuntimeError("judge LLM server 無回應")
        result = self._run_judge(compress_data, digests, date=ctx.today)
        return StepOutput(persist=result, value=result)

    def _default(self, input):
        return None

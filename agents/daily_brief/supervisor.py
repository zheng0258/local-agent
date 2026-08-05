"""SupervisorAgent — pipeline 步驟執行、重試、self-healing。"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

from config import get_logger, parse_llm_json
from config.settings import DEFAULT_LOCAL_LLM_URL, LLMBackend, check_local_llm

from . import reflect_prompts
from .config import STEP_CONFIGS
from .step import StepResult  # StepResult 現住 step.py（消費者側）；run_step 回傳它

logger = get_logger(__name__)


class SupervisorAgent:

    def __init__(
        self,
        llm: LLMBackend,
        judge_llm: LLMBackend,
        steps_dir: Path,
        today: str,
    ) -> None:
        self._llm = llm
        self._judge_llm = judge_llm
        self._steps_dir = steps_dir
        self._today = today

    def run_step(
        self,
        name: str,
        fn: Callable[..., Any],
        force: bool = False,
    ) -> StepResult:
        """執行一個步驟，失敗時依 strategy 重試。"""
        cfg = STEP_CONFIGS[name]
        start_ts = time.monotonic()
        adjusted_prompts: list[str] = []
        last_error = ""
        output = None

        for attempt in range(1, cfg.max_retries + 1):
            reflect_context = adjusted_prompts[-1] if adjusted_prompts else ""
            try:
                if cfg.strategy == "error_aware":
                    output = fn(reflect_context=reflect_context)
                else:
                    output = fn()
                logger.info(
                    "Step %s: 完成（attempt %d，耗時 %.1fs）",
                    name,
                    attempt,
                    time.monotonic() - start_ts,
                )
                return StepResult(
                    name=name,
                    success=True,
                    output=output,
                    error=None,
                    attempts=attempt,
                    adjusted_prompts=tuple(adjusted_prompts),
                )
            except Exception as exc:
                last_error = str(exc)
                last_output_str = str(output) if output is not None else ""
                logger.warning(
                    "Step %s: attempt %d/%d 失敗 — %s",
                    name, attempt, cfg.max_retries, last_error,
                )

                if attempt < cfg.max_retries:
                    if cfg.strategy == "error_aware":
                        adjusted = self._reflect(
                            step_name=name,
                            task_description=cfg.task_description,
                            bad_output=last_output_str,
                            error=last_error,
                        )
                        if adjusted:
                            adjusted_prompts.append(adjusted)
                    backoff = cfg.backoff_seconds[min(attempt - 1, len(cfg.backoff_seconds) - 1)]
                    if backoff > 0:
                        time.sleep(backoff)

        self._record_failure(name, last_error, force=force)
        return StepResult(
            name=name,
            success=False,
            output=None,
            error=last_error,
            attempts=cfg.max_retries,
            adjusted_prompts=tuple(adjusted_prompts),
        )

    def reflect_for_completeness(
        self, missed_urls: list[str], original_digest_prompt: str
    ) -> str:
        """judge completeness < 3 時產出 digest 重跑用的 reflect 提示；server 無回應則降級回空字串。"""
        judge_url = os.environ.get("JUDGE_LLM_URL", DEFAULT_LOCAL_LLM_URL)
        if check_local_llm(judge_url, timeout=3):
            return self._reflect_with_judge(missed_urls, original_digest_prompt)
        logger.warning("Judge server 無回應，降級：直接用原 prompt 重跑 digest")
        return ""

    # ── 內部方法 ─────────────────────────────────────────────────────

    def _reflect(self, step_name: str, task_description: str, bad_output: str, error: str) -> str:
        """呼叫主 LLM 診斷失敗，回傳 adjusted_prompt（空字串表示失敗）。"""
        try:
            raw = self._llm.complete(
                reflect_prompts.build_reflect_prompt(
                    original_prompt=task_description or f"[step: {step_name}]",
                    bad_output=bad_output,
                    error=error,
                )
            )
            parsed = parse_llm_json(raw)
            diagnosis = parsed.get("diagnosis", "")
            adjusted = parsed.get("adjusted_prompt", "")
            if diagnosis:
                logger.info("Step %s reflect 診斷：%s", step_name, diagnosis)
            return adjusted
        except Exception as exc:
            logger.warning("Step %s reflect LLM 呼叫失敗：%s", step_name, exc)
            return ""

    def _reflect_with_judge(self, missed_urls: list[str], original_prompt: str) -> str:
        """呼叫 judge LLM 針對 completeness 不足產出 adjusted_prompt。"""
        try:
            raw = self._judge_llm.complete(
                reflect_prompts.build_judge_reflect_prompt(missed_urls, original_prompt)
            )
            parsed = parse_llm_json(raw)
            return parsed.get("adjusted_prompt", "")
        except Exception as exc:
            logger.warning("Judge reflect LLM 呼叫失敗：%s", exc)
            return ""

    def _record_failure(self, name: str, error: str, force: bool = False) -> None:
        """把失敗記入 alerts.json（委派 alerts 模組 — Alert 單一 owner），
        同一步驟同一天只記一次（force 重跑時重置）。

        不即時推播：pipeline 收尾的 alert_store.send_summary 讀 alerts.json
        彙總成單封 Telegram，避免 N 個步驟失敗收 N+1 封。
        """
        from . import alerts as alert_store

        if not force and alert_store.already_recorded(self._steps_dir, name):
            logger.info("Step %s: 失敗已記錄過，略過重複記錄", name)
            return
        alert_store.record_failure(self._steps_dir, name, error)


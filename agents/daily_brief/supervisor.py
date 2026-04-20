"""SupervisorAgent — pipeline 步驟執行、重試、self-healing。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from config import get_logger
from config.settings import LLMBackend

from . import reflect_prompts
from .config import STEP_CONFIGS

from tools.notifiers.telegram import send

logger = get_logger(__name__)


@dataclass(frozen=True)
class StepResult:
    name: str
    success: bool
    output: Any
    error: str | None
    attempts: int
    adjusted_prompts: tuple[str, ...] = ()


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
        adjusted_prompts: list[str] = []
        last_error = ""
        output = None

        for attempt in range(1, cfg.max_retries + 1):
            reflect_context = adjusted_prompts[-1] if adjusted_prompts else ""
            try:
                output = fn(reflect_context=reflect_context)
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
                            bad_output=last_output_str,
                            error=last_error,
                        )
                        if adjusted:
                            adjusted_prompts.append(adjusted)
                    backoff = cfg.backoff_seconds[min(attempt - 1, len(cfg.backoff_seconds) - 1)]
                    if backoff > 0:
                        time.sleep(backoff)

        diagnosis = adjusted_prompts[-1][:200] if adjusted_prompts else last_error
        self._notify_failure(name, last_error, cfg.max_retries, diagnosis, force=force)
        return StepResult(
            name=name,
            success=False,
            output=None,
            error=last_error,
            attempts=cfg.max_retries,
            adjusted_prompts=tuple(adjusted_prompts),
        )

    def run_judge_feedback(
        self,
        missed_urls: list[str],
        original_digest_prompt: str,
        run_digest_fn: Callable[..., Any],
        run_judge_fn: Callable[..., Any],
    ) -> tuple[list[dict], dict, dict]:
        """judge completeness < 3 時，用 judge_llm reflect 並重跑 digest + judge（上限 1 次）。"""
        judge_server_ok = self._is_judge_server_available()

        if judge_server_ok:
            reflect_resp = self._reflect_with_judge(missed_urls, original_digest_prompt)
        else:
            logger.warning("Judge server 無回應，降級：直接用原 prompt 重跑 digest")
            reflect_resp = ""

        digests, digest_data = run_digest_fn(reflect_context=reflect_resp)
        judge_result = run_judge_fn(reflect_context="")
        return digests, digest_data, judge_result

    # ── 內部方法 ─────────────────────────────────────────────────────

    def _reflect(self, step_name: str, bad_output: str, error: str) -> str:
        """呼叫主 LLM 診斷失敗，回傳 adjusted_prompt（空字串表示失敗）。"""
        try:
            raw = self._llm.complete(
                reflect_prompts.build_reflect_prompt(
                    original_prompt=f"[step: {step_name}]",
                    bad_output=bad_output,
                    error=error,
                )
            )
            parsed = _parse_reflect_response(raw)
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
            parsed = _parse_reflect_response(raw)
            return parsed.get("adjusted_prompt", "")
        except Exception as exc:
            logger.warning("Judge reflect LLM 呼叫失敗：%s", exc)
            return ""

    def _is_judge_server_available(self) -> bool:
        """快速探測 judge LLM server 是否在線。"""
        import os
        import urllib.error
        import urllib.request

        from config.settings import DEFAULT_LOCAL_LLM_URL

        url = os.environ.get("JUDGE_LLM_URL", DEFAULT_LOCAL_LLM_URL)
        try:
            urllib.request.urlopen(f"{url}/v1/models", timeout=3)
            return True
        except Exception:
            return False

    def _notify_failure(
        self,
        name: str,
        error: str,
        attempts: int,
        diagnosis: str,
        force: bool = False,
    ) -> None:
        """發 Telegram 告警，同一步驟同一天只發一次（force 重跑時重置）。"""
        alerts_file = self._steps_dir / "alerts.json"
        alerts: dict[str, str] = {}
        if alerts_file.exists():
            try:
                alerts = json.loads(alerts_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                alerts = {}

        if name in alerts and not force:
            logger.info("Step %s: 告警已發送過（%s），略過重複告警", name, alerts[name])
            return

        msg = (
            f"⚠️ Daily Brief 步驟失敗（{self._today}）\n\n"
            f"步驟：{name}（嘗試 {attempts} 次）\n"
            f"錯誤：{error[:300]}\n"
            f"診斷：{diagnosis[:300]}\n\n"
            f"建議：python3 main.py \"/daily-brief --force {name}\""
        )
        send(msg)
        alerts[name] = datetime.now().isoformat(timespec="seconds")
        alerts_file.write_text(json.dumps(alerts, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_reflect_response(raw: str) -> dict:
    """從 LLM 輸出解析 reflect JSON（含 json-repair fallback）。"""
    import re

    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    text = m.group(1) if m else raw
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        from json_repair import repair_json

        result = json.loads(repair_json(text))
        if isinstance(result, dict):
            return result
    except Exception:
        pass
    return {}

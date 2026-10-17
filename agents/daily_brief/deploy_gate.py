"""deploy_gate — deploy 前資料品質關卡：先修復、修復失敗才擋。

流程（`run_gate`）：
  1. `invariants.check_day` 判定不可能狀態（檢查本身出錯 → log 後放行，不弄垮 pipeline、
     不憑空停站）。
  2. **發佈內容違規**（leftover_token / unlinked_articles）先修：
     a. 確定性修復（`report_repair.relink_report`：同一套 id 枚舉重替換 token +
        唯一標題比對補連結），無 LLM。
     b. 仍違規 → 允許**一次**以 reflect context 強制重跑 ReportStep（LLM），再檢查。
     修好 → 放行，並在 run manifest 記 `invariants=repaired`（不靜默）。
     仍壞 → 記 `invariants` alert + manifest `deploy=blocked`，擋下（health 的 deploy
     記為 invariant）。修復失敗後的長期處置政策尚未定案，暫維持「擋 + 告警」。
  3. **帳本違規**（zero_tokens）：只記 `ledger` alert、**不擋 deploy**。理由：這是
     觀測帳本的問題，不是發佈內容的問題——報告本身是好的，擋站只會讓讀者看不到
     正確內容；而帳本無可靠的自動修復（token 數無法事後重建），結構性根除另由
     event-ledger 重構處理。alert 鍵刻意不用 `invariants`，避免 health 把 deploy
     誤判為被擋。

副作用（改寫 report.md、alerts、manifest）集中於此；判定與修復邏輯皆為純函數
（invariants / report_repair）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from config import get_logger

from . import alerts as alert_store
from . import invariants, report_repair
from .invariants import Violation
from .reflect_prompts import build_report_link_fix_context

logger = get_logger(__name__)

GATE_ALERT = "invariants"  # 發佈內容違規且修不好 → 擋 deploy（health 讀此鍵）
LEDGER_ALERT = "ledger"  # 帳本違規 → 只告警不擋
GATE_STEP = "invariants"  # run manifest 上的關卡紀錄名（repaired / blocked）
CONTENT_CODES: frozenset[str] = frozenset({"leftover_token", "unlinked_articles"})
LEDGER_CODES: frozenset[str] = frozenset({"zero_tokens"})


@dataclass(frozen=True)
class GateResult:
    allow: bool
    repairs: tuple[str, ...] = ()  # 已執行的修復：relink（有改寫才算）/ report_rerun
    remaining: tuple[Violation, ...] = ()


def _content(violations) -> tuple[Violation, ...]:
    return tuple(v for v in violations if v.code in CONTENT_CODES)


def _relink(day_dir: Path, steps_dir: Path) -> bool:
    """確定性修復 report.md；有改寫才回 True。依據缺席或修復出錯 → False（交給下一層）。"""
    try:
        sources = report_repair.load_link_sources(steps_dir)
        if sources is None:
            logger.warning("資料品質關卡：缺 enrich/digest artifact，無法確定性修復")
            return False
        path = day_dir / "report.md"
        before = path.read_text(encoding="utf-8")
        after = report_repair.relink_report(before, *sources)
        if after == before:
            return False
        path.write_text(after, encoding="utf-8")
        return True
    except Exception as exc:  # 修復出錯 → 當作修不好，往下走（最終擋下）
        logger.warning("資料品質關卡：確定性修復失敗：%s", exc)
        return False


def _rerun(rerun_report: Callable[[str], None], violations) -> bool:
    try:
        rerun_report(build_report_link_fix_context(invariants.format_violations(violations)))
        return True
    except Exception as exc:
        logger.warning("資料品質關卡：重跑 ReportStep 失敗：%s", exc)
        return False


def _safe(fn, *args) -> None:
    """alert 記帳出錯只記 log：放行 / 擋下的決定不受記帳成敗影響。"""
    try:
        fn(*args)
    except Exception as exc:
        logger.warning("資料品質關卡記帳失敗：%s", exc)


def _check(day_dir: Path) -> tuple[Violation, ...]:
    return tuple(invariants.check_day(day_dir))


def run_gate(
    day_dir: Path,
    steps_dir: Path,
    manifest,
    rerun_report: Callable[[str], None] | None = None,
) -> GateResult:
    """檢查 → 修復 → 再檢查；回傳是否放行 deploy。

    rerun_report(reflect_context)：強制重跑 ReportStep 的 hook（run() 注入；None 則跳過
    LLM 那一層）。只在確定性修復後仍有內容違規時呼叫，且最多一次。
    """
    t0 = time.monotonic()
    try:
        violations = _check(day_dir)
    except Exception as exc:  # 關卡不得反過來弄垮 pipeline
        logger.warning("資料品質關卡檢查失敗（放行 deploy）：%s", exc)
        return GateResult(allow=True)

    repairs: list[str] = []
    try:
        if _content(violations) and _relink(day_dir, steps_dir):
            repairs.append("relink")
            violations = _check(day_dir)
        if _content(violations) and rerun_report is not None:
            if _rerun(rerun_report, _content(violations)):
                repairs.append("report_rerun")
            violations = _check(day_dir)
    except Exception as exc:  # 修復後的重新檢查出錯 → 保守視為仍違規
        logger.warning("資料品質關卡：修復後重新檢查失敗：%s", exc)

    ledger = tuple(v for v in violations if v.code in LEDGER_CODES)
    if ledger:
        logger.warning("資料品質關卡：帳本違規（不擋 deploy）：%s", ledger)
        _safe(alert_store.record_failure, steps_dir, LEDGER_ALERT,
              invariants.format_violations(ledger, blocked=False))
    else:
        _safe(alert_store.clear_failure, steps_dir, LEDGER_ALERT)

    blocking = _content(violations)
    if blocking:
        message = invariants.format_violations(blocking)
        logger.error("資料品質關卡擋下 deploy（已嘗試修復：%s）：%s", repairs or "無", message)
        _safe(alert_store.record_failure, steps_dir, GATE_ALERT, message)
        if manifest is not None:
            manifest.record_step(GATE_STEP, "blocked", time.monotonic() - t0)
            manifest.record_step("deploy", "blocked", 0.0)
        return GateResult(allow=False, repairs=tuple(repairs), remaining=violations)

    _safe(alert_store.clear_failure, steps_dir, GATE_ALERT)
    if repairs:
        logger.warning("資料品質關卡：report.md 已自動修復（%s），放行 deploy", ", ".join(repairs))
        if manifest is not None:
            manifest.record_step(GATE_STEP, "repaired", time.monotonic() - t0)
    return GateResult(allow=True, repairs=tuple(repairs), remaining=violations)

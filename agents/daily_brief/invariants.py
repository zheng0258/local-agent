"""invariants — deploy 前資料品質關卡（L1 不可能狀態檢查）。

pipeline 的韌性設計（≥2 來源門檻、失敗回 default）讓壞資料也能一路走到 deploy，
health 照樣全綠。10-15 起實例：快取重跑把六天 token 帳本覆寫成 0；report.md 的
`[標題](@@id@@)` token 未替換就上站。兩者都是「不可能狀態」——邏輯上不該存在，
出現即代表上游有 bug。此模組只負責**判定**：純函數吃已落盤的當日痕跡，回傳違規
清單；記 alert / 擋 deploy 的副作用由 agent._deploy_gate 承擔。

與 health 同為「事後檢視痕跡」，不汙染 Step。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .config import FETCH_STEPS

# 會呼叫 chat LLM 的步驟（Source 評分 + LLM producer）。dedup 走 embedding、
# save / notify / deploy 無 LLM，它們 ran 而 0 tokens 是合理狀態。
LLM_STEPS: frozenset[str] = frozenset(
    {*FETCH_STEPS, "compress", "enrich", "digest", "tldr", "judge", "report", "compose_tg"}
)

_TOKEN_RE = re.compile(r"@@\d+@@")
_ARTICLE_ROW_RE = re.compile(r"^\s*(?:\d+\.|[-*•])\s|^\s*\|")
# 文章列的熱度標記：(288 users) / (1234pt) / (1,234 ups)。report_repair 共用。
ARTICLE_MARKER_RE = re.compile(r"\(\s*\d[\d,]*\s*(?:users|pt|ups)\s*\)")
_HTTP_LINK_RE = re.compile(r"\]\(https?://")
_SAMPLE_MAX = 3
_SAMPLE_CHARS = 60


@dataclass(frozen=True)
class Violation:
    """一筆不可能狀態：code 供機器判別，detail 供人讀。"""

    code: str
    detail: str


def check_token_ledger(
    run_summary: Mapping | None, usage_summary: Mapping | None
) -> tuple[Violation, ...]:
    """LLM 步驟本次真的跑了（ran），帳本卻是 0 tokens → 帳本被覆寫或沒記到。"""
    steps = (run_summary or {}).get("steps") or {}
    ran_llm = sorted(
        name
        for name, info in steps.items()
        if name in LLM_STEPS and str((info or {}).get("status", "")) == "ran"
    )
    if not ran_llm:
        return ()
    totals = (usage_summary or {}).get("totals") or {}
    total = totals.get("total_tokens", 0) if isinstance(totals, Mapping) else 0
    if isinstance(total, (int, float)) and total > 0:
        return ()
    return (
        Violation(
            "zero_tokens",
            f"LLM 步驟 {', '.join(ran_llm)} 本次已執行，但 _usage.json total_tokens=0",
        ),
    )


def is_unlinked_article_row(line: str) -> bool:
    """清單項 / 表格列、帶熱度標記、卻沒有 http(s) markdown 連結的文章列。"""
    return bool(
        _ARTICLE_ROW_RE.match(line)
        and ARTICLE_MARKER_RE.search(line)
        and not _HTTP_LINK_RE.search(line)
    )


def _sample(lines: Sequence[str]) -> str:
    return "；".join(line.strip()[:_SAMPLE_CHARS] for line in lines[:_SAMPLE_MAX])


def check_report(report_md: str | None) -> tuple[Violation, ...]:
    """report.md 不得殘留 id token，文章列（清單項 / 表格列帶熱度標記）必須有 http(s) 連結。"""
    if not report_md:
        return ()
    lines = report_md.splitlines()
    violations: list[Violation] = []

    leftover = [line for line in lines if _TOKEN_RE.search(line)]
    if leftover:
        violations.append(
            Violation(
                "leftover_token",
                f"report.md 殘留 {len(leftover)} 行 @@id@@ token：{_sample(leftover)}",
            )
        )

    unlinked = [line for line in lines if is_unlinked_article_row(line)]
    if unlinked:
        violations.append(
            Violation(
                "unlinked_articles",
                f"report.md 有 {len(unlinked)} 篇文章列沒有 http(s) 連結：{_sample(unlinked)}",
            )
        )
    return tuple(violations)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def check_day(day_dir: Path) -> tuple[Violation, ...]:
    """讀當日落盤痕跡（steps/_run.json、steps/_usage.json、report.md）跑全部檢查。"""
    steps_dir = day_dir / "steps"
    report_path = day_dir / "report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else None
    return (
        *check_token_ledger(
            _read_json(steps_dir / "_run.json"), _read_json(steps_dir / "_usage.json")
        ),
        *check_report(report),
    )


def format_violations(violations: Sequence[Violation], blocked: bool = True) -> str:
    """alert 用的單行文字（alerts.record_failure 會截在 300 字內）。"""
    prefix = "deploy 已擋下：" if blocked else "（未擋 deploy）"
    return prefix + " | ".join(f"[{v.code}] {v.detail}" for v in violations)

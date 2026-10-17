"""invariants — deploy 前資料品質關卡（L1 不可能狀態檢查）的純函數測試。"""

import json

import pytest

from agents.daily_brief.invariants import (
    LLM_STEPS,
    Violation,
    check_day,
    check_report,
    check_token_ledger,
    format_violations,
)

pytestmark = pytest.mark.unit


def _run(**statuses: str) -> dict:
    return {
        "date": "2026-10-17",
        "steps": {n: {"status": s, "duration_seconds": 1.0} for n, s in statuses.items()},
    }


def _usage(total: int) -> dict:
    return {"date": "2026-10-17", "totals": {"calls": 1, "total_tokens": total}}


# ── token 帳本 ──────────────────────────────────────────────────


def test_ledger_flags_llm_step_ran_with_zero_tokens():
    violations = check_token_ledger(_run(digest="ran", save="ran"), _usage(0))
    assert [v.code for v in violations] == ["zero_tokens"]
    assert "digest" in violations[0].detail


def test_ledger_ok_when_tokens_recorded():
    assert check_token_ledger(_run(digest="ran"), _usage(1234)) == ()


def test_ledger_ok_when_only_non_llm_steps_ran():
    # save / notify / deploy / dedup 不呼叫 chat LLM，0 tokens 合理
    assert check_token_ledger(_run(dedup="ran", save="ran", notify="ran"), _usage(0)) == ()


def test_ledger_ok_when_llm_steps_only_loaded():
    # 快取重跑：全部 loaded、0 次 LLM 呼叫 —— 0 tokens 是合理狀態
    assert check_token_ledger(_run(digest="loaded", judge="loaded"), _usage(0)) == ()


def test_ledger_flags_missing_usage_when_llm_ran():
    violations = check_token_ledger(_run(report="ran"), None)
    assert [v.code for v in violations] == ["zero_tokens"]


def test_ledger_ok_without_run_manifest():
    assert check_token_ledger(None, None) == ()


def test_llm_steps_cover_sources_and_llm_producers():
    assert {"hatena", "rss", "compress", "digest", "judge", "report", "compose_tg"} <= LLM_STEPS
    assert not {"dedup", "save", "notify", "deploy"} & LLM_STEPS


# ── report.md ───────────────────────────────────────────────────

_GOOD_REPORT = """# Daily Brief

## Hatena
1. [標題 A](https://a.example/x) (288 users) — 摘要
2. [漢堡王 App | NHK 新聞](https://b.example/y) (98 users) — 摘要

## HN
| 標題 | 分數 |
|---|---|
| [標題 C](https://c.example) | 1234pt |
1. [標題 D](http://d.example) (289pt) — 摘要

## Reddit
- [標題 E](https://e.example) (1,234 ups) — r/x — 摘要
"""


def test_report_clean_has_no_violations():
    assert check_report(_GOOD_REPORT) == ()


def test_report_flags_leftover_token():
    text = _GOOD_REPORT + "\n3. [標題 F](@@7@@) (5 users) — 摘要\n"
    codes = {v.code for v in check_report(text)}
    assert "leftover_token" in codes


def test_report_flags_bare_token():
    codes = {v.code for v in check_report("見 @@12@@ 的說明\n")}
    assert codes == {"leftover_token"}


def test_report_flags_article_line_without_link():
    text = _GOOD_REPORT + "3. 標題 G (77 users) — 降級成純文字\n- 標題 H (12pt) — x\n"
    violations = [v for v in check_report(text) if v.code == "unlinked_articles"]
    assert len(violations) == 1
    assert "2" in violations[0].detail


def test_report_flags_unlinked_table_row():
    text = "| 標題 I (300 users) | 300 | *** |\n"
    assert [v.code for v in check_report(text)] == ["unlinked_articles"]


def test_report_ignores_prose_mentioning_users():
    # 非清單 / 非表格的敘述行不算文章列
    assert check_report("今天整體 (100 users) 的熱度偏低。\n") == ()


def test_report_missing_is_not_a_violation():
    # 沒有 report.md 時 DeployStep 自身的 guard 會略過，不由此處判定
    assert check_report(None) == ()


# ── check_day（讀檔）─────────────────────────────────────────────


def _write_day(day_dir, run=None, usage=None, report=None):
    steps = day_dir / "steps"
    steps.mkdir(parents=True)
    if run is not None:
        (steps / "_run.json").write_text(json.dumps(run), encoding="utf-8")
    if usage is not None:
        (steps / "_usage.json").write_text(json.dumps(usage), encoding="utf-8")
    if report is not None:
        (day_dir / "report.md").write_text(report, encoding="utf-8")


def test_check_day_combines_all_checks(tmp_path):
    _write_day(
        tmp_path,
        run=_run(report="ran"),
        usage=_usage(0),
        report="1. [x](@@1@@) (5 users) — y\n",
    )
    codes = {v.code for v in check_day(tmp_path)}
    assert codes == {"zero_tokens", "leftover_token", "unlinked_articles"}


def test_check_day_clean(tmp_path):
    _write_day(tmp_path, run=_run(report="ran"), usage=_usage(99), report=_GOOD_REPORT)
    assert check_day(tmp_path) == ()


def test_check_day_tolerates_corrupt_json(tmp_path):
    _write_day(tmp_path, report=_GOOD_REPORT)
    (tmp_path / "steps" / "_run.json").write_text("{壞", encoding="utf-8")
    assert check_day(tmp_path) == ()


def test_format_violations_lists_each():
    text = format_violations(
        (Violation("zero_tokens", "a"), Violation("leftover_token", "b"))
    )
    assert "zero_tokens" in text and "leftover_token" in text

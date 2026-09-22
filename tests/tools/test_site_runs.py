"""site_builder.runs — 純函數：judge/health/usage/manifest 歷史 → RunRecord 串。

純記憶體：無 git / LLM / 網路 / 檔案副作用。loader (load_runs) 才碰檔案。
"""

import pytest

from tools.site_builder.runs import (
    RunRecord,
    StepTiming,
    compute_runs,
    run_status,
)

pytestmark = pytest.mark.unit


def _health(*records):
    return [{"date": d, "results": r} for d, r in records]


def _judge(*pairs):
    return [{"date": d, "overall": o} for d, o in pairs]


def _usage(*rows):
    return [{"date": d, "calls": c, "total_tokens": t} for d, c, t in rows]


ALL_OK = {
    "hatena": "ok",
    "hn": "ok",
    "reddit": "ok",
    "security": "ok",
    "rss": "ok",
    "telegram": "ok",
    "vault": "ok",
    "deploy": "ok",
}


def test_run_status_success_when_all_ok():
    assert run_status(ALL_OK) == "success"


def test_run_status_partial_when_delivery_fails_but_sources_ok():
    r = {**ALL_OK, "deploy": "other"}
    assert run_status(r) == "partial"


def test_run_status_failed_when_fewer_than_two_sources_ok():
    r = {
        "hatena": "network",
        "hn": "network",
        "reddit": "ok",
        "security": "network",
        "rss": "network",
    }
    assert run_status(r) == "failed"


def test_run_status_unknown_when_no_health():
    assert run_status({}) == "unknown"


def test_compute_runs_newest_first():
    runs = compute_runs(
        judge_history=_judge(("2026-09-20", 4.2), ("2026-09-21", 4.0)),
        health_history=_health(("2026-09-20", ALL_OK), ("2026-09-21", ALL_OK)),
    )
    assert [r.date for r in runs] == ["2026-09-21", "2026-09-20"]
    assert isinstance(runs[0], RunRecord)


def test_compute_runs_merges_all_histories_by_date():
    runs = compute_runs(
        judge_history=_judge(("2026-09-22", 4.1)),
        health_history=_health(("2026-09-22", {**ALL_OK, "deploy": "other"})),
        usage_history=_usage(("2026-09-22", 42, 1_420_000)),
    )
    (run,) = runs
    assert run.overall == 4.1
    assert run.tokens_total == 1_420_000
    assert run.calls == 42
    assert run.status == "partial"


def test_compute_runs_missing_fields_are_none():
    # 只有 health 有該日 → judge/usage/manifest 欄位皆 None，不報錯。
    (run,) = compute_runs(
        judge_history=[],
        health_history=_health(("2026-09-19", ALL_OK)),
    )
    assert run.overall is None
    assert run.tokens_total is None
    assert run.duration_seconds is None
    assert run.trigger is None
    assert run.steps == ()


def test_compute_runs_includes_manifest_timings():
    manifests = [
        {
            "date": "2026-09-22",
            "trigger": "cron",
            "git_sha": "8fbe2a3",
            "duration_seconds": 11640.0,
            "steps": {
                "digest": {"status": "ran", "duration_seconds": 1620.0},
                "deploy": {"status": "failed", "duration_seconds": 3.0},
            },
        }
    ]
    (run,) = compute_runs(
        judge_history=[],
        health_history=_health(("2026-09-22", ALL_OK)),
        run_manifests=manifests,
    )
    assert run.trigger == "cron"
    assert run.git_sha == "8fbe2a3"
    assert run.duration_seconds == 11640.0
    assert StepTiming("digest", "ran", 1620.0) in run.steps
    assert any(s.name == "deploy" and s.status == "failed" for s in run.steps)


def test_compute_runs_tolerates_malformed_rows():
    runs = compute_runs(
        judge_history=["oops", {"no_date": 1}],
        health_history=_health(("2026-09-18", ALL_OK)),
        usage_history=[None, 5],
    )
    assert [r.date for r in runs] == ["2026-09-18"]

"""deploy 前資料品質關卡：先修復、修復失敗才擋；alerts / health / 運行紀錄皆可見。"""

import json

import pytest

from agents.daily_brief import deploy_gate
from agents.daily_brief.alerts import (
    clear_failure,
    load_alerts,
    record_failure,
    send_summary,
)
from agents.daily_brief.deploy_gate import run_gate
from agents.daily_brief.health import ErrorClass, observe_run, render_health_table
from agents.daily_brief.run_manifest import RunManifest

pytestmark = pytest.mark.unit

_DAY = "2026-10-17"
_ENRICH = {"hatena": {"articles": [{"title": "標題甲", "url": "https://a.example/0"}]}}
_DIGESTS = [{"title": "標題甲", "url": "https://a.example/0"}]

_GOOD_REPORT = "1. [標題甲](https://a.example/0) (10 users) — 摘要\n"
_TOKEN_REPORT = "1. [標題甲](@@0@@) (10 users) — 摘要\n"  # 確定性可修
_UNFIXABLE_REPORT = "1. 沒人認得的標題 (10 users) — 摘要\n"  # 無 token、標題比不到


def _day(tmp_path, report: str, with_sources: bool = True):
    day_dir = tmp_path / _DAY
    steps_dir = day_dir / "steps"
    steps_dir.mkdir(parents=True)
    (day_dir / "report.md").write_text(report, encoding="utf-8")
    if with_sources:
        (steps_dir / "enrich.json").write_text(json.dumps(_ENRICH), encoding="utf-8")
        (steps_dir / "digest.json").write_text(
            json.dumps({"digests": _DIGESTS}), encoding="utf-8"
        )
    return day_dir, steps_dir


def _steps(manifest: RunManifest) -> dict:
    return manifest.summarize(_DAY)["steps"]


def _report(day_dir) -> str:
    return (day_dir / "report.md").read_text(encoding="utf-8")


# ── alerts.clear_failure ────────────────────────────────────────


def test_clear_failure_removes_only_named(tmp_path):
    record_failure(tmp_path, "invariants", "x")
    record_failure(tmp_path, "judge", "y")
    clear_failure(tmp_path, "invariants")
    assert set(load_alerts(tmp_path)) == {"judge"}


def test_clear_failure_noop_without_store(tmp_path):
    clear_failure(tmp_path, "invariants")
    assert not (tmp_path / "alerts.json").exists()


# ── 乾淨日 ──────────────────────────────────────────────────────


def test_clean_day_passes_and_clears_stale_alerts(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _GOOD_REPORT)
    record_failure(steps_dir, "invariants", "早上那次 run 的違規")
    record_failure(steps_dir, "ledger", "早上那次 run 的帳本")
    manifest = RunManifest()

    result = run_gate(day_dir, steps_dir, manifest)

    assert result.allow and result.repairs == ()
    assert not {"invariants", "ledger"} & set(load_alerts(steps_dir))
    assert "invariants" not in _steps(manifest) and "deploy" not in _steps(manifest)


# ── 確定性修復 ──────────────────────────────────────────────────


def test_deterministic_relink_repairs_and_allows(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _TOKEN_REPORT)
    manifest = RunManifest()

    result = run_gate(day_dir, steps_dir, manifest)

    assert result.allow
    assert result.repairs == ("relink",)
    assert _report(day_dir) == _GOOD_REPORT
    assert "invariants" not in load_alerts(steps_dir)
    # 修復不得靜默：運行紀錄記 invariants=repaired
    assert _steps(manifest)["invariants"]["status"] == "repaired"


def test_relink_success_does_not_call_llm_rerun(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _TOKEN_REPORT)
    calls = []

    run_gate(day_dir, steps_dir, RunManifest(), rerun_report=calls.append)

    assert calls == []


# ── LLM 重跑 ReportStep（確定性修不好時，一次）──────────────────


def test_llm_rerun_used_once_when_relink_fails(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _UNFIXABLE_REPORT)
    calls = []

    def rerun(reflect: str) -> None:
        calls.append(reflect)
        (day_dir / "report.md").write_text(_GOOD_REPORT, encoding="utf-8")

    manifest = RunManifest()
    result = run_gate(day_dir, steps_dir, manifest, rerun_report=rerun)

    assert result.allow
    assert result.repairs == ("report_rerun",)
    assert len(calls) == 1
    assert "unlinked_articles" in calls[0]  # reflect context 帶上違規細節
    assert _steps(manifest)["invariants"]["status"] == "repaired"


def test_blocks_when_llm_rerun_still_bad(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _UNFIXABLE_REPORT)
    calls = []
    manifest = RunManifest()

    result = run_gate(day_dir, steps_dir, manifest, rerun_report=calls.append)

    assert not result.allow
    assert len(calls) == 1
    assert "unlinked_articles" in load_alerts(steps_dir)["invariants"]["error"]
    assert _steps(manifest)["deploy"]["status"] == "blocked"
    assert _steps(manifest)["invariants"]["status"] == "blocked"


def test_blocks_when_llm_rerun_raises(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _UNFIXABLE_REPORT)

    def rerun(_reflect):
        raise RuntimeError("LM Studio down")

    result = run_gate(day_dir, steps_dir, RunManifest(), rerun_report=rerun)
    assert not result.allow
    assert "invariants" in load_alerts(steps_dir)


def test_blocks_without_rerun_hook_when_relink_fails(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _UNFIXABLE_REPORT)
    assert not run_gate(day_dir, steps_dir, RunManifest()).allow


def test_blocks_when_link_sources_missing(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _TOKEN_REPORT, with_sources=False)
    result = run_gate(day_dir, steps_dir, RunManifest())
    assert not result.allow
    assert _report(day_dir) == _TOKEN_REPORT  # 沒依據就不動


# ── zero_tokens：帳本問題，不擋、只記 alert ─────────────────────


def _zero_ledger(steps_dir):
    (steps_dir / "_run.json").write_text(
        json.dumps({"steps": {"digest": {"status": "ran"}}}), encoding="utf-8"
    )
    (steps_dir / "_usage.json").write_text(
        json.dumps({"totals": {"total_tokens": 0}}), encoding="utf-8"
    )


def test_zero_tokens_alerts_but_does_not_block(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _GOOD_REPORT)
    _zero_ledger(steps_dir)
    manifest = RunManifest()

    result = run_gate(day_dir, steps_dir, manifest)

    assert result.allow
    alerts = load_alerts(steps_dir)
    assert "zero_tokens" in alerts["ledger"]["error"]
    assert "invariants" not in alerts  # 不讓 health 把 deploy 誤判為被擋
    assert "deploy" not in _steps(manifest)


def test_zero_tokens_plus_unfixable_content_still_blocks(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _UNFIXABLE_REPORT)
    _zero_ledger(steps_dir)
    result = run_gate(day_dir, steps_dir, RunManifest())
    assert not result.allow
    assert {"ledger", "invariants"} <= set(load_alerts(steps_dir))


# ── 不反噬 pipeline ─────────────────────────────────────────────


def test_fails_open_when_checker_crashes(tmp_path, monkeypatch):
    day_dir, steps_dir = _day(tmp_path, _UNFIXABLE_REPORT)

    def boom(_day_dir):
        raise RuntimeError("checker bug")

    monkeypatch.setattr(deploy_gate.invariants, "check_day", boom)
    assert run_gate(day_dir, steps_dir, RunManifest()).allow


def test_relink_crash_falls_through_to_block(tmp_path, monkeypatch):
    day_dir, steps_dir = _day(tmp_path, _TOKEN_REPORT)

    def boom(*_args):
        raise RuntimeError("repair bug")

    monkeypatch.setattr(deploy_gate.report_repair, "relink_report", boom)
    assert not run_gate(day_dir, steps_dir, RunManifest()).allow


def test_tolerates_missing_manifest(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _UNFIXABLE_REPORT)
    assert not run_gate(day_dir, steps_dir, None).allow


# ── health / 摘要可見 ───────────────────────────────────────────


def test_health_marks_deploy_invariant_when_blocked(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _UNFIXABLE_REPORT)
    (day_dir / "deploy.done").touch()  # 同日稍早已發佈過，這次 run 仍要看得出被擋
    run_gate(day_dir, steps_dir, RunManifest())

    record = observe_run(_DAY, day_dir, steps_dir)
    assert record.results["deploy"] == ErrorClass.INVARIANT.value
    table = render_health_table([record], today=_DAY)
    assert "invariant" in next(l for l in table.splitlines() if "deploy" in l)


def test_health_deploy_unaffected_by_ledger_alert(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _GOOD_REPORT)
    _zero_ledger(steps_dir)
    (day_dir / "deploy.done").touch()
    run_gate(day_dir, steps_dir, RunManifest())
    assert observe_run(_DAY, day_dir, steps_dir).results["deploy"] == "ok"


def test_summary_lists_gate_alerts_without_bogus_rerun_command(tmp_path):
    record_failure(tmp_path, "invariants", "deploy 已擋下：[leftover_token] x")
    record_failure(tmp_path, "ledger", "[zero_tokens] y")
    sent = []
    send_summary(tmp_path, _DAY, lambda msg: sent.append(msg) or True)

    assert len(sent) == 1
    assert "invariants" in sent[0] and "ledger" in sent[0]
    assert "--force" not in sent[0]

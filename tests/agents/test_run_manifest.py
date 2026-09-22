"""run_manifest — 單次 run 的耗時/步驟/觸發/版本紀錄（純模組 + Step 計時掛鉤）。"""

import json

import pytest

from agents.daily_brief.run_manifest import (
    RunManifest,
    append_history,
    detect_trigger,
    load_history,
)

pytestmark = pytest.mark.unit


def test_detect_trigger_scheduled_when_no_flags():
    assert detect_trigger("") == "scheduled"


def test_detect_trigger_manual_with_force_flag():
    assert detect_trigger("--force deploy") == "manual"
    assert detect_trigger("/daily-brief --only judge") == "manual"


def test_record_step_and_summarize_shape():
    m = RunManifest(trigger="scheduled", sha="abc1234")
    m.record_step("digest", "ran", 1620.0)
    m.record_step("deploy", "failed", 3.2)
    summary = m.summarize("2026-09-22")

    assert summary["date"] == "2026-09-22"
    assert summary["trigger"] == "scheduled"
    assert summary["git_sha"] == "abc1234"
    assert "started_at" in summary and "ended_at" in summary
    assert summary["duration_seconds"] >= 0
    assert summary["steps"]["digest"] == {"status": "ran", "duration_seconds": 1620.0}
    assert summary["steps"]["deploy"]["status"] == "failed"


def test_record_step_last_write_wins():
    m = RunManifest()
    m.record_step("judge", "failed", 1.0)
    m.record_step("judge", "ran", 5.0)
    assert m.summarize("2026-09-22")["steps"]["judge"]["status"] == "ran"


def test_append_history_idempotent_same_day(tmp_path):
    f = tmp_path / "_run-history.json"
    m = RunManifest(trigger="scheduled")
    m.record_step("digest", "ran", 10.0)
    append_history(f, m.summarize("2026-09-22"))
    append_history(f, m.summarize("2026-09-22"))  # 同日重跑覆寫
    rows = json.loads(f.read_text(encoding="utf-8"))
    assert len([r for r in rows if r["date"] == "2026-09-22"]) == 1


def test_load_history_missing_returns_empty(tmp_path):
    assert load_history(tmp_path / "nope.json") == []


def test_step_run_records_timing_into_manifest(tmp_path):
    # Step.run 計時外殼：跑一個真 Step（SaveStep）並確認耗時/狀態進 manifest。
    from agents.daily_brief.steps.save import SaveStep
    from tests.fakes import make_step_ctx

    manifest = RunManifest()
    ctx = make_step_ctx(tmp_path, steps_to_run={"save"}, run_manifest=manifest)
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")

    SaveStep(today="2026-06-21", save=lambda *a: None).run(ctx, [{"url": "http://a"}])

    steps = manifest.summarize("2026-06-21")["steps"]
    assert "save" in steps
    assert steps["save"]["status"] == "ran"
    assert steps["save"]["duration_seconds"] >= 0

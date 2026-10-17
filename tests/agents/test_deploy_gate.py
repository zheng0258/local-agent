"""deploy 前資料品質關卡的接線：alerts 記錄 / health 可見 / 運行紀錄可見 / 不反噬 pipeline。"""

import json

import pytest

from agents.daily_brief import agent as agent_mod
from agents.daily_brief.alerts import clear_failure, load_alerts, record_failure
from agents.daily_brief.health import ErrorClass, observe_run, render_health_table
from agents.daily_brief.run_manifest import RunManifest

pytestmark = pytest.mark.unit

_BAD_REPORT = "1. [標題](@@3@@) (10 users) — 摘要\n"
_GOOD_REPORT = "1. [標題](https://a.example) (10 users) — 摘要\n"


def _day(tmp_path, report: str):
    day_dir = tmp_path / "2026-10-17"
    steps_dir = day_dir / "steps"
    steps_dir.mkdir(parents=True)
    (day_dir / "report.md").write_text(report, encoding="utf-8")
    return day_dir, steps_dir


# ── alerts.clear_failure ────────────────────────────────────────


def test_clear_failure_removes_only_named(tmp_path):
    record_failure(tmp_path, "invariants", "x")
    record_failure(tmp_path, "judge", "y")
    clear_failure(tmp_path, "invariants")
    assert set(load_alerts(tmp_path)) == {"judge"}


def test_clear_failure_noop_without_store(tmp_path):
    clear_failure(tmp_path, "invariants")
    assert not (tmp_path / "alerts.json").exists()


# ── _deploy_gate ────────────────────────────────────────────────


def test_gate_blocks_and_records_alert_on_violation(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _BAD_REPORT)
    manifest = RunManifest()

    assert agent_mod._deploy_gate(day_dir, steps_dir, manifest) is False

    alerts = load_alerts(steps_dir)
    assert "leftover_token" in alerts["invariants"]["error"]
    # 運行紀錄可見：deploy 一步記為 blocked
    assert manifest.summarize("2026-10-17")["steps"]["deploy"]["status"] == "blocked"


def test_gate_passes_clean_day_and_clears_stale_alert(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _GOOD_REPORT)
    record_failure(steps_dir, "invariants", "早上那次 run 的違規")
    manifest = RunManifest()

    assert agent_mod._deploy_gate(day_dir, steps_dir, manifest) is True

    assert "invariants" not in load_alerts(steps_dir)
    assert "deploy" not in manifest.summarize("2026-10-17")["steps"]


def test_gate_fails_open_when_checker_crashes(tmp_path, monkeypatch):
    day_dir, steps_dir = _day(tmp_path, _BAD_REPORT)

    def boom(_day_dir):
        raise RuntimeError("checker bug")

    monkeypatch.setattr(agent_mod.invariants, "check_day", boom)
    # 檢查本身出錯不得弄垮 pipeline，也不憑空擋 deploy
    assert agent_mod._deploy_gate(day_dir, steps_dir, RunManifest()) is True


def test_gate_tolerates_missing_manifest(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _BAD_REPORT)
    assert agent_mod._deploy_gate(day_dir, steps_dir, None) is False


# ── health 可見 ─────────────────────────────────────────────────


def test_health_marks_deploy_invariant_when_blocked(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _BAD_REPORT)
    agent_mod._deploy_gate(day_dir, steps_dir, RunManifest())

    record = observe_run("2026-10-17", day_dir, steps_dir)
    assert record.results["deploy"] == ErrorClass.INVARIANT.value


def test_health_invariant_overrides_earlier_successful_deploy(tmp_path):
    # 同日稍早已發佈過（deploy.done 在），這次 run 的資料卻壞了 → 仍要看得出被擋
    day_dir, steps_dir = _day(tmp_path, _BAD_REPORT)
    (day_dir / "deploy.done").touch()
    agent_mod._deploy_gate(day_dir, steps_dir, RunManifest())

    record = observe_run("2026-10-17", day_dir, steps_dir)
    assert record.results["deploy"] == ErrorClass.INVARIANT.value


def test_health_table_shows_invariant(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _BAD_REPORT)
    agent_mod._deploy_gate(day_dir, steps_dir, RunManifest())
    record = observe_run("2026-10-17", day_dir, steps_dir)

    table = render_health_table([record], today="2026-10-17")
    deploy_line = next(line for line in table.splitlines() if "deploy" in line)
    assert "invariant" in deploy_line


# ── 漏斗：run() 的 deploy 前快照之後才檢查（讀得到當日 _run/_usage）──────


def test_gate_sees_persisted_ledger(tmp_path):
    day_dir, steps_dir = _day(tmp_path, _GOOD_REPORT)
    (steps_dir / "_run.json").write_text(
        json.dumps({"steps": {"digest": {"status": "ran"}}}), encoding="utf-8"
    )
    (steps_dir / "_usage.json").write_text(
        json.dumps({"totals": {"total_tokens": 0}}), encoding="utf-8"
    )
    assert agent_mod._deploy_gate(day_dir, steps_dir, RunManifest()) is False
    assert "zero_tokens" in load_alerts(steps_dir)["invariants"]["error"]


# ── 當日 Telegram 摘要接得到 ────────────────────────────────────


def test_summary_lists_invariants_without_bogus_rerun_command(tmp_path):
    from agents.daily_brief.alerts import send_summary

    record_failure(tmp_path, "invariants", "deploy 已擋下：[leftover_token] x")
    sent = []
    send_summary(tmp_path, "2026-10-17", lambda msg: sent.append(msg) or True)

    assert len(sent) == 1
    assert "invariants" in sent[0]
    assert "--force invariants" not in sent[0]

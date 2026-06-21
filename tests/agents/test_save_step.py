"""SaveStep — SentinelCodec(vault.done), guards on digests + report.md, side-effect _run_save."""

from types import SimpleNamespace

import pytest

from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.save import SaveStep


class _FakeSupervisor:
    def run_step(self, name, fn, force=False):
        return SimpleNamespace(success=True, output=fn())


def _ctx(tmp_path, steps_to_run={"save"}, force=set()):
    return SimpleNamespace(steps_dir=tmp_path, day_dir=tmp_path,
                           steps_to_run=steps_to_run, force_steps=force,
                           supervisor=_FakeSupervisor())


@pytest.mark.unit
def test_save_step_runs_and_touches_sentinel(tmp_path):
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")
    captured = {}

    def fake_run_save(day_dir, today, digests):
        captured["args"] = (day_dir, today, digests)

    outcome = SaveStep(fake_run_save, today="2026-06-21").run(
        _ctx(tmp_path), [{"url": "http://a"}])

    assert outcome.status is StepStatus.RAN
    assert (tmp_path / "vault.done").exists()
    assert captured["args"] == (tmp_path, "2026-06-21", [{"url": "http://a"}])


@pytest.mark.unit
def test_save_step_guard_blocks_without_report_md(tmp_path):
    outcome = SaveStep(lambda *a: None, today="2026-06-21").run(
        _ctx(tmp_path), [{"url": "http://a"}])
    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "vault.done").exists()


@pytest.mark.unit
def test_save_step_loads_when_sentinel_exists(tmp_path):
    (tmp_path / "vault.done").touch()
    called = {"n": 0}

    def fake_run_save(day_dir, today, digests):
        called["n"] += 1

    outcome = SaveStep(fake_run_save, today="2026-06-21").run(
        _ctx(tmp_path), [{"url": "http://a"}])
    assert outcome.status is StepStatus.LOADED
    assert called["n"] == 0

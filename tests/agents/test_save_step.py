"""SaveStep — SentinelCodec(vault.done), guards on digests + report.md, side-effect _run_save."""

from types import SimpleNamespace

import pytest

from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.save import SaveStep
from tests.fakes import make_step_ctx


def _ctx(tmp_path, steps_to_run={"save"}, force=set()):
    return make_step_ctx(tmp_path, steps_to_run=steps_to_run, force_steps=force)


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
def test_save_step_skips_when_vault_unconfigured(tmp_path, monkeypatch):
    # 產品化：未配置 VAULT_ROOT（VAULT_DAILY_BRIEF_DIR is None）時整步略過
    import agents.daily_brief.config as cfg

    monkeypatch.setattr(cfg, "VAULT_DAILY_BRIEF_DIR", None)
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")
    called = {"n": 0}

    def fake_run_save(day_dir, today, digests):
        called["n"] += 1

    outcome = SaveStep(fake_run_save, today="2026-06-21").run(
        _ctx(tmp_path), [{"url": "http://a"}])

    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "vault.done").exists()
    assert called["n"] == 0


@pytest.mark.unit
def test_save_step_skips_when_vault_path_missing(tmp_path, monkeypatch):
    # 已配置但 vault 根目錄不存在（誤填）→ 略過，不建假目錄樹、不寫 sentinel
    import agents.daily_brief.config as cfg

    bogus = tmp_path / "nope" / "01 Projects" / "daily-brief"
    monkeypatch.setattr(cfg, "VAULT_DAILY_BRIEF_DIR", bogus)
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")

    outcome = SaveStep(lambda *a: None, today="2026-06-21").run(
        _ctx(tmp_path), [{"url": "http://a"}])

    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "vault.done").exists()
    assert not bogus.exists()


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

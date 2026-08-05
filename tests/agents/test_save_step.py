"""SaveStep — SentinelCodec(vault.done); save 邏輯住 save.py（run_save），

預設注入 _produce，測試以 save= 覆寫成 fake（合法 side-effect seam，不碰真 vault）。
run_save + format_obsidian_digest 的直接測試亦在此。
"""

import pytest

from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.save import SaveStep, format_obsidian_digest, run_save
from tests.fakes import make_step_ctx


def _ctx(tmp_path, steps_to_run={"save"}, force=set()):
    return make_step_ctx(tmp_path, steps_to_run=steps_to_run, force_steps=force)


@pytest.mark.unit
def test_save_step_runs_and_touches_sentinel(tmp_path):
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")
    captured = {}

    def fake_save(day_dir, today, digests):
        captured["args"] = (day_dir, today, digests)

    outcome = SaveStep(today="2026-06-21", save=fake_save).run(
        _ctx(tmp_path), [{"url": "http://a"}])

    assert outcome.status is StepStatus.RAN
    assert (tmp_path / "vault.done").exists()
    assert captured["args"] == (tmp_path, "2026-06-21", [{"url": "http://a"}])


@pytest.mark.unit
def test_save_step_guard_blocks_without_report_md(tmp_path):
    outcome = SaveStep(today="2026-06-21", save=lambda *a: None).run(
        _ctx(tmp_path), [{"url": "http://a"}])
    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "vault.done").exists()


@pytest.mark.unit
def test_save_step_skips_when_vault_unconfigured(tmp_path, monkeypatch):
    import agents.daily_brief.config as cfg

    monkeypatch.setattr(cfg, "VAULT_DAILY_BRIEF_DIR", None)
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")
    called = {"n": 0}

    def fake_save(day_dir, today, digests):
        called["n"] += 1

    outcome = SaveStep(today="2026-06-21", save=fake_save).run(
        _ctx(tmp_path), [{"url": "http://a"}])

    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "vault.done").exists()
    assert called["n"] == 0


@pytest.mark.unit
def test_save_step_skips_when_vault_path_missing(tmp_path, monkeypatch):
    import agents.daily_brief.config as cfg

    bogus = tmp_path / "nope" / "01 Projects" / "daily-brief"
    monkeypatch.setattr(cfg, "VAULT_DAILY_BRIEF_DIR", bogus)
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")

    outcome = SaveStep(today="2026-06-21", save=lambda *a: None).run(
        _ctx(tmp_path), [{"url": "http://a"}])

    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "vault.done").exists()
    assert not bogus.exists()


@pytest.mark.unit
def test_save_step_loads_when_sentinel_exists(tmp_path):
    (tmp_path / "vault.done").touch()
    called = {"n": 0}

    def fake_save(day_dir, today, digests):
        called["n"] += 1

    outcome = SaveStep(today="2026-06-21", save=fake_save).run(
        _ctx(tmp_path), [{"url": "http://a"}])
    assert outcome.status is StepStatus.LOADED
    assert called["n"] == 0


@pytest.mark.unit
def test_run_save_creates_vault_files(tmp_path, monkeypatch):
    import agents.daily_brief.config as cfg

    monkeypatch.setattr(cfg, "VAULT_DAILY_BRIEF_DIR", tmp_path / "vault" / "daily-brief")
    day_dir = tmp_path / "outputs" / "2026-04-12"
    day_dir.mkdir(parents=True)
    (day_dir / "report.md").write_text("# 報告", encoding="utf-8")

    digests = [
        {
            "title": "測試文章",
            "url": "https://example.com",
            "source": "HN",
            "interest": "***",
            "summary": "這是摘要。",
        }
    ]
    run_save(day_dir, "2026-04-12", digests)

    vault_report = cfg.VAULT_DAILY_BRIEF_DIR / "2026-04-12.md"
    vault_digest = cfg.VAULT_DAILY_BRIEF_DIR / "2026-04-12-digest.md"
    assert vault_report.read_text(encoding="utf-8") == "# 報告"
    content = vault_digest.read_text(encoding="utf-8")
    assert "created: 2026-04-12" in content
    assert "測試文章" in content
    assert "這是摘要。" in content


@pytest.mark.unit
def test_format_obsidian_digest_frontmatter():
    digests = [
        {"title": "A", "url": "https://a.com", "source": "HN", "summary": "摘要 A"}
    ]
    result = format_obsidian_digest(digests, "2026-04-12")
    assert result.startswith("---")
    assert "created: 2026-04-12" in result
    assert "tags: [daily-brief, digest]" in result
    assert "## A" in result
    assert "https://a.com" in result

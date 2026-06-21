"""NotifyStep — SentinelCodec(telegram.done); _notify False → raise → FAILED, no sentinel."""

from types import SimpleNamespace

import pytest

from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.notify import NotifyStep


class _FakeSupervisor:
    """Mimics supervisor: calls fn(); on exception returns success=False."""

    def run_step(self, name, fn, force=False):
        try:
            return SimpleNamespace(success=True, output=fn(reflect_context=""))
        except Exception:
            return SimpleNamespace(success=False, output=None)


def _ctx(tmp_path, steps_to_run={"notify"}, force=set()):
    return SimpleNamespace(steps_dir=tmp_path, day_dir=tmp_path,
                           steps_to_run=steps_to_run, force_steps=force,
                           supervisor=_FakeSupervisor())


@pytest.mark.unit
def test_notify_step_success_touches_sentinel(tmp_path):
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")
    captured = {}

    def fake_notify(digests, today, steps_dir=None, reflect_context=""):
        captured["digests"] = digests
        return True

    outcome = NotifyStep(fake_notify, today="2026-06-21").run(
        _ctx(tmp_path), [{"url": "http://a"}])

    assert outcome.status is StepStatus.RAN
    assert (tmp_path / "telegram.done").exists()
    assert captured["digests"] == [{"url": "http://a"}]


@pytest.mark.unit
def test_notify_step_false_result_fails_without_sentinel(tmp_path):
    (tmp_path / "report.md").write_text("# r", encoding="utf-8")

    def fake_notify(digests, today, steps_dir=None, reflect_context=""):
        return False

    outcome = NotifyStep(fake_notify, today="2026-06-21").run(
        _ctx(tmp_path), [{"url": "http://a"}])

    assert outcome.status is StepStatus.FAILED
    assert not (tmp_path / "telegram.done").exists()


@pytest.mark.unit
def test_notify_step_guard_blocks_without_report_md(tmp_path):
    outcome = NotifyStep(lambda *a, **k: True, today="2026-06-21").run(
        _ctx(tmp_path), [{"url": "http://a"}])
    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "telegram.done").exists()

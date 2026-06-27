"""NotifyStep — send-only, per-message idempotent.

Input is the composed {"overview","digest"} dict. The step sends via an injected
send callable (no LLM). Per-message sub-sentinels mean a retry only resends the
not-yet-delivered message; telegram.done is written only when BOTH delivered.
"""

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
    return SimpleNamespace(
        steps_dir=tmp_path,
        day_dir=tmp_path,
        steps_to_run=steps_to_run,
        force_steps=force,
        supervisor=_FakeSupervisor(),
    )


def _composed(overview="OV", digest="DG"):
    return {"overview": overview, "digest": digest}


@pytest.mark.unit
def test_notify_sends_both_and_touches_sentinel(tmp_path):
    sent = []

    def fake_send(text):
        sent.append(text)
        return True

    outcome = NotifyStep(fake_send, today="2026-06-27").run(_ctx(tmp_path), _composed())

    assert outcome.status is StepStatus.RAN
    assert sent == ["OV", "DG"]
    assert (tmp_path / "telegram.done").exists()
    assert (tmp_path / "telegram_overview.done").exists()
    assert (tmp_path / "telegram_digest.done").exists()


@pytest.mark.unit
def test_notify_does_not_call_llm(tmp_path):
    """Send-only: NotifyStep takes a send callable, never an LLM/producer."""
    sent = []
    NotifyStep(lambda t: sent.append(t) or True, today="2026-06-27").run(
        _ctx(tmp_path), _composed()
    )
    # Both messages were the verbatim composed texts (no generation happened).
    assert sent == ["OV", "DG"]


@pytest.mark.unit
def test_notify_second_message_failure_no_sentinel(tmp_path):
    def fake_send(text):
        return text == "OV"  # first ok, second fails

    outcome = NotifyStep(fake_send, today="2026-06-27").run(_ctx(tmp_path), _composed())

    assert outcome.status is StepStatus.FAILED
    assert not (tmp_path / "telegram.done").exists()
    assert (tmp_path / "telegram_overview.done").exists()  # first delivered
    assert not (tmp_path / "telegram_digest.done").exists()


@pytest.mark.unit
def test_notify_retry_only_resends_failed_message(tmp_path):
    """After first message delivered + second failed, a forced retry must
    re-send ONLY the second message, never the already-delivered first."""
    # First attempt: second send fails.
    NotifyStep(lambda t: t == "OV", today="2026-06-27").run(_ctx(tmp_path), _composed())
    assert (tmp_path / "telegram_overview.done").exists()
    assert not (tmp_path / "telegram_digest.done").exists()

    # Retry: both sends would succeed now, but overview is already delivered.
    sent = []

    def fake_send(text):
        sent.append(text)
        return True

    outcome = NotifyStep(fake_send, today="2026-06-27").run(
        _ctx(tmp_path, force={"notify"}), _composed()
    )

    assert sent == ["DG"]  # overview NOT resent
    assert outcome.status is StepStatus.RAN
    assert (tmp_path / "telegram.done").exists()


@pytest.mark.unit
def test_notify_guard_blocks_without_composed(tmp_path):
    outcome = NotifyStep(lambda t: True, today="2026-06-27").run(_ctx(tmp_path), {})
    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "telegram.done").exists()

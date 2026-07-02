"""ComposeTgStep — JsonCodec({"overview","digest"}); LOAD on re-run does NOT call LLM producer."""

from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.compose_tg import ComposeTgStep
from tests.fakes import make_step_ctx


def _ctx(tmp_path, steps_to_run={"compose_tg"}, force=set()):
    return make_step_ctx(tmp_path, steps_to_run=steps_to_run, force_steps=force)


@pytest.mark.unit
def test_compose_persists_two_messages(tmp_path):
    composed = {"overview": "OV", "digest": "DG"}

    def fake_compose(digests, today, reflect_context=""):
        return composed

    outcome = ComposeTgStep(fake_compose, today="2026-06-27").run(
        _ctx(tmp_path), [{"url": "http://a"}]
    )

    assert outcome.status is StepStatus.RAN
    assert outcome.value == composed
    assert JsonCodec().read(tmp_path / "compose_tg.json") == composed


@pytest.mark.unit
def test_compose_load_does_not_call_producer(tmp_path):
    JsonCodec().write(tmp_path / "compose_tg.json", {"overview": "X", "digest": "Y"})
    calls = {"n": 0}

    def fake_compose(digests, today, reflect_context=""):
        calls["n"] += 1
        return {"overview": "NEW", "digest": "NEW"}

    outcome = ComposeTgStep(fake_compose, today="2026-06-27").run(
        _ctx(tmp_path), [{"url": "http://a"}]
    )

    assert outcome.status is StepStatus.LOADED
    assert outcome.value == {"overview": "X", "digest": "Y"}
    assert calls["n"] == 0


@pytest.mark.unit
def test_compose_guard_blocks_without_digests(tmp_path):
    outcome = ComposeTgStep(lambda *a, **k: {}, today="2026-06-27").run(
        _ctx(tmp_path), []
    )
    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "compose_tg.json").exists()


@pytest.mark.unit
def test_compose_default_is_empty_dict(tmp_path):
    outcome = ComposeTgStep(lambda *a, **k: {}, today="2026-06-27").run(
        _ctx(tmp_path, steps_to_run=set()), [{"url": "http://a"}]
    )
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value == {}

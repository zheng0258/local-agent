"""SourceStep — a Step subclass: scores pre-fetched raw into {name}.json."""

from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.source import SourceStep
from tests.fakes import make_step_ctx


def _ctx(tmp_path, steps_to_run={"hn"}, force=set()):
    return make_step_ctx(tmp_path, steps_to_run=steps_to_run, force_steps=force)


@pytest.mark.unit
def test_source_step_scores_raw_and_stamps_fetched_at(tmp_path):
    captured = {}

    def fake_score(name, raw):
        captured["args"] = (name, raw)
        return {"articles": [{"url": "http://a", "interest": "***"}]}

    outcome = SourceStep("hn", fake_score).run(_ctx(tmp_path), [{"title": "t"}])

    assert outcome.status is StepStatus.RAN
    assert captured["args"] == ("hn", [{"title": "t"}])
    saved = JsonCodec().read(tmp_path / "hn.json")
    assert saved["articles"] == [{"url": "http://a", "interest": "***"}]
    assert "fetched_at" in saved
    assert outcome.value["articles"][0]["url"] == "http://a"


@pytest.mark.unit
def test_source_step_guard_skips_when_raw_is_none(tmp_path):
    outcome = SourceStep("hn", lambda n, r: {"articles": []}).run(_ctx(tmp_path), None)
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is None
    assert not (tmp_path / "hn.json").exists()


@pytest.mark.unit
def test_source_step_scores_empty_raw_list(tmp_path):
    outcome = SourceStep("hn", lambda n, r: {"articles": []}).run(_ctx(tmp_path), [])
    assert outcome.status is StepStatus.RAN
    assert (tmp_path / "hn.json").exists()


@pytest.mark.unit
def test_source_step_loads_existing_scored_artifact(tmp_path):
    JsonCodec().write(tmp_path / "hn.json", {"articles": [{"url": "http://cached"}], "fetched_at": "t"})
    ctx = _ctx(tmp_path, steps_to_run=set())
    outcome = SourceStep("hn", lambda n, r: {}).run(ctx, None)
    assert outcome.status is StepStatus.LOADED
    assert outcome.value["articles"][0]["url"] == "http://cached"


@pytest.mark.unit
def test_source_step_artifact_path_uses_name(tmp_path):
    step = SourceStep("reddit", lambda n, r: {})
    assert step.artifact_path(SimpleNamespace(steps_dir=tmp_path)) == tmp_path / "reddit.json"

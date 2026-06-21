"""_fetch_sources orchestrator — parallel raw / serial score / ≥2 gate, via SourceStep."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agents.daily_brief.agent import DailyBriefAgent, FETCH_STEPS


def _ctx(tmp_path, steps_to_run, force=set()):
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir(exist_ok=True)
    sup = SimpleNamespace()
    sup.run_step = lambda name, fn, force=False: SimpleNamespace(success=True, output=fn())
    return SimpleNamespace(
        today="2026-06-21", day_dir=tmp_path, steps_dir=steps_dir,
        steps_to_run=set(steps_to_run), force_steps=set(force),
        supervisor=sup, notify_fn=lambda m: True,
    )


@pytest.mark.unit
def test_fetch_orchestrator_scores_fresh_sources(tmp_path):
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())
    agent._fetch_raw_data = lambda name: [{"raw": name}]
    agent._score_raw_data = lambda name, raw: {"articles": [{"url": f"http://{name}"}]}

    ctx = _ctx(tmp_path, steps_to_run=set(FETCH_STEPS))
    result = agent._fetch_sources(ctx)

    assert set(result.keys()) == set(FETCH_STEPS)
    for name in FETCH_STEPS:
        assert result[name]["articles"][0]["url"] == f"http://{name}"
        assert (ctx.steps_dir / f"{name}.json").exists()


@pytest.mark.unit
def test_fetch_orchestrator_loads_cached_sources(tmp_path):
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())
    fetch_calls = []
    agent._fetch_raw_data = lambda name: fetch_calls.append(name) or [{"raw": name}]
    agent._score_raw_data = lambda name, raw: {"articles": []}

    ctx = _ctx(tmp_path, steps_to_run=set(FETCH_STEPS))
    for name in FETCH_STEPS:
        (ctx.steps_dir / f"{name}.json").write_text(
            json.dumps({"articles": [{"url": f"http://cached-{name}"}], "fetched_at": "t"}),
            encoding="utf-8")

    result = agent._fetch_sources(ctx)
    assert fetch_calls == []
    assert result["hn"]["articles"][0]["url"] == "http://cached-hn"


@pytest.mark.unit
def test_fetch_orchestrator_aborts_when_fewer_than_two_succeed(tmp_path):
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())

    def only_hn(name):
        if name == "hn":
            return [{"raw": "hn"}]
        raise RuntimeError("fetch failed")

    agent._fetch_raw_data = only_hn
    agent._score_raw_data = lambda name, raw: {"articles": [{"url": "http://hn"}]}

    alerts = []
    ctx = _ctx(tmp_path, steps_to_run=set(FETCH_STEPS))
    ctx.notify_fn = lambda m: alerts.append(m) or True

    result = agent._fetch_sources(ctx)
    assert result is None
    assert alerts and "Fetch" in alerts[0]


@pytest.mark.unit
def test_fetch_orchestrator_one_raw_failure_does_not_block_others(tmp_path):
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())

    def fail_reddit(name):
        if name == "reddit":
            raise RuntimeError("boom")
        return [{"raw": name}]

    agent._fetch_raw_data = fail_reddit
    agent._score_raw_data = lambda name, raw: {"articles": [{"url": f"http://{name}"}]}

    ctx = _ctx(tmp_path, steps_to_run=set(FETCH_STEPS))
    result = agent._fetch_sources(ctx)
    assert "reddit" not in result
    assert set(result.keys()) == set(FETCH_STEPS) - {"reddit"}

"""_fetch_sources orchestrator — parallel raw / serial score / ≥2 gate, via SourceStep.

scoring 現住 SourceStep（讀 ctx.llm）；orchestrator 測試注入 FakeLLM 回傳 canned 評分，
斷言編排性質（哪些來源成功 / 快取 / <2 中止 / 單一失敗不 block），非逐來源 URL。
"""

import json
from unittest.mock import MagicMock

import pytest

from agents.daily_brief.agent import DailyBriefAgent, FETCH_STEPS
from tests.fakes import FakeLLM, make_step_ctx

_SCORED = json.dumps({"articles": [{"url": "http://scored", "score": 500, "interest": "***"}]})


def _ctx(tmp_path, steps_to_run, force=set(), notify_fn=lambda m: True, llm=None):
    return make_step_ctx(
        tmp_path,
        steps_to_run=steps_to_run,
        force_steps=force,
        notify_fn=notify_fn,
        llm=llm if llm is not None else FakeLLM(default=_SCORED),
    )


@pytest.mark.unit
def test_fetch_orchestrator_scores_fresh_sources(tmp_path):
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())
    agent._fetch_raw_data = lambda name: [{"raw": name}]

    ctx = _ctx(tmp_path, steps_to_run=set(FETCH_STEPS))
    result = agent._fetch_sources(ctx)

    assert set(result.keys()) == set(FETCH_STEPS)
    for name in FETCH_STEPS:
        assert result[name]["articles"]  # 每來源都被評分
        assert (ctx.steps_dir / f"{name}.json").exists()


@pytest.mark.unit
def test_fetch_orchestrator_loads_cached_sources(tmp_path):
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())
    fetch_calls = []
    agent._fetch_raw_data = lambda name: fetch_calls.append(name) or [{"raw": name}]

    ctx = _ctx(tmp_path, steps_to_run=set(FETCH_STEPS))
    for name in FETCH_STEPS:
        (ctx.steps_dir / f"{name}.json").write_text(
            json.dumps({"articles": [{"url": f"http://cached-{name}"}], "fetched_at": "t"}),
            encoding="utf-8")

    result = agent._fetch_sources(ctx)
    assert fetch_calls == []  # 全部 LOAD，無網路 I/O
    assert result["hn"]["articles"][0]["url"] == "http://cached-hn"


@pytest.mark.unit
def test_fetch_orchestrator_aborts_when_fewer_than_two_succeed(tmp_path):
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())

    def only_hn(name):
        if name == "hn":
            return [{"raw": "hn"}]
        raise RuntimeError("fetch failed")

    agent._fetch_raw_data = only_hn

    alerts = []
    ctx = _ctx(tmp_path, steps_to_run=set(FETCH_STEPS),
               notify_fn=lambda m: alerts.append(m) or True)

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

    ctx = _ctx(tmp_path, steps_to_run=set(FETCH_STEPS))
    result = agent._fetch_sources(ctx)
    assert "reddit" not in result
    assert set(result.keys()) == set(FETCH_STEPS) - {"reddit"}

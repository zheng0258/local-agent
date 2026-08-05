"""SourceStep — producer 邏輯住 _produce/_score（讀 ctx.llm）：評分 raw → {name}.json。

RAN 路徑注入 FakeLLM 回傳 canned 評分 JSON；guard 對 None（抓取失敗）略過。
"""

import json
from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.source import SourceStep
from tests.fakes import FakeLLM, make_step_ctx


def _ctx(tmp_path, steps_to_run={"hn"}, force=set(), llm=None):
    return make_step_ctx(
        tmp_path, steps_to_run=steps_to_run, force_steps=force, llm=llm
    )


@pytest.mark.unit
def test_source_step_scores_raw_and_stamps_fetched_at(tmp_path):
    llm = FakeLLM(
        default=json.dumps({"articles": [{"url": "http://a", "score": 300, "interest": "***"}]})
    )
    outcome = SourceStep("hn").run(
        _ctx(tmp_path, llm=llm), [{"title": "t", "url": "http://a"}]
    )
    assert outcome.status is StepStatus.RAN
    saved = JsonCodec().read(tmp_path / "hn.json")
    assert saved["articles"][0]["url"] == "http://a"
    assert "fetched_at" in saved
    assert outcome.value["articles"][0]["url"] == "http://a"


@pytest.mark.unit
def test_source_step_guard_skips_when_raw_is_none(tmp_path):
    outcome = SourceStep("hn").run(_ctx(tmp_path), None)
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is None
    assert not (tmp_path / "hn.json").exists()


@pytest.mark.unit
def test_source_step_scores_empty_raw_list(tmp_path):
    llm = FakeLLM(default=json.dumps({"articles": []}))
    outcome = SourceStep("hn").run(_ctx(tmp_path, llm=llm), [])
    assert outcome.status is StepStatus.RAN
    assert (tmp_path / "hn.json").exists()


@pytest.mark.unit
def test_source_step_loads_existing_scored_artifact(tmp_path):
    JsonCodec().write(tmp_path / "hn.json", {"articles": [{"url": "http://cached"}], "fetched_at": "t"})
    ctx = _ctx(tmp_path, steps_to_run=set())
    outcome = SourceStep("hn").run(ctx, None)
    assert outcome.status is StepStatus.LOADED
    assert outcome.value["articles"][0]["url"] == "http://cached"


@pytest.mark.unit
def test_source_step_artifact_path_uses_name(tmp_path):
    assert SourceStep("reddit").artifact_path(
        SimpleNamespace(steps_dir=tmp_path)
    ) == tmp_path / "reddit.json"


@pytest.mark.unit
def test_source_step_reddit_batches_large_input(tmp_path):
    """154 篇 Reddit 應分 7 批呼叫 LLM，每批 ≤ 25 篇。"""
    call_sizes: list[int] = []

    class BatchLLM:
        def complete(self, prompt: str, system: str | None = None) -> str:
            import re

            m = re.search(r"## 文章清單[^\n]*\n\n(\[.*?\])\n\n## 任務", prompt, re.DOTALL)
            articles = json.loads(m.group(1)) if m else []
            call_sizes.append(len(articles))
            scored = [
                {
                    "title": a["title"],
                    "url": a["url"],
                    "score": a["score"],
                    "interest": "**",
                    "category": a["category"],
                    "subreddit": a["subreddit"],
                }
                for a in articles
            ]
            return json.dumps({"articles": scored})

    raw = [
        {
            "subreddit": "r/programming",
            "title": f"Article {i}",
            "score": 0,
            "num_comments": 0,
            "url": f"https://reddit.com/{i}",
            "orig_url": f"https://example.com/{i}",
            "category": "核心技術類",
        }
        for i in range(154)
    ]
    ctx = SimpleNamespace(llm=BatchLLM())
    result = SourceStep("reddit")._score(ctx, "reddit", raw)

    assert len(call_sizes) == 7
    assert max(call_sizes) <= 25
    assert sum(call_sizes) == 154
    assert len(result["articles"]) == 154

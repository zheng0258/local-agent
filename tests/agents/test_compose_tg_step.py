"""ComposeTgStep — producer 邏輯住 _produce（讀 ctx.llm）；JsonCodec 落盤兩封訊息。

RAN 路徑注入 FakeLLM（兩次生成）；LOAD 不呼叫 LLM。含跨來源均衡挑選與 JSON 解包。
"""

import json

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.compose_tg import (
    TG_DIGEST_MAX_ITEMS,
    ComposeTgStep,
    extract_tg_text,
    pick_top_balanced,
)
from tests.fakes import FakeLLM, make_step_ctx


def _ctx(tmp_path, steps_to_run={"compose_tg"}, force=set(), llm=None):
    return make_step_ctx(
        tmp_path, steps_to_run=steps_to_run, force_steps=force, llm=llm
    )


@pytest.mark.unit
def test_compose_persists_two_messages(tmp_path):
    llm = FakeLLM(
        responses=[
            json.dumps({"tg_overview": "overview text"}),
            json.dumps({"tg_digest": "digest text"}),
        ]
    )
    outcome = ComposeTgStep().run(
        _ctx(tmp_path, llm=llm),
        [{"title": "T", "url": "https://u.com", "_source": "hn"}],
    )
    assert outcome.status is StepStatus.RAN
    assert outcome.value == {"overview": "overview text", "digest": "digest text"}
    assert JsonCodec().read(tmp_path / "compose_tg.json") == outcome.value


@pytest.mark.unit
def test_compose_load_does_not_call_producer(tmp_path):
    JsonCodec().write(tmp_path / "compose_tg.json", {"overview": "X", "digest": "Y"})
    llm = FakeLLM(default="SHOULD NOT BE CALLED")
    outcome = ComposeTgStep().run(_ctx(tmp_path, llm=llm), [{"url": "http://a"}])
    assert outcome.status is StepStatus.LOADED
    assert outcome.value == {"overview": "X", "digest": "Y"}
    assert llm.prompts == []


@pytest.mark.unit
def test_compose_caps_digest_items(tmp_path):
    # 20 篇單一來源 → msg2 應 ≤ TG_DIGEST_MAX_ITEMS 則
    llm = FakeLLM(default="text")
    digests = [
        {"title": f"A{i}", "url": f"https://example.com/{i}", "_source": "hn"}
        for i in range(20)
    ]
    ComposeTgStep().run(_ctx(tmp_path, llm=llm), digests)
    msg2_prompt = next(p for p in llm.prompts if "深度摘要（" in p)
    assert f"example.com/{TG_DIGEST_MAX_ITEMS - 1}" in msg2_prompt
    assert f"example.com/{TG_DIGEST_MAX_ITEMS}" not in msg2_prompt


@pytest.mark.unit
def test_compose_guard_blocks_without_digests(tmp_path):
    outcome = ComposeTgStep().run(_ctx(tmp_path), [])
    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "compose_tg.json").exists()


@pytest.mark.unit
def test_compose_default_is_empty_dict(tmp_path):
    outcome = ComposeTgStep().run(
        _ctx(tmp_path, steps_to_run=set()), [{"url": "http://a"}]
    )
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value == {}


@pytest.mark.unit
def test_pick_top_balanced_round_robins_across_sources():
    digests = [
        {"title": f"hn{i}", "url": f"u/hn/{i}", "_source": "hn"} for i in range(10)
    ] + [{"title": "rd0", "url": "u/rd/0", "_source": "reddit"}]
    picked = pick_top_balanced(digests, n=6)
    sources = [d["_source"] for d in picked]
    assert len(picked) == 6
    assert "reddit" in sources  # 少數來源仍被選入
    assert sources.count("reddit") == 1


@pytest.mark.unit
def test_extract_tg_text_unwraps_json():
    assert extract_tg_text(json.dumps({"tg_overview": "hello"})) == "hello"
    assert extract_tg_text("plain text") == "plain text"

"""DigestStep — producer 邏輯住 _produce（讀 ctx.llm）；persist digest_data、pass digests。

RAN 路徑注入 FakeLLM 回傳逐來源 digest JSON；LOAD/SKIP 不跑 producer。
"""

import json

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.digest import DigestStep
from tests.fakes import FakeLLM, make_step_ctx


def _ctx(tmp_path, steps_to_run={"digest"}, force=set(), llm=None):
    return make_step_ctx(
        tmp_path, steps_to_run=steps_to_run, force_steps=force, llm=llm
    )


@pytest.mark.unit
def test_digest_step_produces_list_and_persists_digest_data(tmp_path):
    # LLM 只回 {id, summary}；title/url 依 id 從 compress 重建
    llm = FakeLLM(default=json.dumps({"digests": [{"id": 0, "summary": "摘要"}]}))
    compress_data = {
        "hn": {
            "themes": ["AI"],
            "articles": [
                {"title": "t", "url": "https://example.com", "one_liner": "x", "interest": "***"}
            ],
        }
    }

    outcome = DigestStep().run(_ctx(tmp_path, llm=llm), compress_data)

    assert outcome.status is StepStatus.RAN
    assert isinstance(outcome.value, list) and len(outcome.value) == 1
    assert outcome.value[0]["title"] == "t"  # 來自 compress，非 LLM
    assert outcome.value[0]["url"] == "https://example.com"
    assert outcome.value[0]["summary"] == "摘要"  # summary 才採信 LLM
    assert outcome.value[0]["_source"] == "hn"  # 逐來源標記
    persisted = JsonCodec().read(tmp_path / "digest.json")
    assert "generated_at" in persisted
    assert persisted["digests"] == outcome.value


@pytest.mark.unit
def test_digest_step_url_always_from_compress_even_when_llm_omits(tmp_path):
    # 回歸：LLM 完全不回 id / 空 digests 時，url/title 仍依 compress 重建、禁止丟棄
    llm = FakeLLM(default=json.dumps({"digests": []}))
    compress_data = {
        "hn": {
            "articles": [
                {"title": "t", "url": "https://restored", "one_liner": "ol", "interest": "***"}
            ]
        }
    }
    outcome = DigestStep().run(_ctx(tmp_path, llm=llm), compress_data)
    assert len(outcome.value) == 1
    assert outcome.value[0]["url"] == "https://restored"
    assert outcome.value[0]["summary"] == "ol"  # LLM 漏 id → one_liner 退回


@pytest.mark.unit
def test_digest_step_load_returns_digests_field(tmp_path):
    digests = [{"title": "X", "url": "http://x"}]
    JsonCodec().write(tmp_path / "digest.json", {"generated_at": "t", "digests": digests})
    outcome = DigestStep().run(_ctx(tmp_path), {"hn": {}})
    assert outcome.status is StepStatus.LOADED
    assert outcome.value == digests


@pytest.mark.unit
def test_digest_step_default_is_empty_list(tmp_path):
    outcome = DigestStep().run(_ctx(tmp_path, steps_to_run=set()), {"hn": {}})
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value == []

"""CompressStep — producer 邏輯住 _produce（讀 ctx.llm）；壓縮後就地檢查來源健康。

RAN 路徑注入 FakeLLM 回傳 compress JSON；prefilter *** 與 URL 補回一併驗證。
"""

import json
from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.compress import CompressStep, check_source_health
from tests.fakes import FakeLLM, make_step_ctx


def _ctx(tmp_path, steps_to_run={"compress"}, llm=None):
    return make_step_ctx(tmp_path, steps_to_run=steps_to_run, llm=llm)


@pytest.mark.unit
def test_compress_step_runs_producer_and_persists(tmp_path):
    llm = FakeLLM(default=json.dumps({"themes": ["t"], "articles": []}))
    outcome = CompressStep().run(
        _ctx(tmp_path, llm=llm),
        {"hn": {"articles": [{"title": "a", "url": "u", "interest": "***"}]}},
    )
    assert outcome.status is StepStatus.RAN
    assert outcome.value["hn"] == {"themes": ["t"], "articles": []}
    assert "_meta" in outcome.value and "compressed_at" in outcome.value["_meta"]
    assert JsonCodec().read(tmp_path / "compress.json") == outcome.value


@pytest.mark.unit
def test_compress_step_prefilters_to_starred_only(tmp_path):
    llm = FakeLLM(default=json.dumps({"themes": ["AI"], "articles": []}))
    source_data = {
        "hn": {
            "articles": [
                {"title": "A", "url": "https://hn.com/1", "interest": "***"},
                {"title": "B", "url": "https://hn.com/2", "interest": "**"},
                {"title": "C", "url": "https://hn.com/3", "interest": "*"},
            ]
        }
    }
    CompressStep().run(_ctx(tmp_path, llm=llm), source_data)
    hn_prompt = next(p for p in llm.prompts if "hn.com/1" in p)
    assert "hn.com/1" in hn_prompt  # *** 保留
    assert "hn.com/2" not in hn_prompt  # ** 過濾
    assert "hn.com/3" not in hn_prompt  # * 過濾


@pytest.mark.unit
def test_compress_step_skips_llm_when_no_starred(tmp_path):
    llm = FakeLLM(default="SHOULD NOT BE CALLED")
    outcome = CompressStep().run(
        _ctx(tmp_path, llm=llm), {"hn": {"articles": [{"interest": "*"}]}}
    )
    assert llm.prompts == []  # 無 *** → 不呼叫 LLM
    assert outcome.value["hn"] == {"themes": [], "articles": []}


@pytest.mark.unit
def test_compress_step_artifact_path(tmp_path):
    assert CompressStep().artifact_path(
        SimpleNamespace(steps_dir=tmp_path)
    ) == tmp_path / "compress.json"


@pytest.mark.unit
def test_compress_step_default_is_empty_dict(tmp_path):
    outcome = CompressStep().run(_ctx(tmp_path, steps_to_run=set()), {"hn": {}})
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value == {}


@pytest.mark.unit
def test_check_source_health_flags_zero_article_sources():
    compress_data = {
        "hatena": {"themes": ["AI"], "articles": [{"interest": "***", "url": "u1"}]},
        "hn": {"themes": [], "articles": []},
        "reddit": {"themes": ["資安"], "articles": [{"interest": "***", "url": "u2"}]},
        "security": {"themes": [], "articles": []},
    }
    warnings = check_source_health(compress_data)
    assert "hn" in warnings
    assert "security" in warnings
    assert "hatena" not in warnings
    assert "reddit" not in warnings

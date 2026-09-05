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
    llm = FakeLLM(
        default=json.dumps(
            {"themes": ["t"], "articles": [{"id": 0, "one_liner": "摘要"}]}
        )
    )
    outcome = CompressStep().run(
        _ctx(tmp_path, llm=llm),
        {"hn": {"articles": [{"title": "a", "url": "u", "interest": "***"}]}},
    )
    assert outcome.status is StepStatus.RAN
    assert outcome.value["hn"] == {
        "themes": ["t"],
        "articles": [{"title": "a", "url": "u", "interest": "***", "one_liner": "摘要"}],
    }
    assert "_meta" in outcome.value and "compressed_at" in outcome.value["_meta"]
    assert JsonCodec().read(tmp_path / "compress.json") == outcome.value


@pytest.mark.unit
def test_compress_step_restores_url_when_llm_drops_title_and_articles(tmp_path):
    """回歸（09-05 TG 無連結）：LLM 丟 title/url 又漏整篇時，仍依 id 補回全部 URL。"""
    # 3 篇 starred，LLM 只回 id 0 與 2（漏 id 1），且完全不回吐 url/title
    llm = FakeLLM(
        default=json.dumps(
            {
                "themes": ["AI"],
                "articles": [
                    {"id": 0, "one_liner": "第一篇"},
                    {"id": 2, "one_liner": "第三篇"},
                ],
            }
        )
    )
    source_data = {
        "hn": {
            "articles": [
                {"title": "A", "url": "https://hn.com/1", "interest": "***"},
                {"title": "B", "url": "https://hn.com/2", "interest": "***"},
                {"title": "C", "url": "https://hn.com/3", "interest": "***"},
            ]
        }
    }
    articles = CompressStep().run(_ctx(tmp_path, llm=llm), source_data).value["hn"][
        "articles"
    ]
    # 三篇都在（保序、禁止丟棄），URL 全部保留
    assert [a["url"] for a in articles] == [
        "https://hn.com/1",
        "https://hn.com/2",
        "https://hn.com/3",
    ]
    # LLM 有給的採 one_liner；漏掉的 id 1 退回標題
    assert [a["one_liner"] for a in articles] == ["第一篇", "B", "第三篇"]


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

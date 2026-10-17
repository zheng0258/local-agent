"""同一次 run 內的上游失效 —— 上游 step 本次 RUN，下游不得 LOAD 舊 artifact。

回歸 2026-10-17：早上 rss 失敗，dedup 以四來源落盤 dedup.json（kept_urls 無 rss）。
下午重跑 rss 成功（RUN），dedup 卻判 LOAD，`_load` 以舊 kept_urls 重濾上游
→ rss 全部文章被濾掉。Fix C（run 開始時的 mtime 比對）看不到 run 中途才落盤的 rss.json。
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.compress import CompressStep
from agents.daily_brief.steps.dedup import DedupStep
from agents.daily_brief.steps.source import SourceStep
from tests.fakes import FakeLLM, FakeSupervisor, make_step_ctx

_MORNING = {
    "hatena": {"articles": [{"url": "http://hatena/1", "title": "h"}]},
    "hn": {"articles": [{"url": "http://hn/1", "title": "n"}]},
}
_RSS_RAW = [{"title": "r", "url": "http://rss/1"}]


def _passthrough_dedup(source_data, **_kwargs):
    """模擬 dedup 全部保留（同日記錄不參與比對，故重跑等冪）。"""
    urls = [a["url"] for src in source_data.values() for a in src["articles"]]
    result = SimpleNamespace(
        total=len(urls), kept=len(urls), filtered_url=0, filtered_semantic=0,
        kept_urls=urls, filtered_items=[],
    )
    return source_data, result


def _patch_dedup():
    return (
        patch("agents.daily_brief.steps.dedup.dedup_source_data",
              side_effect=_passthrough_dedup),
        patch("agents.daily_brief.steps.dedup.get_collection"),
        patch("agents.daily_brief.steps.dedup.cleanup_old_records"),
        patch("agents.daily_brief.steps.dedup.Qwen3Embedder"),
    )


@pytest.mark.unit
def test_source_ran_this_run_forces_dedup_to_rerun_not_load(tmp_path):
    # 早上：dedup.json 已落盤，kept_urls 不含任何 rss URL；rss.json 不存在（失敗）
    for name, data in _MORNING.items():
        JsonCodec().write(tmp_path / f"{name}.json", data)
    JsonCodec().write(
        tmp_path / "dedup.json",
        {"kept_urls": ["http://hatena/1", "http://hn/1"]},
    )
    llm = FakeLLM(default=json.dumps(
        {"articles": [{"url": "http://rss/1", "score": 10, "interest": "***"}]}
    ))
    ctx = make_step_ctx(tmp_path, llm=llm)

    # 下午：rss 本次成功 RUN
    rss = SourceStep("rss").run(ctx, _RSS_RAW)
    assert rss.status is StepStatus.RAN
    source_data = {**_MORNING, "rss": rss.value}

    p1, p2, p3, p4 = _patch_dedup()
    with p1, p2, p3, p4:
        outcome = DedupStep().run(ctx, source_data)

    assert outcome.status is StepStatus.RAN  # 不得 LOAD 舊 kept_urls
    assert [a["url"] for a in outcome.value["rss"]["articles"]] == ["http://rss/1"]
    assert "http://rss/1" in JsonCodec().read(tmp_path / "dedup.json")["kept_urls"]


@pytest.mark.unit
def test_upstream_loaded_keeps_downstream_load(tmp_path):
    # 對照組：上游全部 LOAD（無人 RUN）→ dedup 照舊 LOAD，不白跑
    JsonCodec().write(tmp_path / "rss.json", {"articles": []})
    JsonCodec().write(tmp_path / "dedup.json", {"kept_urls": []})
    ctx = make_step_ctx(tmp_path)

    assert SourceStep("rss").run(ctx, None).status is StepStatus.LOADED
    assert DedupStep().run(ctx, {"rss": {"articles": []}}).status is StepStatus.LOADED
    assert ctx.ran_steps == set()


@pytest.mark.unit
def test_ran_step_is_recorded_and_propagates_transitively(tmp_path):
    # dedup 因上游而 RUN → 它自己也記入 ran_steps → compress 跟著失效
    JsonCodec().write(tmp_path / "dedup.json", {"kept_urls": []})
    JsonCodec().write(tmp_path / "compress.json", {"stale": True})
    sup = FakeSupervisor()
    ctx = make_step_ctx(tmp_path, supervisor=sup)
    ctx.ran_steps.add("rss")

    p1, p2, p3, p4 = _patch_dedup()
    with p1, p2, p3, p4:
        DedupStep().run(ctx, {"rss": {"articles": [{"url": "http://rss/1", "title": "r"}]}})
    CompressStep().run(ctx, {"rss": {"articles": []}})

    assert {"dedup", "compress"} <= ctx.ran_steps
    assert sup.calls == ["dedup", "compress"]
    # 因上游失效而重跑等同 force：supervisor 重置該步的 alert 去重
    assert sup.forced["dedup"] is True


@pytest.mark.unit
def test_failed_step_does_not_invalidate_downstream(tmp_path):
    # 上游 FAILED（未落盤新 artifact）→ 下游沿用既有 artifact
    JsonCodec().write(tmp_path / "dedup.json", {"kept_urls": []})
    ctx = make_step_ctx(tmp_path, supervisor=FakeSupervisor(fail=frozenset({"rss"})))

    assert SourceStep("rss").run(ctx, _RSS_RAW).status is StepStatus.FAILED
    assert DedupStep().run(ctx, {}).status is StepStatus.LOADED

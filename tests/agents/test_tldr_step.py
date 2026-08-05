"""TldrStep — producer 邏輯住 _produce（讀 ctx.llm）；persist 純文字英文 TL;DR 為 JSON。

RAN 路徑注入 FakeLLM 回傳 canned completion；LOAD/SKIP 不跑 producer。
"""

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.tldr import TldrStep
from tests.fakes import FakeLLM, make_step_ctx


def _ctx(tmp_path, steps_to_run={"tldr"}, force=set(), llm=None):
    return make_step_ctx(
        tmp_path, steps_to_run=steps_to_run, force_steps=force, llm=llm
    )


@pytest.mark.unit
def test_tldr_step_persists_and_passes_text(tmp_path):
    digests = [{"title": "A", "url": "http://a", "summary": "s"}]
    llm = FakeLLM(default="  Today AI tooling moved fast.  ")

    outcome = TldrStep().run(_ctx(tmp_path, llm=llm), digests)

    assert outcome.status is StepStatus.RAN
    assert outcome.value == "Today AI tooling moved fast."  # producer 有 strip
    assert JsonCodec().read(tmp_path / "tldr.json") == {
        "tldr": "Today AI tooling moved fast."
    }


@pytest.mark.unit
def test_tldr_step_load_returns_tldr_field(tmp_path):
    JsonCodec().write(tmp_path / "tldr.json", {"tldr": "Cached TL;DR."})
    outcome = TldrStep().run(_ctx(tmp_path), [{"title": "X"}])
    assert outcome.status is StepStatus.LOADED
    assert outcome.value == "Cached TL;DR."


@pytest.mark.unit
def test_tldr_step_guard_blocks_without_digests(tmp_path):
    outcome = TldrStep().run(_ctx(tmp_path), [])
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is None
    assert not (tmp_path / "tldr.json").exists()


@pytest.mark.unit
def test_tldr_step_default_is_none_when_not_in_steps(tmp_path):
    outcome = TldrStep().run(_ctx(tmp_path, steps_to_run=set()), [{"title": "X"}])
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is None

"""ReportStep — producer 邏輯住 _produce（讀 ctx.llm/ctx.today）；TextCodec、value=None。

RAN 路徑注入 FakeLLM 回傳純 markdown；LLM 直接輸出（無 JSON 包裝）、去 URL 重複。
"""

from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import TextCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.report import ReportStep
from tests.fakes import FakeLLM, make_step_ctx


def _ctx(tmp_path, steps_to_run={"report"}, force=set(), llm=None, today="2026-06-21"):
    return make_step_ctx(
        tmp_path, steps_to_run=steps_to_run, force_steps=force, llm=llm, today=today
    )


@pytest.mark.unit
def test_report_step_writes_markdown_to_report_md(tmp_path):
    llm = FakeLLM(default="# Trend Report\n\nbody")
    outcome = ReportStep().run(
        _ctx(tmp_path, llm=llm), ({"hn": {}}, [{"url": "http://a"}])
    )
    assert outcome.status is StepStatus.RAN
    assert outcome.value is None
    assert TextCodec().read(tmp_path / "report.md") == "# Trend Report\n\nbody"


@pytest.mark.unit
def test_report_step_strips_markdown_fence(tmp_path):
    llm = FakeLLM(default="```markdown\n# Report\n```")
    ReportStep().run(_ctx(tmp_path, llm=llm), ({"hn": {}}, [{"url": "http://a"}]))
    assert TextCodec().read(tmp_path / "report.md") == "# Report"


@pytest.mark.unit
def test_report_step_deduplicates_digests_by_url(tmp_path):
    llm = FakeLLM(default="# Report")
    digests = [
        {"title": "A", "url": "https://example.com/1"},
        {"title": "B", "url": "https://example.com/1"},  # dup url
        {"title": "C", "url": "https://example.com/2"},
    ]
    ReportStep().run(_ctx(tmp_path, llm=llm), ({"hn": {}}, digests))
    prompt = llm.prompts[0]
    assert prompt.count("example.com/1") == 1  # 重複 URL 只入 prompt 一次


@pytest.mark.unit
def test_report_step_guard_blocks_when_no_digests(tmp_path):
    outcome = ReportStep().run(_ctx(tmp_path), ({"hn": {}}, []))
    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "report.md").exists()


@pytest.mark.unit
def test_report_step_artifact_path_is_day_dir(tmp_path):
    assert ReportStep().artifact_path(
        SimpleNamespace(day_dir=tmp_path)
    ) == tmp_path / "report.md"

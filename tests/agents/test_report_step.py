"""ReportStep — TextCodec, tuple input (compress, digests), value=None."""

from types import SimpleNamespace

import pytest

from agents.daily_brief.codecs import TextCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.report import ReportStep


class _FakeSupervisor:
    def run_step(self, name, fn, force=False):
        return SimpleNamespace(success=True, output=fn(reflect_context=""))


def _ctx(tmp_path, steps_to_run={"report"}, force=set()):
    return SimpleNamespace(steps_dir=tmp_path, day_dir=tmp_path,
                           steps_to_run=steps_to_run, force_steps=force,
                           supervisor=_FakeSupervisor())


@pytest.mark.unit
def test_report_step_writes_markdown_to_report_md(tmp_path):
    captured = {}

    def fake_run_report(compress_data, digests, today, reflect_context=""):
        captured["args"] = (compress_data, digests, today)
        return "# Trend Report\n\nbody"

    outcome = ReportStep(fake_run_report, today="2026-06-21").run(
        _ctx(tmp_path), ({"hn": {}}, [{"url": "http://a"}]))

    assert outcome.status is StepStatus.RAN
    assert outcome.value is None
    assert TextCodec().read(tmp_path / "report.md") == "# Trend Report\n\nbody"
    assert captured["args"] == ({"hn": {}}, [{"url": "http://a"}], "2026-06-21")


@pytest.mark.unit
def test_report_step_guard_blocks_when_no_digests(tmp_path):
    outcome = ReportStep(lambda *a, **k: "x", today="2026-06-21").run(
        _ctx(tmp_path), ({"hn": {}}, []))
    assert outcome.status is StepStatus.SKIPPED
    assert not (tmp_path / "report.md").exists()


@pytest.mark.unit
def test_report_step_artifact_path_is_day_dir(tmp_path):
    step = ReportStep(lambda *a, **k: "x", today="2026-06-21")
    assert step.artifact_path(SimpleNamespace(day_dir=tmp_path)) == tmp_path / "report.md"

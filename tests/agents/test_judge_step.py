"""JudgeStep — scoring only; value = judge_result dict; raises when server down."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agents.daily_brief.codecs import JsonCodec
from agents.daily_brief.step import StepStatus
from agents.daily_brief.steps.judge import JudgeStep


class _Supervisor:
    def run_step(self, name, fn, force=False):
        try:
            return SimpleNamespace(success=True, output=fn(reflect_context=""))
        except Exception:
            return SimpleNamespace(success=False, output=None)


def _ctx(tmp_path, steps_to_run={"judge"}, force=set()):
    return SimpleNamespace(steps_dir=tmp_path, day_dir=tmp_path, today="2026-06-21",
                           steps_to_run=steps_to_run, force_steps=force,
                           supervisor=_Supervisor())


@pytest.mark.unit
def test_judge_step_runs_and_persists(tmp_path):
    judge_result = {"scores": {"completeness": {"score": 4}}, "overall": 4.0}

    def fake_run_judge(compress, digests, date=None):
        return judge_result

    with patch("agents.daily_brief.steps.judge.check_local_llm", return_value=True):
        outcome = JudgeStep(fake_run_judge).run(_ctx(tmp_path), ({"hn": {}}, [{"url": "http://a"}]))
    assert outcome.status is StepStatus.RAN
    assert outcome.value == judge_result
    assert JsonCodec().read(tmp_path / "judge.json") == judge_result


@pytest.mark.unit
def test_judge_step_fails_when_server_down(tmp_path):
    # fail-fast 探測改由 JudgeStep._produce 直接呼叫 check_local_llm（不再穿 supervisor seam）
    with patch("agents.daily_brief.steps.judge.check_local_llm", return_value=False):
        outcome = JudgeStep(lambda *a, **k: {}).run(
            _ctx(tmp_path), ({"hn": {}}, [{"url": "http://a"}]))
    assert outcome.status is StepStatus.FAILED
    assert outcome.value is None
    assert not (tmp_path / "judge.json").exists()


@pytest.mark.unit
def test_judge_step_guard_blocks_without_digests(tmp_path):
    outcome = JudgeStep(lambda *a, **k: {}).run(_ctx(tmp_path), ({"hn": {}}, []))
    assert outcome.status is StepStatus.SKIPPED


@pytest.mark.unit
def test_judge_step_default_is_none(tmp_path):
    outcome = JudgeStep(lambda *a, **k: {}).run(
        _ctx(tmp_path, steps_to_run=set()), ({"hn": {}}, [{"url": "http://a"}]))
    assert outcome.status is StepStatus.SKIPPED
    assert outcome.value is None

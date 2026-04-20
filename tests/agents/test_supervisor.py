import json
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch
import pytest


def _make_supervisor(tmp_path, llm_resp="", judge_resp=""):
    from agents.daily_brief.supervisor import SupervisorAgent

    llm = MagicMock()
    llm.complete.return_value = llm_resp
    judge_llm = MagicMock()
    judge_llm.complete.return_value = judge_resp
    return SupervisorAgent(
        llm=llm,
        judge_llm=judge_llm,
        steps_dir=tmp_path,
        today="2026-04-20",
    ), llm, judge_llm


@pytest.mark.unit
def test_plain_step_success_on_first_attempt(tmp_path):
    supervisor, llm, _ = _make_supervisor(tmp_path)
    fn = MagicMock(return_value={"data": "ok"})

    result = supervisor.run_step("judge", fn)

    assert result.success is True
    assert result.attempts == 1
    assert result.output == {"data": "ok"}
    fn.assert_called_once_with()


@pytest.mark.unit
def test_plain_step_retries_without_reflect(tmp_path):
    supervisor, llm, _ = _make_supervisor(tmp_path)
    fn = MagicMock(side_effect=[RuntimeError("boom"), {"data": "ok"}])

    result = supervisor.run_step("judge", fn)

    assert result.success is True
    assert result.attempts == 2
    # reflect LLM 不應被呼叫
    llm.complete.assert_not_called()


@pytest.mark.unit
def test_plain_step_fails_after_max_retries(tmp_path):
    supervisor, llm, _ = _make_supervisor(tmp_path)
    fn = MagicMock(side_effect=RuntimeError("always fails"))

    with patch("agents.daily_brief.supervisor.send", return_value=True):
        result = supervisor.run_step("judge", fn)

    assert result.success is False
    assert result.attempts == 2  # max_retries=2 for judge


@pytest.mark.unit
def test_error_aware_step_calls_reflect_on_failure(tmp_path):
    reflect_resp = json.dumps({
        "diagnosis": "JSON 解析錯誤",
        "adjusted_prompt": "修正後的 prompt",
    })
    supervisor, llm, _ = _make_supervisor(tmp_path, llm_resp=reflect_resp)
    fn = MagicMock(side_effect=[RuntimeError("json error"), {"digests": []}])

    result = supervisor.run_step("digest", fn)

    assert result.success is True
    assert result.attempts == 2
    # reflect LLM 應被呼叫一次
    llm.complete.assert_called_once()
    # 第二次呼叫應帶 reflect context
    assert fn.call_args_list[1] == call(reflect_context="修正後的 prompt")


@pytest.mark.unit
def test_alert_dedup_same_step_same_day(tmp_path):
    supervisor, _, _ = _make_supervisor(tmp_path)
    fn = MagicMock(side_effect=RuntimeError("fail"))

    with patch("agents.daily_brief.supervisor.send", return_value=True) as mock_send:
        supervisor.run_step("judge", fn)
        fn.reset_mock()
        fn.side_effect = RuntimeError("fail again")
        supervisor.run_step("judge", fn)

    # Telegram 只應發一次
    assert mock_send.call_count == 1


@pytest.mark.unit
def test_force_clears_alert(tmp_path):
    supervisor, _, _ = _make_supervisor(tmp_path)
    fn = MagicMock(side_effect=RuntimeError("fail"))

    with patch("agents.daily_brief.supervisor.send", return_value=True) as mock_send:
        supervisor.run_step("judge", fn)
        fn.reset_mock()
        fn.side_effect = RuntimeError("fail again")
        supervisor.run_step("judge", fn, force=True)

    assert mock_send.call_count == 2

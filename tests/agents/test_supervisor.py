import json
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch
import pytest


def _make_supervisor(tmp_path, llm_resp="", judge_resp="", notify_fn=None):
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
        notify_fn=notify_fn,
    ), llm, judge_llm


@pytest.mark.unit
def test_plain_step_success_on_first_attempt(tmp_path):
    supervisor, llm, _ = _make_supervisor(tmp_path)
    fn = MagicMock(return_value={"ok": True})

    # "save" 使用 plain strategy
    result = supervisor.run_step("save", fn)

    assert result.success is True
    assert result.attempts == 1
    assert result.output == {"ok": True}
    fn.assert_called_once_with()


@pytest.mark.unit
def test_plain_step_retries_without_reflect(tmp_path):
    supervisor, llm, _ = _make_supervisor(tmp_path)
    fn = MagicMock(side_effect=[RuntimeError("boom"), {"ok": True}])

    # "save" 使用 plain strategy，失敗重試時不應呼叫 reflect LLM
    result = supervisor.run_step("save", fn)

    assert result.success is True
    assert result.attempts == 2
    llm.complete.assert_not_called()


@pytest.mark.unit
def test_plain_step_fails_after_max_retries(tmp_path):
    mock_notify = MagicMock(return_value=True)
    supervisor, llm, _ = _make_supervisor(tmp_path, notify_fn=mock_notify)
    fn = MagicMock(side_effect=RuntimeError("always fails"))

    result = supervisor.run_step("judge", fn)

    assert result.success is False
    assert result.attempts == 2  # max_retries=2 for judge
    mock_notify.assert_called_once()


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
    mock_notify = MagicMock(return_value=True)
    supervisor, _, _ = _make_supervisor(tmp_path, notify_fn=mock_notify)
    fn = MagicMock(side_effect=RuntimeError("fail"))

    supervisor.run_step("judge", fn)
    fn.reset_mock()
    fn.side_effect = RuntimeError("fail again")
    supervisor.run_step("judge", fn)

    assert mock_notify.call_count == 1


@pytest.mark.unit
def test_force_clears_alert(tmp_path):
    mock_notify = MagicMock(return_value=True)
    supervisor, _, _ = _make_supervisor(tmp_path, notify_fn=mock_notify)
    fn = MagicMock(side_effect=RuntimeError("fail"))

    supervisor.run_step("judge", fn)
    fn.reset_mock()
    fn.side_effect = RuntimeError("fail again")
    supervisor.run_step("judge", fn, force=True)

    assert mock_notify.call_count == 2


@pytest.mark.unit
def test_fetch_partial_success_continues(tmp_path):
    """≥2 fetcher 成功時 pipeline 應繼續。"""
    results = {
        "hatena": {"articles": [{"url": "https://a.com", "interest": "***"}]},
        "hn": None,
        "reddit": {"articles": []},
        "security": None,
    }
    success_count = sum(1 for v in results.values() if v is not None)
    assert success_count >= 2


@pytest.mark.unit
def test_fetch_below_threshold_stops(tmp_path):
    """< 2 fetcher 成功時應停止。"""
    results = {"hatena": None, "hn": None, "reddit": {"articles": []}, "security": None}
    success_count = sum(1 for v in results.values() if v is not None)
    assert success_count < 2


@pytest.mark.unit
def test_reflect_uses_task_description_as_original_prompt(tmp_path):
    """reflect LLM 呼叫的 prompt 應包含 task_description，而非 '[step: name]'。"""
    reflect_resp = json.dumps(
        {
            "diagnosis": "LLM 回傳格式錯誤",
            "adjusted_prompt": "修正後指示",
        }
    )
    supervisor, llm, _ = _make_supervisor(tmp_path, llm_resp=reflect_resp)
    fn = MagicMock(side_effect=[RuntimeError("bad output"), {"digests": []}])

    supervisor.run_step("digest", fn)

    reflect_call_prompt = llm.complete.call_args[0][0]
    assert "跨來源深度摘要" in reflect_call_prompt
    assert "[step:" not in reflect_call_prompt


@pytest.mark.unit
def test_judge_uses_error_aware_strategy(tmp_path):
    """judge 步驟現在應使用 error_aware strategy，失敗時會呼叫 reflect。"""
    from agents.daily_brief.config import STEP_CONFIGS

    assert STEP_CONFIGS["judge"].strategy == "error_aware"


@pytest.mark.unit
def test_notify_failure_writes_error_to_alerts(tmp_path):
    """_notify_failure 應把 error 一起寫入 alerts.json，而非只寫純時間戳字串。"""
    mock_notify = MagicMock(return_value=True)
    supervisor, _, _ = _make_supervisor(tmp_path, notify_fn=mock_notify)
    fn = MagicMock(side_effect=RuntimeError("model not found"))

    supervisor.run_step("judge", fn)

    alerts = json.loads((tmp_path / "alerts.json").read_text(encoding="utf-8"))
    assert isinstance(alerts["judge"], dict), "alerts['judge'] 應為 dict，非純時間戳字串"
    assert "failed_at" in alerts["judge"]
    assert "error" in alerts["judge"]
    assert "model not found" in alerts["judge"]["error"]

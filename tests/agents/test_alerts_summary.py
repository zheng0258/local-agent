"""_send_alerts_summary — pipeline 結尾的單封失敗彙總。

步驟失敗時 supervisor 只寫 alerts.json；此函式負責唯一的失敗推播。
_QUIET_STEPS（如 deploy）仍留在 alerts.json，但不進 Telegram 摘要。
"""

import json

import pytest

from agents.daily_brief.agent import _QUIET_STEPS, _send_alerts_summary


def _write_alerts(steps_dir, alerts: dict) -> None:
    (steps_dir / "alerts.json").write_text(
        json.dumps(alerts, ensure_ascii=False), encoding="utf-8"
    )


def _alert(error: str) -> dict:
    return {"failed_at": "2026-07-10T04:14:13", "error": error}


@pytest.mark.unit
def test_summary_sends_single_message_for_failures(tmp_path):
    _write_alerts(tmp_path, {"judge": _alert("model not found")})
    sent: list[str] = []

    _send_alerts_summary(tmp_path, "2026-07-10", lambda m: sent.append(m) or True)

    assert len(sent) == 1
    assert "judge" in sent[0]
    assert (tmp_path / "alerts_summary.done").exists()


@pytest.mark.unit
def test_summary_excludes_quiet_steps(tmp_path):
    assert "deploy" in _QUIET_STEPS
    _write_alerts(tmp_path, {"deploy": _alert("git push 128"), "judge": _alert("boom")})
    sent: list[str] = []

    _send_alerts_summary(tmp_path, "2026-07-10", lambda m: sent.append(m) or True)

    assert len(sent) == 1
    assert "deploy" not in sent[0]
    assert "judge" in sent[0]


@pytest.mark.unit
def test_summary_silent_when_only_quiet_steps_failed(tmp_path):
    _write_alerts(tmp_path, {"deploy": _alert("git push 128")})
    sent: list[str] = []

    _send_alerts_summary(tmp_path, "2026-07-10", lambda m: sent.append(m) or True)

    assert sent == []
    # 仍 touch sentinel：當日結論已定，重跑不再重讀
    assert (tmp_path / "alerts_summary.done").exists()


@pytest.mark.unit
def test_summary_sends_only_once_per_day(tmp_path):
    _write_alerts(tmp_path, {"judge": _alert("boom")})
    sent: list[str] = []

    _send_alerts_summary(tmp_path, "2026-07-10", lambda m: sent.append(m) or True)
    _send_alerts_summary(tmp_path, "2026-07-10", lambda m: sent.append(m) or True)

    assert len(sent) == 1

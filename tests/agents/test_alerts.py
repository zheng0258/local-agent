"""alerts — Alert store（alerts.json 讀取 / 記錄 / 去重 / 收尾彙總）測試。"""

import json

import pytest

from agents.daily_brief.alerts import (
    _QUIET_STEPS,
    already_recorded,
    load_alerts,
    record_failure,
    send_summary,
)

pytestmark = pytest.mark.unit


def test_load_alerts_missing_returns_empty(tmp_path):
    assert load_alerts(tmp_path) == {}


def test_load_alerts_corrupt_returns_empty(tmp_path):
    (tmp_path / "alerts.json").write_text("{壞掉", encoding="utf-8")
    assert load_alerts(tmp_path) == {}


def test_record_failure_writes_shape(tmp_path):
    record_failure(tmp_path, "judge", "model not found")
    alerts = json.loads((tmp_path / "alerts.json").read_text(encoding="utf-8"))
    assert "failed_at" in alerts["judge"]
    assert "model not found" in alerts["judge"]["error"]


def test_already_recorded_reflects_store(tmp_path):
    assert not already_recorded(tmp_path, "judge")
    record_failure(tmp_path, "judge", "boom")
    assert already_recorded(tmp_path, "judge")


def test_send_summary_sends_once_and_dedups(tmp_path):
    record_failure(tmp_path, "hatena", "network down")
    record_failure(tmp_path, "reddit", "429 rate limit")
    sent = []

    send_summary(tmp_path, "2026-06-21", lambda m: sent.append(m) or True)
    assert len(sent) == 1
    assert "hatena" in sent[0] and "reddit" in sent[0]
    assert (tmp_path / "alerts_summary.done").exists()

    # 再呼叫一次 → summary sentinel 去重 → 不重發
    send_summary(tmp_path, "2026-06-21", lambda m: sent.append(m) or True)
    assert len(sent) == 1


def test_send_summary_silent_when_no_alerts(tmp_path):
    sent = []
    send_summary(tmp_path, "2026-06-21", lambda m: sent.append(m) or True)
    assert sent == []
    assert not (tmp_path / "alerts_summary.done").exists()


def test_send_summary_includes_deploy_failure(tmp_path):
    # 迴歸：deploy 曾被靜默 18 天（token 過期 push 失敗卻不推播）。
    # deploy 已移出 _QUIET_STEPS，push 失敗必須進 Telegram 摘要。
    assert "deploy" not in _QUIET_STEPS
    record_failure(tmp_path, "deploy", "git push 128")
    record_failure(tmp_path, "judge", "model not found")
    sent = []

    send_summary(tmp_path, "2026-06-21", lambda m: sent.append(m) or True)

    assert len(sent) == 1
    assert "deploy" in sent[0]
    assert "judge" in sent[0]


def test_send_summary_sends_when_only_deploy_fails(tmp_path):
    # deploy 單獨失敗（如 token 過期）也要推播——這正是被靜默 18 天的情境。
    record_failure(tmp_path, "deploy", "git push 128")
    sent = []

    send_summary(tmp_path, "2026-06-21", lambda m: sent.append(m) or True)

    assert len(sent) == 1
    assert "deploy" in sent[0]


def test_send_summary_excludes_quiet_steps_mechanism(tmp_path, monkeypatch):
    # _QUIET_STEPS 過濾機制仍在（集合目前為空）：若某步驟被列入 quiet，則不進摘要。
    monkeypatch.setattr("agents.daily_brief.alerts._QUIET_STEPS", frozenset({"deploy"}))
    record_failure(tmp_path, "deploy", "git push 128")
    record_failure(tmp_path, "judge", "model not found")
    sent = []

    send_summary(tmp_path, "2026-06-21", lambda m: sent.append(m) or True)

    assert len(sent) == 1
    assert "deploy" not in sent[0]
    assert "judge" in sent[0]


@pytest.mark.unit
def test_send_summary_includes_quality_block(tmp_path):
    """品質不合格要進當日摘要 TG——quality_alert 過去寫完就沒人看。"""
    from agents.daily_brief import alerts

    sent = []
    alerts.send_summary(
        tmp_path,
        "2026-09-23",
        sent.append,
        quality_reason="faithfulness=2；overall=3.3",
    )

    assert len(sent) == 1
    assert "faithfulness=2" in sent[0]
    # 品質問題不是步驟失敗，不該套用補跑指令
    assert "--force" not in sent[0]


@pytest.mark.unit
def test_send_summary_sends_when_only_quality_fails(tmp_path):
    """零步驟失敗但品質不合格時仍須發訊息（原本 alerts 為空就早退）。"""
    from agents.daily_brief import alerts

    sent = []
    alerts.send_summary(tmp_path, "2026-09-23", sent.append, quality_reason="faithfulness=2")
    assert len(sent) == 1


@pytest.mark.unit
def test_send_summary_silent_when_nothing_wrong(tmp_path):
    from agents.daily_brief import alerts

    sent = []
    alerts.send_summary(tmp_path, "2026-09-23", sent.append, quality_reason="")
    assert sent == []


@pytest.mark.unit
def test_send_summary_combines_step_failures_and_quality(tmp_path):
    from agents.daily_brief import alerts

    alerts.record_failure(tmp_path, "hatena", "HTTP 500")
    sent = []
    alerts.send_summary(tmp_path, "2026-09-23", sent.append, quality_reason="faithfulness=2")

    assert len(sent) == 1
    assert "hatena" in sent[0]
    assert "faithfulness=2" in sent[0]
    # 有步驟失敗時補跑指令仍在
    assert "--force hatena" in sent[0]


@pytest.mark.unit
def test_quality_reason_read_back_from_judge_artifact(tmp_path):
    """_quality_reason 從 judge.json 讀回告警理由，未告警時為空。"""
    import json

    from agents.daily_brief.agent import _quality_reason

    assert _quality_reason(tmp_path) == ""

    (tmp_path / "judge.json").write_text(
        json.dumps({"quality_alert": True, "quality_alert_reason": "faithfulness=2"}),
        encoding="utf-8",
    )
    assert _quality_reason(tmp_path) == "faithfulness=2"

    (tmp_path / "judge.json").write_text(
        json.dumps({"overall": 4.5}), encoding="utf-8"
    )
    assert _quality_reason(tmp_path) == ""

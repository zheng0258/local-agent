"""alerts — Alert store（alerts.json 讀取 / 記錄 / 去重 / 收尾彙總）測試。"""

import json

import pytest

from agents.daily_brief.alerts import (
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

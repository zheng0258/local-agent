"""共享 history typed view（tools/history_schema.py）測試。"""

import pytest

from tools.history_schema import (
    DATE_FMT,
    OK,
    HealthHistoryRecord,
    JudgeHistoryRecord,
    days_between,
    parse_date,
)

pytestmark = pytest.mark.unit


def test_constants():
    assert OK == "ok"
    assert DATE_FMT == "%Y-%m-%d"


def test_parse_date_valid_and_invalid():
    assert parse_date("2026-09-07") is not None
    assert parse_date("nope") is None
    assert parse_date(None) is None
    assert parse_date(42) is None


def test_days_between():
    assert days_between("2026-09-01", "2026-09-08") == 7
    assert days_between("2026-09-08", "2026-09-08") == 0


def test_judge_record_roundtrip():
    rec = JudgeHistoryRecord(
        date="2026-09-07",
        overall=4.2,
        relevance=4,
        completeness=5,
        faithfulness=3,
        quality_alert=False,
    )
    restored = JudgeHistoryRecord.from_dict(rec.to_dict())
    assert restored == rec


def test_judge_from_dict_missing_and_malformed():
    rec = JudgeHistoryRecord.from_dict({"date": "2026-09-07"})
    assert rec.overall is None and rec.completeness is None
    assert rec.quality_alert is False
    # bool 不算數字分數
    rec2 = JudgeHistoryRecord.from_dict(
        {"date": "d", "overall": True, "scores": {"relevance": True}}
    )
    assert rec2.overall is None and rec2.relevance is None
    # 非 Mapping 一律容錯
    assert JudgeHistoryRecord.from_dict("junk").date == ""


def test_judge_record_keeps_quality_alert_reason():
    # #26：示警原因須進跨天歷史，事後才查得到是哪一軸觸發
    rec = JudgeHistoryRecord(
        date="2026-10-14",
        overall=4.0,
        relevance=5,
        completeness=5,
        faithfulness=2,
        quality_alert=True,
        quality_alert_reason="faithfulness=2",
    )
    raw = rec.to_dict()
    assert raw["quality_alert_reason"] == "faithfulness=2"
    assert JudgeHistoryRecord.from_dict(raw) == rec


def test_judge_record_reason_absent_for_legacy_and_clean_rows():
    # 舊列無此欄 → 空字串；無示警時不寫入此鍵（未示警日形狀不變）
    assert JudgeHistoryRecord.from_dict({"date": "d"}).quality_alert_reason == ""
    clean = JudgeHistoryRecord(
        date="d", overall=5.0, relevance=5, completeness=5, faithfulness=5,
        quality_alert=False,
    )
    assert "quality_alert_reason" not in clean.to_dict()


def test_health_record_roundtrip_and_malformed():
    rec = HealthHistoryRecord(date="2026-09-07", results={"hn": OK, "rss": "network"})
    restored = HealthHistoryRecord.from_dict(rec.to_dict())
    assert restored == rec
    # 畸形 results → 空
    assert HealthHistoryRecord.from_dict({"date": "d", "results": "x"}).results == {}
    assert HealthHistoryRecord.from_dict(None).date == ""

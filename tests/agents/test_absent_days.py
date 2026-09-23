"""缺席日偵測：整天沒跑就完全無痕跡，是 ADR 0001 承認的盲區（計畫項目 3）。"""

import pytest

from agents.daily_brief.health import HealthRecord


def _rec(date: str) -> HealthRecord:
    return HealthRecord(date=date, results={"hatena": "ok"})


@pytest.mark.unit
def test_detect_absent_days_finds_middle_gap():
    from agents.daily_brief.health import detect_absent_days

    history = [_rec("2026-09-18"), _rec("2026-09-21")]
    assert detect_absent_days(history, "2026-09-22") == [
        "2026-09-19",
        "2026-09-20",
    ]


@pytest.mark.unit
def test_detect_absent_days_finds_trailing_gap_up_to_yesterday():
    """最後一筆記錄之後、今天之前的空窗也算缺席（停擺中的情境）。"""
    from agents.daily_brief.health import detect_absent_days

    history = [_rec("2026-09-20")]
    assert detect_absent_days(history, "2026-09-23") == [
        "2026-09-21",
        "2026-09-22",
    ]


@pytest.mark.unit
def test_detect_absent_days_excludes_today():
    """今天可能還在跑，不得算缺席——否則每天早上都會誤報。"""
    from agents.daily_brief.health import detect_absent_days

    history = [_rec("2026-09-22")]
    assert detect_absent_days(history, "2026-09-23") == []


@pytest.mark.unit
def test_detect_absent_days_no_gap():
    from agents.daily_brief.health import detect_absent_days

    history = [_rec("2026-09-21"), _rec("2026-09-22")]
    assert detect_absent_days(history, "2026-09-23") == []


@pytest.mark.unit
def test_detect_absent_days_empty_history():
    """空歷史不代表缺席——系統可能還沒開始跑。"""
    from agents.daily_brief.health import detect_absent_days

    assert detect_absent_days([], "2026-09-23") == []


@pytest.mark.unit
def test_detect_absent_days_ignores_dates_before_first_record():
    """第一筆記錄之前不算缺席（系統當時還不存在）。"""
    from agents.daily_brief.health import detect_absent_days

    history = [_rec("2026-09-22")]
    result = detect_absent_days(history, "2026-09-23")
    assert all(d >= "2026-09-22" for d in result)


@pytest.mark.unit
def test_compute_runs_renders_absent_rows():
    """站台運行紀錄頁要看得出停擺區間，而非整段消失。"""
    from tools.site_builder.runs import compute_runs

    health = [
        {"date": "2026-09-18", "results": {"hatena": "ok"}},
        {"date": "2026-09-21", "results": {"hatena": "ok"}},
    ]
    runs = compute_runs([], health, [], [])
    by_date = {r.date: r for r in runs}

    assert by_date["2026-09-19"].status == "absent"
    assert by_date["2026-09-20"].status == "absent"
    assert by_date["2026-09-21"].status != "absent"
    # newest first 的排序不受影響
    assert [r.date for r in runs] == sorted(by_date, reverse=True)


@pytest.mark.unit
def test_observe_and_escalate_notifies_absence_once(tmp_path, monkeypatch):
    """停擺後 pipeline 回來跑時要回補告警，且同一段空窗只打擾一次。"""
    import json

    from agents.daily_brief import health as health_mod

    history_file = tmp_path / "_health-history.json"
    state_file = tmp_path / "_health-escalated.json"
    history_file.write_text(
        json.dumps([{"date": "2026-09-18", "results": {"hatena": "ok"}}]),
        encoding="utf-8",
    )

    day_dir = tmp_path / "2026-09-21"
    steps_dir = day_dir / "steps"
    steps_dir.mkdir(parents=True)
    (steps_dir / "hatena.json").write_text("{}", encoding="utf-8")

    sent = []
    for _ in range(2):  # 跑兩次：第二次不得重複打擾
        health_mod.observe_and_escalate(
            "2026-09-21", day_dir, steps_dir, sent.append,
            history_file=history_file, state_file=state_file,
        )

    absence_msgs = [m for m in sent if "缺席日偵測" in m]
    assert len(absence_msgs) == 1
    assert "2026-09-19" in absence_msgs[0]
    assert "2026-09-20" in absence_msgs[0]


@pytest.mark.unit
def test_observe_and_escalate_silent_without_absence(tmp_path):
    """沒有空窗就不該發缺席告警。"""
    import json

    from agents.daily_brief import health as health_mod

    history_file = tmp_path / "_health-history.json"
    state_file = tmp_path / "_health-escalated.json"
    history_file.write_text(
        json.dumps([{"date": "2026-09-20", "results": {"hatena": "ok"}}]),
        encoding="utf-8",
    )

    day_dir = tmp_path / "2026-09-21"
    steps_dir = day_dir / "steps"
    steps_dir.mkdir(parents=True)
    (steps_dir / "hatena.json").write_text("{}", encoding="utf-8")

    sent = []
    health_mod.observe_and_escalate(
        "2026-09-21", day_dir, steps_dir, sent.append,
        history_file=history_file, state_file=state_file,
    )
    assert [m for m in sent if "缺席日偵測" in m] == []

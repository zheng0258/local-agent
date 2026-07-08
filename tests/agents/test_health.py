"""Daily Brief 可觀測性層（health.py）測試。"""

import json

import pytest

from agents.daily_brief.health import (
    OK,
    ChronicFinding,
    ErrorClass,
    HealthRecord,
    JudgeSaturationFinding,
    append_record,
    classify_error,
    detect_chronic,
    detect_judge_saturation,
    digest_source_shares,
    filter_new_escalations,
    format_escalation,
    load_history,
    load_judge_history,
    load_recent_digests,
    observe_run,
    record_escalations,
    render_health_table,
)

pytestmark = pytest.mark.unit


# ── classify_error ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "error, expected",
    [
        ("<urlopen error [Errno 61] Connection refused>", ErrorClass.NETWORK),
        ("<urlopen error [Errno 111] Connection refused>", ErrorClass.NETWORK),
        ("HTTP Error 400: Bad Request", ErrorClass.UPSTREAM_HTTP),
        ("HTTP Error 500: Internal Server Error", ErrorClass.UPSTREAM_HTTP),
        ("parse_llm_json: LLM 回傳無法解析為 JSON dict（前 120 字元）: ''", ErrorClass.EMPTY_LLM),
        ("parse_llm_json: 無法解析 {壞掉的 json", ErrorClass.PARSE),
        ("Telegram 訊息發送失敗", ErrorClass.OTHER),
        ("[Errno 2] No such file or directory: 'npx'", ErrorClass.OTHER),
        ("'list' object has no attribute 'get'", ErrorClass.OTHER),
        ("", ErrorClass.OTHER),
    ],
)
def test_classify_error(error, expected):
    assert classify_error(error) is expected


# ── observe_run ──────────────────────────────────────────────────


def _seed_run(tmp_path, *, ok_sources, alerts=None, telegram=False, vault=False):
    day_dir = tmp_path / "2026-06-21"
    steps_dir = day_dir / "steps"
    steps_dir.mkdir(parents=True)
    for src in ok_sources:
        (steps_dir / f"{src}.json").write_text("{}", encoding="utf-8")
    if alerts:
        (steps_dir / "alerts.json").write_text(json.dumps(alerts), encoding="utf-8")
    if telegram:
        (day_dir / "telegram.done").touch()
    if vault:
        (day_dir / "vault.done").touch()
    return day_dir, steps_dir


def test_observe_run_all_ok(tmp_path):
    day_dir, steps_dir = _seed_run(
        tmp_path,
        ok_sources=["hatena", "hn", "reddit", "security", "rss"],
        telegram=True,
        vault=True,
    )
    record = observe_run("2026-06-21", day_dir, steps_dir)
    assert record.results == {
        "hatena": OK, "hn": OK, "reddit": OK, "security": OK, "rss": OK,
        "telegram": OK, "vault": OK,
    }
    assert record.failures() == {}


def test_observe_run_classifies_source_failure(tmp_path):
    day_dir, steps_dir = _seed_run(
        tmp_path,
        ok_sources=["hn", "reddit", "security", "rss"],
        alerts={"hatena": {"error": "HTTP Error 400: Bad Request"}},
        telegram=True,
        vault=True,
    )
    record = observe_run("2026-06-21", day_dir, steps_dir)
    assert record.results["hatena"] == ErrorClass.UPSTREAM_HTTP.value
    assert record.failures() == {"hatena": ErrorClass.UPSTREAM_HTTP.value}


def test_observe_run_delivery_alert_maps_to_subject(tmp_path):
    # notify 失敗 → telegram subject；save 失敗 → vault subject
    day_dir, steps_dir = _seed_run(
        tmp_path,
        ok_sources=["hatena", "hn", "reddit", "security", "rss"],
        alerts={"notify": {"error": "Telegram 訊息發送失敗"}},
    )
    record = observe_run("2026-06-21", day_dir, steps_dir)
    assert record.results["telegram"] == ErrorClass.OTHER.value
    assert "vault" not in record.results  # 既無 sentinel 也無 alert → 未執行


def test_observe_run_alert_takes_precedence_over_stale_artifact(tmp_path):
    # 既有 artifact 又有 alert（重跑情境）→ 視為失敗
    day_dir, steps_dir = _seed_run(
        tmp_path,
        ok_sources=["hatena", "hn", "reddit", "security", "rss"],
        alerts={"hatena": {"error": "HTTP Error 400"}},
    )
    record = observe_run("2026-06-21", day_dir, steps_dir)
    assert record.results["hatena"] == ErrorClass.UPSTREAM_HTTP.value


# ── persistence ──────────────────────────────────────────────────


def test_append_and_load_roundtrip(tmp_path):
    f = tmp_path / "_health-history.json"
    r1 = HealthRecord("2026-06-20", {"hatena": OK})
    r2 = HealthRecord("2026-06-21", {"hatena": "network"})
    append_record(r1, f)
    history = append_record(r2, f)
    assert [r.date for r in history] == ["2026-06-20", "2026-06-21"]
    assert load_history(f) == history


def test_append_replaces_same_day(tmp_path):
    f = tmp_path / "_health-history.json"
    append_record(HealthRecord("2026-06-21", {"hatena": "network"}), f)
    history = append_record(HealthRecord("2026-06-21", {"hatena": OK}), f)
    assert len(history) == 1
    assert history[0].results["hatena"] == OK


def test_load_history_corrupt_file_returns_empty(tmp_path):
    f = tmp_path / "_health-history.json"
    f.write_text("{not json", encoding="utf-8")
    assert load_history(f) == []


# ── detect_chronic ───────────────────────────────────────────────


def _history(days):
    return [HealthRecord(f"2026-06-{d:02d}", res) for d, res in days]


def test_detect_chronic_fires_at_threshold():
    history = _history([
        (15, {"hatena": "upstream_http"}),
        (16, {"hatena": OK}),
        (17, {"hatena": "upstream_http"}),
        (18, {"hatena": "network"}),
    ])
    findings = detect_chronic(history, window=7, threshold=3)
    assert len(findings) == 1
    f = findings[0]
    assert f.subject == "hatena"
    assert f.fail_count == 3
    assert f.dominant_class == "upstream_http"  # 2 次 > network 1 次
    assert f.suggestion


def test_detect_chronic_silent_below_threshold():
    history = _history([
        (17, {"hatena": "network"}),
        (18, {"hatena": "network"}),
    ])
    assert detect_chronic(history, window=7, threshold=3) == []


def test_detect_chronic_respects_window():
    # 3 次失敗但散落在 10 天，window=7 只看最近 7 天 → 不觸發
    history = _history([
        (10, {"hatena": "network"}),
        (11, {"hatena": "network"}),
        (20, {"hatena": "network"}),
    ])
    assert detect_chronic(history, window=7, threshold=3) == []


# ── escalation 去重 ───────────────────────────────────────────────


def test_filter_new_escalations_blocks_recent_repeat(tmp_path):
    state = tmp_path / "_health-escalated.json"
    finding = ChronicFinding("hatena", 3, 7, "network", "fix it")
    record_escalations([finding], state, "2026-06-18")
    # 3 天後同一 subject 仍 chronic，但 window 內已 escalate → 不再打擾
    fresh = filter_new_escalations([finding], state, "2026-06-21", window=7)
    assert fresh == []


def test_filter_new_escalations_allows_after_window(tmp_path):
    state = tmp_path / "_health-escalated.json"
    finding = ChronicFinding("hatena", 3, 7, "network", "fix it")
    record_escalations([finding], state, "2026-06-10")
    fresh = filter_new_escalations([finding], state, "2026-06-21", window=7)
    assert fresh == [finding]


def test_filter_new_escalations_first_time_passes(tmp_path):
    state = tmp_path / "_health-escalated.json"
    finding = ChronicFinding("rss", 4, 7, "empty_llm", "fix")
    assert filter_new_escalations([finding], state, "2026-06-21") == [finding]


# ── digest 貢獻度 ─────────────────────────────────────────────────


def _digest_artifact(sources):
    return {
        "generated_at": "2026-07-07T02:00:00",
        "digests": [
            {"title": f"t{i}", "url": f"https://x/{i}", "source": "顯示名",
             "interest": "***", "summary": "s", "_source": src}
            for i, src in enumerate(sources)
        ],
    }


def test_digest_source_shares_counts_ratio():
    artifacts = [
        _digest_artifact(["rss", "rss", "hatena"]),
        _digest_artifact(["hn"]),
    ]
    shares = digest_source_shares(artifacts)
    assert shares == {"rss": 0.5, "hatena": 0.25, "hn": 0.25}


def test_digest_source_shares_skips_entries_without_source_field():
    # 舊 schema：digest 條目沒有 _source 欄位 → 靜默略過，不影響其他條目
    old = {"generated_at": "x", "digests": [
        {"title": "t", "url": "u", "source": "顯示名", "interest": "**", "summary": "s"},
    ]}
    shares = digest_source_shares([old, _digest_artifact(["rss"])])
    assert shares == {"rss": 1.0}


def test_digest_source_shares_empty_or_malformed_input():
    assert digest_source_shares([]) == {}
    assert digest_source_shares([{}, {"digests": "not-a-list"}, {"digests": [42]}]) == {}


def _seed_digest(tmp_path, date, sources):
    steps_dir = tmp_path / date / "steps"
    steps_dir.mkdir(parents=True)
    (steps_dir / "digest.json").write_text(
        json.dumps(_digest_artifact(sources)), encoding="utf-8"
    )


def test_load_recent_digests_reads_window_and_skips_missing_days(tmp_path):
    _seed_digest(tmp_path, "2026-07-07", ["rss"])
    _seed_digest(tmp_path, "2026-07-05", ["hn"])   # 07-06 缺檔 → 靜默略過
    _seed_digest(tmp_path, "2026-06-01", ["reddit"])  # 超出 30 天視窗 → 不讀
    artifacts = load_recent_digests(tmp_path, "2026-07-07", window=30)
    assert digest_source_shares(artifacts) == {"rss": 0.5, "hn": 0.5}


def test_load_recent_digests_skips_corrupt_file(tmp_path):
    _seed_digest(tmp_path, "2026-07-07", ["rss"])
    steps_dir = tmp_path / "2026-07-06" / "steps"
    steps_dir.mkdir(parents=True)
    (steps_dir / "digest.json").write_text("{not json", encoding="utf-8")
    artifacts = load_recent_digests(tmp_path, "2026-07-07", window=30)
    assert digest_source_shares(artifacts) == {"rss": 1.0}


def test_load_recent_digests_empty_dir(tmp_path):
    assert load_recent_digests(tmp_path, "2026-07-07") == []


# ── detect_judge_saturation ──────────────────────────────────────


def _judge_records(overalls, start="2026-06-01"):
    """依序生成連續日期的 judge 歷史記錄（形狀鏡像 _judge-history.json）。"""
    from datetime import datetime, timedelta

    base = datetime.strptime(start, "%Y-%m-%d")
    return [
        {
            "date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            "overall": overall,
            "scores": {"relevance": 5, "completeness": 5, "faithfulness": 5},
            "quality_alert": False,
        }
        for i, overall in enumerate(overalls)
    ]


def test_detect_judge_saturation_fires_when_scores_pinned():
    # 30 天中 29 天 overall ≥ 4.0（96.7% ≥ 90% 門檻）→ 飽和
    records = _judge_records([5.0] * 27 + [4.0, 4.3, 3.0])
    finding = detect_judge_saturation(records)
    assert finding is not None
    assert finding.window_days == 30
    assert finding.saturated_days == 29
    assert finding.min_overall == 3.0
    assert finding.max_overall == 5.0


def test_detect_judge_saturation_silent_when_scores_discriminate():
    # 30 天中只有 26 天 ≥ 4.0（86.7% < 90%）→ 儀表仍有鑑別力
    records = _judge_records([5.0] * 26 + [3.5, 3.0, 2.5, 3.8])
    assert detect_judge_saturation(records) is None


def test_detect_judge_saturation_insufficient_data():
    # 歷史只有 29 天（雖全貼頂）→ 資料不足，不誤報
    records = _judge_records([5.0] * 29)
    assert detect_judge_saturation(records) is None


def test_detect_judge_saturation_window_gaps_count_as_insufficient():
    # 歷史很長，但最新 30 個日曆天內只有 20 筆（cron 漏跑）→ 資料不足
    old = _judge_records([5.0] * 60, start="2026-01-01")
    recent = _judge_records([5.0] * 20, start="2026-06-19")  # 06-19 ~ 07-08
    assert detect_judge_saturation(old + recent) is None


def test_load_judge_history_roundtrip(tmp_path):
    f = tmp_path / "_judge-history.json"
    records = _judge_records([5.0, 4.0])
    f.write_text(json.dumps(records), encoding="utf-8")
    assert load_judge_history(f) == records


def test_load_judge_history_missing_or_corrupt_returns_empty(tmp_path):
    assert load_judge_history(tmp_path / "nope.json") == []
    f = tmp_path / "_judge-history.json"
    f.write_text("{壞掉", encoding="utf-8")
    assert load_judge_history(f) == []


def test_detect_judge_saturation_skips_malformed_records():
    # 形狀異常的記錄（缺 overall / 非 dict）靜默略過，不弄垮判定
    records = _judge_records([5.0] * 30) + [{"date": "2026-07-01"}, "junk", 42]
    finding = detect_judge_saturation(records)
    assert finding is not None
    assert finding.window_days == 30


# ── render ───────────────────────────────────────────────────────


def test_format_escalation_uses_allowed_html():
    msg = format_escalation([ChronicFinding("hatena", 4, 7, "upstream_http", "確認端點")], "2026-06-21")
    assert "<b>hatena</b>" in msg
    assert "4 次" in msg
    assert "確認端點" in msg
    for bad in ("<br>", "<p>", "<div>"):
        assert bad not in msg


def test_render_health_table_shows_rates():
    history = _history([
        (19, {"hatena": OK, "telegram": OK}),
        (20, {"hatena": "upstream_http", "telegram": OK}),
        (21, {"hatena": OK, "telegram": OK}),
    ])
    table = render_health_table(history)
    assert "hatena" in table
    assert "2/3" in table       # hatena 2 成功 / 3 天
    assert "telegram" in table
    assert "3/3" in table
    assert "upstream_http" in table  # 失敗類別標註


def test_render_health_table_empty():
    assert render_health_table([]) == "（尚無健康記錄）"


def test_render_health_table_shows_digest_shares():
    history = _history([
        (20, {"hatena": OK, "rss": OK, "telegram": OK}),
        (21, {"hatena": OK, "rss": OK, "telegram": OK}),
    ])
    table = render_health_table(history, digest_shares={"rss": 0.39, "hatena": 0.28})
    hatena_line = next(l for l in table.splitlines() if "hatena" in l)
    rss_line = next(l for l in table.splitlines() if l.strip().startswith("rss"))
    telegram_line = next(l for l in table.splitlines() if "telegram" in l)
    assert "digest 28%" in hatena_line
    assert "digest 39%" in rss_line
    assert "digest" not in telegram_line  # 遞送 subject 無占比欄
    assert "digest" in table.splitlines()[0]  # 標題註明 digest 欄意義


def test_render_health_table_without_shares_unchanged():
    history = _history([(21, {"hatena": OK})])
    table = render_health_table(history)
    assert "digest" not in table


def test_render_health_table_shows_judge_saturation_warning():
    history = _history([(20, {"hatena": OK}), (21, {"hatena": OK})])
    finding = JudgeSaturationFinding(
        window_days=30,
        saturated_days=30,
        score_floor=4.0,
        min_overall=4.0,
        max_overall=5.0,
        distribution={4.0: 6, 4.3: 7, 4.7: 1, 5.0: 16},
    )
    table = render_health_table(history, judge_saturation=finding)
    assert "judge 已失去鑑別力" in table
    assert "30/30" in table          # 貼頂天數 / 檢視天數
    assert "≥ 4.0" in table          # 門檻
    assert "4.0×6" in table          # 分數分佈摘要
    assert "5.0×16" in table


def test_render_health_table_without_saturation_no_warning():
    history = _history([(20, {"hatena": OK}), (21, {"hatena": OK})])
    table = render_health_table(history, judge_saturation=None)
    assert "judge" not in table

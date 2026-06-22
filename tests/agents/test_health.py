"""Daily Brief 可觀測性層（health.py）測試。"""

import json

import pytest

from agents.daily_brief.health import (
    OK,
    ChronicFinding,
    ErrorClass,
    HealthRecord,
    append_record,
    classify_error,
    detect_chronic,
    filter_new_escalations,
    format_escalation,
    load_history,
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

"""site_builder.status — 純函數：吃已解析的 judge/health 歷史 → SystemStatus DTO。

純記憶體：無 git / LLM / 網路 / 檔案副作用。loader (load_status) 才碰檔案。
系統狀態區的衍生指標（連續運作天數、judge 品質分趨勢、各來源成功率）皆在此計算，
並渲染為 inline SVG sparkline（不引入圖表庫）。
"""

import pytest

from tools.site_builder.status import (
    SystemStatus,
    compute_status,
    render_status_section,
)


def _judge(*pairs):
    """測試語料：(date, overall) → judge 歷史 dict 串。"""
    return [{"date": d, "overall": o} for d, o in pairs]


def _health(*records):
    """測試語料：(date, results_dict) → health 歷史 dict 串。"""
    return [{"date": d, "results": r} for d, r in records]


@pytest.mark.unit
def test_compute_status_returns_system_status():
    status = compute_status(
        judge_history=_judge(("2026-06-24", 4.0), ("2026-06-25", 5.0)),
        health_history=_health(
            ("2026-06-24", {"hn": "ok", "reddit": "ok"}),
            ("2026-06-25", {"hn": "ok", "reddit": "network"}),
        ),
    )
    assert isinstance(status, SystemStatus)


@pytest.mark.unit
def test_streak_counts_consecutive_run_days():
    # 連續運作天數：health 歷史中連到最新一天為止的連續日曆天數
    status = compute_status(
        judge_history=_judge(("2026-06-23", 4.0)),
        health_history=_health(
            ("2026-06-23", {"hn": "ok"}),
            ("2026-06-24", {"hn": "ok"}),
            ("2026-06-25", {"hn": "ok"}),
        ),
    )
    assert status.streak_days == 3


@pytest.mark.unit
def test_streak_breaks_on_calendar_gap():
    # 中間漏跑一天 → streak 只算最新的連續段
    status = compute_status(
        judge_history=_judge(("2026-06-25", 4.0)),
        health_history=_health(
            ("2026-06-20", {"hn": "ok"}),
            ("2026-06-21", {"hn": "ok"}),
            ("2026-06-24", {"hn": "ok"}),
            ("2026-06-25", {"hn": "ok"}),
        ),
    )
    assert status.streak_days == 2


@pytest.mark.unit
def test_judge_series_is_chronological_overall_scores():
    # sparkline 用：judge overall 分數依日期由舊到新
    status = compute_status(
        judge_history=_judge(
            ("2026-06-25", 5.0), ("2026-06-23", 3.0), ("2026-06-24", 4.0)
        ),
        health_history=_health(("2026-06-25", {"hn": "ok"})),
    )
    assert status.judge_series == (3.0, 4.0, 5.0)


@pytest.mark.unit
def test_source_rates_compute_per_source_success_pct():
    # 各來源成功率：ok 次數 / 出現次數
    status = compute_status(
        judge_history=_judge(("2026-06-25", 4.0)),
        health_history=_health(
            ("2026-06-24", {"hn": "ok", "reddit": "ok"}),
            ("2026-06-25", {"hn": "ok", "reddit": "network"}),
        ),
    )
    rates = {r.source: r.rate for r in status.source_rates}
    assert rates["hn"] == 1.0
    assert rates["reddit"] == 0.5


@pytest.mark.unit
def test_compute_status_none_when_both_histories_empty():
    # 優雅降級：兩份歷史皆空 → None（呼叫端略過狀態區）
    assert compute_status(judge_history=[], health_history=[]) is None


@pytest.mark.unit
def test_compute_status_tolerates_missing_overall_and_malformed_rows():
    # 缺 overall / 非 dict 列 → 跳過，不報錯
    status = compute_status(
        judge_history=[
            {"date": "2026-06-25"},
            "garbage",
            {"overall": 4.0, "date": "2026-06-24"},
        ],
        health_history=[{"date": "2026-06-25", "results": {"hn": "ok"}}, "junk"],
    )
    assert status.judge_series == (4.0,)
    assert status.streak_days == 1


@pytest.mark.unit
def test_render_status_section_includes_streak_and_svg():
    status = compute_status(
        judge_history=_judge(("2026-06-24", 4.0), ("2026-06-25", 5.0)),
        health_history=_health(
            ("2026-06-24", {"hn": "ok"}),
            ("2026-06-25", {"hn": "ok"}),
        ),
    )
    html = render_status_section(status)
    assert "系統狀態" in html
    assert "連續" in html and "2" in html
    assert "<svg" in html  # inline SVG sparkline，無圖表庫
    assert "</svg>" in html


@pytest.mark.unit
def test_render_status_section_shows_source_rates():
    status = compute_status(
        judge_history=_judge(("2026-06-25", 4.0)),
        health_history=_health(
            ("2026-06-24", {"hn": "ok", "reddit": "ok"}),
            ("2026-06-25", {"hn": "ok", "reddit": "network"}),
        ),
    )
    html = render_status_section(status)
    assert "hn" in html
    assert "reddit" in html
    assert "100" in html  # hn 100%
    assert "50" in html  # reddit 50%


@pytest.mark.unit
def test_render_status_section_single_point_series_does_not_crash():
    # 只有一天 judge 分 → sparkline 仍渲染（不除以零）
    status = compute_status(
        judge_history=_judge(("2026-06-25", 4.0)),
        health_history=_health(("2026-06-25", {"hn": "ok"})),
    )
    html = render_status_section(status)
    assert "<svg" in html

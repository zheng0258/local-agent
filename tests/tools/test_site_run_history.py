"""運行紀錄頁：render_run_history（純渲染）+ load_runs（薄 loader）+ build 整合。"""

import json

import pytest

from tools.site_builder.builder import build_site_archive
from tools.site_builder.loader import load_runs
from tools.site_builder.runs import RunRecord, compute_runs
from tools.site_builder.template import render_run_history

pytestmark = pytest.mark.unit

ALL_OK = {
    "hatena": "ok",
    "hn": "ok",
    "reddit": "ok",
    "security": "ok",
    "rss": "ok",
    "telegram": "ok",
    "vault": "ok",
    "deploy": "ok",
}


def _runs():
    return compute_runs(
        judge_history=[{"date": "2026-09-22", "overall": 4.1}],
        health_history=[
            {"date": "2026-09-22", "results": {**ALL_OK, "deploy": "other"}}
        ],
        usage_history=[{"date": "2026-09-22", "calls": 40, "total_tokens": 1_420_000}],
    )


def test_render_run_history_contains_row_and_status():
    html = render_run_history(_runs())
    assert "2026-09-22" in html
    assert "partial" in html  # deploy 失敗 → 降級
    assert "1.42M" in html
    assert "4.1" in html
    # 狀態矩陣 8 個 subject 小格
    assert html.count("rcell") >= 8


def test_render_run_history_empty_state():
    html = render_run_history([])
    assert "尚無運行紀錄" in html


def test_render_run_history_links_to_archive_day():
    html = render_run_history(_runs())
    assert 'href="archive/2026-09-22.html"' in html


def test_load_runs_reads_all_histories(tmp_path):
    (tmp_path / "_judge-history.json").write_text(
        json.dumps([{"date": "2026-09-22", "overall": 4.1}]), encoding="utf-8"
    )
    (tmp_path / "_health-history.json").write_text(
        json.dumps([{"date": "2026-09-22", "results": ALL_OK}]), encoding="utf-8"
    )
    (tmp_path / "_usage-history.json").write_text(
        json.dumps([{"date": "2026-09-22", "calls": 40, "total_tokens": 999}]),
        encoding="utf-8",
    )
    (tmp_path / "_run-history.json").write_text(
        json.dumps(
            [{"date": "2026-09-22", "trigger": "cron", "duration_seconds": 100.0}]
        ),
        encoding="utf-8",
    )
    runs = load_runs(tmp_path)
    assert len(runs) == 1
    assert runs[0].overall == 4.1
    assert runs[0].tokens_total == 999
    assert runs[0].trigger == "cron"


def test_load_runs_missing_files_returns_empty(tmp_path):
    assert load_runs(tmp_path) == ()


def test_build_site_archive_emits_run_history_when_runs_given():
    site = build_site_archive([("2026-09-22", "# r")], runs=_runs())
    assert "run-history.html" in site
    assert "運行紀錄" in site["index.html"]  # 首頁 top nav 連結


def test_build_site_archive_omits_run_history_when_runs_none():
    site = build_site_archive([("2026-09-22", "# r")])
    assert "run-history.html" not in site

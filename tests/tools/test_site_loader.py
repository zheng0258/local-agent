"""load_days — 薄 loader（impure）：掃 OUTPUT_DIR/<date>/report.md → (date, md) 串。

純 builder 餵 fixture；此 loader 是唯一碰檔案的歷史讀取點，餵真實目錄結構。
餵 tmp_path，不碰真 outputs/。
"""

import json

import pytest

from tools.site_builder import Narrative, load_days, load_narrative
from tools.site_builder.loader import (
    DEFAULT_NARRATIVE_PATH,
    load_latest_tldr,
    load_status,
)
from tools.site_builder.status import SystemStatus


@pytest.mark.unit
def test_load_days_reads_all_report_md(tmp_path):
    for date, body in [
        ("2026-06-23", "# Day 23"),
        ("2026-06-24", "# Day 24"),
        ("2026-06-25", "# Day 25"),
    ]:
        d = tmp_path / date
        d.mkdir()
        (d / "report.md").write_text(body, encoding="utf-8")

    days = load_days(tmp_path)
    assert [date for date, _ in days] == ["2026-06-25", "2026-06-24", "2026-06-23"]
    assert dict(days)["2026-06-24"] == "# Day 24"


@pytest.mark.unit
def test_load_days_newest_first(tmp_path):
    for date in ["2026-01-01", "2026-12-31", "2026-06-15"]:
        d = tmp_path / date
        d.mkdir()
        (d / "report.md").write_text("# r", encoding="utf-8")
    days = load_days(tmp_path)
    assert [date for date, _ in days] == ["2026-12-31", "2026-06-15", "2026-01-01"]


@pytest.mark.unit
def test_load_days_skips_dirs_without_report(tmp_path):
    (tmp_path / "2026-06-25").mkdir()
    (tmp_path / "2026-06-25" / "report.md").write_text("# ok", encoding="utf-8")
    (tmp_path / "2026-06-24").mkdir()  # 無 report.md（補跑中 / 失敗天）
    (tmp_path / "_judge-history.json").write_text("{}", encoding="utf-8")  # 非日期檔
    days = load_days(tmp_path)
    assert [date for date, _ in days] == ["2026-06-25"]


@pytest.mark.unit
def test_load_days_ignores_non_date_dirs(tmp_path):
    (tmp_path / ".vectordb").mkdir()
    (tmp_path / "2026-06-25").mkdir()
    (tmp_path / "2026-06-25" / "report.md").write_text("# ok", encoding="utf-8")
    days = load_days(tmp_path)
    assert [date for date, _ in days] == ["2026-06-25"]


@pytest.mark.unit
def test_load_days_empty_dir_returns_empty(tmp_path):
    assert load_days(tmp_path) == []


@pytest.mark.unit
def test_load_days_missing_dir_returns_empty(tmp_path):
    assert load_days(tmp_path / "nope") == []


# --- load_narrative (issue #8): 薄 loader 讀雙語敘事 config 檔 ---


@pytest.mark.unit
def test_load_narrative_splits_zh_and_en_sections(tmp_path):
    cfg = tmp_path / "narrative.md"
    cfg.write_text(
        "<!-- 檔頭註解，忽略 -->\n"
        "<!-- lang:zh -->\n## 標題\n繁中段落\n"
        "<!-- lang:en -->\n## Title\nEnglish paragraph\n",
        encoding="utf-8",
    )
    n = load_narrative(cfg)
    assert isinstance(n, Narrative)
    assert "繁中段落" in n.zh_md
    assert "## 標題" in n.zh_md
    assert "English paragraph" in n.en_md
    # 不洩漏跨區塊內容
    assert "English paragraph" not in n.zh_md
    assert "繁中段落" not in n.en_md


@pytest.mark.unit
def test_load_narrative_default_config_has_both_languages():
    # AC1：in-repo 預設 config 真實存在且中英兩版皆有內容
    assert DEFAULT_NARRATIVE_PATH.is_file()
    n = load_narrative()
    assert n.zh_md.strip()
    assert n.en_md.strip()
    # 繁中提及定位詞、英文提及 local-LLM 多代理
    assert "本地" in n.zh_md
    assert "local" in n.en_md.lower()


# --- load_latest_tldr: 讀最新一天 steps/tldr.json ---


def _make_day(tmp_path, date, *, report=True, tldr=None):
    d = tmp_path / date
    (d / "steps").mkdir(parents=True)
    if report:
        (d / "report.md").write_text("# r", encoding="utf-8")
    if tldr is not None:
        (d / "steps" / "tldr.json").write_text(
            f'{{"tldr": "{tldr}"}}', encoding="utf-8"
        )
    return d


def test_load_latest_tldr_reads_latest_day(tmp_path):
    _make_day(tmp_path, "2026-06-24", tldr="舊")
    _make_day(tmp_path, "2026-06-25", tldr="最新今日重點")
    assert load_latest_tldr(tmp_path) == "最新今日重點"


def test_load_latest_tldr_none_when_latest_day_has_no_tldr(tmp_path):
    # 歷史天有 tldr，但最新天沒有 → 不回填，回 None
    _make_day(tmp_path, "2026-06-24", tldr="舊")
    _make_day(tmp_path, "2026-06-25", tldr=None)
    assert load_latest_tldr(tmp_path) is None


def test_load_latest_tldr_none_when_no_days(tmp_path):
    assert load_latest_tldr(tmp_path) is None


def test_load_latest_tldr_missing_dir_returns_none(tmp_path):
    assert load_latest_tldr(tmp_path / "nope") is None


# --- load_status (issue #10): 讀 _judge-history.json + _health-history.json ---


def _write_history(tmp_path, judge=None, health=None):
    if judge is not None:
        (tmp_path / "_judge-history.json").write_text(
            json.dumps(judge), encoding="utf-8"
        )
    if health is not None:
        (tmp_path / "_health-history.json").write_text(
            json.dumps(health), encoding="utf-8"
        )


@pytest.mark.unit
def test_load_status_parses_both_histories(tmp_path):
    _write_history(
        tmp_path,
        judge=[
            {"date": "2026-06-24", "overall": 4.0},
            {"date": "2026-06-25", "overall": 5.0},
        ],
        health=[
            {"date": "2026-06-24", "results": {"hn": "ok"}},
            {"date": "2026-06-25", "results": {"hn": "ok"}},
        ],
    )
    status = load_status(tmp_path)
    assert isinstance(status, SystemStatus)
    assert status.streak_days == 2
    assert status.judge_series == (4.0, 5.0)


@pytest.mark.unit
def test_load_status_none_when_files_missing(tmp_path):
    # AC4：歷史檔缺失 → None（呼叫端略過狀態區），不報錯
    assert load_status(tmp_path) is None


@pytest.mark.unit
def test_load_status_none_when_histories_empty(tmp_path):
    _write_history(tmp_path, judge=[], health=[])
    assert load_status(tmp_path) is None


@pytest.mark.unit
def test_load_status_tolerates_corrupt_json(tmp_path):
    # 損毀 JSON → 視為空，不報錯
    (tmp_path / "_judge-history.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "_health-history.json").write_text("also broken", encoding="utf-8")
    assert load_status(tmp_path) is None


@pytest.mark.unit
def test_load_status_works_with_only_health(tmp_path):
    # judge 缺失但 health 在 → 仍回 status（streak + 來源成功率），sparkline 空序列
    _write_history(
        tmp_path,
        health=[{"date": "2026-06-25", "results": {"hn": "ok", "reddit": "network"}}],
    )
    status = load_status(tmp_path)
    assert isinstance(status, SystemStatus)
    assert status.streak_days == 1
    assert status.judge_series == ()
    rates = {r.source: r.rate for r in status.source_rates}
    assert rates["hn"] == 1.0
    assert rates["reddit"] == 0.0

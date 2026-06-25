"""load_days — 薄 loader（impure）：掃 OUTPUT_DIR/<date>/report.md → (date, md) 串。

純 builder 餵 fixture；此 loader 是唯一碰檔案的歷史讀取點，餵真實目錄結構。
餵 tmp_path，不碰真 outputs/。
"""

import pytest

from tools.site_builder import load_days


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

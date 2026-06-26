"""load_days — 薄 loader（impure）：掃 OUTPUT_DIR/<date>/report.md → (date, md) 串。

純 builder 餵 fixture；此 loader 是唯一碰檔案的歷史讀取點，餵真實目錄結構。
餵 tmp_path，不碰真 outputs/。
"""

import pytest

from tools.site_builder import Narrative, load_days, load_narrative
from tools.site_builder.loader import DEFAULT_NARRATIVE_PATH


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

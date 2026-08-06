"""site_builder — 純函數：吃最新一天 Brief 語料，回傳 in-memory {path: html} map。

對照 tests/tools/fetchers/* 純工具形狀：無 git / LLM / 網路 / 檔案副作用。
薄 writer (write_site) 才落盤。
"""

import pytest

from tools.site_builder import build_site, build_site_archive, write_site


@pytest.mark.unit
def test_build_site_returns_map_with_index():
    site = build_site(report_md="# Hello", date="2026-06-25")
    assert isinstance(site, dict)
    assert "index.html" in site
    assert isinstance(site["index.html"], str)


@pytest.mark.unit
def test_index_renders_report_markdown_to_html():
    md = "# 今日趨勢\n\n- [Example](https://example.com) 很重要"
    html = build_site(report_md=md, date="2026-06-25")["index.html"]
    # markdown → HTML：標題與連結被渲染成標籤，而非保留原始 markdown 符號。
    # 連結屬性不精確比對（sanitizer 會補 rel="noopener noreferrer"），只驗意圖。
    assert "<h1>今日趨勢</h1>" in html
    assert '<a href="https://example.com"' in html
    assert ">Example</a>" in html


@pytest.mark.unit
def test_index_has_positioning_line():
    html = build_site(report_md="# r", date="2026-06-25")["index.html"]
    assert "本地 LLM 多代理自主系統" in html


@pytest.mark.unit
def test_index_uses_terminal_dark_monospace_shell():
    html = build_site(report_md="# r", date="2026-06-25")["index.html"]
    # 技術終端風：暗色背景 + 等寬字
    assert "monospace" in html
    assert ("#0b0f14" in html) or ("background: #0" in html)
    assert html.lstrip().startswith("<!DOCTYPE html>")


@pytest.mark.unit
def test_index_strips_raw_html_script_injection():
    # report_md 源自外部文章標題（不可信）；公開站台必須中和 raw HTML（stored XSS）
    md = "1. 惡意標題 <script>alert(document.cookie)</script> 後文"
    html = build_site(report_md=md, date="2026-06-25")["index.html"]
    assert "<script>" not in html
    assert "alert(document.cookie)" not in html


@pytest.mark.unit
def test_index_strips_event_handler_attributes():
    md = "1. <img src=x onerror=alert(1)> 圖片注入"
    html = build_site(report_md=md, date="2026-06-25")["index.html"]
    assert "onerror" not in html
    assert "<img" not in html


@pytest.mark.unit
def test_index_strips_javascript_uri_in_links():
    # markdown 連結語法可產生 live href；javascript: scheme 必須被丟棄
    md = "1. [點我](javascript:alert(1)) 惡意連結"
    html = build_site(report_md=md, date="2026-06-25")["index.html"]
    assert "javascript:" not in html


@pytest.mark.unit
def test_index_preserves_safe_links_and_tables():
    md = (
        "# 趨勢\n\n| 標題 | 分數 |\n|---|---|\n| GLM | 544 |\n\n"
        "1. [安全連結](https://ok.example/a)"
    )
    html = build_site(report_md=md, date="2026-06-25")["index.html"]
    assert "<table>" in html
    assert "https://ok.example/a" in html


# --- Archive corpus (issue #7): build_site_archive(days) ---


def _days(*pairs):
    """測試語料：(date, report_md) tuple 串（newest first），純記憶體。"""
    return list(pairs)


@pytest.mark.unit
def test_archive_has_one_page_per_day_count_equals_input():
    # AC1：餵 N 天，存檔頁數 == N（每天一頁）
    days = _days(
        ("2026-06-25", "# Day 25"),
        ("2026-06-24", "# Day 24"),
        ("2026-06-23", "# Day 23"),
    )
    site = build_site_archive(days)
    archive_pages = [p for p in site if p.startswith("archive/")]
    assert len(archive_pages) == 3
    assert set(archive_pages) == {
        "archive/2026-06-25.html",
        "archive/2026-06-24.html",
        "archive/2026-06-23.html",
    }


@pytest.mark.unit
def test_archive_map_also_has_index():
    site = build_site_archive(_days(("2026-06-25", "# r")))
    assert "index.html" in site


@pytest.mark.unit
def test_archive_page_labels_its_date_and_renders_report():
    # AC2：存檔頁清楚標示日期，內容由該天 report.md 渲染
    days = _days(
        ("2026-06-25", "# 今日 25"),
        ("2026-06-24", "# 昨日 24"),
    )
    site = build_site_archive(days)
    page24 = site["archive/2026-06-24.html"]
    assert "2026-06-24" in page24
    assert "<h1>昨日 24</h1>" in page24
    # 不洩漏其他天的內容
    assert "今日 25" not in page24


@pytest.mark.unit
def test_archive_index_links_to_every_day():
    # AC3：首頁/導覽提供連往各天的入口
    days = _days(
        ("2026-06-25", "# r"),
        ("2026-06-24", "# r"),
        ("2026-06-23", "# r"),
    )
    index = build_site_archive(days)["index.html"]
    assert 'href="archive/2026-06-25.html"' in index
    assert 'href="archive/2026-06-24.html"' in index
    assert 'href="archive/2026-06-23.html"' in index


@pytest.mark.unit
def test_archive_index_shows_latest_day_and_positioning():
    # 不可回歸 #6：首頁仍秀最新天 + 定位句 + 終端風
    days = _days(
        ("2026-06-25", "# 最新內容"),
        ("2026-06-24", "# 舊內容"),
    )
    index = build_site_archive(days)["index.html"]
    assert "本地 LLM 多代理自主系統" in index
    assert "2026-06-25" in index
    assert "<h1>最新內容</h1>" in index
    assert "monospace" in index
    assert index.lstrip().startswith("<!DOCTYPE html>")


@pytest.mark.unit
def test_archive_page_sanitizes_untrusted_report_html():
    # 存檔頁內容同樣不可信，必須走 _sanitize（stored XSS 防護）
    days = _days(("2026-06-25", "壞 <script>alert(1)</script> 標題"))
    page = build_site_archive(days)["archive/2026-06-25.html"]
    assert "<script>" not in page
    assert "alert(1)" not in page


@pytest.mark.unit
def test_archive_empty_corpus_returns_index_only():
    site = build_site_archive(_days())
    assert "index.html" in site
    assert not any(p.startswith("archive/") for p in site)


# --- Latest-day 今日重點 TL;DR: build_site_archive(latest_tldr=...) ---


@pytest.mark.unit
def test_archive_index_renders_latest_tldr_when_present():
    days = _days(("2026-06-25", "# 最新內容"))
    index = build_site_archive(days, latest_tldr="今日 AI 工具進展快速。")[
        "index.html"
    ]
    assert "今日 AI 工具進展快速。" in index
    assert "今日重點" in index


@pytest.mark.unit
def test_archive_index_omits_tldr_when_none():
    days = _days(("2026-06-25", "# 最新內容"))
    index = build_site_archive(days)["index.html"]
    # 無今日重點時不渲染該區段（section.tldr markup 不出現）
    assert '<section class="tldr">' not in index


@pytest.mark.unit
def test_archive_index_sanitizes_untrusted_tldr_html():
    # 今日重點源自 LLM 對外部內容的摘要（不可信）；公開站台必須中和 raw HTML
    days = _days(("2026-06-25", "# r"))
    index = build_site_archive(days, latest_tldr="bad <script>alert(1)</script> end")[
        "index.html"
    ]
    assert "<script>" not in index
    assert "alert(1)" not in index


@pytest.mark.unit
def test_archive_tldr_only_on_index_not_archive_pages():
    days = _days(
        ("2026-06-25", "# 今日"),
        ("2026-06-24", "# 昨日"),
    )
    site = build_site_archive(days, latest_tldr="UNIQUE_TLDR_MARKER")
    # 只出現在首頁最新天，不滲入歷史存檔頁
    assert "UNIQUE_TLDR_MARKER" in site["index.html"]
    assert "UNIQUE_TLDR_MARKER" not in site["archive/2026-06-24.html"]


# --- System status section (issue #10): build_site_archive(status=...) ---


def _status(streak=2, series=(4.0, 5.0)):
    from tools.site_builder.status import SourceRate, SystemStatus

    return SystemStatus(
        streak_days=streak,
        judge_series=series,
        source_rates=(
            SourceRate(source="hn", rate=1.0, ok=2, total=2),
            SourceRate(source="reddit", rate=0.5, ok=1, total=2),
        ),
    )


@pytest.mark.unit
def test_archive_index_renders_status_section_when_present():
    # AC1/AC2：首頁含「系統狀態」區，呈現連續天數 + sparkline
    days = _days(("2026-06-25", "# 最新內容"))
    index = build_site_archive(days, status=_status(streak=7))["index.html"]
    assert "系統狀態" in index
    assert "連續" in index and "7" in index
    assert "<svg" in index  # inline SVG sparkline，無圖表庫


@pytest.mark.unit
def test_archive_index_status_shows_source_rates():
    days = _days(("2026-06-25", "# r"))
    index = build_site_archive(days, status=_status())["index.html"]
    assert "hn" in index
    assert "reddit" in index
    assert "100%" in index
    assert "50%" in index


@pytest.mark.unit
def test_archive_index_omits_status_when_none():
    # AC4：歷史缺失 → status None → 不渲染狀態區，不報錯（向後相容 #6/#7/#8/#9）
    days = _days(("2026-06-25", "# 最新內容"))
    index = build_site_archive(days)["index.html"]
    assert "系統狀態" not in index


@pytest.mark.unit
def test_archive_status_no_chart_library_imported():
    # AC3：不引入圖表庫／前端框架；趨勢為 inline SVG
    days = _days(("2026-06-25", "# r"))
    index = build_site_archive(days, status=_status())["index.html"]
    lowered = index.lower()
    for lib in ("chart.js", "d3.min", "plotly", "react", "vue.js"):
        assert lib not in lowered


@pytest.mark.unit
def test_archive_status_only_on_index_not_archive_pages():
    days = _days(("2026-06-25", "# 今日"), ("2026-06-24", "# 昨日"))
    site = build_site_archive(days, status=_status())
    assert "系統狀態" in site["index.html"]
    assert "系統狀態" not in site["archive/2026-06-24.html"]


@pytest.mark.unit
def test_write_site_dumps_map_to_directory(tmp_path):
    site = build_site(report_md="# r", date="2026-06-25")
    write_site(site, tmp_path)
    written = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert written == site["index.html"]


@pytest.mark.unit
def test_write_site_creates_nested_subdirs(tmp_path):
    write_site({"assets/style.css": "body{}"}, tmp_path)
    assert (tmp_path / "assets" / "style.css").read_text(encoding="utf-8") == "body{}"

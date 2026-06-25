"""site_builder — 純函數：吃最新一天 Brief 語料，回傳 in-memory {path: html} map。

對照 tests/tools/fetchers/* 純工具形狀：無 git / LLM / 網路 / 檔案副作用。
薄 writer (write_site) 才落盤。
"""

import pytest

from tools.site_builder import build_site, write_site


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
    # markdown → HTML：標題與連結被渲染成標籤，而非保留原始 markdown 符號
    assert "<h1>今日趨勢</h1>" in html
    assert '<a href="https://example.com">Example</a>' in html


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
def test_write_site_dumps_map_to_directory(tmp_path):
    site = build_site(report_md="# r", date="2026-06-25")
    write_site(site, tmp_path)
    written = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert written == site["index.html"]


@pytest.mark.unit
def test_write_site_creates_nested_subdirs(tmp_path):
    write_site({"assets/style.css": "body{}"}, tmp_path)
    assert (tmp_path / "assets" / "style.css").read_text(encoding="utf-8") == "body{}"

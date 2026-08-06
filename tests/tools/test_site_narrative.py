"""專案描述（issue #8 → 改版）— 純 builder 吃 in-memory Narrative，渲染繁中描述進 overlay。

專案描述不直接顯示：hero 排一個「關於本專案」按鈕，點擊彈出純 CSS overlay 呈現繁中描述
（不再中英切換，以中文為主）。純核心測試一律以記憶體 Narrative fixture 餵入，不碰檔案。
"""

import pytest

from tools.site_builder import Narrative, build_site_archive


def _days(*pairs):
    return list(pairs)


_NARRATIVE = Narrative(
    zh_md="## 這是什麼\n\n本地多代理系統的繁中敘事段落。",
    en_md="## What this is\n\nThe English narrative paragraph here.",
)


@pytest.mark.unit
def test_index_renders_chinese_narrative_only():
    # 繁中描述在場（收於 overlay）；英文版不再顯示（以中文為主）
    index = build_site_archive(_days(("2026-06-25", "# r")), narrative=_NARRATIVE)[
        "index.html"
    ]
    assert "本地多代理系統的繁中敘事段落" in index
    assert "The English narrative paragraph here" not in index


@pytest.mark.unit
def test_index_offers_about_button_and_overlay_no_language_toggle():
    # 專案描述不直接顯示：hero 排「關於本專案」按鈕 + 純 CSS overlay；不再有中/EN 切換
    index = build_site_archive(_days(("2026-06-25", "# r")), narrative=_NARRATIVE)[
        "index.html"
    ]
    assert "關於本專案" in index
    assert 'class="about-btn"' in index
    assert 'class="about-overlay"' in index
    assert 'id="about-toggle"' in index
    # 舊的中/EN 切換機制已移除
    assert 'id="lang-zh"' not in index
    assert 'id="lang-en"' not in index


@pytest.mark.unit
def test_index_renders_narrative_markdown_to_html():
    # 描述走與 report 一致的 markdown→HTML 路徑（## → <h2>）；只渲染繁中版
    index = build_site_archive(_days(("2026-06-25", "# r")), narrative=_NARRATIVE)[
        "index.html"
    ]
    assert "<h2>這是什麼</h2>" in index
    assert "What this is" not in index


@pytest.mark.unit
def test_index_hero_shows_positioning_line_with_narrative():
    # hero 區顯著呈現定位句（描述在場時仍在）
    index = build_site_archive(_days(("2026-06-25", "# r")), narrative=_NARRATIVE)[
        "index.html"
    ]
    assert "本地 LLM 多代理自主系統" in index


@pytest.mark.unit
def test_narrative_optional_backward_compatible():
    # 不傳 narrative：首頁照常產出、無「關於本專案」按鈕與 overlay
    index = build_site_archive(_days(("2026-06-25", "# 內容")))["index.html"]
    assert "本地 LLM 多代理自主系統" in index
    assert "<h1>內容</h1>" in index
    # 斷言 markup（非 CSS class 名/註解，後者恆在 <style> 內）：無 overlay 與按鈕
    assert '<div class="about-overlay">' not in index
    assert '<label for="about-toggle"' not in index
    assert 'id="about-toggle"' not in index


@pytest.mark.unit
def test_narrative_untrusted_html_still_sanitized():
    # 描述雖為手寫可信內容，仍走 _sanitize（一致渲染路徑、無害）
    n = Narrative(zh_md="壞 <script>alert(1)</script>", en_md="ok")
    index = build_site_archive(_days(("2026-06-25", "# r")), narrative=n)["index.html"]
    assert "<script>" not in index
    assert "alert(1)" not in index

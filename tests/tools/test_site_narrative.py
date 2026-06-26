"""雙語專案敘事（issue #8）— 純 builder 吃 in-memory Narrative，渲染中英兩版 + 切換。

純核心測試一律以記憶體 Narrative fixture 餵入，不碰檔案；薄 loader (load_narrative)
才碰 config 檔。對照 build_site_archive：無 git / LLM / 網路 / 檔案副作用。
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
def test_index_renders_both_zh_and_en_narrative():
    # AC4：中英兩版皆存在於 index 輸出
    index = build_site_archive(_days(("2026-06-25", "# r")), narrative=_NARRATIVE)[
        "index.html"
    ]
    assert "本地多代理系統的繁中敘事段落" in index
    assert "The English narrative paragraph here" in index


@pytest.mark.unit
def test_index_offers_en_zh_language_toggle():
    # AC2：提供 EN／中 切換（純 CSS radio toggle，無框架）
    index = build_site_archive(_days(("2026-06-25", "# r")), narrative=_NARRATIVE)[
        "index.html"
    ]
    # 兩個切換鈕的可見文字
    assert ">中</label>" in index
    assert ">EN</label>" in index
    # 純 CSS toggle 機制：兩個語言 radio + label for 綁定
    assert 'id="lang-zh"' in index
    assert 'id="lang-en"' in index
    assert 'for="lang-zh"' in index
    assert 'for="lang-en"' in index


@pytest.mark.unit
def test_index_renders_narrative_markdown_to_html():
    # 敘事走與 report 一致的 markdown→HTML 路徑（## → <h2>）
    index = build_site_archive(_days(("2026-06-25", "# r")), narrative=_NARRATIVE)[
        "index.html"
    ]
    assert "<h2>這是什麼</h2>" in index
    assert "<h2>What this is</h2>" in index


@pytest.mark.unit
def test_index_hero_shows_positioning_line_with_narrative():
    # AC3：hero 區顯著呈現定位句（敘事在場時仍在）
    index = build_site_archive(_days(("2026-06-25", "# r")), narrative=_NARRATIVE)[
        "index.html"
    ]
    assert "本地 LLM 多代理自主系統" in index


@pytest.mark.unit
def test_narrative_optional_backward_compatible():
    # 不傳 narrative：首頁照常產出、無敘事區（不回歸 #6/#7）
    index = build_site_archive(_days(("2026-06-25", "# 內容")))["index.html"]
    assert "本地 LLM 多代理自主系統" in index
    assert "<h1>內容</h1>" in index
    assert '<section class="narrative' not in index


@pytest.mark.unit
def test_narrative_untrusted_html_still_sanitized():
    # 敘事雖為手寫可信內容，仍走 _sanitize（一致渲染路徑、無害）
    n = Narrative(zh_md="壞 <script>alert(1)</script>", en_md="ok")
    index = build_site_archive(_days(("2026-06-25", "# r")), narrative=n)["index.html"]
    assert "<script>" not in index
    assert "alert(1)" not in index

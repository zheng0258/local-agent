"""links — URL 確定性替換與驗證（純函數）。

涵蓋：token 替換、未知 id 保留、非 http href 拆殼、合法 href 保留。
"""

import pytest

from agents.daily_brief.links import (
    href_token,
    is_valid_url,
    strip_invalid_anchors,
    strip_invalid_md_links,
    substitute_href_tokens,
    substitute_md_link_tokens,
)


@pytest.mark.unit
def test_href_token_format():
    assert href_token(3) == "@@3@@"


@pytest.mark.unit
@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://a.com", True),
        ("http://a.com", True),
        ("（原始 URL 未提供）", False),
        ("@@0@@", False),
        ("", False),
        (None, False),
    ],
)
def test_is_valid_url(url, ok):
    assert is_valid_url(url) is ok


@pytest.mark.unit
def test_substitute_replaces_token_with_url():
    html = '<a href="@@0@@">A</a> <a href="@@1@@">B</a>'
    out = substitute_href_tokens(html, {0: "https://a", 1: "https://b"})
    assert out == '<a href="https://a">A</a> <a href="https://b">B</a>'


@pytest.mark.unit
def test_substitute_leaves_unknown_id_untouched():
    # 未知 id 不替換，交由 strip_invalid_anchors 收尾
    html = '<a href="@@9@@">A</a>'
    assert substitute_href_tokens(html, {0: "https://a"}) == html


@pytest.mark.unit
def test_substitute_leaves_real_url_untouched():
    # LLM 若仍寫真實 URL（未照 token 規則）也不破壞
    html = '<a href="https://kept.example">A</a>'
    assert substitute_href_tokens(html, {0: "https://a"}) == html


@pytest.mark.unit
def test_strip_invalid_anchors_unwraps_non_http():
    html = '<b><a href="@@0@@">未替換</a></b> <a href="https://ok">保留</a>'
    cleaned, removed = strip_invalid_anchors(html)
    assert removed == 1
    assert cleaned == '<b>未替換</b> <a href="https://ok">保留</a>'


@pytest.mark.unit
def test_strip_invalid_anchors_keeps_all_valid():
    html = '<a href="https://a">A</a><a href="http://b">B</a>'
    cleaned, removed = strip_invalid_anchors(html)
    assert removed == 0
    assert cleaned == html


@pytest.mark.unit
def test_substitute_md_link_replaces_token():
    md = "1. [標題](@@0@@) — x"
    assert substitute_md_link_tokens(md, {0: "https://a"}) == "1. [標題](https://a) — x"


@pytest.mark.unit
def test_substitute_md_link_leaves_unknown_and_real_untouched():
    assert substitute_md_link_tokens("[A](@@9@@)", {0: "https://a"}) == "[A](@@9@@)"
    assert substitute_md_link_tokens("[A](https://k)", {0: "x"}) == "[A](https://k)"


@pytest.mark.unit
def test_strip_invalid_md_links_unwraps_non_http():
    md = "[死連結](#) 與 [未替換](@@0@@) 與 [好的](https://ok)"
    cleaned, removed = strip_invalid_md_links(md)
    assert removed == 2
    assert cleaned == "死連結 與 未替換 與 [好的](https://ok)"


@pytest.mark.unit
def test_substitute_md_link_handles_brackets_inside_title():
    # 09-24 / 09-28 實例：標題自帶 [已修復] / [預覽]，舊正則跨不過內層 ]，token 原樣上站
    md = "2. [Claude Code 讀取 AGENTS.md [已修復]](@@3@@) (374pt)"
    assert (
        substitute_md_link_tokens(md, {3: "https://a"})
        == "2. [Claude Code 讀取 AGENTS.md [已修復]](https://a) (374pt)"
    )
    assert (
        substitute_md_link_tokens("| [[預覽] AWS Agent](@@1@@) | 32 |", {1: "https://b"})
        == "| [[預覽] AWS Agent](https://b) | 32 |"
    )


@pytest.mark.unit
def test_substitute_md_link_repairs_missing_open_bracket():
    # 10-16 實例：LLM 漏寫開頭 [，只剩 標題](@@10@@)
    md = "11. 【Mac Info】Safari 擴充功能](@@10@@) (19 users) — x"
    assert (
        substitute_md_link_tokens(md, {10: "https://m"})
        == "11. [【Mac Info】Safari 擴充功能](https://m) (19 users) — x"
    )
    assert (
        substitute_md_link_tokens("| 標題](@@1@@) | 32 |", {1: "https://t"})
        == "| [標題](https://t) | 32 |"
    )
    assert substitute_md_link_tokens("- 標題](@@1@@)", {1: "https://t"}) == "- [標題](https://t)"


@pytest.mark.unit
def test_strip_invalid_md_links_unwraps_nested_bracket_title():
    cleaned, removed = strip_invalid_md_links("[Claude [已修復]](@@3@@) 尾")
    assert removed == 1
    assert cleaned == "Claude [已修復] 尾"


@pytest.mark.unit
def test_strip_invalid_md_links_removes_orphan_tokens():
    # 任何殘留 token 都不得上站：孤立的 ](@@N@@) 與裸 @@N@@ 一律清掉並計數
    cleaned, removed = strip_invalid_md_links("句中 標題](@@4@@) 與 @@5@@ 結尾")
    assert removed == 2
    assert "@@" not in cleaned
    assert cleaned == "句中 標題 與  結尾"

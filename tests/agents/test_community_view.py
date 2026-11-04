"""community_view — 「💬 社群觀點」由程式依 comment_summary 組裝的純函數測試。

10-19 起 digest LLM 編造社群觀點、外洩佔位字、貼錯文章；社群觀點是資料不是 LLM 輸出。
"""

import pytest

from agents.daily_brief.community_view import (
    attach_community_view,
    comments_by_url,
    reconcile_report_views,
    strip_community_view,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "written",
    [
        "摘要。\n💬 社群觀點：編造的看法",
        "摘要。\n社群觀點：編造的看法",
        "摘要。\n💬 社群觀點: 編造的看法",
        "摘要。\n**💬 社群觀點**：編造的看法",
        "摘要。\n💬 社群觀點：[comment_summary 的內容]",
        "摘要。 💬 社群觀點：同一行的編造",
    ],
)
def test_strip_removes_every_llm_written_form(written):
    assert strip_community_view(written) == "摘要。"


def test_strip_keeps_text_without_marker():
    text = "第一行\n第二行提到社群觀點但沒有冒號"
    assert strip_community_view(text) == text


def test_attach_replaces_llm_view_with_real_comment():
    out = attach_community_view("摘要。\n💬 社群觀點：編造", "真實留言摘要")
    assert out == "摘要。\n💬 社群觀點：真實留言摘要"


def test_attach_without_comment_only_strips():
    assert attach_community_view("摘要。\n💬 社群觀點：編造", "") == "摘要。"


def test_comments_by_url_collects_across_sources_and_skips_meta():
    enrich = {
        "_meta": {"x": 1},
        "hn": {"articles": [{"url": "u1", "comment_summary": "c1"}, {"url": "u2"}]},
        "reddit": {"articles": [{"url": "u3", "comment_summary": "c3"}]},
    }
    assert comments_by_url(enrich) == {"u1": "c1", "u3": "c3"}


_REPORT = """\
## Hacker News

| 標題 | 分數 |
|------|------|
| [甲](https://a.example/1) | 10pt |

1. [甲](https://a.example/1) (10pt) — 摘要甲
   💬 社群觀點：貼錯的看法
2. [乙](https://a.example/2) (5pt) — 摘要乙
   💬 社群觀點：編造的看法
3. [丙](https://a.example/3) (3pt) — 摘要丙

## 今日總結
"""


def test_reconcile_report_puts_real_view_under_its_own_article():
    out = reconcile_report_views(
        _REPORT, {"https://a.example/1": "甲的真實留言", "https://a.example/3": "丙的真實留言"}
    )
    lines = out.splitlines()
    assert lines[lines.index("1. [甲](https://a.example/1) (10pt) — 摘要甲") + 1] == (
        "   💬 社群觀點：甲的真實留言"
    )
    assert lines[lines.index("3. [丙](https://a.example/3) (3pt) — 摘要丙") + 1] == (
        "   💬 社群觀點：丙的真實留言"
    )
    assert "編造的看法" not in out
    assert "貼錯的看法" not in out


def test_reconcile_report_never_touches_table_rows_and_inserts_once():
    report = (
        "| [甲](https://a.example/1) | 社群觀點：表格備註 |\n"
        "1. [甲](https://a.example/1) — 第一次\n"
        "- [甲](https://a.example/1) — 第二次\n"
    )
    out = reconcile_report_views(report, {"https://a.example/1": "真實"})
    assert out.count("💬 社群觀點：真實") == 1
    assert "| 社群觀點：表格備註 |" in out
    assert out.splitlines()[2] == "   💬 社群觀點：真實"


def test_reconcile_report_is_idempotent():
    comments = {"https://a.example/1": "甲的真實留言"}
    once = reconcile_report_views(_REPORT, comments)
    assert reconcile_report_views(once, comments) == once


def test_reconcile_report_preserves_trailing_newline():
    assert reconcile_report_views("# 標題\n", {}) == "# 標題\n"
    assert reconcile_report_views("# 標題", {}) == "# 標題"

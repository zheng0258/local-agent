"""report_repair — report.md 連結的確定性修復（token 重替換 + 標題比對補連結）。"""

import json

import pytest

from agents.daily_brief.invariants import check_report
from agents.daily_brief.report_repair import load_link_sources, relink_report

pytestmark = pytest.mark.unit

# id 枚舉與 ReportStep 相同：enrich 全來源文章依序 → 去重後 digests 中的新 URL
_ENRICH = {
    "_meta": {"enriched_at": "x"},
    "hatena": {
        "articles": [
            {"title": "漢堡王 App 會員資訊外洩 | NHK 新聞", "url": "https://a.example/0"},
            {"title": "源ネクスト網站遭非法存取", "url": "https://a.example/1"},
        ]
    },
    "hn": {
        "articles": [
            {
                "title": "核心漏洞利用程式",
                "original_title": "Wanted to download an ISO",
                "url": "https://a.example/2",
            },
            {"title": "重複標題", "url": "https://a.example/3"},
            {"title": "重複標題", "url": "https://a.example/4"},
        ]
    },
}
_DIGESTS = [
    {"title": "漢堡王 App 會員資訊外洩 | NHK 新聞", "url": "https://a.example/0"},
    {"title": "只在 digest 的文章", "url": "https://a.example/5"},
]


def test_substitutes_leftover_tokens_with_same_enumeration():
    md = "1. [源ネクスト網站遭非法存取](@@1@@) (98 users) — x\n"
    fixed = relink_report(md, _ENRICH, _DIGESTS)
    assert fixed == "1. [源ネクスト網站遭非法存取](https://a.example/1) (98 users) — x\n"


def test_digest_only_url_gets_id_after_enrich():
    md = "- [只在 digest 的文章](@@5@@) (3 ups) — y\n"
    assert "https://a.example/5" in relink_report(md, _ENRICH, _DIGESTS)


def test_repairs_missing_open_bracket_token():
    md = "1. 核心漏洞利用程式](@@2@@) (289pt) — z\n"
    fixed = relink_report(md, _ENRICH, _DIGESTS)
    assert "[核心漏洞利用程式](https://a.example/2)" in fixed
    assert check_report(fixed) == ()


def test_title_match_relinks_degraded_plain_row():
    md = "2. 源ネクスト網站遭非法存取 (98 users) — 已被降級成純文字\n"
    fixed = relink_report(md, _ENRICH, _DIGESTS)
    assert fixed == (
        "2. [源ネクスト網站遭非法存取](https://a.example/1) (98 users) — 已被降級成純文字\n"
    )


def test_title_match_handles_pipe_in_title_and_original_title():
    md = (
        "1. 漢堡王 App 會員資訊外洩 | NHK 新聞 (269 users) — a\n"
        "2. Wanted to download an ISO (289pt) — b\n"
    )
    fixed = relink_report(md, _ENRICH, _DIGESTS)
    assert "[漢堡王 App 會員資訊外洩 | NHK 新聞](https://a.example/0)" in fixed
    assert "[Wanted to download an ISO](https://a.example/2)" in fixed


def test_title_match_table_row():
    md = "| 源ネクスト網站遭非法存取 (98 users) | 98 | *** |\n"
    fixed = relink_report(md, _ENRICH, _DIGESTS)
    assert "[源ネクスト網站遭非法存取](https://a.example/1)" in fixed


def test_ambiguous_title_left_alone():
    md = "3. 重複標題 (10pt) — 兩篇同名，不猜\n"
    assert relink_report(md, _ENRICH, _DIGESTS) == md


def test_unknown_title_left_alone():
    md = "3. 完全沒見過的標題 (10pt) — x\n"
    assert relink_report(md, _ENRICH, _DIGESTS) == md


def test_unknown_token_is_stripped_not_left_on_site():
    md = "1. [怪東西](@@99@@) (5 users) — x\n"
    fixed = relink_report(md, _ENRICH, _DIGESTS)
    assert "@@" not in fixed


def test_linked_rows_untouched():
    md = "1. [源ネクスト網站遭非法存取](https://a.example/1) (98 users) — x\n"
    assert relink_report(md, _ENRICH, _DIGESTS) == md


def test_load_link_sources_reads_artifacts(tmp_path):
    (tmp_path / "enrich.json").write_text(json.dumps(_ENRICH), encoding="utf-8")
    (tmp_path / "digest.json").write_text(
        json.dumps({"generated_at": "x", "digests": _DIGESTS}), encoding="utf-8"
    )
    enrich, digests = load_link_sources(tmp_path)
    assert enrich == _ENRICH and digests == _DIGESTS


def test_load_link_sources_missing_returns_none(tmp_path):
    assert load_link_sources(tmp_path) is None

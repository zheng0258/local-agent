"""SourceStep._score — live 評分路徑（Phase 2）的韌性特徵測試。

score 邏輯已從 God object 移入 SourceStep；用 FakeLLM 注入 canned 回應直接驅動 _score。
「LLM 回傳錯 key」的韌性留在這裡；「非 JSON → raise」由 supervisor.run_step 負責。
"""

import json
from types import SimpleNamespace

import pytest

from agents.daily_brief.steps.source import SourceStep
from tests.fakes import FakeLLM


def _score(name: str, raw: list, llm_response: str) -> dict:
    ctx = SimpleNamespace(llm=FakeLLM(default=llm_response))
    return SourceStep(name)._score(ctx, name, raw)


@pytest.mark.unit
@pytest.mark.parametrize(
    "name,article",
    [
        ("hatena", {"title": "A", "url": "https://x.com", "bookmarks": 200, "interest": "***"}),
        ("hn", {"title": "B", "url": "https://hn.com/item?id=1", "score": 300, "interest": "***"}),
        ("security", {"title": "D", "url": "https://aikido.dev/x", "source": "aikido.dev", "interest": "***"}),
    ],
)
def test_correct_key_returns_articles(name: str, article: dict) -> None:
    result = _score(name, [], f"```json\n{json.dumps({'articles': [article]})}\n```")
    assert len(result["articles"]) == 1


@pytest.mark.unit
@pytest.mark.parametrize("name", ["hatena", "hn", "reddit", "security", "rss"])
def test_wrong_key_returns_empty_not_crash(name: str) -> None:
    result = _score(name, [], json.dumps({"wrong_key": []}))
    assert result.get("articles", []) == []


@pytest.mark.unit
def test_score_attaches_original_title_by_url() -> None:
    """LLM 評分會把 title 翻成繁中；artifact 條目須保留 fetch 階段原始 title（URL 對齊）。"""
    scored = {
        "articles": [
            {
                "title": "繁中翻譯標題",
                "url": "https://x.com/post",
                "bookmarks": 200,
                "interest": "***",
            }
        ]
    }
    raw = [
        {
            "title": "Original Raw Title",
            "url": "https://x.com/post",
            "bookmarks": 200,
            "description": "raw description text",
        }
    ]
    result = _score("hatena", raw, json.dumps(scored, ensure_ascii=False))
    article = result["articles"][0]
    assert article["original_title"] == "Original Raw Title"
    assert article["original_description"] == "raw description text"
    assert article["title"] == "繁中翻譯標題"  # 既有欄位不動（on-disk schema 只加不改）


@pytest.mark.unit
def test_score_attaches_original_title_via_hn_url() -> None:
    """HN scored artifact 的 url 是 hn_url（討論串），須以 raw 的 hn_url 對齊原始 title。"""
    scored = {
        "articles": [
            {
                "title": "繁中翻譯標題",
                "url": "https://news.ycombinator.com/item?id=1",
                "score": 300,
                "interest": "***",
            }
        ]
    }
    raw = [
        {
            "title": "Original HN Title",
            "url": "https://orig.example.com/post",
            "hn_url": "https://news.ycombinator.com/item?id=1",
            "score": 300,
            "comments": 12,
        }
    ]
    result = _score("hn", raw, json.dumps(scored, ensure_ascii=False))
    assert result["articles"][0]["original_title"] == "Original HN Title"


@pytest.mark.unit
def test_score_without_raw_match_leaves_article_intact() -> None:
    """raw 中找不到對應 URL（LLM 改寫 url 等）時不 crash，條目維持原樣。"""
    scored = {
        "articles": [
            {
                "title": "T",
                "url": "https://unmatched.example.com",
                "score": 10,
                "interest": "***",
            }
        ]
    }
    result = _score(
        "hn",
        [{"title": "X", "url": "https://other.com"}],
        json.dumps(scored, ensure_ascii=False),
    )
    article = result["articles"][0]
    assert article["url"] == "https://unmatched.example.com"
    assert "original_title" not in article

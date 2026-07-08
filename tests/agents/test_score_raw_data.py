"""_score_raw_data — live 評分路徑（Phase 2）的韌性特徵測試。

取代已刪除的 _fetch_* 測試：score 函數內對「LLM 回傳錯 key」的韌性留在這裡；
「非 JSON → raise」的韌性由 supervisor.run_step 的 catch-retry 負責（見 test_supervisor）。
"""

import json
from unittest.mock import MagicMock

import pytest


def _agent_with(llm_response: str):
    from agents.daily_brief.agent import DailyBriefAgent

    llm = MagicMock()
    llm.complete.return_value = llm_response
    return DailyBriefAgent(llm=llm)


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
    agent = _agent_with(f"```json\n{json.dumps({'articles': [article]})}\n```")
    result = agent._score_raw_data(name, [])
    assert len(result["articles"]) == 1


@pytest.mark.unit
@pytest.mark.parametrize("name", ["hatena", "hn", "reddit", "security", "rss"])
def test_wrong_key_returns_empty_not_crash(name: str) -> None:
    agent = _agent_with(json.dumps({"wrong_key": []}))
    result = agent._score_raw_data(name, [])
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
    agent = _agent_with(json.dumps(scored, ensure_ascii=False))
    raw = [
        {
            "title": "Original Raw Title",
            "url": "https://x.com/post",
            "bookmarks": 200,
            "description": "raw description text",
        }
    ]
    result = agent._score_raw_data("hatena", raw)
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
    agent = _agent_with(json.dumps(scored, ensure_ascii=False))
    raw = [
        {
            "title": "Original HN Title",
            "url": "https://orig.example.com/post",
            "hn_url": "https://news.ycombinator.com/item?id=1",
            "score": 300,
            "comments": 12,
        }
    ]
    result = agent._score_raw_data("hn", raw)
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
    agent = _agent_with(json.dumps(scored, ensure_ascii=False))
    result = agent._score_raw_data("hn", [{"title": "X", "url": "https://other.com"}])
    article = result["articles"][0]
    assert article["url"] == "https://unmatched.example.com"
    assert "original_title" not in article

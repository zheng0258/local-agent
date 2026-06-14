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

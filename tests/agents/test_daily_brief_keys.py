"""
DailyBriefAgent — prompt key 驗證測試。

測試重點：
  _fetch_* 方法沿用新版 schema（articles），
  且 LLM 回傳錯誤 key 或非 JSON 時，agent 不崩潰。
"""

import json
from unittest.mock import MagicMock


# ── 共用 fixture ─────────────────────────────────────────────────

def _make_agent(llm_response: str):
    """建立一個 LLM 永遠回傳固定字串的 DailyBriefAgent。"""
    from agents.daily_brief.agent import DailyBriefAgent
    mock_llm = MagicMock()
    mock_llm.complete.return_value = llm_response
    return DailyBriefAgent(llm=mock_llm)


def _make_fetcher(data):
    """建立一個 fetch() 永遠回傳固定資料的 mock fetcher module。"""
    mod = MagicMock()
    mod.fetch.return_value = data
    return mod


# ── Hatena ───────────────────────────────────────────────────────

class TestFetchHatena:

    def test_correct_key_returns_articles(self):
        """LLM 回傳新版 articles key。"""
        response = json.dumps({
            "articles": [{"title": "A", "url": "https://x.com", "bookmarks": 200, "interest": "***"}]
        })
        agent = _make_agent(f"```json\n{response}\n```")
        result = agent._fetch_hatena(_make_fetcher([]))
        assert "articles" in result
        assert len(result["articles"]) == 1

    def test_wrong_key_returns_empty_not_crash(self):
        """LLM 回傳錯誤 key → agent 不崩潰，取出空 list。"""
        response = json.dumps({"wrong_key": []})
        agent = _make_agent(f"```json\n{response}\n```")
        result = agent._fetch_hatena(_make_fetcher([]))
        articles = result.get("articles", [])
        assert isinstance(articles, list)
        assert len(articles) == 0

    def test_non_json_response_returns_raw_not_crash(self):
        """LLM 回傳非 JSON → agent 不崩潰。"""
        agent = _make_agent("無法處理這個請求")
        result = agent._fetch_hatena(_make_fetcher([]))
        assert isinstance(result, dict)


# ── HN ──────────────────────────────────────────────────────────

class TestFetchHN:

    def test_correct_key_returns_articles(self):
        response = json.dumps({
            "articles": [{"title": "B", "url": "https://hn.com/item?id=1", "score": 300, "interest": "***"}]
        })
        agent = _make_agent(f"```json\n{response}\n```")
        result = agent._fetch_hn(_make_fetcher([]))
        assert "articles" in result
        assert len(result["articles"]) == 1

    def test_wrong_key_returns_empty_not_crash(self):
        agent = _make_agent(json.dumps({"bad_key": []}))
        result = agent._fetch_hn(_make_fetcher([]))
        assert isinstance(result.get("articles", []), list)

    def test_non_json_response_not_crash(self):
        agent = _make_agent("error occurred")
        result = agent._fetch_hn(_make_fetcher([]))
        assert isinstance(result, dict)


# ── Reddit ──────────────────────────────────────────────────────

class TestFetchReddit:

    def test_correct_key_returns_articles(self):
        response = json.dumps({
            "articles": {"AI 類": [{"title": "C", "url": "https://reddit.com/r/ai/1", "score": 400}]}
        })
        agent = _make_agent(f"```json\n{response}\n```")
        result = agent._fetch_reddit(_make_fetcher({}))
        assert "articles" in result

    def test_wrong_key_not_crash(self):
        agent = _make_agent(json.dumps({"nope": {}}))
        result = agent._fetch_reddit(_make_fetcher({}))
        assert isinstance(result, dict)


# ── Security ────────────────────────────────────────────────────

class TestFetchSecurity:

    def test_correct_key_returns_articles(self):
        response = json.dumps({
            "articles": [{"title": "D", "url": "https://aikido.dev/blog/x", "source": "aikido.dev", "interest": "***"}]
        })
        agent = _make_agent(f"```json\n{response}\n```")
        result = agent._fetch_security(_make_fetcher([]))
        assert "articles" in result
        assert len(result["articles"]) == 1

    def test_wrong_key_not_crash(self):
        agent = _make_agent(json.dumps({"wrong": []}))
        result = agent._fetch_security(_make_fetcher([]))
        assert isinstance(result, dict)


# ── 舊欄位清理 ────────────────────────────────────────────────────

class TestLegacyDigestKeyRemoved:

    def test_legacy_all_digests_append_not_required(self):
        """新版 fetch schema 不依賴 all_digests_append。"""
        response = json.dumps({"articles": []})
        agent = _make_agent(f"```json\n{response}\n```")
        result = agent._fetch_hatena(_make_fetcher([]))
        assert "all_digests_append" not in result

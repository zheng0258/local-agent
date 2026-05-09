# tests/tw_stock/test_agent.py
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_agent(llm_response: str = "{}") -> "TwStockAgent":
    from agents.tw_stock.agent import TwStockAgent
    mock_llm = MagicMock()
    mock_llm.complete.return_value = llm_response
    return TwStockAgent(llm=mock_llm)


def test_all_steps_in_correct_order():
    from agents.tw_stock.config import ALL_STEPS
    steps = list(ALL_STEPS)
    assert steps.index("news") < steps.index("sentiment")
    assert steps.index("sentiment") < steps.index("market_data")
    assert steps.index("market_data") < steps.index("technical")
    assert steps.index("technical") < steps.index("signal")
    assert steps.index("signal") < steps.index("paper_trade")
    assert steps.index("paper_trade") < steps.index("pnl")
    assert steps.index("pnl") < steps.index("notify")


def test_agent_name():
    from agents.tw_stock.agent import TwStockAgent
    assert TwStockAgent.AGENT_NAME == "tw-stock"


def test_phase_news_loads_artifact_if_exists(tmp_path):
    from agents.tw_stock.agent import TwStockAgent
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()
    cached = {"articles": [{"title": "cached", "url": "http://x"}], "fetched_at": "2026-05-08T08:00:00"}
    (steps_dir / "news.json").write_text(json.dumps(cached), encoding="utf-8")

    agent = _make_agent()
    result = agent._phase_news(steps_dir, force_steps=set(), only_steps={"news"}, today="2026-05-08")
    assert result["articles"][0]["title"] == "cached"


def test_phase_news_skips_if_not_in_only_steps(tmp_path):
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()

    agent = _make_agent()
    result = agent._phase_news(steps_dir, force_steps=set(), only_steps={"sentiment"}, today="2026-05-08")
    assert result == {"articles": []}


def test_phase_sentiment_returns_neutral_when_no_articles(tmp_path):
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()

    agent = _make_agent('{"overall": "neutral", "score": 0.5}')
    result = agent._phase_sentiment(
        steps_dir, force_steps=set(), only_steps={"sentiment"},
        news_data={"articles": []},
    )
    assert result["overall"] == "neutral"


def test_phase_sentiment_calls_llm_with_articles(tmp_path):
    from agents.tw_stock.agent import TwStockAgent
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()

    mock_llm = MagicMock()
    mock_llm.complete.return_value = json.dumps({
        "overall": "bullish", "score": 0.7,
        "sector_signals": {}, "bearish_sectors": [],
    })
    agent = TwStockAgent(llm=mock_llm)

    news = {"articles": [{"title": "台積電大漲", "source": "鉅亨"}]}
    result = agent._phase_sentiment(
        steps_dir, force_steps=set(), only_steps={"sentiment"},
        news_data=news,
    )
    assert result["overall"] == "bullish"
    mock_llm.complete.assert_called_once()


def test_parse_args_force():
    from agents.tw_stock.agent import _parse_args
    force, only = _parse_args("--force news sentiment")
    assert force == {"news", "sentiment"}
    assert only == set()


def test_parse_args_only():
    from agents.tw_stock.agent import _parse_args
    force, only = _parse_args("--only pnl notify")
    assert force == set()
    assert only == {"pnl", "notify"}


def test_parse_args_empty():
    from agents.tw_stock.agent import _parse_args
    force, only = _parse_args("")
    assert force == set()
    assert only == set()


def test_phase_news_force_bypasses_existing_artifact(tmp_path):
    from agents.tw_stock.agent import TwStockAgent
    import json as _json
    from unittest.mock import patch, MagicMock

    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()
    cached = {"articles": [{"title": "old", "url": "http://old"}], "fetched_at": "2026-05-08T07:00:00"}
    (steps_dir / "news.json").write_text(_json.dumps(cached), encoding="utf-8")

    mock_llm = MagicMock()
    agent = TwStockAgent(llm=mock_llm)

    new_articles = [{"title": "new", "url": "http://new", "source": "鉅亨",
                     "published_at": "2026-05-09T08:00:00", "description": "新新聞"}]
    with patch("tools.fetchers.tw_news.fetch", return_value=new_articles):
        result = agent._phase_news(steps_dir, force_steps={"news"}, only_steps={"news"}, today="2026-05-09")

    assert result["articles"][0]["title"] == "new"

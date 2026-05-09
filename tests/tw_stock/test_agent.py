# tests/tw_stock/test_agent.py
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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


def test_main_routes_tw_stock():
    from main import route
    from agents.tw_stock.agent import TwStockAgent
    agent_cls, remaining = route("/tw-stock")
    assert agent_cls is TwStockAgent
    assert remaining == ""


def test_main_routes_tw_stock_with_force():
    from main import route
    from agents.tw_stock.agent import TwStockAgent
    agent_cls, remaining = route("/tw-stock --force news")
    assert agent_cls is TwStockAgent
    assert "--force news" in remaining


# ── Init tests ────────────────────────────────────────────────────


def test_phase_init_generates_template_when_no_init_file(tmp_path):
    from agents.tw_stock.agent import TwStockAgent
    from unittest.mock import patch

    agent = _make_agent()
    with patch("agents.tw_stock.agent.DATA_DIR", tmp_path), \
         patch("agents.tw_stock.agent.INIT_FILE", tmp_path / "init.json"), \
         patch("agents.tw_stock.agent.POSITIONS_FILE", tmp_path / "positions.json"), \
         patch("agents.tw_stock.agent.PNL_HISTORY_FILE", tmp_path / "pnl_history.json"):
        result = agent._phase_init()

    assert "範本" in result
    assert (tmp_path / "init.json").exists()
    template = json.loads((tmp_path / "init.json").read_text(encoding="utf-8"))
    assert "cash" in template
    assert "positions" in template
    assert "past_trades" in template


def test_phase_init_converts_positions_and_writes_files(tmp_path):
    from agents.tw_stock.agent import TwStockAgent
    from unittest.mock import patch

    init_data = {
        "cash": 500_000,
        "positions": [
            {
                "ticker": "2330",
                "entry_price": 900.0,
                "lots": 1,
                "stop_loss": 880.0,
                "take_profit": 950.0,
                "entry_date": "2026-05-01",
            }
        ],
        "past_trades": [],
    }
    init_file = tmp_path / "init.json"
    init_file.write_text(json.dumps(init_data), encoding="utf-8")

    agent = _make_agent()
    positions_file = tmp_path / "positions.json"
    pnl_file = tmp_path / "pnl_history.json"

    with patch("agents.tw_stock.agent.DATA_DIR", tmp_path), \
         patch("agents.tw_stock.agent.INIT_FILE", init_file), \
         patch("agents.tw_stock.agent.POSITIONS_FILE", positions_file), \
         patch("agents.tw_stock.agent.PNL_HISTORY_FILE", pnl_file):
        result = agent._phase_init()

    assert "✅" in result
    state = json.loads(positions_file.read_text(encoding="utf-8"))
    assert "2330" in state["positions"]
    assert state["positions"]["2330"]["shares"] == 1000
    assert state["positions"]["2330"]["stop_loss"] == 880.0
    assert state["cash"] == 500_000
    assert state["portfolio_value"] == pytest.approx(500_000 + 900 * 1000, abs=1)


def test_phase_init_computes_pnl_history_from_past_trades(tmp_path):
    import pytest
    from agents.tw_stock.agent import TwStockAgent
    from unittest.mock import patch

    init_data = {
        "cash": 1_000_000,
        "positions": [],
        "past_trades": [
            {
                "ticker": "2454",
                "entry_price": 1000.0,
                "exit_price": 1050.0,
                "lots": 1,
                "entry_date": "2026-04-28",
                "exit_date": "2026-05-03",
                "reason": "take_profit",
            },
            {
                "ticker": "2317",
                "entry_price": 200.0,
                "exit_price": 190.0,
                "lots": 2,
                "entry_date": "2026-04-25",
                "exit_date": "2026-05-02",
                "reason": "stop_loss",
            },
        ],
    }
    init_file = tmp_path / "init.json"
    init_file.write_text(json.dumps(init_data), encoding="utf-8")

    agent = _make_agent()
    positions_file = tmp_path / "positions.json"
    pnl_file = tmp_path / "pnl_history.json"

    with patch("agents.tw_stock.agent.DATA_DIR", tmp_path), \
         patch("agents.tw_stock.agent.INIT_FILE", init_file), \
         patch("agents.tw_stock.agent.POSITIONS_FILE", positions_file), \
         patch("agents.tw_stock.agent.PNL_HISTORY_FILE", pnl_file):
        result = agent._phase_init()

    assert "✅" in result
    history = json.loads(pnl_file.read_text(encoding="utf-8"))
    assert len(history) == 1
    entry = history[0]
    assert entry["total_trades"] == 2
    assert entry["win_rate"] == pytest.approx(0.5, abs=0.01)
    # 2454: +50*1000=+50000, 2317: -10*2000=-20000 → net +30000
    assert entry["daily_pnl_twd"] == pytest.approx(30_000, abs=1)


def test_phase_init_uses_default_stop_take_when_omitted(tmp_path):
    from agents.tw_stock.agent import TwStockAgent
    from unittest.mock import patch

    init_data = {
        "cash": 1_000_000,
        "positions": [
            {"ticker": "2330", "entry_price": 1000.0, "lots": 1, "entry_date": "2026-05-01"}
        ],
        "past_trades": [],
    }
    init_file = tmp_path / "init.json"
    init_file.write_text(json.dumps(init_data), encoding="utf-8")

    agent = _make_agent()
    positions_file = tmp_path / "positions.json"
    pnl_file = tmp_path / "pnl_history.json"

    with patch("agents.tw_stock.agent.DATA_DIR", tmp_path), \
         patch("agents.tw_stock.agent.INIT_FILE", init_file), \
         patch("agents.tw_stock.agent.POSITIONS_FILE", positions_file), \
         patch("agents.tw_stock.agent.PNL_HISTORY_FILE", pnl_file):
        agent._phase_init()

    state = json.loads(positions_file.read_text(encoding="utf-8"))
    pos = state["positions"]["2330"]
    assert pos["stop_loss"] == pytest.approx(950.0, abs=0.01)   # 1000 * 0.95
    assert pos["take_profit"] == pytest.approx(1100.0, abs=0.01)  # 1000 * 1.10

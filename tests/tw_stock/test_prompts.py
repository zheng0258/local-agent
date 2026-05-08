# tests/tw_stock/test_prompts.py


def test_build_sentiment_prompt_contains_articles_json():
    from agents.tw_stock.prompts import build_sentiment_prompt
    articles_json = '[{"title": "台積電大漲", "source": "鉅亨"}]'
    prompt = build_sentiment_prompt(articles_json)
    assert "台積電大漲" in prompt
    assert "bullish" in prompt


def test_build_sentiment_prompt_requests_json_output():
    from agents.tw_stock.prompts import build_sentiment_prompt
    prompt = build_sentiment_prompt("[]")
    assert "overall" in prompt
    assert "score" in prompt
    assert "sector_signals" in prompt


def test_build_notify_signal_prompt_contains_date():
    from agents.tw_stock.prompts import build_notify_signal_prompt
    prompt = build_notify_signal_prompt("2026-05-08", "[]", '{"overall": "bullish"}')
    assert "2026-05-08" in prompt


def test_build_notify_pnl_prompt_contains_portfolio():
    from agents.tw_stock.prompts import build_notify_pnl_prompt
    pnl_json = '{"portfolio_value": 1031200, "total_return_pct": 3.12}'
    prompt = build_notify_pnl_prompt("2026-05-08", pnl_json, '{"positions": {}}')
    assert "1031200" in prompt


def test_system_is_nonempty_string():
    from agents.tw_stock.prompts import SYSTEM
    assert isinstance(SYSTEM, str)
    assert len(SYSTEM) > 10

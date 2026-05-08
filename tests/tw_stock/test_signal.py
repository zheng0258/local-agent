# tests/tw_stock/test_signal.py
import pytest
import pandas as pd


def test_bullish_r2_gives_buy_full_confidence():
    from agents.tw_stock.signal import apply_sentiment_filter
    result = apply_sentiment_filter("R2", "bullish", 0.41)
    assert result["direction"] == "BUY"
    assert result["confidence_mult"] == pytest.approx(1.0)


def test_bullish_r3_gives_buy_full_confidence():
    from agents.tw_stock.signal import apply_sentiment_filter
    result = apply_sentiment_filter("R3", "bullish", 0.50)
    assert result["direction"] == "BUY"
    assert result["confidence_mult"] == pytest.approx(1.0)


def test_bullish_r1_gives_weak_buy():
    from agents.tw_stock.signal import apply_sentiment_filter
    result = apply_sentiment_filter("R1", "bullish", 0.41)
    assert result["direction"] == "BUY"
    assert result["confidence_mult"] == pytest.approx(0.7)


def test_bullish_bearish_signal_skipped():
    from agents.tw_stock.signal import apply_sentiment_filter
    result = apply_sentiment_filter("S", "bullish", 0.50)
    assert result["direction"] is None


def test_bullish_f0_skipped():
    from agents.tw_stock.signal import apply_sentiment_filter
    result = apply_sentiment_filter("F0", "bullish", 0.30)
    assert result["direction"] is None


def test_bearish_s_gives_watch():
    from agents.tw_stock.signal import apply_sentiment_filter
    result = apply_sentiment_filter("S", "bearish", 0.35)
    assert result["direction"] == "WATCH"
    assert result["confidence_mult"] == pytest.approx(1.0)


def test_bearish_r2_skipped():
    from agents.tw_stock.signal import apply_sentiment_filter
    result = apply_sentiment_filter("R2", "bearish", 0.50)
    assert result["direction"] is None


def test_neutral_gives_reduced_confidence():
    from agents.tw_stock.signal import apply_sentiment_filter
    result = apply_sentiment_filter("R2", "neutral", 0.50)
    assert result["direction"] == "BUY"
    assert result["confidence_mult"] == pytest.approx(0.8)


def test_cross_stock_centrality_returns_all_tickers():
    from agents.tw_stock.signal import compute_cross_stock_centrality
    returns = pd.DataFrame({
        "A": [0.01, 0.02, -0.01, 0.03, 0.01],
        "B": [0.01, 0.02, -0.01, 0.03, 0.01],
        "C": [-0.02, -0.01, 0.02, -0.01, -0.02],
    })
    centrality = compute_cross_stock_centrality(returns)
    assert set(centrality.keys()) == {"A", "B", "C"}


def test_cross_stock_centrality_normalized_0_to_1():
    from agents.tw_stock.signal import compute_cross_stock_centrality
    returns = pd.DataFrame({
        "A": [0.01, 0.02, -0.01, 0.03],
        "B": [0.01, 0.02, -0.01, 0.03],
        "C": [-0.02, -0.01, 0.02, -0.01],
    })
    centrality = compute_cross_stock_centrality(returns)
    for v in centrality.values():
        assert 0.0 <= v <= 1.0


def test_cross_stock_centrality_no_edges_returns_zeros():
    from agents.tw_stock.signal import compute_cross_stock_centrality
    returns = pd.DataFrame({
        "A": [0.0] * 10,
        "B": [0.0] * 10,
    })
    centrality = compute_cross_stock_centrality(returns, threshold=0.9)
    assert all(v == 0.0 for v in centrality.values())


def test_txf_signal_below_threshold_returns_none():
    from agents.tw_stock.signal import compute_txf_signal
    result = compute_txf_signal(sentiment_score=0.51, bluechip_bull_ratio=0.52)
    assert result is None


def test_txf_signal_bullish():
    from agents.tw_stock.signal import compute_txf_signal
    result = compute_txf_signal(sentiment_score=0.80, bluechip_bull_ratio=0.80)
    assert result is not None
    assert result["direction"] == "LONG"
    assert result["final_score"] > 0.2


def test_txf_signal_bearish():
    from agents.tw_stock.signal import compute_txf_signal
    result = compute_txf_signal(sentiment_score=0.20, bluechip_bull_ratio=0.20)
    assert result is not None
    assert result["direction"] == "SHORT"


def test_build_signals_skips_below_threshold():
    from agents.tw_stock.signal import build_signals
    sentiment = {"overall": "bullish", "score": 0.65}
    technical = {
        "2330": {
            "most_likely": "S", "confidence": 0.50,
            "signal": {"stop_loss": 880.0, "take_profit": 950.0, "strength": "Strong"},
        },
    }
    centrality = {"2330": 0.5}
    signals = build_signals(sentiment, technical, centrality)
    tickers = [s["ticker"] for s in signals]
    assert "2330" not in tickers


def test_build_signals_buy_signal_has_required_fields():
    from agents.tw_stock.signal import build_signals
    sentiment = {"overall": "bullish", "score": 0.65}
    technical = {
        "2330": {
            "most_likely": "R2", "confidence": 0.41,
            "signal": {"stop_loss": 885.0, "take_profit": 950.0, "strength": "Strong"},
        },
    }
    centrality = {"2330": 0.5}
    signals = build_signals(sentiment, technical, centrality)
    assert len(signals) == 1
    s = signals[0]
    for key in ("ticker", "type", "direction", "technical_interval",
                "sentiment_direction", "base_confidence", "centrality",
                "final_score", "signal", "is_leader"):
        assert key in s, f"Missing key: {key}"

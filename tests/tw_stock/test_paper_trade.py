# tests/tw_stock/test_paper_trade.py
import pytest


def test_position_size_basic_calculation():
    from agents.tw_stock.paper_trade import compute_position_size
    # risk = 1,000,000 × 2% = 20,000; price_risk = 905-885 = 20; shares = 1000; lots = 1
    lots = compute_position_size(
        portfolio_value=1_000_000,
        entry_price=905.0,
        stop_loss=885.0,
    )
    assert lots == 1


def test_position_size_large_risk_gives_more_lots():
    from agents.tw_stock.paper_trade import compute_position_size
    # risk = 2,000,000 × 2% = 40,000; price_risk = 10; shares = 4000; lots = 4
    lots = compute_position_size(
        portfolio_value=2_000_000,
        entry_price=100.0,
        stop_loss=90.0,
    )
    assert lots == 4


def test_position_size_minimum_is_one():
    from agents.tw_stock.paper_trade import compute_position_size
    lots = compute_position_size(
        portfolio_value=100_000,
        entry_price=1000.0,
        stop_loss=999.5,
    )
    assert lots >= 1


def test_position_size_zero_price_risk_returns_one():
    from agents.tw_stock.paper_trade import compute_position_size
    lots = compute_position_size(
        portfolio_value=1_000_000,
        entry_price=905.0,
        stop_loss=905.0,
    )
    assert lots == 1


def test_check_exit_stop_loss():
    from agents.tw_stock.paper_trade import check_exit_reason
    reason = check_exit_reason(
        {"entry_price": 905.0, "stop_loss": 885.0, "take_profit": 950.0, "hold_days": 1},
        current_price=880.0,
        signal_direction=None,
    )
    assert reason == "stop_loss"


def test_check_exit_take_profit():
    from agents.tw_stock.paper_trade import check_exit_reason
    reason = check_exit_reason(
        {"entry_price": 905.0, "stop_loss": 885.0, "take_profit": 950.0, "hold_days": 1},
        current_price=955.0,
        signal_direction=None,
    )
    assert reason == "take_profit"


def test_check_exit_max_hold():
    from agents.tw_stock.paper_trade import check_exit_reason
    reason = check_exit_reason(
        {"entry_price": 905.0, "stop_loss": 885.0, "take_profit": 950.0, "hold_days": 5},
        current_price=910.0,
        signal_direction="BUY",
    )
    assert reason == "max_hold"


def test_check_exit_signal_reversal():
    from agents.tw_stock.paper_trade import check_exit_reason
    reason = check_exit_reason(
        {"entry_price": 905.0, "stop_loss": 885.0, "take_profit": 950.0, "hold_days": 2},
        current_price=910.0,
        signal_direction="WATCH",
    )
    assert reason == "signal_reversal"


def test_check_exit_hold_returns_none():
    from agents.tw_stock.paper_trade import check_exit_reason
    reason = check_exit_reason(
        {"entry_price": 905.0, "stop_loss": 885.0, "take_profit": 950.0, "hold_days": 1},
        current_price=910.0,
        signal_direction="BUY",
    )
    assert reason is None


def test_process_paper_trade_opens_new_position():
    from agents.tw_stock.paper_trade import process_paper_trade
    signals = [{
        "ticker": "2330", "type": "stock", "direction": "BUY",
        "final_score": 0.52,
        "signal": {"stop_loss": 885.0, "take_profit": 950.0, "strength": "Strong"},
    }]
    result = process_paper_trade(
        signals=signals,
        positions={},
        market_prices={"2330": 905.0},
        portfolio_value=1_000_000,
        cash=1_000_000,
        today="2026-05-08",
    )
    assert "2330" in result["positions"]
    assert result["positions"]["2330"]["entry_price"] == 905.0
    assert result["positions"]["2330"]["entry_date"] == "2026-05-08"


def test_process_paper_trade_closes_stop_loss():
    from agents.tw_stock.paper_trade import process_paper_trade
    existing_positions = {
        "2454": {
            "entry_price": 1050.0, "lots": 1, "shares": 1000,
            "stop_loss": 1020.0, "take_profit": 1130.0,
            "entry_date": "2026-05-06", "hold_days": 2,
        }
    }
    result = process_paper_trade(
        signals=[],
        positions=existing_positions,
        market_prices={"2454": 1010.0},
        portfolio_value=1_050_000,
        cash=0.0,
        today="2026-05-08",
    )
    assert "2454" not in result["positions"]
    assert len(result["closed_today"]) == 1
    assert result["closed_today"][0]["reason"] == "stop_loss"


def test_compute_pnl_total_return():
    from agents.tw_stock.paper_trade import compute_pnl_summary
    pnl = compute_pnl_summary(
        paper_trade={"cash": 1_050_000, "positions": {}, "closed_today": []},
        pnl_history=[],
        today="2026-05-08",
        market_prices={},
        initial_value=1_000_000,
    )
    assert pnl["portfolio_value"] == pytest.approx(1_050_000, abs=1)
    assert pnl["total_return_pct"] == pytest.approx(5.0, abs=0.1)

# tests/tw_stock/test_config_watchlist.py
from pathlib import Path


def test_output_dir_contains_tw_stock():
    from agents.tw_stock.config import OUTPUT_DIR
    assert "tw-stock" in str(OUTPUT_DIR)


def test_positions_file_under_data_dir():
    from agents.tw_stock.config import POSITIONS_FILE
    assert "tw-stock" in str(POSITIONS_FILE)
    assert POSITIONS_FILE.name == "positions.json"


def test_risk_per_trade_is_two_percent():
    from agents.tw_stock.config import RISK_PER_TRADE_PCT
    assert RISK_PER_TRADE_PCT == 0.02


def test_initial_portfolio_value():
    from agents.tw_stock.config import INITIAL_PORTFOLIO_VALUE
    assert INITIAL_PORTFOLIO_VALUE == 1_000_000


def test_watchlist_contains_tsmc():
    from agents.tw_stock.watchlist import get_tickers
    assert "2330" in get_tickers()


def test_get_stock_name_known():
    from agents.tw_stock.watchlist import get_stock_name
    assert get_stock_name("2330") == "台積電"


def test_get_stock_name_unknown_returns_ticker():
    from agents.tw_stock.watchlist import get_stock_name
    assert get_stock_name("9999") == "9999"


def test_watchlist_minimum_size():
    from agents.tw_stock.watchlist import WATCHLIST
    assert len(WATCHLIST) >= 20


def test_watchlist_each_stock_has_required_fields():
    from agents.tw_stock.watchlist import WATCHLIST
    for stock in WATCHLIST:
        assert stock.ticker
        assert stock.name
        assert stock.sector


def test_get_stock_sector_known():
    from agents.tw_stock.watchlist import get_stock_sector
    assert get_stock_sector("2330") == "半導體"


def test_get_stock_sector_unknown_returns_ticker():
    from agents.tw_stock.watchlist import get_stock_sector
    assert get_stock_sector("9999") == "9999"

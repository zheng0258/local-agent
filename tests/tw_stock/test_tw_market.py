# tests/tw_stock/test_tw_market.py
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

_SAMPLE_DF = pd.DataFrame({
    "date": ["2026-05-01", "2026-05-02", "2026-05-05"],
    "open": [880.0, 885.0, 890.0],
    "high": [895.0, 895.0, 905.0],
    "low": [875.0, 880.0, 885.0],
    "close": [885.0, 890.0, 895.0],
    "volume": [25_000_000, 26_000_000, 24_000_000],
})

_TXF_AK_DF = pd.DataFrame({
    "日期": ["2026-05-01", "2026-05-02"],
    "开盘价": [20_000.0, 20_100.0],
    "最高价": [20_100.0, 20_200.0],
    "最低价": [19_900.0, 20_000.0],
    "收盘价": [20_050.0, 20_150.0],
    "成交量": [50_000, 55_000],
})


def test_fetch_stock_returns_dataframe_with_required_cols():
    from tools.fetchers.tw_market import fetch_stock
    with patch("tools.fetchers.finmind.fetch_incremental", return_value=_SAMPLE_DF):
        df = fetch_stock("2330", Path("/tmp/tw_market_test"), token="fake")
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert set(["date", "open", "high", "low", "close", "volume"]).issubset(df.columns)


def test_fetch_stock_falls_back_to_akshare_on_finmind_error():
    from tools.fetchers.tw_market import fetch_stock
    with patch("tools.fetchers.finmind.fetch_incremental", side_effect=Exception("API error")):
        with patch("tools.fetchers.tw_market._fetch_stock_akshare", return_value=_SAMPLE_DF) as mock_ak:
            df = fetch_stock("2330", Path("/tmp/tw_market_test"), token="fake")
    mock_ak.assert_called_once_with("2330", 130)
    assert isinstance(df, pd.DataFrame)


def test_fetch_stock_no_token_uses_akshare():
    from tools.fetchers.tw_market import fetch_stock
    with patch("tools.fetchers.tw_market._fetch_stock_akshare", return_value=_SAMPLE_DF) as mock_ak:
        with patch.dict("os.environ", {}, clear=True):
            df = fetch_stock("2330", Path("/tmp"), token=None)
    mock_ak.assert_called_once()


def test_fetch_txf_returns_dataframe_with_required_cols():
    import sys
    from tools.fetchers.tw_market import fetch_txf
    mock_ak = MagicMock()
    mock_ak.futures_zh_daily_sina.return_value = _TXF_AK_DF
    with patch.dict(sys.modules, {"akshare": mock_ak}):
        df = fetch_txf()
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert set(["date", "open", "high", "low", "close", "volume"]).issubset(df.columns)


def test_fetch_txf_returns_empty_df_on_error():
    import sys
    from tools.fetchers.tw_market import fetch_txf
    mock_ak = MagicMock()
    mock_ak.futures_zh_daily_sina.side_effect = Exception("API error")
    with patch.dict(sys.modules, {"akshare": mock_ak}):
        df = fetch_txf()
    assert isinstance(df, pd.DataFrame)
    assert df.empty

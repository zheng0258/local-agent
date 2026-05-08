"""
台股市場資料抓取。
- 個股 OHLCV：FinMind API (fetch_incremental)，失敗時 AKShare 備援
- 台指期 TXF：AKShare futures_zh_daily_sina
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

_REQUIRED_COLS = ["date", "open", "high", "low", "close", "volume"]


def fetch() -> list[dict]:
    """Fetcher 介面入口：回傳空列表（資料由 fetch_stock / fetch_txf 提供）。"""
    return []


def fetch_stock(
    ticker: str,
    data_dir: Path,
    token: str | None = None,
    lookback_days: int = 130,
) -> pd.DataFrame:
    """個股 OHLCV：先試 FinMind，失敗時 fallback 到 AKShare。"""
    if token is None:
        token = os.environ.get("FINMIND_TOKEN", "")

    if token:
        try:
            from tools.fetchers.finmind import fetch_incremental
            df = fetch_incremental(ticker, data_dir, token)
            if not df.empty:
                return _tail(df, lookback_days)
        except Exception as e:
            print(f"⚠️ FinMind 失敗 ({ticker}): {e}，改用 AKShare")

    return _fetch_stock_akshare(ticker, lookback_days)


def fetch_txf(lookback_days: int = 130) -> pd.DataFrame:
    """台指期 TXF 日線 OHLCV via AKShare futures_zh_daily_sina。"""
    try:
        import akshare as ak
        end_date = date.today().strftime("%Y%m%d")
        start_date = (date.today() - timedelta(days=lookback_days + 30)).strftime("%Y%m%d")
        df = ak.futures_zh_daily_sina(symbol="TXF", start_date=start_date, end_date=end_date)
        df = df.rename(columns={
            "日期": "date",
            "开盘价": "open",
            "最高价": "high",
            "最低价": "low",
            "收盘价": "close",
            "成交量": "volume",
        })
        df = df[[c for c in _REQUIRED_COLS if c in df.columns]].copy()
        df["date"] = df["date"].astype(str)
        df = df.sort_values("date").reset_index(drop=True)
        return _tail(df, lookback_days)
    except Exception as e:
        print(f"⚠️ AKShare TXF 抓取失敗: {e}")
        return pd.DataFrame(columns=_REQUIRED_COLS)


def _fetch_stock_akshare(ticker: str, lookback_days: int) -> pd.DataFrame:
    try:
        import akshare as ak
        end_date = date.today().strftime("%Y%m%d")
        start_date = (date.today() - timedelta(days=lookback_days + 30)).strftime("%Y%m%d")
        df = ak.stock_tw_daily(symbol=ticker, start_date=start_date, end_date=end_date)
        col_map = {
            "date": "date", "open": "open", "high": "high",
            "low": "low", "close": "close", "volume": "volume",
            "開盤": "open", "最高": "high", "最低": "low",
            "收盤": "close", "成交量": "volume", "日期": "date",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df = df[[c for c in _REQUIRED_COLS if c in df.columns]].copy()
        df["date"] = df["date"].astype(str)
        df = df.sort_values("date").reset_index(drop=True)
        return _tail(df, lookback_days)
    except Exception as e:
        print(f"⚠️ AKShare stock_tw_daily 失敗 ({ticker}): {e}")
        return pd.DataFrame(columns=_REQUIRED_COLS)


def _tail(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.tail(n).reset_index(drop=True)

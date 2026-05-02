"""tools/fetchers/finmind.py

FinMind API OHLCV 抓取 + 增量 CSV 快取。
"""
from __future__ import annotations

import json
import ssl
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
_REQUIRED_COLS = ["date", "open", "high", "low", "close", "volume"]


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _api_get(ticker: str, start_date: str, token: str) -> dict:
    url = (
        f"{FINMIND_API_URL}?dataset=TaiwanStockPrice"
        f"&data_id={ticker}&start_date={start_date}&token={token}"
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode())


def fetch_ohlcv(ticker: str, start_date: str, end_date: str, token: str) -> pd.DataFrame:
    """從 FinMind API 抓取 OHLCV，回傳標準化 DataFrame（升序排列）。"""
    data = _api_get(ticker, start_date, token)
    rows = data.get("data", [])
    if not rows:
        return pd.DataFrame(columns=_REQUIRED_COLS)

    df = pd.DataFrame(rows)
    df = df.rename(columns={"Trading_Volume": "volume", "max": "high", "min": "low"})
    df = df[_REQUIRED_COLS].copy()
    df = df[df["date"] <= end_date]
    df = df.sort_values("date").reset_index(drop=True)
    return df


def fetch_incremental(
    ticker: str,
    data_dir: Path,
    token: str,
    initial_days: int = 1750,
) -> pd.DataFrame:
    """
    讀取本地 CSV，補抓缺失資料，存回 CSV，回傳完整 DataFrame。
    首次執行時抓取 initial_days 曆日的歷史（預設 1750 曆日 ≈ 1250 交易日）。
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / f"{ticker}.csv"
    today = date.today().isoformat()

    if csv_path.exists():
        existing = pd.read_csv(csv_path, dtype={"date": str})
        last_date = existing["date"].max()
        start_date = (date.fromisoformat(last_date) + timedelta(days=1)).isoformat()
    else:
        existing = pd.DataFrame(columns=_REQUIRED_COLS)
        start_date = (date.today() - timedelta(days=initial_days)).isoformat()

    if start_date > today:
        return existing

    new_df = fetch_ohlcv(ticker, start_date, today, token)
    if new_df.empty:
        return existing

    if existing.empty:
        combined = new_df.copy()
    else:
        combined = pd.concat([existing, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    combined.to_csv(csv_path, index=False)
    return combined


def load_ohlcv(ticker: str, data_dir: Path, lookback_days: int = 500) -> pd.DataFrame:
    """從本地 CSV 載入最近 lookback_days 筆資料。"""
    csv_path = Path(data_dir) / f"{ticker}.csv"
    if not csv_path.exists():
        return pd.DataFrame(columns=_REQUIRED_COLS)
    df = pd.read_csv(csv_path, dtype={"date": str})
    return df.tail(lookback_days).reset_index(drop=True)

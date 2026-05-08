# agents/tw_stock/watchlist.py
"""台股監控清單（台 50 成分股 + AI/半導體主題）。"""
from __future__ import annotations
from typing import Final, NamedTuple


class Stock(NamedTuple):
    ticker: str
    name: str
    sector: str


WATCHLIST: Final[list[Stock]] = [
    Stock("2330", "台積電", "半導體"),
    Stock("2317", "鴻海", "電子製造"),
    Stock("2454", "聯發科", "半導體"),
    Stock("2412", "中華電", "電信"),
    Stock("2308", "台達電", "電子"),
    Stock("2882", "國泰金", "金融"),
    Stock("2303", "聯電", "半導體"),
    Stock("3711", "日月光投控", "半導體封測"),
    Stock("2881", "富邦金", "金融"),
    Stock("1301", "台塑", "石化"),
    Stock("2002", "中鋼", "鋼鐵"),
    Stock("1303", "南亞", "塑膠"),
    Stock("2886", "兆豐金", "金融"),
    Stock("2891", "中信金", "金融"),
    Stock("6669", "緯穎", "伺服器"),
    Stock("3231", "緯創", "電腦"),
    Stock("3034", "聯詠", "IC設計"),
    Stock("2357", "華碩", "電腦"),
    Stock("2382", "廣達", "電腦"),
    Stock("2395", "研華", "工業電腦"),
    Stock("4938", "和碩", "電子代工"),
    Stock("2379", "瑞昱", "IC設計"),
    Stock("3008", "大立光", "光學"),
    Stock("2409", "友達", "面板"),
    Stock("3045", "台灣大", "電信"),
]

TXF = "TXF"


def get_tickers() -> list[str]:
    return [s.ticker for s in WATCHLIST]


def get_stock_name(ticker: str) -> str:
    for s in WATCHLIST:
        if s.ticker == ticker:
            return s.name
    return ticker


def get_stock_sector(ticker: str) -> str:
    for s in WATCHLIST:
        if s.ticker == ticker:
            return s.sector
    return ticker

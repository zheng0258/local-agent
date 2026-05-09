# agents/tw_stock/config.py
"""tw_stock Agent — 路徑、門檻、環境變數名稱。"""
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent

OUTPUT_DIR = _PROJECT_ROOT / "outputs" / "tw-stock"
DATA_DIR = _PROJECT_ROOT / "data" / "tw-stock"
POSITIONS_FILE = DATA_DIR / "positions.json"
PNL_HISTORY_FILE = DATA_DIR / "pnl_history.json"

INITIAL_PORTFOLIO_VALUE = 1_000_000  # TWD

SIGNAL_MIN_SCORE = 0.40
MAX_DAILY_NEW_POSITIONS = 3
MAX_TOTAL_POSITIONS = 5
RISK_PER_TRADE_PCT = 0.02
MAX_HOLD_DAYS = 5

CENTRALITY_BOOST_FACTOR = 0.5
CORRELATION_LOOKBACK_DAYS = 120
CORRELATION_THRESHOLD = 0.4

TXF_MIN_CONFIDENCE = 0.2

STOCK_BOT_TOKEN_ENV = "STOCK_TELEGRAM_BOT_TOKEN"
STOCK_CHAT_ID_ENV = "STOCK_TELEGRAM_CHAT_ID"

INIT_FILE = DATA_DIR / "init.json"

ALL_STEPS: tuple[str, ...] = (
    "news", "sentiment", "market_data", "technical",
    "signal", "paper_trade", "pnl", "notify",
)

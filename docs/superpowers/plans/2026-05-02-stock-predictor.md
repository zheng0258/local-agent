# Stock Predictor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立每日台股預測訊號系統，包含 De Bruijn + Markov + PageRank 核心算法、FinMind 資料層、每日 Telegram 訊號推送、Telegram Bot watchlist 管理、及每週 LLM 策略分析報告。

**Architecture:** 核心算法封裝為純函數 `tools/predictors/algorithm.py`，兩個 agent（`stock_predictor` / `stock_analyst`）負責流程編排，Telegram Bot 長駐監聽 watchlist 指令。每日 15:30 透過 n8n 觸發預測；週六透過 n8n 觸發策略分析。

**Tech Stack:** Python 3.11+、pandas、ta、networkx、python-telegram-bot v20、requests、pytest

---

## File Map

| 檔案 | 動作 | 職責 |
|------|------|------|
| `tools/predictors/__init__.py` | 新增 | 模組匯出 |
| `tools/predictors/algorithm.py` | 新增 | ALGORITHM.md Step 2–12 全實作 |
| `tools/fetchers/finmind.py` | 新增 | FinMind OHLCV 抓取 + 增量 CSV 快取 |
| `tools/notifiers/telegram_bot.py` | 新增 | 長駐 Telegram Bot，watchlist CRUD |
| `agents/stock_predictor/__init__.py` | 新增 | 模組匯出 |
| `agents/stock_predictor/agent.py` | 新增 | 每日流程：verify → predict → notify |
| `agents/stock_predictor/prompts.py` | 新增 | （預留，目前空） |
| `agents/stock_predictor/config.py` | 新增 | 預設超參數、路徑常數 |
| `agents/stock_analyst/__init__.py` | 新增 | 模組匯出 |
| `agents/stock_analyst/agent.py` | 新增 | 策略分析流程 |
| `agents/stock_analyst/prompts.py` | 新增 | LLM 比較分析 prompts |
| `agents/stock_analyst/config.py` | 新增 | 策略變體定義 |
| `main.py` | 修改 | 新增兩個 agent 路由 |
| `AGENTS.md` | 修改 | 新增路由表條目 |
| `tests/tools/predictors/__init__.py` | 新增 | 測試模組 |
| `tests/tools/predictors/test_algorithm.py` | 新增 | algorithm.py 單元測試 |
| `tests/tools/fetchers/test_finmind.py` | 新增 | finmind.py 單元測試 |
| `tests/agents/stock_predictor/test_agent.py` | 新增 | predictor agent 測試 |
| `tests/agents/stock_analyst/test_agent.py` | 新增 | analyst agent 測試 |

---

## Phase 1：核心算法

---

### Task 1：模組骨架 + 技術指標（Step 2）

**Files:**
- Create: `tools/predictors/__init__.py`
- Create: `tools/predictors/algorithm.py`
- Create: `tests/tools/predictors/__init__.py`
- Create: `tests/tools/predictors/test_algorithm.py`

- [ ] **Step 1：安裝依賴**

```bash
pip install ta networkx
```

- [ ] **Step 2：建立空模組結構**

```bash
touch tools/predictors/__init__.py
touch tests/tools/predictors/__init__.py
```

- [ ] **Step 3：撰寫指標測試（失敗）**

建立 `tests/tools/predictors/test_algorithm.py`：

```python
"""tests/tools/predictors/test_algorithm.py"""
import numpy as np
import pandas as pd
import pytest


INTERVALS = ["S", "F0", "R1", "R2", "R3"]


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """50 根 OHLCV，供所有 algorithm 測試共用。"""
    np.random.seed(42)
    n = 50
    dates = pd.bdate_range("2025-01-02", periods=n).strftime("%Y-%m-%d").tolist()
    close = 100.0 * np.cumprod(1 + np.random.normal(0.001, 0.015, n))
    open_ = close * (1 + np.random.normal(0, 0.005, n))
    high = np.maximum(close, open_) * (1 + np.abs(np.random.normal(0, 0.008, n)))
    low = np.minimum(close, open_) * (1 - np.abs(np.random.normal(0, 0.008, n)))
    volume = np.random.randint(1_000, 10_000, n).astype(float)
    return pd.DataFrame({"date": dates, "open": open_, "high": high,
                         "low": low, "close": close, "volume": volume})


# ── Step 2 ──────────────────────────────────────────────────────────────────

def test_compute_indicators_adds_columns(sample_ohlcv):
    from tools.predictors.algorithm import _compute_indicators
    result = _compute_indicators(sample_ohlcv)
    expected_cols = [
        "ma5", "ma10", "ma20", "rsi14", "k_value", "d_value",
        "macd", "macd_signal", "macd_hist",
        "boll_upper", "boll_middle", "boll_lower",
        "atr14", "obv", "volume_ratio",
    ]
    for col in expected_cols:
        assert col in result.columns, f"missing column: {col}"


def test_compute_indicators_does_not_mutate(sample_ohlcv):
    from tools.predictors.algorithm import _compute_indicators
    original_cols = list(sample_ohlcv.columns)
    _compute_indicators(sample_ohlcv)
    assert list(sample_ohlcv.columns) == original_cols


def test_compute_indicators_ma5_last_row(sample_ohlcv):
    from tools.predictors.algorithm import _compute_indicators
    result = _compute_indicators(sample_ohlcv)
    expected_ma5 = sample_ohlcv["close"].iloc[-5:].mean()
    assert abs(result["ma5"].iloc[-1] - expected_ma5) < 1e-6


def test_compute_indicators_volume_ratio(sample_ohlcv):
    from tools.predictors.algorithm import _compute_indicators
    result = _compute_indicators(sample_ohlcv)
    # 最後一行 volume_ratio = volume / rolling_mean(volume, 20)
    last_vol = sample_ohlcv["volume"].iloc[-1]
    rolling_mean = sample_ohlcv["volume"].iloc[-20:].mean()
    expected = last_vol / rolling_mean
    assert abs(result["volume_ratio"].iloc[-1] - expected) < 1e-6
```

- [ ] **Step 4：執行測試，確認 FAIL**

```bash
pytest tests/tools/predictors/test_algorithm.py::test_compute_indicators_adds_columns -v
```

預期：`ImportError: cannot import name '_compute_indicators'`

- [ ] **Step 5：實作 `tools/predictors/algorithm.py`（指標部分）**

```python
"""tools/predictors/algorithm.py

Taiwan Stock Prediction Engine
ALGORITHM.md Steps 2–12 完整實作。
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

try:
    import ta
    from ta.momentum import RSIIndicator, StochasticOscillator
    from ta.trend import MACD, SMAIndicator
    from ta.volatility import AverageTrueRange, BollingerBands
    from ta.volume import OnBalanceVolumeIndicator
except ImportError as e:  # pragma: no cover
    raise ImportError("pip install ta") from e

# ── Constants ────────────────────────────────────────────────────────────────

INTERVALS: list[str] = ["S", "F0", "R1", "R2", "R3"]

DEFAULT_PARAMS: dict[str, Any] = {
    "flat_lower": -0.5,
    "small_move": 2.0,
    "large_move": 4.0,
    "rsi_overbought": 70.0,
    "rsi_oversold": 30.0,
    "n_order": 3,
    "lookback_days": 120,
    "decay_gamma": 0.005,
    "lambda1": 0.6,
    "lambda2": 0.3,
    "lambda3": 0.1,
    "atr_k_r1": 0.5,
    "atr_k_r2": 0.8,
    "atr_k_r3": 1.2,
}

# ── Step 2：Technical Indicators ─────────────────────────────────────────────

def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """回傳含所有技術指標的新 DataFrame（不修改輸入）。"""
    df = df.copy()
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]

    df["ma5"]  = SMAIndicator(close, window=5).sma_indicator()
    df["ma10"] = SMAIndicator(close, window=10).sma_indicator()
    df["ma20"] = SMAIndicator(close, window=20).sma_indicator()

    df["rsi14"] = RSIIndicator(close, window=14).rsi()

    stoch = StochasticOscillator(high=high, low=low, close=close, window=9, smooth_window=3)
    df["k_value"] = stoch.stoch()
    df["d_value"] = stoch.stoch_signal()

    macd = MACD(close, window_fast=12, window_slow=26, window_sign=9)
    df["macd"]        = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"]   = macd.macd_diff()

    bb = BollingerBands(close, window=20, window_dev=2)
    df["boll_upper"]  = bb.bollinger_hband()
    df["boll_middle"] = bb.bollinger_mavg()
    df["boll_lower"]  = bb.bollinger_lband()

    df["atr14"] = AverageTrueRange(high, low, close, window=14).average_true_range()
    df["obv"]   = OnBalanceVolumeIndicator(close, vol).on_balance_volume()

    rolling_vol_mean = vol.rolling(20).mean()
    df["volume_ratio"] = vol / rolling_vol_mean

    return df
```

- [ ] **Step 6：執行 Step 2 測試，確認 PASS**

```bash
pytest tests/tools/predictors/test_algorithm.py -k "compute_indicators" -v
```

預期：4 tests PASSED

- [ ] **Step 7：Commit**

```bash
git add tools/predictors/ tests/tools/predictors/
git commit -m "feat: add algorithm.py module with Step 2 indicators"
```

---

### Task 2：Regime 偵測 + 符號離散化（Steps 3–4）

**Files:**
- Modify: `tools/predictors/algorithm.py`
- Modify: `tests/tools/predictors/test_algorithm.py`

- [ ] **Step 1：新增 Steps 3–4 測試（append 到測試檔末尾）**

```python
# ── Step 3：Regime ───────────────────────────────────────────────────────────

def test_detect_regime_bull():
    from tools.predictors.algorithm import _detect_regime
    assert _detect_regime(close=110.0, ma5=105.0, ma10=100.0) == "Bull"


def test_detect_regime_bear():
    from tools.predictors.algorithm import _detect_regime
    assert _detect_regime(close=90.0, ma5=95.0, ma10=100.0) == "Bear"


def test_detect_regime_range():
    from tools.predictors.algorithm import _detect_regime
    # close > ma5 但 < ma10
    assert _detect_regime(close=102.0, ma5=100.0, ma10=105.0) == "Range"


# ── Step 4：Discretization ───────────────────────────────────────────────────

def test_interval_token_s():
    from tools.predictors.algorithm import _interval_token, DEFAULT_PARAMS
    assert _interval_token(-1.0, DEFAULT_PARAMS) == "S"


def test_interval_token_f0():
    from tools.predictors.algorithm import _interval_token, DEFAULT_PARAMS
    assert _interval_token(0.0, DEFAULT_PARAMS) == "F0"


def test_interval_token_r1():
    from tools.predictors.algorithm import _interval_token, DEFAULT_PARAMS
    assert _interval_token(1.0, DEFAULT_PARAMS) == "R1"


def test_interval_token_r2():
    from tools.predictors.algorithm import _interval_token, DEFAULT_PARAMS
    assert _interval_token(3.0, DEFAULT_PARAMS) == "R2"


def test_interval_token_r3():
    from tools.predictors.algorithm import _interval_token, DEFAULT_PARAMS
    assert _interval_token(5.0, DEFAULT_PARAMS) == "R3"


def test_rsi_zone_overbought():
    from tools.predictors.algorithm import _rsi_zone, DEFAULT_PARAMS
    assert _rsi_zone(75.0, DEFAULT_PARAMS) == "RSI_OB"


def test_rsi_zone_oversold():
    from tools.predictors.algorithm import _rsi_zone, DEFAULT_PARAMS
    assert _rsi_zone(25.0, DEFAULT_PARAMS) == "RSI_OS"


def test_rsi_zone_neutral():
    from tools.predictors.algorithm import _rsi_zone, DEFAULT_PARAMS
    assert _rsi_zone(50.0, DEFAULT_PARAMS) == "RSI_NEU"


def test_rsi_zone_none():
    from tools.predictors.algorithm import _rsi_zone, DEFAULT_PARAMS
    assert _rsi_zone(None, DEFAULT_PARAMS) == "RSI_UNK"


def test_ma_touch_yes():
    from tools.predictors.algorithm import _ma_touch_token
    assert _ma_touch_token(low=98.0, high=102.0, ma=100.0, prefix="T5") == "T5_Y"


def test_ma_touch_no():
    from tools.predictors.algorithm import _ma_touch_token
    assert _ma_touch_token(low=103.0, high=107.0, ma=100.0, prefix="T5") == "T5_N"


def test_ma_touch_unknown():
    from tools.predictors.algorithm import _ma_touch_token
    assert _ma_touch_token(low=100.0, high=105.0, ma=None, prefix="T10") == "T10_UNK"


def test_encode_symbol_format(sample_ohlcv):
    from tools.predictors.algorithm import _compute_indicators, _encode_symbol, DEFAULT_PARAMS
    df = _compute_indicators(sample_ohlcv)
    row = df.iloc[-1]
    prev_close = df.iloc[-2]["close"]
    code = _encode_symbol(row, prev_close, DEFAULT_PARAMS)
    parts = code.split("|")
    assert len(parts) == 4
    assert parts[0] in ["S", "F0", "R1", "R2", "R3"]
    assert parts[1].startswith("RSI_")
    assert parts[2].startswith("T5_")
    assert parts[3].startswith("T10_")
```

- [ ] **Step 2：執行測試，確認 FAIL**

```bash
pytest tests/tools/predictors/test_algorithm.py -k "regime or interval_token or rsi_zone or ma_touch or encode_symbol" -v
```

預期：全部 FAIL（函數尚未定義）

- [ ] **Step 3：實作 Steps 3–4（追加到 algorithm.py 指標部分之後）**

```python
# ── Step 3：Regime Detection ─────────────────────────────────────────────────

def _detect_regime(close: float, ma5: float | None, ma10: float | None) -> str:
    if ma5 is None or ma10 is None or np.isnan(ma5) or np.isnan(ma10):
        return "Range"
    if close > ma5 and close > ma10:
        return "Bull"
    if close < ma5 and close < ma10:
        return "Bear"
    return "Range"


# ── Step 4：Discretization ───────────────────────────────────────────────────

def _interval_token(pct: float, params: dict) -> str:
    flat_lower = params["flat_lower"]        # e.g. -0.5
    small_move = params["small_move"]        # e.g.  2.0
    large_move = params["large_move"]        # e.g.  4.0
    if pct < flat_lower:
        return "S"
    if pct < -flat_lower:
        return "F0"
    if pct < small_move:
        return "R1"
    if pct < large_move:
        return "R2"
    return "R3"


def _rsi_zone(rsi: float | None, params: dict) -> str:
    if rsi is None or (isinstance(rsi, float) and np.isnan(rsi)):
        return "RSI_UNK"
    if rsi >= params["rsi_overbought"]:
        return "RSI_OB"
    if rsi <= params["rsi_oversold"]:
        return "RSI_OS"
    return "RSI_NEU"


def _ma_touch_token(low: float, high: float, ma: float | None, prefix: str) -> str:
    if ma is None or (isinstance(ma, float) and np.isnan(ma)):
        return f"{prefix}_UNK"
    return f"{prefix}_Y" if low <= ma <= high else f"{prefix}_N"


def _encode_symbol(row: pd.Series, prev_close: float | None, params: dict) -> str:
    if prev_close is None or np.isnan(prev_close) or prev_close == 0:
        interval = "F0"
    else:
        pct = (row["close"] / prev_close - 1) * 100
        interval = _interval_token(pct, params)

    rsi = row.get("rsi14")
    ma5  = row.get("ma5")
    ma10 = row.get("ma10")
    rsi_zone = _rsi_zone(rsi if not (isinstance(rsi, float) and np.isnan(rsi)) else None, params)
    t5  = _ma_touch_token(row["low"], row["high"], ma5 if not (isinstance(ma5, float) and np.isnan(ma5)) else None, "T5")
    t10 = _ma_touch_token(row["low"], row["high"], ma10 if not (isinstance(ma10, float) and np.isnan(ma10)) else None, "T10")

    return f"{interval}|{rsi_zone}|{t5}|{t10}"
```

- [ ] **Step 4：執行測試，確認 PASS**

```bash
pytest tests/tools/predictors/test_algorithm.py -k "regime or interval_token or rsi_zone or ma_touch or encode_symbol" -v
```

預期：全部 PASS

- [ ] **Step 5：Commit**

```bash
git add tools/predictors/algorithm.py tests/tools/predictors/test_algorithm.py
git commit -m "feat: add regime detection and symbol discretization (Steps 3-4)"
```

---

### Task 3：De Bruijn 圖（Step 5）

**Files:**
- Modify: `tools/predictors/algorithm.py`
- Modify: `tests/tools/predictors/test_algorithm.py`

- [ ] **Step 1：新增 De Bruijn 測試**

```python
# ── Step 5：De Bruijn Graph ──────────────────────────────────────────────────

def test_build_debruijn_edge_count():
    from tools.predictors.algorithm import _build_debruijn_graph
    symbols = ["A", "B", "C", "A", "B", "C"]
    dates = ["2025-01-01", "2025-01-02", "2025-01-03",
             "2025-01-04", "2025-01-05", "2025-01-06"]
    graph = _build_debruijn_graph(symbols, n=2, dates=dates)
    # edge (("A","B"), ("B","C")) appears twice
    assert graph["edge_counts"][(("A", "B"), ("B", "C"))] == 2


def test_build_debruijn_edge_dates():
    from tools.predictors.algorithm import _build_debruijn_graph
    symbols = ["A", "B", "C"]
    dates = ["2025-01-01", "2025-01-02", "2025-01-03"]
    graph = _build_debruijn_graph(symbols, n=2, dates=dates)
    edge = (("A", "B"), ("B", "C"))
    # date of last symbol in destination node = dates[2]
    assert graph["edge_dates"][edge] == ["2025-01-03"]


def test_build_debruijn_empty_symbols():
    from tools.predictors.algorithm import _build_debruijn_graph
    graph = _build_debruijn_graph([], n=3, dates=[])
    assert graph["edge_counts"] == {}


def test_build_debruijn_current_node(sample_ohlcv):
    from tools.predictors.algorithm import (
        _compute_indicators, _build_debruijn_graph,
        _encode_symbols_from_df, DEFAULT_PARAMS,
    )
    df = _compute_indicators(sample_ohlcv)
    symbols, dates = _encode_symbols_from_df(df, DEFAULT_PARAMS)
    graph = _build_debruijn_graph(symbols, n=3, dates=dates)
    current = tuple(symbols[-3:])
    assert isinstance(current, tuple)
    assert len(current) == 3
```

- [ ] **Step 2：執行測試，確認 FAIL**

```bash
pytest tests/tools/predictors/test_algorithm.py -k "debruijn" -v
```

- [ ] **Step 3：實作 De Bruijn（追加到 algorithm.py）**

```python
# ── Step 5：De Bruijn Graph ──────────────────────────────────────────────────

def _encode_symbols_from_df(df: pd.DataFrame, params: dict) -> tuple[list[str], list[str]]:
    """從 DataFrame 產生 (symbols, dates) 兩個等長 list。"""
    symbols: list[str] = []
    dates: list[str] = []
    prev_close: float | None = None
    for _, row in df.iterrows():
        code = _encode_symbol(row, prev_close, params)
        symbols.append(code)
        dates.append(str(row["date"]))
        prev_close = row["close"]
    return symbols, dates


def _build_debruijn_graph(
    symbols: list[str], n: int, dates: list[str]
) -> dict[str, Any]:
    """
    Build De Bruijn graph from symbol sequence.
    Returns {"edge_counts": {...}, "edge_dates": {...}}.
    """
    if len(symbols) < n + 1:
        return {"edge_counts": {}, "edge_dates": {}}

    windows = [tuple(symbols[i : i + n]) for i in range(len(symbols) - n + 1)]
    edge_counts: dict = defaultdict(int)
    edge_dates: dict = defaultdict(list)

    for i in range(len(windows) - 1):
        edge = (windows[i], windows[i + 1])
        edge_counts[edge] += 1
        edge_dates[edge].append(dates[i + n])

    return {"edge_counts": dict(edge_counts), "edge_dates": dict(edge_dates)}
```

- [ ] **Step 4：執行測試，確認 PASS**

```bash
pytest tests/tools/predictors/test_algorithm.py -k "debruijn" -v
```

- [ ] **Step 5：Commit**

```bash
git add tools/predictors/algorithm.py tests/tools/predictors/test_algorithm.py
git commit -m "feat: add De Bruijn graph construction (Step 5)"
```

---

### Task 4：Markov 轉移矩陣（Step 6）

**Files:**
- Modify: `tools/predictors/algorithm.py`
- Modify: `tests/tools/predictors/test_algorithm.py`

- [ ] **Step 1：新增 Markov 測試**

```python
# ── Step 6：Markov ───────────────────────────────────────────────────────────

def test_markov_distribution_known_state():
    from tools.predictors.algorithm import _markov_distribution, DEFAULT_PARAMS
    # A→B 出現 2 次，A→C 出現 1 次，使用相同日期（無衰減差異）
    ref_date = "2025-03-01"
    graph = {
        "edge_counts": {
            (("A",), ("B",)): 2,
            (("A",), ("C",)): 1,
        },
        "edge_dates": {
            (("A",), ("B",)): [ref_date, ref_date],
            (("A",), ("C",)): [ref_date],
        },
    }
    current_node = ("A",)
    params = {**DEFAULT_PARAMS, "decay_gamma": 0.0}  # 無衰減
    dist = _markov_distribution(graph, current_node, ref_date, params)
    # B 權重 2/3，C 權重 1/3
    assert abs(dist.get("B", 0) - 2 / 3) < 1e-6
    assert abs(dist.get("C", 0) - 1 / 3) < 1e-6


def test_markov_distribution_unknown_state_uses_global():
    from tools.predictors.algorithm import _markov_distribution, DEFAULT_PARAMS
    ref_date = "2025-03-01"
    graph = {
        "edge_counts": {(("X",), ("Y",)): 1},
        "edge_dates": {(("X",), ("Y",)): [ref_date]},
    }
    dist = _markov_distribution(graph, ("Z",), ref_date, DEFAULT_PARAMS)
    # fallback to global distribution → Y 應有非零機率
    assert sum(dist.values()) > 0
    assert abs(sum(dist.values()) - 1.0) < 1e-6


def test_markov_distribution_sums_to_one(sample_ohlcv):
    from tools.predictors.algorithm import (
        _compute_indicators, _encode_symbols_from_df,
        _build_debruijn_graph, _markov_distribution, DEFAULT_PARAMS,
    )
    df = _compute_indicators(sample_ohlcv)
    symbols, dates = _encode_symbols_from_df(df, DEFAULT_PARAMS)
    n = DEFAULT_PARAMS["n_order"]
    graph = _build_debruijn_graph(symbols, n, dates)
    current_node = tuple(symbols[-n:])
    dist = _markov_distribution(graph, current_node, dates[-1], DEFAULT_PARAMS)
    assert abs(sum(dist.values()) - 1.0) < 1e-6
```

- [ ] **Step 2：執行測試，確認 FAIL**

```bash
pytest tests/tools/predictors/test_algorithm.py -k "markov" -v
```

- [ ] **Step 3：實作 Markov（追加到 algorithm.py）**

```python
# ── Step 6：Markov Transition Matrix ─────────────────────────────────────────

def _date_to_ordinal(d: str) -> int:
    """'YYYY-MM-DD' → int，用於計算天數差。"""
    y, m, day = d.split("-")
    return date(int(y), int(m), int(day)).toordinal()


def _edge_weight(edge_dates: list[str], reference_date: str, gamma: float) -> float:
    ref_ord = _date_to_ordinal(reference_date)
    return sum(
        math.exp(-gamma * max(0, ref_ord - _date_to_ordinal(d)))
        for d in edge_dates
    )


def _markov_distribution(
    graph: dict,
    current_node: tuple,
    reference_date: str,
    params: dict,
) -> dict[str, float]:
    """
    Markov transition probability from current_node.
    Falls back to global distribution if current_node is unseen.
    Returns dict keyed by the *last symbol* of each next node.
    """
    gamma = params["decay_gamma"]
    eps = 1e-12
    edge_counts = graph.get("edge_counts", {})
    edge_dates_map = graph.get("edge_dates", {})

    # Outgoing edges from current_node
    outgoing: dict[tuple, float] = {}
    for (src, dst), count in edge_counts.items():
        if src == current_node:
            dates_list = edge_dates_map.get((src, dst), [reference_date] * count)
            outgoing[dst] = _edge_weight(dates_list, reference_date, gamma)

    # Global fallback
    if not outgoing:
        global_weights: dict[tuple, float] = defaultdict(float)
        for (src, dst), count in edge_counts.items():
            dates_list = edge_dates_map.get((src, dst), [reference_date] * count)
            global_weights[dst] += _edge_weight(dates_list, reference_date, gamma)
        outgoing = dict(global_weights)

    if not outgoing:
        return {iv: 1 / len(INTERVALS) for iv in INTERVALS}

    # Laplace smoothing then aggregate to interval (last symbol of next node)
    total = sum(outgoing.values()) + eps * len(outgoing)
    interval_dist: dict[str, float] = defaultdict(float)
    for dst_node, w in outgoing.items():
        interval = dst_node[-1].split("|")[0]  # first token = interval
        interval_dist[interval] += (w + eps) / total

    # Normalise
    s = sum(interval_dist.values())
    return {k: v / s for k, v in interval_dist.items()}
```

- [ ] **Step 4：執行測試，確認 PASS**

```bash
pytest tests/tools/predictors/test_algorithm.py -k "markov" -v
```

- [ ] **Step 5：Commit**

```bash
git add tools/predictors/algorithm.py tests/tools/predictors/test_algorithm.py
git commit -m "feat: add Markov transition matrix with time-decay (Step 6)"
```

---

### Task 5：PageRank + Indicator 分布（Steps 7–8）

**Files:**
- Modify: `tools/predictors/algorithm.py`
- Modify: `tests/tools/predictors/test_algorithm.py`

- [ ] **Step 1：新增 PageRank + Indicator 測試**

```python
# ── Step 7：PageRank ─────────────────────────────────────────────────────────

def test_pagerank_distribution_sums_to_one(sample_ohlcv):
    from tools.predictors.algorithm import (
        _compute_indicators, _encode_symbols_from_df,
        _build_debruijn_graph, _pagerank_distribution, DEFAULT_PARAMS,
    )
    df = _compute_indicators(sample_ohlcv)
    symbols, dates = _encode_symbols_from_df(df, DEFAULT_PARAMS)
    n = DEFAULT_PARAMS["n_order"]
    graph = _build_debruijn_graph(symbols, n, dates)
    dist = _pagerank_distribution(graph, dates[-1], DEFAULT_PARAMS)
    assert abs(sum(dist.values()) - 1.0) < 1e-6


def test_pagerank_distribution_returns_all_intervals(sample_ohlcv):
    from tools.predictors.algorithm import (
        _compute_indicators, _encode_symbols_from_df,
        _build_debruijn_graph, _pagerank_distribution, DEFAULT_PARAMS,
    )
    df = _compute_indicators(sample_ohlcv)
    symbols, dates = _encode_symbols_from_df(df, DEFAULT_PARAMS)
    graph = _build_debruijn_graph(symbols, DEFAULT_PARAMS["n_order"], dates)
    dist = _pagerank_distribution(graph, dates[-1], DEFAULT_PARAMS)
    # 全部 key 都在 INTERVALS 集合內
    from tools.predictors.algorithm import INTERVALS
    for k in dist:
        assert k in INTERVALS


# ── Step 8：Indicator Distribution ───────────────────────────────────────────

def test_indicator_distribution_rsi_ob_lean_bearish():
    from tools.predictors.algorithm import _indicator_distribution
    code = "R1|RSI_OB|T5_N|T10_N"
    dist = _indicator_distribution(code)
    assert dist["S"] > dist["R3"], "RSI_OB should give bearish lean"


def test_indicator_distribution_rsi_os_lean_bullish():
    from tools.predictors.algorithm import _indicator_distribution
    code = "F0|RSI_OS|T5_N|T10_N"
    dist = _indicator_distribution(code)
    assert dist["R1"] > dist["S"], "RSI_OS should give bullish lean"


def test_indicator_distribution_sums_to_one():
    from tools.predictors.algorithm import _indicator_distribution
    for code in ["S|RSI_OB|T5_Y|T10_Y", "R2|RSI_NEU|T5_N|T10_N", "F0|RSI_OS|T5_Y|T10_N"]:
        dist = _indicator_distribution(code)
        assert abs(sum(dist.values()) - 1.0) < 1e-6
```

- [ ] **Step 2：執行測試，確認 FAIL**

```bash
pytest tests/tools/predictors/test_algorithm.py -k "pagerank or indicator_distribution" -v
```

- [ ] **Step 3：實作 Steps 7–8（追加到 algorithm.py）**

```python
# ── Step 7：PageRank ─────────────────────────────────────────────────────────

def _pagerank_distribution(
    graph: dict, reference_date: str, params: dict
) -> dict[str, float]:
    """
    Build DiGraph from De Bruijn edges (time-decay weights),
    run PageRank, aggregate to intervals.
    """
    gamma = params["decay_gamma"]
    edge_counts = graph.get("edge_counts", {})
    edge_dates_map = graph.get("edge_dates", {})

    G = nx.DiGraph()
    for (src, dst), count in edge_counts.items():
        dates_list = edge_dates_map.get((src, dst), [reference_date] * count)
        w = _edge_weight(dates_list, reference_date, gamma)
        if G.has_edge(src, dst):
            G[src][dst]["weight"] += w
        else:
            G.add_edge(src, dst, weight=w)

    if G.number_of_nodes() == 0:
        return {iv: 1 / len(INTERVALS) for iv in INTERVALS}

    try:
        pr = nx.pagerank(G, alpha=0.85, weight="weight")
    except nx.PowerIterationFailedConvergence:
        pr = {n: 1 / G.number_of_nodes() for n in G.nodes()}

    interval_scores: dict[str, float] = defaultdict(float)
    for node, score in pr.items():
        interval = node[-1].split("|")[0]
        interval_scores[interval] += score

    s = sum(interval_scores.values())
    return {k: v / s for k, v in interval_scores.items()}


# ── Step 8：Indicator Signal Distribution ────────────────────────────────────

def _indicator_distribution(latest_code: str) -> dict[str, float]:
    """
    Heuristic prior from the latest day's symbol code tokens.
    """
    parts = latest_code.split("|")
    rsi_zone = parts[1] if len(parts) > 1 else "RSI_NEU"
    t5       = parts[2] if len(parts) > 2 else "T5_N"
    t10      = parts[3] if len(parts) > 3 else "T10_N"

    scores: dict[str, float] = {iv: 0.0 for iv in INTERVALS}
    scores["F0"] = 1.0  # base

    if t5 == "T5_Y" and t10 == "T10_Y":
        scores["R1"] += 0.6
        scores["S"]  += 0.6
    elif t5 == "T5_Y":
        scores["F0"] += 0.5

    if rsi_zone == "RSI_OB":
        scores["S"] += 1.3
    elif rsi_zone == "RSI_OS":
        scores["R1"] += 0.8
        scores["R2"] += 0.5

    s = sum(scores.values())
    return {k: v / s for k, v in scores.items()}
```

- [ ] **Step 4：執行測試，確認 PASS**

```bash
pytest tests/tools/predictors/test_algorithm.py -k "pagerank or indicator_distribution" -v
```

- [ ] **Step 5：Commit**

```bash
git add tools/predictors/algorithm.py tests/tools/predictors/test_algorithm.py
git commit -m "feat: add PageRank and indicator signal distribution (Steps 7-8)"
```

---

### Task 6：加權組合 + 信心 + 預測收盤 + 交易訊號（Steps 9–12）

**Files:**
- Modify: `tools/predictors/algorithm.py`
- Modify: `tests/tools/predictors/test_algorithm.py`

- [ ] **Step 1：新增 Steps 9–12 測試**

```python
# ── Steps 9–12 ───────────────────────────────────────────────────────────────

def test_combine_sums_to_one():
    from tools.predictors.algorithm import _combine, DEFAULT_PARAMS
    uniform = {iv: 0.2 for iv in ["S", "F0", "R1", "R2", "R3"]}
    result = _combine(uniform, uniform, uniform, DEFAULT_PARAMS)
    assert abs(sum(result.values()) - 1.0) < 1e-6


def test_combine_all_keys_present():
    from tools.predictors.algorithm import _combine, DEFAULT_PARAMS, INTERVALS
    uniform = {iv: 0.2 for iv in INTERVALS}
    result = _combine(uniform, uniform, uniform, DEFAULT_PARAMS)
    assert set(result.keys()) == set(INTERVALS)


def test_confidence_uniform_is_zero():
    from tools.predictors.algorithm import _confidence, INTERVALS
    uniform = {iv: 1 / len(INTERVALS) for iv in INTERVALS}
    assert abs(_confidence(uniform) - 0.0) < 1e-6


def test_confidence_certain_is_one():
    from tools.predictors.algorithm import _confidence, INTERVALS
    certain = {iv: 0.0 for iv in INTERVALS}
    certain["R2"] = 1.0
    assert abs(_confidence(certain) - 1.0) < 1e-6


def test_trading_signal_r1_has_sl_tp():
    from tools.predictors.algorithm import _trading_signal, DEFAULT_PARAMS
    sig = _trading_signal("R1", current_close=100.0, atr=1.0,
                          confidence=0.5, params=DEFAULT_PARAMS)
    assert sig is not None
    assert sig["stop_loss"] < 100.0
    assert sig["take_profit"] > 100.0
    assert sig["stop_loss_pct"] < 0


def test_trading_signal_s_returns_none():
    from tools.predictors.algorithm import _trading_signal, DEFAULT_PARAMS
    sig = _trading_signal("S", current_close=100.0, atr=1.0,
                          confidence=0.5, params=DEFAULT_PARAMS)
    assert sig is None


def test_trading_signal_strength_strong():
    from tools.predictors.algorithm import _trading_signal, DEFAULT_PARAMS
    sig = _trading_signal("R3", current_close=100.0, atr=1.0,
                          confidence=0.45, params=DEFAULT_PARAMS)
    assert sig["strength"] == "Strong"
```

- [ ] **Step 2：執行測試，確認 FAIL**

```bash
pytest tests/tools/predictors/test_algorithm.py -k "combine or confidence or trading_signal" -v
```

- [ ] **Step 3：實作 Steps 9–12（追加到 algorithm.py）**

```python
# ── Step 9：Weighted Combination ─────────────────────────────────────────────

def _combine(
    markov: dict[str, float],
    pagerank: dict[str, float],
    indicator: dict[str, float],
    params: dict,
) -> dict[str, float]:
    l1, l2, l3 = params["lambda1"], params["lambda2"], params["lambda3"]
    total = l1 + l2 + l3
    l1, l2, l3 = l1 / total, l2 / total, l3 / total

    combined = {
        iv: l1 * markov.get(iv, 0.0)
          + l2 * pagerank.get(iv, 0.0)
          + l3 * indicator.get(iv, 0.0)
        for iv in INTERVALS
    }
    s = sum(combined.values())
    return {k: v / s for k, v in combined.items()}


# ── Step 10：Confidence ───────────────────────────────────────────────────────

def _confidence(probs: dict[str, float]) -> float:
    h_max = math.log(len(INTERVALS))
    h = -sum(p * math.log(p) for p in probs.values() if p > 0)
    return max(0.0, min(1.0, 1.0 - h / h_max))


# ── Step 11：Projected Close ─────────────────────────────────────────────────

_FALLBACK_MIDPOINTS: dict[str, float] = {
    "S": -1.5, "F0": 0.0, "R1": 1.25, "R2": 3.0, "R3": 5.5
}


def _projected_close(
    probs: dict[str, float], df: pd.DataFrame, current_close: float
) -> float:
    if "close_change_pct" not in df.columns:
        df = df.copy()
        df["close_change_pct"] = df["close"].pct_change() * 100

    midpoints: dict[str, float] = {}
    for iv in INTERVALS:
        if "interval_token" in df.columns:
            rows = df[df["interval_token"] == iv]["close_change_pct"].dropna()
            midpoints[iv] = float(rows.mean()) if len(rows) > 0 else _FALLBACK_MIDPOINTS[iv]
        else:
            midpoints[iv] = _FALLBACK_MIDPOINTS[iv]

    expected_pct = sum(probs[iv] * midpoints[iv] for iv in INTERVALS)
    return current_close * (1 + expected_pct / 100)


# ── Step 12：Trading Signal ───────────────────────────────────────────────────

_ATR_K: dict[str, str] = {"R1": "atr_k_r1", "R2": "atr_k_r2", "R3": "atr_k_r3"}
_TP_BOUNDS: dict[str, tuple[float, float]] = {
    "R1": (0.5, 2.0), "R2": (2.0, 4.0), "R3": (4.0, 7.0)
}


def _trading_signal(
    most_likely: str,
    current_close: float,
    atr: float,
    confidence: float,
    params: dict,
) -> dict | None:
    if most_likely not in {"R1", "R2", "R3"}:
        return None

    k = params[_ATR_K[most_likely]]
    stop_loss = current_close - k * atr
    stop_loss_pct = (stop_loss / current_close - 1) * 100

    lower, upper = _TP_BOUNDS[most_likely]
    target_pct = lower + confidence * (upper - lower)
    take_profit = current_close * (1 + target_pct / 100)
    take_profit_pct = target_pct

    if confidence >= 0.40 and most_likely in {"R2", "R3"}:
        strength = "Strong"
    elif confidence >= 0.25 and most_likely in {"R1", "R2"}:
        strength = "Moderate"
    else:
        strength = "Weak"

    return {
        "stop_loss": round(stop_loss, 2),
        "stop_loss_pct": round(stop_loss_pct, 2),
        "take_profit": round(take_profit, 2),
        "take_profit_pct": round(take_profit_pct, 2),
        "strength": strength,
    }
```

- [ ] **Step 4：執行測試，確認 PASS**

```bash
pytest tests/tools/predictors/test_algorithm.py -k "combine or confidence or trading_signal" -v
```

- [ ] **Step 5：Commit**

```bash
git add tools/predictors/algorithm.py tests/tools/predictors/test_algorithm.py
git commit -m "feat: add combine, confidence, projected close, trading signal (Steps 9-12)"
```

---

### Task 7：公開 API `predict()` + `backtest()`

**Files:**
- Modify: `tools/predictors/algorithm.py`
- Modify: `tools/predictors/__init__.py`
- Modify: `tests/tools/predictors/test_algorithm.py`

- [ ] **Step 1：新增 predict() / backtest() 測試**

```python
# ── Public API ───────────────────────────────────────────────────────────────

def test_predict_returns_required_keys(sample_ohlcv):
    from tools.predictors.algorithm import predict, DEFAULT_PARAMS
    df = sample_ohlcv.copy()
    result = predict(df, DEFAULT_PARAMS)
    for key in ["most_likely", "probs", "confidence", "projected_close",
                "current_close", "signal", "regime"]:
        assert key in result, f"missing key: {key}"


def test_predict_most_likely_in_intervals(sample_ohlcv):
    from tools.predictors.algorithm import predict, DEFAULT_PARAMS, INTERVALS
    result = predict(sample_ohlcv.copy(), DEFAULT_PARAMS)
    assert result["most_likely"] in INTERVALS


def test_predict_probs_sum_to_one(sample_ohlcv):
    from tools.predictors.algorithm import predict, DEFAULT_PARAMS
    result = predict(sample_ohlcv.copy(), DEFAULT_PARAMS)
    assert abs(sum(result["probs"].values()) - 1.0) < 1e-6


def test_predict_signal_none_for_bearish(sample_ohlcv):
    """強制讓 most_likely = S，確認 signal = None。"""
    from tools.predictors import algorithm
    from tools.predictors.algorithm import predict, DEFAULT_PARAMS
    import unittest.mock as mock

    # Force probs so most_likely = S
    forced_probs = {"S": 0.9, "F0": 0.025, "R1": 0.025, "R2": 0.025, "R3": 0.025}
    with mock.patch.object(algorithm, "_combine", return_value=forced_probs):
        result = predict(sample_ohlcv.copy(), DEFAULT_PARAMS)
    assert result["signal"] is None


def test_backtest_returns_metrics(sample_ohlcv):
    from tools.predictors.algorithm import backtest, DEFAULT_PARAMS
    result = backtest(sample_ohlcv.copy(), DEFAULT_PARAMS, window=10)
    for key in ["direction_acc", "exact_hit_rate", "adjacent_hit_rate", "n_predictions"]:
        assert key in result
    assert 0.0 <= result["direction_acc"] <= 1.0
    assert result["n_predictions"] >= 0
```

- [ ] **Step 2：執行測試，確認 FAIL**

```bash
pytest tests/tools/predictors/test_algorithm.py -k "predict or backtest" -v
```

- [ ] **Step 3：實作 `predict()` 和 `backtest()`（追加到 algorithm.py 末尾）**

```python
# ── Public API ───────────────────────────────────────────────────────────────

def predict(df: pd.DataFrame, params: dict | None = None) -> dict:
    """
    Run full prediction pipeline (Steps 2–12).
    df: OHLCV DataFrame sorted ascending by date.
    Returns prediction result dict.
    """
    p = {**DEFAULT_PARAMS, **(params or {})}
    lookback = p["lookback_days"]
    df = df.tail(lookback).reset_index(drop=True)

    # Step 2
    df = _compute_indicators(df)

    # Step 3 — regime of latest day
    last = df.iloc[-1]
    latest_regime = _detect_regime(
        close=last["close"],
        ma5=last.get("ma5"),
        ma10=last.get("ma10"),
    )

    # Step 4 — encode all symbols
    symbols, dates = _encode_symbols_from_df(df, p)

    # Regime filtering
    n = p["n_order"]
    regimes = [
        _detect_regime(row["close"], row.get("ma5"), row.get("ma10"))
        for _, row in df.iterrows()
    ]
    regime_indices = [i for i, r in enumerate(regimes) if r == latest_regime]
    if len(regime_indices) >= n * 5:
        filtered_symbols = [symbols[i] for i in regime_indices]
        filtered_dates   = [dates[i]   for i in regime_indices]
    else:
        filtered_symbols, filtered_dates = symbols, dates

    # Step 5
    graph = _build_debruijn_graph(filtered_symbols, n, filtered_dates)

    # Current node from full (unfiltered) sequence
    current_node = tuple(symbols[-n:])
    ref_date = dates[-1]

    # Step 6
    markov_dist = _markov_distribution(graph, current_node, ref_date, p)

    # Step 7
    pagerank_dist = _pagerank_distribution(graph, ref_date, p)

    # Step 8
    indicator_dist = _indicator_distribution(symbols[-1])

    # Step 9
    probs = _combine(markov_dist, pagerank_dist, indicator_dist, p)

    # Step 10
    conf = _confidence(probs)

    # Step 11
    projected = _projected_close(probs, df, float(last["close"]))

    # Step 12
    most_likely = max(probs, key=lambda k: probs[k])
    atr = float(last["atr14"]) if not np.isnan(last.get("atr14", float("nan"))) else 0.0
    signal = _trading_signal(most_likely, float(last["close"]), atr, conf, p)

    return {
        "most_likely": most_likely,
        "probs": probs,
        "confidence": round(conf, 4),
        "projected_close": round(projected, 2),
        "current_close": round(float(last["close"]), 2),
        "signal": signal,
        "regime": latest_regime,
        "date": str(last["date"]),
    }


_ADJACENT: dict[str, set[str]] = {
    "S":  {"S", "F0"},
    "F0": {"S", "F0", "R1"},
    "R1": {"F0", "R1", "R2"},
    "R2": {"R1", "R2", "R3"},
    "R3": {"R2", "R3"},
}

_BULLISH = {"R1", "R2", "R3"}
_BEARISH = {"S"}


def backtest(df: pd.DataFrame, params: dict | None = None, window: int = 60) -> dict:
    """
    Walk-forward backtest over the last `window` rows.
    Returns {direction_acc, exact_hit_rate, adjacent_hit_rate, n_predictions}.
    """
    p = {**DEFAULT_PARAMS, **(params or {})}
    df = df.reset_index(drop=True)
    n_rows = len(df)
    min_rows = p["n_order"] + 20  # minimum history for first prediction

    results = []
    for i in range(max(min_rows, n_rows - window), n_rows - 1):
        history = df.iloc[:i]
        actual_row = df.iloc[i + 1]
        actual_prev = df.iloc[i]["close"]
        actual_close = actual_row["close"]
        actual_pct = (actual_close / actual_prev - 1) * 100
        actual_iv = _interval_token(actual_pct, p)

        try:
            result = predict(history, p)
        except Exception:
            continue

        predicted = result["most_likely"]
        is_exact = predicted == actual_iv
        is_direction = (
            (predicted in _BULLISH and actual_iv in _BULLISH)
            or (predicted in _BEARISH and actual_iv in _BEARISH)
            or (predicted == "F0" and actual_iv == "F0")
        )
        is_adjacent = actual_iv in _ADJACENT.get(predicted, {predicted})

        results.append({
            "exact": is_exact,
            "direction": is_direction,
            "adjacent": is_adjacent,
        })

    n = len(results)
    if n == 0:
        return {"direction_acc": 0.0, "exact_hit_rate": 0.0,
                "adjacent_hit_rate": 0.0, "n_predictions": 0}

    return {
        "direction_acc":      round(sum(r["direction"] for r in results) / n, 4),
        "exact_hit_rate":     round(sum(r["exact"] for r in results) / n, 4),
        "adjacent_hit_rate":  round(sum(r["adjacent"] for r in results) / n, 4),
        "n_predictions": n,
    }
```

- [ ] **Step 4：更新 `tools/predictors/__init__.py`**

```python
from tools.predictors.algorithm import DEFAULT_PARAMS, INTERVALS, backtest, predict

__all__ = ["predict", "backtest", "DEFAULT_PARAMS", "INTERVALS"]
```

- [ ] **Step 5：執行所有 algorithm 測試，確認全 PASS**

```bash
pytest tests/tools/predictors/ -v
```

- [ ] **Step 6：Commit**

```bash
git add tools/predictors/ tests/tools/predictors/
git commit -m "feat: add predict() and backtest() public API, complete algorithm.py"
```

---

## Phase 2：資料層

---

### Task 8：FinMind OHLCV Fetcher（增量 CSV 快取）

**Files:**
- Create: `tools/fetchers/finmind.py`
- Create: `tests/tools/fetchers/test_finmind.py`

- [ ] **Step 1：新增 FinMind 測試**

建立 `tests/tools/fetchers/test_finmind.py`：

```python
"""tests/tools/fetchers/test_finmind.py"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest


MOCK_RESPONSE = {
    "data": [
        {"date": "2025-01-02", "open": 100.0, "high": 102.0,
         "low": 99.0, "close": 101.0, "Trading_Volume": 5000},
        {"date": "2025-01-03", "open": 101.0, "high": 103.5,
         "low": 100.5, "close": 103.0, "Trading_Volume": 6000},
    ]
}


def test_fetch_ohlcv_returns_dataframe():
    from tools.fetchers.finmind import fetch_ohlcv
    with patch("tools.fetchers.finmind._api_get", return_value=MOCK_RESPONSE):
        df = fetch_ohlcv("2330", "2025-01-01", "2025-01-03", token="test")
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert len(df) == 2


def test_fetch_ohlcv_sorted_ascending():
    from tools.fetchers.finmind import fetch_ohlcv
    reversed_data = {"data": list(reversed(MOCK_RESPONSE["data"]))}
    with patch("tools.fetchers.finmind._api_get", return_value=reversed_data):
        df = fetch_ohlcv("2330", "2025-01-01", "2025-01-03", token="test")
    assert df.iloc[0]["date"] == "2025-01-02"


def test_fetch_incremental_creates_csv(tmp_path):
    from tools.fetchers.finmind import fetch_incremental
    with patch("tools.fetchers.finmind._api_get", return_value=MOCK_RESPONSE):
        df = fetch_incremental("2330", data_dir=tmp_path, token="test",
                               initial_days=365)
    csv_path = tmp_path / "2330.csv"
    assert csv_path.exists()
    assert len(df) == 2


def test_fetch_incremental_appends_new_rows(tmp_path):
    from tools.fetchers.finmind import fetch_incremental
    # First run: 2 rows
    with patch("tools.fetchers.finmind._api_get", return_value=MOCK_RESPONSE):
        fetch_incremental("2330", data_dir=tmp_path, token="test", initial_days=365)

    new_data = {"data": [{"date": "2025-01-06", "open": 103.0, "high": 105.0,
                          "low": 102.0, "close": 104.0, "Trading_Volume": 7000}]}
    # Second run: 1 new row
    with patch("tools.fetchers.finmind._api_get", return_value=new_data):
        df = fetch_incremental("2330", data_dir=tmp_path, token="test", initial_days=365)
    assert len(df) == 3


def test_load_ohlcv_respects_lookback(tmp_path):
    from tools.fetchers.finmind import fetch_incremental, load_ohlcv
    with patch("tools.fetchers.finmind._api_get", return_value=MOCK_RESPONSE):
        fetch_incremental("2330", data_dir=tmp_path, token="test", initial_days=365)
    df = load_ohlcv("2330", data_dir=tmp_path, lookback_days=1)
    assert len(df) == 1
```

- [ ] **Step 2：執行測試，確認 FAIL**

```bash
pytest tests/tools/fetchers/test_finmind.py -v
```

- [ ] **Step 3：實作 `tools/fetchers/finmind.py`**

```python
"""tools/fetchers/finmind.py

FinMind API OHLCV 抓取 + 增量 CSV 快取。

API endpoint:
    GET https://api.finmindtrade.com/api/v4/data
    ?dataset=TaiwanStockPrice&data_id={ticker}&start_date={start}&token={token}
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
_REQUIRED_COLS = ["date", "open", "high", "low", "close", "volume"]


def _api_get(ticker: str, start_date: str, token: str) -> dict:
    url = (
        f"{FINMIND_API_URL}?dataset=TaiwanStockPrice"
        f"&data_id={ticker}&start_date={start_date}&token={token}"
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_ohlcv(
    ticker: str, start_date: str, end_date: str, token: str
) -> pd.DataFrame:
    """從 FinMind API 抓取 OHLCV，回傳標準化 DataFrame（升序排列）。"""
    data = _api_get(ticker, start_date, token)
    rows = data.get("data", [])
    if not rows:
        return pd.DataFrame(columns=_REQUIRED_COLS)

    df = pd.DataFrame(rows)
    df = df.rename(columns={"Trading_Volume": "volume"})
    df = df[_REQUIRED_COLS].copy()
    df = df[df["date"] <= end_date]
    df = df.sort_values("date").reset_index(drop=True)
    return df


def fetch_incremental(
    ticker: str,
    data_dir: Path,
    token: str,
    initial_days: int = 1250,
) -> pd.DataFrame:
    """
    讀取本地 CSV，補抓缺失資料，存回 CSV，回傳完整 DataFrame。
    首次執行時抓取 initial_days 天的歷史。
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
```

- [ ] **Step 4：執行測試，確認 PASS**

```bash
pytest tests/tools/fetchers/test_finmind.py -v
```

- [ ] **Step 5：Commit**

```bash
git add tools/fetchers/finmind.py tests/tools/fetchers/test_finmind.py
git commit -m "feat: add FinMind OHLCV fetcher with incremental CSV cache"
```

---

## Phase 3：Stock Predictor Agent

---

### Task 9：Config + 交易日判斷

**Files:**
- Create: `agents/stock_predictor/__init__.py`
- Create: `agents/stock_predictor/config.py`
- Create: `agents/stock_predictor/prompts.py`

- [ ] **Step 1：建立空 `__init__.py` 和 `prompts.py`**

```bash
touch agents/stock_predictor/__init__.py
```

`agents/stock_predictor/prompts.py`：
```python
"""agents/stock_predictor/prompts.py — 預留，目前無 LLM 呼叫。"""
```

- [ ] **Step 2：建立 `agents/stock_predictor/config.py`**

```python
"""agents/stock_predictor/config.py"""
from __future__ import annotations

import json
from pathlib import Path

# ── 路徑常數 ─────────────────────────────────────────────────────────────────

REPO_ROOT    = Path(__file__).parent.parent.parent
DATA_DIR     = REPO_ROOT / "data"
OHLCV_DIR    = DATA_DIR / "ohlcv"
PARAMS_DIR   = DATA_DIR / "model_params"
STATS_DIR    = DATA_DIR / "stats"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"
OUTPUTS_DIR  = REPO_ROOT / "outputs" / "stock-predictor"
HOLIDAYS_FILE = REPO_ROOT / "tw_holidays.json"

for _d in [OHLCV_DIR, PARAMS_DIR, STATS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)


# ── 交易日工具 ────────────────────────────────────────────────────────────────

def _load_holidays() -> set[str]:
    if not HOLIDAYS_FILE.exists():
        return set()
    data = json.loads(HOLIDAYS_FILE.read_text())
    holidays: set[str] = set()
    for dates in data.values():
        holidays.update(dates)
    return holidays


_HOLIDAYS = _load_holidays()


def is_trading_day(d: str) -> bool:
    """d = 'YYYY-MM-DD'。週六日 + 台灣假日 → False。"""
    from datetime import date
    dt = date.fromisoformat(d)
    if dt.weekday() >= 5:
        return False
    return d not in _HOLIDAYS


def prev_trading_day(d: str) -> str:
    """回傳 d 之前最近的交易日（不含 d 本身）。"""
    from datetime import date, timedelta
    dt = date.fromisoformat(d)
    dt -= timedelta(days=1)
    while not is_trading_day(dt.isoformat()):
        dt -= timedelta(days=1)
    return dt.isoformat()


# ── Watchlist ─────────────────────────────────────────────────────────────────

def load_watchlist() -> list[str]:
    if not WATCHLIST_FILE.exists():
        return []
    data = json.loads(WATCHLIST_FILE.read_text())
    return data.get("stocks", [])


# ── Model Params ──────────────────────────────────────────────────────────────

def load_params(ticker: str) -> dict:
    from tools.predictors.algorithm import DEFAULT_PARAMS
    path = PARAMS_DIR / f"{ticker}.json"
    if not path.exists():
        return dict(DEFAULT_PARAMS)
    data = json.loads(path.read_text())
    return {**DEFAULT_PARAMS, **data.get("params", {})}
```

- [ ] **Step 3：驗證 config import 正常**

```bash
python3 -c "from agents.stock_predictor.config import is_trading_day; print(is_trading_day('2025-01-01'))"
```

預期輸出：`False`（元旦假日）

- [ ] **Step 4：Commit**

```bash
git add agents/stock_predictor/
git commit -m "feat: add stock_predictor config with trading day utilities"
```

---

### Task 10：Predictor Agent — verify + predict + notify

**Files:**
- Create: `agents/stock_predictor/agent.py`
- Create: `tests/agents/stock_predictor/test_agent.py`

- [ ] **Step 1：建立測試目錄結構**

```bash
mkdir -p tests/agents/stock_predictor
touch tests/agents/__init__.py tests/agents/stock_predictor/__init__.py
```

- [ ] **Step 2：撰寫 predictor agent 測試**

建立 `tests/agents/stock_predictor/test_agent.py`：

```python
"""tests/agents/stock_predictor/test_agent.py"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def tmp_data_dirs(tmp_path, monkeypatch):
    """Patch config paths to tmp_path."""
    import agents.stock_predictor.config as cfg
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "OHLCV_DIR", tmp_path / "ohlcv")
    monkeypatch.setattr(cfg, "PARAMS_DIR", tmp_path / "params")
    monkeypatch.setattr(cfg, "STATS_DIR", tmp_path / "stats")
    monkeypatch.setattr(cfg, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(cfg, "WATCHLIST_FILE", tmp_path / "watchlist.json")
    for d in ["ohlcv", "params", "stats", "outputs"]:
        (tmp_path / d).mkdir()
    return tmp_path


def test_agent_name():
    from agents.stock_predictor.agent import StockPredictorAgent
    assert StockPredictorAgent.AGENT_NAME == "stock_predictor"


def test_run_skips_on_non_trading_day(tmp_data_dirs):
    from agents.stock_predictor.agent import StockPredictorAgent
    agent = StockPredictorAgent(llm=MagicMock())
    with patch("agents.stock_predictor.agent.is_trading_day", return_value=False):
        result = agent.run("")
    assert "非交易日" in result


def test_run_empty_watchlist(tmp_data_dirs):
    from agents.stock_predictor.agent import StockPredictorAgent
    # watchlist.json not created → empty list
    agent = StockPredictorAgent(llm=MagicMock())
    with patch("agents.stock_predictor.agent.is_trading_day", return_value=True):
        result = agent.run("")
    assert "watchlist" in result.lower() or "空" in result


def test_format_signal_card_r2():
    from agents.stock_predictor.agent import _format_signal_card
    prediction = {
        "most_likely": "R2",
        "confidence": 0.62,
        "projected_close": 940.5,
        "current_close": 920.0,
        "regime": "Bull",
        "signal": {
            "stop_loss": 902.0,
            "stop_loss_pct": -1.96,
            "take_profit": 940.0,
            "take_profit_pct": 2.17,
            "strength": "Moderate",
        },
    }
    card = _format_signal_card("2330", prediction)
    assert "2330" in card
    assert "R2" in card
    assert "62%" in card
    assert "902" in card  # stop loss
```

- [ ] **Step 3：執行測試，確認 FAIL**

```bash
pytest tests/agents/stock_predictor/test_agent.py -v
```

- [ ] **Step 4：實作 `agents/stock_predictor/agent.py`**

```python
"""agents/stock_predictor/agent.py

每日台股預測 Agent。
流程：交易日判斷 → 隔日驗證 → 全 watchlist 預測 → Telegram 推送。
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from config import get_logger
from config.settings import LLMBackend
from tools.fetchers.finmind import fetch_incremental, load_ohlcv
from tools.notifiers.telegram import send as telegram_send

from .config import (
    OHLCV_DIR, OUTPUTS_DIR, PARAMS_DIR, STATS_DIR,
    is_trading_day, load_params, load_watchlist, prev_trading_day,
)

logger = get_logger(__name__)

FINMIND_TOKEN_ENV = "FINMIND_API_TOKEN"


class StockPredictorAgent:
    AGENT_NAME = "stock_predictor"

    def __init__(self, llm: LLMBackend | None = None) -> None:
        self._llm = llm

    def run(self, args: str = "") -> str:
        import os
        today = date.today().isoformat()

        if not is_trading_day(today):
            logger.info("非交易日 %s，跳過預測", today)
            return f"非交易日（{today}），跳過預測。"

        watchlist = load_watchlist()
        if not watchlist:
            return "watchlist 為空，請先透過 Telegram Bot /watch <ticker> 新增股票。"

        token = os.environ.get(FINMIND_TOKEN_ENV, "")
        yesterday = prev_trading_day(today)

        # 隔日驗證
        self._verify(yesterday, token)

        # 並行預測
        signals: list[str] = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self._predict_one, ticker, today, token): ticker
                for ticker in watchlist
            }
            for fut in as_completed(futures):
                ticker = futures[fut]
                try:
                    card = fut.result()
                    if card:
                        signals.append(card)
                except Exception as e:
                    logger.warning("預測 %s 失敗：%s", ticker, e)

        if not signals:
            msg = f"📊 今日無多頭訊號（共掃描 {len(watchlist)} 支）"
            telegram_send(msg)
            return msg

        for card in signals:
            telegram_send(card)

        return f"已發送 {len(signals)} 支股票訊號。"

    # ── 隔日驗證 ──────────────────────────────────────────────────────────────

    def _verify(self, yesterday: str, token: str) -> None:
        from tools.predictors.algorithm import _interval_token, DEFAULT_PARAMS

        outputs_yesterday = OUTPUTS_DIR / yesterday / "predictions"
        if not outputs_yesterday.exists():
            return

        for pred_file in outputs_yesterday.glob("*.json"):
            ticker = pred_file.stem
            try:
                pred = json.loads(pred_file.read_text())
                df = fetch_incremental(ticker, OHLCV_DIR, token)
                if df.empty:
                    continue

                yesterday_rows = df[df["date"] == yesterday]
                if yesterday_rows.empty:
                    continue

                actual_close = float(yesterday_rows.iloc[0]["close"])
                prev_rows = df[df["date"] < yesterday]
                if prev_rows.empty:
                    continue
                prev_close = float(prev_rows.iloc[-1]["close"])

                actual_pct = (actual_close / prev_close - 1) * 100
                actual_iv = _interval_token(actual_pct, DEFAULT_PARAMS)

                predicted = pred.get("most_likely", "F0")
                _bullish = {"R1", "R2", "R3"}
                is_exact = predicted == actual_iv
                is_direction = (
                    (predicted in _bullish and actual_iv in _bullish)
                    or predicted == actual_iv
                )

                _adjacent = {"S": {"S","F0"}, "F0": {"S","F0","R1"},
                             "R1": {"F0","R1","R2"}, "R2": {"R1","R2","R3"}, "R3": {"R2","R3"}}
                is_adjacent = actual_iv in _adjacent.get(predicted, {predicted})
                self._update_stats(ticker, is_exact, is_direction, is_adjacent)
            except Exception as e:
                logger.warning("驗證 %s 失敗：%s", ticker, e)

    def _update_stats(self, ticker: str, is_exact: bool, is_direction: bool, is_adjacent: bool) -> None:
        stats_file = STATS_DIR / f"{ticker}.json"
        stats = json.loads(stats_file.read_text()) if stats_file.exists() else {
            "total": 0, "direction_correct": 0, "exact_hit": 0, "adjacent_hit": 0,
        }
        stats["total"] += 1
        if is_direction:
            stats["direction_correct"] += 1
        if is_exact:
            stats["exact_hit"] += 1
        if is_adjacent:
            stats.setdefault("adjacent_hit", 0)
            stats["adjacent_hit"] += 1

        n = stats["total"]
        stats["direction_acc"]      = round(stats["direction_correct"] / n, 4)
        stats["exact_hit_rate"]     = round(stats["exact_hit"] / n, 4)
        stats["adjacent_hit_rate"]  = round(stats.get("adjacent_hit", 0) / n, 4)
        stats_file.write_text(json.dumps(stats, indent=2, ensure_ascii=False))

    # ── 單股預測 ──────────────────────────────────────────────────────────────

    def _predict_one(self, ticker: str, today: str, token: str) -> str | None:
        from tools.predictors.algorithm import predict

        df = fetch_incremental(ticker, OHLCV_DIR, token)
        if df.empty or len(df) < 20:
            logger.warning("%s 資料不足，跳過", ticker)
            return None

        params = load_params(ticker)
        result = predict(df, params)
        result["ticker"] = ticker

        # 存 artifact
        out_dir = OUTPUTS_DIR / today / "predictions"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{ticker}.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False)
        )

        if result["most_likely"] not in {"R1", "R2", "R3"}:
            return None

        return _format_signal_card(ticker, result)


def _format_signal_card(ticker: str, pred: dict) -> str:
    most_likely = pred["most_likely"]
    conf_pct = int(pred["confidence"] * 100)
    proj = pred["projected_close"]
    sig = pred.get("signal") or {}

    lines = [
        f"📈 <b>{ticker}</b> [{most_likely}] 信心 {conf_pct}%",
        f"預計收盤：<code>{proj}</code>",
    ]
    if sig:
        lines += [
            f"止損：{sig['stop_loss']}（{sig['stop_loss_pct']:.1f}%）",
            f"止盈：{sig['take_profit']}（+{sig['take_profit_pct']:.1f}%）",
            f"強度：{sig['strength']} ｜ 13:20 強制出場",
        ]
    return "\n".join(lines)
```

- [ ] **Step 5：執行測試，確認 PASS**

```bash
pytest tests/agents/stock_predictor/test_agent.py -v
```

- [ ] **Step 6：Commit**

```bash
git add agents/stock_predictor/ tests/agents/
git commit -m "feat: add stock_predictor agent with verify, predict, notify flow"
```

---

### Task 11：路由整合（stock_predictor）

**Files:**
- Modify: `main.py`
- Modify: `AGENTS.md`

- [ ] **Step 1：更新 `main.py`**

在 `main.py` 的 import 區塊後加入：

```python
from agents.stock_predictor import StockPredictorAgent
```

在 `SKILL_MAP` list 中新增：

```python
    (["/stock-predict", "跑股票預測"], StockPredictorAgent),
```

- [ ] **Step 2：更新 `agents/stock_predictor/__init__.py`**

```python
from agents.stock_predictor.agent import StockPredictorAgent

__all__ = ["StockPredictorAgent"]
```

- [ ] **Step 3：更新 `AGENTS.md` Agent 路由表**（在現有表格後追加）

```markdown
| `stock_predictor` | `/stock-predict`、`跑股票預測` | `agents/stock_predictor/agent.py` |
```

並在 Tools 表格後追加：
```markdown
| `tools/fetchers/finmind.py` | FinMind OHLCV 抓取 + 增量 CSV 快取 |
| `tools/predictors/algorithm.py` | ALGORITHM.md Step 2–12 純函數實作 |
| `tools/notifiers/telegram_bot.py` | 長駐 Telegram Bot（watchlist 管理） |
```

- [ ] **Step 4：驗證路由**

```bash
python3 -c "
from main import route
cls, args = route('/stock-predict')
print(cls.AGENT_NAME)
"
```

預期輸出：`stock_predictor`

- [ ] **Step 5：Commit**

```bash
git add main.py agents/stock_predictor/__init__.py AGENTS.md
git commit -m "feat: add stock_predictor route to main.py and AGENTS.md"
```

---

## Phase 4：Telegram Bot

---

### Task 12：Telegram Bot（Watchlist 管理）

**Files:**
- Create: `tools/notifiers/telegram_bot.py`

- [ ] **Step 1：安裝依賴**

```bash
pip install python-telegram-bot
```

- [ ] **Step 2：設定 Telegram Bot token**

確認 `Scripts/.env` 有：
```
TELEGRAM_BOT_TOKEN=<your_bot_token>
TELEGRAM_CHAT_ID=<your_chat_id>
```

- [ ] **Step 3：實作 `tools/notifiers/telegram_bot.py`**

```python
"""tools/notifiers/telegram_bot.py

長駐 Telegram Bot，負責 watchlist CRUD。
啟動方式：python3 -m tools.notifiers.telegram_bot

支援指令：
  /watch 2330       加入 watchlist
  /unwatch 2330     移除 watchlist
  /watchlist        列出所有追蹤股票
  /stats 2330       顯示準確率統計
  /predict 2330     立即觸發單股預測
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ── 路徑（與 stock_predictor config 一致） ────────────────────────────────────
REPO_ROOT    = Path(__file__).parent.parent.parent
DATA_DIR     = REPO_ROOT / "data"
WATCHLIST    = DATA_DIR / "watchlist.json"
STATS_DIR    = DATA_DIR / "stats"
DATA_DIR.mkdir(exist_ok=True)


# ── Watchlist 操作 ────────────────────────────────────────────────────────────

def _read_watchlist() -> dict:
    if WATCHLIST.exists():
        return json.loads(WATCHLIST.read_text())
    return {"stocks": [], "added_at": {}}


def _save_watchlist(data: dict) -> None:
    WATCHLIST.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ── 指令處理器 ────────────────────────────────────────────────────────────────

async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("用法：/watch <ticker>，例：/watch 2330")
        return

    ticker = context.args[0].strip().upper()
    data = _read_watchlist()

    if ticker in data["stocks"]:
        await update.message.reply_text(f"⚠️ {ticker} 已在 watchlist 中。")
        return

    data["stocks"].append(ticker)
    data["added_at"][ticker] = date.today().isoformat()
    _save_watchlist(data)
    await update.message.reply_text(
        f"✅ 已加入 {ticker}。\n"
        f"請等待排程執行時自動抓取歷史資料，或執行 /predict {ticker}。"
    )


async def cmd_unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("用法：/unwatch <ticker>，例：/unwatch 2330")
        return

    ticker = context.args[0].strip().upper()
    data = _read_watchlist()

    if ticker not in data["stocks"]:
        await update.message.reply_text(f"⚠️ {ticker} 不在 watchlist 中。")
        return

    data["stocks"].remove(ticker)
    data["added_at"].pop(ticker, None)
    _save_watchlist(data)
    await update.message.reply_text(f"✅ 已移除 {ticker}。")


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = _read_watchlist()
    stocks = data.get("stocks", [])
    if not stocks:
        await update.message.reply_text("watchlist 為空。用 /watch <ticker> 新增。")
        return
    lines = [f"• {t}（加入：{data['added_at'].get(t, '?')}）" for t in stocks]
    msg = f"目前追蹤 {len(stocks)} 支：\n" + "\n".join(lines)
    await update.message.reply_text(msg)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("用法：/stats <ticker>，例：/stats 2330")
        return

    ticker = context.args[0].strip().upper()
    stats_file = STATS_DIR / f"{ticker}.json"

    if not stats_file.exists():
        await update.message.reply_text(f"⚠️ {ticker} 尚無預測紀錄。")
        return

    stats = json.loads(stats_file.read_text())
    msg = (
        f"📊 <b>{ticker}</b> 預測統計\n"
        f"樣本數：{stats.get('total', 0)}\n"
        f"方向準確率：{stats.get('direction_acc', 0):.1%}\n"
        f"完全命中率：{stats.get('exact_hit_rate', 0):.1%}"
    )
    await update.message.reply_html(msg)


async def cmd_predict(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("用法：/predict <ticker>，例：/predict 2330")
        return

    ticker = context.args[0].strip().upper()
    await update.message.reply_text(f"⏳ 正在預測 {ticker}...")

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), f"/stock-predict --only {ticker}"],
        capture_output=True, text=True, cwd=REPO_ROOT
    )
    reply = result.stdout.strip() or result.stderr.strip() or "完成（無輸出）"
    await update.message.reply_text(reply[:4000])


# ── 啟動 ─────────────────────────────────────────────────────────────────────

def run() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        # 嘗試從 Scripts/.env 讀取
        env_path = REPO_ROOT.parent / "Second-Brain" / "Scripts" / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not found in env or Scripts/.env")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("watch",     cmd_watch))
    app.add_handler(CommandHandler("unwatch",   cmd_unwatch))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("stats",     cmd_stats))
    app.add_handler(CommandHandler("predict",   cmd_predict))

    print("Telegram Bot 已啟動，監聽指令中…")
    app.run_polling()


if __name__ == "__main__":
    run()
```

- [ ] **Step 4：手動測試 Bot 啟動（確認無語法錯誤）**

```bash
python3 -c "import tools.notifiers.telegram_bot; print('import ok')"
```

- [ ] **Step 5：Commit**

```bash
git add tools/notifiers/telegram_bot.py
git commit -m "feat: add Telegram Bot for watchlist management"
```

---

## Phase 5：Stock Analyst Agent

---

### Task 13：策略變體 Config + Analyst Agent

**Files:**
- Create: `agents/stock_analyst/__init__.py`
- Create: `agents/stock_analyst/config.py`
- Create: `agents/stock_analyst/prompts.py`
- Create: `agents/stock_analyst/agent.py`
- Create: `tests/agents/stock_analyst/test_agent.py`

- [ ] **Step 1：建立骨架**

```bash
touch agents/stock_analyst/__init__.py
mkdir -p tests/agents/stock_analyst
touch tests/agents/stock_analyst/__init__.py
```

- [ ] **Step 2：建立 `agents/stock_analyst/config.py`**

```python
"""agents/stock_analyst/config.py — 策略變體定義。"""
from __future__ import annotations

from tools.predictors.algorithm import DEFAULT_PARAMS

STRATEGY_VARIANTS: dict[str, dict] = {
    "v1_pure_markov": {
        **DEFAULT_PARAMS,
        "lambda1": 1.0, "lambda2": 0.0, "lambda3": 0.0,
    },
    "v2_markov_pagerank": {
        **DEFAULT_PARAMS,
        "lambda1": 0.6, "lambda2": 0.4, "lambda3": 0.0,
    },
    "v3_default": dict(DEFAULT_PARAMS),
    "v4_high_order": {
        **DEFAULT_PARAMS,
        "n_order": 6,
    },
    "v5_no_indicator": {
        **DEFAULT_PARAMS,
        "lambda1": 0.65, "lambda2": 0.35, "lambda3": 0.0,
    },
    "v6_no_decay": {
        **DEFAULT_PARAMS,
        "decay_gamma": 0.0,
    },
}

BACKTEST_WINDOW = 60  # walk-forward 回測筆數
```

- [ ] **Step 3：建立 `agents/stock_analyst/prompts.py`**

```python
"""agents/stock_analyst/prompts.py"""


def comparison_prompt(ticker: str, variant_results: dict[str, dict], current_stats: dict) -> str:
    rows = "\n".join(
        f"  {name}: direction_acc={m['direction_acc']:.1%}, "
        f"exact_hit={m['exact_hit_rate']:.1%}, adjacent={m['adjacent_hit_rate']:.1%}, "
        f"n={m['n_predictions']}"
        for name, m in variant_results.items()
    )
    current_acc = current_stats.get("direction_acc", "N/A")
    return f"""你是台股量化策略分析師。以下是股票 {ticker} 在不同預測策略變體下的 walk-forward 回測結果：

{rows}

目前線上版本的歷史方向準確率：{current_acc}

變體說明：
- v1_pure_markov：只用馬可夫轉移概率（λ1=1.0）
- v2_markov_pagerank：馬可夫 + PageRank（不含技術指標信號）
- v3_default：完整三組合（ALGORITHM.md 預設值）
- v4_high_order：n_order=6（長記憶，捕捉更長序列模式）
- v5_no_indicator：不使用技術指標信號（λ3=0，純量化序列）
- v6_no_decay：不做時間衰減（所有歷史等權）

請：
1. 比較各變體的優缺點（表格 + 文字說明）
2. 指出當前算法（v3）的具體弱點
3. 提出 2–3 條具體可實作的改良建議（例如調整某參數範圍、改變 regime 過濾條件等）

用繁體中文回應，重點清晰，不超過 600 字。"""
```

- [ ] **Step 4：撰寫 analyst agent 測試**

建立 `tests/agents/stock_analyst/test_agent.py`：

```python
"""tests/agents/stock_analyst/test_agent.py"""
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
import pytest


@pytest.fixture
def sample_df():
    np.random.seed(0)
    n = 80
    dates = pd.bdate_range("2024-01-01", periods=n).strftime("%Y-%m-%d").tolist()
    close = 100.0 * np.cumprod(1 + np.random.normal(0.001, 0.015, n))
    open_ = close * (1 + np.random.normal(0, 0.005, n))
    high = np.maximum(close, open_) * (1 + np.abs(np.random.normal(0, 0.008, n)))
    low = np.minimum(close, open_) * (1 - np.abs(np.random.normal(0, 0.008, n)))
    volume = np.random.randint(1000, 10000, n).astype(float)
    return pd.DataFrame({"date": dates, "open": open_, "high": high,
                         "low": low, "close": close, "volume": volume})


def test_agent_name():
    from agents.stock_analyst.agent import StockAnalystAgent
    assert StockAnalystAgent.AGENT_NAME == "stock_analyst"


def test_run_variants_returns_dict(sample_df):
    from agents.stock_analyst.agent import StockAnalystAgent
    from agents.stock_analyst.config import STRATEGY_VARIANTS
    agent = StockAnalystAgent(llm=MagicMock())
    results = agent._run_variants("2330", sample_df)
    assert set(results.keys()) == set(STRATEGY_VARIANTS.keys())
    for metrics in results.values():
        assert "direction_acc" in metrics
        assert 0.0 <= metrics["direction_acc"] <= 1.0


def test_run_empty_watchlist(tmp_path, monkeypatch):
    from agents.stock_analyst import agent as ag_module
    monkeypatch.setattr(ag_module, "load_watchlist", lambda: [])
    from agents.stock_analyst.agent import StockAnalystAgent
    a = StockAnalystAgent(llm=MagicMock())
    result = a.run("")
    assert "watchlist" in result.lower() or "空" in result
```

- [ ] **Step 5：執行測試，確認 FAIL**

```bash
pytest tests/agents/stock_analyst/test_agent.py -v
```

- [ ] **Step 6：實作 `agents/stock_analyst/agent.py`**

```python
"""agents/stock_analyst/agent.py

每週 LLM 策略分析 Agent。
流程：載入 watchlist → 跑各策略變體回測 → LLM 比較 → 報告 + Telegram。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from config import get_llm, get_logger
from config.settings import LLMBackend
from tools.fetchers.finmind import fetch_incremental, load_ohlcv
from tools.notifiers.telegram import send as telegram_send
from tools.predictors.algorithm import backtest

from agents.stock_predictor.config import (
    OHLCV_DIR, OUTPUTS_DIR as PREDICTOR_OUTPUTS, STATS_DIR,
    load_watchlist,
)
from .config import BACKTEST_WINDOW, STRATEGY_VARIANTS
from .prompts import comparison_prompt

logger = get_logger(__name__)

REPO_ROOT   = Path(__file__).parent.parent.parent
OUTPUTS_DIR = REPO_ROOT / "outputs" / "stock-analyst"
FINMIND_TOKEN_ENV = "FINMIND_API_TOKEN"


class StockAnalystAgent:
    AGENT_NAME = "stock_analyst"

    def __init__(self, llm: LLMBackend | None = None) -> None:
        self._llm = llm or get_llm()

    def run(self, args: str = "") -> str:
        import os
        watchlist = load_watchlist()
        if not watchlist:
            return "watchlist 為空，跳過策略分析。"

        token = os.environ.get(FINMIND_TOKEN_ENV, "")
        today = date.today().isoformat()
        out_dir = OUTPUTS_DIR / today
        out_dir.mkdir(parents=True, exist_ok=True)

        all_reports: list[str] = []

        for ticker in watchlist:
            logger.info("分析 %s …", ticker)
            try:
                df = load_ohlcv(ticker, OHLCV_DIR, lookback_days=500)
                if len(df) < 40:
                    logger.warning("%s 資料不足，跳過", ticker)
                    continue

                variant_results = self._run_variants(ticker, df)
                current_stats = self._load_stats(ticker)

                prompt = comparison_prompt(ticker, variant_results, current_stats)
                analysis = self._complete(prompt)

                report_section = f"## {ticker}\n\n{analysis}\n"
                all_reports.append(report_section)

                # 更新 model_params（採用表現最佳的 variant）
                best_variant = max(
                    variant_results,
                    key=lambda v: variant_results[v]["direction_acc"],
                )
                self._save_recommendation(ticker, best_variant, variant_results[best_variant])

            except Exception as e:
                logger.warning("分析 %s 失敗：%s", ticker, e)

        if not all_reports:
            return "所有股票分析均失敗。"

        report_md = f"# 策略分析報告 {today}\n\n" + "\n---\n".join(all_reports)
        report_path = out_dir / "report.md"
        report_path.write_text(report_md, encoding="utf-8")

        # Telegram 發送摘要（前 3 個建議）
        summary_lines = [f"📊 <b>策略分析完成</b> {today}"]
        for ticker in watchlist[:3]:
            section = next((r for r in all_reports if r.startswith(f"## {ticker}")), "")
            if section:
                first_para = section.split("\n\n")[1][:200] if "\n\n" in section else ""
                summary_lines.append(f"\n<b>{ticker}</b>：{first_para.strip()}")
        telegram_send("\n".join(summary_lines))

        return f"策略分析完成，報告已存至 {report_path}"

    def _run_variants(self, ticker: str, df) -> dict[str, dict]:
        results = {}
        for name, params in STRATEGY_VARIANTS.items():
            try:
                results[name] = backtest(df.copy(), params, window=BACKTEST_WINDOW)
            except Exception as e:
                logger.warning("%s 變體 %s 失敗：%s", ticker, name, e)
                results[name] = {
                    "direction_acc": 0.0, "exact_hit_rate": 0.0,
                    "adjacent_hit_rate": 0.0, "n_predictions": 0,
                }
        return results

    def _load_stats(self, ticker: str) -> dict:
        stats_file = STATS_DIR / f"{ticker}.json"
        if stats_file.exists():
            return json.loads(stats_file.read_text())
        return {}

    def _save_recommendation(self, ticker: str, best_variant: str, metrics: dict) -> None:
        params_file = REPO_ROOT / "data" / "model_params" / f"{ticker}.json"
        params_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "ticker": ticker,
            "analyzed_at": date.today().isoformat(),
            "recommended_variant": best_variant,
            "score": metrics.get("direction_acc", 0.0),
            "params": STRATEGY_VARIANTS[best_variant],
        }
        params_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _complete(self, prompt: str) -> str:
        return self._llm.complete(prompt, system=(
            "你是專業台股量化策略分析師。輸出繁體中文。"
        ))
```

- [ ] **Step 7：執行測試，確認 PASS**

```bash
pytest tests/agents/stock_analyst/test_agent.py -v
```

- [ ] **Step 8：Commit**

```bash
git add agents/stock_analyst/ tests/agents/stock_analyst/
git commit -m "feat: add stock_analyst agent with LLM strategy comparison"
```

---

### Task 14：路由整合（stock_analyst）

**Files:**
- Modify: `main.py`
- Modify: `agents/stock_analyst/__init__.py`
- Modify: `AGENTS.md`

- [ ] **Step 1：更新 `main.py`**

在 import 區塊加入：

```python
from agents.stock_analyst import StockAnalystAgent
```

在 `SKILL_MAP` 加入：

```python
    (["/stock-analyze", "跑策略分析"], StockAnalystAgent),
```

- [ ] **Step 2：更新 `agents/stock_analyst/__init__.py`**

```python
from agents.stock_analyst.agent import StockAnalystAgent

__all__ = ["StockAnalystAgent"]
```

- [ ] **Step 3：更新 `AGENTS.md`** Agent 路由表追加：

```markdown
| `stock_analyst` | `/stock-analyze`、`跑策略分析` | `agents/stock_analyst/agent.py` |
```

- [ ] **Step 4：執行完整測試套件**

```bash
pytest tests/ -v --ignore=tests/harness
```

預期：所有新增測試 PASS，無既有測試被破壞。

- [ ] **Step 5：執行 lint 驗證**

```bash
python lint/check_agent_interface.py
```

預期輸出包含 `stock_predictor` 和 `stock_analyst` 均驗證通過。

- [ ] **Step 6：最終 Commit**

```bash
git add main.py agents/stock_analyst/__init__.py AGENTS.md
git commit -m "feat: add stock_analyst route, complete stock predictor system integration"
```

---

## 驗收清單

- [ ] `pytest tests/tools/predictors/` 全 PASS
- [ ] `pytest tests/tools/fetchers/test_finmind.py` 全 PASS
- [ ] `pytest tests/agents/stock_predictor/` 全 PASS
- [ ] `pytest tests/agents/stock_analyst/` 全 PASS
- [ ] `python lint/check_agent_interface.py` 無錯誤
- [ ] `python3 main.py "/stock-predict"` 非交易日時輸出「非交易日，跳過」
- [ ] Telegram Bot `/watch 2330` 回應 ✅
- [ ] n8n workflow 新增兩條排程觸發（15:30 / 週六 10:00）
- [ ] `FINMIND_API_TOKEN` 已加入 `Scripts/.env`

"""tools/predictors/algorithm.py

Taiwan Stock Prediction Engine
ALGORITHM.md Steps 2–12 完整實作。
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

try:
    from ta.momentum import RSIIndicator, StochasticOscillator
    from ta.trend import MACD, SMAIndicator
    from ta.volatility import AverageTrueRange, BollingerBands
    from ta.volume import OnBalanceVolumeIndicator
except ImportError as e:  # pragma: no cover
    raise ImportError("pip install ta") from e


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


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """回傳含所有技術指標的新 DataFrame（不修改輸入）。"""
    df = df.copy()
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]

    df["ma5"] = SMAIndicator(close, n=5).sma_indicator()
    df["ma10"] = SMAIndicator(close, n=10).sma_indicator()
    df["ma20"] = SMAIndicator(close, n=20).sma_indicator()
    df["ma60"] = SMAIndicator(close, n=60).sma_indicator()

    df["rsi14"] = RSIIndicator(close, n=14).rsi()

    stoch = StochasticOscillator(high=high, low=low, close=close, n=9, d_n=3)
    df["k_value"] = stoch.stoch()
    df["d_value"] = stoch.stoch_signal()

    macd = MACD(close, n_fast=12, n_slow=26, n_sign=9)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    bb = BollingerBands(close, n=20, ndev=2)
    df["boll_upper"] = bb.bollinger_hband()
    df["boll_middle"] = bb.bollinger_mavg()
    df["boll_lower"] = bb.bollinger_lband()

    try:
        df["atr14"] = AverageTrueRange(high, low, close, n=14).average_true_range()
    except (IndexError, ValueError):
        df["atr14"] = float("nan")
    df["obv"] = OnBalanceVolumeIndicator(close, vol).on_balance_volume()

    rolling_vol_mean = vol.rolling(20).mean()
    df["volume_ratio"] = vol / rolling_vol_mean
    return df


def resample_5day_windows(df: pd.DataFrame) -> pd.DataFrame:
    """把日線 df（含 indicators）聚合為非重疊5日窗口。
    從最新日往前對齊：捨棄首部不足5日的殘餘資料。
    """
    df = df.reset_index(drop=True)
    n = len(df)
    remainder = n % 5
    start = remainder  # 捨棄前 remainder 行
    rows = []
    for i in range(start, n, 5):
        chunk = df.iloc[i : i + 5]
        if len(chunk) < 5:
            break
        last = chunk.iloc[-1]
        rows.append({
            "date":      str(last["date"]),
            "open":      float(chunk.iloc[0]["open"]),
            "high":      float(chunk["high"].max()),
            "low":       float(chunk["low"].min()),
            "close":     float(last["close"]),
            "volume":    float(chunk["volume"].sum()),
            "ma20":      float(last["ma20"]) if pd.notna(last["ma20"]) else float("nan"),
            "ma60":      float(last["ma60"]) if pd.notna(last["ma60"]) else float("nan"),
            "macd_hist": float(last["macd_hist"]) if pd.notna(last["macd_hist"]) else float("nan"),
            "rsi14":     float(last["rsi14"]) if pd.notna(last["rsi14"]) else float("nan"),
            "atr14":     float(last["atr14"]) if pd.notna(last["atr14"]) else float("nan"),
        })
    return pd.DataFrame(rows)


def _detect_regime(close: float, ma5: float | None, ma10: float | None) -> str:
    if ma5 is None or ma10 is None or np.isnan(ma5) or np.isnan(ma10):
        return "Range"
    if close > ma5 and close > ma10:
        return "Bull"
    if close < ma5 and close < ma10:
        return "Bear"
    return "Range"


def _interval_token(pct: float, params: dict) -> str:
    flat_lower = params["flat_lower"]
    small_move = params["small_move"]
    large_move = params["large_move"]
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
    ma5 = row.get("ma5")
    ma10 = row.get("ma10")
    rsi_zone = _rsi_zone(rsi if not (isinstance(rsi, float) and np.isnan(rsi)) else None, params)
    t5 = _ma_touch_token(row["low"], row["high"], ma5 if not (isinstance(ma5, float) and np.isnan(ma5)) else None, "T5")
    t10 = _ma_touch_token(
        row["low"], row["high"], ma10 if not (isinstance(ma10, float) and np.isnan(ma10)) else None, "T10"
    )
    return f"{interval}|{rsi_zone}|{t5}|{t10}"


def _encode_symbols_from_df(df: pd.DataFrame, params: dict) -> tuple[list[str], list[str]]:
    symbols: list[str] = []
    dates: list[str] = []
    prev_close: float | None = None
    for _, row in df.iterrows():
        code = _encode_symbol(row, prev_close, params)
        symbols.append(code)
        dates.append(str(row["date"]))
        prev_close = row["close"]
    return symbols, dates


def _build_debruijn_graph(symbols: list[str], n: int, dates: list[str]) -> dict[str, Any]:
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


def _date_to_ordinal(d: str) -> int:
    y, m, day = d.split("-")
    return date(int(y), int(m), int(day)).toordinal()


def _edge_weight(edge_dates: list[str], reference_date: str, gamma: float) -> float:
    ref_ord = _date_to_ordinal(reference_date)
    return sum(math.exp(-gamma * max(0, ref_ord - _date_to_ordinal(d))) for d in edge_dates)


def _markov_distribution(
    graph: dict,
    current_node: tuple,
    reference_date: str,
    params: dict,
) -> dict[str, float]:
    gamma = params["decay_gamma"]
    eps = 1e-12
    edge_counts = graph.get("edge_counts", {})
    edge_dates_map = graph.get("edge_dates", {})

    outgoing: dict[tuple, float] = {}
    for (src, dst), count in edge_counts.items():
        if src == current_node:
            dates_list = edge_dates_map.get((src, dst), [reference_date] * count)
            outgoing[dst] = _edge_weight(dates_list, reference_date, gamma)

    if not outgoing:
        global_weights: dict[tuple, float] = defaultdict(float)
        for (src, dst), count in edge_counts.items():
            dates_list = edge_dates_map.get((src, dst), [reference_date] * count)
            global_weights[dst] += _edge_weight(dates_list, reference_date, gamma)
        outgoing = dict(global_weights)

    if not outgoing:
        return {iv: 1 / len(INTERVALS) for iv in INTERVALS}

    total = sum(outgoing.values()) + eps * len(outgoing)
    interval_dist: dict[str, float] = defaultdict(float)
    for dst_node, w in outgoing.items():
        interval = dst_node[-1].split("|")[0]
        interval_dist[interval] += (w + eps) / total

    s = sum(interval_dist.values())
    return {k: v / s for k, v in interval_dist.items()}


def _pagerank_distribution(graph: dict, reference_date: str, params: dict) -> dict[str, float]:
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


def _indicator_distribution(latest_code: str) -> dict[str, float]:
    parts = latest_code.split("|")
    rsi_zone = parts[1] if len(parts) > 1 else "RSI_NEU"
    t5 = parts[2] if len(parts) > 2 else "T5_N"
    t10 = parts[3] if len(parts) > 3 else "T10_N"

    scores: dict[str, float] = {iv: 0.0 for iv in INTERVALS}
    scores["F0"] = 1.0

    if t5 == "T5_Y" and t10 == "T10_Y":
        scores["R1"] += 0.6
        scores["S"] += 0.6
    elif t5 == "T5_Y":
        scores["F0"] += 0.5

    if rsi_zone == "RSI_OB":
        scores["S"] += 1.3
    elif rsi_zone == "RSI_OS":
        scores["R1"] += 0.8
        scores["R2"] += 0.5

    s = sum(scores.values())
    return {k: v / s for k, v in scores.items()}


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
        iv: l1 * markov.get(iv, 0.0) + l2 * pagerank.get(iv, 0.0) + l3 * indicator.get(iv, 0.0)
        for iv in INTERVALS
    }
    s = sum(combined.values())
    return {k: v / s for k, v in combined.items()}


def _confidence(probs: dict[str, float]) -> float:
    h_max = math.log(len(INTERVALS))
    h = -sum(p * math.log(p) for p in probs.values() if p > 0)
    return max(0.0, min(1.0, 1.0 - h / h_max))


_FALLBACK_MIDPOINTS: dict[str, float] = {
    "S": -1.5,
    "F0": 0.0,
    "R1": 1.25,
    "R2": 3.0,
    "R3": 5.5,
}


def _projected_close(probs: dict[str, float], df: pd.DataFrame, current_close: float) -> float:
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


_ATR_K: dict[str, str] = {"R1": "atr_k_r1", "R2": "atr_k_r2", "R3": "atr_k_r3"}
_TP_BOUNDS: dict[str, tuple[float, float]] = {
    "R1": (0.5, 2.0),
    "R2": (2.0, 4.0),
    "R3": (4.0, 7.0),
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


def predict(df: pd.DataFrame, params: dict | None = None) -> dict:
    p = {**DEFAULT_PARAMS, **(params or {})}
    lookback = p["lookback_days"]
    df = df.tail(lookback).reset_index(drop=True)

    df = _compute_indicators(df)
    last = df.iloc[-1]
    latest_regime = _detect_regime(close=last["close"], ma5=last.get("ma5"), ma10=last.get("ma10"))

    symbols, dates = _encode_symbols_from_df(df, p)

    n = p["n_order"]
    regimes = [_detect_regime(row["close"], row.get("ma5"), row.get("ma10")) for _, row in df.iterrows()]
    regime_indices = [i for i, r in enumerate(regimes) if r == latest_regime]
    if len(regime_indices) >= n * 5:
        filtered_symbols = [symbols[i] for i in regime_indices]
        filtered_dates = [dates[i] for i in regime_indices]
    else:
        filtered_symbols, filtered_dates = symbols, dates

    graph = _build_debruijn_graph(filtered_symbols, n, filtered_dates)
    current_node = tuple(symbols[-n:])
    ref_date = dates[-1]

    markov_dist = _markov_distribution(graph, current_node, ref_date, p)
    pagerank_dist = _pagerank_distribution(graph, ref_date, p)
    indicator_dist = _indicator_distribution(symbols[-1])
    probs = _combine(markov_dist, pagerank_dist, indicator_dist, p)
    conf = _confidence(probs)
    projected = _projected_close(probs, df, float(last["close"]))

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
    "S": {"S", "F0"},
    "F0": {"S", "F0", "R1"},
    "R1": {"F0", "R1", "R2"},
    "R2": {"R1", "R2", "R3"},
    "R3": {"R2", "R3"},
}
_BULLISH = {"R1", "R2", "R3"}
_BEARISH = {"S"}


def backtest(df: pd.DataFrame, params: dict | None = None, window: int = 60) -> dict:
    p = {**DEFAULT_PARAMS, **(params or {})}
    df = df.reset_index(drop=True)
    n_rows = len(df)
    min_rows = p["n_order"] + 20

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

        results.append({"exact": is_exact, "direction": is_direction, "adjacent": is_adjacent})

    n = len(results)
    if n == 0:
        return {"direction_acc": 0.0, "exact_hit_rate": 0.0, "adjacent_hit_rate": 0.0, "n_predictions": 0}

    return {
        "direction_acc": round(sum(r["direction"] for r in results) / n, 4),
        "exact_hit_rate": round(sum(r["exact"] for r in results) / n, 4),
        "adjacent_hit_rate": round(sum(r["adjacent"] for r in results) / n, 4),
        "n_predictions": n,
    }

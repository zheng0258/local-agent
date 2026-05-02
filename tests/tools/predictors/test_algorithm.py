"""tests/tools/predictors/test_algorithm.py"""
import unittest.mock as mock

import numpy as np
import pandas as pd
import pytest


INTERVALS = ["S", "F0", "R1", "R2", "R3"]


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    np.random.seed(42)
    n = 50
    dates = pd.bdate_range("2025-01-02", periods=n).strftime("%Y-%m-%d").tolist()
    close = 100.0 * np.cumprod(1 + np.random.normal(0.001, 0.015, n))
    open_ = close * (1 + np.random.normal(0, 0.005, n))
    high = np.maximum(close, open_) * (1 + np.abs(np.random.normal(0, 0.008, n)))
    low = np.minimum(close, open_) * (1 - np.abs(np.random.normal(0, 0.008, n)))
    volume = np.random.randint(1_000, 10_000, n).astype(float)
    return pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low, "close": close, "volume": volume})


def test_compute_indicators_adds_columns(sample_ohlcv):
    from tools.predictors.algorithm import _compute_indicators

    result = _compute_indicators(sample_ohlcv)
    expected_cols = [
        "ma5",
        "ma10",
        "ma20",
        "ma60",
        "rsi14",
        "k_value",
        "d_value",
        "macd",
        "macd_signal",
        "macd_hist",
        "boll_upper",
        "boll_middle",
        "boll_lower",
        "atr14",
        "obv",
        "volume_ratio",
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
    last_vol = sample_ohlcv["volume"].iloc[-1]
    rolling_mean = sample_ohlcv["volume"].iloc[-20:].mean()
    expected = last_vol / rolling_mean
    assert abs(result["volume_ratio"].iloc[-1] - expected) < 1e-6


def test_detect_regime_bull():
    from tools.predictors.algorithm import _detect_regime

    assert _detect_regime(close=110.0, ma5=105.0, ma10=100.0) == "Bull"


def test_detect_regime_bear():
    from tools.predictors.algorithm import _detect_regime

    assert _detect_regime(close=90.0, ma5=95.0, ma10=100.0) == "Bear"


def test_detect_regime_range():
    from tools.predictors.algorithm import _detect_regime

    assert _detect_regime(close=102.0, ma5=100.0, ma10=105.0) == "Range"


def test_interval_token_s():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _interval_token

    assert _interval_token(-1.0, DEFAULT_PARAMS) == "S"


def test_interval_token_f0():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _interval_token

    assert _interval_token(0.0, DEFAULT_PARAMS) == "F0"


def test_interval_token_r1():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _interval_token

    assert _interval_token(1.0, DEFAULT_PARAMS) == "R1"


def test_interval_token_r2():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _interval_token

    assert _interval_token(3.0, DEFAULT_PARAMS) == "R2"


def test_interval_token_r3():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _interval_token

    assert _interval_token(5.0, DEFAULT_PARAMS) == "R3"


def test_rsi_zone_overbought():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _rsi_zone

    assert _rsi_zone(75.0, DEFAULT_PARAMS) == "RSI_OB"


def test_rsi_zone_oversold():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _rsi_zone

    assert _rsi_zone(25.0, DEFAULT_PARAMS) == "RSI_OS"


def test_rsi_zone_neutral():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _rsi_zone

    assert _rsi_zone(50.0, DEFAULT_PARAMS) == "RSI_NEU"


def test_rsi_zone_none():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _rsi_zone

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
    from tools.predictors.algorithm import DEFAULT_PARAMS, _compute_indicators, _encode_symbol

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


def test_build_debruijn_edge_count():
    from tools.predictors.algorithm import _build_debruijn_graph

    symbols = ["A", "B", "C", "A", "B", "C"]
    dates = ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05", "2025-01-06"]
    graph = _build_debruijn_graph(symbols, n=2, dates=dates)
    assert graph["edge_counts"][(("A", "B"), ("B", "C"))] == 2


def test_build_debruijn_edge_dates():
    from tools.predictors.algorithm import _build_debruijn_graph

    symbols = ["A", "B", "C"]
    dates = ["2025-01-01", "2025-01-02", "2025-01-03"]
    graph = _build_debruijn_graph(symbols, n=2, dates=dates)
    edge = (("A", "B"), ("B", "C"))
    assert graph["edge_dates"][edge] == ["2025-01-03"]


def test_build_debruijn_empty_symbols():
    from tools.predictors.algorithm import _build_debruijn_graph

    graph = _build_debruijn_graph([], n=3, dates=[])
    assert graph["edge_counts"] == {}


def test_build_debruijn_current_node(sample_ohlcv):
    from tools.predictors.algorithm import DEFAULT_PARAMS, _build_debruijn_graph, _compute_indicators, _encode_symbols_from_df

    df = _compute_indicators(sample_ohlcv)
    symbols, dates = _encode_symbols_from_df(df, DEFAULT_PARAMS)
    graph = _build_debruijn_graph(symbols, n=3, dates=dates)
    current = tuple(symbols[-3:])
    assert isinstance(current, tuple)
    assert len(current) == 3


def test_markov_distribution_known_state():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _markov_distribution

    ref_date = "2025-03-01"
    graph = {
        "edge_counts": {(("A",), ("B",)): 2, (("A",), ("C",)): 1},
        "edge_dates": {(("A",), ("B",)): [ref_date, ref_date], (("A",), ("C",)): [ref_date]},
    }
    current_node = ("A",)
    params = {**DEFAULT_PARAMS, "decay_gamma": 0.0}
    dist = _markov_distribution(graph, current_node, ref_date, params)
    assert abs(dist.get("B", 0) - 2 / 3) < 1e-6
    assert abs(dist.get("C", 0) - 1 / 3) < 1e-6


def test_markov_distribution_unknown_state_uses_global():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _markov_distribution

    ref_date = "2025-03-01"
    graph = {"edge_counts": {(("X",), ("Y",)): 1}, "edge_dates": {(("X",), ("Y",)): [ref_date]}}
    dist = _markov_distribution(graph, ("Z",), ref_date, DEFAULT_PARAMS)
    assert sum(dist.values()) > 0
    assert abs(sum(dist.values()) - 1.0) < 1e-6


def test_markov_distribution_sums_to_one(sample_ohlcv):
    from tools.predictors.algorithm import (
        DEFAULT_PARAMS,
        _build_debruijn_graph,
        _compute_indicators,
        _encode_symbols_from_df,
        _markov_distribution,
    )

    df = _compute_indicators(sample_ohlcv)
    symbols, dates = _encode_symbols_from_df(df, DEFAULT_PARAMS)
    n = DEFAULT_PARAMS["n_order"]
    graph = _build_debruijn_graph(symbols, n, dates)
    current_node = tuple(symbols[-n:])
    dist = _markov_distribution(graph, current_node, dates[-1], DEFAULT_PARAMS)
    assert abs(sum(dist.values()) - 1.0) < 1e-6


def test_pagerank_distribution_sums_to_one(sample_ohlcv):
    from tools.predictors.algorithm import (
        DEFAULT_PARAMS,
        _build_debruijn_graph,
        _compute_indicators,
        _encode_symbols_from_df,
        _pagerank_distribution,
    )

    df = _compute_indicators(sample_ohlcv)
    symbols, dates = _encode_symbols_from_df(df, DEFAULT_PARAMS)
    n = DEFAULT_PARAMS["n_order"]
    graph = _build_debruijn_graph(symbols, n, dates)
    dist = _pagerank_distribution(graph, dates[-1], DEFAULT_PARAMS)
    assert abs(sum(dist.values()) - 1.0) < 1e-6


def test_pagerank_distribution_returns_all_intervals(sample_ohlcv):
    from tools.predictors.algorithm import (
        DEFAULT_PARAMS,
        INTERVALS as ALG_INTERVALS,
        _build_debruijn_graph,
        _compute_indicators,
        _encode_symbols_from_df,
        _pagerank_distribution,
    )

    df = _compute_indicators(sample_ohlcv)
    symbols, dates = _encode_symbols_from_df(df, DEFAULT_PARAMS)
    graph = _build_debruijn_graph(symbols, DEFAULT_PARAMS["n_order"], dates)
    dist = _pagerank_distribution(graph, dates[-1], DEFAULT_PARAMS)
    for k in dist:
        assert k in ALG_INTERVALS


def test_indicator_distribution_rsi_ob_lean_bearish():
    from tools.predictors.algorithm import _indicator_distribution

    code = "R1|RSI_OB|T5_N|T10_N"
    dist = _indicator_distribution(code)
    assert dist["S"] > dist["R3"]


def test_indicator_distribution_rsi_os_lean_bullish():
    from tools.predictors.algorithm import _indicator_distribution

    code = "F0|RSI_OS|T5_N|T10_N"
    dist = _indicator_distribution(code)
    assert dist["R1"] > dist["S"]


def test_indicator_distribution_sums_to_one():
    from tools.predictors.algorithm import _indicator_distribution

    for code in ["S|RSI_OB|T5_Y|T10_Y", "R2|RSI_NEU|T5_N|T10_N", "F0|RSI_OS|T5_Y|T10_N"]:
        dist = _indicator_distribution(code)
        assert abs(sum(dist.values()) - 1.0) < 1e-6


def test_combine_sums_to_one():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _combine

    uniform = {iv: 0.2 for iv in ["S", "F0", "R1", "R2", "R3"]}
    result = _combine(uniform, uniform, uniform, DEFAULT_PARAMS)
    assert abs(sum(result.values()) - 1.0) < 1e-6


def test_combine_all_keys_present():
    from tools.predictors.algorithm import DEFAULT_PARAMS, INTERVALS as ALG_INTERVALS, _combine

    uniform = {iv: 0.2 for iv in ALG_INTERVALS}
    result = _combine(uniform, uniform, uniform, DEFAULT_PARAMS)
    assert set(result.keys()) == set(ALG_INTERVALS)


def test_confidence_uniform_is_zero():
    from tools.predictors.algorithm import INTERVALS as ALG_INTERVALS, _confidence

    uniform = {iv: 1 / len(ALG_INTERVALS) for iv in ALG_INTERVALS}
    assert abs(_confidence(uniform) - 0.0) < 1e-6


def test_confidence_certain_is_one():
    from tools.predictors.algorithm import INTERVALS as ALG_INTERVALS, _confidence

    certain = {iv: 0.0 for iv in ALG_INTERVALS}
    certain["R2"] = 1.0
    assert abs(_confidence(certain) - 1.0) < 1e-6


def test_trading_signal_r1_has_sl_tp():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _trading_signal

    sig = _trading_signal("R1", current_close=100.0, atr=1.0, confidence=0.5, params=DEFAULT_PARAMS)
    assert sig is not None
    assert sig["stop_loss"] < 100.0
    assert sig["take_profit"] > 100.0
    assert sig["stop_loss_pct"] < 0


def test_trading_signal_s_returns_none():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _trading_signal

    sig = _trading_signal("S", current_close=100.0, atr=1.0, confidence=0.5, params=DEFAULT_PARAMS)
    assert sig is None


def test_trading_signal_strength_strong():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _trading_signal

    sig = _trading_signal("R3", current_close=100.0, atr=1.0, confidence=0.45, params=DEFAULT_PARAMS)
    assert sig["strength"] == "Strong"


def test_predict_returns_required_keys(sample_ohlcv):
    from tools.predictors.algorithm import DEFAULT_PARAMS, predict

    result = predict(sample_ohlcv.copy(), DEFAULT_PARAMS)
    for key in ["most_likely", "probs", "confidence", "projected_close", "current_close", "signal", "regime"]:
        assert key in result, f"missing key: {key}"


def test_predict_most_likely_in_intervals(sample_ohlcv):
    from tools.predictors.algorithm import DEFAULT_PARAMS, INTERVALS as ALG_INTERVALS, predict

    result = predict(sample_ohlcv.copy(), DEFAULT_PARAMS)
    assert result["most_likely"] in ALG_INTERVALS


def test_predict_probs_sum_to_one(sample_ohlcv):
    from tools.predictors.algorithm import DEFAULT_PARAMS, predict

    result = predict(sample_ohlcv.copy(), DEFAULT_PARAMS)
    assert abs(sum(result["probs"].values()) - 1.0) < 1e-6


def test_predict_signal_none_for_bearish(sample_ohlcv):
    from tools.predictors import algorithm
    from tools.predictors.algorithm import DEFAULT_PARAMS, predict

    forced_probs = {"S": 0.9, "F0": 0.025, "R1": 0.025, "R2": 0.025, "R3": 0.025}
    with mock.patch.object(algorithm, "_combine", return_value=forced_probs):
        result = predict(sample_ohlcv.copy(), DEFAULT_PARAMS)
    assert result["signal"] is None


def test_backtest_returns_metrics(sample_ohlcv):
    from tools.predictors.algorithm import DEFAULT_PARAMS, backtest

    result = backtest(sample_ohlcv.copy(), DEFAULT_PARAMS, window=10)
    for key in ["direction_acc", "exact_hit_rate", "adjacent_hit_rate", "n_predictions"]:
        assert key in result
    assert 0.0 <= result["direction_acc"] <= 1.0
    assert result["n_predictions"] >= 0


@pytest.fixture
def ohlcv_15rows() -> pd.DataFrame:
    """剛好15個交易日 → 3個完整5日窗口"""
    np.random.seed(7)
    n = 15
    dates = pd.bdate_range("2025-01-02", periods=n).strftime("%Y-%m-%d").tolist()
    close = 100.0 * np.cumprod(1 + np.random.normal(0.001, 0.01, n))
    open_ = close * (1 + np.random.normal(0, 0.003, n))
    high = np.maximum(close, open_) * 1.005
    low = np.minimum(close, open_) * 0.995
    volume = np.random.randint(1000, 5000, n).astype(float)
    return pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low, "close": close, "volume": volume})


@pytest.fixture
def ohlcv_13rows() -> pd.DataFrame:
    """13個交易日 → 捨棄首3日，留2個完整5日窗口"""
    np.random.seed(8)
    n = 13
    dates = pd.bdate_range("2025-01-02", periods=n).strftime("%Y-%m-%d").tolist()
    close = 100.0 * np.cumprod(1 + np.random.normal(0.001, 0.01, n))
    open_ = close * (1 + np.random.normal(0, 0.003, n))
    high = np.maximum(close, open_) * 1.005
    low = np.minimum(close, open_) * 0.995
    volume = np.random.randint(1000, 5000, n).astype(float)
    return pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low, "close": close, "volume": volume})


def test_resample_5day_exact_windows(ohlcv_15rows):
    from tools.predictors.algorithm import _compute_indicators, resample_5day_windows
    df = _compute_indicators(ohlcv_15rows)
    windows = resample_5day_windows(df)
    assert len(windows) == 3


def test_resample_5day_partial_discarded(ohlcv_13rows):
    from tools.predictors.algorithm import _compute_indicators, resample_5day_windows
    df = _compute_indicators(ohlcv_13rows)
    windows = resample_5day_windows(df)
    assert len(windows) == 2


def test_resample_5day_columns(ohlcv_15rows):
    from tools.predictors.algorithm import _compute_indicators, resample_5day_windows
    df = _compute_indicators(ohlcv_15rows)
    windows = resample_5day_windows(df)
    required = {"date", "open", "high", "low", "close", "volume", "ma20", "ma60", "macd_hist", "rsi14", "atr14"}
    assert required.issubset(set(windows.columns))


def test_resample_5day_high_is_max(ohlcv_15rows):
    from tools.predictors.algorithm import _compute_indicators, resample_5day_windows
    df = _compute_indicators(ohlcv_15rows)
    windows = resample_5day_windows(df)
    expected_high = df.iloc[:5]["high"].max()
    assert abs(windows.iloc[0]["high"] - expected_high) < 1e-6


def test_resample_5day_volume_is_sum(ohlcv_15rows):
    from tools.predictors.algorithm import _compute_indicators, resample_5day_windows
    df = _compute_indicators(ohlcv_15rows)
    windows = resample_5day_windows(df)
    expected_vol = df.iloc[:5]["volume"].sum()
    assert abs(windows.iloc[0]["volume"] - expected_vol) < 1e-6


def test_resample_5day_close_is_last(ohlcv_15rows):
    from tools.predictors.algorithm import _compute_indicators, resample_5day_windows
    df = _compute_indicators(ohlcv_15rows)
    windows = resample_5day_windows(df)
    assert abs(windows.iloc[0]["close"] - df.iloc[4]["close"]) < 1e-6


def test_interval_token_5d_s():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _interval_token_5d
    assert _interval_token_5d(-5.0, DEFAULT_PARAMS) == "S"

def test_interval_token_5d_f0():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _interval_token_5d
    assert _interval_token_5d(-1.0, DEFAULT_PARAMS) == "F0"

def test_interval_token_5d_r1():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _interval_token_5d
    assert _interval_token_5d(3.0, DEFAULT_PARAMS) == "R1"

def test_interval_token_5d_r2():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _interval_token_5d
    assert _interval_token_5d(8.0, DEFAULT_PARAMS) == "R2"

def test_interval_token_5d_r3():
    from tools.predictors.algorithm import DEFAULT_PARAMS, _interval_token_5d
    assert _interval_token_5d(15.0, DEFAULT_PARAMS) == "R3"

def test_encode_5day_symbol_format(ohlcv_15rows):
    from tools.predictors.algorithm import DEFAULT_PARAMS, _compute_indicators, _encode_5day_symbol, resample_5day_windows
    df = _compute_indicators(ohlcv_15rows)
    windows = resample_5day_windows(df)
    row = windows.iloc[1]
    prev_close = float(windows.iloc[0]["close"])
    prev_vol = float(windows.iloc[0]["volume"])
    sym = _encode_5day_symbol(row, prev_close, prev_vol, DEFAULT_PARAMS)
    parts = sym.split("|")
    assert len(parts) == 4
    assert parts[0] in {"S", "F0", "R1", "R2", "R3"}
    assert parts[1] in {"BULL", "BEAR", "FLAT"}
    assert parts[2] in {"MU", "MD", "MN"}
    assert parts[3] in {"VH", "VL", "VN"}

def test_encode_5day_symbol_first_window_vn(ohlcv_15rows):
    from tools.predictors.algorithm import DEFAULT_PARAMS, _compute_indicators, _encode_5day_symbol, resample_5day_windows
    df = _compute_indicators(ohlcv_15rows)
    windows = resample_5day_windows(df)
    row = windows.iloc[0]
    sym = _encode_5day_symbol(row, prev_close=None, prev_vol=None, params=DEFAULT_PARAMS)
    parts = sym.split("|")
    assert parts[3] == "VN"

def test_encode_symbols_from_5day_length(ohlcv_15rows):
    from tools.predictors.algorithm import DEFAULT_PARAMS, _compute_indicators, _encode_symbols_from_5day, resample_5day_windows
    df = _compute_indicators(ohlcv_15rows)
    windows = resample_5day_windows(df)
    symbols, dates = _encode_symbols_from_5day(windows, DEFAULT_PARAMS)
    assert len(symbols) == len(windows)
    assert len(dates) == len(windows)

def test_encode_symbols_from_5day_dates_match(ohlcv_15rows):
    from tools.predictors.algorithm import DEFAULT_PARAMS, _compute_indicators, _encode_symbols_from_5day, resample_5day_windows
    df = _compute_indicators(ohlcv_15rows)
    windows = resample_5day_windows(df)
    _, dates = _encode_symbols_from_5day(windows, DEFAULT_PARAMS)
    assert dates[0] == windows.iloc[0]["date"]
    assert dates[-1] == windows.iloc[-1]["date"]


def test_detect_regime_5d_bull():
    from tools.predictors.algorithm import _detect_regime_5d
    import pandas as pd
    row = pd.Series({"close": 110.0, "ma20": 105.0, "ma60": 100.0})
    assert _detect_regime_5d(row) == "Bull"


def test_detect_regime_5d_bear():
    from tools.predictors.algorithm import _detect_regime_5d
    import pandas as pd
    row = pd.Series({"close": 90.0, "ma20": 95.0, "ma60": 100.0})
    assert _detect_regime_5d(row) == "Bear"


def test_detect_regime_5d_range():
    from tools.predictors.algorithm import _detect_regime_5d
    import pandas as pd
    row = pd.Series({"close": 102.0, "ma20": 100.0, "ma60": 103.0})
    assert _detect_regime_5d(row) == "Range"


def test_detect_regime_5d_nan():
    from tools.predictors.algorithm import _detect_regime_5d
    import pandas as pd
    row = pd.Series({"close": 100.0, "ma20": float("nan"), "ma60": 100.0})
    assert _detect_regime_5d(row) == "Range"


def test_indicator_distribution_5d_bull_mu_bullish():
    from tools.predictors.algorithm import _indicator_distribution_5d
    dist = _indicator_distribution_5d("R1|BULL|MU|VH")
    assert dist["R1"] + dist["R2"] + dist["R3"] > dist["S"] + dist["F0"]


def test_indicator_distribution_5d_bear_md_bearish():
    from tools.predictors.algorithm import _indicator_distribution_5d
    dist = _indicator_distribution_5d("S|BEAR|MD|VL")
    assert dist["S"] > dist["R3"]


def test_indicator_distribution_5d_sums_to_one():
    from tools.predictors.algorithm import _indicator_distribution_5d
    for sym in ["R1|BULL|MU|VH", "S|BEAR|MD|VL", "F0|FLAT|MN|VN"]:
        dist = _indicator_distribution_5d(sym)
        assert abs(sum(dist.values()) - 1.0) < 1e-6

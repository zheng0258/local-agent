# agents/tw_stock/signal.py
"""台股訊號合成：情緒過濾 × 技術確認 × 跨股 PageRank 放大。"""
from __future__ import annotations

from typing import Any

import networkx as nx
import pandas as pd


def apply_sentiment_filter(
    technical_interval: str,
    sentiment_overall: str,
    base_confidence: float,
) -> dict[str, Any]:
    """
    情緒過濾層。
    回傳 {"direction": str | None, "confidence_mult": float}
    direction: "BUY", "WATCH", "BUY"（neutral）, None（跳過）
    """
    if sentiment_overall == "bullish":
        if technical_interval in ("R2", "R3"):
            return {"direction": "BUY", "confidence_mult": 1.0}
        if technical_interval == "R1":
            return {"direction": "BUY", "confidence_mult": 0.7}
        return {"direction": None, "confidence_mult": 0.0}

    if sentiment_overall == "bearish":
        if technical_interval == "S":
            return {"direction": "WATCH", "confidence_mult": 1.0}
        return {"direction": None, "confidence_mult": 0.0}

    # neutral
    return {"direction": "BUY", "confidence_mult": 0.8}


def compute_cross_stock_centrality(
    returns_df: pd.DataFrame,
    threshold: float = 0.4,
    alpha: float = 0.85,
) -> dict[str, float]:
    """
    以 120 日日報酬相關係數建構有向圖，計算 PageRank 中心性（正規化至 [0,1]）。
    returns_df：columns = tickers, rows = daily returns (float)
    """
    if returns_df.empty or len(returns_df) < 2:
        return {t: 0.0 for t in returns_df.columns}

    corr = returns_df.corr()
    G = nx.DiGraph()
    G.add_nodes_from(returns_df.columns)

    for t1 in returns_df.columns:
        for t2 in returns_df.columns:
            if t1 != t2:
                w = corr.loc[t1, t2]
                if not pd.isna(w) and abs(w) > threshold:
                    G.add_edge(t1, t2, weight=abs(w))

    if G.number_of_edges() == 0:
        return {t: 0.0 for t in returns_df.columns}

    pr = nx.pagerank(G, alpha=alpha, weight="weight")
    max_val = max(pr.values()) or 1.0
    return {k: v / max_val for k, v in pr.items()}


def compute_txf_signal(
    sentiment_score: float,
    bluechip_bull_ratio: float,
    min_confidence: float = 0.2,
) -> dict[str, Any] | None:
    """
    台指期方向：情緒 60% + 藍籌牛市比例 40%。
    final_score < min_confidence 時回傳 None（不發訊號）。
    """
    sentiment_component = (sentiment_score - 0.5) * 2      # [-1, 1]
    ratio_component = (bluechip_bull_ratio - 0.5) * 2       # [-1, 1]
    raw_score = 0.6 * sentiment_component + 0.4 * ratio_component

    if abs(raw_score) < min_confidence:
        return None

    return {
        "direction": "LONG" if raw_score > 0 else "SHORT",
        "sentiment_score": round(sentiment_score, 3),
        "bluechip_bullish_ratio": round(bluechip_bull_ratio, 3),
        "final_score": round(abs(raw_score), 3),
    }


def build_signals(
    sentiment: dict,
    technical: dict,
    centrality: dict[str, float],
    boost_factor: float = 0.5,
) -> list[dict]:
    """
    合成最終訊號列表。
    sentiment: {"overall": "bullish"|"bearish"|"neutral", "score": float, ...}
    technical: {ticker: {"most_likely": str, "confidence": float, "signal": dict|None}}
    centrality: {ticker: normalized_score}
    """
    signals: list[dict] = []
    overall = sentiment.get("overall", "neutral")
    non_txf = {k: v for k, v in technical.items() if k != "TXF"}

    for ticker, tech in non_txf.items():
        most_likely = tech.get("most_likely", "F0")
        base_conf = tech.get("confidence", 0.0)
        signal_detail = tech.get("signal")

        filt = apply_sentiment_filter(most_likely, overall, base_conf)
        if filt["direction"] is None:
            continue

        adjusted_conf = base_conf * filt["confidence_mult"]
        norm_centrality = centrality.get(ticker, 0.0)
        final_score = adjusted_conf * (1 + boost_factor * norm_centrality)

        signals.append({
            "ticker": ticker,
            "type": "stock",
            "direction": filt["direction"],
            "technical_interval": most_likely,
            "sentiment_direction": overall,
            "base_confidence": round(base_conf, 4),
            "centrality": round(norm_centrality, 4),
            "final_score": round(final_score, 4),
            "signal": signal_detail,
            "is_leader": norm_centrality >= 0.7,
        })

    # TXF
    if "TXF" in technical:
        bullish_count = sum(
            1 for v in non_txf.values()
            if v.get("most_likely") in ("R1", "R2", "R3")
        )
        bull_ratio = bullish_count / max(len(non_txf), 1)
        txf_sig = compute_txf_signal(
            sentiment_score=sentiment.get("score", 0.5),
            bluechip_bull_ratio=bull_ratio,
        )
        if txf_sig:
            signals.append({
                "ticker": "TXF",
                "type": "futures",
                **txf_sig,
                "technical_interval": None,
                "sentiment_direction": overall,
                "base_confidence": txf_sig["final_score"],
                "centrality": 0.0,
                "signal": None,
                "is_leader": False,
            })

    return signals

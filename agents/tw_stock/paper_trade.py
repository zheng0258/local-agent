# agents/tw_stock/paper_trade.py
"""紙上交易：倉位計算、進出場邏輯、損益統計（純函數，無副作用）。"""
from __future__ import annotations

from typing import Any


def compute_position_size(
    portfolio_value: float,
    entry_price: float,
    stop_loss: float,
    risk_pct: float = 0.02,
) -> int:
    """固定風險法：每筆最多虧損 risk_pct × portfolio_value。回傳整張數（≥1）。"""
    price_risk = abs(entry_price - stop_loss)
    if price_risk == 0:
        return 1
    risk_amount = portfolio_value * risk_pct
    lots = max(1, int(risk_amount / price_risk / 1000))
    return lots


def check_exit_reason(
    position: dict[str, Any],
    current_price: float,
    signal_direction: str | None,
) -> str | None:
    """
    判斷是否出場，回傳原因或 None（繼續持有）。
    出場優先順序：stop_loss > take_profit > max_hold > signal_reversal
    """
    from agents.tw_stock.config import MAX_HOLD_DAYS

    if current_price <= position["stop_loss"]:
        return "stop_loss"
    if current_price >= position["take_profit"]:
        return "take_profit"
    if position["hold_days"] >= MAX_HOLD_DAYS:
        return "max_hold"
    if signal_direction == "WATCH":
        return "signal_reversal"
    return None


def process_paper_trade(
    signals: list[dict],
    positions: dict[str, dict],
    market_prices: dict[str, float],
    portfolio_value: float,
    cash: float,
    today: str,
    max_new: int = 3,
    max_total: int = 5,
    min_score: float = 0.40,
    risk_pct: float = 0.02,
) -> dict[str, Any]:
    """
    執行一日紙上交易。
    1. 檢查現有倉位出場條件
    2. 新增符合條件的買入訊號
    回傳 paper_trade state dict（含 positions, closed_today, cash）。
    """
    signal_map = {s["ticker"]: s for s in signals}
    closed_today: list[dict] = []
    updated_positions: dict[str, dict] = {}

    # 1. 出場判斷
    for ticker, pos in positions.items():
        current_price = market_prices.get(ticker, pos["entry_price"])
        sig_dir = signal_map.get(ticker, {}).get("direction")
        reason = check_exit_reason(pos, current_price, sig_dir)

        if reason:
            pnl_twd = (current_price - pos["entry_price"]) * pos["shares"]
            pnl_pct = (current_price / pos["entry_price"] - 1) * 100
            cash += current_price * pos["shares"]
            closed_today.append({
                "ticker": ticker,
                "entry": pos["entry_price"],
                "exit": round(current_price, 2),
                "pnl_twd": round(pnl_twd, 0),
                "pnl_pct": round(pnl_pct, 2),
                "reason": reason,
                "hold_days": pos["hold_days"],
            })
        else:
            updated_positions[ticker] = {**pos, "hold_days": pos["hold_days"] + 1}

    # 2. 新開倉
    buy_signals = sorted(
        [
            s for s in signals
            if s["direction"] == "BUY"
            and s.get("final_score", 0) >= min_score
            and s["ticker"] not in updated_positions
            and s.get("signal")
        ],
        key=lambda s: s["final_score"],
        reverse=True,
    )

    new_opened = 0
    for sig in buy_signals:
        if new_opened >= max_new or len(updated_positions) >= max_total:
            break
        ticker = sig["ticker"]
        entry_price = market_prices.get(ticker, 0.0)
        if entry_price <= 0:
            continue
        stop_loss = sig["signal"]["stop_loss"]
        take_profit = sig["signal"]["take_profit"]
        lots = compute_position_size(portfolio_value, entry_price, stop_loss, risk_pct)
        shares = lots * 1000
        cost = entry_price * shares
        if cost > cash:
            continue
        cash -= cost
        updated_positions[ticker] = {
            "entry_price": round(entry_price, 2),
            "lots": lots,
            "shares": shares,
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "entry_date": today,
            "hold_days": 0,
        }
        new_opened += 1

    return {
        "portfolio_value": round(portfolio_value, 0),
        "cash": round(cash, 0),
        "positions": updated_positions,
        "closed_today": closed_today,
    }


def compute_pnl_summary(
    paper_trade: dict,
    pnl_history: list[dict],
    today: str,
    market_prices: dict[str, float],
    initial_value: float = 1_000_000,
) -> dict[str, Any]:
    """計算今日損益與累積績效指標（純函數）。"""
    positions = paper_trade.get("positions", {})
    closed_today = paper_trade.get("closed_today", [])
    cash = paper_trade.get("cash", 0.0)

    position_market_value = sum(
        market_prices.get(t, pos["entry_price"]) * pos["shares"]
        for t, pos in positions.items()
    )
    portfolio_value = cash + position_market_value

    daily_closed_pnl = sum(c["pnl_twd"] for c in closed_today)
    unrealized = sum(
        (market_prices.get(t, pos["entry_price"]) - pos["entry_price"]) * pos["shares"]
        for t, pos in positions.items()
    )

    total_return_pct = (portfolio_value / initial_value - 1) * 100

    values = [h["portfolio_value"] for h in pnl_history] + [portfolio_value]
    peak = values[0] if values else initial_value
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        dd = (v - peak) / peak * 100
        max_dd = min(max_dd, dd)

    all_closed = [
        t
        for h in pnl_history
        if "closed_today" in h
        for t in h["closed_today"]
    ] + closed_today
    winning = [t for t in all_closed if t["pnl_twd"] > 0]
    win_rate = len(winning) / len(all_closed) if all_closed else 0.0
    avg_hold = (
        sum(t.get("hold_days", 0) for t in all_closed) / len(all_closed)
        if all_closed else 0.0
    )

    return {
        "date": today,
        "portfolio_value": round(portfolio_value, 0),
        "daily_pnl_twd": round(daily_closed_pnl, 0),
        "unrealized_pnl_twd": round(unrealized, 0),
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "win_rate": round(win_rate, 3),
        "total_trades": len(all_closed),
        "avg_hold_days": round(avg_hold, 1),
    }

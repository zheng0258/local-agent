"""agents/stock_predictor/agent.py

每日台股預測 Agent。
流程：交易日判斷 → 隔日驗證 → 全 watchlist 預測 → Telegram 推送。
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from config import get_logger
from config.settings import LLMBackend
from tools.fetchers.finmind import fetch_incremental
from tools.notifiers.telegram import send as _tg_send

def telegram_send(text: str) -> bool:
    return _tg_send(text, token_env="STOCK_TELEGRAM_BOT_TOKEN")

from .config import OHLCV_DIR, OUTPUTS_DIR, STATS_DIR, is_trading_day, load_params, load_watchlist, prev_trading_day

logger = get_logger(__name__)

FINMIND_TOKEN_ENV = "FINMIND_API_TOKEN"


class StockPredictorAgent:
    AGENT_NAME = "stock_predictor"

    def __init__(self, llm: LLMBackend | None = None) -> None:
        self._llm = llm

    def run(self, args: str = "") -> str:
        today = date.today().isoformat()

        if not is_trading_day(today):
            logger.info("非交易日 %s，跳過預測", today)
            return f"非交易日（{today}），跳過預測。"

        watchlist = load_watchlist()
        if "--only" in args:
            only = args.split("--only", 1)[1].strip().split()
            watchlist = [t.upper() for t in only if t.strip()]

        if not watchlist:
            return "watchlist 為空，請先透過 Telegram Bot /watch <ticker> 新增股票。"

        token = os.environ.get(FINMIND_TOKEN_ENV, "")
        yesterday = prev_trading_day(today)

        self._verify(yesterday, token)

        signals: list[str] = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(self._predict_one, ticker, today, token): ticker for ticker in watchlist}
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

    def _verify(self, yesterday: str, token: str) -> None:
        from tools.predictors.algorithm import DEFAULT_PARAMS, _interval_token

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
                bullish = {"R1", "R2", "R3"}
                is_exact = predicted == actual_iv
                is_direction = ((predicted in bullish and actual_iv in bullish) or predicted == actual_iv)

                adjacent = {
                    "S": {"S", "F0"},
                    "F0": {"S", "F0", "R1"},
                    "R1": {"F0", "R1", "R2"},
                    "R2": {"R1", "R2", "R3"},
                    "R3": {"R2", "R3"},
                }
                is_adjacent = actual_iv in adjacent.get(predicted, {predicted})
                self._update_stats(ticker, is_exact, is_direction, is_adjacent)
            except Exception as e:
                logger.warning("驗證 %s 失敗：%s", ticker, e)

    def _update_stats(self, ticker: str, is_exact: bool, is_direction: bool, is_adjacent: bool) -> None:
        stats_file = STATS_DIR / f"{ticker}.json"
        stats = (
            json.loads(stats_file.read_text())
            if stats_file.exists()
            else {"total": 0, "direction_correct": 0, "exact_hit": 0, "adjacent_hit": 0}
        )
        stats["total"] += 1
        if is_direction:
            stats["direction_correct"] += 1
        if is_exact:
            stats["exact_hit"] += 1
        if is_adjacent:
            stats["adjacent_hit"] += 1

        n = stats["total"]
        stats["direction_acc"] = round(stats["direction_correct"] / n, 4)
        stats["exact_hit_rate"] = round(stats["exact_hit"] / n, 4)
        stats["adjacent_hit_rate"] = round(stats["adjacent_hit"] / n, 4)
        stats_file.write_text(json.dumps(stats, indent=2, ensure_ascii=False))

    def _predict_one(self, ticker: str, today: str, token: str) -> str | None:
        from tools.predictors.algorithm import predict

        df = fetch_incremental(ticker, OHLCV_DIR, token)
        if df.empty or len(df) < 20:
            logger.warning("%s 資料不足，跳過", ticker)
            return None

        params = load_params(ticker)
        result = predict(df, params)
        result["ticker"] = ticker

        out_dir = OUTPUTS_DIR / today / "predictions"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{ticker}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))

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

# agents/tw_stock/agent.py
"""
TwStockAgent — 台灣股市訊號系統。

步驟：news → sentiment → market_data → technical → signal → paper_trade → pnl → notify

執行參數：
  （無）              正常執行，略過已完成步驟
  --init             初始化持倉與歷史交易（讀取 data/tw-stock/init.json）
  --force <step>...  強制重跑指定步驟
  --only <step>...   只執行指定步驟

可用 step：news / sentiment / market_data / technical / signal / paper_trade / pnl / notify
"""
from __future__ import annotations

import json
import os
import shlex
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import get_llm, get_logger, parse_llm_json
from config.settings import LLMBackend

from . import prompts
from .config import (
    ALL_STEPS,
    CENTRALITY_BOOST_FACTOR,
    CORRELATION_LOOKBACK_DAYS,
    CORRELATION_THRESHOLD,
    DATA_DIR,
    INIT_FILE,
    INITIAL_PORTFOLIO_VALUE,
    MAX_DAILY_NEW_POSITIONS,
    MAX_TOTAL_POSITIONS,
    OUTPUT_DIR,
    PNL_HISTORY_FILE,
    POSITIONS_FILE,
    RISK_PER_TRADE_PCT,
    SIGNAL_MIN_SCORE,
    STOCK_BOT_TOKEN_ENV,
    STOCK_CHAT_ID_ENV,
)

logger = get_logger(__name__)


class TwStockAgent:
    AGENT_NAME = "tw-stock"

    def __init__(self, llm: LLMBackend | None = None) -> None:
        self._llm = llm or get_llm()

    def run(self, args: str = "") -> str:
        if "--init" in (shlex.split(args) if args.strip() else []):
            return self._phase_init()

        today = date.today().strftime("%Y-%m-%d")
        force_steps, only_steps = _parse_args(args)
        effective_steps = only_steps or set(ALL_STEPS)

        day_dir = OUTPUT_DIR / today
        steps_dir = day_dir / "steps"
        steps_dir.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        news = self._phase_news(steps_dir, force_steps, effective_steps, today)
        sentiment = self._phase_sentiment(steps_dir, force_steps, effective_steps, news)
        market_data = self._phase_market_data(steps_dir, force_steps, effective_steps)
        technical = self._phase_technical(steps_dir, force_steps, effective_steps, market_data)
        signals = self._phase_signal(steps_dir, force_steps, effective_steps, sentiment, technical, market_data)
        paper_trade = self._phase_paper_trade(steps_dir, force_steps, effective_steps, signals, market_data, today)
        pnl = self._phase_pnl(steps_dir, force_steps, effective_steps, paper_trade, market_data, today)
        self._phase_notify(steps_dir, day_dir, force_steps, effective_steps, signals, pnl, paper_trade, sentiment, today)

        return f"完成。輸出目錄：outputs/tw-stock/{today}/"

    # ── Init ──────────────────────────────────────────────────────

    def _phase_init(self) -> str:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        if not INIT_FILE.exists():
            INIT_FILE.write_text(
                json.dumps(_build_init_template(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return (
                f"已產生範本：{INIT_FILE}\n"
                "請填寫後再次執行 python3 main.py \"/tw-stock --init\""
            )

        data = _load_json(INIT_FILE, default={})
        if not data:
            return "❌ init.json 格式錯誤或為空，請確認 JSON 格式後重試"

        today_str = date.today().strftime("%Y-%m-%d")
        cash = float(data.get("cash", INITIAL_PORTFOLIO_VALUE))

        # ── 持倉轉換 ────────────────────────────────────────────────
        positions: dict[str, Any] = {}
        for p in data.get("positions", []):
            ticker = str(p["ticker"])
            entry_price = float(p["entry_price"])
            lots = int(p["lots"])
            shares = lots * 1000
            entry_date = str(p.get("entry_date", today_str))
            hold_days = (date.today() - date.fromisoformat(entry_date)).days
            positions[ticker] = {
                "entry_price": entry_price,
                "lots": lots,
                "shares": shares,
                "stop_loss": float(p.get("stop_loss", round(entry_price * 0.95, 2))),
                "take_profit": float(p.get("take_profit", round(entry_price * 1.10, 2))),
                "entry_date": entry_date,
                "hold_days": hold_days,
            }

        position_value = sum(p["entry_price"] * p["shares"] for p in positions.values())
        portfolio_value = cash + position_value

        state: dict[str, Any] = {
            "portfolio_value": round(portfolio_value, 0),
            "cash": round(cash, 0),
            "positions": positions,
            "closed_today": [],
        }
        POSITIONS_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # ── 歷史交易轉換 ────────────────────────────────────────────
        closed: list[dict[str, Any]] = []
        for t in data.get("past_trades", []):
            entry_price = float(t["entry_price"])
            exit_price = float(t["exit_price"])
            lots = int(t["lots"])
            shares = lots * 1000
            entry_date = str(t.get("entry_date", today_str))
            exit_date = str(t.get("exit_date", today_str))
            hold_days = (date.fromisoformat(exit_date) - date.fromisoformat(entry_date)).days
            pnl_twd = (exit_price - entry_price) * shares
            pnl_pct = (exit_price / entry_price - 1) * 100
            closed.append({
                "ticker": str(t["ticker"]),
                "entry": entry_price,
                "exit": exit_price,
                "pnl_twd": round(pnl_twd, 0),
                "pnl_pct": round(pnl_pct, 2),
                "reason": str(t.get("reason", "manual")),
                "hold_days": hold_days,
            })

        winning = [t for t in closed if t["pnl_twd"] > 0]
        win_rate = len(winning) / len(closed) if closed else 0.0
        avg_hold = sum(t["hold_days"] for t in closed) / len(closed) if closed else 0.0
        total_return_pct = (portfolio_value / INITIAL_PORTFOLIO_VALUE - 1) * 100

        pnl_entry: dict[str, Any] = {
            "date": today_str,
            "portfolio_value": round(portfolio_value, 0),
            "daily_pnl_twd": round(sum(t["pnl_twd"] for t in closed), 0),
            "unrealized_pnl_twd": 0.0,
            "total_return_pct": round(total_return_pct, 2),
            "max_drawdown_pct": 0.0,
            "win_rate": round(win_rate, 3),
            "total_trades": len(closed),
            "avg_hold_days": round(avg_hold, 1),
            "closed_today": closed,
        }
        PNL_HISTORY_FILE.write_text(
            json.dumps([pnl_entry], ensure_ascii=False, indent=2), encoding="utf-8"
        )

        logger.info(
            "Init 完成 → 持倉 %d 檔，歷史交易 %d 筆，總資產 %.0f TWD",
            len(positions), len(closed), portfolio_value,
        )
        lines = [
            "✅ 初始化完成",
            f"   現金：{cash:,.0f} TWD",
            f"   持倉：{len(positions)} 檔（成本市值 {position_value:,.0f} TWD）",
            f"   總資產：{portfolio_value:,.0f} TWD",
            f"   歷史交易：{len(closed)} 筆（勝率 {win_rate:.1%}，均持 {avg_hold:.1f} 日）",
            f"   → {POSITIONS_FILE}",
            f"   → {PNL_HISTORY_FILE}",
        ]
        return "\n".join(lines)

    # ── Phase 1: News ──────────────────────────────────────────────

    def _phase_news(
        self,
        steps_dir: Path,
        force_steps: set[str],
        only_steps: set[str],
        today: str,
    ) -> dict:
        artifact = steps_dir / "news.json"
        if "news" not in only_steps:
            return json.loads(artifact.read_text(encoding="utf-8")) if artifact.exists() else {"articles": []}
        if artifact.exists() and "news" not in force_steps:
            logger.info("Step news      : 載入既有 artifact")
            return json.loads(artifact.read_text(encoding="utf-8"))

        logger.info("Step news      : 執行中...")
        from tools.fetchers.tw_news import fetch as fetch_news
        articles = fetch_news()
        data = {"articles": articles, "fetched_at": datetime.now().isoformat(timespec="seconds")}
        artifact.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Step news      : 完成 → %d 篇新聞", len(articles))
        return data

    # ── Phase 2: Sentiment ─────────────────────────────────────────

    def _phase_sentiment(
        self,
        steps_dir: Path,
        force_steps: set[str],
        only_steps: set[str],
        news_data: dict,
    ) -> dict:
        artifact = steps_dir / "sentiment.json"
        _default = {"overall": "neutral", "score": 0.5, "sector_signals": {}, "bearish_sectors": []}
        if "sentiment" not in only_steps:
            return json.loads(artifact.read_text(encoding="utf-8")) if artifact.exists() else _default
        if artifact.exists() and "sentiment" not in force_steps:
            logger.info("Step sentiment : 載入既有 artifact")
            return json.loads(artifact.read_text(encoding="utf-8"))

        logger.info("Step sentiment : 執行中...")
        articles = news_data.get("articles", [])
        if not articles:
            logger.info("Step sentiment : 無新聞，使用中性預設值")
            artifact.write_text(json.dumps(_default, ensure_ascii=False, indent=2), encoding="utf-8")
            return _default

        raw = self._complete(prompts.build_sentiment_prompt(json.dumps(articles, ensure_ascii=False)))
        result = parse_llm_json(raw)
        result.setdefault("overall", "neutral")
        result.setdefault("score", 0.5)
        result.setdefault("sector_signals", {})
        result.setdefault("bearish_sectors", [])
        artifact.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Step sentiment : 完成 → overall=%s score=%.2f", result["overall"], result["score"])
        return result

    # ── Phase 3: Market Data ───────────────────────────────────────

    def _phase_market_data(
        self,
        steps_dir: Path,
        force_steps: set[str],
        only_steps: set[str],
    ) -> dict:
        artifact = steps_dir / "market_data.json"
        if "market_data" not in only_steps:
            return json.loads(artifact.read_text(encoding="utf-8")) if artifact.exists() else {}
        if artifact.exists() and "market_data" not in force_steps:
            logger.info("Step market_data: 載入既有 artifact")
            return json.loads(artifact.read_text(encoding="utf-8"))

        logger.info("Step market_data: 執行中...")
        from tools.fetchers.tw_market import fetch_stock, fetch_txf
        from agents.tw_stock.watchlist import get_tickers

        token = os.environ.get("FINMIND_TOKEN", "")
        stock_data_dir = DATA_DIR / "ohlcv"
        stock_data_dir.mkdir(parents=True, exist_ok=True)

        stocks: dict[str, Any] = {}
        for ticker in get_tickers():
            df = fetch_stock(ticker, stock_data_dir, token=token)
            if df.empty:
                logger.warning("Step market_data: %s 無資料，略過", ticker)
                continue
            stocks[ticker] = {
                "status": "ok",
                "current_close": float(df["close"].iloc[-1]),
                "rows": df.to_dict(orient="records"),
            }

        txf_df = fetch_txf()
        txf_data: dict[str, Any] = {
            "status": "ok" if not txf_df.empty else "error",
            "current_close": float(txf_df["close"].iloc[-1]) if not txf_df.empty else 0.0,
            "rows": txf_df.to_dict(orient="records") if not txf_df.empty else [],
        }

        data = {
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "stocks": stocks,
            "txf": txf_data,
        }
        artifact.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Step market_data: 完成 → %d 檔個股 + TXF", len(stocks))
        return data

    # ── Phase 4: Technical ─────────────────────────────────────────

    def _phase_technical(
        self,
        steps_dir: Path,
        force_steps: set[str],
        only_steps: set[str],
        market_data: dict,
    ) -> dict:
        artifact = steps_dir / "technical.json"
        if "technical" not in only_steps:
            return json.loads(artifact.read_text(encoding="utf-8")) if artifact.exists() else {}
        if artifact.exists() and "technical" not in force_steps:
            logger.info("Step technical : 載入既有 artifact")
            return json.loads(artifact.read_text(encoding="utf-8"))

        logger.info("Step technical : 執行中...")
        from tools.predictors.algorithm import predict

        results: dict = {}
        for ticker, stock_info in market_data.get("stocks", {}).items():
            if stock_info.get("status") != "ok":
                continue
            df = pd.DataFrame(stock_info["rows"])
            if df.empty or len(df) < 10:
                continue
            try:
                results[ticker] = predict(df)
            except Exception as e:
                logger.warning("Step technical : %s predict() 失敗：%s", ticker, e)

        txf_info = market_data.get("txf", {})
        if txf_info.get("status") == "ok" and txf_info.get("rows"):
            txf_df = pd.DataFrame(txf_info["rows"])
            try:
                results["TXF"] = predict(txf_df)
            except Exception as e:
                logger.warning("Step technical : TXF predict() 失敗：%s", e)

        artifact.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Step technical : 完成 → %d 檔", len(results))
        return results

    # ── Phase 5: Signal ────────────────────────────────────────────

    def _phase_signal(
        self,
        steps_dir: Path,
        force_steps: set[str],
        only_steps: set[str],
        sentiment: dict,
        technical: dict,
        market_data: dict,
    ) -> list[dict]:
        artifact = steps_dir / "signal.json"
        if "signal" not in only_steps:
            return json.loads(artifact.read_text(encoding="utf-8")) if artifact.exists() else []
        if artifact.exists() and "signal" not in force_steps:
            logger.info("Step signal    : 載入既有 artifact")
            return json.loads(artifact.read_text(encoding="utf-8"))

        logger.info("Step signal    : 執行中...")
        from agents.tw_stock.signal import build_signals, compute_cross_stock_centrality

        stocks = market_data.get("stocks", {})
        centrality: dict[str, float] = {}
        if len(stocks) >= 2:
            returns_data: dict[str, Any] = {}
            for ticker, info in stocks.items():
                if info.get("status") == "ok" and info.get("rows"):
                    df = pd.DataFrame(info["rows"])
                    if len(df) >= CORRELATION_LOOKBACK_DAYS:
                        df = df.tail(CORRELATION_LOOKBACK_DAYS)
                    closes = df["close"].astype(float)
                    returns_data[ticker] = closes.pct_change().dropna()

            if len(returns_data) >= 2:
                min_len = min(len(v) for v in returns_data.values())
                returns_df = pd.DataFrame(
                    {t: v.values[-min_len:] for t, v in returns_data.items()}
                )
                centrality = compute_cross_stock_centrality(
                    returns_df, threshold=CORRELATION_THRESHOLD
                )

        signals = build_signals(sentiment, technical, centrality, boost_factor=CENTRALITY_BOOST_FACTOR)
        artifact.write_text(json.dumps(signals, ensure_ascii=False, indent=2), encoding="utf-8")
        buy_count = sum(1 for s in signals if s.get("direction") == "BUY")
        logger.info("Step signal    : 完成 → %d 個訊號（%d BUY）", len(signals), buy_count)
        return signals

    # ── Phase 6: Paper Trade ───────────────────────────────────────

    def _phase_paper_trade(
        self,
        steps_dir: Path,
        force_steps: set[str],
        only_steps: set[str],
        signals: list[dict],
        market_data: dict,
        today: str,
    ) -> dict:
        artifact = steps_dir / "paper_trade.json"
        if "paper_trade" not in only_steps:
            return json.loads(artifact.read_text(encoding="utf-8")) if artifact.exists() else {}
        if artifact.exists() and "paper_trade" not in force_steps:
            logger.info("Step paper_trade: 載入既有 artifact")
            return json.loads(artifact.read_text(encoding="utf-8"))

        logger.info("Step paper_trade: 執行中...")
        from agents.tw_stock.paper_trade import process_paper_trade

        existing = _load_json(POSITIONS_FILE, default={
            "portfolio_value": INITIAL_PORTFOLIO_VALUE,
            "cash": INITIAL_PORTFOLIO_VALUE,
            "positions": {},
        })
        portfolio_value = existing.get("portfolio_value", INITIAL_PORTFOLIO_VALUE)
        cash = existing.get("cash", INITIAL_PORTFOLIO_VALUE)
        positions = existing.get("positions", {})

        market_prices = {
            t: info["current_close"]
            for t, info in market_data.get("stocks", {}).items()
        }
        txf_close = market_data.get("txf", {}).get("current_close", 0.0)
        if txf_close:
            market_prices["TXF"] = txf_close

        result = process_paper_trade(
            signals=signals,
            positions=positions,
            market_prices=market_prices,
            portfolio_value=portfolio_value,
            cash=cash,
            today=today,
            max_new=MAX_DAILY_NEW_POSITIONS,
            max_total=MAX_TOTAL_POSITIONS,
            min_score=SIGNAL_MIN_SCORE,
            risk_pct=RISK_PER_TRADE_PCT,
        )

        POSITIONS_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "Step paper_trade: 完成 → 持倉 %d 檔，今日平倉 %d 筆",
            len(result["positions"]),
            len(result["closed_today"]),
        )
        return result

    # ── Phase 7: PnL ──────────────────────────────────────────────

    def _phase_pnl(
        self,
        steps_dir: Path,
        force_steps: set[str],
        only_steps: set[str],
        paper_trade: dict,
        market_data: dict,
        today: str,
    ) -> dict:
        artifact = steps_dir / "pnl.json"
        if "pnl" not in only_steps:
            return json.loads(artifact.read_text(encoding="utf-8")) if artifact.exists() else {}
        if artifact.exists() and "pnl" not in force_steps:
            logger.info("Step pnl       : 載入既有 artifact")
            return json.loads(artifact.read_text(encoding="utf-8"))

        logger.info("Step pnl       : 執行中...")
        from agents.tw_stock.paper_trade import compute_pnl_summary

        pnl_history = _load_json(PNL_HISTORY_FILE, default=[])
        market_prices = {
            t: info["current_close"]
            for t, info in market_data.get("stocks", {}).items()
        }

        result = compute_pnl_summary(
            paper_trade=paper_trade,
            pnl_history=pnl_history,
            today=today,
            market_prices=market_prices,
            initial_value=INITIAL_PORTFOLIO_VALUE,
        )

        pnl_history = [h for h in pnl_history if h.get("date") != today]
        pnl_history.append({**result, "closed_today": paper_trade.get("closed_today", [])})
        PNL_HISTORY_FILE.write_text(
            json.dumps(pnl_history, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        artifact.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "Step pnl       : 完成 → 累積報酬 %.2f%% 最大回撤 %.2f%%",
            result["total_return_pct"],
            result["max_drawdown_pct"],
        )
        return result

    # ── Phase 8: Notify ────────────────────────────────────────────

    def _phase_notify(
        self,
        steps_dir: Path,
        day_dir: Path,
        force_steps: set[str],
        only_steps: set[str],
        signals: list[dict],
        pnl: dict,
        paper_trade: dict,
        sentiment: dict,
        today: str,
    ) -> None:
        done_file = day_dir / "telegram_stock.done"
        if "notify" not in only_steps:
            return
        if done_file.exists() and "notify" not in force_steps:
            logger.info("Step notify    : 已發送過，略過")
            return

        logger.info("Step notify    : 執行中...")
        from tools.notifiers.telegram import send

        signals_json = json.dumps(signals, ensure_ascii=False)
        pnl_json = json.dumps(pnl, ensure_ascii=False)
        paper_trade_json = json.dumps(
            {
                "positions": paper_trade.get("positions", {}),
                "closed_today": paper_trade.get("closed_today", []),
            },
            ensure_ascii=False,
        )
        sentiment_json = json.dumps(sentiment, ensure_ascii=False)

        raw1 = self._complete(prompts.build_notify_signal_prompt(today, signals_json, sentiment_json))
        raw2 = self._complete(prompts.build_notify_pnl_prompt(today, pnl_json, paper_trade_json))

        res1 = parse_llm_json(raw1)
        res2 = parse_llm_json(raw2)

        ok1 = ok2 = False
        if msg1 := res1.get("tg_signal", ""):
            (steps_dir / "telegram_signal.txt").write_text(msg1, encoding="utf-8")
            ok1 = send(msg1, token_env=STOCK_BOT_TOKEN_ENV, chat_id_env=STOCK_CHAT_ID_ENV)

        if msg2 := res2.get("tg_pnl", ""):
            (steps_dir / "telegram_pnl.txt").write_text(msg2, encoding="utf-8")
            ok2 = send(msg2, token_env=STOCK_BOT_TOKEN_ENV, chat_id_env=STOCK_CHAT_ID_ENV)

        if ok1 and ok2:
            done_file.touch()
            logger.info("Step notify    : 完成")
        else:
            logger.error("Step notify    : 訊息發送失敗（ok1=%s ok2=%s）", ok1, ok2)

    def _complete(self, prompt: str) -> str:
        return self._llm.complete(prompt, system=prompts.SYSTEM)


# ── Module-level helpers ───────────────────────────────────────────

def _parse_args(args: str) -> tuple[set[str], set[str]]:
    tokens = shlex.split(args) if args.strip() else []
    force: set[str] = set()
    only: set[str] = set()
    i = 0
    while i < len(tokens):
        if tokens[i] == "--force":
            i += 1
            while i < len(tokens) and not tokens[i].startswith("--"):
                if tokens[i] in ALL_STEPS:
                    force.add(tokens[i])
                i += 1
        elif tokens[i] == "--only":
            i += 1
            while i < len(tokens) and not tokens[i].startswith("--"):
                if tokens[i] in ALL_STEPS:
                    only.add(tokens[i])
                i += 1
        else:
            i += 1
    return force, only


def _load_json(path: Path, default: Any) -> Any:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("_load_json: 無法讀取 %s (%s)，使用預設值", path, e)
    return default


def _build_init_template() -> dict[str, Any]:
    """產生 init.json 使用者填寫範本。"""
    return {
        "_使用說明": (
            "填寫完成後執行：python3 main.py \"/tw-stock --init\"。"
            "stop_loss / take_profit 省略時分別預設為成本價的 -5% / +10%。"
            "entry_date / exit_date 格式：YYYY-MM-DD。"
            "reason 可填：take_profit / stop_loss / max_hold / signal_reversal / manual。"
            "執行後此檔案不會被刪除，可修改後再次執行以更新狀態。"
        ),
        "cash": INITIAL_PORTFOLIO_VALUE,
        "positions": [
            {
                "_範例": "台積電 1 張，成本 905 元，止損 885，止盈 950",
                "ticker": "2330",
                "entry_price": 905.0,
                "lots": 1,
                "stop_loss": 885.0,
                "take_profit": 950.0,
                "entry_date": date.today().strftime("%Y-%m-%d"),
            }
        ],
        "past_trades": [
            {
                "_範例": "聯發科 1 張，成本 1050，賣出 1082，持有 5 日，止盈出場",
                "ticker": "2454",
                "entry_price": 1050.0,
                "exit_price": 1082.0,
                "lots": 1,
                "entry_date": "2026-04-28",
                "exit_date": "2026-05-03",
                "reason": "take_profit",
            }
        ],
    }

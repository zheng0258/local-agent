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
from tools.notifiers.telegram import send as _tg_send

def telegram_send(text: str) -> bool:
    return _tg_send(text, token_env="STOCK_TELEGRAM_BOT_TOKEN", chat_id_env="STOCK_TELEGRAM_CHAT_ID")
from tools.predictors.algorithm import backtest

from agents.stock_predictor.config import OHLCV_DIR, STATS_DIR, load_watchlist
from tools.fetchers.finmind import load_ohlcv

from .config import BACKTEST_WINDOW, STRATEGY_VARIANTS
from .prompts import comparison_prompt

logger = get_logger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
OUTPUTS_DIR = REPO_ROOT / "outputs" / "stock-analyst"


class StockAnalystAgent:
    AGENT_NAME = "stock_analyst"

    def __init__(self, llm: LLMBackend | None = None) -> None:
        self._llm = llm or get_llm()

    def run(self, args: str = "") -> str:
        watchlist = load_watchlist()
        if not watchlist:
            return "watchlist 為空，跳過策略分析。"

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

                best_variant = max(variant_results, key=lambda v: variant_results[v]["direction_acc"])
                self._save_recommendation(ticker, best_variant, variant_results[best_variant])
            except Exception as e:
                logger.warning("分析 %s 失敗：%s", ticker, e)

        if not all_reports:
            return "所有股票分析均失敗。"

        report_md = f"# 策略分析報告 {today}\n\n" + "\n---\n".join(all_reports)
        report_path = out_dir / "report.md"
        report_path.write_text(report_md, encoding="utf-8")

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
                    "direction_acc": 0.0,
                    "exact_hit_rate": 0.0,
                    "adjacent_hit_rate": 0.0,
                    "n_predictions": 0,
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
        return self._llm.complete(prompt, system="你是專業台股量化策略分析師。輸出繁體中文。")

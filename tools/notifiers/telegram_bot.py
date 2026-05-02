"""tools/notifiers/telegram_bot.py

長駐 Telegram Bot，負責 watchlist CRUD。
啟動方式：python3 -m tools.notifiers.telegram_bot
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

REPO_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
WATCHLIST = DATA_DIR / "watchlist.json"
STATS_DIR = DATA_DIR / "stats"
DATA_DIR.mkdir(exist_ok=True)


def _read_watchlist() -> dict:
    if WATCHLIST.exists():
        return json.loads(WATCHLIST.read_text())
    return {"stocks": [], "added_at": {}}


def _save_watchlist(data: dict) -> None:
    WATCHLIST.write_text(json.dumps(data, indent=2, ensure_ascii=False))


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
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    reply = result.stdout.strip() or result.stderr.strip() or "完成（無輸出）"
    await update.message.reply_text(reply[:4000])


def _load_project_env() -> None:
    """從專案根目錄 .env 載入環境變數（setdefault，不覆蓋已有值）。"""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def run() -> None:
    _load_project_env()
    token = os.environ.get("STOCK_TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("STOCK_TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("unwatch", cmd_unwatch))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("predict", cmd_predict))

    print("Telegram Bot 已啟動，監聽指令中…")
    app.run_polling()


if __name__ == "__main__":
    run()

# agents/tw_stock/prompts.py
"""tw_stock Agent — 所有 LLM prompts。"""
from __future__ import annotations

SYSTEM = (
    "你是台灣股市分析助手。\n"
    "輸出語言：繁體中文（股票代號、英文術語保持原文）。\n"
    "需要結構化輸出時，回傳合法 JSON（可用 ```json 包裹）。"
)


def build_sentiment_prompt(articles_json: str) -> str:
    return (
        "請分析以下台灣財經新聞，判斷今日市場整體情緒與板塊方向。\n\n"
        f"新聞列表：\n{articles_json}\n\n"
        "回傳 JSON，格式如下：\n"
        "{\n"
        '  "overall": "bullish" | "bearish" | "neutral",\n'
        '  "score": 0.0-1.0（0=極度悲觀, 0.5=中立, 1.0=極度樂觀）,\n'
        '  "sector_signals": {\n'
        '    "半導體": {"direction": "bullish"|"bearish"|"neutral", "stocks": ["2330", "2454"]},\n'
        "    ...\n"
        "  },\n"
        '  "bearish_sectors": ["電信", ...]\n'
        "}\n\n"
        "判斷依據：\n"
        "- 看多關鍵詞：上漲、創高、訂單增加、獲利成長、看好、突破\n"
        "- 看空關鍵詞：下跌、跌破、獲利衰退、庫存問題、砍單、虧損\n"
        "- 中性：橫盤、持平、觀望"
    )


def build_notify_signal_prompt(today: str, signals_json: str, sentiment_json: str) -> str:
    return (
        f"今日日期：{today}\n\n"
        f"台股訊號列表（JSON）：\n{signals_json}\n\n"
        f"市場情緒（JSON）：\n{sentiment_json}\n\n"
        "請生成 Telegram HTML 訊號報告（第一封訊息），格式如下：\n"
        "📊 <b>台股訊號</b> {today}\n\n"
        "🟢 BUY 訊號（N）\n"
        "• <b><a href=\"https://tw.finance.yahoo.com/quote/{ticker}.TW\">{ticker} {name}</a></b>"
        " [{technical_interval}] 信心{pct}%  {strength}\n"
        "   止損 {sl}（{sl_pct}%）  止盈 {tp}  {leader_mark}\n\n"
        "⚪ 觀望（N）{tickers...}\n\n"
        "📰 情緒：{overall_text} {score}｜{key_theme}\n\n"
        "規則：\n"
        "- 只允許 Telegram HTML tag：<b>, <i>, <a href>, <code>\n"
        "- ▲領頭羊：is_leader=true 時加上\n"
        "- 訊號按 final_score 降序排列\n"
        "- 未發 BUY 訊號的股票列為觀望（最多顯示 10 個代號）\n"
        "- 總字元數 ≤ 4096\n"
        "回傳 JSON：{\"tg_signal\": \"<HTML 訊息>\"}"
    )


def build_notify_pnl_prompt(today: str, pnl_json: str, paper_trade_json: str) -> str:
    return (
        f"今日日期：{today}\n\n"
        f"損益資料（JSON）：\n{pnl_json}\n\n"
        f"持倉與平倉資料（JSON）：\n{paper_trade_json}\n\n"
        "請生成 Telegram HTML 紙上績效報告（第二封訊息），格式如下：\n"
        "💼 <b>紙上交易</b> {today}\n\n"
        "本日損益  +/- {daily_pnl}（{pct}%）\n"
        "累計報酬  {total_return}%  最大回撤 {drawdown}%\n"
        "勝率 {win_rate}%  均持 {avg_hold}日\n\n"
        "🟢 持倉（N）\n"
        "• <b>{ticker}</b>  {entry}→{current}  {unrealized_pnl}（{pct}%）  {note}\n\n"
        "✅ 今日平倉\n"
        "• <b>{ticker}</b>  {pnl}（{pct}%）{reason}\n\n"
        "規則：\n"
        "- 只允許 Telegram HTML tag：<b>, <i>, <a href>, <code>\n"
        "- 無持倉或無平倉時對應段落省略\n"
        "- ⚠️近止盈：持倉浮盈 > (take_profit - entry) × 80%\n"
        "- ✴️加碼訊號：持倉且今日有 BUY 訊號\n"
        "- 總字元數 ≤ 4096\n"
        "回傳 JSON：{\"tg_pnl\": \"<HTML 訊息>\"}"
    )

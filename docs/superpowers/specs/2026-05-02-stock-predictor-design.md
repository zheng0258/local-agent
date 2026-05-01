# Taiwan Stock Predictor — Design Spec

**Date:** 2026-05-02  
**Status:** Approved  
**Scope:** 每日台股預測訊號系統（De Bruijn + Markov + PageRank）+ 每週 LLM 策略分析

---

## 1. 整體架構

### 新增 Agents

| Agent | 觸發 | 排程 | 說明 |
|-------|------|------|------|
| `stock_predictor` | `/stock-predict` | 每日 15:30 TWN | 交易日判斷 → 隔日驗證 → 全 watchlist 預測 → Telegram |
| `stock_analyst` | `/stock-analyze` | 每週六 10:00 | 策略變體回測 → LLM 比較優缺點 + 改良建議 |

### 新增 Tools

| Tool | 類型 | 職責 |
|------|------|------|
| `tools/fetchers/finmind.py` | 純函數 | FinMind OHLCV 抓取 + 增量更新 CSV |
| `tools/predictors/algorithm.py` | 純函數 | ALGORITHM.md Step 2–12 完整實作 |
| `tools/notifiers/telegram_bot.py` | 長駐程序 | Telegram Bot polling，watchlist CRUD |

### 目錄結構

```
agents/
├── stock_predictor/
│   ├── agent.py       # 每日流程編排
│   ├── prompts.py     # （預留，目前無 LLM prompt）
│   └── config.py      # 預設超參數、路徑常數
└── stock_analyst/
    ├── agent.py       # 策略分析流程編排
    ├── prompts.py     # LLM 比較分析 prompts
    └── config.py      # 策略變體定義、回測視窗

tools/
├── fetchers/
│   └── finmind.py
├── predictors/
│   └── algorithm.py
└── notifiers/
    └── telegram_bot.py

data/                           # git ignore
├── watchlist.json
├── ohlcv/
│   └── {ticker}.csv            # 完整歷史 OHLCV（增量補抓）
├── model_params/
│   └── {ticker}.json           # 各股策略分析建議參數
└── stats/
    └── {ticker}.json           # 累積預測準確率

outputs/stock-predictor/
└── {today}/
    ├── predictions/
    │   └── {ticker}.json       # 當日預測 artifact（供隔日驗證）
    └── verify.json             # 驗證結果

outputs/stock-analyst/
└── {today}/
    └── report.md               # LLM 策略分析報告
```

---

## 2. 每日預測流程（stock_predictor）

### 交易日判斷

```
tw_holidays.json + 週六週日 → 今天非交易日 → 靜默退出（無 Telegram 通知）
```

### 隔日驗證（verify）

1. 讀 `outputs/stock-predictor/{yesterday}/predictions/*.json`
2. 從 FinMind 抓昨日實際收盤價（增量更新 CSV 的副產品）
3. 計算 `is_exact_hit` / `is_direction_correct` / `is_adjacent_hit`
4. 累積寫入 `data/stats/{ticker}.json`

### 預測（predict）—— 並行跑所有 watchlist 股票

每支股票：
1. `finmind.fetch_incremental(ticker)` — 補抓新資料到 `data/ohlcv/{ticker}.csv`
2. 讀取 `data/model_params/{ticker}.json`（存在用之，否則用預設值）
3. `algorithm.predict(df, params)` — Step 2–12
4. 存 `outputs/stock-predictor/{today}/predictions/{ticker}.json`
5. `most_likely ∈ {R1, R2, R3}` → 組訊號卡 → `telegram.send()`

### 無訊號彙總

所有股票均為 S / F0 時，發一則彙總：
```
📊 今日無多頭訊號（共掃描 N 支）
```

### Telegram 訊號卡格式

```
📈 <b>2330 台積電</b> [R2] 信心 62%
區間：+2.0% ~ +4.0%
預計收盤：<code>940.5</code>
止損：920.3（-1.8%）
止盈：935.0（+2.4%）
強度：Moderate ｜ 13:20 強制出場
```

---

## 3. Telegram Bot（watchlist 管理）

長駐程序：`python3 -m tools.notifiers.telegram_bot`  
模式：polling（python-telegram-bot 庫）  
保活：n8n 或系統 supervisor

### 支援指令

| 指令 | 說明 |
|------|------|
| `/watch 2330` | 加入 watchlist，觸發全量 OHLCV 抓取（最多 1250 天） |
| `/unwatch 2330` | 移出 watchlist |
| `/watchlist` | 列出所有追蹤股票 |
| `/stats 2330` | 顯示累積準確率（direction_acc / exact_hit_rate / 樣本數） |
| `/predict 2330` | 立即觸發單股預測（不等排程） |

### 資料結構

**watchlist.json**
```json
{
  "stocks": ["2330", "2317", "0050"],
  "added_at": {"2330": "2026-05-01", "2317": "2026-04-20"}
}
```

**stats/{ticker}.json**
```json
{
  "total": 29,
  "direction_correct": 21,
  "exact_hit": 10,
  "adjacent_hit": 18,
  "direction_acc": 0.724,
  "exact_hit_rate": 0.345,
  "adjacent_hit_rate": 0.621
}
```

---

## 4. 每週 LLM 策略分析（stock_analyst）

### 目標

取代黑盒 Optuna 調優，用本地 LLM（與 daily-brief 共用 `get_llm()`）提供**可解釋的策略比較與改良建議**。

### 流程

```
stock_analyst.run()
│
├─ [1] 載入策略變體（config.py 定義）
│       v1: 純 Markov（λ1=1.0, λ2=0, λ3=0）
│       v2: Markov + PageRank（λ1=0.6, λ2=0.4, λ3=0）
│       v3: 完整三組合（ALGORITHM.md 預設值）
│       v4: 高階記憶 n_order=6
│       v5: 無 regime 過濾
│       v6: 無時間衰減（decay_gamma=0）
│       （可在 config.py 新增更多）
│
├─ [2] 對每支 watchlist 股票，逐變體 walk-forward 回測
│       algorithm.backtest(df, params) → {direction_acc, exact_hit_rate, adjacent_hit_rate}
│       結果矩陣：{ticker: {variant: metrics}}
│
├─ [3] LLM 分析
│       輸入：回測結果表 + ALGORITHM.md 精華摘要 + 當前 stats
│       輸出 A：各變體優缺點比較（表格 + 文字說明）
│       輸出 B：具體演算法改良建議（指出弱點 + 提出修改方向）
│
└─ [4] 輸出
        outputs/stock-analyst/{today}/report.md
        Telegram 發送摘要（最重要 2–3 條建議）
```

### 與 Optuna 對比

| 面向 | Optuna | LLM 策略分析 |
|------|--------|--------------|
| 輸出 | 最佳參數 JSON | 可讀報告 + 建議 |
| 可解釋性 | 無 | 有（LLM 說明原因） |
| 使用者學習 | 無 | 了解算法弱點 |
| 過擬合風險 | 高 | 低（LLM 推理而非搜尋）|
| 模型依賴 | 無 | 本地 LLM 品質 |

### model_params/{ticker}.json（分析後建議參數）

```json
{
  "ticker": "2330",
  "analyzed_at": "2026-05-03",
  "recommended_variant": "v3",
  "score": 0.681,
  "params": {
    "n_order": 4,
    "lookback_days": 500,
    "decay_gamma": 0.006,
    "lambda1": 0.62,
    "lambda2": 0.28,
    "lambda3": 0.10
  },
  "llm_rationale": "v3 在 Bull 市場表現最穩定，regime filtering 對 Bear 市場有效..."
}
```

---

## 5. 路由整合

### AGENTS.md 新增路由

| Agent | 觸發條件 | 入口 |
|-------|----------|------|
| `stock_predictor` | `/stock-predict`、`跑股票預測` | `agents/stock_predictor/agent.py` |
| `stock_analyst` | `/stock-analyze`、`跑策略分析` | `agents/stock_analyst/agent.py` |

### n8n workflow 新增觸發

| 時間 | 指令 |
|------|------|
| 每日 15:30 TWN | `python3 main.py "/stock-predict"` |
| 每週六 10:00 TWN | `python3 main.py "/stock-analyze"` |

---

## 6. 資料流與 tw_holidays.json 使用

- `stock_predictor` 入口：讀取 `tw_holidays.json` 判斷今日是否交易日，非交易日靜默退出
- `finmind.fetch_incremental()`：跳過非交易日的日期缺口（正常現象，不補抓）
- 隔日驗證：確認昨日是否為交易日後再執行

---

## 7. 外部依賴

```
pip install ta networkx python-telegram-bot finmind
FINMIND_API_TOKEN=...    # 加入 Scripts/.env
```

- LLM：`get_llm()`（與 daily-brief 共用，無額外配置）
- Optuna：**不引入**（由 LLM 策略分析取代）

# Telegram 使用者互動設計

**日期**：2026-04-22  
**狀態**：已核可，待實作  

## 目標

Daily Brief 透過 Telegram 發送後，讓使用者可以標記感興趣的文章，系統學習偏好並回饋至隔日的 LLM 評分，使推薦內容隨時間越來越精準。

## 設計決策摘要

| 面向 | 決定 |
|---|---|
| 互動方式 | Inline keyboard 數字按鈕（`⭐1`…`⭐8`）附在 digest 訊息底部 |
| 多選 | 每次點擊一個 callback，pipeline 批次合併處理 |
| 偏好機制 | 主題 tag 輪廓（LLM 萃取，Haiku 4.5）|
| Callback 讀取時機 | 每日 pipeline 啟動時一次性 `getUpdates` |
| 偏好持久化 | 永久累積 |

---

## 架構

### Pipeline 步驟順序

```
feedback → update_profile → hatena/hn/reddit/security → compress → digest → judge → report → save → notify
```

`feedback` 和 `update_profile` 為新增步驟，位於 fetch 之前。失敗時不 block 後續流程。

---

## 各元件設計

### 1. `feedback` 步驟

**職責**：批次讀取 Telegram callback，更新星標清單。

**流程**：
1. 讀取 `outputs/tg_offset.json` 取得上次 offset（不存在則呼叫 `getUpdates?limit=1` 取得當前最新 update_id，寫入 offset = update_id + 1，本次跳過處理）
2. 呼叫 `GET /getUpdates?offset={N}&timeout=0`
3. 過濾 `callback_query` 類型，解析 `callback_data` 格式 `{YYYYMMDD}:{hash8}`
4. 依 date 查找對應的 `outputs/daily-brief/{date}/steps/article_map.json`，取得完整文章資料
5. 去重（同一 URL 多次點擊只保留一筆），追加寫入 `outputs/starred.json`
6. 更新 `outputs/tg_offset.json`
7. 批次呼叫 `answerCallbackQuery` 清除所有 loading 狀態

**Artifact**：`steps/feedback.json`（記錄本次讀取到的新星標數量與 offset）

**失敗處理**：寫入 warning log，步驟標記失敗，後續步驟照常執行。

---

### 2. `update_profile` 步驟

**職責**：從新星標文章萃取主題 tag，累積偏好輪廓。

**流程**：
1. 讀取 `outputs/starred.json`，篩選 `processed: false` 的項目
2. 若無新項目則跳過（不呼叫 LLM）
3. 呼叫 Haiku 4.5，對每篇文章的 `title + summary` 萃取 2-4 個主題 tag
4. 更新 `outputs/preference_profile.json`（tag 計數累加）
5. 將 `starred.json` 中已處理項目標記 `processed: true`

**Artifact**：`steps/update_profile.json`

---

### 3. fetch 步驟（scoring prompt 改造）

**觸發條件**：`preference_profile.json` 存在且 `total_starred >= 3`

**改動**：在 hatena / hn / reddit / security 的評分 prompt 尾端附加：

```
使用者偏好主題（由高到低）：{tag}({count}), {tag}({count}), ...
評分時請適當提高與上述主題相關文章的 interest 分數。
```

**未達條件**：直接跳過注入，行為與現在完全一致。

---

### 4. `notify` 步驟（改造）

**新增行為**：
- 發送 digest 訊息時附加 `reply_markup`（InlineKeyboardMarkup）
- 按鈕數量 = 實際 digest 篇數（上限 8），每排 4 顆：`⭐1`…`⭐N`
- 同時寫入 `steps/article_map.json`

**Fallback**：`send_with_buttons()` 若回傳 400，自動 fallback 呼叫原本的 `send()`，確保通知照常發出（沒有按鈕）。

**現有 `send()` 函式不改動**，新增獨立的 `send_with_buttons()` 函式。

---

## callback_data 格式

```
{YYYYMMDD}:{url_sha256[:8]}
範例：20260422:abc123de   （18 bytes，< 64 bytes 上限）
```

日期欄位讓 pipeline 知道去哪個日期的 `article_map.json` 查找文章，支援使用者點擊舊日文章（跨日追溯）。

**限制**：Telegram `getUpdates` 未確認的 callback 最多保留約 24 小時。正常每日執行不會觸發此問題。補救機制（透過 message_id 補查）列為 future work。

---

## 新增 / 修改檔案

### 新增檔案

| 路徑 | 說明 |
|---|---|
| `agents/daily_brief/preferences.py` | starred.json / preference_profile.json / tg_offset.json 讀寫邏輯 |
| `outputs/starred.json` | 永久星標文章清單 |
| `outputs/preference_profile.json` | 主題 tag 權重輪廓 |
| `outputs/tg_offset.json` | getUpdates offset 記錄 |
| `outputs/daily-brief/{date}/steps/article_map.json` | hash8 → 文章資料（notify 時寫入）|

### 修改檔案

| 路徑 | 改動 |
|---|---|
| `agents/daily_brief/agent.py` | 新增 `_phase_feedback()`、`_phase_update_profile()`；更新 `ALL_STEPS` |
| `agents/daily_brief/prompts.py` | 新增 `build_preference_context(profile: dict) -> str` |
| `tools/notifiers/telegram.py` | 新增 `send_with_buttons(text, buttons)` |

---

## 資料結構

### `starred.json`

```json
[
  {
    "url": "https://...",
    "title": "Axios npm 包遭供應鏈攻擊",
    "source": "Aikido",
    "summary": "...",
    "date": "2026-04-22",
    "starred_at": "2026-04-23T09:15:00",
    "processed": false
  }
]
```

### `preference_profile.json`

```json
{
  "updated_at": "2026-04-23",
  "total_starred": 7,
  "tags": {
    "supply-chain-attack": 4,
    "claude-code": 3,
    "llm-tools": 2
  }
}
```

### `tg_offset.json`

```json
{ "offset": 12345678 }
```

### `article_map.json`（每日 steps/ 目錄）

```json
{
  "abc123de": {
    "url": "https://...",
    "title": "...",
    "source": "Hatena",
    "summary": "..."
  }
}
```

---

## 影響評估

| 元件 | 影響程度 | 緩解方式 |
|---|---|---|
| compress / digest / judge / report / save | 無 | — |
| feedback / update_profile（新增）| 低，失敗不 block | graceful skip，log warning |
| notify（改造）| 低，additive | fallback 到原本 send() |
| fetch scoring（改造）| 中，預期行為改變 | total_starred < 3 時不注入 |

---

## 範圍外（Future Work）

- Callback 24h 過期補救機制
- 按鈕標記後即時顯示 ✅（需常駐進程）
- Obsidian 星標文章整合

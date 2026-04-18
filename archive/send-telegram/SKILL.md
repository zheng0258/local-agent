---
name: send-telegram
description: Use when sending a Telegram message to the user's personal bot. Triggered by /send-telegram or when another skill needs to deliver a notification. Accepts direct text or a list of texts for multi-part messages.
argument-hint: "<text> | --file <path> [--file <path2>]"
disable-model-invocation: true
---

## 功能說明

透過 Telegram Bot API 發送通知。從 `Scripts/.env` 讀取憑證，訊息超過 4096 字元自動截斷，憑證未設定時靜默略過。

## 常數

```
VAULT_ROOT = $HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Second-Brain
ENV_PATH   = {VAULT_ROOT}/Scripts/.env
MAX_LEN    = 4096
```

## 注意事項

- **憑證遺失不報錯**：`TELEGRAM_BOT_TOKEN` 或 `TELEGRAM_CHAT_ID` 未設定 → 印出警告、直接結束
- **使用 HTML parse_mode**：支援 `<b>粗體</b>` 與 `<a href="url">連結</a>`，呼叫方輸出 HTML 格式文字
- **多段訊息**：傳入多個文字時，依序發送，每段獨立計算 4096 限制

---

## Step 1–3：載入憑證 + Guard + 傳送函式（Python）

```python
import sys
sys.path.insert(0, "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Second-Brain/Scripts")
from send_telegram import send
# 憑證載入、guard 檢查、4096 截斷均由 send() 內部處理
```

---

## Step 4：依輸入模式呼叫

### 模式 A：直接文字（skill 引數 or 呼叫方傳入 Python 變數）

```python
# 呼叫方已有文字變數
send(my_text)
```

### 模式 B：--file 引數（讀取檔案後傳送）

```python
from datetime import date

# 例：/send-telegram --file "01 Projects/daily-brief/2026-03-16.md"
file_path = f"{VAULT}/{arg_file}"
with open(file_path, "r") as f:
    content = f.read()
send(content)
```

### 模式 C：多段訊息（list）

```python
messages = [msg1, msg2]  # 各自不超過 4096 字元
for msg in messages:
    if msg:
        send(msg)
```

---

## 呼叫範例（其他 skill 引用）

```python
# 在 daily-brief Step 12 中，產出 msg1 / msg2 後：
send(msg1)
if digest_content:
    send(msg2)
```

---

## Step 5：回報結果

輸出：

「Telegram 通知已發送。」 或 「⚠️ Telegram 略過（未設定憑證）。」

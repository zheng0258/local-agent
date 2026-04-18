# [AgentName] Agent

一行說明此 agent 的目標。

## 觸發條件

- `/command-name`
- 「自然語言觸發詞」

## 輸入

`args`：使用者輸入去掉觸發詞後的剩餘部分。

## 輸出

說明回傳的訊息格式。

## 依賴

- **Tools**：列出使用的 tools（`tools/fetchers/xxx.py` 等）
- **Notifiers**：列出使用的通知工具
- **Pipeline**：若有跨 agent 編排，列出 pipeline 名稱

## 流程

1. 步驟一
2. 步驟二
3. 步驟三

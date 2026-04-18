# DailyBrief Agent

收集當日科技趨勢（Hatena、HN、Reddit 16 子版、資安部落格），輸出繁體中文報告並發送 Telegram 通知。

## 觸發條件

- `/daily-brief`
- 「收集今日趨勢」、「跑趨勢收集」、「run daily-brief」

## 輸入

無（`args` 忽略）

## 輸出

報告存至 `{VAULT}/01 Projects/daily-brief/YYYY-MM-DD.md`，索引更新至 `_daily-brief.md`。

## 依賴

- **Tools/fetchers**：`hatena`、`hn`、`reddit`、`security_blogs`
- **Tools/notifiers**：`telegram`
- **Vault Scripts**：`Scripts/daily-brief/save_output.py`（存檔）

## 流程

```
hatena.fetch() → LLM 興趣評分  ─┐
hn.fetch()     → LLM 興趣評分  ─┤
reddit.fetch() → LLM 興趣評分  ─┤→ compress（Python 預篩選 ***，LLM 產 themes + one_liner）
security.fetch()→ LLM 興趣評分 ─┘
                                         ↓
                              digest（跨來源深度摘要）
                                         ↓
                              judge（LLM-as-Judge，slim context）
                                         ↓
                              report（純 markdown 趨勢報告）
                                         ↓
                              save（Obsidian vault）
                                         ↓
                              telegram.send(msg1 分群) + telegram.send(msg2 前8則摘要)
```

## Prompt 設計原則

- **fetch**：`prompts.build_*_prompt()` 包含 `_scoring_block()`（INTEREST_CRITERIA + few-shot 邊界範例）
- **compress**：只傳 `***` 文章（Python 預篩選），prompt 明確禁止丟棄任何一篇
- **digest**：明確要求對每一篇文章生成摘要，禁止跳過
- **judge**：只傳 `url + one_liner`（slim context），省 ~60% token
- **report**：直接輸出純 markdown，不包成 JSON；`_run_report()` 自動剝除 fence
- **notify msg2**：只傳前 8 篇 digests（`digests[:8]`）

# Step 快取失效：run 內上游傳播（現行）→ 輸入指紋快取鍵（建議下一步）

## Context

步驟化執行以「artifact 存在」當快取鍵：`step_cache.decide(in_steps, exists, forced)`
有檔就 LOAD。過期偵測只有 Fix C——`_detect_stale_downstream` 在 **run 開始時**以 mtime
比對一次（任一來源 artifact 比下游新 → 強制重跑下游）。

2026-10-17 實例：早上 rss 失敗，dedup 以四來源落盤 `dedup.json`（kept_urls 無 rss）。
下午重跑時 rss.json 尚不存在，Fix C 看不到；rss 隨後 RUN 成功，dedup 卻判 LOAD，
`DedupStep._load` 以舊 kept_urls 經 `filter_source_data_by_urls` 重濾上游 → **rss 全部
文章被濾掉**。人工 `--force dedup` 才補救。根因：快取鍵是「檔案存在 + 開跑時的 mtime」，
而不是「這份 artifact 是由哪份輸入算出來的」。

## Decision（本次實作：最小修復）

`_RunContext.ran_steps` 記本次 run 已 RUN（非 LOAD）的步驟；`Step._run_inner` 以
`step_cache.upstream_ran(name, ran_steps)` 判定，任一上游 RUN → `decide(..., upstream_ran=True)`
必回 RUN（等同 force，supervisor 亦重置 alert 去重）。上游關係用 `INVALIDATION_TIERS`
鏡射 `run()` 的接線順序，同層為並列兄弟互不失效：

```
sources(5) → dedup → compress → enrich → digest → {tldr, judge, report, compose_tg} → deploy
```

save / notify 不參與（同 Fix C：使用者決定的副作用步）。`--only` 收窄時仍尊重使用者意圖。
遞移性由「重跑的下游也記入 ran_steps」自然帶出，不另造依賴圖。Fix C 保留，負責跨 run。

## 評估：改為輸入指紋快取鍵

做法（類 Make/Bazel 的 action key、Dagster 的 code_version + data_version）：每步 RUN
時記下 `sha256(canonical_json(input))`（加上選填的 `code_version`），LOAD 前重算，
不符即失效。

| 面向 | 現行（存在 + mtime + ran_steps） | 輸入指紋 |
|---|---|---|
| 10-17 類（run 中途上游變動） | ran_steps 補上 | 天生涵蓋 |
| 跨 run / `--only` 分段重跑 | Fix C mtime（touch、git checkout、複製檔皆會誤判） | 依內容判定，與時間無關 |
| 精確度 | 保守：上游 RUN 但輸出相同也連鎖重跑 | 只有輸入真的變才重跑 |
| 程式 / prompt 改版 | 不偵測（靠手動 `--force`） | 可由 `code_version` 顯式控制 |
| 落盤 schema | 不變 | 需 sidecar（建議 `steps/_fingerprints.json`，不碰 artifact 本體，下游消費者無感） |
| 不適用處 | — | 來源步（輸入是網路，抓了才知道）、副作用步（deploy 讀全部歷史）仍需存在/sentinel 語義 |
| 外部狀態 | dedup 依賴向量庫歷史，兩者皆未納入 | 同左（只有同日記錄不參與比對，故同日重跑等冪） |
| 遷移 | — | 舊 artifact 無指紋：首見時「信任並補記」（=現行行為）或「一律重跑」（一天的 LLM 成本） |

取捨重點：
- **LLM 非確定性不構成障礙**：上游重跑產出新內容 → 下游指紋不符 → 重跑，正是要的語義；
  上游 LOAD → 輸入逐位元相同 → 下游 LOAD。
- **code_version 不該自動取 git SHA**：每個 commit 都會讓全部 artifact 失效，補跑變全量
  重跑（每次都付一整天的 LLM 成本，見 `--usage`）。採 Dagster 式手動宣告的步級 `code_version`，
  改 prompt 時 bump。
- **canonical JSON** 需 `sort_keys=True`；`fetched_at` 等時間戳在來源重跑時本就會變，無妨。
- 實作落點單一：`Step._run_inner` 已同時握有 `input` 與 artifact 路徑，指紋計算與比對
  可全部收在 Step 基底 + 新 codec 方法，各步零改動（`_load` 依 input 重濾的 dedup 因此變安全）。

## Recommendation

**採用輸入指紋，作為下一個獨立任務**（本次不實作）：sidecar 指紋帳本 + 步級 `code_version`，
來源步與 save/notify/deploy 維持現行語義；落地後可同時退場 Fix C 的 mtime 比對與本次的
`ran_steps` 傳播，`INVALIDATION_TIERS` 隨之刪除。若「SQLite 事件帳本」重構卡先行，指紋
宜作為其一張表而非另一個 JSON 檔。

## Consequences（現行修復）

- 保守連鎖：如 `--force tldr` 會連帶重新 deploy（站台含 TL;DR，語義正確但多一次 push）。
- 已知盲區（既存、本次未修）：`reconcile_completeness` 在 tldr 之後才重生 digest，tldr
  本次 run 仍基於舊 digest；ran_steps 是前向傳播，無法回頭。輸入指紋會在下一次 run 修正它。
- `--only rss` 時 dedup 不在 steps_to_run 而 LOAD，記憶體中的 rss 仍會被舊 kept_urls 濾掉；
  因下游也都 LOAD、不產出新 artifact，無實害。

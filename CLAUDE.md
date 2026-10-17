# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案目標

將 Claude Code Skills 改為可由本地 LLM server 執行的 multi-agent 系統。

## 執行方式

```bash
# 預設：本地 LLM server（http://localhost:1234，模型 qwen/qwen3.6-27b）
python3 main.py "/daily-brief"
python3 main.py "幫我摘要這些連結 https://example.com"

# 強制重新執行特定步驟（忽略當日 artifact）
python3 main.py "/daily-brief --force hatena"
python3 main.py "/daily-brief --force hatena hn"
python3 main.py "/daily-brief --force report"   # 重新生成報告（不重抓資料）
python3 main.py "/daily-brief --force notify"   # 重送 Telegram

# 只執行特定步驟
python3 main.py "/daily-brief --only hatena"
python3 main.py "/daily-brief --only report notify"

# 健康狀態查詢（唯讀 pull，不喚醒/載入模型、不跑 pipeline）
python3 main.py "/daily-brief --health"   # 印近 7 天各來源/遞送成功率表
python3 main.py "/daily-brief --usage"    # 印近 7 天 token 用量表 + 今日各步驟明細

# 可用 step 名稱：hatena / hn / reddit / security / rss / dedup / compress / enrich / digest / judge / report / save / notify

# 覆蓋本地 LLM 設定
export LOCAL_LLM_URL=http://localhost:1234
export LOCAL_LLM_MODEL=qwen/qwen3.6-27b

```

## 架構

```
main.py                          # 主入口（路由 + 執行）
AGENTS.md                        # 路由地圖

agents/
├── _template/                   # 新增 agent 的黃金範本
├── daily_brief/                 # 每日趨勢收集
│   ├── agent.py                 # 主流程（並行四來源）
│   ├── prompts.py               # 所有 LLM prompts
│   ├── config.py                # 來源設定、門檻、路徑
│   ├── supervisor.py            # LLM 監督器（fetch 品質控管）
│   ├── step_cache.py            # cache-or-force 門檻判定（decide → RUN/LOAD/SKIP）
│   ├── schemas.py               # step artifact 的 typed 唯讀 view（from_dict）
│   ├── completeness.py          # 完整性校正 seam：judge→不足則重生 digest→重評
│   ├── health.py                # 可觀測性：Health Record + 慢性故障跨天偵測（純函數）
│   ├── quality_signals.py       # 品質訊號：digest 來源占比 + judge 分數飽和（純函數）
│   ├── run_manifest.py          # 執行帳本：本次 run 的耗時/各步結果/觸發/git SHA（純函數 roll-up）
│   └── fetchers/                # 各來源 fetcher（agent 層）
└── url_digest/                  # URL 摘要
    ├── agent.py
    └── prompts.py

tools/
├── fetchers/                    # 純函數，無 LLM，各來源抓取
│   ├── _template.py
│   ├── hatena.py
│   ├── hn.py
│   ├── reddit.py
│   ├── security_blogs.py
│   └── browser.py              # playwright-cli 共用工具（hn 使用）
├── vector_store/                # 語義 dedup（embedding + cosine）
│   ├── client.py
│   ├── dedup.py
│   └── embedder.py
├── lms_lifecycle.py             # lms CLI 模型載入/卸載
├── history_schema.py            # judge/health 歷史檔的共享 typed view（agents ⇄ tools 共用）
├── site_builder/                # showcase 站建造器（build_full_site 為整站組裝入口）
└── notifiers/
    └── telegram.py              # Telegram 發送（HTML parse_mode）

n8n-workflow.json                # 排程 workflow（每日 01:00 執行 daily-brief）

config/
├── settings.py                  # LLM 後端設定（LocalLLMBackend）
└── logging_config.py

lint/
├── check_agent_interface.py     # 驗證 AGENT_NAME + run()
└── check_fetcher_interface.py   # 驗證 fetch()

archive/                         # 原始 Claude Code SKILL.md 保存
```

**Fetcher 共用工具**：playwright-cli 的 `_cli_bin`、`_run`、`_wait_for_session` 定義在 `tools/fetchers/browser.py`，新增 fetcher 直接 import，禁止複製。RSS 來源（hatena / security_blogs / rss）的 SSL context + feed 抓取共用 `tools/fetchers/rss_common.py`（`ssl_context()` 走 certifi、`fetch_feed(url)`），安全 XML 用 `defusedxml`；hatena 已退場舊的 `CERT_NONE` + `xml.etree`。parse 邏輯仍住各 fetcher（各家 feed 格式不同）。

## Daily Brief 故障排查

**失敗首先確認兩點**（按順序）：
```bash
curl -s http://localhost:1234/v1/models | python3 -c "import json,sys; print([m['id'] for m in json.load(sys.stdin)['data']])"  # LM Studio 是否有模型？
ls outputs/daily-brief/$(date +%Y-%m-%d)/             # 今日 output 是否存在？
```

**補跑今日**：確認 LM Studio 正常後 `python3 main.py "/daily-brief"`（Idempotent，已完成步驟會略過）。

## 排程（crontab）

兩段式排程：先預熱模型，再執行 pipeline。

```bash
# 第一條：load_model
(crontab -l 2>/dev/null; echo "45 1 * * * cd $HOME/Workspace/agent && /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 load_model.py >> /tmp/load_model.log 2>&1") | crontab -

# 第二條：daily-brief
(crontab -l 2>/dev/null; echo "0 2 * * * cd $HOME/Workspace/agent && /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 main.py \"/daily-brief\" >> /tmp/daily_brief.log 2>&1") | crontab -
```

確認：`crontab -l`

**load_model.py 故障處理**：
- LM Studio 未啟動 → 自動 `open -a "LM Studio"` + `lms server start`，最多等 3 分鐘
- 模型載入失敗（lms ps 缺少） → log + exit 1（**不發 Telegram**：main.py 02:00 會再試一次喚醒，真失敗時由 main.py 發唯一告警）
- 若是剛才才載入模型 → 等 600s 讓 API 穩定

**手動補跑**：`run_daily_brief.command`（雙點擊）或直接執行 `python3 main.py "/daily-brief"`（跳過 load_model.py，確保 LM Studio 已手動啟動）

## 核心設計原則

**Agent vs Tool**：Agent 有 LLM 推理與狀態；Tool 是純函數、確定性、無 LLM。  
`send_telegram` 已從 agent 降級為 `tools/notifiers/telegram.py`。

**Prompts 集中管理**：所有 LLM prompt 定義在 `agents/<name>/prompts.py`，`agent.py` 禁止直接寫 prompt 字串。

**步驟化執行（Idempotent Steps）**：每個步驟把結果存為 artifact（`outputs/daily-brief/{today}/steps/{name}.json`）。重複執行時自動略過已完成步驟；用 `--force` 強制重跑，用 `--only` 指定單步執行。「該跑/該載入/該略過」的門檻判定集中於 `step_cache.decide(in_steps, exists, forced)` 純函數（回傳 RUN/LOAD/SKIP），各 `_phase_*` 只定義三種結果各自的動作，不再各自重抄 gating 串接。判定（`step_cache.decide`）與其後的動作（artifact I/O、委派 supervisor、default）收進 `step.py` 的 `Step` 基底模板：公開介面只有 `run(ctx, input) -> StepOutcome`，每步差異住內部 seam（`_produce`/`_load`/`_guard`/`_default`）與注入的 `codecs.py` `ArtifactCodec`（Json/Text/Sentinel）。**producer 邏輯住各 step 檔內的 `_produce`（非 God object 注入）**：LLM producer 透過 `ctx.llm` / `ctx.judge_llm`（`_RunContext` 上的 LLM seam）呼叫，共用 `Step._complete(ctx, prompt)` 與 `Step._with_reflect(prompt, ctx_hint)`；`agent.py` 不再持有 `_run_*` producer。測試對 step 注入 `tests/fakes.py` 的 `FakeLLM`（走真 `_produce`），不再注入 fake producer callback。副作用 step（save/deploy）的實作（`run_save` / `push_site`）住各自 step 檔並以建構子預設值注入，測試可覆寫成 fake（合法 side-effect seam，避免碰真 vault/git）。新增 step：在 `agents/daily_brief/steps/` 加一檔、繼承 `Step`、`_produce` 內寫 producer 邏輯（讀 `ctx.llm`）、在 `run()` 顯式接線（不造依賴圖）。全部步驟為深 `Step`：5 個 Source（hatena/hn/reddit/security/rss，`steps/source.py` 的 `SourceStep`）+ dedup / compress / enrich / digest / judge / report / save / notify（`steps/*.py`）。`_fetch_sources` 維持 orchestrator（並行預抓 raw → 序列 `SourceStep.run` 評分 → ≥2 門檻）；judge 的 completeness 回饋（**完整性校正**，見 CONTEXT.md）收進 `completeness.reconcile_completeness(ctx, ...)` 單一 seam（judge→不足則 reflect 重生 digest→重評），`run()` 只單行呼叫、不再持有迴圈與門檻常數；Fix C 收進 `_compute_force_steps`（僅 run 開始時 mtime 比對一次）；**run 內上游失效**另由 `_RunContext.ran_steps` 補上——`Step` 每次 RAN 即記入，下游以 `step_cache.upstream_ran`（`INVALIDATION_TIERS` 鏡射接線順序、同層兄弟互不失效、save/notify 不參與）判定，任一上游本次 RUN 則 `decide` 必回 RUN 而非 LOAD（10-17 rss 下午才成功、dedup 卻 LOAD 舊 kept_urls 濾掉整個 rss）；長期改為輸入指紋快取鍵的評估見 `docs/adr/0005`。`run()` 是純地圖，無 `_phase_*`。`agent.py` 約 400 行。

**Typed 唯讀 view（schemas.py）**：step artifact 仍以原 JSON dict 穿流與序列化（on-disk schema 不變、下游消費者不受影響）；`schemas.py` 的 frozen dataclass（`QualityScore`/`Digest`/`Article`/`SourceCompress`）只罩在**記憶體讀取點**上，用 `from_dict` 把巢狀防呆與欄位對帳（如 judge 雙 `missed_urls`、digest 的 `_source` 內部鍵 vs `source` 顯示名）集中一處。新增讀取點優先用 view，不要散寫 `.get().get()`。

**可觀測性（health.py）**：pipeline 有韌性（≥2 來源門檻）但會默默降級。`health.py` 在每次執行末由 `_observe_and_escalate` 呼叫：檢視 artifact / sentinel / `alerts.json` 推導出一筆 **Health Record**（5 來源 + telegram/vault 遞送的 ok/失敗，失敗分類為 `ErrorClass` enum），append 到 `_health-history.json`（形狀鏡像 `_judge-history.json`）。再跨天 roll-up 偵測**慢性故障**（同 subject 7 天內失敗 ≥3 次）才主動 Telegram escalate，single transient flake 靜默；同一 episode 經 `_health-escalated.json` 去重只打擾一次。詞彙見 CONTEXT.md「系統訊號」、決策見 `docs/adr/0001`。**缺席日偵測**（`detect_absent_days`）補上 ADR 0001 承認的盲區——整天沒跑就沒有記錄、健康表仍顯示 100%（09-04~09-22 停更 18 天即如此）。缺席**不落盤**（避免走回 `001dd0f` 修掉的 unknown 記錄），改為由歷史推導的純函數，三個消費端共用：`observe_and_escalate` 回補 escalate（`_health-escalated.json` 以 `absent:` 前綴去重，同一段空窗只打擾一次）、`--health` 表尾點出空窗、站台 `compute_runs` 補 `absent` 列。可觀測性層與 Step 解耦（事後檢視痕跡，不汙染 step），且包在 try/except 內絕不反過來弄垮 pipeline。`--health` 是同一份歷史的唯讀 render（`render_health_table`），在 `main.py` 短路、不載入模型。錯誤分類來自對 alert 自由文字的字串比對（脆弱，僅驅動建議文字，不影響 chronic 判定）。**digest 來源占比 + judge 分數飽和**這兩個「品質面」觀測概念住 `quality_signals.py`（與健康記錄拆開，各自 cohesion 清楚；`health.py` re-export 供 `--health` 公開表面不變）。judge/health 兩份歷史檔的 on-disk 形狀由 `tools/history_schema.py` 的共享 typed view（`JudgeHistoryRecord` / `HealthHistoryRecord`）單一定義，寫入端（judge/health）與消費端（`site_builder.status`）共用，杜絕欄位名手抄漂移。

**執行紀錄（run_manifest.py）+ 站台「運行紀錄」頁**：`agents/daily_brief/run_manifest.py` 的 `RunManifest` 是「執行邊界」——記本次 run 的開始時間、每步耗時+結果、觸發源（`detect_trigger`：帶旗標=手動、否則排程）、git SHA。`Step.run` 是計時外殼（委派 `_run_inner` 跑真正 gating/IO，再 `record_step(name, status, duration)`；manifest 為選填 seam，None 時純計時無副作用）。`_persist_run` 落 `steps/_run.json` + append `_run-history.json`（同 health/usage 紀律，try/except 不反噬）。站台 `tools/site_builder/runs.py`（純函數 `compute_runs`）把 judge/health/usage/run 四份歷史依日期合併成 `RunRecord` 串，`render_run_history` 出 `run-history.html`（首頁 top nav 連入；一列一次 run：狀態+耗時+tokens+judge 分+8 subject 狀態矩陣）。**deploy 已納入 health subject**（`day_dir/deploy.done` sentinel / `alerts.get("deploy")`），故 gh-pages push 失敗會進 health 記錄、跨天慢性偵測、及運行紀錄矩陣的 D 格（此前 deploy token 過期致 gh-pages 靜默停更 18 天無從察覺）。

**觀測落盤時序（`_persist_observations`）**：health / usage / run 三份歷史的落盤收進單一 seam，`run()` **刻意呼叫兩次**——deploy 前一次、deploy 後一次。因為 `DeployStep` 讀這三份歷史檔全量建站：若只在 pipeline 最末落盤，站台永遠讀到「昨天為止」的資料，運行紀錄頁最新一列恆為 `unknown`、耗時與 tokens 恆為「—」，且是**每天都會發生的結構性落後**而非首次執行的一次性現象（2026-09-23 實測）。deploy 前落快照讓站台當天即有資料，deploy 後補記把 deploy 自身結果與耗時寫進同日記錄；三者皆同日冪等覆寫（`append_record` / `append_history` 以 date 去重），escalation 另有 `_health-escalated.json` 去重，故重複呼叫不重複打擾。**部分重跑（`--only`）為合併而非覆寫**：`run()` 每次建新的 `UsageMeter` / `RunManifest`，若整份覆寫，`--only judge` 這類重跑會把當日完整 run 的 16 步／總 tokens 抹成殘缺版。`run_manifest.merge_summary` / `usage_meter.merge_summary` 兩個純函數只 patch 本次實際跑過的步（fresh 的 `skipped` 項不覆蓋既有項），頂層耗時／觸發／SHA 沿用首次完整 run；`partial` 由 `run()` 以 `bool(only_steps)` 判定，`_persist_observations` 再以 `run_manifest.builds_on_prior_run`（任一步 `loaded` = 同日已有前一次 run）擴充——不帶旗標的重跑會全部 loaded、0 次 LLM 呼叫，舊判準只看 `--only` 時把 09-24／09-28／10-04／10-05／10-08／10-15 六天蓋成 0 tokens。`loaded` 與 `skipped` 同列為不覆蓋既有步的空狀態。health 天生免疫（`observe_run` 讀落盤痕跡而非記憶體）。**站台上當天 deploy 格靠「發佈自證」**——站台在 push 前建置，快照讀不到自身發佈結果（09-24 實測：線上 D 格恆為「未執行」、首頁 deploy 成功率少算當天）。但產物只有 push 成功才會上線，故 `build_full_site(OUTPUT_DIR, publishing_date=today)` 經 `loader.mark_self_published` 在記憶體中把當日 deploy 標 ok（運行紀錄矩陣、首頁成功率、`health-history.json` 端點三處一致）；push 失敗則該產物不上線、不會誤報。本機歷史檔不被改寫，仍由 deploy 後的 observe 如實補記。

**品質告警（judge → 每日摘要）**：judge 的 `quality_alert` 原本只看 `completeness < 3`，且寫進 `judge.json` 與 `_judge-history.json` 後**沒有任何消費者**（不發 TG、不上站台、不進 health；`reconcile_completeness` 也是直接讀分數而非旗標）——09-22／09-23 連兩天 `faithfulness=2`（digest 編造原文沒有的社群觀點）完全無聲通過。現改為：判準擴充成三軸各自門檻（`_DIMENSION_FLOOR=3.0`）+ overall 門檻（`_OVERALL_FLOOR=3.5`），任一觸發即示警、`quality_alert_reason` 列出所有觸發維度（`_quality_alert_reasons` 純函數）；輸出接進既有的 `alerts.send_summary`，與步驟失敗合成當日單封 Telegram（品質問題不是步驟失敗，故獨立成段、不套補跑指令；兩者皆無才靜默）。`run()` 經 `_quality_reason(steps_dir)` 從 `judge.json` 讀回理由，與 health 同為「事後檢視痕跡」。

**Token 用量追蹤（usage_meter.py）**：`tools/usage_meter.py` 的 `UsageMeter` 是「帳本邊界」——本地 LLM 無金錢成本，但要知道每天 token 吞吐量。單一 choke point `LocalLLMBackend.complete()` 在每次回應後 `record(model, usage)`（LM Studio 回應自帶 `usage`）；`current_step` 由 `Step.run` 在跑 producer 前設定，使每筆用量歸到當時步驟（enrich 的並行 thread 皆歸 `enrich`）。`UsageEvent` frozen、`totals`/`by_step`/`by_model` 為純函數 roll-up。`_persist_usage` 落盤（`steps/_usage.json` 當日明細 + append `_usage-history.json` 跨天，同日 idempotent 覆寫），與 health 同紀律包在 try/except 內絕不反噬 pipeline。`--usage` 是唯讀 render（`render_usage_table`），在 `main.py` 短路、不載入模型。**注意**：實測 qwen3.6 即使掛 `/no_think`，completion_tokens 仍含大量被 strip 的隱藏 reasoning（單次瑣碎呼叫可達 ~1900 tokens），故 completion 遠高於可見輸出——真實數字以 `--usage` 為準，勿用可見字元數推估。

**輸出目錄結構**：
```
outputs/daily-brief/{today}/
├── steps/
│   ├── hatena.json      # fetch raw + LLM scored（含 fetched_at）
│   ├── hn.json
│   ├── reddit.json
│   ├── security.json
│   ├── alerts.json      # 步驟失敗記錄（重試耗盡只寫此檔不即時推播；pipeline 結尾彙總成單封 Telegram，`_QUIET_STEPS` 如 deploy 不進摘要）
│   ├── compress.json    # 各來源語義壓縮（themes + *** articles + one_liner）
│   ├── enrich.json      # HN/Reddit 留言摘要（comment_summary 欄位）
│   ├── digest.json      # 跨來源深度摘要
│   ├── judge.json       # LLM-as-Judge 品質評分（relevance/completeness/faithfulness）
│   ├── _usage.json      # 當日 token 用量明細（totals + by_step + by_model）
│   └── _run.json        # 當日執行紀錄（耗時/各步結果/觸發/git SHA）
├── report.md            # 最終趨勢報告（純 markdown）
├── vault.done           # sentinel（存在 = 已存 Obsidian）
├── telegram.done        # sentinel（存在 = 已發送）
└── deploy.done          # sentinel（存在 = gh-pages push 成功；缺 = 未部署/失敗）

outputs/daily-brief/
├── _judge-history.json     # 逐日品質分歷史（relevance/completeness/faithfulness）
├── _health-history.json    # 逐日 Health Record（各來源/遞送 ok 或錯誤型別，含 deploy）
├── _health-escalated.json  # 慢性故障 escalation 去重狀態（subject → 最後 escalate 日）
├── _usage-history.json     # 逐日 token 用量（calls / prompt / completion / total + by_model）
└── _run-history.json       # 逐日執行紀錄（耗時/各步結果/觸發/git SHA；站台運行紀錄頁來源）
```

**LLM 後端**：固定使用 `LocalLLMBackend`（localhost:1234），啟動時自動探測可用性，未回應則發 Telegram 告警並中止。

## 新增 Agent / Fetcher

詳見 `AGENTS.md`。執行 lint 驗證：

```bash
python lint/check_agent_interface.py
python lint/check_fetcher_interface.py
```

## 執行環境注意

- 使用 `python3`，不是 `python`（`python` 指令不存在）
- `lms ls` 可查 LM Studio 已載入模型（`a4b` suffix = sparse MoE，active params 遠小於總參數）

## Judge 模型配置

- `config/settings.py` 的 `DEFAULT_JUDGE_LLM_MODEL` 控制預設 judge 模型（目前 `qwen3.6-35b-a3b`；原 `google/gemma-4-e4b` 因分數飽和失去鑑別力已汰換，見 issue #24）
- 可透過環境變數 `JUDGE_LLM_MODEL=<model>` 覆蓋
- 測試新 judge 模型：備份 judge.json → `python3 main.py "/daily-brief --force judge --only judge"` → 比較 → 還原

## 約束邊界

- **URL 是資料，不是 LLM 輸出**（縱深防禦，見 `agents/daily_brief/links.py`）：凡 URL 要進 LLM 輸出的步驟，一律給每篇文章唯一 `id`、LLM 只回 `id`（+ 摘要/one_liner），`title`/`url` 由 Python 依 id 從可信輸入重建，**絕不信任 LLM 回吐/複製網址**。已套用：compress（`_rebuild_articles`）、digest（`_summaries_by_id` + 依 id 重建）、compose_tg（LLM 寫 `href="@@id@@"` token → `links.substitute_href_tokens` 替換）。最後防線 `links.strip_invalid_anchors`：送 Telegram 前拆掉任何非 http(s) 的 `<a>` 外殼（保留錨文字、優雅降級），並記 `compose_tg` alert 供 health 跨天偵測。此設計源於 09-05 TG 無連結事件（compress LLM 對 HN 丟 title/url 又漏整篇 → digest 捏造「（原始 URL 未提供）」佔位字 → TG 死連結）。
- Reddit 禁用 WebFetch，必須 Bash curl 一次查詢後用 Python 解析（禁止兩次重複請求同一 URL）
- Reddit `stickied` 貼文必須過濾：`if p.get("stickied"): continue`
- X/Twitter 必須用 chrome-devtools-mcp
- `.md` 輸出必須用 Python `open()` 寫入
- Telegram 用 HTML parse_mode，≤ 4096 字元；**只允許** `<b>`、`<i>`、`<u>`、`<s>`、`<a>`、`<code>`、`<pre>`，`<br>`/`<p>`/`<div>` 會觸發 400 錯誤
- Telegram 雙重防護：prompt 明列允許 tag + `tools/notifiers/telegram.py` 的 `_sanitize_html()` 在發送前自動過濾
- daily-brief 發兩封訊息：msg1 主題分群列表（`• <b><a>` 格式）、msg2 深度摘要編號列表（`n. <b><a>` + 2–3 句說明），兩者均為 HTML 格式
- TG 訊息一律塞進**單封**（4096 上限），用**條目數上限**控制長度而非分段：送 LLM 前以 `_pick_top8_balanced` 跨來源均衡挑選，overview ≤ `_TG_OVERVIEW_MAX_ITEMS`(24)、digest ≤ `_TG_DIGEST_MAX_ITEMS`(7)；`telegram.py` 的 `_safe_truncate` 為最後防線（不切斷 tag、補閉合）
- compress 步驟：Python 層先過濾 `interest == "***"` 後才傳 LLM；來源無 *** 文章時直接略過 LLM 呼叫
- report 步驟：LLM 直接輸出純 markdown（不包 JSON）；`_run_report()` 自動剝除 LLM 可能加上的 markdown fence
- judge 步驟：只傳 `url + one_liner` 給 judge LLM（slim context），不傳完整文章內容

## playwright-cli 使用規範

- `open` 啟動長駐 daemon（不自動退出），必須用 `Popen` 放背景，再輪詢 `list` 等 session 就緒
- `--raw eval "<expr>"` 回傳 JSON-encoded 字串，需 `json.loads()` 解碼一層
- `eval` 在瀏覽器 context 執行（有 `document`）；`run-code` 在 Node.js context 執行（有 `page`，無 `document`）
- JS 重度渲染頁面需 `page_load_wait=6` 秒，否則 DOM 尚未就緒
- 複雜提取用 `eval "(function(){...})()"` IIFE，不支援 `const`/`let`，用 `var`
- security 來源（aikido.dev、wiz.io）已改走 RSS feed，不再用 playwright（見 `docs/adr/0003`）

## LM Studio API

- Endpoint：`POST /v1/chat/completions`（非 `/api/v1/chat`）
- Body：`{"model": "...", "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]}`
- Response：`data["choices"][0]["message"]["content"]`

## Fetcher 已知 Gotcha

- Hatena `ai.rss`：HTTP 404，已移除；只用 `it.rss`
- HN HTML 留言數格式：`88&nbsp;comments`（含 `&nbsp;`，非空格）
- LLM context 262144 tokens，`max_chars` 可設較大值：HN=36000（全 30 篇）

## 核心工程理念

### 1. 倉庫即記錄系統
所有架構決策寫進 CLAUDE.md；「為什麼這樣設計」必須版本化。Slack 討論、口頭共識對 AI 不可見。

### 2. 地圖而非手冊
根層 CLAUDE.md 只做導航；每個子目錄 CLAUDE.md ≤ 30 行；漸進式披露。

### 3. 機械化執行
介面規範透過 `lint/` 強制執行；lint 錯誤訊息內嵌修復指令，AI 可自我糾正。

### 4. 智能體可讀性
選無聊技術（httpx、asyncio、BeautifulSoup）；每個 tool/agent 可獨立執行與測試。

### 5. 吞吐量改變合併理念
`outputs/` 存放中間產物；pipeline 允許從任意步驟重新執行；單一 fetcher 失敗不 block 整條流程。

### 6. 熵管理
新增 agent/fetcher 複製 `_template`，不參考其他現有實作；壞模式出現一次立即修正。

## 設定與外部依賴

所有機器專屬值走專案根 `.env`（範本見 `.env.example`），原始碼不寫死路徑/憑證。
`config/settings.py` 在 import 時即 `load_project_env()`，確保 module 層的 env 解析拿得到值
（`os.environ.setdefault`，不覆寫既有環境變數）。

| 設定 | env var | 必填？ | 未設定時 |
|---|---|---|---|
| 本地 LLM | `LOCAL_LLM_URL` / `LOCAL_LLM_MODEL` | 否（有預設） | 用 localhost:1234 預設 |
| Telegram 推播 | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | **選填** | 靜默略過推播與告警 |
| Obsidian 存檔 | `VAULT_ROOT` | **選填** | SaveStep 略過（不 touch vault.done、不入 health 記錄） |
| Judge 模型 | `JUDGE_LLM_MODEL` / `JUDGE_LLM_URL` | 否 | 與主 LLM 相同 |
| Deploy（gh-pages）| `DEPLOY_GITHUB_TOKEN` | **選填** | push 走 `origin`（互動式 session 靠既有 credential helper；cron 拿不到 osxkeychain 會失敗） |

- **telegram.py 自包**：直接打 Telegram Bot API，憑證讀專案 `.env`，**不再依賴 vault 的 `Scripts/`**。
- **save 直接寫檔**：`_run_save` 以 Python `open()` 寫入 `VAULT_ROOT/01 Projects/daily-brief/`；
  `VAULT_ROOT` 設定但路徑不存在（誤填 / iCloud 未掛載）→ 警告並略過，不建假目錄樹。
- 唯一的真實外部依賴是 vault 目錄本身（選填）；偏好設定（`interests.txt`、Reddit subreddits）
  為 in-repo config 檔，直接編輯即可。

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues (`zheng0258/local-agent`), via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles; label strings equal their role names (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

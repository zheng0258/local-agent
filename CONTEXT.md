# Daily Brief

每天一次，從多個技術來源**策展**出「當日值得關注的趨勢」這個成果概念，以及產出它的 multi-agent pipeline。

## Language

**Daily Brief**:
每日策展出的「當日值得關注的技術趨勢」這個成果概念本身，與載體無關。它有兩種呈現形式：完整的 Report 與精簡的 Telegram 推播。
_Avoid_: report（那只是其中一種載體）、digest（指更窄的東西）

**Report**:
Daily Brief 的完整呈現載體——一份存檔用的 markdown 文件（`report.md`），同步進 Obsidian vault。
_Avoid_: brief、文章、summary

**Telegram 推播**:
Daily Brief 的精簡即時呈現載體——兩封 Telegram 訊息（主題分群列表 + 深度摘要）。
_Avoid_: notification、alert（alert 是另一個概念）

## 來源

**Source（來源）**:
Daily Brief 策展的一個上游平台（Hatena / HN / Reddit / 資安部落格 / RSS）。每個 Source 有自己的人氣值定義與進入 Digest 的人氣門檻。Reddit 的多個 subreddit 同屬一個 Source。
_Avoid_: feed、channel、fetcher（fetcher 是抓取它的程式，屬實作）、平台

## 評級與指標

> 「score / 分數」是被多載的口語詞，文件與 prompt 中禁止單獨使用，必須指明是下列哪一個。

**人氣值（Popularity）**:
來源平台原生的熱度數字（HN score、Reddit upvotes、Hatena bookmarks）。由外部平台給定，客觀。策展時作為「夠不夠紅」的門檻。
_Avoid_: score、熱度、讚數

**興趣度（Interest）**:
系統用 LLM 對單篇文章「對我的相關性」評定的三級評級（`***` / `**` / `*`）。策展的核心篩選依據，決定「主題對不對」。
_Avoid_: score、評分、rating、相關性分數

**興趣標準（Interest Criteria）**:
定義「什麼算 `***`」的明文價值觀（存於 `interests.txt`，可直接改檔調整）。是整個策展「我在乎什麼」的來源，興趣度評級依此判定。
_Avoid_: 規則、prompt、設定

**品質分（Quality Score）**:
LLM-as-Judge 對最終 Brief 產物「做得好不好」的自評，分 relevance / completeness / faithfulness 三軸。評的是系統自己的輸出，與文章本身無關。
_Avoid_: score、judge 分數、評價

## 摘要層級

兩種粒度不同的摘要，不可混用。

**One-liner**:
單篇文章 20 字內的標題級摘要，供快速掃讀。
_Avoid_: summary、摘要（太籠統）、digest

**Digest（深度摘要）**:
針對少數最值得關注的項目，跨來源（含社群觀點）綜合而成的多句段落級說明，供決定「要不要點進去讀」。
_Avoid_: summary、one-liner、url_digest（那是另一個 agent，服務隨選 URL 摘要，不屬本 context）

## 分組

**Category（類別）**:
預先定義好的固定分類桶（AI / 資安 / 核心技術…），每篇文章歸進其中一個，跨日穩定。是「事先畫好的格子」。
_Avoid_: theme、tag、type

**Theme（主題）**:
由當日抓到的 `***` 文章動態浮現的語義群，由壓縮產生，每天不同。是「今天大家在談什麼」的切片，也是 Telegram 推播主清單的組織軸。是「當天長出來的群」。
_Avoid_: category、topic、群組

## 內容型別

**社群觀點（Community Perspective）**:
針對某文章，從來源平台留言區萃取的群眾反應摘要（質疑 / 補充 / 反例 / 實戰經驗），有別於文章本身的作者主張。只有具留言生態的來源（HN、Reddit）才有，併入 Digest 呈現。
_Avoid_: 留言摘要、comments、評論

## 策展政策

**新鮮度（Freshness）**:
近 7 天內已報導過（URL 重複或語意相似）的文章不再出現，避免洗版。關注的是「這則是不是已經給過了」，與其底層去重機制無關。
_Avoid_: dedup、去重、重複（那些指機制）

## 系統訊號

**Alert（警報）**:
條件觸發的例外訊號，只關乎系統健康與產出品質，**不關乎內容主題**。三種子型別：步驟失敗（某 step 重試耗盡）、啟動故障（LLM 無回應 / 模型載入失敗）、品質警報（judge 品質分過低）。與例行的 Daily Brief 遞送是不同概念，即使共用 Telegram。**Alert 是「單次事件」**，發生當下即發送，彼此獨立、不跨天聚合。
_Avoid_: 通知、notification、異常訊號（會被誤解為內容異常）、推播

**Health Record（健康記錄）**:
單次執行後，對每個 Source 與每個遞送載體（Telegram 推播 / vault 存檔）逐一判定的「成功或失敗」結果，失敗者另記其錯誤型別（network / upstream_http / empty_llm / parse / other）。逐日累積成歷史（`_health-history.json`），是回答「系統近來健不健康」的事實來源。對應「品質」面的是 Quality Score 歷史。
_Avoid_: log、metrics、alert（那是事件，這是狀態快照）

**慢性故障（Chronic Failure）**:
同一 subject（某 Source 或某遞送）在滑動視窗（預設 7 天）內失敗達門檻次數（預設 3 次）的**跨天樣態**。相對於單次 transient flake（雜訊，靜默容忍），慢性故障是真正需要人介入的訊號，會主動 escalate。是「Alert 的跨天 roll-up 結論」，而非又一個 Alert 子型別。
_Avoid_: alert（Alert 是單次事件）、transient（那是相反概念：偶發、可自癒）

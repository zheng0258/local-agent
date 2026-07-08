# Security 來源改走 RSS feed，退場 playwright DOM 抓取

## Context

security 來源（aikido.dev、wiz.io）是全 pipeline 維護成本最高的 fetcher：
playwright-cli 長駐 daemon、JS 重度渲染需 6 秒等待、DOM selector
（`[fs-list-field="title"]`、`h2`/`h3`）對兩站頁面結構寫死，改版即壞。
但近 30 天只貢獻約 3% 的最終 digest 條目 — ROI 倒掛最嚴重的一塊。

## Feed 調查結論（2026-07-08，實際 curl 驗證）

| 站點 | Feed URL | 狀態 | 格式 | 覆蓋範圍 |
|---|---|---|---|---|
| aikido.dev | `https://www.aikido.dev/blog/rss.xml` | 200 `application/rss+xml` | RSS 2.0（Webflow 產生） | 全 blog，100 items，含 title/link/description/pubDate |
| wiz.io | `https://www.wiz.io/feed/rss.xml` | 200 `application/xml` | RSS 2.0（jpmonette/feed 產生，title/description 為 CDATA） | 全 blog，600+ items，含 title/link/description/pubDate/author |

其他常見路徑：aikido `/rss.xml`、`/feed` 皆 404；wiz `/rss.xml` 404、
`/blog/rss.xml` 301 轉址至 `/feed/rss.xml`。

## Decision

兩站皆有覆蓋全 blog 的標準 RSS 2.0 feed，`tools/fetchers/security_blogs.py`
全面改為 feed 解析（urllib + defusedxml，比照 hatena 的無聊技術路線），
移除對 `tools/fetchers/browser.py` 的依賴。fetcher 介面（`fetch()`）與
artifact schema（`[{"title", "url", "source", "description"}]`，錯誤時
`[{"source", "error"}]`）不變，下游 step 無感。

wiz feed 有 600+ items，維持原行為每來源截前 10 篇；description 截 200 字元。

## Considered Options

- **維持 playwright DOM 抓取** — 否決：selector 寫死、6 秒渲染等待、長駐 daemon，
  維護成本與貢獻度不成比例。
- **混合（部分站 feed、部分站 playwright）** — 不需要：兩站都有可用 feed。
- **併入 rss step 的 `rss_sources.yaml`** — 否決：security 來源有獨立的
  LLM 評分 prompt 與 `***` 門檻（`min_interest`），且 step artifact
  （`security.json`）為既有下游輸入；併入 rss 會改變 artifact schema。

## Consequences

- `tools/fetchers/browser.py` 仍保留，唯一消費者剩 `hn.py`。
- feed 依 pubDate 排序取前 10 篇 = 「最新」而非 playwright 版的「頁面呈現順序」
  （含編輯精選）；對每日趨勢收集而言最新優先是正確語義。
- 若兩站日後撤掉 feed（HTTP 404/HTML），fetcher 回傳 error dict，
  health.py 的慢性故障偵測（ADR 0001）會在 7 天內 escalate。

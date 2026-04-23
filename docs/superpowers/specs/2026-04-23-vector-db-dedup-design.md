# Vector DB 去重設計：daily-brief pipeline

**日期**：2026-04-23  
**狀態**：已確認，待實作

---

## 問題陳述

daily-brief pipeline 目前沒有跨天記憶，同一篇文章或同一則新聞的多篇報導會在不同天重複出現，浪費 LLM token（compress/digest 步驟）並降低報告品質。

---

## 目標

| 優先 | 功能 | 說明 |
|------|------|------|
| P0 | URL 去重 | 同一 URL 在 7 天內只處理一次 |
| P0 | 語意去重 | 不同 URL 但報導同一事件（相似度 > 0.80）在 7 天內過濾 |
| P1 | 趨勢偵測 | 跨天持續出現的話題自動標記（擴充點） |
| P2 | 個人化學習 | 根據 judge 評分微調興趣偵測（擴充點） |
| P2 | 語意搜尋 | 查詢歷史文章（擴充點） |

---

## 架構

### Pipeline 變動

```
fetch（hatena / hn / reddit / security）  ← 不變
    ↓  source_data（含全部 articles）
[NEW] dedup                               ← 新增步驟
    ↓  source_data（已過濾重複文章）
compress（LLM）                           ← 不變，但 token 消耗下降
    ↓
digest / judge / report / save / notify   ← 不變
```

`dedup` 在 compress 之前執行，被過濾的文章不觸發任何 LLM 呼叫。

### 新增檔案

```
tools/
└── vector_store/
    ├── __init__.py
    ├── embedder.py    # Qwen3Embedder：mlx_lm 直接推理
    ├── client.py      # ChromaDB persistent client + TTL 清理
    └── dedup.py       # URL 去重 + 語意去重邏輯

outputs/daily-brief/
└── .vectordb/         # ChromaDB 持久化資料庫（加入 .gitignore）
```

---

## 技術選型

| 元件 | 選擇 | 理由 |
|------|------|------|
| Vector store | ChromaDB persistent | 純本地檔案、HNSW index、Python API 簡潔 |
| Embedding model | `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` | Apple Silicon 原生、多語言（中日英）、351MB |
| Embedding 呼叫方式 | `mlx_lm` 直接推理 | LM Studio `/v1/embeddings` 不支援 MLX 格式模型 |
| Similarity | Cosine similarity | 實測：同主題 0.81–0.86，不同主題 0.45 |

**LM Studio 限制說明**：`/v1/embeddings` endpoint 對 MLX 格式模型回傳 "No models loaded"，確認為平台限制。改用 `mlx_lm.load()` 直接在 Python 內推理，模型首次使用後快取於記憶體。

---

## 資料模型

### ChromaDB Collection：`daily_brief_articles`

```python
collection.upsert(
    ids=["https://example.com/article"],   # URL 作為唯一 ID
    documents=["文章標題"],                  # 用於 embedding 計算
    metadatas=[{
        "date": "2026-04-23",              # 用於 7 天 TTL 過濾
        "source": "hatena",               # 來源
        "interest": "***",                # 興趣度
    }]
)
```

### 7 天 TTL

每次 pipeline 啟動時執行一次清理，刪除 `date < today - 7` 的記錄，避免 collection 無限增長。

---

## 去重邏輯

每篇文章依序執行：

```
1. URL 精確比對
   → collection.get(ids=[url]) 有結果且 date ≥ today-7 → 過濾（reason: url_seen）

2. 語意相似比對（URL 未命中才執行）
   → embed(title) → query top-3 nearest（where date ≥ today-7）
   → similarity > 0.80 → 過濾（reason: semantic_dup）

3. 兩者都未命中 → 保留，upsert 進 collection
```

### 效能估算

- URL 比對：O(1)
- 語意比對：僅對「URL 未見過」的文章執行
- Embedding 速度：~5–10ms / 篇（Apple Silicon MPS），42 篇 < 1 秒

---

## Artifact：`steps/dedup.json`

```json
{
  "total": 42,
  "kept": 28,
  "filtered_url": 8,
  "filtered_semantic": 6,
  "filtered_items": [
    {
      "url": "https://example.com/article",
      "title": "文章標題",
      "reason": "url_seen",
      "original_date": "2026-04-20"
    }
  ]
}
```

---

## 設定（`agents/daily_brief/config.py` 新增）

```python
DEDUP_SIMILARITY_THRESHOLD = 0.80   # 可調整
DEDUP_WINDOW_DAYS = 7
VECTOR_DB_PATH = OUTPUT_DIR / ".vectordb"
```

---

## Embedder 實作

```python
# tools/vector_store/embedder.py
import mlx.core as mx
import mlx_lm

class Qwen3Embedder:
    MODEL_ID = "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ"

    def __init__(self):
        self._model = None
        self._tokenizer = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            self._model, self._tokenizer = mlx_lm.load(self.MODEL_ID)
        results = []
        for text in texts:
            tokens = mx.array(self._tokenizer.encode(text)).reshape(1, -1)
            hidden = self._model.model(tokens)   # (1, seq_len, 1024)
            vec = hidden[0, -1, :]               # last token hidden state
            norm = mx.sqrt((vec * vec).sum()) + 1e-8
            vec = vec / norm
            mx.eval(vec)                         # MLX lazy → eager materialization
            results.append(vec.tolist())
        return results
```

---

## 未來擴充點（不在本次實作範圍）

### B. 趨勢偵測

`dedup.json` 的 `filtered_semantic` 已記錄「與過去哪篇文章相似」。統計同一語意群跨越的天數，查詢 ChromaDB 找出 `date` 跨 3 天以上的群組，即為「本週持續熱點」，可加入 report 的 `## 今日總結` section。

### C. 個人化興趣學習

在 ChromaDB metadata 加 `judge_score` 欄位（judge 步驟完成後回寫）。compress/digest prompt 注入「過去相似且高分文章的 title」作為興趣參考，讓 LLM 對同類主題給出更一致的高評分。

### D. 語意搜尋

```bash
python3 main.py "/search 供應鏈攻擊 npm"
```

對 ChromaDB 執行 `collection.query(query_texts=[keyword], n_results=10)`，回傳歷史相關文章列表。vector store 建好後約 10 行實作。

---

## 不在設計範圍內

- 跨天興趣度重新評分
- Embedding model 自動更新
- 多使用者支援

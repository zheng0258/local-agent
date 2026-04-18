"""
Fetcher 黃金範本。

每個 fetcher 必須實作：
  fetch() -> list[dict] | str

fetch() 為純函數（無副作用、無 LLM 呼叫），
回傳原始資料供 agent 送 LLM 評分。
"""

from __future__ import annotations


def fetch() -> list[dict]:
    """
    抓取來源資料。

    回傳格式（list of dict）：
    [
        {
            "title": "文章標題",
            "url": "https://...",
            "score": 0,          # 書籤數 / 分數 / upvotes
            # 來源特有欄位...
        }
    ]
    """
    raise NotImplementedError

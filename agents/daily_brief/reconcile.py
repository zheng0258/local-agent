"""reconcile — pipeline 各階段之間以 URL 對齊的 join / filter（fetch ↔ score ↔ digest）。

這些 helper 全講同一套 source_data / digests + URL 詞彙，並倚賴 schemas.py 的 typed view。
集中一處，不再散落於 agent.py 模組層。純函數、不 mutate 輸入。
"""

from __future__ import annotations

from .config import FETCH_STEPS
from .schemas import Digest, SourceCompress

_ORIGINAL_DESC_MAX_CHARS = 200


def filter_top_articles(source_data: dict) -> dict:
    """只保留 *** 文章傳入分析管線；** 文章已存於 artifact，不影響記錄。"""
    result: dict = {}
    for src, data in source_data.items():
        articles = data.get("articles", [])
        top = [
            a for a in articles if isinstance(a, dict) and a.get("interest") == "***"
        ]
        if top:
            result[src] = {**data, "articles": top}
    return result


def filter_source_data_by_urls(source_data: dict, kept_urls: set[str]) -> dict:
    """以 kept_urls 過濾各來源文章（dedup LOAD 時用 kept_urls 重濾上游）。"""
    filtered: dict = {}
    for source_name, content in source_data.items():
        articles = content.get("articles", [])
        filtered[source_name] = {
            **content,
            "articles": [
                a for a in articles if isinstance(a, dict) and a.get("url") in kept_urls
            ],
        }
    return filtered


def attach_original_fields(articles: list[dict], raw: list) -> list[dict]:
    """以 URL 對齊，把 fetch 階段未經 LLM 改寫的原始 title/描述附回評分後條目。

    LLM 評分會把 title 翻成繁中；faithfulness 去循環化需要原始素材落盤。
    回傳新 list（不 mutate 輸入）；既有欄位不動（on-disk schema 只加不改）。
    HN raw 的 `url` 是原文連結、`hn_url` 才是 scored artifact 用的討論串 URL，兩者皆入索引。
    """
    originals: dict[str, dict] = {}
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or item.get("summary") or "").strip()
        fields = {"original_title": str(item.get("title", ""))}
        if description:
            fields["original_description"] = description[:_ORIGINAL_DESC_MAX_CHARS]
        for url_key in ("url", "hn_url"):
            url = item.get(url_key)
            if url:
                originals[url] = fields
    return [
        {**article, **originals[article.get("url", "")]}
        if article.get("url", "") in originals
        else dict(article)
        for article in articles
    ]


def original_pairs_for_digests(digests: list[dict], source_data: dict) -> list[dict]:
    """faithfulness 去循環化：以 URL 對齊，為每條 digest 配上 fetch 階段原始素材。

    對照基準是 source artifact 的 original_title（未經 LLM 改寫）；
    舊 artifact 無此欄位時退回 artifact 的 title（graceful degradation）。
    維持 slim context：只帶 title/描述，不帶全文。
    """
    articles_by_url = {
        article.url: article
        for src in FETCH_STEPS
        for article in SourceCompress.from_dict(source_data.get(src, {})).articles
        if article.url
    }
    pairs: list[dict] = []
    for digest in (Digest.from_dict(d) for d in digests):
        article = articles_by_url.get(digest.url)
        pair = {
            "url": digest.url,
            "original_title": (
                (article.original_title or article.title) if article else ""
            ),
        }
        if article and article.original_description:
            pair["original_description"] = article.original_description
        pairs.append(pair)
    return pairs

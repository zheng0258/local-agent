"""URL and semantic deduplication for fetched article data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .embedder import Qwen3Embedder


@dataclass
class DedupResult:
    total: int
    kept: int
    filtered_url: int
    filtered_semantic: int
    kept_urls: list[str]
    filtered_items: list[dict] = field(default_factory=list)


def dedup_source_data(
    source_data: dict,
    collection,
    embedder: Qwen3Embedder,
    today: str,
    window_days: int = 7,
    threshold: float = 0.80,
) -> tuple[dict, DedupResult]:
    today_ordinal = date.fromisoformat(today).toordinal()
    cutoff_day_index = today_ordinal - window_days
    # 只比對「過去 N 天」，排除今天本身，避免 --force 重跑時自我過濾
    history_filter = {
        "$and": [
            {"day_index": {"$gte": cutoff_day_index}},
            {"day_index": {"$lt": today_ordinal}},
        ]
    }
    kept_urls: list[str] = []
    filtered_items: list[dict] = []
    filtered_url = 0
    filtered_semantic = 0
    total = 0

    new_ids: list[str] = []
    new_docs: list[str] = []
    new_embeddings: list[list[float]] = []
    new_metas: list[dict] = []

    for source_name, source_content in source_data.items():
        articles = source_content.get("articles", [])
        for article in _flatten_articles(articles):
            url = article.get("url", "")
            title = article.get("title", "")
            if not url:
                continue
            total += 1

            existing = collection.get(ids=[url], where=history_filter)
            if existing["ids"]:
                filtered_url += 1
                filtered_items.append(
                    {
                        "url": url,
                        "title": title,
                        "reason": "url_seen",
                        "original_date": existing["metadatas"][0].get("date", ""),
                    }
                )
                continue

            embedding = embedder.embed([title])[0]
            try:
                query_result = collection.query(
                    query_embeddings=[embedding],
                    n_results=3,
                    where=history_filter,
                    include=["distances", "metadatas"],
                )
                distances = query_result.get("distances", [[]])[0]
                if distances and (1.0 - distances[0]) >= threshold:
                    nearest_meta = query_result["metadatas"][0][0]
                    filtered_semantic += 1
                    filtered_items.append(
                        {
                            "url": url,
                            "title": title,
                            "reason": "semantic_dup",
                            "original_date": nearest_meta.get("date", ""),
                        }
                    )
                    continue
            except Exception:
                pass

            kept_urls.append(url)
            new_ids.append(url)
            new_docs.append(title)
            new_embeddings.append(embedding)
            new_metas.append(
                {
                    "date": today,
                    "day_index": date.fromisoformat(today).toordinal(),
                    "source": source_name,
                    "interest": article.get("interest", ""),
                }
            )

    if new_ids:
        collection.upsert(
            ids=new_ids,
            documents=new_docs,
            embeddings=new_embeddings,
            metadatas=new_metas,
        )

    kept_set = set(kept_urls)
    return _filter_source_data_by_urls(source_data, kept_set), DedupResult(
        total=total,
        kept=len(kept_urls),
        filtered_url=filtered_url,
        filtered_semantic=filtered_semantic,
        kept_urls=kept_urls,
        filtered_items=filtered_items,
    )


def _flatten_articles(articles: list | dict) -> list[dict]:
    if isinstance(articles, list):
        return articles
    if isinstance(articles, dict):
        return [a for cat in articles.values() if isinstance(cat, list) for a in cat]
    return []


def _filter_source_data_by_urls(source_data: dict, kept_urls: set[str]) -> dict:
    filtered: dict = {}
    for source_name, content in source_data.items():
        articles = content.get("articles", [])
        if isinstance(articles, list):
            filtered[source_name] = {
                **content,
                "articles": [a for a in articles if a.get("url") in kept_urls],
            }
        elif isinstance(articles, dict):
            filtered[source_name] = {
                **content,
                "articles": {
                    cat: [a for a in cat_arts if a.get("url") in kept_urls]
                    for cat, cat_arts in articles.items()
                    if isinstance(cat_arts, list)
                },
            }
        else:
            filtered[source_name] = content
    return filtered

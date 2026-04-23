"""ChromaDB persistent collection and retention helpers."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import chromadb

COLLECTION_NAME = "daily_brief_articles"


def get_collection(db_path: Path):
    client = chromadb.PersistentClient(path=str(db_path))
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def cleanup_old_records(collection, window_days: int) -> int:
    cutoff_day_index = (date.today() - timedelta(days=window_days)).toordinal()
    results = collection.get(where={"day_index": {"$lt": cutoff_day_index}})
    if not results["ids"]:
        return 0
    collection.delete(ids=results["ids"])
    return len(results["ids"])

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
def test_get_collection_returns_collection():
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    with patch("tools.vector_store.client.chromadb.PersistentClient", return_value=mock_client):
        from tools.vector_store.client import get_collection

        result = get_collection(Path("/tmp/testdb"))

    mock_client.get_or_create_collection.assert_called_once_with(
        name="daily_brief_articles",
        metadata={"hnsw:space": "cosine"},
    )
    assert result is mock_collection


@pytest.mark.unit
def test_cleanup_deletes_records_older_than_window():
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": ["url1", "url2", "url3"]}

    from tools.vector_store.client import cleanup_old_records

    deleted = cleanup_old_records(mock_collection, window_days=7)

    assert deleted == 3
    mock_collection.delete.assert_called_once_with(ids=["url1", "url2", "url3"])


@pytest.mark.unit
def test_cleanup_no_old_records_skips_delete():
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": []}

    from tools.vector_store.client import cleanup_old_records

    deleted = cleanup_old_records(mock_collection, window_days=7)

    assert deleted == 0
    mock_collection.delete.assert_not_called()


@pytest.mark.unit
def test_cleanup_uses_correct_cutoff_date():
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": []}
    expected_cutoff = (date.today() - timedelta(days=7)).toordinal()

    from tools.vector_store.client import cleanup_old_records

    cleanup_old_records(mock_collection, window_days=7)

    call_kwargs = mock_collection.get.call_args
    assert call_kwargs[1]["where"] == {"day_index": {"$lt": expected_cutoff}}

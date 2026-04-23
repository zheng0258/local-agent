import math
from unittest.mock import MagicMock, patch

import mlx.core as mx
import pytest


def _make_mock_mlx(hidden_dim: int = 1024, seq_len: int = 3):
    mock_model = MagicMock()
    mock_tokenizer = MagicMock()
    mock_model.model.return_value = mx.zeros((1, seq_len, hidden_dim))
    mock_tokenizer.encode.return_value = list(range(seq_len))
    return mock_model, mock_tokenizer


@pytest.mark.unit
def test_embed_returns_vector_of_correct_dim():
    mock_model, mock_tokenizer = _make_mock_mlx()
    with patch("tools.vector_store.embedder.mlx_lm.load", return_value=(mock_model, mock_tokenizer)):
        from tools.vector_store.embedder import Qwen3Embedder

        embedder = Qwen3Embedder()
        result = embedder.embed(["Claude Code Max 付費限制"])
    assert len(result) == 1
    assert len(result[0]) == 1024


@pytest.mark.unit
def test_embed_multiple_texts_returns_multiple_vectors():
    mock_model, mock_tokenizer = _make_mock_mlx()
    with patch("tools.vector_store.embedder.mlx_lm.load", return_value=(mock_model, mock_tokenizer)):
        from tools.vector_store.embedder import Qwen3Embedder

        embedder = Qwen3Embedder()
        result = embedder.embed(["text 1", "text 2", "text 3"])
    assert len(result) == 3
    assert all(len(v) == 1024 for v in result)


@pytest.mark.unit
def test_model_loaded_only_once():
    mock_model, mock_tokenizer = _make_mock_mlx()
    with patch(
        "tools.vector_store.embedder.mlx_lm.load",
        return_value=(mock_model, mock_tokenizer),
    ) as mock_load:
        from tools.vector_store.embedder import Qwen3Embedder

        embedder = Qwen3Embedder()
        embedder.embed(["first call"])
        embedder.embed(["second call"])
    mock_load.assert_called_once()


@pytest.mark.unit
def test_embed_returns_normalized_vector():
    mock_model, mock_tokenizer = _make_mock_mlx()
    mock_model.model.return_value = mx.ones((1, 3, 1024))
    with patch("tools.vector_store.embedder.mlx_lm.load", return_value=(mock_model, mock_tokenizer)):
        from tools.vector_store.embedder import Qwen3Embedder

        embedder = Qwen3Embedder()
        result = embedder.embed(["test"])
    norm = math.sqrt(sum(v * v for v in result[0]))
    assert abs(norm - 1.0) < 1e-4

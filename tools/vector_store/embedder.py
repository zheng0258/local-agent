"""Qwen3 embedder wrapper using local mlx_lm inference."""

from __future__ import annotations

import mlx.core as mx
import mlx_lm


class Qwen3Embedder:
    MODEL_ID = "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ"

    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None

    def _ensure_loaded(self) -> None:
        if self._model is None:
            self._model, self._tokenizer = mlx_lm.load(self.MODEL_ID)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._ensure_loaded()
        vectors: list[list[float]] = []
        for text in texts:
            tokens = mx.array(self._tokenizer.encode(text)).reshape(1, -1)
            hidden = self._model.model(tokens)
            vec = hidden[0, -1, :]
            norm = mx.sqrt((vec * vec).sum()) + 1e-8
            vec = vec / norm
            vectors.append(vec.tolist())
        return vectors

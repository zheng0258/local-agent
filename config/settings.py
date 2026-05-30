"""
LLM 後端設定。

預設：LocalLLMBackend（http://localhost:1234）

環境變數：
    LOCAL_LLM_URL    本地 LLM server URL（預設 http://localhost:1234）
    LOCAL_LLM_MODEL  本地模型名稱（預設 qwen3.5-27b-claude-4.6-opus-distilled-mlx）
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


VAULT_ROOT = Path(
    os.environ.get(
        "VAULT_ROOT",
        "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Second-Brain",
    )
)

DEFAULT_LOCAL_LLM_URL = "http://localhost:1234"
DEFAULT_LOCAL_LLM_MODEL = "qwen3.6-35b-a3b"
DEFAULT_JUDGE_LLM_MODEL = "google/gemma-4-e4b"


class LLMBackend(Protocol):
    def complete(self, prompt: str, system: str = "") -> str: ...


class LocalLLMBackend:
    """
    本地 LLM server 後端（LM Studio / OpenAI-compatible API）。
    Endpoint：POST /v1/chat/completions
    """

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def complete(self, prompt: str, system: str = "") -> str:
        import json
        import urllib.request

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps({"model": self.model, "messages": messages}).encode()

        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3600) as resp:
            data = json.loads(resp.read().decode())

        return data["choices"][0]["message"]["content"]


def get_llm() -> LLMBackend:
    local_url = os.environ.get("LOCAL_LLM_URL", DEFAULT_LOCAL_LLM_URL)
    local_model = os.environ.get("LOCAL_LLM_MODEL", DEFAULT_LOCAL_LLM_MODEL)
    return LocalLLMBackend(base_url=local_url, model=local_model)


def check_local_llm(base_url: str = DEFAULT_LOCAL_LLM_URL, timeout: int = 5) -> bool:
    """探測本地 LLM server 是否可用（GET /v1/models）。"""
    import urllib.request

    try:
        urllib.request.urlopen(f"{base_url}/v1/models", timeout=timeout)
        return True
    except Exception:
        return False


def get_judge_llm() -> LLMBackend:
    """
    Judge LLM backend（預設與主 LLM 相同）。
    可透過 JUDGE_LLM_URL / JUDGE_LLM_MODEL 指定獨立模型（如更強的評分模型）。
    """
    judge_url = (
        os.environ.get("JUDGE_LLM_URL")
        or os.environ.get("LOCAL_LLM_URL", DEFAULT_LOCAL_LLM_URL)
    )
    judge_model = os.environ.get("JUDGE_LLM_MODEL", DEFAULT_JUDGE_LLM_MODEL)
    return LocalLLMBackend(base_url=judge_url, model=judge_model)

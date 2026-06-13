"""
LLM 後端設定。

預設：LocalLLMBackend（http://localhost:1234）

環境變數：
    LOCAL_LLM_URL    本地 LLM server URL（預設 http://localhost:1234）
    LOCAL_LLM_MODEL  本地模型名稱（預設 qwen/qwen3.6-27b）
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


VAULT_ROOT = Path(
    os.environ.get(
        "VAULT_ROOT",
        "/Users/guangzhenglee/Library/Mobile Documents/iCloud~md~obsidian/Documents/Second-Brain",
    )
)

DEFAULT_LOCAL_LLM_URL = "http://localhost:1234"
DEFAULT_LOCAL_LLM_MODEL = "qwen/qwen3.6-27b"
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

        body: dict = {"model": self.model, "messages": messages, "max_tokens": 16384}
        payload = json.dumps(body).encode()

        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1500) as resp:
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


def ensure_llm_ready(
    base_url: str = DEFAULT_LOCAL_LLM_URL,
    retries: int = 18,
    interval: int = 10,
) -> bool:
    """確保 LM Studio server 可用；若未啟動則自動喚醒並等待就緒。

    流程：
      1. 直接探測 API，已就緒則立即返回 True
      2. open -a "LM Studio" + lms server start
      3. 每 interval 秒輪詢，最多 retries 次（預設 3 分鐘）
      4. 超時仍無回應則返回 False
    """
    import shutil
    import subprocess
    import time

    if check_local_llm(base_url):
        return True

    subprocess.run(["open", "-a", "LM Studio"], capture_output=True)
    lms_bin = shutil.which("lms") or (
        "/Applications/LM Studio.app/Contents/Resources/app/.webpack/lms"
    )
    try:
        subprocess.run([lms_bin, "server", "start"], capture_output=True, timeout=15)
    except Exception:
        pass

    for _ in range(retries):
        time.sleep(interval)
        if check_local_llm(base_url):
            return True

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

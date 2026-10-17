"""
LLM 後端設定。

預設：LocalLLMBackend（http://localhost:1234）

環境變數：
    LOCAL_LLM_URL    本地 LLM server URL（預設 http://localhost:1234）
    LOCAL_LLM_MODEL  本地模型名稱（預設 qwen/qwen3.6-27b）
    LLM_STRUCTURED_OUTPUT  json_schema 約束解碼開關（預設開；0/false/off 關閉，見 ADR 0006）
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from config.utils import load_project_env

if TYPE_CHECKING:
    from tools.usage_meter import UsageMeter

# 啟動時即載入專案根 .env，確保下方的 env 解析（含 VAULT_ROOT）拿得到值。
load_project_env()

# Obsidian vault 根目錄。**選填**：未配置 VAULT_ROOT 時為 None，
# save 步驟會優雅略過 Obsidian 存檔（其餘 pipeline 不受影響）。
# 機器專屬路徑請寫在各自的 .env，不要寫死在原始碼。
_VAULT_ROOT_RAW = (os.environ.get("VAULT_ROOT") or "").strip()
VAULT_ROOT: Path | None = Path(_VAULT_ROOT_RAW) if _VAULT_ROOT_RAW else None

DEFAULT_LOCAL_LLM_URL = "http://localhost:1234"
DEFAULT_LOCAL_LLM_MODEL = "qwen/qwen3.6-27b"
# qwen3.6-35b-a3b：a3b 稀疏 MoE（active ~3b、開銷低），實測比 gemma-4-e4b
# 有鑑別力（會針對具體缺陷扣分而非一律給 5）；解 judge 飽和（見 issue #24）。
DEFAULT_JUDGE_LLM_MODEL = "qwen3.6-35b-a3b"


# response_format.json_schema.name：LM Studio 只要求非空，不影響解碼。
_SCHEMA_NAME = "response"
_FALSY = frozenset({"0", "false", "off", "no"})


def structured_output_enabled() -> bool:
    """LLM_STRUCTURED_OUTPUT 回退開關：未設定或非 falsy 值 → 開。"""
    raw = (os.environ.get("LLM_STRUCTURED_OUTPUT") or "").strip().lower()
    return raw not in _FALSY


class LLMBackend(Protocol):
    def complete(
        self, prompt: str, system: str = "", schema: dict | None = None
    ) -> str: ...


def _extract_content(message: dict, structured: bool) -> str:
    """從 chat completion message 取回答案文字（純函數）。

    spike 實測（ADR 0006）：LM Studio 對 qwen3.6 帶 json_schema 時，文法從第一個
    token 即生效、模型不思考，但 reasoning parser 仍把整段輸出標成 reasoning，
    使 JSON 落在 reasoning_content、content 為空。僅在約束解碼時退回讀
    reasoning_content；無 schema 時它是隱藏思考，絕不當答案。
    """
    content = message.get("content") or ""
    if structured and not content.strip():
        return message.get("reasoning_content") or ""
    return content


class LocalLLMBackend:
    """
    本地 LLM server 後端（LM Studio / OpenAI-compatible API）。
    Endpoint：POST /v1/chat/completions
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        meter: "UsageMeter | None" = None,
        structured_output: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        # 選填的 token 帳本：非 None 時每次 complete() 後記錄 usage（觀測層，預設不追蹤）。
        self.meter = meter
        # False 時忽略 schema、退回純 prompt + parse_llm_json（回退開關）。
        self.structured_output = structured_output

    def complete(
        self, prompt: str, system: str = "", schema: dict | None = None
    ) -> str:
        """送出 chat completion。schema 非 None 時以 json_schema 約束解碼（strict）。"""
        import json
        import urllib.request

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        structured = schema is not None and self.structured_output
        body: dict = {"model": self.model, "messages": messages, "max_tokens": 16384}
        if structured:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": _SCHEMA_NAME, "strict": True, "schema": schema},
            }
        payload = json.dumps(body).encode()

        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1500) as resp:
            data = json.loads(resp.read().decode())

        if self.meter is not None:
            self.meter.record(self.model, data.get("usage"))

        return _extract_content(data["choices"][0]["message"], structured)


def get_llm() -> LLMBackend:
    local_url = os.environ.get("LOCAL_LLM_URL", DEFAULT_LOCAL_LLM_URL)
    local_model = os.environ.get("LOCAL_LLM_MODEL", DEFAULT_LOCAL_LLM_MODEL)
    return LocalLLMBackend(
        base_url=local_url,
        model=local_model,
        structured_output=structured_output_enabled(),
    )


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
    judge_url = os.environ.get("JUDGE_LLM_URL") or os.environ.get(
        "LOCAL_LLM_URL", DEFAULT_LOCAL_LLM_URL
    )
    judge_model = os.environ.get("JUDGE_LLM_MODEL", DEFAULT_JUDGE_LLM_MODEL)
    return LocalLLMBackend(
        base_url=judge_url,
        model=judge_model,
        structured_output=structured_output_enabled(),
    )

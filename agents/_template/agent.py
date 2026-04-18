"""
[AgentName] — 一行說明此 agent 的目標。

複製此範本時：
1. 重新命名類別與 AGENT_NAME
2. 實作 run() 主流程
3. 在 prompts.py 定義所有 LLM prompt
4. 在 pipelines/ 定義跨 agent 編排（若需要）
"""

from __future__ import annotations

from config import get_llm, get_logger
from config.settings import LLMBackend

logger = get_logger(__name__)


class TemplateAgent:
    """黃金範本 — 所有 agent 需符合此介面。"""

    AGENT_NAME = "template"

    def __init__(self, llm: LLMBackend | None = None) -> None:
        self._llm = llm or get_llm()

    # ── 公開介面（lint/check_agent_interface.py 驗證） ───────────

    def run(self, args: str = "") -> str:
        """
        執行 agent 主流程。
        - args：使用者輸入（去掉觸發詞後的剩餘部分）
        - 回傳：最終輸出訊息（str）
        """
        raise NotImplementedError

    # ── LLM 呼叫 ────────────────────────────────────────────────

    def _complete(self, prompt: str, system: str = "") -> str:
        """統一 LLM 呼叫入口，方便測試時 mock。"""
        logger.debug("LLM prompt length: %d", len(prompt))
        return self._llm.complete(prompt, system=system)

    # ── 系統 prompt ──────────────────────────────────────────────

    @staticmethod
    def _system() -> str:
        return (
            "你是一個嚴格按照指示執行的 agent。\n"
            "輸出語言：繁體中文。\n"
            "需要結構化輸出時，回傳合法 JSON（可用 ```json 包裹）。"
        )

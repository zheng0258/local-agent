"""
Agent 主入口。

使用方式：
    python main.py "/daily-brief"
    python main.py "幫我摘要這些連結 https://example.com"

環境變數：
    LOCAL_LLM_URL    本地 LLM server URL（如 http://localhost:11434）
    LOCAL_LLM_MODEL  本地模型名稱（預設 llama3）
    ANTHROPIC_API_KEY  備援 Anthropic API key
"""

import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import get_llm, setup_logging
from tools.lms_lifecycle import ensure_models_loaded, unload_all
from config.settings import DEFAULT_LOCAL_LLM_MODEL, DEFAULT_JUDGE_LLM_MODEL
from agents.daily_brief import DailyBriefAgent
from agents.url_digest import UrlDigestAgent

SKILL_MAP = [
    (["/daily-brief", "收集今日趨勢", "跑趨勢收集", "run daily-brief"], DailyBriefAgent),
    (["/url-digest", "幫我摘要這些連結", "digest these urls", "summarize this article"], UrlDigestAgent),
]


def route(user_input: str):
    lower = user_input.lower()
    for triggers, agent_cls in SKILL_MAP:
        for trigger in triggers:
            if re.search(re.escape(trigger.lower()), lower):
                # 保留原始大小寫（URL 對大小寫敏感）
                original_args = user_input[len(trigger):].strip() if lower.startswith(trigger.lower()) else user_input
                return agent_cls, original_args
    return None, user_input


_STABILIZE_SECONDS = 600


def _wait_for_model_stabilize(logger: logging.Logger) -> None:
    """模型剛被載入時等待 LM Studio API 完全就緒。

    lms load 完成只代表模型進 lms ps，不代表 /v1/chat/completions 可用。
    大型模型（27B+）通常需要 30–120s 才能接受第一個 inference 請求。
    """
    try:
        from tools.notifiers.telegram import send as tg_send
        tg_send(
            f"🔄 模型剛載入完成，等待 {_STABILIZE_SECONDS // 60} 分鐘讓 LM Studio API 穩定後再開始執行..."
        )
    except Exception:
        pass  # Telegram 失敗不應阻斷 pipeline

    logger.info("模型剛載入，等待 %ds 確保 API 就緒...", _STABILIZE_SECONDS)
    time.sleep(_STABILIZE_SECONDS)
    logger.info("等待完畢，開始執行 pipeline")


def main() -> None:
    setup_logging()
    user_input = " ".join(sys.argv[1:]).strip()
    if not user_input:
        print("使用方式：python main.py \"<指令>\"")
        print("可用 skill：/daily-brief、/url-digest <URL>")
        sys.exit(1)

    agent_cls, args = route(user_input)
    if agent_cls is None:
        print(f"找不到對應的 skill：{user_input!r}")
        sys.exit(1)

    logger = logging.getLogger(__name__)

    llm = get_llm()
    agent = agent_cls(llm=llm)
    print(f"[router] skill={agent.AGENT_NAME}, args={args!r}")

    freshly_loaded = ensure_models_loaded([DEFAULT_LOCAL_LLM_MODEL, DEFAULT_JUDGE_LLM_MODEL])
    if freshly_loaded:
        _wait_for_model_stabilize(logger)

    try:
        print(agent.run(args))
    finally:
        unload_all()


if __name__ == "__main__":
    main()

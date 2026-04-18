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

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import get_llm, setup_logging
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

    llm = get_llm()
    agent = agent_cls(llm=llm)
    print(f"[router] skill={agent.AGENT_NAME}, args={args!r}")
    print(agent.run(args))


if __name__ == "__main__":
    main()

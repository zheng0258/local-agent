"""Daily Brief — 來源設定與門檻。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from config.settings import VAULT_ROOT

# ── 輸出路徑 ─────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = _PROJECT_ROOT / "outputs" / "daily-brief"
INDEX_FILE = OUTPUT_DIR / "_daily-brief.md"

# ── Dedup 設定 ────────────────────────────────────────────────────

DEDUP_SIMILARITY_THRESHOLD = 0.80
DEDUP_WINDOW_DAYS = 7
VECTOR_DB_PATH = OUTPUT_DIR / ".vectordb"

# ── 抓取來源 ─────────────────────────────────────────────────────

HATENA_URLS = [
    "https://b.hatena.ne.jp/hotentry/it",
    "https://b.hatena.ne.jp/hotentry/it/AI%E3%83%BB%E6%A9%9F%E6%A2%B0%E5%AD%A6%E7%BF%92",
]

SECURITY_BLOG_URLS = [
    "https://www.aikido.dev/blog",
    "https://www.wiz.io/blog",
]

# ── 評分門檻 ─────────────────────────────────────────────────────

HATENA_DIGEST_THRESHOLD = 100    # 書籤數
HN_DIGEST_THRESHOLD = 200        # 分數
REDDIT_DIGEST_THRESHOLD = 300    # upvotes
FALLBACK_TOP_N = 3               # 無符合門檻時取前 N 篇

# ── Reddit 子版 ──────────────────────────────────────────────────

REDDIT_SUBREDDITS: dict[str, list[str]] = {
    "資安類":        ["netsec", "cybersecurity"],
    "AI 類":         ["OpenAI", "LocalLLaMA", "ClaudeCode"],
    "AI 開發工具類": ["cursor_ai", "ChatGPT", "GoogleGeminiAI"],
    "核心技術類":    ["programming", "technology"],
    "OSS・獨立開發類": ["opensource", "indiehackers", "webdev", "javascript"],
    "職涯・實踐類":  ["cscareerquestions", "productivity"],
}

# ── Obsidian vault ────────────────────────────────────────────────

VAULT_DAILY_BRIEF_DIR = VAULT_ROOT / "01 Projects" / "daily-brief"

# ── Step retry config ─────────────────────────────────────────────


@dataclass(frozen=True)
class StepConfig:
    max_retries: int
    strategy: Literal["plain", "error_aware"]
    backoff_seconds: tuple[float, ...] = (0.0,)
    task_description: str = ""


STEP_CONFIGS: dict[str, StepConfig] = {
    "dedup": StepConfig(
        max_retries=1,
        strategy="plain",
        task_description="向量去重：過濾 7 天內 URL 重複或語意相似（> 0.80）文章",
    ),
    "hatena": StepConfig(
        max_retries=3,
        strategy="plain",
        backoff_seconds=(1.0, 3.0, 9.0),
        task_description="從 Hatena Bookmark 抓取文章並以 JSON 格式回傳 interest 評分結果",
    ),
    "hn": StepConfig(
        max_retries=3,
        strategy="plain",
        backoff_seconds=(1.0, 3.0, 9.0),
        task_description="從 Hacker News 抓取文章並以 JSON 格式回傳 interest 評分結果",
    ),
    "reddit": StepConfig(
        max_retries=3,
        strategy="plain",
        backoff_seconds=(1.0, 3.0, 9.0),
        task_description="從 Reddit 各 subreddit 抓取文章並以 JSON 格式回傳 interest 評分結果",
    ),
    "security": StepConfig(
        max_retries=3,
        strategy="plain",
        backoff_seconds=(1.0, 3.0, 9.0),
        task_description="從 Security blogs 抓取文章並以 JSON 格式回傳 interest 評分結果",
    ),
    "compress": StepConfig(
        max_retries=2,
        strategy="error_aware",
        task_description="將各來源 *** 文章語義壓縮為 themes 陣列 + articles 陣列（含 one_liner），輸出 JSON",
    ),
    "digest": StepConfig(
        max_retries=2,
        strategy="error_aware",
        task_description="跨來源深度摘要，輸出含 title/url/source/summary 的 digests 陣列 JSON",
    ),
    "judge": StepConfig(
        max_retries=2,
        strategy="error_aware",
        task_description="LLM-as-Judge 評分 relevance/completeness/faithfulness，輸出含 scores 物件的 JSON",
    ),
    "report": StepConfig(
        max_retries=2,
        strategy="error_aware",
        task_description="根據 compress + digest 資料生成純 markdown 格式的科技趨勢報告，不包 JSON fence",
    ),
    "notify": StepConfig(
        max_retries=2,
        strategy="error_aware",
        task_description="生成 Telegram 訊息 JSON（tg_overview 或 tg_digest key），限用 Telegram 允許的 HTML tag",
    ),
    "save": StepConfig(
        max_retries=2,
        strategy="plain",
        task_description="將 report.md 和 digest 存入 Obsidian vault",
    ),
}

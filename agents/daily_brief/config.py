"""Daily Brief — 來源設定與門檻。"""

from pathlib import Path
from config.settings import VAULT_ROOT

# ── 輸出路徑 ─────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = _PROJECT_ROOT / "outputs" / "daily-brief"
INDEX_FILE = OUTPUT_DIR / "_daily-brief.md"

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

"""
UrlDigestAgent — URL 摘要工具。

流程：
  解析 URL → 分類 → 依類型抓取 → LLM 摘要 → 存檔
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from config import get_llm, get_logger
from config.settings import LLMBackend

from . import prompts

logger = get_logger(__name__)

URL_PATTERN = re.compile(r"https?://\S+")

_PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = _PROJECT_ROOT / "outputs" / "url-digest"
INDEX_FILE = _PROJECT_ROOT / "outputs" / "url-digest" / "_index.md"


class UrlDigestAgent:

    AGENT_NAME = "url-digest"

    def __init__(self, llm: LLMBackend | None = None) -> None:
        self._llm = llm or get_llm()

    def run(self, args: str = "") -> str:
        urls = URL_PATTERN.findall(args)
        if not urls:
            return "未找到有效 URL，請提供至少一個 https:// 開頭的連結。"

        today = date.today().strftime("%Y-%m-%d")
        articles: list[str] = []

        for url in urls:
            logger.info("處理 URL：%s", url)
            article_md = self._process_url(url)
            if article_md:
                articles.append(article_md)

        if articles:
            self._save(articles, today)

        return f"摘要完成。已儲存至 01 Projects/daily-digest/url-digest/{today}.md"

    # ── URL 分類（確定性）───────────────────────────────────────

    @staticmethod
    def _classify(url: str) -> str:
        if "x.com/" in url or "twitter.com/" in url:
            return "twitter"
        if "news.ycombinator.com/item?id=" in url:
            return "hn"
        if "reddit.com/r/" in url and "/comments/" in url:
            return "reddit"
        return "general"

    # ── 依類型抓取 ──────────────────────────────────────────────

    def _process_url(self, url: str) -> str | None:
        url_type = self._classify(url)
        try:
            if url_type == "hn":
                return self._process_hn(url)
            elif url_type == "reddit":
                return self._process_reddit(url)
            elif url_type == "twitter":
                return self._process_twitter(url)
            else:
                return self._process_general(url)
        except Exception as e:
            logger.warning("處理 %s 失敗：%s", url, e)
            return None

    def _process_general(self, url: str) -> str:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "url-digest/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="replace")[:6000]
        return self._summarize(title=url, content=content, url=url)

    def _process_hn(self, url: str) -> str:
        import subprocess
        item_id = re.search(r"item\?id=(\d+)", url).group(1)
        result = subprocess.run(
            f'curl -s "https://hn.algolia.com/api/v1/items/{item_id}" | '
            "jq '{title, url, text, children: [.children[:5][].text]}'",
            shell=True, capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout or "{}")
        content = data.get("text") or ""
        comments = "\n".join(c for c in (data.get("children") or []) if c)
        return self._summarize(
            title=data.get("title", url),
            content=content,
            url=url,
            comments=comments,
        )

    def _process_reddit(self, url: str) -> str:
        import subprocess
        m = re.search(r"reddit\.com/r/(\w+)/comments/(\w+)", url)
        sub, post_id = m.group(1), m.group(2)
        api = f"https://old.reddit.com/r/{sub}/comments/{post_id}.json"

        raw = subprocess.run(
            f"curl -s -H 'User-Agent: url-digest/1.0' '{api}'",
            shell=True, capture_output=True, text=True, timeout=30,
        ).stdout or "[]"

        data = json.loads(raw)
        post_data = data[0]["data"]["children"][0]["data"] if data else {}
        comment_children = data[1]["data"]["children"][:8] if len(data) > 1 else []

        content = post_data.get("selftext") or ""
        comments = "\n".join(
            c["data"]["body"][:500]
            for c in comment_children
            if c.get("data", {}).get("body")
        )
        return self._summarize(
            title=post_data.get("title", url),
            content=content,
            url=url,
            comments=comments,
        )

    def _process_twitter(self, url: str) -> str:
        # chrome-devtools-mcp 需要瀏覽器環境，此處回傳提示
        return f"## [Twitter/X]\n\n需要 chrome-devtools-mcp 瀏覽器工具才能處理 X/Twitter 連結。\n\n{url}"

    # ── LLM 摘要 ────────────────────────────────────────────────

    def _summarize(self, title: str, content: str, url: str, comments: str = "") -> str:
        prompt = prompts.build_summary_prompt(title, content[:4000], url, comments[:1000])
        result = self._parse_json(self._llm.complete(prompt, system=prompts.SYSTEM))
        title_zh = result.get("title_zh", title)
        summary = result.get("summary", "（摘要生成失敗）")
        return f"## {title_zh}\n\n{summary}\n\n{url}"

    # ── 存檔 ────────────────────────────────────────────────────

    def _save(self, articles: list[str], today: str) -> None:
        output_path = OUTPUT_DIR / f"{today}.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        article_content = "\n\n---\n\n".join(articles)

        if not output_path.exists():
            output_path.write_text(
                f"# URL Digest：{today}\n\n---\n\n{article_content}",
                encoding="utf-8",
            )
        else:
            with output_path.open("a", encoding="utf-8") as f:
                f.write(f"\n---\n\n{article_content}")

        self._update_index(today)

    def _update_index(self, today: str) -> None:
        if not INDEX_FILE.exists():
            return
        existing = INDEX_FILE.read_text(encoding="utf-8")
        row_marker = f"| url-digest | {today} |"
        if row_marker not in existing:
            new_row = f"| [[01 Projects/daily-digest/url-digest/{today}|{today}]] | url-digest | {today} |\n"
            with INDEX_FILE.open("a", encoding="utf-8") as f:
                f.write(new_row)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        try:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            return json.loads(m.group(1) if m else raw)
        except (json.JSONDecodeError, AttributeError):
            return {}

"""Security blogs fetcher（aikido.dev、wiz.io）。使用 Playwright 渲染 JS 頁面。"""

from __future__ import annotations

import json
import subprocess
import time
import uuid

from tools.fetchers.browser import _cli_bin, _run, _wait_for_session

# JS 提取腳本（在瀏覽器 context 執行）
_AIKIDO_JS = (
    "(function(){"
    "var seen={}; var arts=[];"
    "document.querySelectorAll('a[href^=\"/blog/\"]').forEach(function(a){"
    "var t=a.querySelector('[fs-list-field=\"title\"]');"
    "var d=a.querySelector('[fs-list-field=\"description\"]');"
    "var href=a.getAttribute('href');"
    "if(t&&href&&!seen[href]){"
    "seen[href]=1;"
    "arts.push({title:t.textContent.trim(),"
    "url:'https://www.aikido.dev'+href,"
    "description:d?d.textContent.trim().slice(0,200):''});"
    "}"
    "});"
    "return JSON.stringify(arts.slice(0,10));"
    "})()"
)

_WIZ_JS = (
    "(function(){"
    "var seen={}; var arts=[];"
    "document.querySelectorAll('a[href^=\"/blog/\"]').forEach(function(a){"
    "var t=a.querySelector('h2,h3');"
    "var href=a.getAttribute('href');"
    "if(t&&href&&!seen[href]&&t.textContent.trim().length>10){"
    "seen[href]=1;"
    "arts.push({title:t.textContent.trim(),"
    "url:'https://www.wiz.io'+href});"
    "}"
    "});"
    "return JSON.stringify(arts.slice(0,10));"
    "})()"
)

_SOURCES: list[dict] = [
    {"url": "https://www.aikido.dev/blog", "source": "aikido.dev", "js": _AIKIDO_JS},
    {"url": "https://www.wiz.io/blog",     "source": "wiz.io",     "js": _WIZ_JS},
]

_PAGE_LOAD_WAIT = 6  # JS 重度渲染需要等待


def _fetch_articles(source: dict) -> list[dict]:
    cli = _cli_bin()
    session = f"sec-{uuid.uuid4().hex[:8]}"
    base = cli + [f"-s={session}"]

    open_proc = subprocess.Popen(
        base + ["open", source["url"]],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        if not _wait_for_session(cli, session):
            raise RuntimeError(f"session '{session}' 未就緒")
        time.sleep(_PAGE_LOAD_WAIT)

        raw = _run(base + ["--raw", "eval", source["js"]])
        # --raw eval 回傳 JSON 字串，需解碼一層
        try:
            inner = json.loads(raw)
            articles = json.loads(inner) if isinstance(inner, str) else inner
        except (json.JSONDecodeError, TypeError):
            articles = []

        for a in articles:
            a["source"] = source["source"]
        return articles
    except Exception as e:
        return [{"source": source["source"], "error": str(e)}]
    finally:
        _run(base + ["close"])
        open_proc.terminate()
        try:
            open_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            open_proc.kill()


def fetch() -> list[dict]:
    """
    抓取 aikido.dev 與 wiz.io 最新文章。
    回傳格式：[{"title", "url", "source", "description"?}, ...]
    """
    articles: list[dict] = []
    for source in _SOURCES:
        articles.extend(_fetch_articles(source))
    return articles

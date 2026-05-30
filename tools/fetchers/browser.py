"""
Browser fetcher — 使用 playwright-cli 渲染 JS 頁面。

提供 fetch_page() 和 fetch_pages() 兩個公開介面。

playwright-cli 採 daemon 模式：
  - `open` 啟動背景 daemon，不會自行退出
  - 後續 `eval` / `close` 連接到同一 session
  - 必須用 Popen 啟動 `open`，再輪詢 `list` 確認就緒
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid

# launchd 環境 PATH 極簡，手動補全常見 node/brew 路徑
_EXTRA_PATHS = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    os.path.expanduser("~/.nvm/versions/node/v22.15.0/bin"),
]
_env_path = os.environ.get("PATH", "")
os.environ["PATH"] = ":".join([p for p in _EXTRA_PATHS if p not in _env_path] + [_env_path])


def _cli_bin() -> list[str]:
    """回傳 playwright-cli 執行指令（list 形式）。"""
    if shutil.which("playwright-cli"):
        return ["playwright-cli"]
    npx = shutil.which("npx")
    if npx:
        return [npx, "--no-install", "playwright-cli"]
    raise FileNotFoundError("playwright-cli / npx 均不在 PATH 中，請確認 Node.js 已安裝")


def _run(args: list[str], timeout: int = 60) -> str:
    """執行 playwright-cli 指令，回傳 stdout。"""
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip()


def _decode_js_result(raw: str) -> str:
    """playwright-cli --raw eval 回傳 JSON 字串，需解碼一層。"""
    try:
        decoded = json.loads(raw)
        return decoded if isinstance(decoded, str) else raw
    except (json.JSONDecodeError, ValueError):
        return raw


def _wait_for_session(cli: list[str], session: str, retries: int = 10, interval: float = 1.0) -> bool:
    """輪詢直到 session 出現在 list 中，回傳是否就緒。"""
    for _ in range(retries):
        output = _run(cli + ["list"])
        if session in output:
            return True
        time.sleep(interval)
    return False


def _fetch_with_playwright_cli(url: str, session: str, page_load_wait: float = 0) -> dict:
    cli = _cli_bin()
    base = cli + [f"-s={session}"]

    # open 是長駐 daemon，用 Popen 放到背景
    open_proc = subprocess.Popen(
        base + ["open", url],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # 等 session daemon 就緒（最多 10 秒）
        ready = _wait_for_session(cli, session, retries=10, interval=1.0)
        if not ready:
            raise RuntimeError(f"playwright-cli session '{session}' 未在 10 秒內就緒")

        # JS 重度渲染頁面需要額外等待
        if page_load_wait > 0:
            time.sleep(page_load_wait)

        title = _decode_js_result(_run(base + ["--raw", "eval", "document.title"]))
        html = _decode_js_result(_run(base + ["--raw", "eval", "document.documentElement.outerHTML"]))
        _run(base + ["close"])
    finally:
        open_proc.terminate()
        try:
            open_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            open_proc.kill()

    return {"url": url, "html": html, "title": title}


def fetch_page(url: str, max_chars: int = 8000, page_load_wait: float = 0) -> dict:
    """
    用 playwright-cli 抓取單一 URL（支援 JS 渲染）。

    page_load_wait：session 就緒後額外等待秒數（JS 重度渲染頁面用）。
    回傳：{"url": str, "html": str, "title": str}
    失敗：{"url": str, "error": str}
    """
    session = f"fetch-{uuid.uuid4().hex[:8]}"
    try:
        result = _fetch_with_playwright_cli(url, session, page_load_wait=page_load_wait)
        result["html"] = result["html"][:max_chars]
        return result
    except Exception as e:
        return {"url": url, "error": str(e)}


def fetch_pages(urls: list[str], max_chars: int = 8000, page_load_wait: float = 0) -> list[dict]:
    """
    依序抓取多個 URL。
    """
    return [fetch_page(url, max_chars=max_chars, page_load_wait=page_load_wait) for url in urls]

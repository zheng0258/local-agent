"""
Telegram 通知工具（純函數，無 LLM）。

憑證從專案根目錄的 .env 載入：
  TELEGRAM_BOT_TOKEN=...
  TELEGRAM_CHAT_ID=...

憑證未設定時靜默略過（印出警告，不拋錯）。
"""

from __future__ import annotations

import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from config.utils import load_project_env

# Telegram HTML mode 支援的 tag（其餘一律移除）
_ALLOWED_TAGS = {"b", "i", "u", "s", "a", "code", "pre"}
_TAG_RE = re.compile(r"<(/?)(\w[\w-]*)(\s[^>]*)?>", re.IGNORECASE)


def _sanitize_html(text: str) -> str:
    """移除 Telegram 不支援的 HTML tag，保留允許的 tag 與其屬性。"""
    def _replace(m: re.Match) -> str:
        tag = m.group(2).lower()
        if tag in _ALLOWED_TAGS:
            return m.group(0)
        return ""

    return _TAG_RE.sub(_replace, text)

MAX_LEN = 4096


def send(
    text: str,
    token_env: str = "TELEGRAM_BOT_TOKEN",
    chat_id_env: str = "TELEGRAM_CHAT_ID",
) -> bool:
    """
    發送 Telegram 訊息。
    - parse_mode=HTML（支援 <b>、<a href>）
    - 超過 MAX_LEN 自動截斷
    - 憑證未設定：印出警告後回傳 False
    - token_env / chat_id_env：指定讀取哪個 env var（不同 bot 時覆寫）
    """
    load_project_env()
    token = (os.environ.get(token_env) or "").strip() or None
    chat_id = (os.environ.get(chat_id_env) or "").strip() or None

    if not token or not chat_id:
        print(f"⚠️  {token_env} 或 {chat_id_env} 未設定，略過通知。")
        return False

    text = _sanitize_html(text)

    if len(text) > MAX_LEN:
        text = text[: MAX_LEN - 3] + "..."

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    ).encode()

    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    try:
        urllib.request.urlopen(url, data=data, context=ctx, timeout=30)
        print("✅ Telegram 訊息傳送成功")
        return True
    except urllib.error.HTTPError as e:
        print(f"❌ Telegram 發送失敗：{e.code} {e.read().decode()}")
        return False
    except urllib.error.URLError as e:
        print(f"❌ Telegram 網路錯誤：{e.reason}")
        return False


def send_many(messages: list[str]) -> None:
    """依序發送多段訊息，各自獨立計算 MAX_LEN。"""
    for msg in messages:
        if msg:
            send(msg)

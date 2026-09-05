"""links — URL 確定性替換與驗證（純函數，無 LLM、無 I/O）。

核心原則：**URL 是資料，不是 LLM 輸出。** 凡是 URL 要進入 LLM 輸出（digest
的 url 欄位、compose_tg 的 <a href>），一律以 id token 佔位，送回後由 Python
依 id 從可信來源替換。LLM 只負責它擅長的事（摘要、翻譯標題），永遠不負責複製
網址——杜絕「捏造 / 竄改 / 丟失 URL」整類 bug（見 09-05 TG 無連結事件）。

- `TOKEN_RE` / `href_token`：token 格式 @@<id>@@。
- `substitute_href_tokens`：把 href="@@N@@" 換成 url_by_id[N] 的真實網址。
- `strip_invalid_anchors`：把 href 非 http(s) 的 <a>…</a> 拆掉外殼、只留錨文字
  （優雅降級：使用者看到條目但無死連結），回傳 (清理後 html, 被拆數量)。
- `is_valid_url`：http/https 開頭才算合法。
"""

from __future__ import annotations

import re

TOKEN_RE = re.compile(r"@@(\d+)@@")
_HREF_RE = re.compile(r'href="([^"]*)"')
# <a ...>錨文字</a>：錨文字不含巢狀標籤（TG 格式為 <b><a>title</a></b>）
_ANCHOR_RE = re.compile(r'<a\s+href="([^"]*)"\s*>(.*?)</a>', re.DOTALL)
# Markdown 連結 [文字](目標)；文字不含 ]、目標不含 )
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")


def href_token(article_id: int) -> str:
    """LLM 應寫入 href 的佔位符（取代真實 URL）。"""
    return f"@@{article_id}@@"


def is_valid_url(url: str) -> bool:
    return isinstance(url, str) and (
        url.startswith("http://") or url.startswith("https://")
    )


def substitute_href_tokens(html: str, url_by_id: dict[int, str]) -> str:
    """把 html 中 href="@@N@@" 的 token 替換成 url_by_id[N] 的真實 URL。

    未知 id 或格式不符的 href 原樣保留（交由 strip_invalid_anchors 收尾）。
    純函數：回傳新字串，不 mutate 輸入。
    """

    def _repl(m: re.Match) -> str:
        raw = m.group(1)
        token = TOKEN_RE.fullmatch(raw.strip())
        if token:
            url = url_by_id.get(int(token.group(1)))
            if url:
                return f'href="{url}"'
        return m.group(0)

    return _HREF_RE.sub(_repl, html)


def strip_invalid_anchors(html: str) -> tuple[str, int]:
    """把 href 非 http(s) 的 <a href="…">錨文字</a> 拆成純錨文字。

    最後防線：確保送達使用者的訊息**絕不含死連結 / 佔位字 / 未替換 token**。
    回傳 (清理後 html, 被拆掉的錨數量)；數量 > 0 應由呼叫端記 alert。
    """
    removed = 0

    def _repl(m: re.Match) -> str:
        nonlocal removed
        url, text = m.group(1), m.group(2)
        if is_valid_url(url):
            return m.group(0)
        removed += 1
        return text

    return _ANCHOR_RE.sub(_repl, html), removed


def substitute_md_link_tokens(md: str, url_by_id: dict[int, str]) -> str:
    """把 markdown [文字](@@N@@) 的 token 換成 url_by_id[N] 的真實 URL。

    未知 id / 格式不符原樣保留（交由 strip_invalid_md_links 收尾）。純函數。
    """

    def _repl(m: re.Match) -> str:
        text, target = m.group(1), m.group(2)
        token = TOKEN_RE.fullmatch(target.strip())
        if token:
            url = url_by_id.get(int(token.group(1)))
            if url:
                return f"[{text}]({url})"
        return m.group(0)

    return _MD_LINK_RE.sub(_repl, md)


def strip_invalid_md_links(md: str) -> tuple[str, int]:
    """把 [文字](目標) 中目標非 http(s) 的連結拆成純文字（防死連結 / (#) / 未替換 token）。

    回傳 (清理後 md, 被拆掉的連結數)。> 0 應由呼叫端記 alert。純函數。
    """
    removed = 0

    def _repl(m: re.Match) -> str:
        nonlocal removed
        text, target = m.group(1), m.group(2)
        if is_valid_url(target):
            return m.group(0)
        removed += 1
        return text

    return _MD_LINK_RE.sub(_repl, md), removed

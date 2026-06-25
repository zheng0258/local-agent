"""render_index — Jinja2 首頁模板（技術終端風：暗色 + 等寬）。

inline CSS，不引入 Node toolchain / SSG 框架 / 圖表庫。
定位句「本地 LLM 多代理自主系統」固定出現在首頁。
"""

from __future__ import annotations

from jinja2 import Template

POSITIONING_LINE = "本地 LLM 多代理自主系統"

_INDEX_TEMPLATE = Template(
    """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Brief — {{ date }}</title>
<style>
  :root { --bg: #0b0f14; --fg: #c8d3df; --accent: #4fd1c5; --dim: #5a6b7a; }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 2rem 1rem;
    background: var(--bg);
    color: var(--fg);
    font-family: "SFMono-Regular", "Menlo", "Consolas", "Liberation Mono", monospace;
    line-height: 1.6;
  }
  main { max-width: 880px; margin: 0 auto; }
  header { border-bottom: 1px solid var(--dim); padding-bottom: 1rem; margin-bottom: 2rem; }
  .tagline { color: var(--accent); }
  a { color: var(--accent); }
  h1, h2, h3 { color: var(--fg); }
  code, pre { background: #11161d; color: var(--accent); }
  .meta { color: var(--dim); }
</style>
</head>
<body>
<main>
<header>
  <p class="tagline">{{ positioning_line }}</p>
  <p class="meta">{{ date }}</p>
</header>
<article>
{{ body_html }}
</article>
</main>
</body>
</html>
"""
)


def render_index(body_html: str, date: str) -> str:
    """渲染首頁 HTML：技術終端 shell 包住 report 內文。"""
    return _INDEX_TEMPLATE.render(
        body_html=body_html,
        date=date,
        positioning_line=POSITIONING_LINE,
    )

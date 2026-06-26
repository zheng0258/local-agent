"""render_index / render_archive — Jinja2 模板（技術終端風：暗色 + 等寬）。

inline CSS，不引入 Node toolchain / SSG 框架 / 圖表庫。
定位句「本地 LLM 多代理自主系統」固定出現在首頁。
存檔頁維持繁中（雙語策略：歷史不英譯）。
"""

from __future__ import annotations

from typing import NamedTuple, Sequence

from jinja2 import Template

POSITIONING_LINE = "本地 LLM 多代理自主系統"

# 共用 shell CSS：首頁與存檔頁同一終端風外觀。
_SHELL_STYLE = """
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
  nav.archive { margin-top: 2rem; border-top: 1px solid var(--dim); padding-top: 1rem; }
  nav.archive ul { list-style: none; padding: 0; }
  nav.archive li { margin: 0.25rem 0; }
  section.narrative { margin-bottom: 2rem; border-bottom: 1px solid var(--dim); padding-bottom: 1rem; }
  /* EN／中 切換：純 CSS，無 JS 框架。隱藏 radio，label 當分頁鈕，:checked 決定顯示哪版。 */
  .lang-toggle input { position: absolute; left: -9999px; }
  .lang-toggle label { cursor: pointer; color: var(--dim); border: 1px solid var(--dim);
    padding: 0.15rem 0.6rem; margin-right: 0.4rem; border-radius: 3px; user-select: none; }
  #lang-zh:checked ~ .lang-tabs label[for="lang-zh"],
  #lang-en:checked ~ .lang-tabs label[for="lang-en"] { color: var(--bg); background: var(--accent); border-color: var(--accent); }
  .narrative-zh, .narrative-en { display: none; }
  #lang-zh:checked ~ .narrative-zh { display: block; }
  #lang-en:checked ~ .narrative-en { display: block; }
"""


class ArchiveLink(NamedTuple):
    """導覽列一個存檔入口：日期 + 相對連結。"""

    date: str
    href: str


_INDEX_TEMPLATE = Template(
    """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Brief — {{ date }}</title>
<style>{{ shell_style }}</style>
</head>
<body>
<main>
<header>
  <p class="tagline">{{ positioning_line }}</p>
  <p class="meta">{{ date }}</p>
</header>
{% if tldr_html %}<section class="tldr">
{{ tldr_html }}
</section>{% endif %}
{% if narrative_zh_html or narrative_en_html %}<section class="narrative lang-toggle">
  <input type="radio" name="lang" id="lang-zh" checked>
  <input type="radio" name="lang" id="lang-en">
  <div class="lang-tabs">
    <label for="lang-zh">中</label><label for="lang-en">EN</label>
  </div>
  <div class="narrative-zh">
{{ narrative_zh_html }}
  </div>
  <div class="narrative-en">
{{ narrative_en_html }}
  </div>
</section>{% endif %}
<article>
{{ body_html }}
</article>
{% if archive_links %}<nav class="archive">
<p class="meta">存檔（連續 {{ archive_links|length }} 天）</p>
<ul>
{% for link in archive_links %}  <li><a href="{{ link.href }}">{{ link.date }}</a></li>
{% endfor %}</ul>
</nav>{% endif %}
</main>
</body>
</html>
"""
)

_ARCHIVE_TEMPLATE = Template(
    """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Brief 存檔 — {{ date }}</title>
<style>{{ shell_style }}</style>
</head>
<body>
<main>
<header>
  <p class="tagline">{{ positioning_line }}</p>
  <p class="meta">存檔日期：{{ date }}</p>
  <p class="meta"><a href="../index.html">← 回首頁</a></p>
</header>
<article>
{{ body_html }}
</article>
</main>
</body>
</html>
"""
)


def render_index(
    body_html: str,
    date: str,
    archive_links: Sequence[ArchiveLink] = (),
    narrative_zh_html: str = "",
    narrative_en_html: str = "",
    tldr_html: str = "",
) -> str:
    """渲染首頁 HTML：技術終端 shell 包住英文 TL;DR + 雙語敘事（EN／中 切換）+ 最新天內文 + 存檔導覽列。

    `tldr_html` 為已渲染消毒的當日英文 TL;DR HTML（空字串時不渲染該區段，向後相容）。
    `narrative_*_html` 為已渲染消毒的中英敘事 HTML（皆空時不渲染敘事區，向後相容）。
    """
    return _INDEX_TEMPLATE.render(
        body_html=body_html,
        date=date,
        positioning_line=POSITIONING_LINE,
        shell_style=_SHELL_STYLE,
        archive_links=list(archive_links),
        narrative_zh_html=narrative_zh_html,
        narrative_en_html=narrative_en_html,
        tldr_html=tldr_html,
    )


def render_archive(body_html: str, date: str) -> str:
    """渲染單天存檔頁：標示日期 + 回首頁連結，繁中內文。"""
    return _ARCHIVE_TEMPLATE.render(
        body_html=body_html,
        date=date,
        positioning_line=POSITIONING_LINE,
        shell_style=_SHELL_STYLE,
    )

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
  main { max-width: 1100px; margin: 0 auto; }
  header { border-bottom: 1px solid var(--dim); padding-bottom: 1rem; margin-bottom: 2rem; }
  .tagline { color: var(--accent); }
  a { color: var(--accent); }
  h1, h2, h3 { color: var(--fg); }
  code, pre { background: #11161d; color: var(--accent); }
  /* 報告表格：只讓「標題」(第一欄)與「備註」(最後一欄)兩個長文字欄限寬換行；
     表頭與數字/類別/子版等短欄維持自然寬度、不逐字硬斷。整體放不下時橫向捲動不破版。 */
  article { overflow-x: auto; }
  article table { border-collapse: collapse; margin: 1rem 0; }
  article th, article td {
    border: 1px solid var(--dim); padding: 0.4rem 0.6rem;
    text-align: left; vertical-align: top;
  }
  article th { color: var(--accent); white-space: nowrap; }
  article td:first-child { max-width: 30ch; overflow-wrap: break-word; }
  article td:last-child { max-width: 24ch; overflow-wrap: break-word; }
  .meta { color: var(--dim); }
  nav.archive { margin-top: 2rem; border-top: 1px solid var(--dim); padding-top: 1rem; }
  nav.archive ul { list-style: none; padding: 0; }
  nav.archive li { margin: 0.25rem 0; }
  /* Hero 排：左側「關於本專案」按鈕 + 定位句。專案描述不直接顯示，收進 overlay。 */
  .hero-row { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
  .about-btn { cursor: pointer; color: var(--accent); border: 1px solid var(--dim);
    padding: 0.15rem 0.7rem; border-radius: 3px; user-select: none; white-space: nowrap; }
  .about-btn:hover { border-color: var(--accent); }
  /* 純 CSS overlay（無 JS）：隱藏 checkbox，label 當開關，:checked 顯示彈窗；背景 label 可關。 */
  .about-checkbox { position: absolute; left: -9999px; }
  .about-overlay { display: none; position: fixed; inset: 0; z-index: 100; }
  .about-checkbox:checked ~ .about-overlay { display: block; }
  .about-backdrop { position: absolute; inset: 0; background: rgba(0, 0, 0, 0.75); }
  .about-panel { position: relative; max-width: 720px; margin: 6vh auto; max-height: 84vh;
    overflow-y: auto; background: var(--bg); border: 1px solid var(--dim);
    border-radius: 4px; padding: 1.5rem 2rem; }
  .about-close { position: absolute; top: 0.5rem; right: 0.9rem; cursor: pointer;
    color: var(--dim); font-size: 1.2rem; line-height: 1; text-decoration: none; }
  .about-close:hover { color: var(--accent); }
  /* system status block: hand-written CSS, terminal aesthetic; trend is inline SVG (no chart lib). */
  section.status { margin-bottom: 2rem; border-bottom: 1px solid var(--dim); padding-bottom: 1rem; }
  section.status h2 { color: var(--accent); font-size: 1rem; letter-spacing: 0.05em; }
  .status-grid { display: flex; flex-wrap: wrap; gap: 2rem; align-items: flex-end; }
  .status-streak { display: flex; flex-direction: column; }
  .status-num { color: var(--accent); font-size: 2.4rem; line-height: 1; }
  .status-label { color: var(--dim); font-size: 0.8rem; }
  .status-trend { display: flex; flex-direction: column; flex: 1 1 240px; min-width: 200px; }
  svg.spark { color: var(--accent); width: 100%; height: 40px; margin-top: 0.3rem; }
  .status-rates { list-style: none; padding: 0; margin: 1rem 0 0;
    display: flex; flex-wrap: wrap; gap: 0.4rem 1.2rem; }
  .status-rates li { display: flex; gap: 0.5rem; align-items: baseline; }
  .status-src { color: var(--fg); }
  .status-pct { color: var(--accent); }
  .status-frac { color: var(--dim); font-size: 0.8rem; }
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
{% if narrative_html %}<input type="checkbox" id="about-toggle" class="about-checkbox">{% endif %}
<header>
  <div class="hero-row">
{% if narrative_html %}    <label for="about-toggle" class="about-btn">關於本專案</label>{% endif %}
    <p class="tagline">{{ positioning_line }}</p>
  </div>
  <p class="meta">{{ date }}</p>
</header>
{% if status_html %}{{ status_html }}{% endif %}
<article>
{{ body_html }}
</article>
{% if archive_links %}<nav class="archive">
<p class="meta">存檔（連續 {{ archive_links|length }} 天）</p>
<ul>
{% for link in archive_links %}  <li><a href="{{ link.href }}">{{ link.date }}</a></li>
{% endfor %}</ul>
</nav>{% endif %}
{% if narrative_html %}<div class="about-overlay">
  <label for="about-toggle" class="about-backdrop"></label>
  <div class="about-panel">
    <label for="about-toggle" class="about-close" aria-label="關閉">✕</label>
{{ narrative_html }}
  </div>
</div>{% endif %}
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
    narrative_html: str = "",
    status_html: str = "",
) -> str:
    """渲染首頁 HTML：技術終端 shell 包住系統狀態區 + 最新天內文 + 存檔導覽列。

    `status_html` 為已渲染的系統狀態區 HTML（連續天數 + judge sparkline + 來源成功率；
    空字串時不渲染該區段，向後相容 #6/#7/#8/#9）。
    `narrative_html` 為已渲染消毒的專案描述 HTML（繁中）；非空時 hero 排顯示「關於本專案」
    按鈕，點擊彈出 overlay 呈現，不直接顯示在頁面主流程（空字串時不渲染按鈕與 overlay）。
    """
    return _INDEX_TEMPLATE.render(
        body_html=body_html,
        date=date,
        positioning_line=POSITIONING_LINE,
        shell_style=_SHELL_STYLE,
        archive_links=list(archive_links),
        narrative_html=narrative_html,
        status_html=status_html,
    )


def render_archive(body_html: str, date: str) -> str:
    """渲染單天存檔頁：標示日期 + 回首頁連結，繁中內文。"""
    return _ARCHIVE_TEMPLATE.render(
        body_html=body_html,
        date=date,
        positioning_line=POSITIONING_LINE,
        shell_style=_SHELL_STYLE,
    )

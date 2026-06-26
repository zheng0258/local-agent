"""site_builder.status — 純函數：judge/health 歷史 → 系統狀態 DTO + inline SVG。

「系統狀態」區展現系統被工程化、有 instrumentation：連續運作天數、judge 品質分隨
時間的趨勢（inline SVG sparkline）、各來源成功率。純記憶體：吃**已解析**的歷史
list（list[dict]），不碰 git / LLM / 網路 / 檔案。薄 loader (load_status) 才落盤讀取。

不引入圖表庫／前端框架：sparkline 為手建 inline SVG 字串，樣式手寫 CSS（樣式住
template.py，與 shell 終端風一致）。歷史缺失／為空 → compute_status 回 None，呼叫端
略過狀態區，絕不報錯。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Optional, Sequence, Tuple

# judge/health 歷史每列共用的日期格式（與 health.py 一致）。
_DATE_FMT = "%Y-%m-%d"

OK = "ok"

# sparkline SVG 尺寸（viewBox 座標；CSS 控實際顯示寬高）。
_SPARK_W = 240
_SPARK_H = 40
_SPARK_PAD = 4
# judge overall 分數理論範圍（固定軸，跨天可比；不隨資料縮放）。
_SCORE_MIN = 0.0
_SCORE_MAX = 5.0


@dataclass(frozen=True)
class SourceRate:
    """單一來源的成功率：出現次數中 ok 的比例（0.0 ~ 1.0）。"""

    source: str
    rate: float
    ok: int
    total: int


@dataclass(frozen=True)
class SystemStatus:
    """系統狀態區的衍生指標（純資料，已脫離歷史原始 JSON）。

    - streak_days：連到最新一天為止的連續運作日曆天數
    - judge_series：judge overall 分數，依日期由舊到新（sparkline 用）
    - source_rates：各來源成功率（依來源名排序，呈現穩定）
    """

    streak_days: int
    judge_series: Tuple[float, ...]
    source_rates: Tuple[SourceRate, ...]


def _parse_date(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, _DATE_FMT)
    except ValueError:
        return None


def _judge_series(judge_history: Sequence[object]) -> Tuple[float, ...]:
    """judge overall 分數，依日期由舊到新。缺 overall／非 dict 列跳過。"""
    rows: list[tuple[datetime, float]] = []
    for item in judge_history:
        if not isinstance(item, Mapping):
            continue
        when = _parse_date(item.get("date"))
        overall = item.get("overall")
        if when is None or not isinstance(overall, (int, float)):
            continue
        rows.append((when, float(overall)))
    rows.sort(key=lambda pair: pair[0])
    return tuple(score for _, score in rows)


def _run_dates(health_history: Sequence[object]) -> list[datetime]:
    """health 歷史中所有可解析的運作日（去重、升冪）。"""
    seen: set[datetime] = set()
    for item in health_history:
        if not isinstance(item, Mapping):
            continue
        when = _parse_date(item.get("date"))
        if when is not None:
            seen.add(when)
    return sorted(seen)


def _streak_days(dates: Sequence[datetime]) -> int:
    """連到最新一天為止的連續日曆天數。空 → 0。"""
    if not dates:
        return 0
    streak = 1
    for earlier, later in zip(reversed(dates[:-1]), reversed(dates[1:])):
        if (later - earlier).days == 1:
            streak += 1
        else:
            break
    return streak


def _source_rates(health_history: Sequence[object]) -> Tuple[SourceRate, ...]:
    """各來源 ok 次數 / 出現次數。依來源名排序，呈現穩定。"""
    ok_counts: dict[str, int] = {}
    totals: dict[str, int] = {}
    for item in health_history:
        if not isinstance(item, Mapping):
            continue
        results = item.get("results")
        if not isinstance(results, Mapping):
            continue
        for source, outcome in results.items():
            key = str(source)
            totals[key] = totals.get(key, 0) + 1
            if outcome == OK:
                ok_counts[key] = ok_counts.get(key, 0) + 1
    rates = [
        SourceRate(
            source=src,
            rate=ok_counts.get(src, 0) / total,
            ok=ok_counts.get(src, 0),
            total=total,
        )
        for src, total in totals.items()
    ]
    rates.sort(key=lambda r: r.source)
    return tuple(rates)


def compute_status(
    judge_history: Sequence[object],
    health_history: Sequence[object],
) -> Optional[SystemStatus]:
    """純函數：已解析的 judge/health 歷史 → SystemStatus（兩者皆空 → None）。

    對畸形列（非 dict、缺欄位）寬容跳過，絕不報錯。
    """
    series = _judge_series(judge_history)
    dates = _run_dates(health_history)
    rates = _source_rates(health_history)
    if not series and not dates and not rates:
        return None
    return SystemStatus(
        streak_days=_streak_days(dates),
        judge_series=series,
        source_rates=rates,
    )


def render_sparkline_svg(series: Sequence[float]) -> str:
    """judge 品質分趨勢 → 手建 inline SVG sparkline（無圖表庫）。

    固定 0~5 軸（跨天可比）；單點不除以零。空序列回空 SVG（仍合法）。
    """
    inner_w = _SPARK_W - 2 * _SPARK_PAD
    inner_h = _SPARK_H - 2 * _SPARK_PAD
    span = _SCORE_MAX - _SCORE_MIN

    def _y(score: float) -> float:
        clamped = max(_SCORE_MIN, min(_SCORE_MAX, score))
        # 高分在上：分數越高 y 越小
        return _SPARK_PAD + inner_h * (1 - (clamped - _SCORE_MIN) / span)

    points: list[str] = []
    n = len(series)
    for i, score in enumerate(series):
        x = _SPARK_PAD + (inner_w * (i / (n - 1)) if n > 1 else inner_w / 2)
        points.append(f"{x:.1f},{_y(score):.1f}")
    polyline = (
        f'<polyline fill="none" stroke="currentColor" stroke-width="2" '
        f'points="{" ".join(points)}"/>'
        if points
        else ""
    )
    last_dot = ""
    if points:
        lx, ly = points[-1].split(",")
        last_dot = f'<circle cx="{lx}" cy="{ly}" r="2.5" fill="currentColor"/>'
    return (
        f'<svg class="spark" viewBox="0 0 {_SPARK_W} {_SPARK_H}" '
        f'role="img" aria-label="judge quality trend" '
        f'preserveAspectRatio="none">{polyline}{last_dot}</svg>'
    )


def render_status_section(status: SystemStatus) -> str:
    """系統狀態區 HTML：連續天數 + judge sparkline + 各來源成功率。

    手寫 markup（樣式類別住 template.py 的 shell CSS，終端風一致）。
    """
    spark = render_sparkline_svg(status.judge_series)
    latest = f"{status.judge_series[-1]:.1f}" if status.judge_series else "—"
    rate_lines = "".join(
        f'<li><span class="status-src">{r.source}</span>'
        f'<span class="status-pct">{r.rate * 100:.0f}%</span>'
        f'<span class="status-frac">{r.ok}/{r.total}</span></li>'
        for r in status.source_rates
    )
    return (
        '<section class="status">'
        "<h2>系統狀態</h2>"
        '<div class="status-grid">'
        '<div class="status-streak">'
        f'<span class="status-num">{status.streak_days}</span>'
        '<span class="status-label">連續運作天數</span>'
        "</div>"
        '<div class="status-trend">'
        f'<span class="status-label">judge 品質分趨勢（最新 {latest}/5）</span>'
        f"{spark}"
        "</div>"
        "</div>"
        '<ul class="status-rates">'
        f"{rate_lines}"
        "</ul>"
        "</section>"
    )

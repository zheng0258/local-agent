"""品質訊號：digest 來源貢獻度 + judge 分數飽和偵測。

這兩個觀測概念與「健康記錄 / 慢性故障」（health.py）不同——它們關乎**產出品質**
而非遞送成敗，只是恰好都在 `--health` 表露臉。原先與 health 記錄擠在同一檔，
拆出後各自 cohesion 更清楚；render 端（health.render_health_table）再組合兩者。

純函數（跨天 roll-up）+ 薄 I/O（load_*，接受顯式路徑以利測試）。不 import health，
維持單向依賴（health → quality_signals）。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping, Sequence

from tools.history_schema import JudgeHistoryRecord, days_between

from .config import OUTPUT_DIR

# ── Digest 貢獻度 ─────────────────────────────────────────────────

# digest 貢獻度統計的滑動視窗（日曆天）
DIGEST_SHARE_WINDOW_DAYS = 30


def digest_source_shares(artifacts: Sequence[Mapping]) -> dict[str, float]:
    """統計各來源在最終 digest 條目中的占比（0.0–1.0）。純函數。

    輸入為多日 digest artifact（`{"digests": [{..., "_source": key}, ...]}`）；
    缺 `_source` 的條目（舊 schema）與形狀異常的 artifact 靜默略過。
    """
    counts: Counter[str] = Counter()
    for artifact in artifacts:
        digests = artifact.get("digests") if isinstance(artifact, Mapping) else None
        if not isinstance(digests, list):
            continue
        for entry in digests:
            if not isinstance(entry, Mapping):
                continue
            source = entry.get("_source")
            if isinstance(source, str) and source:
                counts[source] += 1
    total = sum(counts.values())
    if total == 0:
        return {}
    return {source: count / total for source, count in counts.items()}


def load_recent_digests(
    output_dir: Path, end_date: str, window: int = DIGEST_SHARE_WINDOW_DAYS
) -> list[dict]:
    """讀取近 window 個日曆天（含 end_date）的 digest artifact。純讀檔，不寫。

    缺檔或壞檔的日子靜默略過。
    """
    end = datetime.strptime(end_date, "%Y-%m-%d")
    artifacts: list[dict] = []
    for offset in range(window):
        day = (end - timedelta(days=offset)).strftime("%Y-%m-%d")
        digest_file = output_dir / day / "steps" / "digest.json"
        if not digest_file.exists():
            continue
        try:
            data = json.loads(digest_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            artifacts.append(data)
    return artifacts


# ── Judge 飽和偵測 ────────────────────────────────────────────────
#
# LLM-as-Judge 的分數若長期貼頂（quality_alert 只在 completeness < 3 觸發，
# 而歷史 overall 從未低於 4.0），儀表就失去鑑別力卻沒人知道。
# 比照慢性故障：純函數跨天 roll-up，只在 --health 加註警示，不動 judge step。

JUDGE_SATURATION_WINDOW_DAYS = 30
# 資料不足門檻：視窗內記錄少於此數即不判定（避免小樣本誤報）
JUDGE_SATURATION_MIN_RECORDS = 30
# 「貼頂」的 overall 下限：1–5 分制的次高分
JUDGE_SATURATION_SCORE_FLOOR = 4.0
# 貼頂天數占比 ≥ 此值即視為飽和
JUDGE_SATURATION_RATIO = 0.9

JUDGE_HISTORY_FILE = OUTPUT_DIR / "_judge-history.json"


@dataclass(frozen=True)
class JudgeSaturationFinding:
    """judge 分數飽和的判定結果（含近 N 天分數分佈摘要）。"""

    window_days: int                    # 實際檢視的記錄數
    saturated_days: int                 # overall ≥ score_floor 的天數
    score_floor: float
    min_overall: float
    max_overall: float
    distribution: Mapping[float, int]   # overall 分數 → 天數


def detect_judge_saturation(
    history: Sequence[Mapping],
    window: int = JUDGE_SATURATION_WINDOW_DAYS,
    min_records: int = JUDGE_SATURATION_MIN_RECORDS,
    score_floor: float = JUDGE_SATURATION_SCORE_FLOOR,
    ratio: float = JUDGE_SATURATION_RATIO,
) -> JudgeSaturationFinding | None:
    """近 window 個日曆天內，overall ≥ score_floor 的天數占比 ≥ ratio 即飽和。

    輸入形狀鏡像 `_judge-history.json`（每筆含 "date" 與 "overall"）。
    視窗內記錄不足 min_records 筆視為資料不足，回傳 None 不誤報；
    未飽和亦回傳 None。純函數，不讀檔。
    """
    overalls = _recent_judge_overalls(history, window)
    if len(overalls) < min_records:
        return None
    saturated = [o for o in overalls if o >= score_floor]
    if len(saturated) / len(overalls) < ratio:
        return None
    return JudgeSaturationFinding(
        window_days=len(overalls),
        saturated_days=len(saturated),
        score_floor=score_floor,
        min_overall=min(overalls),
        max_overall=max(overalls),
        distribution=dict(sorted(Counter(overalls).items())),
    )


def load_judge_history(history_file: Path) -> list[dict]:
    """讀 judge 歷史檔（形狀同 `_judge-history.json`）。缺檔或壞檔回傳空 list。"""
    if not history_file.exists():
        return []
    try:
        raw = json.loads(history_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def _recent_judge_overalls(history: Sequence[Mapping], window: int) -> list[float]:
    """取最新記錄日往前 window 個日曆天內的 overall 值（形狀異常的記錄略過）。"""
    dated: list[tuple[str, float]] = []
    for item in history:
        rec = JudgeHistoryRecord.from_dict(item) if isinstance(item, Mapping) else None
        if rec is None or not rec.date or rec.overall is None:
            continue
        dated.append((rec.date, float(rec.overall)))
    if not dated:
        return []
    dated.sort(key=lambda pair: pair[0])
    latest = dated[-1][0]
    return [o for d, o in dated if 0 <= days_between(d, latest) < window]


def format_judge_saturation(finding: JudgeSaturationFinding) -> str:
    """judge 飽和警示行：貼頂占比 + 分數分佈摘要 + 建議。"""
    dist = " / ".join(
        f"{score:.1f}×{count}" for score, count in finding.distribution.items()
    )
    return (
        f"  ⚠️ judge 已失去鑑別力：近 {finding.window_days} 天有 "
        f"{finding.saturated_days}/{finding.window_days} 天 overall ≥ "
        f"{finding.score_floor:.1f}（分佈 {dist}）\n"
        f"     ↳ 建議：更換 judge 模型（JUDGE_LLM_MODEL）或收緊評分 rubric"
    )

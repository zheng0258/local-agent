"""site_builder.runs — 純函數：judge / health / usage / run-manifest 歷史 → 運行紀錄。

「運行紀錄」把每一次 pipeline 執行當成一等公民（CI 執行史模型）：一列一天，
彙整該次的整體狀態、各 subject 成敗、judge 品質分、token 用量、耗時與觸發源。
純記憶體：吃**已解析**的四份歷史 list（list[dict]），不碰 git / LLM / 網路 / 檔案。
薄 loader (load_runs) 才落盤讀取，再委派此處的 compute_runs。

狀態語義（run_status）：pipeline 有 ≥2 來源門檻的韌性，故：
  - failed：來源有記錄但成功 < 2（brief 無法成形）
  - partial：≥2 來源成功、但任一 subject（來源或遞送）失敗（降級但有產出）
  - success：所有記錄到的 subject 皆 ok
  - unknown：當天無 health 記錄（無從判定）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence, Tuple

from tools.history_schema import (
    OK,
    HealthHistoryRecord,
    JudgeHistoryRecord,
)

# 顯示順序：5 來源 + 3 遞送。單字母標籤供狀態矩陣的小格顯示。
SOURCES: Tuple[str, ...] = ("hatena", "hn", "reddit", "security", "rss")
DELIVERIES: Tuple[str, ...] = ("telegram", "vault", "deploy")
SUBJECTS: Tuple[str, ...] = (*SOURCES, *DELIVERIES)
SUBJECT_LABELS: Mapping[str, str] = {
    "hatena": "H",
    "hn": "N",
    "reddit": "R",
    "security": "S",
    "rss": "F",
    "telegram": "T",
    "vault": "V",
    "deploy": "D",
}

# 來源門檻（與 pipeline 的 _fetch_sources ≥2 韌性門檻一致）。
_MIN_SOURCES = 2


@dataclass(frozen=True)
class StepTiming:
    """單一步驟在某次 run 的耗時與結果（來自 run manifest）。"""

    name: str
    status: str
    duration_seconds: float


@dataclass(frozen=True)
class RunRecord:
    """單日一次 run 的彙整檢視（純資料，已脫離各歷史原始 JSON）。

    health/judge/usage 三份歷史至少一份有該日期即成一列；缺席的欄位為 None，
    呼叫端（模板）優雅降級。manifest 缺席時 duration/trigger/git_sha/steps 皆空。
    """

    date: str
    results: Mapping[str, str]  # subject → "ok" 或 ErrorClass 值（缺 health → {}）
    overall: Optional[float]  # judge overall（缺 → None）
    tokens_total: Optional[int]
    calls: Optional[int]
    duration_seconds: Optional[float]
    trigger: Optional[str]
    git_sha: Optional[str]
    steps: Tuple[StepTiming, ...] = field(default_factory=tuple)

    @property
    def status(self) -> str:
        return run_status(self.results)


def run_status(results: Mapping[str, str]) -> str:
    """依 subject 結果推導整體狀態（見模組 docstring 的語義）。"""
    if not results:
        return "unknown"
    present_sources = [s for s in SOURCES if s in results]
    ok_sources = sum(1 for s in present_sources if results.get(s) == OK)
    if present_sources and ok_sources < _MIN_SOURCES:
        return "failed"
    if all(v == OK for v in results.values()):
        return "success"
    return "partial"


def _index_by_date(history: Sequence[object]) -> dict[str, dict]:
    """把一份扁平歷史 list 依 date 建索引（畸形列跳過；同日後者覆寫）。"""
    out: dict[str, dict] = {}
    for item in history:
        if isinstance(item, dict):
            date = str(item.get("date", ""))
            if date:
                out[date] = item
    return out


def _num(value: object) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _int(value: object) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _steps_from_manifest(manifest: dict) -> Tuple[StepTiming, ...]:
    raw = manifest.get("steps", {})
    if not isinstance(raw, Mapping):
        return ()
    timings: list[StepTiming] = []
    for name, info in raw.items():
        if not isinstance(info, Mapping):
            continue
        timings.append(
            StepTiming(
                name=str(name),
                status=str(info.get("status", "")),
                duration_seconds=float(_num(info.get("duration_seconds")) or 0.0),
            )
        )
    return tuple(timings)


def compute_runs(
    judge_history: Sequence[object],
    health_history: Sequence[object],
    usage_history: Sequence[object] = (),
    run_manifests: Sequence[object] = (),
) -> Tuple[RunRecord, ...]:
    """純函數：四份已解析歷史 → RunRecord 串（newest first）。

    以「所有出現過的日期」為列；每列從各歷史依日期取值。對畸形列寬容跳過，絕不報錯。
    """
    judge_idx = _index_by_date(judge_history)
    health_idx = _index_by_date(health_history)
    usage_idx = _index_by_date(usage_history)
    manifest_idx = _index_by_date(run_manifests)

    all_dates = set(judge_idx) | set(health_idx) | set(usage_idx) | set(manifest_idx)

    runs: list[RunRecord] = []
    for date in sorted(all_dates, reverse=True):
        health = HealthHistoryRecord.from_dict(health_idx.get(date, {}))
        judge = JudgeHistoryRecord.from_dict(judge_idx.get(date, {}))
        usage = usage_idx.get(date, {})
        manifest = manifest_idx.get(date, {})
        runs.append(
            RunRecord(
                date=date,
                results=health.results,
                overall=judge.overall if date in judge_idx else None,
                tokens_total=_int(usage.get("total_tokens")),
                calls=_int(usage.get("calls")),
                duration_seconds=_num(manifest.get("duration_seconds")),
                trigger=(
                    str(manifest.get("trigger")) if manifest.get("trigger") else None
                ),
                git_sha=(
                    str(manifest.get("git_sha")) if manifest.get("git_sha") else None
                ),
                steps=_steps_from_manifest(manifest),
            )
        )
    return tuple(runs)

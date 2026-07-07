"""Daily Brief 可觀測性：每日健康記錄 + 慢性故障偵測。

設計主軸是「可觀測性」：系統有韌性（≥2 來源門檻撐過部分失敗），但會默默降級。
本模組讓「健康狀態」可見、可查詢，並把每天各自獨立的 alert **跨天 roll-up**，
區分 transient flake（雜訊）與 chronic 故障（訊號），只在後者主動打擾。

形狀鏡像 `_judge-history.json`：扁平的每日記錄 list，每次執行 append 一筆。
邏輯（分類、慢性判定、render）皆為純函數可獨立測試；I/O 集中在薄薄的
load/append/escalate 函式，全部接受顯式路徑參數以利測試注入。

詞彙見 CONTEXT.md「系統訊號」：Health Record / 慢性故障 / Alert。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

from .config import OUTPUT_DIR

# ── 常數 ─────────────────────────────────────────────────────────

SOURCES: tuple[str, ...] = ("hatena", "hn", "reddit", "security", "rss")
DELIVERIES: tuple[str, ...] = ("telegram", "vault")
SUBJECTS: tuple[str, ...] = (*SOURCES, *DELIVERIES)

# 慢性故障判定：滑動視窗 N 天內，同一 subject 失敗 ≥ M 次即視為 chronic
CHRONIC_WINDOW_DAYS = 7
CHRONIC_FAIL_THRESHOLD = 3

OK = "ok"

HEALTH_HISTORY_FILE = OUTPUT_DIR / "_health-history.json"
ESCALATION_STATE_FILE = OUTPUT_DIR / "_health-escalated.json"


class ErrorClass(str, Enum):
    """失敗的錯誤型別。chronic escalation 據此給出針對性的修復建議。"""

    NETWORK = "network"            # connection refused：多為模型/服務啟動時序
    UPSTREAM_HTTP = "upstream_http"  # HTTP 4xx/5xx：上游端點問題
    EMPTY_LLM = "empty_llm"        # 本地模型吐空字串
    PARSE = "parse"               # LLM 輸出無法解析為合法 JSON
    OTHER = "other"               # 環境 / 程式 / 遞送等其他


_SUGGESTIONS: Mapping[str, str] = {
    ErrorClass.NETWORK.value: "啟動時序問題 — 檢查 load_model.py 與 cron 兩段排程的間隔",
    ErrorClass.UPSTREAM_HTTP.value: "上游持續回錯 — 確認來源端點仍有效，或需更新 URL / header",
    ErrorClass.EMPTY_LLM.value: "本地模型反覆吐空 — 檢查模型載入狀態或調整 prompt / temperature",
    ErrorClass.PARSE.value: "LLM 輸出格式持續不合 — 強化 prompt 或 parse fallback",
    ErrorClass.OTHER.value: "環境或程式問題 — 檢視該 subject 近期的 alert 內容",
}

# alerts.json 的 step 名稱 → health subject（遞送步驟改名對齊使用者視角）
_ALERT_STEP_TO_SUBJECT: Mapping[str, str] = {"notify": "telegram", "save": "vault"}


# ── 錯誤分類 ─────────────────────────────────────────────────────


def classify_error(error: str) -> ErrorClass:
    """把 alert 的自由文字 error 訊息歸進一個 ErrorClass（順序敏感）。"""
    text = error or ""
    low = text.lower()
    if "connection refused" in low or "errno 61" in low or "errno 111" in low:
        return ErrorClass.NETWORK
    if "http error" in low:
        return ErrorClass.UPSTREAM_HTTP
    if "urlopen error" in low:
        return ErrorClass.NETWORK
    if "parse_llm_json" in low or "無法解析" in text or "json" in low:
        # 空字串輸出 vs 格式錯誤
        if "''" in text or '""' in text or "空" in text:
            return ErrorClass.EMPTY_LLM
        return ErrorClass.PARSE
    return ErrorClass.OTHER


# ── 每日健康記錄 ──────────────────────────────────────────────────


@dataclass(frozen=True)
class HealthRecord:
    """單日的健康記錄：subject → 結果（"ok" 或失敗的 ErrorClass 值）。"""

    date: str
    results: Mapping[str, str]

    def failures(self) -> Mapping[str, str]:
        return {s: r for s, r in self.results.items() if r != OK}

    def to_dict(self) -> dict:
        return {"date": self.date, "results": dict(self.results)}

    @classmethod
    def from_dict(cls, data: Mapping) -> "HealthRecord":
        results = data.get("results", {})
        return cls(
            date=str(data.get("date", "")),
            results={str(k): str(v) for k, v in results.items()} if isinstance(results, dict) else {},
        )


def _subject_outcome(artifact: Path, alert: object) -> str | None:
    """單一 subject 的結果：失敗（alert）優先於成功（artifact 存在），皆無則 None（未執行）。"""
    if isinstance(alert, dict):
        return classify_error(str(alert.get("error", ""))).value
    if isinstance(alert, str):  # 異常的 alert（值為時間戳）仍記為失敗
        return ErrorClass.OTHER.value
    if artifact.exists():
        return OK
    return None


def observe_run(today: str, day_dir: Path, steps_dir: Path) -> HealthRecord:
    """檢視一次執行的產物，推導每個 subject 的結果。純讀檔，不寫。"""
    alerts = _load_alerts(steps_dir)
    candidates: dict[str, str | None] = {}
    for src in SOURCES:
        candidates[src] = _subject_outcome(steps_dir / f"{src}.json", alerts.get(src))
    candidates["telegram"] = _subject_outcome(day_dir / "telegram.done", alerts.get("notify"))
    candidates["vault"] = _subject_outcome(day_dir / "vault.done", alerts.get("save"))
    results = {s: r for s, r in candidates.items() if r is not None}
    return HealthRecord(date=today, results=results)


def _load_alerts(steps_dir: Path) -> dict:
    alerts_file = steps_dir / "alerts.json"
    if not alerts_file.exists():
        return {}
    try:
        data = json.loads(alerts_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


# ── 歷史記錄持久化 ────────────────────────────────────────────────


def load_history(history_file: Path) -> list[HealthRecord]:
    if not history_file.exists():
        return []
    try:
        raw = json.loads(history_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [HealthRecord.from_dict(d) for d in raw if isinstance(d, dict)]


def append_record(record: HealthRecord, history_file: Path) -> list[HealthRecord]:
    """append 一筆健康記錄（同日重跑則替換），回傳排序後的完整歷史。"""
    history = [r for r in load_history(history_file) if r.date != record.date]
    history.append(record)
    history.sort(key=lambda r: r.date)
    history_file.parent.mkdir(parents=True, exist_ok=True)
    history_file.write_text(
        json.dumps([r.to_dict() for r in history], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return history


# ── 慢性故障偵測 ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ChronicFinding:
    subject: str
    fail_count: int
    window_days: int
    dominant_class: str
    suggestion: str


def detect_chronic(
    history: Sequence[HealthRecord],
    window: int = CHRONIC_WINDOW_DAYS,
    threshold: int = CHRONIC_FAIL_THRESHOLD,
) -> list[ChronicFinding]:
    """近 window 個日曆天內，同一 subject 失敗 ≥ threshold 次即為 chronic。

    用日曆天而非記錄數：cron 漏跑時不會往回多撈舊記錄。
    """
    recent = _recent_by_days(history, window)
    findings: list[ChronicFinding] = []
    for subject in SUBJECTS:
        classes = [
            r.results[subject]
            for r in recent
            if subject in r.results and r.results[subject] != OK
        ]
        if len(classes) >= threshold:
            dominant = Counter(classes).most_common(1)[0][0]
            findings.append(
                ChronicFinding(
                    subject=subject,
                    fail_count=len(classes),
                    window_days=len(recent),
                    dominant_class=dominant,
                    suggestion=_SUGGESTIONS.get(dominant, _SUGGESTIONS[ErrorClass.OTHER.value]),
                )
            )
    return findings


# ── Escalation 去重（同一 chronic episode 只打擾一次）─────────────────


def _load_escalation_state(state_file: Path) -> dict[str, str]:
    if not state_file.exists():
        return {}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _days_between(earlier: str, later: str) -> int:
    fmt = "%Y-%m-%d"
    return (datetime.strptime(later, fmt) - datetime.strptime(earlier, fmt)).days


def _recent_by_days(history: Sequence[HealthRecord], window: int) -> list[HealthRecord]:
    """回傳最新記錄日往前 window-1 天（含當天，共 window 天）內的記錄。"""
    ordered = sorted(history, key=lambda r: r.date)
    if not ordered:
        return []
    latest = ordered[-1].date
    return [r for r in ordered if 0 <= _days_between(r.date, latest) < window]


def filter_new_escalations(
    findings: Sequence[ChronicFinding],
    state_file: Path,
    today: str,
    window: int = CHRONIC_WINDOW_DAYS,
) -> list[ChronicFinding]:
    """過濾掉 window 天內已 escalate 過的 subject，避免每天重複打擾。"""
    state = _load_escalation_state(state_file)
    fresh: list[ChronicFinding] = []
    for finding in findings:
        last = state.get(finding.subject)
        if last is None or _days_between(last, today) >= window:
            fresh.append(finding)
    return fresh


def record_escalations(
    findings: Sequence[ChronicFinding], state_file: Path, today: str
) -> None:
    state = _load_escalation_state(state_file)
    for finding in findings:
        state[finding.subject] = today
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


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


# ── Render ───────────────────────────────────────────────────────


def format_escalation(findings: Sequence[ChronicFinding], today: str) -> str:
    """慢性故障的 Telegram 推播文字（HTML parse_mode，只用允許的 tag）。"""
    lines = [f"⚠️ Daily Brief 慢性故障偵測（{today}）", ""]
    for finding in findings:
        lines.append(
            f"• <b>{finding.subject}</b>：近 {finding.window_days} 天失敗 "
            f"{finding.fail_count} 次（主要：{finding.dominant_class}）"
        )
        lines.append(f"  ↳ {finding.suggestion}")
    return "\n".join(lines)


def render_health_table(
    history: Sequence[HealthRecord],
    window: int = CHRONIC_WINDOW_DAYS,
    digest_shares: Mapping[str, float] | None = None,
) -> str:
    """pull 查詢用：印出近 window 天各 subject 的成功率表（純文字）。

    給定 digest_shares 時，來源列附上近 DIGEST_SHARE_WINDOW_DAYS 天的
    digest 條目占比欄（遞送 subject 無此欄）。
    """
    recent = _recent_by_days(history, window)
    if not recent:
        return "（尚無健康記錄）"
    title = f"Daily Brief 健康狀態（近 {len(recent)} 天，{recent[0].date} ~ {recent[-1].date}）"
    if digest_shares:
        title += f"；digest 欄 = 近 {DIGEST_SHARE_WINDOW_DAYS} 天 digest 條目占比"
    lines = [title, ""]
    for subject in SUBJECTS:
        total = sum(1 for r in recent if subject in r.results)
        if total == 0:
            continue
        ok = sum(1 for r in recent if r.results.get(subject) == OK)
        fails = [
            r.results[subject]
            for r in recent
            if subject in r.results and r.results[subject] != OK
        ]
        share = ""
        if digest_shares and subject in digest_shares:
            share = f"  digest {digest_shares[subject] * 100:.0f}%"
        suffix = f"  ⚠️ {Counter(fails).most_common(1)[0][0]}" if fails else ""
        lines.append(
            f"  {subject:9} {ok:>2}/{total:<2}  {ok / total * 100:5.1f}%{share}{suffix}"
        )
    return "\n".join(lines)

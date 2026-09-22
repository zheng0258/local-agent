"""Token 用量追蹤：LLM 呼叫的 usage 累加器 + 純函數 roll-up。

設計（鏡射 health.py 的可觀測性紀律）：
- UsageMeter 是「帳本邊界」——全模組唯一可變處，鏡射 LM Studio 每次回應的 usage。
  LocalLLMBackend 在每次 complete() 後呼叫 record()；current_step 由 Step.run 設定，
  使每筆用量歸到當時執行的步驟（enrich 的並行 thread 皆歸 "enrich"）。
- UsageEvent 為 frozen；totals / by_step / by_model 為純函數 roll-up。
- 與 Step 解耦：pipeline 結尾一次落盤，包在 try/except，絕不反噬 pipeline。

on-disk 形狀（steps/_usage.json）：
    {"date", "totals": {...}, "by_step": {name: {...}}, "by_model": {model: {...}}}
跨天歷史（_usage-history.json，形狀鏡射 _judge-history.json）：
    [{"date", "calls", "prompt_tokens", "completion_tokens", "total_tokens", "by_model"}]
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

_OTHER_STEP = "other"


@dataclass(frozen=True)
class UsageEvent:
    """單次 LLM 呼叫的 token 用量（歸屬於執行當下的 step + model）。"""

    step: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


def _usage_ints(usage: dict) -> tuple[int, int, int]:
    """從 LM Studio 回應的 usage 物件抽出三個整數，缺 total 時以 prompt+completion 補。"""
    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion = int(usage.get("completion_tokens", 0) or 0)
    total = int(usage.get("total_tokens", 0) or 0)
    if total == 0:
        total = prompt + completion
    return prompt, completion, total


class UsageMeter:
    """跨步驟共用的 token 帳本（本模組唯一可變邊界）；append thread-safe。"""

    def __init__(self) -> None:
        self.current_step = ""
        self._events: list[UsageEvent] = []
        self._lock = threading.Lock()

    def record(self, model: str, usage: dict | None) -> None:
        """記一筆用量（歸到 current_step）。usage 缺失或全零則靜默略過。"""
        if not usage:
            return
        prompt, completion, total = _usage_ints(usage)
        if total == 0:
            return
        event = UsageEvent(
            step=self.current_step or _OTHER_STEP,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        )
        with self._lock:
            self._events.append(event)

    @property
    def events(self) -> tuple[UsageEvent, ...]:
        with self._lock:
            return tuple(self._events)


# ── 純函數 roll-up ────────────────────────────────────────────


def _blank() -> dict[str, int]:
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _fold(acc: dict[str, int], event: UsageEvent) -> dict[str, int]:
    return {
        "calls": acc["calls"] + 1,
        "prompt_tokens": acc["prompt_tokens"] + event.prompt_tokens,
        "completion_tokens": acc["completion_tokens"] + event.completion_tokens,
        "total_tokens": acc["total_tokens"] + event.total_tokens,
    }


def totals(events: tuple[UsageEvent, ...]) -> dict[str, int]:
    acc = _blank()
    for event in events:
        acc = _fold(acc, event)
    return acc


def _group_by(events: tuple[UsageEvent, ...], key) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for event in events:
        bucket = key(event)
        out[bucket] = _fold(out.get(bucket, _blank()), event)
    return out


def by_step(events: tuple[UsageEvent, ...]) -> dict[str, dict[str, int]]:
    return _group_by(events, lambda e: e.step)


def by_model(events: tuple[UsageEvent, ...]) -> dict[str, dict[str, int]]:
    return _group_by(events, lambda e: e.model)


def summarize(meter: UsageMeter, today: str) -> dict:
    """組成 steps/_usage.json 的當日 on-disk 形狀。"""
    events = meter.events
    return {
        "date": today,
        "totals": totals(events),
        "by_step": by_step(events),
        "by_model": by_model(events),
    }


# ── 跨天歷史（形狀鏡射 _judge-history.json）────────────────────


def load_history(history_file: Path) -> list[dict]:
    """讀跨天用量歷史；缺檔 / 壞檔回空 list（唯讀，永不拋）。"""
    if not history_file.exists():
        return []
    try:
        data = json.loads(history_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def append_history(history_file: Path, summary: dict) -> None:
    """把當日 totals 追加到跨天歷史；同日重跑則覆寫（idempotent）。"""
    today = summary.get("date", "")
    kept = [r for r in load_history(history_file) if r.get("date") != today]
    row = {
        "date": today,
        **summary.get("totals", _blank()),
        "by_model": summary.get("by_model", {}),
    }
    kept.append(row)
    kept.sort(key=lambda r: r.get("date", ""))
    history_file.write_text(
        json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── --usage 唯讀 render ───────────────────────────────────────


def _fmt(n: int) -> str:
    return f"{n:,}"


def render_usage_table(
    records: list[dict], today_summary: dict | None = None, days: int = 7
) -> str:
    """近 N 天 token 用量表 + 今日各步驟明細（--usage 短路輸出，不載入模型）。"""
    if not records:
        return "📊 Token 用量：尚無歷史資料（跑一次 daily-brief 後再查）。"

    recent = records[-days:]
    lines = [f"📊 Token 用量（近 {len(recent)} 天）", ""]
    lines.append(f"{'日期':<12}{'呼叫':>6}{'輸入':>12}{'輸出':>12}{'合計':>12}")
    for r in recent:
        lines.append(
            f"{r.get('date', '?'):<12}"
            f"{r.get('calls', 0):>6}"
            f"{_fmt(r.get('prompt_tokens', 0)):>12}"
            f"{_fmt(r.get('completion_tokens', 0)):>12}"
            f"{_fmt(r.get('total_tokens', 0)):>12}"
        )

    totals_sum = sum(r.get("total_tokens", 0) for r in recent)
    avg = totals_sum // len(recent) if recent else 0
    lines += ["", f"平均/天：{_fmt(avg)} tokens"]

    if today_summary and today_summary.get("by_step"):
        lines += ["", f"今日各步驟（{today_summary.get('date', '?')}）："]
        step_rows = sorted(
            today_summary["by_step"].items(),
            key=lambda kv: kv[1].get("total_tokens", 0),
            reverse=True,
        )
        for name, agg in step_rows:
            lines.append(
                f"  {name:<12}{agg.get('calls', 0):>4} 次  {_fmt(agg.get('total_tokens', 0)):>12} tokens"
            )

    return "\n".join(lines)

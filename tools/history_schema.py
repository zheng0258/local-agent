"""可觀測性歷史檔的共享 typed view —— judge / health 逐日記錄的單一形狀定義。

`_judge-history.json` / `_health-history.json` 的 on-disk 形狀原本被三處各自手抄：
生產端（judge.py / health.py 寫入）、消費端（site_builder.status 讀取）、測試 fixture。
欄位名、日期格式、`"ok"` 魔法值散落多份，任一端漂移時另一端只會靜默降級。

本模組把「這兩份歷史檔長什麼樣」收成單一權威：寫入端走 `to_dict`、讀取端走
`from_dict`，跨 agents / tools 兩層合法共用（agents → tools、tools → tools 同層）。
純資料，不碰檔案；I/O 仍住各自的 load/append 薄函式。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Optional

# judge / health 歷史每列共用的日期字串格式與成功標記（唯一定義點）。
DATE_FMT = "%Y-%m-%d"
OK = "ok"


def parse_date(value: object) -> Optional[datetime]:
    """把歷史列的 date 欄位解析為 datetime；非字串或格式錯誤回 None（寬容跳過）。"""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, DATE_FMT)
    except ValueError:
        return None


def days_between(earlier: str, later: str) -> int:
    """兩個 DATE_FMT 日期字串之間的日曆天數（later - earlier）。"""
    return (datetime.strptime(later, DATE_FMT) - datetime.strptime(earlier, DATE_FMT)).days


def _num_or_none(value: object) -> int | float | None:
    """數字（排除 bool）原樣回傳，其餘回 None。"""
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None


@dataclass(frozen=True)
class JudgeHistoryRecord:
    """`_judge-history.json` 單列的 typed view / 寫入模型。

    on-disk 形狀：{date, overall, scores:{relevance, completeness, faithfulness}, quality_alert}。
    overall / 各軸分數缺值或非數字時為 None（不轉 0，保留「無有效分」語義）。
    """

    date: str
    overall: float | None
    relevance: int | float | None
    completeness: int | float | None
    faithfulness: int | float | None
    quality_alert: bool

    @classmethod
    def from_dict(cls, raw: Mapping) -> "JudgeHistoryRecord":
        raw = raw if isinstance(raw, Mapping) else {}
        scores = raw.get("scores", {})
        scores = scores if isinstance(scores, Mapping) else {}
        return cls(
            date=str(raw.get("date", "")),
            overall=_num_or_none(raw.get("overall")),
            relevance=_num_or_none(scores.get("relevance")),
            completeness=_num_or_none(scores.get("completeness")),
            faithfulness=_num_or_none(scores.get("faithfulness")),
            quality_alert=bool(raw.get("quality_alert", False)),
        )

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "overall": self.overall,
            "scores": {
                "relevance": self.relevance,
                "completeness": self.completeness,
                "faithfulness": self.faithfulness,
            },
            "quality_alert": self.quality_alert,
        }


@dataclass(frozen=True)
class HealthHistoryRecord:
    """`_health-history.json` 單列的 typed view：date + subject → 結果（"ok" 或 ErrorClass 值）。

    畸形 results（非 dict）視為空。跨 agents / tools 兩層共用的讀取形狀。
    """

    date: str
    results: Mapping[str, str]

    @classmethod
    def from_dict(cls, raw: Mapping) -> "HealthHistoryRecord":
        raw = raw if isinstance(raw, Mapping) else {}
        results = raw.get("results", {})
        return cls(
            date=str(raw.get("date", "")),
            results=(
                {str(k): str(v) for k, v in results.items()}
                if isinstance(results, Mapping)
                else {}
            ),
        )

    def to_dict(self) -> dict:
        return {"date": self.date, "results": dict(self.results)}

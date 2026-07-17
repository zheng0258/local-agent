"""SaveStep — 把 report.md + digest 存進 Obsidian vault。

save 副作用邏輯（run_save）與 markdown 格式化住此檔（不再是 God object 的方法）。
run_save 預設注入 _produce；測試可覆寫成 fake，避免碰真 vault（合法 side-effect seam）。
SentinelCodec：成功後 touch vault.done（存在 = 已存過 → 下次 LOAD 略過）。
guard：需有 digests、report.md 已存在、且 vault 已配置（VAULT_ROOT）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from config import get_logger

from ..codecs import SentinelCodec
from ..schemas import Digest
from ..step import Step, StepOutput

logger = get_logger(__name__)


def format_obsidian_digest(digests: list[dict], today: str) -> str:
    """將 digest list 格式化為 Obsidian markdown 筆記。"""
    lines: list[str] = [
        "---",
        f"created: {today}",
        "tags: [daily-brief, digest]",
        "type: digest",
        "---",
        "",
        f"# {today} *** 文章深度摘要",
        "",
    ]
    for d in digests:
        item = Digest.from_dict(d)
        lines += [
            f"## {item.title}",
            "",
            f"**來源：** {item.source_label}",
            f"**URL：** {item.url}",
            "",
            item.summary,
            "",
            "---",
            "",
        ]
    return "\n".join(lines)


def run_save(day_dir: Path, today: str, digests: list[dict]) -> None:
    """把 report.md 與 digest markdown 寫入 vault（純副作用）。"""
    from ..config import VAULT_DAILY_BRIEF_DIR

    if VAULT_DAILY_BRIEF_DIR is None:
        logger.info("Save: VAULT_ROOT 未配置，略過 Obsidian 存檔")
        return

    VAULT_DAILY_BRIEF_DIR.mkdir(parents=True, exist_ok=True)

    report_md = day_dir / "report.md"
    if report_md.exists():
        vault_report = VAULT_DAILY_BRIEF_DIR / f"{today}.md"
        vault_report.write_text(report_md.read_text(encoding="utf-8"), encoding="utf-8")
        logger.info("Save: 寫入 %s", vault_report)

    vault_digest = VAULT_DAILY_BRIEF_DIR / f"{today}-digest.md"
    vault_digest.write_text(format_obsidian_digest(digests, today), encoding="utf-8")
    logger.info("Save: 寫入 %s", vault_digest)


class SaveStep(Step):
    name = "save"
    codec = SentinelCodec()

    def __init__(self, today: str, save: Callable[..., None] = run_save) -> None:
        self._today = today
        self._save = save

    def artifact_path(self, ctx) -> Path:
        return ctx.day_dir / "vault.done"

    def _guard(self, ctx, input) -> bool:
        from ..config import VAULT_DAILY_BRIEF_DIR

        if not (bool(input) and (ctx.day_dir / "report.md").exists()):
            return False
        if VAULT_DAILY_BRIEF_DIR is None:
            return False  # 未配置 VAULT_ROOT：save 停用，靜默略過
        # 已配置但 vault 根目錄不存在（誤填 / iCloud 未掛載）→ 警告並略過，
        # 不用 mkdir(parents=True) 建出一棵假目錄樹。
        vault_root = VAULT_DAILY_BRIEF_DIR.parent.parent
        if not vault_root.exists():
            logger.warning("Save: VAULT_ROOT 路徑不存在，略過存檔：%s", vault_root)
            return False
        return True

    def _produce(self, ctx, input, reflect_context: str = "") -> StepOutput:
        self._save(ctx.day_dir, self._today, input)
        return StepOutput(persist=None, value=None)

    def _default(self, input):
        return None

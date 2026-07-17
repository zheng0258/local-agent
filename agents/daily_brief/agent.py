"""
DailyBriefAgent — 每日科技趨勢收集。

步驟化流程：
  hatena / hn / reddit / security → dedup → compress → digest → judge → report → save → notify

執行參數：
  （無參數）               正常執行，略過已完成步驟
  --force <step>...       強制重新執行指定步驟
  --only <step>...        只執行指定步驟

可用 step 名稱：hatena / hn / reddit / security / dedup / compress / digest / tldr / judge / report / save / notify
"""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from config import get_judge_llm, get_llm, get_logger
from config.settings import (
    DEFAULT_LOCAL_LLM_URL,
    LLMBackend,
    check_local_llm,
)

from . import prompts
from .config import FETCH_STEPS, OUTPUT_DIR
from .reconcile import filter_top_articles
from .schemas import QualityScore
from .step import StepStatus, Supervisor
from .step_cache import Verdict, decide

logger = get_logger(__name__)

ALL_STEPS = [
    *FETCH_STEPS,
    "dedup",
    "compress",
    "enrich",
    "digest",
    "tldr",
    "judge",
    "report",
    "save",
    "compose_tg",
    "notify",
    "deploy",
]


@dataclass(frozen=True)
class _RunContext:
    today: str
    day_dir: Path
    steps_dir: Path
    force_steps: set[str]
    steps_to_run: set[str]
    supervisor: Supervisor
    notify_fn: Callable[[str], bool]
    llm: LLMBackend
    judge_llm: LLMBackend


class DailyBriefAgent:
    AGENT_NAME = "daily-brief"

    def __init__(
        self, llm: LLMBackend | None = None, judge_llm: LLMBackend | None = None
    ) -> None:
        self._llm = llm or get_llm()
        self._judge_llm = judge_llm or get_judge_llm()

    def run(self, args: str = "") -> str:
        today = date.today().strftime("%Y-%m-%d")

        # 唯讀健康查詢（pull）：短路，不跑 pipeline、不需 LLM
        if "--health" in shlex.split(args):
            from .health import (
                HEALTH_HISTORY_FILE,
                JUDGE_HISTORY_FILE,
                detect_judge_saturation,
                digest_source_shares,
                load_history,
                load_judge_history,
                load_recent_digests,
                render_health_table,
            )

            shares = digest_source_shares(load_recent_digests(OUTPUT_DIR, today))
            saturation = detect_judge_saturation(load_judge_history(JUDGE_HISTORY_FILE))
            return render_health_table(
                load_history(HEALTH_HISTORY_FILE),
                digest_shares=shares,
                judge_saturation=saturation,
            )

        force_steps, only_steps = _parse_args(args)

        prompts._load_interests.cache_clear()

        llm_url = os.environ.get("LOCAL_LLM_URL", DEFAULT_LOCAL_LLM_URL)
        if not check_local_llm(llm_url):
            from tools.notifiers.telegram import send as tg_send

            tg_send(
                f"⚠️ Daily Brief 無法啟動（{today}）\n"
                f"LM Studio 未回應：{llm_url}\n"
                f"建議：啟動 LM Studio 後重跑\n"
                f'  python3 main.py "/daily-brief"'
            )
            logger.error("LM Studio 未回應（%s），pipeline 中止", llm_url)
            return f"Pipeline 中止：LM Studio 未回應（{llm_url}）"

        day_dir = OUTPUT_DIR / today
        steps_dir = day_dir / "steps"
        steps_dir.mkdir(parents=True, exist_ok=True)

        # Fix C: source artifact 比下游新時自動強制重跑下游
        force_steps = _compute_force_steps(only_steps, force_steps, steps_dir, day_dir)

        from .supervisor import SupervisorAgent
        from tools.notifiers.telegram import send as tg_send

        supervisor = SupervisorAgent(
            llm=self._llm,
            judge_llm=self._judge_llm,
            steps_dir=steps_dir,
            today=today,
            notify_fn=tg_send,
        )
        ctx = _RunContext(
            today=today,
            day_dir=day_dir,
            steps_dir=steps_dir,
            force_steps=force_steps,
            steps_to_run=only_steps or set(ALL_STEPS),
            supervisor=supervisor,
            notify_fn=tg_send,
            llm=self._llm,
            judge_llm=self._judge_llm,
        )

        source_data = self._fetch_sources(ctx)
        if source_data is None:
            return "Pipeline 中止：fetch 成功不足（需 ≥ 2）"
        source_data = filter_top_articles(source_data)
        from .steps.dedup import DedupStep

        source_data = DedupStep().run(ctx, source_data).value
        from .steps.compress import CompressStep

        compress_data = CompressStep().run(ctx, source_data).value
        from .steps.enrich import EnrichStep

        enrich_data = EnrichStep().run(ctx, compress_data).value
        from .steps.digest import DigestStep

        digests = DigestStep().run(ctx, enrich_data).value
        from .steps.tldr import TldrStep

        # 當日英文 TL;DR（additive；失敗回 default 不 block 後續步驟）
        TldrStep().run(ctx, digests)
        from .steps.judge import JudgeStep

        judge_outcome = JudgeStep().run(
            ctx, (enrich_data, digests, source_data)
        )
        if judge_outcome.status is StepStatus.RAN:
            quality = QualityScore.from_dict(judge_outcome.value)
            if (
                quality.completeness is not None
                and quality.completeness < 3
                and "digest" not in ctx.force_steps
                and digests
            ):
                logger.warning(
                    "Judge completeness=%.1f，觸發 digest 重跑（missed: %s）",
                    quality.completeness,
                    list(quality.missed_urls),
                )
                hint = ctx.supervisor.reflect_for_completeness(
                    list(quality.missed_urls),
                    prompts.build_digest_prompt_from_compress(
                        json.dumps(enrich_data, ensure_ascii=False)
                    ),
                )
                digests = (
                    DigestStep()
                    .run(ctx, enrich_data, reflect=hint, force=True)
                    .value
                )
                JudgeStep().run(
                    ctx, (enrich_data, digests, source_data), force=True
                )
                logger.info("Judge 回饋 digest 重跑完成")
        from .steps.report import ReportStep

        ReportStep().run(ctx, (enrich_data, digests))
        from .steps.save import SaveStep

        SaveStep(ctx.today).run(ctx, digests)
        from .steps.compose_tg import ComposeTgStep
        from .steps.notify import NotifyStep

        # compose（生成兩封訊息純文字，持久化、重跑 LOAD 不重生）→ notify（send-only、逐封冪等）
        composed = ComposeTgStep().run(ctx, digests).value
        NotifyStep(tg_send, ctx.today).run(ctx, composed)
        from .steps.deploy import DeployStep
        from tools.site_builder import (
            build_site_archive,
            load_days,
            load_latest_tldr,
            load_narrative,
            load_status,
        )

        # 全量重建 thunk：讀全部歷史天 + 手寫雙語敘事 config + 當日英文 TL;DR +
        # judge/health 歷史推導的系統狀態 → 整站 map（公開站 ⇔ 本機真實狀態一致；
        # 敘事中英切換，報告/存檔維持繁中；TL;DR 只在最新天；系統狀態展現 instrumentation）。
        DeployStep(
            lambda: build_site_archive(
                load_days(OUTPUT_DIR),
                narrative=load_narrative(),
                latest_tldr=load_latest_tldr(OUTPUT_DIR),
                status=load_status(OUTPUT_DIR),
            ),
            ctx.today,
        ).run(ctx, None)

        # Fix B: pipeline 結束後，若有步驟失敗記錄，發一則彙總告警（每天只發一次）
        _send_alerts_summary(steps_dir, today, tg_send)

        # 可觀測性：記錄今日健康狀態 + 慢性故障跨天偵測（只在 chronic 時打擾）
        _observe_and_escalate(today, day_dir, steps_dir, tg_send)

        return f"完成。輸出目錄：outputs/daily-brief/{today}/"

    def _fetch_sources(self, ctx: _RunContext) -> dict[str, dict] | None:
        """Orchestrator：並行預抓 raw（RUN-verdict 來源）→ 序列評分（SourceStep.run）→ ≥2 門檻。"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from .steps.source import SourceStep

        sources = {n: SourceStep(n) for n in FETCH_STEPS}

        # 哪些來源該重抓 raw（verdict == RUN）。LOAD/SKIP 不需網路 I/O。
        to_fetch = [
            n
            for n in FETCH_STEPS
            if decide(
                n in ctx.steps_to_run,
                (ctx.steps_dir / f"{n}.json").exists(),
                n in ctx.force_steps,
            )
            is Verdict.RUN
        ]

        # Stage 1（並行）：純網路 I/O，無 LLM。
        raws: dict[str, list] = {}
        with ThreadPoolExecutor(max_workers=len(to_fetch) or 1) as executor:
            futures = {executor.submit(self._fetch_raw_data, n): n for n in to_fetch}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    raws[name] = future.result()
                except Exception as exc:
                    logger.warning("Step %-8s: 原始資料抓取失敗 — %s", name, exc)

        # Stage 2（序列）：評分序列化，避免 LM Studio 並行 HTTP 400。
        source_data: dict[str, dict] = {}
        for name in FETCH_STEPS:
            outcome = sources[name].run(ctx, raws.get(name))
            if outcome.value is not None:
                source_data[name] = outcome.value

        fetch_failed = [n for n in to_fetch if n not in source_data]
        success_count = len(source_data)
        if success_count < 2 and ctx.steps_to_run.intersection(set(FETCH_STEPS)):
            msg = (
                f"⚠️ Daily Brief Fetch 嚴重失敗（{ctx.today}）\n"
                f"成功：{success_count}/{len(FETCH_STEPS)}，失敗：{fetch_failed}\n"
                "Pipeline 停止。"
            )
            ctx.notify_fn(msg)
            logger.error(
                "Fetch 成功 %d/%d，低於門檻，pipeline 停止",
                success_count,
                len(FETCH_STEPS),
            )
            return None

        return source_data

    def _fetch_raw_data(self, name: str) -> list:
        """Phase 1 helper: 純資料抓取，不呼叫 LLM。"""
        from tools.fetchers import hatena, hn, reddit, security_blogs
        from agents.daily_brief.fetchers import rss_fetcher

        dispatch = {
            "hatena": lambda: hatena.fetch(),
            "hn": lambda: hn.fetch(),
            "reddit": lambda: reddit.fetch(),
            "security": lambda: security_blogs.fetch(),
            "rss": lambda: rss_fetcher.fetch(),
        }
        return dispatch[name]()

def _parse_args(args: str) -> tuple[set[str], set[str]]:
    """
    解析 --force 和 --only 參數。

    範例：
      "--force hatena hn"    → force={"hatena","hn"}, only=set()
      "--only report notify" → force=set(), only={"report","notify"}
    """
    tokens = shlex.split(args) if args.strip() else []
    force: set[str] = set()
    only: set[str] = set()

    i = 0
    while i < len(tokens):
        if tokens[i] == "--force":
            i += 1
            while i < len(tokens) and not tokens[i].startswith("--"):
                if tokens[i] in ALL_STEPS:
                    force.add(tokens[i])
                i += 1
        elif tokens[i] == "--only":
            i += 1
            while i < len(tokens) and not tokens[i].startswith("--"):
                if tokens[i] in ALL_STEPS:
                    only.add(tokens[i])
                i += 1
        else:
            i += 1

    return force, only


def _compute_force_steps(
    only_steps: set[str], force_steps: set[str], steps_dir: Path, day_dir: Path
) -> set[str]:
    """Fix C：非 --only 模式下，source artifact 比下游新時，把過期下游加進 force_steps。"""
    if only_steps:
        return force_steps
    stale = _detect_stale_downstream(steps_dir, day_dir)
    newly_forced = stale - force_steps
    if newly_forced:
        logger.warning("來源 artifact 比下游新，自動強制重跑：%s", sorted(newly_forced))
    return force_steps | newly_forced


def _downstream_steps() -> list:
    """過期偵測涵蓋的下游 step（依 pipeline 順序）。

    路徑取自各 Step.artifact_path（單一 DAG 來源）；新增 step 只需在此加一個類別，
    不再各自重抄 `("name", steps_dir/"name.json")` 路徑字串。save / notify 由使用者決定，
    不列入自動過期重跑；deploy 另以 report.md 上游單獨判定。
    """
    from .steps.compose_tg import ComposeTgStep
    from .steps.compress import CompressStep
    from .steps.dedup import DedupStep
    from .steps.digest import DigestStep
    from .steps.enrich import EnrichStep
    from .steps.judge import JudgeStep
    from .steps.report import ReportStep
    from .steps.tldr import TldrStep

    return [
        DedupStep(),
        CompressStep(),
        EnrichStep(),
        DigestStep(),
        TldrStep(),
        JudgeStep(),
        ReportStep(),
        ComposeTgStep(),
    ]


def _detect_stale_downstream(steps_dir: Path, day_dir: Path) -> set[str]:
    """Fix C: 比較 source artifact mtime 與下游 artifact mtime。

    若任一 source artifact 比下游 artifact 新，回傳需強制重跑的下游 step 名稱集合。
    下游 artifact 路徑取自各 Step.artifact_path（見 _downstream_steps）。
    deploy 的上游是 report.md（非 source）：report.md 比 deploy.done 新 → deploy 過期。
    """
    from types import SimpleNamespace

    stale: set[str] = set()
    pctx = SimpleNamespace(steps_dir=steps_dir, day_dir=day_dir)

    # deploy 上游是 report.md：report 重生後須重新發佈站台。
    report_md = day_dir / "report.md"
    deploy_done = day_dir / "deploy.done"
    if (
        report_md.exists()
        and deploy_done.exists()
        and deploy_done.stat().st_mtime < report_md.stat().st_mtime
    ):
        stale.add("deploy")

    source_artifacts = [
        steps_dir / f"{name}.json"
        for name in FETCH_STEPS
        if (steps_dir / f"{name}.json").exists()
    ]
    if not source_artifacts:
        return stale

    latest_source_mtime = max(a.stat().st_mtime for a in source_artifacts)

    for step in _downstream_steps():
        artifact = step.artifact_path(pctx)
        if artifact.exists() and artifact.stat().st_mtime < latest_source_mtime:
            stale.add(step.name)
    return stale


def _send_alerts_summary(
    steps_dir: Path,
    today: str,
    notify_fn: Callable[[str], bool],
) -> None:
    """Fix B: pipeline 結束後發一則彙總告警（每天只發一次）。

    個別步驟失敗時 supervisor._notify_failure 已即時發送；
    此函式在 pipeline 最後補發「今日整體失敗摘要」，方便使用者一眼看清楚哪些來源缺失。
    """
    alerts_file = steps_dir / "alerts.json"
    summary_done = steps_dir / "alerts_summary.done"

    if not alerts_file.exists() or summary_done.exists():
        return

    try:
        alerts: dict = json.loads(alerts_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    if not alerts:
        return

    lines = [
        f"📋 Daily Brief 失敗摘要（{today}）",
        "",
        "以下步驟全部重試後仍失敗，今日 brief 可能不完整：",
    ]
    for step, info in alerts.items():
        if isinstance(info, dict):
            err = info.get("error", "")[:120]
            lines.append(f"• <b>{step}</b>：{err}")
        else:
            lines.append(f"• <b>{step}</b>")

    lines += [
        "",
        "補跑指令：",
        f"  python3 main.py \"/daily-brief --force {' '.join(alerts.keys())}\"",
    ]
    notify_fn("\n".join(lines))
    summary_done.touch()
    logger.info("alerts_summary 已發送（%d 個失敗步驟）", len(alerts))


def _observe_and_escalate(
    today: str,
    day_dir: Path,
    steps_dir: Path,
    notify_fn: Callable[[str], bool],
) -> None:
    """記錄今日健康狀態並跨天偵測慢性故障。

    每天各自獨立的 alert 在此被 roll-up：同一 subject 在滑動視窗內反覆失敗
    （chronic）才主動 escalate，single transient flake 靜默。同一 chronic
    episode 只打擾一次（escalation state 去重）。
    """
    from . import health

    try:
        record = health.observe_run(today, day_dir, steps_dir)
        history = health.append_record(record, health.HEALTH_HISTORY_FILE)
        findings = health.detect_chronic(history)
        fresh = health.filter_new_escalations(
            findings, health.ESCALATION_STATE_FILE, today
        )
        if fresh:
            notify_fn(health.format_escalation(fresh, today))
            health.record_escalations(fresh, health.ESCALATION_STATE_FILE, today)
            logger.warning("慢性故障 escalation：%s", [f.subject for f in fresh])
    except Exception as exc:  # 可觀測性不得反過來弄垮 pipeline
        logger.warning("健康記錄失敗（不影響 pipeline）：%s", exc)



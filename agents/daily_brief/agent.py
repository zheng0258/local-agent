"""
DailyBriefAgent — 每日科技趨勢收集。

步驟化流程：
  hatena / hn / reddit / security → dedup → compress → digest → judge → report → save → notify

執行參數：
  （無參數）               正常執行，略過已完成步驟
  --force <step>...       強制重新執行指定步驟
  --only <step>...        只執行指定步驟

可用 step 名稱：hatena / hn / reddit / security / dedup / compress / digest / judge / report / save / notify
"""

from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from config import get_judge_llm, get_llm, get_logger, parse_llm_json
from config.settings import (
    DEFAULT_JUDGE_LLM_MODEL,
    DEFAULT_LOCAL_LLM_MODEL,
    DEFAULT_LOCAL_LLM_URL,
    LLMBackend,
    check_local_llm,
)

from . import prompts
from .config import OUTPUT_DIR
from .schemas import Digest, QualityScore, SourceCompress
from .step_cache import Verdict, decide

if TYPE_CHECKING:
    from .supervisor import SupervisorAgent

logger = get_logger(__name__)

FETCH_STEPS = ["hatena", "hn", "reddit", "security", "rss"]
ALL_STEPS = [*FETCH_STEPS, "dedup", "compress", "enrich", "digest", "judge", "report", "save", "notify"]


@dataclass
class _RunContext:
    today: str
    day_dir: Path
    steps_dir: Path
    force_steps: set[str]
    steps_to_run: set[str]
    supervisor: SupervisorAgent
    notify_fn: Callable[[str], bool]


class DailyBriefAgent:
    AGENT_NAME = "daily-brief"

    def __init__(self, llm: LLMBackend | None = None, judge_llm: LLMBackend | None = None) -> None:
        self._llm = llm or get_llm()
        self._judge_llm = judge_llm or get_judge_llm()

    def run(self, args: str = "") -> str:
        today = date.today().strftime("%Y-%m-%d")
        force_steps, only_steps = _parse_args(args)

        prompts._load_interests.cache_clear()

        llm_url = os.environ.get("LOCAL_LLM_URL", DEFAULT_LOCAL_LLM_URL)
        if not check_local_llm(llm_url):
            from tools.notifiers.telegram import send as tg_send
            tg_send(
                f"⚠️ Daily Brief 無法啟動（{today}）\n"
                f"LM Studio 未回應：{llm_url}\n"
                f"建議：啟動 LM Studio 後重跑\n"
                f"  python3 main.py \"/daily-brief\""
            )
            logger.error("LM Studio 未回應（%s），pipeline 中止", llm_url)
            return f"Pipeline 中止：LM Studio 未回應（{llm_url}）"

        day_dir = OUTPUT_DIR / today
        steps_dir = day_dir / "steps"
        steps_dir.mkdir(parents=True, exist_ok=True)

        # Fix C: source artifact 比下游新時自動強制重跑下游
        if not only_steps:
            stale = _detect_stale_downstream(steps_dir, day_dir)
            newly_forced = stale - force_steps
            if newly_forced:
                logger.warning(
                    "來源 artifact 比下游新，自動強制重跑：%s", sorted(newly_forced)
                )
                force_steps = force_steps | newly_forced

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
        )

        source_data = self._phase_fetch(ctx)
        if source_data is None:
            return "Pipeline 中止：fetch 成功不足（需 ≥ 2）"
        source_data = _filter_top_articles(source_data)
        source_data = self._phase_dedup(ctx, source_data)
        from .steps.compress import CompressStep
        compress_data = CompressStep(
            self._run_compress, self._check_source_health
        ).run(ctx, source_data).value
        enrich_data = self._phase_enrich(ctx, compress_data)
        digests = self._phase_digest(ctx, enrich_data)
        enrich_data, digests = self._phase_judge(ctx, enrich_data, digests)
        self._phase_report(ctx, enrich_data, digests)
        self._phase_save(ctx, digests)
        self._phase_notify(ctx, digests)

        # Fix B: pipeline 結束後，若有步驟失敗記錄，發一則彙總告警（每天只發一次）
        _send_alerts_summary(steps_dir, today, tg_send)

        return f"完成。輸出目錄：outputs/daily-brief/{today}/"

    def _phase_fetch(self, ctx: _RunContext) -> dict[str, dict] | None:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        source_data: dict[str, dict] = {}
        fetch_failed: list[str] = []

        # Phase 1: 網路 I/O 並行（純資料抓取，無 LLM）
        def _load_or_fetch_raw(name: str) -> tuple[str, dict | list | None, bool]:
            artifact = ctx.steps_dir / f"{name}.json"
            if name not in ctx.steps_to_run:
                if artifact.exists():
                    return name, json.loads(artifact.read_text(encoding="utf-8")), True
                return name, None, True
            if artifact.exists() and name not in ctx.force_steps:
                logger.info("Step %-8s: 載入既有 artifact", name)
                return name, json.loads(artifact.read_text(encoding="utf-8")), True
            try:
                raw = self._fetch_raw_data(name)
                return name, raw, False
            except Exception as exc:
                logger.warning("Step %-8s: 原始資料抓取失敗 — %s", name, exc)
                return name, None, False

        to_score: dict[str, list] = {}
        with ThreadPoolExecutor(max_workers=len(FETCH_STEPS)) as executor:
            futures = {executor.submit(_load_or_fetch_raw, n): n for n in FETCH_STEPS}
            for future in as_completed(futures):
                name, data, is_cached = future.result()
                if is_cached:
                    if data is not None:
                        source_data[name] = data
                else:
                    if data is not None:
                        to_score[name] = data
                    elif name in ctx.steps_to_run:
                        fetch_failed.append(name)

        # Phase 2: LLM 評分序列化（避免並行請求導致 LM Studio HTTP 400）
        for name in FETCH_STEPS:
            if name not in to_score:
                continue
            raw = to_score[name]
            artifact = ctx.steps_dir / f"{name}.json"

            def _make_fn(n: str = name, r: list = raw, a: Path = artifact) -> Callable[[], dict]:
                def fn() -> dict:
                    result = self._score_raw_data(n, r)
                    result["fetched_at"] = datetime.now().isoformat(timespec="seconds")
                    a.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                    logger.info("Step %-8s: 完成 → %s", n, a.name)
                    return result
                return fn

            step_result = ctx.supervisor.run_step(name, _make_fn(), force=(name in ctx.force_steps))
            if step_result.success:
                source_data[name] = step_result.output
            else:
                fetch_failed.append(name)

        success_count = len(source_data)
        if success_count < 2 and ctx.steps_to_run.intersection(set(FETCH_STEPS)):
            msg = (
                f"⚠️ Daily Brief Fetch 嚴重失敗（{ctx.today}）\n"
                f"成功：{success_count}/{len(FETCH_STEPS)}，失敗：{fetch_failed}\n"
                "Pipeline 停止。"
            )
            ctx.notify_fn(msg)
            logger.error("Fetch 成功 %d/%d，低於門檻，pipeline 停止", success_count, len(FETCH_STEPS))
            return None

        return source_data

    def _phase_dedup(self, ctx: _RunContext, source_data: dict) -> dict:
        dedup_artifact = ctx.steps_dir / "dedup.json"
        verdict = decide(
            "dedup" in ctx.steps_to_run,
            dedup_artifact.exists(),
            "dedup" in ctx.force_steps,
        )
        if verdict is Verdict.SKIP:
            return source_data
        if verdict is Verdict.LOAD:
            logger.info("Step dedup     : 載入既有 artifact")
            artifact = json.loads(dedup_artifact.read_text(encoding="utf-8"))
            kept_urls = set(artifact.get("kept_urls", []))
            return _filter_source_data_by_urls(source_data, kept_urls)
        if not source_data:
            logger.warning("Step dedup     : 無 fetch 資料，略過")
            return source_data

        logger.info("Step dedup     : 執行中...")
        from agents.daily_brief.config import (
            DEDUP_SIMILARITY_THRESHOLD,
            DEDUP_WINDOW_DAYS,
            VECTOR_DB_PATH,
        )
        from tools.vector_store.client import cleanup_old_records, get_collection
        from tools.vector_store.dedup import dedup_source_data
        from tools.vector_store.embedder import Qwen3Embedder

        VECTOR_DB_PATH.mkdir(parents=True, exist_ok=True)
        collection = get_collection(VECTOR_DB_PATH)
        cleanup_old_records(collection, DEDUP_WINDOW_DAYS)
        embedder = Qwen3Embedder()

        filtered_data, result = dedup_source_data(
            source_data=source_data,
            collection=collection,
            embedder=embedder,
            today=ctx.today,
            window_days=DEDUP_WINDOW_DAYS,
            threshold=DEDUP_SIMILARITY_THRESHOLD,
        )

        artifact_data = {
            "total": result.total,
            "kept": result.kept,
            "filtered_url": result.filtered_url,
            "filtered_semantic": result.filtered_semantic,
            "kept_urls": result.kept_urls,
            "filtered_items": result.filtered_items,
        }
        dedup_artifact.write_text(
            json.dumps(artifact_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(
            "Step dedup     : 完成 → %d/%d 文章保留（url過濾:%d, 語意過濾:%d）",
            result.kept,
            result.total,
            result.filtered_url,
            result.filtered_semantic,
        )
        return filtered_data

    def _phase_digest(self, ctx: _RunContext, compress_data: dict) -> list[dict]:
        digest_artifact = ctx.steps_dir / "digest.json"
        verdict = decide(
            "digest" in ctx.steps_to_run,
            digest_artifact.exists(),
            "digest" in ctx.force_steps,
        )
        if verdict is Verdict.SKIP:
            return []
        if verdict is Verdict.LOAD:
            logger.info("Step digest   : 載入既有 artifact")
            return json.loads(digest_artifact.read_text(encoding="utf-8")).get("digests", [])
        if not compress_data:
            logger.warning("Step digest   : 無壓縮資料，略過（先執行 compress step）")
            return []

        logger.info("Step digest   : 執行中...")

        def _digest_fn(reflect_context: str = "") -> tuple[list[dict], dict]:
            return self._run_digest(compress_data, reflect_context=reflect_context)

        result = ctx.supervisor.run_step(
            "digest", _digest_fn, force=("digest" in ctx.force_steps)
        )
        if not result.success:
            logger.error("Step digest: 全部重試失敗，略過 judge/report/notify")
            return []
        digests, digest_data = result.output
        digest_artifact.write_text(
            json.dumps(digest_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Step digest   : 完成 → digest.json（%d 篇）", len(digests))
        return digests

    def _phase_judge(
        self, ctx: _RunContext, compress_data: dict, digests: list[dict]
    ) -> tuple[dict, list[dict]]:
        judge_artifact = ctx.steps_dir / "judge.json"
        verdict = decide(
            "judge" in ctx.steps_to_run,
            judge_artifact.exists(),
            "judge" in ctx.force_steps,
        )
        if verdict is Verdict.LOAD:
            logger.info("Step judge     : 載入既有 artifact")
            return compress_data, digests
        if verdict is Verdict.SKIP:
            return compress_data, digests
        if not digests or not compress_data:
            logger.warning("Step judge     : 缺少 digests 或 compress 資料，略過")
            return compress_data, digests

        logger.info("Step judge     : 執行中...")

        def _judge_fn(reflect_context: str = "") -> dict:
            if not ctx.supervisor._is_judge_server_available():
                raise RuntimeError("judge LLM server 無回應")
            return self._run_judge(compress_data, digests, date=ctx.today)

        judge_step = ctx.supervisor.run_step(
            "judge", _judge_fn, force=("judge" in ctx.force_steps)
        )
        if not judge_step.success:
            logger.error("Step judge: 全部重試失敗，report/notify 仍繼續執行（無品質評分）")
            return compress_data, digests

        judge_result = judge_step.output
        judge_artifact.write_text(
            json.dumps(judge_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        quality = QualityScore.from_dict(judge_result)
        logger.info(
            "Step judge     : 完成 → judge.json (overall=%.1f)",
            quality.overall,
        )

        if (
            quality.completeness is not None
            and quality.completeness < 3
            and "digest" not in ctx.force_steps
            and digests
        ):
            missed_urls = list(quality.missed_urls)
            logger.warning(
                "Judge completeness=%.1f，觸發 digest 重跑（missed: %s）",
                quality.completeness,
                missed_urls,
            )
            original_digest_prompt = prompts.build_digest_prompt_from_compress(
                json.dumps(compress_data, ensure_ascii=False)
            )
            retry_state: dict[str, list[dict]] = {"digests": digests}

            def _retry_digest_fn(reflect_context: str = "") -> tuple[list[dict], dict]:
                new_digests, new_digest_data = self._run_digest(
                    compress_data, reflect_context=reflect_context
                )
                retry_state["digests"] = new_digests
                return new_digests, new_digest_data

            def _retry_judge_fn(reflect_context: str = "") -> dict:
                return self._run_judge(compress_data, retry_state["digests"], date=ctx.today)

            digests, digest_data, judge_result = ctx.supervisor.run_judge_feedback(
                missed_urls=missed_urls,
                original_digest_prompt=original_digest_prompt,
                run_digest_fn=_retry_digest_fn,
                run_judge_fn=_retry_judge_fn,
            )
            (ctx.steps_dir / "digest.json").write_text(
                json.dumps(digest_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            judge_artifact.write_text(
                json.dumps(judge_result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("Judge 回饋 digest 重跑完成")

        return compress_data, digests

    def _phase_report(self, ctx: _RunContext, compress_data: dict, digests: list[dict]) -> None:
        report_md = ctx.day_dir / "report.md"
        verdict = decide(
            "report" in ctx.steps_to_run,
            report_md.exists(),
            "report" in ctx.force_steps,
        )
        if verdict is Verdict.LOAD:
            logger.info("Step report   : 載入既有 artifact")
            return
        if verdict is Verdict.SKIP:
            return
        if not digests:
            logger.warning("Step report   : 無摘要資料，略過（先執行 digest step）")
            return

        logger.info("Step report   : 執行中...")

        def _report_fn(reflect_context: str = "") -> str:
            return self._run_report(
                compress_data, digests, ctx.today, reflect_context=reflect_context
            )

        result = ctx.supervisor.run_step(
            "report", _report_fn, force=("report" in ctx.force_steps)
        )
        if result.success:
            report_md.write_text(result.output, encoding="utf-8")
            logger.info("Step report   : 完成 → report.md")
        else:
            logger.error("Step report: 全部重試失敗，略過 save/notify")

    def _phase_save(self, ctx: _RunContext, digests: list[dict]) -> None:
        vault_done = ctx.day_dir / "vault.done"
        verdict = decide(
            "save" in ctx.steps_to_run,
            vault_done.exists(),
            "save" in ctx.force_steps,
        )
        if verdict is Verdict.LOAD:
            logger.info("Step save     : 已儲存過，略過")
            return
        if verdict is Verdict.SKIP:
            return
        if not digests or not (ctx.day_dir / "report.md").exists():
            logger.warning("Step save     : 缺少 report.md 或 digests，略過（先執行 report step）")
            return

        logger.info("Step save     : 執行中...")

        def _save_fn() -> None:
            self._run_save(ctx.day_dir, ctx.today, digests)

        result = ctx.supervisor.run_step("save", _save_fn, force=("save" in ctx.force_steps))
        if result.success:
            vault_done.touch()
            logger.info("Step save     : 完成 → vault.done")
        else:
            logger.error("Step save: 全部重試失敗")

    def _phase_notify(self, ctx: _RunContext, digests: list[dict]) -> None:
        done_file = ctx.day_dir / "telegram.done"
        verdict = decide(
            "notify" in ctx.steps_to_run,
            done_file.exists(),
            "notify" in ctx.force_steps,
        )
        if verdict is Verdict.LOAD:
            logger.info("Step notify   : 已發送過，略過")
            return
        if verdict is Verdict.SKIP:
            return
        if not digests or not (ctx.day_dir / "report.md").exists():
            logger.warning("Step notify   : 缺少 report.md 或摘要資料，略過")
            return

        logger.info("Step notify   : 執行中...")

        def _notify_fn(reflect_context: str = "") -> bool:
            ok = self._notify(
                digests, ctx.today, steps_dir=ctx.steps_dir, reflect_context=reflect_context
            )
            if not ok:
                raise RuntimeError("Telegram 訊息發送失敗")
            return ok

        result = ctx.supervisor.run_step(
            "notify", _notify_fn, force=("notify" in ctx.force_steps)
        )
        if result.success:
            done_file.touch()
            logger.info("Step notify   : 完成")
        else:
            logger.error("Step notify   : 部分或全部訊息發送失敗，請用 --force notify 重試")

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

    _REDDIT_BATCH_SIZE = 25

    def _score_raw_data(self, name: str, raw: list) -> dict:
        """Phase 2 helper: LLM 評分已抓取的資料。"""
        from tools.fetchers.schema import clean_articles

        if name == "reddit" and len(raw) > self._REDDIT_BATCH_SIZE:
            return self._score_reddit_batched(raw)

        raw_json = json.dumps(raw, ensure_ascii=False)
        prompt_dispatch = {
            "hatena": lambda: prompts.build_hatena_prompt(raw_json),
            "hn": lambda: prompts.build_hn_prompt(raw_json),
            "reddit": lambda: prompts.build_reddit_prompt(raw_json),
            "security": lambda: prompts.build_security_blogs_prompt(raw_json),
            "rss": lambda: prompts.build_rss_prompt(raw_json),
        }
        min_interest = "***" if name == "security" else None

        logger.info("%s LLM 評分：%d 篇文章", name, len(raw))
        result = parse_llm_json(self._complete(prompt_dispatch[name]()))
        cleaned = (
            clean_articles(result.get("articles", []), min_interest=min_interest)
            if min_interest
            else clean_articles(result.get("articles", []))
        )
        result["articles"] = [article.to_dict() for article in cleaned]
        logger.info("%s LLM + 清洗完成：%d 篇", name, len(result["articles"]))
        return result

    def _score_reddit_batched(self, raw: list) -> dict:
        """Reddit 文章數量過多時分批評分，每批 _REDDIT_BATCH_SIZE 篇。"""
        from tools.fetchers.schema import clean_articles

        batch_size = self._REDDIT_BATCH_SIZE
        all_cleaned = []
        n_batches = (len(raw) + batch_size - 1) // batch_size
        logger.info("reddit LLM 評分（分批）：%d 篇 → %d 批", len(raw), n_batches)
        for i in range(0, len(raw), batch_size):
            batch = raw[i : i + batch_size]
            batch_json = json.dumps(batch, ensure_ascii=False)
            result = parse_llm_json(self._complete(prompts.build_reddit_prompt(batch_json)))
            cleaned = clean_articles(result.get("articles", []))
            all_cleaned.extend(cleaned)
            logger.info("reddit 批次 %d/%d：%d 篇 → %d 篇保留", i // batch_size + 1, n_batches, len(batch), len(cleaned))
        logger.info("reddit LLM + 清洗完成（分批）：%d 篇", len(all_cleaned))
        return {"articles": [a.to_dict() for a in all_cleaned]}

    def _phase_enrich(self, ctx: _RunContext, compress_data: dict) -> dict:
        """compress 後、digest 前：對 HN/Reddit *** 文章並行抓留言 → LLM 摘要。"""
        enrich_artifact = ctx.steps_dir / "enrich.json"
        verdict = decide(
            "enrich" in ctx.steps_to_run,
            enrich_artifact.exists(),
            "enrich" in ctx.force_steps,
        )
        if verdict is Verdict.SKIP:
            return compress_data
        if verdict is Verdict.LOAD:
            logger.info("Step enrich    : 載入既有 artifact")
            return json.loads(enrich_artifact.read_text(encoding="utf-8"))
        if not compress_data:
            logger.warning("Step enrich    : 無壓縮資料，略過（先執行 compress step）")
            return compress_data

        logger.info("Step enrich    : 執行中...")
        enrich_data = self._run_enrich(compress_data)
        enrich_artifact.write_text(
            json.dumps(enrich_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        enriched_count = sum(
            1
            for src in ["hn", "reddit"]
            for a in SourceCompress.from_dict(enrich_data.get(src, {})).articles
            if a.comment_summary
        )
        logger.info("Step enrich    : 完成 → enrich.json（%d 篇含留言摘要）", enriched_count)
        return enrich_data

    def _enrich_article(self, src: str, idx: int, article: dict) -> str | None:
        """對單篇文章抓留言並 LLM 摘要，失敗時回傳 None（best-effort）。"""
        from tools.fetchers import hn_comments, reddit_comments
        try:
            url = article.get("url", "")
            if src == "hn":
                item_id = hn_comments.parse_item_id(url)
                if not item_id:
                    logger.debug("HN URL 無法解析 item_id: %s", url)
                    return None
                comments = hn_comments.fetch_comments(item_id, top_n=10)
            else:
                comments = reddit_comments.fetch_comments(url, top_n=10)

            if not comments:
                return None

            sanitized_comments = [c.replace("```", "") for c in comments]
            prompt = prompts.build_comment_summary_prompt(
                source=src,
                title=article.get("title", ""),
                comments_json=json.dumps(sanitized_comments, ensure_ascii=False),
            )
            raw = self._complete(prompt)
            parsed = parse_llm_json(raw)
            summary = parsed.get("comment_summary", "").strip()
            summary = _sanitize_comment_summary(summary)
            return summary if summary else None
        except Exception as exc:
            logger.warning("enrich %s 失敗: %s", src, exc)
            return None

    def _run_enrich(self, compress_data: dict) -> dict:
        """對 compress_data 中 HN/Reddit *** 文章並行抓留言並 LLM 摘要。"""
        import copy
        from concurrent.futures import ThreadPoolExecutor, as_completed

        result = copy.deepcopy(compress_data)
        result["_meta"] = {"enriched_at": datetime.now().isoformat(timespec="seconds")}

        to_enrich: list[tuple[str, int]] = []
        for src in ["hn", "reddit"]:
            for idx, article in enumerate(result.get(src, {}).get("articles", [])):
                if isinstance(article, dict):
                    to_enrich.append((src, idx))

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self._enrich_article, src, idx, result[src]["articles"][idx]): (src, idx)
                for src, idx in to_enrich
            }
            for future in as_completed(futures):
                src, idx = futures[future]
                comment_summary = future.result()
                if comment_summary:
                    result[src]["articles"][idx]["comment_summary"] = comment_summary

        return result

    def _run_compress(self, source_data: dict, reflect_context: str = "") -> dict:
        """Layer 2: LLM compresses each source into themes + one-liners.
        Python pre-filters to *** articles before calling LLM.
        """
        result: dict = {"_meta": {"compressed_at": datetime.now().isoformat(timespec="seconds")}}
        for name in FETCH_STEPS:
            articles = source_data.get(name, {}).get("articles", [])
            starred = [a for a in articles if isinstance(a, dict) and a.get("interest") == "***"]
            if not starred:
                result[name] = {"themes": [], "articles": []}
                logger.info("Step compress  : %s 無 *** 文章，略過 LLM", name)
                continue
            articles_json = json.dumps(starred, ensure_ascii=False)
            prompt = prompts.build_compress_prompt(name, articles_json)
            if reflect_context:
                prompt = f"{prompt}\n\n## 修正指示\n{reflect_context}"
            raw = self._complete(prompt)
            parsed = parse_llm_json(raw)
            if isinstance(parsed, dict) and "themes" in parsed:
                # LLM 有時不複製 URL；用原始 starred 的 title→url 補回
                url_by_title = {a.get("title", ""): a.get("url", "") for a in starred}
                for art in parsed.get("articles", []):
                    if not art.get("url"):
                        restored = url_by_title.get(art.get("title", ""), "")
                        if restored:
                            art["url"] = restored
                result[name] = parsed
            else:
                logger.warning(
                    "Step compress  : %s LLM 回傳無效（缺 themes），使用原始 starred 資料", name
                )
                result[name] = {"themes": [], "articles": starred}
        return result

    def _run_digest(self, compress_data: dict, reflect_context: str = "") -> tuple[list[dict], dict]:
        # 逐來源分批呼叫 LLM，確保每個來源都被處理（避免 LLM 選擇性跳過）
        sources = [k for k in compress_data if k != "_meta"]
        all_digests: list[dict] = []
        url_by_title: dict[str, str] = {}

        for src in sources:
            src_data = compress_data.get(src, {})
            src_compress = SourceCompress.from_dict(src_data)
            if not src_compress.articles:
                continue
            for art in src_compress.articles:
                if art.title and art.url:
                    url_by_title[art.title] = art.url
            per_src = {src: src_data}
            compress_json = json.dumps(per_src, ensure_ascii=False)
            prompt = prompts.build_digest_prompt_from_compress(compress_json)
            if reflect_context:
                prompt = f"{prompt}\n\n## 修正指示\n{reflect_context}"
            result = parse_llm_json(self._complete(prompt))
            src_digests = result.get("digests", [])
            for d in src_digests:
                d["_source"] = src
            logger.info("Digest %s：%d 篇", src, len(src_digests))
            all_digests.extend(src_digests)

        # URL 補回（LLM 有時不複製 URL）
        for d in all_digests:
            if not d.get("url"):
                restored = url_by_title.get(d.get("title", ""), "")
                if restored:
                    d["url"] = restored

        digest_data = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "digests": all_digests,
        }
        logger.info("Digest LLM 完成：%d 篇摘要", len(all_digests))
        return all_digests, digest_data

    def _run_report(
        self,
        compress_data: dict,
        digests: list[dict],
        today: str,
        reflect_context: str = "",
    ) -> str:
        seen: set[str] = set()
        deduped: list[dict] = []
        for d in digests:
            url = Digest.from_dict(d).url
            if url and url not in seen:
                seen.add(url)
                deduped.append(d)

        compress_json = json.dumps(compress_data, ensure_ascii=False)
        prompt = prompts.build_report_prompt_from_compress(
            compress_json=compress_json,
            digests_json=json.dumps(deduped, ensure_ascii=False),
            today=today,
        )
        if reflect_context:
            prompt = f"{prompt}\n\n## 修正指示\n{reflect_context}"
        content = self._complete(prompt).strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?", "", content).rstrip("`").strip()
        return content or "（報告生成失敗）"

    def _run_judge(self, compress_data: dict, digests: list[dict], date: str | None = None) -> dict:
        # 只傳 url + one_liner 給 judge LLM，省 60-70% token
        slim_compress = {
            src: {
                "themes": data.get("themes", []),
                "articles": [
                    {"url": a["url"], "one_liner": a.get("one_liner", "")}
                    for a in data.get("articles", [])
                    if isinstance(a, dict) and "url" in a
                ],
            }
            for src, data in compress_data.items()
            if src in FETCH_STEPS
        }
        if not slim_compress:
            logger.warning("Step judge     : slim_compress 為空，judge 結果可能不可靠")
        compress_json = json.dumps(slim_compress, ensure_ascii=False)
        digest_json = json.dumps({"digests": digests}, ensure_ascii=False)
        raw = self._judge_llm.complete(
            prompts.build_judge_prompt(compress_json, digest_json),
            system=prompts.SYSTEM,
        )
        result = parse_llm_json(raw)
        scores = result.get("scores", {})
        # missed_urls 在新 schema 位於頂層；回寫進 completeness 維持下游介面不變
        missed_urls = result.get("missed_urls") or []
        completeness = scores.get("completeness")
        if isinstance(completeness, dict):
            completeness["missed_urls"] = missed_urls
        dimensions = ["relevance", "completeness", "faithfulness"]
        valid_scores = [
            scores[dim]["score"]
            for dim in dimensions
            if dim in scores and isinstance(scores.get(dim, {}).get("score"), (int, float))
        ]
        result["overall"] = round(sum(valid_scores) / len(valid_scores), 1) if valid_scores else 0.0
        result["judged_at"] = datetime.now().isoformat(timespec="seconds")
        result["judge_model"] = os.environ.get("JUDGE_LLM_MODEL", DEFAULT_JUDGE_LLM_MODEL)

        completeness_score = scores.get("completeness", {}).get("score")
        if isinstance(completeness_score, (int, float)) and completeness_score < 3:
            result["quality_alert"] = True
            result["quality_alert_reason"] = (
                f"completeness={completeness_score}，"
                f"遺漏：{scores['completeness'].get('missed_urls', [])}"
            )
            logger.warning("Judge quality_alert: %s", result["quality_alert_reason"])

        self._append_judge_history(result, date or datetime.now().strftime("%Y-%m-%d"))
        return result

    def _append_judge_history(self, judge_result: dict, date: str) -> None:
        from .config import OUTPUT_DIR
        history_file = OUTPUT_DIR / "_judge-history.json"
        history: list[dict] = []
        if history_file.exists():
            try:
                history = json.loads(history_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                history = []
        # 同一天重跑時替換舊記錄
        history = [r for r in history if r.get("date") != date]
        quality = QualityScore.from_dict(judge_result)
        history.append({
            "date": date,
            "overall": quality.overall,
            "scores": {
                "relevance": quality.relevance,
                "completeness": quality.completeness,
                "faithfulness": quality.faithfulness,
            },
            "quality_alert": quality.quality_alert,
        })
        history.sort(key=lambda r: r["date"])
        history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _check_source_health(compress_data: dict) -> list[str]:
        """回傳 compress 後 articles 為空的來源名稱列表。"""
        empty_sources = []
        for name in FETCH_STEPS:
            if not SourceCompress.from_dict(compress_data.get(name, {})).articles:
                empty_sources.append(name)
                logger.warning("Source health: %s compress 後為 0 篇", name)
        return empty_sources

    def _run_save(self, day_dir: Path, today: str, digests: list[dict]) -> None:
        from .config import VAULT_DAILY_BRIEF_DIR

        VAULT_DAILY_BRIEF_DIR.mkdir(parents=True, exist_ok=True)

        report_md = day_dir / "report.md"
        if report_md.exists():
            vault_report = VAULT_DAILY_BRIEF_DIR / f"{today}.md"
            vault_report.write_text(report_md.read_text(encoding="utf-8"), encoding="utf-8")
            logger.info("Save: 寫入 %s", vault_report)

        vault_digest = VAULT_DAILY_BRIEF_DIR / f"{today}-digest.md"
        vault_digest.write_text(_format_obsidian_digest(digests, today), encoding="utf-8")
        logger.info("Save: 寫入 %s", vault_digest)

    def _notify(
        self,
        digests: list[dict],
        today: str,
        steps_dir: Path | None = None,
        reflect_context: str = "",
    ) -> bool:
        from tools.notifiers.telegram import send

        # 限縮數量塞進單封 Telegram 訊息（4096 上限）：跨來源均衡挑選後送 LLM
        overview_json = json.dumps(
            _pick_top8_balanced(digests, n=_TG_OVERVIEW_MAX_ITEMS), ensure_ascii=False
        )
        digest_json = json.dumps(
            _pick_top8_balanced(digests, n=_TG_DIGEST_MAX_ITEMS), ensure_ascii=False
        )

        overview_prompt = prompts.build_telegram_overview_prompt(overview_json, today)
        digest_prompt = prompts.build_telegram_digest_prompt(digest_json, today)
        if reflect_context:
            overview_prompt = f"{overview_prompt}\n\n## 修正指示\n{reflect_context}"
            digest_prompt = f"{digest_prompt}\n\n## 修正指示\n{reflect_context}"

        overview_raw = self._complete(overview_prompt).strip()
        digest_raw = self._complete(digest_prompt).strip()

        # LLM 有時仍以 JSON 包裝輸出，需解包取出純文字
        overview = _extract_tg_text(overview_raw)
        tg_digest = _extract_tg_text(digest_raw)

        ok1 = False
        if overview:
            if steps_dir:
                (steps_dir / "telegram_overview.txt").write_text(overview, encoding="utf-8")
            ok1 = send(overview)
            if not ok1:
                logger.error("Step notify   : 第一封訊息發送失敗，telegram.done 不寫入")

        ok2 = False
        if tg_digest:
            if steps_dir:
                (steps_dir / "telegram_digest.txt").write_text(tg_digest, encoding="utf-8")
            ok2 = send(tg_digest)
            if not ok2:
                logger.error("Step notify   : 第二封訊息發送失敗，telegram.done 不寫入")

        return ok1 and ok2

    def _complete(self, prompt: str) -> str:
        return self._llm.complete(prompt, system=prompts.SYSTEM)


def _sanitize_comment_summary(text: str) -> str:
    """移除 comment_summary 中可能的注入內容（URL、HTML、markdown 連結、控制序列）。"""
    # 強制 60 字元上限
    text = text[:60]
    # 移除 HTML tag
    text = re.sub(r"<[^>]+>", "", text)
    # 移除 markdown 連結語法 [text](url)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # 移除裸 URL（http/https）
    text = re.sub(r"https?://\S+", "", text)
    # 移除三個反引號（避免 fence 注入）
    text = text.replace("```", "")
    return text.strip()


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


def _extract_tg_text(raw: str) -> str:
    """LLM 有時用 JSON 包裝輸出；嘗試解包取出第一個字串值，否則原樣返回。"""
    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                for v in parsed.values():
                    if isinstance(v, str):
                        return v
        except (json.JSONDecodeError, Exception):
            pass
    return raw


# Telegram 單封 4096 字元上限下的條目數（依實測 overview ~155、digest ~540 字元/則估算，留安全邊際）
_TG_OVERVIEW_MAX_ITEMS = 24
_TG_DIGEST_MAX_ITEMS = 7


def _pick_top8_balanced(digests: list[dict], n: int = 14) -> list[dict]:
    """從各來源 round-robin 各取一篇，湊滿 n 篇，確保 TG 深度摘要跨來源均衡。"""
    from collections import defaultdict

    buckets: dict[str, list[dict]] = defaultdict(list)
    for d in digests:
        buckets[Digest.from_dict(d).source_key].append(d)

    source_order = list(dict.fromkeys(Digest.from_dict(d).source_key for d in digests))
    picked: list[dict] = []
    i = 0
    while len(picked) < n and any(buckets[s] for s in source_order):
        src = source_order[i % len(source_order)]
        if buckets[src]:
            picked.append(buckets[src].pop(0))
        i += 1
    return picked


def _filter_top_articles(source_data: dict) -> dict:
    """只保留 *** 文章傳入分析管線；** 文章已存於 artifact，不影響記錄。"""
    result: dict = {}
    for src, data in source_data.items():
        articles = data.get("articles", [])
        top = [a for a in articles if isinstance(a, dict) and a.get("interest") == "***"]
        if top:
            result[src] = {**data, "articles": top}
    return result


def _filter_source_data_by_urls(source_data: dict, kept_urls: set[str]) -> dict:
    filtered: dict = {}
    for source_name, content in source_data.items():
        articles = content.get("articles", [])
        filtered[source_name] = {
            **content,
            "articles": [a for a in articles if isinstance(a, dict) and a.get("url") in kept_urls],
        }
    return filtered


def _detect_stale_downstream(steps_dir: Path, day_dir: Path) -> set[str]:
    """Fix C: 比較 source artifact mtime 與下游 artifact mtime。

    若任一 source artifact 比下游 artifact 新，回傳需強制重跑的下游 step 名稱集合。
    只比較 dedup / compress / digest / judge / report，save / notify 由使用者決定。
    """
    source_artifacts = [
        steps_dir / f"{name}.json"
        for name in FETCH_STEPS
        if (steps_dir / f"{name}.json").exists()
    ]
    if not source_artifacts:
        return set()

    latest_source_mtime = max(a.stat().st_mtime for a in source_artifacts)

    downstream_check: list[tuple[str, Path]] = [
        ("dedup",    steps_dir / "dedup.json"),
        ("compress", steps_dir / "compress.json"),
        ("enrich",   steps_dir / "enrich.json"),
        ("digest",   steps_dir / "digest.json"),
        ("judge",    steps_dir / "judge.json"),
        ("report",   day_dir   / "report.md"),
    ]
    return {
        name
        for name, artifact in downstream_check
        if artifact.exists() and artifact.stat().st_mtime < latest_source_mtime
    }


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


def _format_obsidian_digest(digests: list[dict], today: str) -> str:
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

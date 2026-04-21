"""
DailyBriefAgent — 每日科技趨勢收集。

步驟化流程：
  hatena / hn / reddit / security → compress → digest → judge → report → save → notify

執行參數：
  （無參數）               正常執行，略過已完成步驟
  --force <step>...       強制重新執行指定步驟
  --only <step>...        只執行指定步驟

可用 step 名稱：hatena / hn / reddit / security / compress / digest / judge / report / save / notify
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
from config.settings import DEFAULT_JUDGE_LLM_MODEL, DEFAULT_LOCAL_LLM_MODEL, LLMBackend

from . import prompts
from .config import OUTPUT_DIR

if TYPE_CHECKING:
    from .supervisor import SupervisorAgent

logger = get_logger(__name__)

FETCH_STEPS = ["hatena", "hn", "reddit", "security"]
ALL_STEPS = [*FETCH_STEPS, "compress", "digest", "judge", "report", "save", "notify"]


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

        day_dir = OUTPUT_DIR / today
        steps_dir = day_dir / "steps"
        steps_dir.mkdir(parents=True, exist_ok=True)

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
        compress_data = self._phase_compress(ctx, source_data)
        digests = self._phase_digest(ctx, compress_data)
        compress_data, digests = self._phase_judge(ctx, compress_data, digests)
        self._phase_report(ctx, compress_data, digests)
        self._phase_save(ctx, digests)
        self._phase_notify(ctx, digests)

        return f"完成。輸出目錄：outputs/daily-brief/{today}/"

    def _phase_fetch(self, ctx: _RunContext) -> dict[str, dict] | None:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        source_data: dict[str, dict] = {}
        fetch_failed: list[str] = []

        def _run_fetch_supervised(name: str) -> tuple[str, dict | None]:
            artifact = ctx.steps_dir / f"{name}.json"
            if name not in ctx.steps_to_run:
                if artifact.exists():
                    return name, json.loads(artifact.read_text(encoding="utf-8"))
                return name, None
            if artifact.exists() and name not in ctx.force_steps:
                logger.info("Step %-8s: 載入既有 artifact", name)
                return name, json.loads(artifact.read_text(encoding="utf-8"))

            def fn() -> dict:
                result = self._run_fetch(name)
                result["fetched_at"] = datetime.now().isoformat(timespec="seconds")
                artifact.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                logger.info("Step %-8s: 完成 → %s", name, artifact.name)
                return result

            step_result = ctx.supervisor.run_step(name, fn, force=(name in ctx.force_steps))
            if step_result.success:
                return name, step_result.output
            return name, None

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_run_fetch_supervised, n): n for n in FETCH_STEPS}
            for future in as_completed(futures):
                name, data = future.result()
                if data is not None:
                    source_data[name] = data
                elif name in ctx.steps_to_run:
                    fetch_failed.append(name)

        success_count = len(source_data)
        if success_count < 2 and ctx.steps_to_run.intersection(set(FETCH_STEPS)):
            msg = (
                f"⚠️ Daily Brief Fetch 嚴重失敗（{ctx.today}）\n"
                f"成功：{success_count}/4，失敗：{fetch_failed}\n"
                "Pipeline 停止。"
            )
            ctx.notify_fn(msg)
            logger.error("Fetch 成功 %d/4，低於門檻，pipeline 停止", success_count)
            return None

        return source_data

    def _phase_compress(self, ctx: _RunContext, source_data: dict[str, dict]) -> dict:
        compress_artifact = ctx.steps_dir / "compress.json"
        if "compress" not in ctx.steps_to_run:
            if compress_artifact.exists():
                return json.loads(compress_artifact.read_text(encoding="utf-8"))
            return {}
        if compress_artifact.exists() and "compress" not in ctx.force_steps:
            logger.info("Step compress  : 載入既有 artifact")
            return json.loads(compress_artifact.read_text(encoding="utf-8"))
        if not source_data:
            logger.warning("Step compress  : 無評分資料，略過（先執行 fetch steps）")
            return {}

        logger.info("Step compress  : 執行中...")

        def _compress_fn(reflect_context: str = "") -> dict:
            return self._run_compress(source_data, reflect_context=reflect_context)

        result = ctx.supervisor.run_step(
            "compress", _compress_fn, force=("compress" in ctx.force_steps)
        )
        if not result.success:
            logger.error("Step compress: 全部重試失敗，略過 digest/judge/report/notify")
            return {}
        compress_artifact.write_text(
            json.dumps(result.output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Step compress  : 完成 → compress.json")
        self._check_source_health(result.output)
        return result.output

    def _phase_digest(self, ctx: _RunContext, compress_data: dict) -> list[dict]:
        digest_artifact = ctx.steps_dir / "digest.json"
        if "digest" not in ctx.steps_to_run:
            if digest_artifact.exists():
                return json.loads(digest_artifact.read_text(encoding="utf-8")).get("digests", [])
            return []
        if digest_artifact.exists() and "digest" not in ctx.force_steps:
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
        if "judge" not in ctx.steps_to_run:
            return compress_data, digests
        if judge_artifact.exists() and "judge" not in ctx.force_steps:
            logger.info("Step judge     : 載入既有 artifact")
            return compress_data, digests
        if not digests or not compress_data:
            logger.warning("Step judge     : 缺少 digests 或 compress 資料，略過")
            return compress_data, digests

        logger.info("Step judge     : 執行中...")

        def _judge_fn() -> dict:
            return self._run_judge(compress_data, digests, date=ctx.today)

        judge_step = ctx.supervisor.run_step(
            "judge", _judge_fn, force=("judge" in ctx.force_steps)
        )
        if not judge_step.success:
            logger.error("Step judge: 全部重試失敗，略過 report/notify")
            return compress_data, digests

        judge_result = judge_step.output
        judge_artifact.write_text(
            json.dumps(judge_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(
            "Step judge     : 完成 → judge.json (overall=%.1f)",
            judge_result.get("overall", 0),
        )

        completeness_score = (
            judge_result.get("scores", {}).get("completeness", {}).get("score")
        )
        if (
            isinstance(completeness_score, (int, float))
            and completeness_score < 3
            and "digest" not in ctx.force_steps
            and digests
        ):
            missed_urls = (
                judge_result.get("scores", {}).get("completeness", {}).get("missed_urls", [])
            )
            logger.warning(
                "Judge completeness=%.1f，觸發 digest 重跑（missed: %s）",
                completeness_score,
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
        if "report" not in ctx.steps_to_run:
            return
        if report_md.exists() and "report" not in ctx.force_steps:
            logger.info("Step report   : 載入既有 artifact")
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
        if "save" not in ctx.steps_to_run:
            return
        if vault_done.exists() and "save" not in ctx.force_steps:
            logger.info("Step save     : 已儲存過，略過")
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
        if "notify" not in ctx.steps_to_run:
            return
        if done_file.exists() and "notify" not in ctx.force_steps:
            logger.info("Step notify   : 已發送過，略過")
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

    def _run_fetch(self, name: str) -> dict:
        from tools.fetchers import hatena, hn, reddit, security_blogs

        dispatch = {
            "hatena": lambda: self._fetch_hatena(hatena),
            "hn": lambda: self._fetch_hn(hn),
            "reddit": lambda: self._fetch_reddit(reddit),
            "security": lambda: self._fetch_security(security_blogs),
        }
        return dispatch[name]()

    def _fetch_hatena(self, mod) -> dict:
        from tools.fetchers.schema import clean_articles

        raw = mod.fetch()
        logger.info("Hatena 抓取：%d 篇文章", len(raw))
        result = parse_llm_json(
            self._complete(prompts.build_hatena_prompt(json.dumps(raw, ensure_ascii=False)))
        )
        cleaned = clean_articles(result.get("articles", []))
        result["articles"] = [article.to_dict() for article in cleaned]
        logger.info("Hatena LLM + 清洗完成：%d 篇", len(result["articles"]))
        return result

    def _fetch_hn(self, mod) -> dict:
        from tools.fetchers.schema import clean_articles

        raw = mod.fetch()
        logger.info("HN 抓取：%d 個 URL", len(raw))
        result = parse_llm_json(
            self._complete(prompts.build_hn_prompt(json.dumps(raw, ensure_ascii=False)))
        )
        cleaned = clean_articles(result.get("articles", []))
        result["articles"] = [article.to_dict() for article in cleaned]
        logger.info("HN LLM + 清洗完成：%d 篇", len(result["articles"]))
        return result

    def _fetch_reddit(self, mod) -> dict:
        from tools.fetchers.schema import clean_articles

        raw = mod.fetch()
        total = sum(len(v) for v in raw.values()) if isinstance(raw, dict) else 0
        logger.info("Reddit 抓取：%d 篇文章", total)
        result = parse_llm_json(
            self._complete(prompts.build_reddit_prompt(json.dumps(raw, ensure_ascii=False)))
        )
        articles = result.get("articles", {})
        if isinstance(articles, dict):
            for category, category_articles in articles.items():
                if isinstance(category_articles, list):
                    cleaned = clean_articles(category_articles)
                    articles[category] = [article.to_dict() for article in cleaned]
        logger.info("Reddit LLM + 清洗完成")
        return result

    def _fetch_security(self, mod) -> dict:
        from tools.fetchers.schema import clean_articles

        raw = mod.fetch()
        raw_json = json.dumps(raw, ensure_ascii=False)
        logger.info("Security blogs 抓取：%d 篇文章，%d 字元", len(raw), len(raw_json))
        result = parse_llm_json(
            self._complete(prompts.build_security_blogs_prompt(raw_json))
        )
        cleaned = clean_articles(result.get("articles", []), min_interest="***")
        result["articles"] = [article.to_dict() for article in cleaned]
        logger.info("Security LLM + 清洗完成：%d 篇", len(result["articles"]))
        return result

    def _run_compress(self, source_data: dict, reflect_context: str = "") -> dict:
        """Layer 2: LLM compresses each source into themes + one-liners.
        Python pre-filters to *** articles before calling LLM.
        """
        result: dict = {"_meta": {"compressed_at": datetime.now().isoformat(timespec="seconds")}}
        for name in FETCH_STEPS:
            articles = source_data.get(name, {}).get("articles", [])
            if isinstance(articles, dict):
                articles = [
                    article
                    for category_articles in articles.values()
                    if isinstance(category_articles, list)
                    for article in category_articles
                ]
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
                result[name] = parsed
            else:
                logger.warning(
                    "Step compress  : %s LLM 回傳無效（缺 themes），使用原始 starred 資料", name
                )
                result[name] = {"themes": [], "articles": starred}
        return result

    def _run_digest(self, compress_data: dict, reflect_context: str = "") -> tuple[list[dict], dict]:
        compress_json = json.dumps(compress_data, ensure_ascii=False)
        prompt = prompts.build_digest_prompt_from_compress(compress_json)
        if reflect_context:
            prompt = f"{prompt}\n\n## 修正指示\n{reflect_context}"
        result = parse_llm_json(self._complete(prompt))
        digests = result.get("digests", [])
        digest_data = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "digests": digests,
        }
        logger.info("Digest LLM 完成：%d 篇摘要", len(digests))
        return digests, digest_data

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
            url = d.get("url", "")
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
        completeness = scores.get("completeness")
        if isinstance(completeness, dict) and "missed_urls" not in completeness:
            completeness["missed_urls"] = []
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
        history.append({
            "date": date,
            "overall": judge_result.get("overall", 0.0),
            "scores": {
                dim: judge_result.get("scores", {}).get(dim, {}).get("score")
                for dim in ["relevance", "completeness", "faithfulness"]
            },
            "quality_alert": judge_result.get("quality_alert", False),
        })
        history.sort(key=lambda r: r["date"])
        history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _check_source_health(compress_data: dict) -> list[str]:
        """回傳 compress 後 articles 為空的來源名稱列表。"""
        empty_sources = []
        for name in FETCH_STEPS:
            articles = compress_data.get(name, {}).get("articles", [])
            if not articles:
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
        from concurrent.futures import ThreadPoolExecutor
        from tools.notifiers.telegram import send

        digests_json = json.dumps(digests, ensure_ascii=False)
        top8_json = json.dumps(digests[:8], ensure_ascii=False)

        overview_prompt = prompts.build_telegram_overview_prompt(digests_json, today)
        digest_prompt = prompts.build_telegram_digest_prompt(top8_json, today)
        if reflect_context:
            overview_prompt = f"{overview_prompt}\n\n## 修正指示\n{reflect_context}"
            digest_prompt = f"{digest_prompt}\n\n## 修正指示\n{reflect_context}"

        with ThreadPoolExecutor(max_workers=2) as executor:
            f_overview = executor.submit(lambda: parse_llm_json(self._complete(overview_prompt)))
            f_digest = executor.submit(lambda: parse_llm_json(self._complete(digest_prompt)))
            overview_result = f_overview.result()
            digest_result = f_digest.result()

        overview = overview_result.get("tg_overview", "")
        ok1 = False
        if overview:
            if steps_dir:
                (steps_dir / "telegram_overview.txt").write_text(overview, encoding="utf-8")
            ok1 = send(overview)
            if not ok1:
                logger.error("Step notify   : 第一封訊息發送失敗，telegram.done 不寫入")

        tg_digest = digest_result.get("tg_digest", "")
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
        lines += [
            f"## {d.get('title', '')}",
            "",
            f"**來源：** {d.get('source', '')}",
            f"**URL：** {d.get('url', '')}",
            "",
            d.get("summary", ""),
            "",
            "---",
            "",
        ]
    return "\n".join(lines)

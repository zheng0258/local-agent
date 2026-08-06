# AI Daily Brief Agent

A production-grade multi-agent pipeline that aggregates daily tech trends from **5 sources**, deduplicates and scores them with a **local LLM**, summarizes them, quality-gates the result with an LLM-as-Judge, and delivers a digest to Telegram, an Obsidian vault, and a public showcase site — running entirely on a local model with near-zero API cost.

[中文說明](README.zh.md)

---

## Architecture

```
main.py ──→ DailyBriefAgent.run()
                │
    ┌───────────┴───────────────────────────┐
    ▼                                        ▼
tools/fetchers/ (pure functions, no LLM)   config/settings.py
hatena / hn / reddit / security / rss      LocalLLMBackend
    │
    ▼   per-step JSON artifacts (idempotent cache)
outputs/daily-brief/{today}/steps/
├── hatena/hn/reddit/security/rss.json  # fetch + LLM interest scoring
├── dedup.json      # URL exact-match + semantic dedup (ChromaDB, cosine ≥ 0.80)
├── compress.json   # per-source semantic compression + theme clustering
├── enrich.json     # HN/Reddit top-comment summaries (community sentiment)
├── digest.json     # cross-source deep summary
├── tldr.json       # one-paragraph "today's highlights" for the showcase site
├── judge.json      # LLM-as-Judge quality scoring (3 dimensions)
├── compose_tg.json # two Telegram messages (Telegram-safe HTML)
└── alerts.json     # per-step failure records (batched into one TG alert)
report.md / vault.done / telegram.done   # final report + delivery sentinels
```

**Agent vs Tool separation:**
- **Agent** — owns LLM reasoning and execution state (`DailyBriefAgent`, `steps/`)
- **Tool** — pure functions, deterministic, no LLM (`tools/fetchers/`, `tools/notifiers/`, `tools/vector_store/`), independently testable

**Full pipeline (14 idempotent steps):**

```
hatena · hn · reddit · security · rss   →  dedup  →  compress  →  enrich
   →  digest  →  tldr  →  judge  →  report  →  save  →  compose_tg  →  notify  →  deploy
```

Each step writes a JSON artifact. Re-runs skip completed steps unless `--force` is given; `--only` runs a single step. The RUN / LOAD / SKIP gating is a single pure function (`step_cache.decide`); every step is a subclass of a shared `Step` base (`step.py`) whose only public surface is `run(ctx, input) -> StepOutcome`.

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Local-only `LLMBackend` (Protocol) | Fixed on `LocalLLMBackend` (LM Studio, OpenAI-compatible); the Protocol keeps the agent code backend-agnostic without hardcoding a vendor |
| Artifact-based idempotency | LLM calls are expensive; every step caches to disk so any step is re-runnable in isolation without breaking the pipeline |
| Single `Step` base + `step_cache.decide` | The RUN/LOAD/SKIP decision lives in one pure function; per-step logic lives behind fixed seams (`_produce`/`_load`/`_guard`), not scattered gating |
| `prompts.py` as single source of truth | Agent code never contains raw prompt strings — all prompts versioned in one place |
| `json-repair` as third-layer fallback | Local models emit malformed JSON that prompting alone can't reliably fix |
| LLM-as-Judge with independent model | Quality gate runs on a separate model (`gemma-4-e4b`); low `completeness` triggers a reflect-and-regenerate loop; scores accumulate in `_judge-history.json` |
| Semantic dedup before compress | URL exact-match (7-day window) + embedding cosine ≥ 0.80 filters near-duplicates so downstream LLM tokens aren't wasted on repeats |
| Observability decoupled from steps (`health.py`) | Post-hoc trace derives a per-run Health Record; chronic failures (same subject ≥3× in 7 days) escalate to Telegram, single flakes stay silent |
| Lint scripts over documentation | Interface contracts are machine-enforced; agents self-correct from error messages |

---

## Engineering Challenges

**Local LLM output instability** — three-layer JSON fallback:
```python
m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
text = m.group(1) if m else raw
try:
    return json.loads(text)
except json.JSONDecodeError:
    return json.loads(repair_json(text))
```

**Telegram HTML constraints** — a regex sanitizer strips every tag outside the Telegram-allowed set (`<b> <i> <u> <s> <a> <code> <pre>`) before sending, preventing API 400 errors; a truncation guard never cuts a tag mid-way.

**Silent degradation** — the pipeline is resilient (ships on ≥2 healthy sources) but that hides failures. `health.py` records each run and only escalates *chronic* failures across days, so a single transient flake doesn't page you.

**playwright-cli daemon lifecycle** — `Popen` background launch + polling for session readiness before issuing eval commands (used by the HN fetcher).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ (type annotations, Protocol, frozen dataclass) |
| LLM Backend | LM Studio (local, OpenAI-compatible `/v1/chat/completions`) |
| Primary Model | Qwen3.6 27B (MLX) — `qwen/qwen3.6-27b` |
| Judge Model | Gemma 4 E4B — `google/gemma-4-e4b` (independent, swappable) |
| Embeddings / Dedup | `Qwen3-Embedding-0.6B-4bit-DWQ` (MLX) + ChromaDB PersistentClient |
| Web Scraping | playwright-cli (JS rendering), curl / urllib + feedparser (RSS / JSON API) |
| Data Sources | Hatena Bookmark RSS, Hacker News, Reddit (16 subreddits), security blogs, RSS feeds |
| Notification | Telegram Bot API (HTML parse_mode, self-contained) |
| Knowledge Base | Obsidian vault (Markdown + frontmatter, optional) |
| Showcase | Static site force-pushed to `gh-pages` via an isolated git worktree |
| Scheduler | crontab (two-stage: `load_model.py` at 01:45, `main.py` at 02:00) |
| Testing / Linting | pytest, ruff, interface lint scripts |

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure the local LLM backend (defaults shown)
export LOCAL_LLM_URL=http://localhost:1234
export LOCAL_LLM_MODEL=qwen/qwen3.6-27b

# Run the daily brief
python3 main.py "/daily-brief"

# URL digest
python3 main.py "幫我摘要這些連結 https://example.com"
```

### Step control (daily-brief)

```bash
# Force re-run specific steps (ignore today's cached artifact)
python3 main.py "/daily-brief --force hatena hn"
python3 main.py "/daily-brief --force report"    # regenerate report (no re-fetch)
python3 main.py "/daily-brief --force notify"    # resend Telegram

# Run only specific steps
python3 main.py "/daily-brief --only report notify"

# Read-only health query (no model load, no pipeline) — prints a 7-day success-rate table
python3 main.py "/daily-brief --health"
```

Valid step names: `hatena · hn · reddit · security · rss · dedup · compress · enrich · digest · tldr · judge · report · save · compose_tg · notify · deploy`

### Configuration

All machine-specific values live in a project-root `.env` (template: `.env.example`) — no paths or credentials in source.

| Setting | Env var | Required? | If unset |
|---------|---------|-----------|----------|
| Local LLM | `LOCAL_LLM_URL` / `LOCAL_LLM_MODEL` | No (has default) | `localhost:1234` / `qwen/qwen3.6-27b` |
| Judge model | `JUDGE_LLM_URL` / `JUDGE_LLM_MODEL` | No | Same URL as main LLM / `gemma-4-e4b` |
| Telegram | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Optional | Silently skips push & alerts |
| Obsidian vault | `VAULT_ROOT` | Optional | `save` step skipped |
| Showcase deploy | `DEPLOY_GITHUB_TOKEN` | Optional | Pushes via `origin` credential helper |

### Scheduling via crontab

Two-stage scheduling — the model is warmed up 15 minutes before the pipeline runs:

```bash
# Stage 1: load_model (01:45)
(crontab -l 2>/dev/null; echo "45 1 * * * cd $HOME/Workspace/agent && /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 load_model.py >> /tmp/load_model.log 2>&1") | crontab -

# Stage 2: daily-brief (02:00)
(crontab -l 2>/dev/null; echo "0 2 * * * cd $HOME/Workspace/agent && /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 main.py \"/daily-brief\" >> /tmp/daily_brief.log 2>&1") | crontab -

crontab -l   # verify
```

`load_model.py` handles LM Studio auto-start → model load → 600s API stabilization; `main.py` re-checks readiness via `ensure_llm_ready()` as a final safety net at 02:00.

---

## Results

- Processes **100+ articles/day** across 5 sources × multiple scraping strategies
- **14 independent steps**, any step re-runnable without breaking the pipeline
- Local LLM keeps API cost near zero
- **LLM-as-Judge** daily quality tracking (relevance / completeness / faithfulness) with an automatic reflect-and-regenerate loop on low completeness
- **Semantic dedup** cuts redundant LLM tokens (7-day window, cosine ≥ 0.80)
- **Health observability** with chronic-failure escalation — a single transient flake stays silent, a persistent one pages you

---

## Project Structure

```
main.py                          # router + entry point
load_model.py                    # crontab pre-loader (LM Studio + model warm-up)

agents/daily_brief/
├── agent.py                     # DailyBriefAgent.run() — pure pipeline map
├── step.py                      # Step base (run → produce/load/guard seams)
├── step_cache.py                # decide(in_steps, exists, forced) → RUN/LOAD/SKIP
├── codecs.py                    # ArtifactCodec (Json/Text/Sentinel)
├── schemas.py                   # typed read-only views over step artifacts
├── health.py                    # observability: Health Record + chronic-failure detection
├── supervisor.py                # LLM supervisor (fetch quality control)
├── prompts.py / reflect_prompts.py
├── config.py                    # sources, thresholds, retry config, paths
├── steps/                       # source · dedup · compress · enrich · digest ·
│                                #   tldr · judge · report · save · compose_tg · notify · deploy
└── fetchers/

tools/
├── fetchers/                    # pure fetch functions (hatena/hn/reddit/security/rss + comments)
├── vector_store/                # ChromaDB + MLX embedder (semantic dedup)
├── lms_lifecycle.py             # lms CLI model load/unload
└── notifiers/telegram.py        # self-contained Telegram sender (project .env)

config/settings.py               # LocalLLMBackend + LLM readiness probe
lint/
├── check_agent_interface.py     # enforces AGENT_NAME + run()
└── check_fetcher_interface.py   # enforces fetch()
```

See [AGENTS.md](AGENTS.md) for agent routing and the extension guide, and [CLAUDE.md](CLAUDE.md) for the full design rationale.

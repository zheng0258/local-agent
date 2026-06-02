# AI Daily Brief Agent

A production-grade multi-agent pipeline that aggregates daily tech trends from 4 sources, scores and summarizes them with LLMs, and delivers a digest to Telegram — running on a local LLM with near-zero API cost.

[中文說明](README.zh.md)

---

## Architecture

```
main.py ──→ DailyBriefAgent
                │
    ┌───────────┼───────────────────────┐
    ▼           ▼                       ▼
tools/fetchers/ config/settings.py  tools/notifiers/
(pure functions, no LLM)             telegram.py
hatena / hn / reddit / security
    │
    ▼
steps/{name}.json   ← per-step artifact cache
├── hatena.json     # fetch + LLM interest scoring
├── hn.json
├── reddit.json
├── security.json
├── compress.json   # semantic compression + theme clustering
├── digest.json     # cross-source deduplication + summary
└── judge.json      # LLM-as-Judge quality scoring (3 dimensions)
report.md / telegram.done / vault.done
```

**Agent vs Tool separation:**
- **Agent** — owns LLM reasoning and execution state (`DailyBriefAgent`)
- **Tool** — pure functions, deterministic, no LLM (fetchers, notifiers), independently testable

**Pipeline steps:** `fetch → compress → digest → judge → report → save → notify`

Each step produces a JSON artifact. Steps are idempotent — re-runs skip completed steps unless `--force` is specified.

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| `LLMBackend` Protocol (not ABC) | Duck typing — swap local LLM ↔ Anthropic API without changing agent code |
| Artifact-based idempotency | LLM calls are expensive; explicit per-step control avoids redundant re-runs |
| `prompts.py` as single source of truth | Agent code never contains raw prompt strings — all prompts versioned in one place |
| `json-repair` as third-layer fallback | Local models produce malformed JSON that prompting alone can't fix reliably |
| LLM-as-Judge with independent backend | Quality gate runs on a separate model; `completeness < 3` triggers `quality_alert`; scores accumulate in `_judge-history.json` for trend tracking |
| Few-shot scoring examples | Rule descriptions alone are unstable at score boundaries (`**` vs `*`); named examples significantly improve consistency |
| Python pre-filter before compress | LLM silently drops `***` articles — pre-filtering to starred-only and marking them "do not drop" in the prompt is more reliable than post-hoc fallback |
| Lint scripts over documentation | Interface contracts are machine-enforced; AI agents can self-correct from error messages |

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

**Telegram HTML constraints** — regex sanitizer strips unsupported tags before sending to prevent Telegram API 400 errors.

**playwright-cli daemon lifecycle** — `Popen` background launch + polling for session readiness before issuing eval commands.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 (type annotations, Protocol, dataclass) |
| LLM Backend | LM Studio (local, OpenAI-compatible) / Anthropic Claude API |
| Primary Model | Qwen 3.5 27B (Claude 4.6 Opus distilled, MLX) |
| Web Scraping | playwright-cli (JS rendering), curl / urllib (RSS / JSON API) |
| Data Sources | Hatena Bookmark RSS, Hacker News, Reddit (16 subreddits), security blogs |
| Notification | Telegram Bot API (HTML parse_mode) |
| Knowledge Base | Obsidian vault (Markdown + frontmatter) |
| Scheduler | crontab (two-stage: load_model.py at 01:45, main.py at 02:00) |
| Testing | pytest (unit + integration) |
| Linting | ruff, interface lint scripts |

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure LLM backend
export LOCAL_LLM_URL=http://localhost:1234          # local LLM (default)
export LOCAL_LLM_MODEL=qwen3.6-35b-a3b
# or: export ANTHROPIC_API_KEY=sk-ant-...           # Anthropic API

# Run daily brief
python3 main.py "/daily-brief"

# Re-run specific steps
python3 main.py "/daily-brief --force report notify"
python3 main.py "/daily-brief --only notify"
```

### Scheduling via crontab

Two-stage scheduling — model pre-loaded 15 minutes before the pipeline runs:

```bash
# load_model entry
(crontab -l 2>/dev/null; echo "45 1 * * * cd $HOME/Workspace/agent && /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 load_model.py >> /tmp/load_model.log 2>&1") | crontab -

# daily-brief entry
(crontab -l 2>/dev/null; echo "0 2 * * * cd $HOME/Workspace/agent && /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 main.py \"/daily-brief\" >> /tmp/daily_brief.log 2>&1") | crontab -

# verify
crontab -l
```

`load_model.py` handles: LM Studio auto-start → model load → 600s API stabilization → Telegram alert on failure.

---

## Results

- Processes **100+ articles/day** from 4 sources × multiple scraping strategies
- **10 independent steps**, any step re-runnable without breaking the pipeline
- Local LLM (Qwen 27B) keeps API cost near zero; cloud API as fallback
- **LLM-as-Judge** daily quality tracking with `quality_alert` on low completeness scores
- **Source health monitoring** — auto-warns when any source returns 0 articles

---

## Project Structure

```
main.py                       # router + entry point
load_model.py                 # crontab pre-loader (LM Studio + model warm-up)
agents/daily_brief/
├── agent.py                  # DailyBriefAgent
├── prompts.py                # all LLM prompts
└── config.py
tools/
├── fetchers/                 # pure fetch functions
├── lms_lifecycle.py          # lms CLI model load/unload
└── notifiers/telegram.py
config/settings.py            # LLMBackend switching
lint/
├── check_agent_interface.py
└── check_fetcher_interface.py
```

See [AGENTS.md](AGENTS.md) for agent routing and extension guide.

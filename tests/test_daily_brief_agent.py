import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from agents.daily_brief.agent import ALL_STEPS, FETCH_STEPS
from agents.daily_brief.config import STEP_CONFIGS
from tests.fakes import FakeSupervisor


def _make_agent(llm_response: str):
    from agents.daily_brief.agent import DailyBriefAgent

    mock_llm = MagicMock()
    mock_llm.complete.return_value = llm_response
    return DailyBriefAgent(llm=mock_llm)


def test_all_steps_contains_compress_and_judge():
    assert "compress" in ALL_STEPS
    assert "judge" in ALL_STEPS
    assert "digest" in ALL_STEPS
    assert "save" in ALL_STEPS


def test_all_steps_contains_dedup():
    assert "dedup" in ALL_STEPS


def test_all_steps_order():
    assert ALL_STEPS.index("security") < ALL_STEPS.index("dedup")
    assert ALL_STEPS.index("dedup") < ALL_STEPS.index("compress")
    assert ALL_STEPS.index("compress") < ALL_STEPS.index("digest")
    assert ALL_STEPS.index("digest") < ALL_STEPS.index("judge")
    assert ALL_STEPS.index("judge") < ALL_STEPS.index("report")
    assert ALL_STEPS.index("digest") < ALL_STEPS.index("report")
    assert ALL_STEPS.index("report") < ALL_STEPS.index("save")
    assert ALL_STEPS.index("save") < ALL_STEPS.index("notify")


def test_fetch_steps_unchanged():
    assert FETCH_STEPS == ["hatena", "hn", "reddit", "security", "rss"]


@pytest.mark.unit
def test_every_wired_step_has_supervisor_config():
    # 回歸防護：每個 ALL_STEPS 步驟都必須在 STEP_CONFIGS 有條目，否則
    # supervisor.run_step 的 `STEP_CONFIGS[name]` 會 KeyError 並 crash 整條
    # pipeline。fake-supervisor 的 step 測試蓋不到真 supervisor 查表，故在此
    # 加結構不變量守住（#6 deploy / #9 tldr 曾雙雙漏配）。
    missing = [s for s in ALL_STEPS if s not in STEP_CONFIGS]
    assert missing == [], f"STEP_CONFIGS 缺少步驟設定：{missing}"


def test_run_digest_returns_digests_list():
    llm_resp = json.dumps(
        {
            "digests": [
                {
                    "title": "測試",
                    "url": "https://example.com",
                    "source": "HN",
                    "interest": "***",
                    "summary": "摘要",
                }
            ]
        }
    )
    agent = _make_agent(llm_resp)

    compress_data = {
        "hatena": {"themes": [], "articles": []},
        "hn": {
            "themes": ["AI"],
            "articles": [
                {
                    "title": "t",
                    "url": "https://example.com",
                    "one_liner": "x",
                    "interest": "***",
                }
            ],
        },
        "reddit": {"themes": [], "articles": []},
        "security": {"themes": [], "articles": []},
    }
    digests, digest_data = agent._run_digest(compress_data)
    assert isinstance(digests, list)
    assert len(digests) == 1
    assert digests[0]["title"] == "測試"
    assert "generated_at" in digest_data
    assert digest_data["digests"] == digests


def test_run_tldr_returns_plaintext_english():
    # issue #9：_run_tldr 回傳 LLM 純文字（strip 後）
    agent = _make_agent("  Today AI tooling and security dominated.  ")
    digests = [{"title": "t", "url": "https://example.com", "summary": "s"}]
    out = agent._run_tldr(digests)
    assert out == "Today AI tooling and security dominated."


def test_run_report_deduplicates_by_url():
    agent = _make_agent("# 趨勢話題：2026-04-12\n\n## Hatena\n")

    compress_data = {
        "hatena": {"themes": [], "articles": []},
        "hn": {"themes": [], "articles": []},
        "reddit": {"themes": [], "articles": []},
        "security": {"themes": [], "articles": []},
    }
    digests = [
        {"title": "A", "url": "https://example.com/1", "source": "HN", "summary": "s"},
        {
            "title": "B",
            "url": "https://example.com/1",
            "source": "Hatena",
            "summary": "s",
        },
        {"title": "C", "url": "https://example.com/2", "source": "HN", "summary": "s"},
    ]
    content = agent._run_report(compress_data, digests, "2026-04-12")
    assert "趨勢話題" in content

    call_args = agent._llm.complete.call_args[0][0]
    assert call_args.count("example.com/1") == 1


def test_run_report_returns_llm_output_directly():
    """新版 _run_report 直接回傳 LLM 輸出的純 markdown，無需 JSON 解析。"""
    raw_markdown = "# 趨勢話題：2026-04-12\n\n## Hatena"
    agent = _make_agent(raw_markdown)
    content = agent._run_report(
        {
            "hatena": {"themes": [], "articles": []},
            "hn": {"themes": [], "articles": []},
            "reddit": {"themes": [], "articles": []},
            "security": {"themes": [], "articles": []},
        },
        [],
        "2026-04-12",
    )
    assert content == raw_markdown


def test_run_compress_returns_dict_with_all_sources():
    llm_resp = json.dumps({"themes": ["AI"], "articles": []})
    agent = _make_agent(llm_resp)
    source_data = {
        "hatena": {
            "articles": [
                {
                    "title": "T",
                    "url": "u",
                    "interest": "***",
                    "score": 100,
                    "category": "AI",
                    "source": "hatena",
                }
            ]
        },
        "hn": {"articles": []},
        "reddit": {"articles": []},
        "security": {"articles": []},
    }
    result = agent._run_compress(source_data)
    assert set(result.keys()) >= {"hatena", "hn", "reddit", "security"}
    assert "themes" in result["hatena"]
    assert "_meta" in result
    assert "compressed_at" in result["_meta"]
    assert "compressed_at" not in {k for k in result if k != "_meta"}


def test_run_compress_prefilters_to_starred_only():
    """_run_compress 應在呼叫 LLM 前，Python 層先篩選出 *** 文章。"""
    from agents.daily_brief.agent import DailyBriefAgent

    captured_prompts: list[str] = []

    def capture_complete(prompt: str, system: str = "") -> str:
        captured_prompts.append(prompt)
        return json.dumps({"themes": ["AI"], "articles": []})

    mock_llm = MagicMock()
    mock_llm.complete.side_effect = capture_complete
    agent = DailyBriefAgent(llm=mock_llm)

    source_data = {
        "hatena": {"articles": []},
        "hn": {
            "articles": [
                {
                    "title": "A",
                    "url": "https://hn.com/1",
                    "interest": "***",
                    "score": 900,
                },
                {
                    "title": "B",
                    "url": "https://hn.com/2",
                    "interest": "**",
                    "score": 200,
                },
                {"title": "C", "url": "https://hn.com/3", "interest": "*", "score": 50},
            ]
        },
        "reddit": {"articles": []},
        "security": {"articles": []},
    }
    agent._run_compress(source_data)

    # hn 的 prompt 中只應包含 *** 文章的 URL
    hn_prompt = next(p for p in captured_prompts if "hn.com/1" in p)
    assert "hn.com/1" in hn_prompt  # *** 保留
    assert "hn.com/2" not in hn_prompt  # ** 過濾掉
    assert "hn.com/3" not in hn_prompt  # * 過濾掉


def test_run_judge_reads_missed_urls_from_top_level():
    """_run_judge 應從頂層 missed_urls 讀取（新 schema），不從 completeness 底下讀。"""
    import json
    from agents.daily_brief.agent import DailyBriefAgent

    llm_resp = json.dumps(
        {
            "scores": {
                "relevance": {"score": 5, "reasoning": "ok"},
                "completeness": {"score": 2, "reasoning": "遺漏部分文章"},
                "faithfulness": {"score": 5, "reasoning": "ok"},
            },
            "missed_urls": [
                "https://example.com/missed1",
                "https://example.com/missed2",
            ],
        }
    )
    mock_judge = MagicMock()
    mock_judge.complete.return_value = llm_resp
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=mock_judge)

    result = agent._run_judge({}, [])
    completeness = result.get("scores", {}).get("completeness", {})
    assert completeness.get("missed_urls") == [
        "https://example.com/missed1",
        "https://example.com/missed2",
    ]


def test_run_judge_returns_scores_and_overall():
    llm_resp = json.dumps(
        {
            "scores": {
                "relevance": {"score": 4, "reasoning": "OK"},
                "completeness": {
                    "score": 3,
                    "reasoning": "missed one",
                    "missed_urls": [],
                },
                "faithfulness": {"score": 5, "reasoning": "accurate"},
            },
            "overall": 4.0,
        }
    )
    from agents.daily_brief.agent import DailyBriefAgent

    mock_judge = MagicMock()
    mock_judge.complete.return_value = llm_resp
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=mock_judge)
    compress_data = {"hatena": {"themes": [], "articles": []}}
    digests = [
        {
            "title": "T",
            "url": "https://u.com",
            "source": "HN",
            "interest": "***",
            "summary": "s",
        }
    ]
    result = agent._run_judge(compress_data, digests)

    assert result["scores"]["relevance"]["score"] == 4
    assert result["overall"] == 4.0
    assert "judged_at" in result
    assert "judge_model" in result


def test_run_save_creates_vault_files(tmp_path):
    import agents.daily_brief.config as cfg

    original = cfg.VAULT_DAILY_BRIEF_DIR
    cfg.VAULT_DAILY_BRIEF_DIR = tmp_path / "vault" / "daily-brief"

    try:
        agent = _make_agent("{}")
        day_dir = tmp_path / "outputs" / "2026-04-12"
        day_dir.mkdir(parents=True)
        (day_dir / "report.md").write_text("# 報告", encoding="utf-8")

        digests = [
            {
                "title": "測試文章",
                "url": "https://example.com",
                "source": "HN",
                "interest": "***",
                "summary": "這是摘要。",
            }
        ]

        agent._run_save(day_dir, "2026-04-12", digests)

        vault_report = cfg.VAULT_DAILY_BRIEF_DIR / "2026-04-12.md"
        vault_digest = cfg.VAULT_DAILY_BRIEF_DIR / "2026-04-12-digest.md"

        assert vault_report.exists()
        assert vault_report.read_text(encoding="utf-8") == "# 報告"
        assert vault_digest.exists()
        content = vault_digest.read_text(encoding="utf-8")
        assert "created: 2026-04-12" in content
        assert "測試文章" in content
        assert "這是摘要。" in content
    finally:
        cfg.VAULT_DAILY_BRIEF_DIR = original


def test_format_obsidian_digest_frontmatter():
    from agents.daily_brief.agent import _format_obsidian_digest

    digests = [
        {"title": "A", "url": "https://a.com", "source": "HN", "summary": "摘要 A"}
    ]
    result = _format_obsidian_digest(digests, "2026-04-12")
    assert result.startswith("---")
    assert "created: 2026-04-12" in result
    assert "tags: [daily-brief, digest]" in result
    assert "## A" in result
    assert "https://a.com" in result


def test_compose_tg_extracts_overview_and_digest_text():
    # compose 半邊：兩次 LLM 生成 → 解包出純文字（#12 拆分後 _notify 不再生成）
    from agents.daily_brief.agent import DailyBriefAgent

    responses = [
        json.dumps({"tg_overview": "overview text"}),
        json.dumps({"tg_digest": "digest text"}),
    ]
    mock_llm = MagicMock()
    mock_llm.complete.side_effect = responses
    agent = DailyBriefAgent(llm=mock_llm)

    digests = [{"title": "T", "url": "https://u.com", "source": "HN", "summary": "s"}]
    composed = agent._run_compose_tg(digests, "2026-04-12")

    assert composed == {"overview": "overview text", "digest": "digest text"}


def test_parse_args_supports_new_steps():
    from agents.daily_brief.agent import _parse_args

    force, _ = _parse_args("--force compress digest save judge")
    assert "compress" in force
    assert "digest" in force
    assert "save" in force
    assert "judge" in force

    _, only = _parse_args("--only compress save notify")
    assert only == {"compress", "save", "notify"}


def test_all_steps_count():
    assert len(ALL_STEPS) == 16


def test_all_steps_contains_compose_tg_before_notify():
    # issue #12：compose（生成）排在 notify（send-only）之前
    assert "compose_tg" in ALL_STEPS
    assert ALL_STEPS.index("save") < ALL_STEPS.index("compose_tg")
    assert ALL_STEPS.index("compose_tg") < ALL_STEPS.index("notify")


def test_parse_args_supports_compose_tg_step():
    from agents.daily_brief.agent import _parse_args

    force, _ = _parse_args("--force compose_tg")
    assert "compose_tg" in force
    _, only = _parse_args("--only compose_tg notify")
    assert only == {"compose_tg", "notify"}


def test_all_steps_contains_tldr_after_digest():
    # issue #9：tldr 在 digest 之後接線
    assert "tldr" in ALL_STEPS
    assert ALL_STEPS.index("digest") < ALL_STEPS.index("tldr")
    assert ALL_STEPS.index("tldr") < ALL_STEPS.index("judge")


def test_parse_args_supports_tldr_step():
    from agents.daily_brief.agent import _parse_args

    force, _ = _parse_args("--force tldr")
    assert "tldr" in force
    _, only = _parse_args("--only tldr")
    assert only == {"tldr"}


def test_all_steps_contains_deploy_after_notify():
    assert "deploy" in ALL_STEPS
    assert ALL_STEPS.index("notify") < ALL_STEPS.index("deploy")


def test_parse_args_supports_deploy_step():
    from agents.daily_brief.agent import _parse_args

    force, _ = _parse_args("--force deploy")
    assert "deploy" in force
    _, only = _parse_args("--only deploy")
    assert only == {"deploy"}


def test_all_steps_contains_enrich():
    assert "enrich" in ALL_STEPS
    assert ALL_STEPS.index("compress") < ALL_STEPS.index("enrich")
    assert ALL_STEPS.index("enrich") < ALL_STEPS.index("digest")


# ── parse_llm_json robustness ───────────────────────────────────────────────


def test_run_judge_logs_warning_when_completeness_below_threshold():
    """completeness < 3 時應在回傳結果中標記 quality_alert。"""
    from agents.daily_brief.agent import DailyBriefAgent

    llm_resp = json.dumps(
        {
            "scores": {
                "relevance": {"score": 5, "reasoning": "ok"},
                "completeness": {
                    "score": 2,
                    "reasoning": "missed many",
                    "missed_urls": ["https://a.com"],
                },
                "faithfulness": {"score": 5, "reasoning": "ok"},
            },
        }
    )
    mock_judge = MagicMock()
    mock_judge.complete.return_value = llm_resp
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=mock_judge)

    result = agent._run_judge({}, [])
    assert result.get("quality_alert") is True
    assert "completeness" in result.get("quality_alert_reason", "")


def test_run_judge_no_alert_when_completeness_sufficient():
    """completeness >= 3 時不應有 quality_alert。"""
    from agents.daily_brief.agent import DailyBriefAgent

    llm_resp = json.dumps(
        {
            "scores": {
                "relevance": {"score": 4, "reasoning": "ok"},
                "completeness": {"score": 3, "reasoning": "ok", "missed_urls": []},
                "faithfulness": {"score": 4, "reasoning": "ok"},
            },
        }
    )
    mock_judge = MagicMock()
    mock_judge.complete.return_value = llm_resp
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=mock_judge)

    result = agent._run_judge({}, [])
    assert not result.get("quality_alert")


def test_run_judge_appends_to_history(tmp_path):
    """每次 judge 執行後應將當日分數 append 至 _judge-history.json。"""
    import agents.daily_brief.config as cfg

    original = cfg.OUTPUT_DIR
    cfg.OUTPUT_DIR = tmp_path

    try:
        from agents.daily_brief.agent import DailyBriefAgent

        llm_resp = json.dumps(
            {
                "scores": {
                    "relevance": {"score": 5, "reasoning": "ok"},
                    "completeness": {"score": 4, "reasoning": "ok", "missed_urls": []},
                    "faithfulness": {"score": 5, "reasoning": "ok"},
                },
            }
        )
        mock_judge = MagicMock()
        mock_judge.complete.return_value = llm_resp
        agent = DailyBriefAgent(llm=MagicMock(), judge_llm=mock_judge)

        agent._run_judge({}, [], date="2026-04-14")

        history_file = tmp_path / "_judge-history.json"
        assert history_file.exists(), "_judge-history.json 應被建立"
        history = json.loads(history_file.read_text(encoding="utf-8"))
        assert isinstance(history, list)
        assert len(history) == 1
        assert history[0]["date"] == "2026-04-14"
        assert history[0]["overall"] == 4.7
    finally:
        cfg.OUTPUT_DIR = original


def test_run_judge_history_accumulates_across_runs(tmp_path):
    """多次執行應累積歷史，不覆蓋舊記錄。"""
    import agents.daily_brief.config as cfg

    original = cfg.OUTPUT_DIR
    cfg.OUTPUT_DIR = tmp_path

    try:
        from agents.daily_brief.agent import DailyBriefAgent

        llm_resp = json.dumps(
            {
                "scores": {
                    "relevance": {"score": 4, "reasoning": "ok"},
                    "completeness": {"score": 4, "reasoning": "ok", "missed_urls": []},
                    "faithfulness": {"score": 4, "reasoning": "ok"},
                },
            }
        )
        for date_str in ("2026-04-13", "2026-04-14"):
            mock_judge = MagicMock()
            mock_judge.complete.return_value = llm_resp
            agent = DailyBriefAgent(llm=MagicMock(), judge_llm=mock_judge)
            agent._run_judge({}, [], date=date_str)

        history = json.loads(
            (tmp_path / "_judge-history.json").read_text(encoding="utf-8")
        )
        assert len(history) == 2
        assert {r["date"] for r in history} == {"2026-04-13", "2026-04-14"}
    finally:
        cfg.OUTPUT_DIR = original


def test_source_health_warns_on_zero_articles():
    """_check_source_health 對 0 篇 *** 的來源應回傳 warning list。"""
    from agents.daily_brief.agent import DailyBriefAgent

    compress_data = {
        "hatena": {"themes": ["AI"], "articles": [{"interest": "***", "url": "u1"}]},
        "hn": {"themes": [], "articles": []},
        "reddit": {"themes": ["資安"], "articles": [{"interest": "***", "url": "u2"}]},
        "security": {"themes": [], "articles": []},
    }
    warnings = DailyBriefAgent._check_source_health(compress_data)
    assert "hn" in warnings
    assert "security" in warnings
    assert "hatena" not in warnings
    assert "reddit" not in warnings


def test_parse_json_recovers_from_fullwidth_colon():
    """HN 情境：LLM 用全形冒號 '：' 作為 key-value 分隔符導致無效 JSON。"""
    from config.utils import parse_llm_json

    broken = (
        "```json\n"
        "{\n"
        '  "articles": [\n'
        '    {"title": "正常文章", "url": "https://example.com", "score": 100, "interest": "**"},\n'
        '    {"title：有全形冒號的標題", "url": "https://example2.com", "score": 50, "interest": "*"},\n'
        '    {"title": "另一篇正常文章", "url": "https://example3.com", "score": 200, "interest": "***"}\n'
        "  ]\n"
        "}\n"
        "```"
    )
    result = parse_llm_json(broken)
    assert "raw" not in result, "全形冒號應被修復，不應 fallback 到 raw"
    assert "articles" in result
    assert len(result["articles"]) == 3


def test_parse_json_recovers_from_unescaped_quotes_in_value():
    """Reddit 情境：字串值內含未逸脫雙引號導致無效 JSON。"""
    from config.utils import parse_llm_json

    broken = (
        "```json\n"
        "{\n"
        '  "articles": [\n'
        '    {"title": "IBM settles but pays $17M | under "Civil Rights Fraud Initiative."", '
        '"url": "https://reddit.com/r/tech/1", "score": 500, "interest": "***"}\n'
        "  ]\n"
        "}\n"
        "```"
    )
    result = parse_llm_json(broken)
    assert "raw" not in result, "未逸脫引號應被修復，不應 fallback 到 raw"
    assert "articles" in result
    assert len(result["articles"]) == 1


def test_run_judge_passes_slim_compress_to_llm():
    """_run_judge 應只傳 url + one_liner 給 judge LLM，不傳完整文章內容。"""
    from agents.daily_brief.agent import DailyBriefAgent

    llm_resp = json.dumps(
        {
            "scores": {
                "relevance": {"score": 4, "reasoning": "ok"},
                "completeness": {"score": 4, "reasoning": "ok", "missed_urls": []},
                "faithfulness": {"score": 4, "reasoning": "ok"},
            },
        }
    )
    mock_judge = MagicMock()
    mock_judge.complete.return_value = llm_resp
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=mock_judge)

    compress_data = {
        "hatena": {
            "themes": ["AI"],
            "articles": [
                {
                    "title": "完整標題文字不應出現在 judge prompt",
                    "url": "https://example.com/1",
                    "one_liner": "核心摘要",
                    "interest": "***",
                    "bookmarks": 999,
                    "extra_field": "不需要的資料",
                }
            ],
        },
        "hn": {"themes": [], "articles": []},
        "reddit": {"themes": [], "articles": []},
        "security": {"themes": [], "articles": []},
    }
    digests = [
        {
            "title": "T",
            "url": "https://example.com/1",
            "source": "Hatena",
            "summary": "s",
        }
    ]
    agent._run_judge(compress_data, digests)

    call_prompt = mock_judge.complete.call_args[0][0]
    assert "https://example.com/1" in call_prompt  # URL 保留
    assert "核心摘要" in call_prompt  # one_liner 保留
    assert "完整標題文字不應出現在 judge prompt" not in call_prompt  # title 移除
    assert "extra_field" not in call_prompt  # 額外欄位移除
    assert "bookmarks" not in call_prompt  # 數值欄位移除


def test_compose_tg_msg2_balances_and_caps_digests():
    """compose msg2 應跨來源均衡挑選，且不超過 _TG_DIGEST_MAX_ITEMS 則（單封 4096 限制）。"""
    from agents.daily_brief.agent import DailyBriefAgent, _TG_DIGEST_MAX_ITEMS

    responses = [
        json.dumps({"tg_overview": "overview"}),
        json.dumps({"tg_digest": "digest"}),
    ]
    mock_llm = MagicMock()
    mock_llm.complete.side_effect = responses
    agent = DailyBriefAgent(llm=mock_llm)

    # 20 篇單一來源 digests
    digests = [
        {
            "title": f"Article {i}",
            "url": f"https://example.com/{i}",
            "source": "HN",
            "summary": "s",
        }
        for i in range(20)
    ]

    agent._run_compose_tg(digests, "2026-04-14")

    all_prompts = [c[0][0] for c in mock_llm.complete.call_args_list]
    msg2_prompt = next(p for p in all_prompts if "深度摘要（" in p)
    last_in = _TG_DIGEST_MAX_ITEMS - 1  # 最後一篇 index
    assert f"example.com/{last_in}" in msg2_prompt  # 第 N 篇應在 msg2
    assert (
        f"example.com/{_TG_DIGEST_MAX_ITEMS}" not in msg2_prompt
    )  # 第 N+1 篇不應在（超過上限）


def test_pick_top8_balanced_round_robins_across_sources():
    """_pick_top8_balanced 應跨來源 round-robin，確保少數來源不被多數來源淹沒。"""
    from agents.daily_brief.agent import _pick_top8_balanced

    digests = [
        {"title": f"hn{i}", "url": f"u/hn/{i}", "_source": "hn"} for i in range(10)
    ] + [{"title": "rd0", "url": "u/rd/0", "_source": "reddit"}]

    picked = _pick_top8_balanced(digests, n=6)
    sources = [d["_source"] for d in picked]

    assert len(picked) == 6
    assert "reddit" in sources  # 少數來源仍被選入
    assert sources.count("reddit") == 1  # reddit 僅 1 篇，不應重複


def test_run_judge_step_is_wrapped_by_supervisor(tmp_path):
    """run() 的 judge 階段應透過 supervisor.run_step 執行。"""
    import agents.daily_brief.agent as agent_module
    from agents.daily_brief.agent import DailyBriefAgent

    today = date.today().strftime("%Y-%m-%d")
    steps_dir = tmp_path / today / "steps"
    steps_dir.mkdir(parents=True)
    (steps_dir / "compress.json").write_text(
        json.dumps({"hatena": {"themes": [], "articles": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (steps_dir / "digest.json").write_text(
        json.dumps({"digests": [{"url": "https://example.com/1"}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    sup = FakeSupervisor(forbid_reflect=True)
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())
    agent._run_judge = MagicMock(return_value={"overall": 4.2})

    with patch.object(agent_module, "OUTPUT_DIR", tmp_path), patch(
        "agents.daily_brief.supervisor.SupervisorAgent",
        lambda **kw: sup,
    ), patch("agents.daily_brief.steps.judge.check_local_llm", return_value=True):
        agent.run("--only judge")

    assert "judge" in sup.calls
    agent._run_judge.assert_called_once()


def test_judge_feedback_loop_uses_new_digests_for_retry(tmp_path):
    """judge feedback 重評時應使用 digest 重跑後的新資料。"""
    import agents.daily_brief.agent as agent_module
    from agents.daily_brief.agent import DailyBriefAgent

    today = date.today().strftime("%Y-%m-%d")
    steps_dir = tmp_path / today / "steps"
    steps_dir.mkdir(parents=True)

    compress_data = {
        "hatena": {
            "themes": ["AI"],
            "articles": [
                {"url": "https://example.com/new", "one_liner": "new one liner"}
            ],
        }
    }
    old_digests = [{"url": "https://example.com/old", "summary": "old"}]
    new_digests = [{"url": "https://example.com/new", "summary": "new"}]
    (steps_dir / "compress.json").write_text(
        json.dumps(compress_data, ensure_ascii=False),
        encoding="utf-8",
    )
    (steps_dir / "digest.json").write_text(
        json.dumps({"digests": old_digests}, ensure_ascii=False),
        encoding="utf-8",
    )

    # 允許進入 feedback loop：reflect_for_completeness 預設回 ""（降級用原 prompt 重跑）
    sup = FakeSupervisor()
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())
    agent._run_digest = MagicMock(
        return_value=(
            new_digests,
            {"generated_at": "2026-04-20T10:00:00", "digests": new_digests},
        )
    )
    agent._run_judge = MagicMock(
        side_effect=[
            {
                "scores": {
                    "completeness": {
                        "score": 2,
                        "missed_urls": ["https://example.com/new"],
                    }
                },
                "overall": 2.5,
            },
            {
                "scores": {"completeness": {"score": 4, "missed_urls": []}},
                "overall": 4.0,
            },
        ]
    )

    with patch.object(agent_module, "OUTPUT_DIR", tmp_path), patch(
        "agents.daily_brief.supervisor.SupervisorAgent",
        lambda **kw: sup,
    ), patch("agents.daily_brief.steps.judge.check_local_llm", return_value=True):
        agent.run("--only judge")

    assert agent._run_judge.call_count == 2
    # 第二次 judge 應吃到新 digest，而不是舊 digest
    assert agent._run_judge.call_args_list[1].args[1] == new_digests


def test_force_judge_passes_force_flag_to_supervisor(tmp_path):
    """--force judge 應把 force=True 傳給 supervisor.run_step。"""
    import agents.daily_brief.agent as agent_module
    from agents.daily_brief.agent import DailyBriefAgent

    today = date.today().strftime("%Y-%m-%d")
    steps_dir = tmp_path / today / "steps"
    steps_dir.mkdir(parents=True)
    (steps_dir / "compress.json").write_text(
        json.dumps({"hatena": {"themes": [], "articles": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (steps_dir / "digest.json").write_text(
        json.dumps({"digests": [{"url": "https://example.com/1"}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    sup = FakeSupervisor(forbid_reflect=True)
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())
    agent._run_judge = MagicMock(return_value={"overall": 4.2})

    with patch.object(agent_module, "OUTPUT_DIR", tmp_path), patch(
        "agents.daily_brief.supervisor.SupervisorAgent",
        lambda **kw: sup,
    ), patch("agents.daily_brief.steps.judge.check_local_llm", return_value=True):
        agent.run("--only judge --force judge")

    assert sup.forced["judge"] is True


def test_judge_phase_uses_run_step_when_server_unavailable(tmp_path):
    """judge LLM server 無回應時，仍應透過 run_step 執行（讓 retry 機制運作），而非直接略過。"""
    import agents.daily_brief.agent as agent_module
    from agents.daily_brief.agent import DailyBriefAgent

    today = date.today().strftime("%Y-%m-%d")
    steps_dir = tmp_path / today / "steps"
    steps_dir.mkdir(parents=True)
    (steps_dir / "compress.json").write_text(
        json.dumps({"hatena": {"themes": [], "articles": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (steps_dir / "digest.json").write_text(
        json.dumps({"digests": [{"url": "https://example.com/1"}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    sup = FakeSupervisor(forbid_reflect=True)
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())

    # server 無回應 = JudgeStep._produce 的 check_local_llm 探測回 False → raise → run_step 走 FAILED
    with patch.object(agent_module, "OUTPUT_DIR", tmp_path), patch(
        "agents.daily_brief.supervisor.SupervisorAgent", lambda **kw: sup
    ), patch("agents.daily_brief.steps.judge.check_local_llm", return_value=False):
        agent.run("--only judge")

    assert "judge" in sup.calls


def test_judge_failure_log_does_not_claim_report_skipped(tmp_path, caplog):
    """judge 失敗時，不應 log『略過 report/notify』，因為那些步驟實際上仍繼續執行。"""
    import logging
    import agents.daily_brief.agent as agent_module
    from agents.daily_brief.agent import DailyBriefAgent

    today = date.today().strftime("%Y-%m-%d")
    steps_dir = tmp_path / today / "steps"
    steps_dir.mkdir(parents=True)
    (steps_dir / "compress.json").write_text(
        json.dumps({"hatena": {"themes": [], "articles": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (steps_dir / "digest.json").write_text(
        json.dumps({"digests": [{"url": "https://example.com/1"}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    sup = FakeSupervisor(fail=frozenset({"judge"}), forbid_reflect=True)
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())

    with patch.object(agent_module, "OUTPUT_DIR", tmp_path), patch(
        "agents.daily_brief.supervisor.SupervisorAgent", lambda **kw: sup
    ), caplog.at_level(logging.WARNING):
        agent.run("--only judge")

    assert "略過 report/notify" not in caplog.text


def test_score_reddit_batched_splits_calls():
    """154 篇 Reddit 文章應分 7 批呼叫 LLM，每批 ≤ 25 篇。"""
    import json
    from agents.daily_brief.agent import DailyBriefAgent

    call_sizes: list[int] = []

    def fake_complete(prompt: str, system: str = "") -> str:
        import re

        # 只取文章清單區段（在 ## 任務 之前）
        m = re.search(r"## 文章清單[^\n]*\n\n(\[.*?\])\n\n## 任務", prompt, re.DOTALL)
        articles_in_prompt = json.loads(m.group(1)) if m else []
        call_sizes.append(len(articles_in_prompt))
        scored = [
            {
                "title": a["title"],
                "url": a["url"],
                "score": a["score"],
                "interest": "**",
                "category": a["category"],
                "subreddit": a["subreddit"],
            }
            for a in articles_in_prompt
        ]
        return json.dumps({"articles": scored})

    mock_llm = MagicMock()
    mock_llm.complete.side_effect = fake_complete

    raw = [
        {
            "subreddit": "r/programming",
            "title": f"Article {i}",
            "score": 0,
            "num_comments": 0,
            "url": f"https://reddit.com/{i}",
            "orig_url": f"https://example.com/{i}",
            "category": "核心技術類",
        }
        for i in range(154)
    ]

    agent = DailyBriefAgent(llm=mock_llm)
    result = agent._score_reddit_batched(raw)

    assert len(call_sizes) == 7, f"預期 7 批，實際 {len(call_sizes)} 批"
    assert max(call_sizes) <= 25, f"批次超過 25 篇：{call_sizes}"
    assert sum(call_sizes) == 154
    assert len(result["articles"]) == 154


# ── --health 唯讀查詢接線 ─────────────────────────────────────────


def test_health_flag_renders_digest_shares(tmp_path, monkeypatch):
    """--health 短路：呈現 digest 貢獻度欄，且全程不呼叫 LLM。"""
    import agents.daily_brief.health as health
    from agents.daily_brief.agent import DailyBriefAgent

    today = date.today().strftime("%Y-%m-%d")
    history_file = tmp_path / "_health-history.json"
    history_file.write_text(
        json.dumps([{"date": today, "results": {"rss": "ok", "hatena": "ok"}}]),
        encoding="utf-8",
    )
    steps_dir = tmp_path / today / "steps"
    steps_dir.mkdir(parents=True)
    (steps_dir / "digest.json").write_text(
        json.dumps({"digests": [
            {"_source": "rss"}, {"_source": "rss"},
            {"_source": "hatena"},
            {"title": "舊 schema 條目，無 _source"},
        ]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(health, "HEALTH_HISTORY_FILE", history_file)
    monkeypatch.setattr("agents.daily_brief.agent.OUTPUT_DIR", tmp_path)

    mock_llm = MagicMock()
    out = DailyBriefAgent(llm=mock_llm, judge_llm=MagicMock()).run("--health")

    rss_line = next(l for l in out.splitlines() if l.strip().startswith("rss"))
    assert "digest 67%" in rss_line
    mock_llm.complete.assert_not_called()


def test_health_flag_survives_missing_digest_artifacts(tmp_path, monkeypatch):
    """近 30 天完全沒有 digest artifact → 表照常 render，不崩潰。"""
    import agents.daily_brief.health as health
    from agents.daily_brief.agent import DailyBriefAgent

    today = date.today().strftime("%Y-%m-%d")
    history_file = tmp_path / "_health-history.json"
    history_file.write_text(
        json.dumps([{"date": today, "results": {"rss": "ok"}}]), encoding="utf-8"
    )
    monkeypatch.setattr(health, "HEALTH_HISTORY_FILE", history_file)
    monkeypatch.setattr("agents.daily_brief.agent.OUTPUT_DIR", tmp_path)

    out = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock()).run("--health")
    assert "rss" in out

import json
from unittest.mock import MagicMock, patch

from agents.daily_brief.agent import ALL_STEPS, FETCH_STEPS


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


def test_all_steps_order():
    assert ALL_STEPS.index("security") < ALL_STEPS.index("compress")
    assert ALL_STEPS.index("compress") < ALL_STEPS.index("digest")
    assert ALL_STEPS.index("digest") < ALL_STEPS.index("judge")
    assert ALL_STEPS.index("judge") < ALL_STEPS.index("report")
    assert ALL_STEPS.index("digest") < ALL_STEPS.index("report")
    assert ALL_STEPS.index("report") < ALL_STEPS.index("save")
    assert ALL_STEPS.index("save") < ALL_STEPS.index("notify")


def test_fetch_steps_unchanged():
    assert FETCH_STEPS == ["hatena", "hn", "reddit", "security"]


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
            "articles": [{"title": "t", "url": "https://example.com", "one_liner": "x", "interest": "***"}],
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
        {"title": "B", "url": "https://example.com/1", "source": "Hatena", "summary": "s"},
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
        {"hatena": {"themes": [], "articles": []}, "hn": {"themes": [], "articles": []},
         "reddit": {"themes": [], "articles": []}, "security": {"themes": [], "articles": []}},
        [],
        "2026-04-12",
    )
    assert content == raw_markdown


def test_run_compress_returns_dict_with_all_sources():
    llm_resp = json.dumps({"themes": ["AI"], "articles": []})
    agent = _make_agent(llm_resp)
    source_data = {
        "hatena": {"articles": [{"title": "T", "url": "u", "interest": "***", "score": 100, "category": "AI", "source": "hatena"}]},
        "hn": {"articles": []},
        "reddit": {"articles": {}},
        "security": {"articles": []},
    }
    result = agent._run_compress(source_data)
    assert set(result.keys()) >= {"hatena", "hn", "reddit", "security"}
    assert "themes" in result["hatena"]


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
                {"title": "A", "url": "https://hn.com/1", "interest": "***", "score": 900},
                {"title": "B", "url": "https://hn.com/2", "interest": "**", "score": 200},
                {"title": "C", "url": "https://hn.com/3", "interest": "*", "score": 50},
            ]
        },
        "reddit": {"articles": {}},
        "security": {"articles": []},
    }
    agent._run_compress(source_data)

    # hn 的 prompt 中只應包含 *** 文章的 URL
    hn_prompt = next(p for p in captured_prompts if "hn.com/1" in p)
    assert "hn.com/1" in hn_prompt          # *** 保留
    assert "hn.com/2" not in hn_prompt      # ** 過濾掉
    assert "hn.com/3" not in hn_prompt      # * 過濾掉


def test_run_judge_returns_scores_and_overall():
    llm_resp = json.dumps(
        {
            "scores": {
                "relevance": {"score": 4, "reasoning": "OK"},
                "completeness": {"score": 3, "reasoning": "missed one", "missed_urls": []},
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
    digests = [{"title": "T", "url": "https://u.com", "source": "HN", "interest": "***", "summary": "s"}]
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

    digests = [{"title": "A", "url": "https://a.com", "source": "HN", "summary": "摘要 A"}]
    result = _format_obsidian_digest(digests, "2026-04-12")
    assert result.startswith("---")
    assert "created: 2026-04-12" in result
    assert "tags: [daily-brief, digest]" in result
    assert "## A" in result
    assert "https://a.com" in result


def test_notify_uses_tg_overview_key():
    from agents.daily_brief.agent import DailyBriefAgent

    responses = [
        json.dumps({"tg_overview": "overview text"}),
        json.dumps({"tg_digest": "digest text"}),
    ]
    mock_llm = MagicMock()
    mock_llm.complete.side_effect = responses
    agent = DailyBriefAgent(llm=mock_llm)

    digests = [{"title": "T", "url": "https://u.com", "source": "HN", "summary": "s"}]

    with patch("tools.notifiers.telegram.send") as mock_send:
        agent._notify(digests, "2026-04-12")
        calls = [c[0][0] for c in mock_send.call_args_list]
        assert "overview text" in calls
        assert "digest text" in calls


def test_notify_saves_telegram_artifacts(tmp_path):
    from agents.daily_brief.agent import DailyBriefAgent

    responses = [
        json.dumps({"tg_overview": "<b>overview</b>"}),
        json.dumps({"tg_digest": "<b>digest</b>"}),
    ]
    mock_llm = MagicMock()
    mock_llm.complete.side_effect = responses
    agent = DailyBriefAgent(llm=mock_llm)

    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()
    digests = [{"title": "T", "url": "https://u.com", "source": "HN", "summary": "s"}]

    with patch("tools.notifiers.telegram.send"):
        agent._notify(digests, "2026-04-13", steps_dir=steps_dir)

    overview_file = steps_dir / "telegram_overview.txt"
    digest_file = steps_dir / "telegram_digest.txt"
    assert overview_file.exists()
    assert overview_file.read_text(encoding="utf-8") == "<b>overview</b>"
    assert digest_file.exists()
    assert digest_file.read_text(encoding="utf-8") == "<b>digest</b>"


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
    assert len(ALL_STEPS) == 10


# ── _parse_json robustness ───────────────────────────────────────────────────

def test_run_judge_logs_warning_when_completeness_below_threshold():
    """completeness < 3 時應在回傳結果中標記 quality_alert。"""
    from agents.daily_brief.agent import DailyBriefAgent

    llm_resp = json.dumps({
        "scores": {
            "relevance":    {"score": 5, "reasoning": "ok"},
            "completeness": {"score": 2, "reasoning": "missed many", "missed_urls": ["https://a.com"]},
            "faithfulness": {"score": 5, "reasoning": "ok"},
        },
    })
    mock_judge = MagicMock()
    mock_judge.complete.return_value = llm_resp
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=mock_judge)

    result = agent._run_judge({}, [])
    assert result.get("quality_alert") is True
    assert "completeness" in result.get("quality_alert_reason", "")


def test_run_judge_no_alert_when_completeness_sufficient():
    """completeness >= 3 時不應有 quality_alert。"""
    from agents.daily_brief.agent import DailyBriefAgent

    llm_resp = json.dumps({
        "scores": {
            "relevance":    {"score": 4, "reasoning": "ok"},
            "completeness": {"score": 3, "reasoning": "ok", "missed_urls": []},
            "faithfulness": {"score": 4, "reasoning": "ok"},
        },
    })
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

        llm_resp = json.dumps({
            "scores": {
                "relevance":    {"score": 5, "reasoning": "ok"},
                "completeness": {"score": 4, "reasoning": "ok", "missed_urls": []},
                "faithfulness": {"score": 5, "reasoning": "ok"},
            },
        })
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

        llm_resp = json.dumps({
            "scores": {
                "relevance":    {"score": 4, "reasoning": "ok"},
                "completeness": {"score": 4, "reasoning": "ok", "missed_urls": []},
                "faithfulness": {"score": 4, "reasoning": "ok"},
            },
        })
        for date_str in ("2026-04-13", "2026-04-14"):
            mock_judge = MagicMock()
            mock_judge.complete.return_value = llm_resp
            agent = DailyBriefAgent(llm=MagicMock(), judge_llm=mock_judge)
            agent._run_judge({}, [], date=date_str)

        history = json.loads((tmp_path / "_judge-history.json").read_text(encoding="utf-8"))
        assert len(history) == 2
        assert {r["date"] for r in history} == {"2026-04-13", "2026-04-14"}
    finally:
        cfg.OUTPUT_DIR = original


def test_source_health_warns_on_zero_articles():
    """_check_source_health 對 0 篇 *** 的來源應回傳 warning list。"""
    from agents.daily_brief.agent import DailyBriefAgent

    compress_data = {
        "hatena":   {"themes": ["AI"], "articles": [{"interest": "***", "url": "u1"}]},
        "hn":       {"themes": [],     "articles": []},
        "reddit":   {"themes": ["資安"], "articles": [{"interest": "***", "url": "u2"}]},
        "security": {"themes": [],     "articles": []},
    }
    warnings = DailyBriefAgent._check_source_health(compress_data)
    assert "hn" in warnings
    assert "security" in warnings
    assert "hatena" not in warnings
    assert "reddit" not in warnings


def test_parse_json_recovers_from_fullwidth_colon():
    """HN 情境：LLM 用全形冒號 '：' 作為 key-value 分隔符導致無效 JSON。"""
    from agents.daily_brief.agent import DailyBriefAgent

    broken = (
        '```json\n'
        '{\n'
        '  "articles": [\n'
        '    {"title": "正常文章", "url": "https://example.com", "score": 100, "interest": "**"},\n'
        '    {"title：有全形冒號的標題", "url": "https://example2.com", "score": 50, "interest": "*"},\n'
        '    {"title": "另一篇正常文章", "url": "https://example3.com", "score": 200, "interest": "***"}\n'
        '  ]\n'
        '}\n'
        '```'
    )
    result = DailyBriefAgent._parse_json(broken)
    assert "raw" not in result, "全形冒號應被修復，不應 fallback 到 raw"
    assert "articles" in result
    assert len(result["articles"]) == 3


def test_parse_json_recovers_from_unescaped_quotes_in_value():
    """Reddit 情境：字串值內含未逸脫雙引號導致無效 JSON。"""
    from agents.daily_brief.agent import DailyBriefAgent

    broken = (
        '```json\n'
        '{\n'
        '  "articles": [\n'
        '    {"title": "IBM settles but pays $17M | under "Civil Rights Fraud Initiative."", '
        '"url": "https://reddit.com/r/tech/1", "score": 500, "interest": "***"}\n'
        '  ]\n'
        '}\n'
        '```'
    )
    result = DailyBriefAgent._parse_json(broken)
    assert "raw" not in result, "未逸脫引號應被修復，不應 fallback 到 raw"
    assert "articles" in result
    assert len(result["articles"]) == 1


def test_run_judge_passes_slim_compress_to_llm():
    """_run_judge 應只傳 url + one_liner 給 judge LLM，不傳完整文章內容。"""
    from agents.daily_brief.agent import DailyBriefAgent

    llm_resp = json.dumps({
        "scores": {
            "relevance":    {"score": 4, "reasoning": "ok"},
            "completeness": {"score": 4, "reasoning": "ok", "missed_urls": []},
            "faithfulness": {"score": 4, "reasoning": "ok"},
        },
    })
    mock_judge = MagicMock()
    mock_judge.complete.return_value = llm_resp
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=mock_judge)

    compress_data = {
        "hatena": {
            "themes": ["AI"],
            "articles": [{
                "title": "完整標題文字不應出現在 judge prompt",
                "url": "https://example.com/1",
                "one_liner": "核心摘要",
                "interest": "***",
                "bookmarks": 999,
                "extra_field": "不需要的資料",
            }]
        },
        "hn": {"themes": [], "articles": []},
        "reddit": {"themes": [], "articles": []},
        "security": {"themes": [], "articles": []},
    }
    digests = [{"title": "T", "url": "https://example.com/1", "source": "Hatena", "summary": "s"}]
    agent._run_judge(compress_data, digests)

    call_prompt = mock_judge.complete.call_args[0][0]
    assert "https://example.com/1" in call_prompt   # URL 保留
    assert "核心摘要" in call_prompt                 # one_liner 保留
    assert "完整標題文字不應出現在 judge prompt" not in call_prompt  # title 移除
    assert "extra_field" not in call_prompt          # 額外欄位移除
    assert "bookmarks" not in call_prompt            # 數值欄位移除


def test_notify_msg2_limits_digests_to_top8():
    """_notify msg2 prompt 應只傳入前 8 篇摘要，不傳全部。"""
    from agents.daily_brief.agent import DailyBriefAgent

    responses = [
        json.dumps({"tg_overview": "overview"}),
        json.dumps({"tg_digest": "digest"}),
    ]
    mock_llm = MagicMock()
    mock_llm.complete.side_effect = responses
    agent = DailyBriefAgent(llm=mock_llm)

    # 建立 15 篇 digests
    digests = [
        {"title": f"Article {i}", "url": f"https://example.com/{i}", "source": "HN", "summary": "s"}
        for i in range(15)
    ]

    with patch("tools.notifiers.telegram.send"):
        agent._notify(digests, "2026-04-14")

    # msg2 的 prompt（第 2 次 complete 呼叫）應只包含前 8 篇
    msg2_prompt = mock_llm.complete.call_args_list[1][0][0]
    assert "example.com/8" not in msg2_prompt   # 第 9 篇（index 8）不應在 msg2
    assert "example.com/0" in msg2_prompt       # 第 1 篇應在 msg2
    assert "example.com/7" in msg2_prompt       # 第 8 篇應在 msg2

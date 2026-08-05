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


# judge 完成度足夠（4 分）→ 不觸發 digest 回饋重跑；judge 只跑一次
_JUDGE_OK = json.dumps(
    {
        "scores": {
            "relevance": {"score": 4},
            "completeness": {"score": 4, "missed_urls": []},
            "faithfulness": {"score": 4},
        },
        "missed_urls": [],
    }
)


def _judge_run_patches(agent_module, tmp_path, sup):
    """orchestration 測試共用：OUTPUT_DIR（agent + config 兩處）+ supervisor + check_local_llm。"""
    return (
        patch.object(agent_module, "OUTPUT_DIR", tmp_path),
        patch("agents.daily_brief.config.OUTPUT_DIR", tmp_path),
        patch("agents.daily_brief.supervisor.SupervisorAgent", lambda **kw: sup),
        patch("agents.daily_brief.steps.judge.check_local_llm", return_value=True),
    )


def _seed_compress_digest(steps_dir, compress, digests):
    steps_dir.mkdir(parents=True)
    (steps_dir / "compress.json").write_text(
        json.dumps(compress, ensure_ascii=False), encoding="utf-8"
    )
    (steps_dir / "digest.json").write_text(
        json.dumps({"digests": digests}, ensure_ascii=False), encoding="utf-8"
    )


def test_run_judge_step_is_wrapped_by_supervisor(tmp_path):
    """run() 的 judge 階段應透過 supervisor.run_step 執行（judge producer 現住 JudgeStep）。"""
    import agents.daily_brief.agent as agent_module
    from agents.daily_brief.agent import DailyBriefAgent

    today = date.today().strftime("%Y-%m-%d")
    steps_dir = tmp_path / today / "steps"
    _seed_compress_digest(
        steps_dir, {"hatena": {"themes": [], "articles": []}}, [{"url": "https://example.com/1"}]
    )

    sup = FakeSupervisor(forbid_reflect=True)
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())
    agent._judge_llm.complete.return_value = _JUDGE_OK

    p1, p2, p3, p4 = _judge_run_patches(agent_module, tmp_path, sup)
    with p1, p2, p3, p4:
        agent.run("--only judge")

    assert "judge" in sup.calls
    assert (steps_dir / "judge.json").exists()
    agent._judge_llm.complete.assert_called_once()


def test_run_wires_source_data_into_judge(tmp_path):
    """--only judge 時，run() 應把載入的 source artifact（含 original_title）接進 judge。"""
    import agents.daily_brief.agent as agent_module
    from agents.daily_brief.agent import DailyBriefAgent

    today = date.today().strftime("%Y-%m-%d")
    steps_dir = tmp_path / today / "steps"
    _seed_compress_digest(
        steps_dir, {"hatena": {"themes": [], "articles": []}}, [{"url": "https://example.com/1"}]
    )
    (steps_dir / "hatena.json").write_text(
        json.dumps(
            {
                "articles": [
                    {
                        "title": "繁中翻譯標題",
                        "url": "https://example.com/1",
                        "original_title": "Raw Original Title",
                        "interest": "***",
                        "score": 100,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    sup = FakeSupervisor(forbid_reflect=True)
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())
    agent._judge_llm.complete.return_value = _JUDGE_OK

    p1, p2, p3, p4 = _judge_run_patches(agent_module, tmp_path, sup)
    with p1, p2, p3, p4:
        agent.run("--only judge")

    # source_data 被接進 judge → 原始 title 進到 judge prompt（去循環化對照）
    prompt = agent._judge_llm.complete.call_args[0][0]
    assert "Raw Original Title" in prompt


def test_judge_feedback_loop_uses_new_digests_for_retry(tmp_path):
    """judge feedback 重評時應使用 digest 重跑後的新資料（透過真 DigestStep/JudgeStep）。"""
    import agents.daily_brief.agent as agent_module
    from agents.daily_brief.agent import DailyBriefAgent

    today = date.today().strftime("%Y-%m-%d")
    steps_dir = tmp_path / today / "steps"

    compress_data = {
        "hatena": {
            "themes": ["AI"],
            "articles": [{"url": "https://example.com/new", "one_liner": "new one liner"}],
        }
    }
    old_digests = [{"url": "https://example.com/old", "summary": "old"}]
    _seed_compress_digest(steps_dir, compress_data, old_digests)

    # digest 重跑（DigestStep 讀 ctx.llm）→ 產出含 example.com/new 的新 digest
    new_digest_resp = json.dumps(
        {"digests": [{"url": "https://example.com/new", "summary": "new"}]}
    )
    # judge 第一次 completeness=2 觸發回饋，第二次=4 收斂
    judge_resp_low = json.dumps(
        {"scores": {"completeness": {"score": 2}}, "missed_urls": ["https://example.com/new"]}
    )

    sup = FakeSupervisor()  # 允許進入 feedback loop（reflect 預設回 ""）
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())
    agent._llm.complete.return_value = new_digest_resp
    agent._judge_llm.complete.side_effect = [judge_resp_low, _JUDGE_OK]

    p1, p2, p3, p4 = _judge_run_patches(agent_module, tmp_path, sup)
    with p1, p2, p3, p4:
        agent.run("--only judge")

    assert agent._judge_llm.complete.call_count == 2
    # 第二次 judge 應吃到新 digest（含 example.com/new），而非舊 digest
    second_prompt = agent._judge_llm.complete.call_args_list[1][0][0]
    assert "example.com/new" in second_prompt
    assert "example.com/old" not in second_prompt


def test_force_judge_passes_force_flag_to_supervisor(tmp_path):
    """--force judge 應把 force=True 傳給 supervisor.run_step。"""
    import agents.daily_brief.agent as agent_module
    from agents.daily_brief.agent import DailyBriefAgent

    today = date.today().strftime("%Y-%m-%d")
    steps_dir = tmp_path / today / "steps"
    _seed_compress_digest(
        steps_dir, {"hatena": {"themes": [], "articles": []}}, [{"url": "https://example.com/1"}]
    )

    sup = FakeSupervisor(forbid_reflect=True)
    agent = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock())
    agent._judge_llm.complete.return_value = _JUDGE_OK

    p1, p2, p3, p4 = _judge_run_patches(agent_module, tmp_path, sup)
    with p1, p2, p3, p4:
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
    monkeypatch.setattr(health, "JUDGE_HISTORY_FILE", tmp_path / "_judge-history.json")
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
    monkeypatch.setattr(health, "JUDGE_HISTORY_FILE", tmp_path / "_judge-history.json")
    monkeypatch.setattr("agents.daily_brief.agent.OUTPUT_DIR", tmp_path)

    out = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock()).run("--health")
    assert "rss" in out
    assert "judge" not in out  # judge 歷史缺檔 → 資料不足，不誤報


def test_health_flag_flags_judge_saturation(tmp_path, monkeypatch):
    """--health 接線：judge 歷史飽和時表尾出現警示行。"""
    from datetime import timedelta

    import agents.daily_brief.health as health
    from agents.daily_brief.agent import DailyBriefAgent

    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    history_file = tmp_path / "_health-history.json"
    history_file.write_text(
        json.dumps([{"date": today_str, "results": {"rss": "ok"}}]), encoding="utf-8"
    )
    judge_file = tmp_path / "_judge-history.json"
    judge_file.write_text(
        json.dumps([
            {
                "date": (today - timedelta(days=offset)).strftime("%Y-%m-%d"),
                "overall": 5.0,
                "scores": {"relevance": 5, "completeness": 5, "faithfulness": 5},
                "quality_alert": False,
            }
            for offset in range(30)
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(health, "HEALTH_HISTORY_FILE", history_file)
    monkeypatch.setattr(health, "JUDGE_HISTORY_FILE", judge_file)
    monkeypatch.setattr("agents.daily_brief.agent.OUTPUT_DIR", tmp_path)

    out = DailyBriefAgent(llm=MagicMock(), judge_llm=MagicMock()).run("--health")
    assert "judge 已失去鑑別力" in out
    assert "30/30" in out

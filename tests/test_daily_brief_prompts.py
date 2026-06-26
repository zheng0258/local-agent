from pathlib import Path
import inspect

from agents.daily_brief import prompts
from agents.daily_brief.config import (
    FALLBACK_TOP_N,
    HATENA_DIGEST_THRESHOLD,
    HN_DIGEST_THRESHOLD,
    REDDIT_DIGEST_THRESHOLD,
    VAULT_DAILY_BRIEF_DIR,
)


def test_vault_daily_brief_dir_optional():
    # vault 選填：未配置 VAULT_ROOT 時為 None，否則 Path 結尾為 daily-brief
    assert VAULT_DAILY_BRIEF_DIR is None or (
        isinstance(VAULT_DAILY_BRIEF_DIR, Path)
        and VAULT_DAILY_BRIEF_DIR.name == "daily-brief"
    )


def test_judge_prompt_has_missed_urls_at_top_level():
    """missed_urls 應在 JSON schema 頂層，不能在 completeness 物件內。"""
    p = prompts.build_judge_prompt("{}", "{}")
    # 頂層 missed_urls
    assert '"missed_urls":' in p
    # completeness 物件不含 missed_urls（避免 LLM 混淆）
    completeness_block = p[p.find('"completeness"') : p.find('"faithfulness"')]
    assert "missed_urls" not in completeness_block


def test_judge_prompt_instructs_no_urls_in_reasoning():
    """prompt 應明確告知 reasoning 欄位不要列 URL。"""
    p = prompts.build_judge_prompt("{}", "{}")
    assert "URL" in p and "reasoning" in p


def test_score_prompts_no_longer_contain_digest_section():
    hatena_p = prompts.build_hatena_prompt("[]")
    hn_p = prompts.build_hn_prompt("[]")
    reddit_p = prompts.build_reddit_prompt("{}")
    security_p = prompts.build_security_blogs_prompt("[]")

    for p in [hatena_p, hn_p, reddit_p, security_p]:
        assert "all_digests_append" not in p


def test_score_prompts_output_articles_key():
    hatena_p = prompts.build_hatena_prompt("[]")
    assert '"articles"' in hatena_p


def test_hatena_prompt_output_has_no_summary_field():
    hatena_p = prompts.build_hatena_prompt("[]")
    assert '"summary"' not in hatena_p


def test_build_digest_prompt_exists():
    assert hasattr(prompts, "build_digest_prompt")


def test_build_digest_prompt_injects_thresholds():
    p = prompts.build_digest_prompt("[]", "[]", "{}", "[]")
    assert str(HATENA_DIGEST_THRESHOLD) in p
    assert str(HN_DIGEST_THRESHOLD) in p
    assert str(REDDIT_DIGEST_THRESHOLD) in p
    assert str(FALLBACK_TOP_N) in p


def test_build_digest_prompt_output_schema():
    p = prompts.build_digest_prompt("[]", "[]", "{}", "[]")
    assert '"digests"' in p
    assert '"summary"' in p
    assert '"source"' in p


def test_telegram_prompts_renamed():
    assert hasattr(prompts, "build_telegram_overview_prompt")
    assert hasattr(prompts, "build_telegram_digest_prompt")
    assert not hasattr(prompts, "build_telegram_msg1_prompt")
    assert not hasattr(prompts, "build_telegram_msg2_prompt")


def test_telegram_overview_outputs_plain_html_not_json():
    p = prompts.build_telegram_overview_prompt("[]", "2026-04-12")
    assert "直接輸出 HTML 純文字" in p
    assert "不要包裝成 JSON" in p


def test_telegram_digest_outputs_plain_html_not_json():
    p = prompts.build_telegram_digest_prompt("[]", "2026-04-12")
    assert "直接輸出 HTML 純文字" in p
    assert "不要包裝成 JSON" in p


def test_report_prompt_uses_digests_json_not_all_digests():
    sig = inspect.signature(prompts.build_report_prompt)
    assert "digests_json" in sig.parameters
    assert "all_digests_json" not in sig.parameters


def test_build_compress_prompt_exists():
    assert hasattr(prompts, "build_compress_prompt")


def test_build_compress_prompt_includes_source_name():
    prompt = prompts.build_compress_prompt("hatena", "[]")
    assert "hatena" in prompt


def test_build_compress_prompt_output_schema():
    prompt = prompts.build_compress_prompt("hn", "[]")
    assert '"themes"' in prompt
    assert '"articles"' in prompt
    assert '"one_liner"' in prompt


def test_build_digest_prompt_from_compress_exists():
    assert hasattr(prompts, "build_digest_prompt_from_compress")


def test_build_digest_prompt_from_compress_output_schema():
    prompt = prompts.build_digest_prompt_from_compress("{}")
    assert '"digests"' in prompt
    assert '"summary"' in prompt
    assert '"source"' in prompt


def test_build_report_prompt_from_compress_exists():
    assert hasattr(prompts, "build_report_prompt_from_compress")


def test_build_report_prompt_from_compress_signature():
    sig = inspect.signature(prompts.build_report_prompt_from_compress)
    assert "compress_json" in sig.parameters
    assert "digests_json" in sig.parameters


def test_build_report_prompt_from_compress_output_schema():
    prompt = prompts.build_report_prompt_from_compress("{}", "[]")
    # 新版直接輸出 markdown，不包成 JSON
    assert '"report_content"' not in prompt
    assert "markdown" in prompt.lower() or "趨勢話題" in prompt


def test_build_judge_prompt_exists():
    assert hasattr(prompts, "build_judge_prompt")


def test_build_judge_prompt_output_schema():
    prompt = prompts.build_judge_prompt("{}", "{}")
    assert '"scores"' in prompt
    assert '"relevance"' in prompt
    assert '"completeness"' in prompt
    assert '"faithfulness"' in prompt
    assert '"overall"' in prompt


def test_build_judge_prompt_includes_inputs():
    compress = '{"hatena": {"themes": [], "articles": []}}'
    digest = '{"digests": []}'
    prompt = prompts.build_judge_prompt(compress, digest)
    assert compress in prompt
    assert digest in prompt


def test_fetch_prompts_contain_few_shot_examples():
    """所有 fetch prompt 應包含具體 few-shot 範例以穩定評分。"""
    hatena_p = prompts.build_hatena_prompt("[]")
    hn_p = prompts.build_hn_prompt("[]")
    reddit_p = prompts.build_reddit_prompt("{}")
    security_p = prompts.build_security_blogs_prompt("[]")

    for p in [hatena_p, hn_p, reddit_p, security_p]:
        assert "Claude Code" in p or "CVE" in p, "應包含 *** 類的 few-shot 範例"
        assert "- ** " in p and "- * " in p, "應包含 ** 與 * 評分層級的範例"


# ── build_comment_summary_prompt ────────────────────────────────


def test_build_comment_summary_prompt_exists():
    assert hasattr(prompts, "build_comment_summary_prompt")


def test_build_comment_summary_prompt_output_key():
    p = prompts.build_comment_summary_prompt("hn", "Some Title", '["comment 1"]')
    assert '"comment_summary"' in p


def test_build_comment_summary_prompt_includes_title_and_source():
    p = prompts.build_comment_summary_prompt("reddit", "My Article", "[]")
    assert "My Article" in p
    assert "reddit" in p


def test_build_comment_summary_prompt_specifies_60_char_limit():
    p = prompts.build_comment_summary_prompt("hn", "T", "[]")
    assert "60" in p


# ── build_digest_prompt_from_compress（更新）───────────────────


def test_build_digest_prompt_from_compress_mentions_comment_summary():
    """更新後的 prompt 應提及 comment_summary 欄位與社群觀點追加。"""
    p = prompts.build_digest_prompt_from_compress("{}")
    assert "comment_summary" in p
    assert "社群觀點" in p


# ── build_tldr_prompt（issue #9：英文 TL;DR）─────────────────────


def test_build_tldr_prompt_exists():
    assert hasattr(prompts, "build_tldr_prompt")


def test_build_tldr_prompt_includes_digests_input():
    digests_json = '{"digests": [{"title": "Foo", "summary": "bar"}]}'
    p = prompts.build_tldr_prompt(digests_json)
    assert digests_json in p


def test_build_tldr_prompt_instructs_english_plaintext():
    """TL;DR 必須是英文純文字，prompt 應明確要求英文且不包成 JSON。"""
    p = prompts.build_tldr_prompt("{}")
    assert "English" in p
    # 純文字輸出，不包成 JSON
    assert "不要包裝成 JSON" in p

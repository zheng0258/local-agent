"""Behavioral tests for judge.json artifact."""


def test_judge_has_scores(judge):
    assert "scores" in judge
    assert isinstance(judge["scores"], dict)


def test_judge_has_all_dimensions(judge):
    required = {"relevance", "completeness", "faithfulness"}
    assert required <= judge["scores"].keys()


def test_judge_scores_in_range(judge):
    for dim in ["relevance", "completeness", "faithfulness"]:
        score = judge["scores"][dim]["score"]
        assert isinstance(score, (int, float)), f"{dim} score is not numeric"
        assert 1 <= score <= 5, f"{dim} score out of range: {score}"


def test_judge_scores_have_reasoning(judge):
    for dim in ["relevance", "completeness", "faithfulness"]:
        reasoning = judge["scores"][dim].get("reasoning", "")
        assert isinstance(reasoning, str) and len(reasoning) > 0, f"{dim} has no reasoning"


def test_judge_completeness_has_missed_urls(judge):
    completeness = judge["scores"]["completeness"]
    assert isinstance(completeness.get("missed_urls", []), list)


def test_judge_overall_in_range(judge):
    overall = judge.get("overall", 0)
    assert isinstance(overall, (int, float))
    assert 1.0 <= overall <= 5.0, f"overall score out of range: {overall}"


def test_judge_has_metadata(judge):
    assert "judged_at" in judge
    assert "judge_model" in judge

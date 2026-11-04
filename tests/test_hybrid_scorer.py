from __future__ import annotations

import pytest

from talentlens.errors import ConfigurationError
from talentlens.matching.hybrid_scorer import HybridScorer, ScoringWeights

COMPONENTS = {
    "semantic": 0.5,
    "section_relevance": 0.4,
    "required_coverage": 0.8,
    "preferred_coverage": 0.25,
    "experience_alignment": 0.6,
    "tfidf": 0.35,
}


def test_weighted_total_and_contributions_are_consistent():
    scorer = HybridScorer()
    breakdown = scorer.score(COMPONENTS)

    assert sum(contribution.contribution for contribution in breakdown.contributions) == pytest.approx(
        breakdown.total, abs=1e-6
    )
    expected = (
        0.30 * 0.5 + 0.15 * 0.4 + 0.33 * 0.8 + 0.07 * 0.25 + 0.15 * 0.6
    )
    assert breakdown.total == pytest.approx(expected, abs=1e-6)
    assert breakdown.tfidf == 0.35
    assert "Hybrid score" in breakdown.explanation


def test_weights_must_sum_to_one():
    with pytest.raises(ConfigurationError):
        ScoringWeights.from_config(
            {
                "semantic": 0.5,
                "section_relevance": 0.1,
                "required_skills": 0.1,
                "preferred_skills": 0.1,
                "experience": 0.1,
            }
        )


def test_negative_weight_rejected():
    with pytest.raises(ConfigurationError):
        ScoringWeights.from_config(
            {
                "semantic": -0.1,
                "section_relevance": 0.3,
                "required_skills": 0.5,
                "preferred_skills": 0.2,
                "experience": 0.1,
            }
        )


def test_components_are_clamped_to_unit_interval():
    scorer = HybridScorer()
    breakdown = scorer.score(
        {**COMPONENTS, "semantic": 2.0, "required_coverage": -3.0}
    )
    assert breakdown.semantic == 1.0
    assert breakdown.required_coverage == 0.0
    assert 0.0 <= breakdown.total <= 1.0


def test_missing_component_is_rejected():
    scorer = HybridScorer()
    with pytest.raises(ConfigurationError):
        scorer.score({"semantic": 0.5})


def test_baseline_total_uses_only_the_retriever():
    breakdown = HybridScorer.baseline(COMPONENTS, baseline="tfidf")
    assert breakdown.total == pytest.approx(COMPONENTS["tfidf"])
    assert breakdown.weights == {"tfidf": 1.0}
    assert [item.component for item in breakdown.contributions] == ["tfidf"]


def test_semantic_baseline_total():
    breakdown = HybridScorer.baseline(COMPONENTS, baseline="semantic")
    assert breakdown.total == pytest.approx(COMPONENTS["semantic"])
    assert breakdown.tfidf == COMPONENTS["tfidf"]

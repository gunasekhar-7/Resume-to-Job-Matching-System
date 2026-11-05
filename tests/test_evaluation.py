from __future__ import annotations

import math

import pytest

from talentlens.evaluation.labels import (
    SPLIT_RESUME_IDS,
    load_labels,
    split_for_resume,
    split_labels,
    validate_splits,
)
from talentlens.evaluation.metrics import (
    evaluate_ranking,
    evaluate_rankings,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_labels_and_frozen_splits_are_consistent(config):
    labels = load_labels(config.resolve("data/annotations/relevance_labels.jsonl"))
    validate_splits()
    assert len(labels) == 140
    assert len({label.pair_id for label in labels}) == 140
    assert {
        split: sum(len(judged) for judged in split_labels(labels, split).values())
        for split in SPLIT_RESUME_IDS
    } == {"dev": 70, "validation": 30, "test": 40}
    assert split_for_resume("r11") == "test"
    with pytest.raises(KeyError):
        split_for_resume("missing")
    with pytest.raises(ValueError):
        split_labels(labels, "unknown")


def test_metric_values_on_a_known_ranking():
    labels = {"j1": 2, "j2": 1, "j3": 0}
    ranked = ["j1", "j2", "j3"]
    assert precision_at_k(ranked, labels, 1) == 1.0
    assert precision_at_k(ranked, labels, 2) == pytest.approx(0.5)
    assert precision_at_k(ranked, labels, 3) == pytest.approx(1 / 3)
    assert recall_at_k(ranked, labels, 2) == 1.0
    assert mrr(ranked, labels) == 1.0
    assert ndcg_at_k(ranked, labels, 3) == pytest.approx(1.0)


def test_graded_ndcg_penalises_swapping_strong_and_partial():
    labels = {"strong": 2, "partial": 1}
    ideal = ndcg_at_k(["strong", "partial"], labels, 2)
    swapped = ndcg_at_k(["partial", "strong"], labels, 2)
    assert ideal == pytest.approx(1.0)
    expected = (1 + 3 / math.log2(3)) / (3 + 1 / math.log2(3))
    assert swapped == pytest.approx(expected)
    assert swapped < ideal


def test_unjudged_jobs_are_ignored_not_counted_as_false_negatives():
    labels = {"strong": 2}
    with_unjudged = ["unjudged_a", "unjudged_b", "strong"]
    without = ["strong"]
    for metric in (
        lambda ranked: precision_at_k(ranked, labels, 5),
        lambda ranked: recall_at_k(ranked, labels, 5),
        lambda ranked: ndcg_at_k(ranked, labels, 5),
        lambda ranked: mrr(ranked, labels),
    ):
        assert metric(with_unjudged) == metric(without)


def test_primary_threshold_controls_mrr_and_precision():
    labels = {"partial": 1}
    assert mrr(["partial"], labels) == 0.0
    assert mrr(["partial"], labels, threshold=1) == 1.0
    assert precision_at_k(["partial"], labels, 1) == 0.0
    assert precision_at_k(["partial"], labels, 1, threshold=1) == 1.0


def test_empty_labels_and_invalid_k_are_safe():
    assert ndcg_at_k(["j1"], {}, 10) == 0.0
    assert precision_at_k(["j1"], {}, 0) == 0.0
    assert recall_at_k(["j1"], {}, 10) == 0.0


def test_evaluate_rankings_aggregates_per_resume():
    result = evaluate_rankings(
        {"r1": ["a", "b"], "r2": ["c", "d"]},
        {"r1": {"a": 2, "b": 0}, "r2": {"c": 1, "d": 2}},
    )
    assert result["resumes"] == 2
    assert result["judged_pairs"] == 4
    assert result["aggregate"]["mrr"] == pytest.approx(0.75)
    assert result["per_resume"]["r1"]["judged"] == 2.0
    assert "unjudged" in result["protocol"]


def test_evaluate_ranking_reports_counts():
    metrics = evaluate_ranking(["j1", "unjudged"], {"j1": 2, "j2": 0}, k_values=(1, 2))
    assert metrics["judged"] == 2.0
    assert metrics["retrieved"] == 1.0
    # Only one job was judged, so min(K, judged) is the denominator.
    assert metrics["precision@2"] == 1.0
    assert metrics["recall@2"] == 1.0

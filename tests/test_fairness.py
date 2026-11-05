from __future__ import annotations

from fakes import FakeEmbedder
from talentlens.evaluation.fairness import (
    VARIANTS,
    compare_rankings,
    counterfactual_document,
    run_counterfactual_fairness,
)
from talentlens.matching.pipeline import MatchingPipeline


def _pipeline(tmp_path, job_documents, config, taxonomy):
    return MatchingPipeline.build(
        job_documents,
        embedder=FakeEmbedder(dimension=48),
        config=config,
        taxonomy=taxonomy,
        artifact_dir=tmp_path / "fairness-index",
        persist=True,
    )


def test_counterfactual_document_only_changes_header_and_education(parsed_r01):
    changed = counterfactual_document(parsed_r01, VARIANTS[0])
    assert changed.sections["skills"] == parsed_r01.sections["skills"]
    assert changed.sections["experience"] == parsed_r01.sections["experience"]
    assert changed.sections["header"] != parsed_r01.sections.get("header", [])
    assert changed.resume_id == parsed_r01.resume_id


def test_counterfactual_rankings_are_invariant(tmp_path, parsed_r01, job_documents, config, taxonomy):
    pipeline = _pipeline(tmp_path, job_documents, config, taxonomy)
    baseline = pipeline.match(parsed_r01, top_k=10)
    for variant in VARIANTS:
        changed = pipeline.match(counterfactual_document(parsed_r01, variant), top_k=10)
        comparison = compare_rankings(baseline, changed, top_k=10)
        assert comparison["same_order"], variant.name
        assert comparison["max_score_delta"] <= 1e-9, variant.name
        assert comparison["max_component_delta"] <= 1e-9, variant.name


def test_fairness_report_is_explicit_about_scope(tmp_path, parsed_r01, job_documents, config, taxonomy):
    pipeline = _pipeline(tmp_path, job_documents, config, taxonomy)
    report = run_counterfactual_fairness(pipeline, [parsed_r01], top_k=5)
    assert report["passed"] is True
    assert report["checks"] == len(VARIANTS)
    assert "statistical fairness" in report["scope"]

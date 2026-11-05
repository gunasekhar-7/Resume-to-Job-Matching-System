"""Counterfactual fairness checks.

These checks establish invariance of the ranking under changes that should be
irrelevant to professional relevance: name, contact details, education institution and
graduation year. They do **not** establish demographic fairness; the synthetic corpus
has no demographic labels. Passing means the scoring path did not use those fields in
the tested variants.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from talentlens.matching.pipeline import MatchingPipeline
from talentlens.schemas import MatchResponse, ResumeDocument


@dataclass(frozen=True)
class CounterfactualVariant:
    name: str
    header: tuple[str, ...]
    education: tuple[str, ...]


VARIANTS: tuple[CounterfactualVariant, ...] = (
    CounterfactualVariant(
        "name_change",
        ("Alex Morgan", "alex.morgan@example.com", "+1 (555) 010-2000", "https://example.com/alex"),
        ("BSc Computer Science, Example State University, 2016",),
    ),
    CounterfactualVariant(
        "contact_change",
        ("Priya Raman", "contact@example.org", "+1 (555) 019-9999", "https://example.org/portfolio"),
        ("BSc Computer Science, Example State University, 2016",),
    ),
    CounterfactualVariant(
        "education_prestige_change",
        ("Alex Morgan", "alex.morgan@example.com", "+1 (555) 010-2000", "https://example.com/alex"),
        ("BSc Computer Science, Ivy League University, 2016",),
    ),
    CounterfactualVariant(
        "graduation_year_change",
        ("Alex Morgan", "alex.morgan@example.com", "+1 (555) 010-2000", "https://example.com/alex"),
        ("BSc Computer Science, Example State University, 1998",),
    ),
    CounterfactualVariant(
        "all_changes",
        ("Jordan Lee", "jordan.lee@example.net", "+1 (555) 011-3456", "https://example.net/jordan"),
        ("MSc Computer Science, Prestigious Institute, 2005",),
    ),
)


def counterfactual_document(
    document: ResumeDocument, variant: CounterfactualVariant
) -> ResumeDocument:
    """Return a document with only header and education content replaced.

    The resume's professional sections and extracted skill mentions are kept intact so
    the comparison isolates fields that the scoring path claims to ignore.
    """
    sections = deepcopy(document.sections)
    old_header = tuple(sections.get("header", []))
    sections["header"] = list(variant.header)
    sections["education"] = list(variant.education)
    full_text = document.full_text
    # Replace the old header lines where they occur, without changing professional text.
    for old, new in zip(old_header, variant.header, strict=False):
        if old and old in full_text:
            full_text = full_text.replace(old, new, 1)
    for line in old_header[len(variant.header) :]:
        if line and line in full_text:
            full_text = full_text.replace(line, "", 1)
    return document.model_copy(update={"sections": sections, "full_text": full_text})


def _snapshot(response: MatchResponse, top_k: int) -> dict[str, Any]:
    return {
        "job_ids": [match.job_id for match in response.results[:top_k]],
        "scores": [round(match.score, 12) for match in response.results[:top_k]],
        "components": [
            [
                match.score_breakdown.semantic,
                match.score_breakdown.section_relevance,
                match.score_breakdown.required_coverage,
                match.score_breakdown.preferred_coverage,
                match.score_breakdown.experience_alignment,
            ]
            for match in response.results[:top_k]
        ],
    }


def compare_rankings(
    baseline: MatchResponse, variant: MatchResponse, *, top_k: int = 10
) -> dict[str, Any]:
    left = _snapshot(baseline, top_k)
    right = _snapshot(variant, top_k)
    score_delta = 0.0
    for first, second in zip(left["scores"], right["scores"], strict=False):
        score_delta = max(score_delta, abs(first - second))
    component_delta = 0.0
    for first_row, second_row in zip(left["components"], right["components"], strict=False):
        for first, second in zip(first_row, second_row, strict=True):
            component_delta = max(component_delta, abs(first - second))
    return {
        "same_order": left["job_ids"] == right["job_ids"],
        "max_score_delta": round(score_delta, 12),
        "max_component_delta": round(component_delta, 12),
        "baseline_job_ids": left["job_ids"],
        "variant_job_ids": right["job_ids"],
    }


def run_counterfactual_fairness(
    pipeline: MatchingPipeline,
    documents: list[ResumeDocument],
    *,
    variants: tuple[CounterfactualVariant, ...] = VARIANTS,
    top_k: int = 10,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for document in documents:
        baseline = pipeline.match(document, top_k=top_k)
        for variant in variants:
            changed = counterfactual_document(document, variant)
            response = pipeline.match(changed, top_k=top_k)
            comparison = compare_rankings(baseline, response, top_k=top_k)
            results.append(
                {
                    "resume_id": document.resume_id,
                    "variant": variant.name,
                    **comparison,
                }
            )
    failed = [
        item
        for item in results
        if not item["same_order"]
        or item["max_score_delta"] > 1e-9
        or item["max_component_delta"] > 1e-9
    ]
    return {
        "checks": len(results),
        "passed": not failed,
        "top_k": top_k,
        "invariance_rule": "same top-k order, scores and component values within 1e-9",
        "variants": [variant.name for variant in variants],
        "results": results,
        "failures": failed,
        "scope": (
            "Counterfactual invariance only. No demographic labels exist, so statistical "
            "fairness across groups is not established."
        ),
    }

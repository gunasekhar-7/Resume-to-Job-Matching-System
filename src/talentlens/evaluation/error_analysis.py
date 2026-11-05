"""Error analysis over held-out rankings.

Produces concrete cases from actual rankings. It does not invent examples: every row
contains the observed rank, label, score and the explanation components for that
resume/job pair.
"""

from __future__ import annotations

from typing import Any

from talentlens.schemas import JobMatch, JobPosting


def _case(
    resume_id: str,
    match: JobMatch,
    *,
    relevance: int,
    kind: str,
) -> dict[str, Any]:
    explanation = match.explanation
    return {
        "resume_id": resume_id,
        "job_id": match.job_id,
        "title": match.title,
        "rank": match.rank,
        "score": match.score,
        "relevance": relevance,
        "kind": kind,
        "missing_required": [item.canonical for item in explanation.missing_required],
        "missing_preferred": [item.canonical for item in explanation.missing_preferred],
        "experience_status": explanation.experience.status.value,
        "experience_note": explanation.experience.notes,
        "top_evidence": (
            explanation.section_evidence[0].sentence if explanation.section_evidence else ""
        ),
        "score_components": match.score_breakdown.model_dump(
            include={
                "semantic",
                "section_relevance",
                "required_coverage",
                "preferred_coverage",
                "experience_alignment",
            }
        ),
    }


def analyse_rankings(
    rankings: dict[str, list[JobMatch]],
    labels: dict[str, dict[str, int]],
    jobs: dict[str, JobPosting],
    *,
    top_k: int = 10,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    summary: dict[str, int] = {}
    for resume_id, matches in sorted(rankings.items()):
        resume_labels = labels.get(resume_id, {})
        for match in matches[:top_k]:
            relevance = resume_labels.get(match.job_id)
            if relevance is None:
                continue
            if relevance == 0:
                kind = "strong_match_to_not_relevant_job"
            elif relevance == 1:
                kind = "partial_match_in_top_k"
            else:
                kind = "strong_match_in_top_k"
            summary[kind] = summary.get(kind, 0) + 1
            if relevance < 2:
                cases.append(_case(resume_id, match, relevance=relevance, kind=kind))
        # Strongly relevant jobs outside the top-k are misses, not top-k false positives.
        ranked_ids = {match.job_id for match in matches[:top_k]}
        for job_id, relevance in resume_labels.items():
            if relevance >= 2 and job_id not in ranked_ids:
                position = next(
                    (match.rank for match in matches if match.job_id == job_id),
                    None,
                )
                if position is not None:
                    match = next(item for item in matches if item.job_id == job_id)
                    summary["strong_relevant_below_top_k"] = (
                        summary.get("strong_relevant_below_top_k", 0) + 1
                    )
                    cases.append(
                        _case(resume_id, match, relevance=relevance, kind="strong_relevant_below_top_k")
                    )
    return {
        "top_k": top_k,
        "summary": summary,
        "cases": cases,
        "notes": [
            "Labels are single-annotator judgements on a synthetic corpus.",
            "A relevance-0 item in the top-k is a ranking error measured against those labels, "
            "not proof that the job is objectively unsuitable.",
            "Missing requirements mean they were not evidenced in the resume text.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Error Analysis - Held-out Split",
        "",
        "Generated from the actual held-out rankings and labels; no case is hand-invented. "
        "The labels are single-annotator synthetic judgements, so every finding is scoped to "
        "this corpus.",
        "",
        "## Summary",
        "",
        "| Outcome | Count |",
        "| --- | --- |",
    ]
    for key, value in sorted(report["summary"].items()):
        lines.append(f"| {key.replace('_', ' ')} | {value} |")
    lines.extend(
        [
            "",
            f"Top-k cutoff: {report['top_k']}.",
            "",
            "## Cases",
            "",
        ]
    )
    for index, case in enumerate(report["cases"][:12], start=1):
        lines.extend(
            [
                f"### {index}. {case['resume_id']} -> {case['job_id']} ({case['title']})",
                "",
                f"- Kind: `{case['kind']}`; rank {case['rank']}; score {case['score']:.3f}; "
                f"label {case['relevance']}.",
                f"- Missing required: {', '.join(case['missing_required']) or 'none'}.",
                f"- Missing preferred: {', '.join(case['missing_preferred']) or 'none'}.",
                f"- Experience: {case['experience_status']}"
                + (f" ({case['experience_note']})" if case["experience_note"] else "")
                + ".",
                f"- Evidence shown: {case['top_evidence'] or 'none crossed the threshold'}",
                "",
            ]
        )
    lines.extend(["## Interpretation", "", *[f"- {note}" for note in report["notes"]], ""])
    return "\n".join(lines)

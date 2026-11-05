"""Structured skill-gap reporting.

Coverage is evidence in the uploaded document. A missing skill means "not evidenced
here", never "the candidate lacks it". Required and preferred gaps stay separate and
the denominator is reported for every aggregate.
"""

from __future__ import annotations

from collections import Counter

from talentlens.matching.skill_matcher import match_skills
from talentlens.schemas import (
    FrequentSkillGap,
    JobPosting,
    JobSkillGap,
    MissingSkill,
    RequirementStatus,
    ResumeDocument,
    SkillGapReport,
    SkillRequirement,
)
from talentlens.skills.taxonomy import SkillTaxonomy, get_taxonomy


def build_skill_gap_report(
    document: ResumeDocument,
    jobs: list[JobPosting],
    *,
    taxonomy: SkillTaxonomy | None = None,
    max_jobs: int | None = None,
) -> SkillGapReport:
    taxonomy = taxonomy or get_taxonomy()
    ordered = sorted(jobs, key=lambda job: job.job_id)
    if max_jobs is not None:
        ordered = ordered[:max_jobs]
    per_job: list[JobSkillGap] = []
    required_counts: Counter[tuple[str, str]] = Counter()
    preferred_counts: Counter[tuple[str, str]] = Counter()

    for job in ordered:
        result = match_skills(document, job, taxonomy=taxonomy)
        per_job.append(
            JobSkillGap(
                job_id=job.job_id,
                title=job.title,
                required_coverage=result.required_coverage,
                preferred_coverage=result.preferred_coverage,
                required_evidenced=[
                    item for item in result.matched if item.requirement == SkillRequirement.REQUIRED
                ],
                required_missing=result.missing_required,
                preferred_evidenced=[
                    item for item in result.matched if item.requirement == SkillRequirement.PREFERRED
                ],
                preferred_missing=result.missing_preferred,
            )
        )
        for item in result.missing_required:
            required_counts[(item.canonical, item.category)] += 1
        for item in result.missing_preferred:
            preferred_counts[(item.canonical, item.category)] += 1

    def frequent(counts: Counter[tuple[str, str]], requirement: SkillRequirement) -> list[FrequentSkillGap]:
        return [
            FrequentSkillGap(
                canonical=canonical,
                category=category,
                job_count=count,
                requirement=requirement,
            )
            for (canonical, category), count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0][0].lower())
            )[:10]
        ]

    ambiguous = [
        MissingSkill(
            canonical=mention.canonical,
            category=mention.category,
            requirement=SkillRequirement.REQUIRED,
            job_evidence="Resume extraction was ambiguous; review the source phrase.",
            status=RequirementStatus.AMBIGUOUS,
            note=f"Original phrase: {mention.original_text!r}",
        )
        for mention in document.skills
        if mention.match_status == "ambiguous"
    ]

    report = SkillGapReport(
        resume_id=document.resume_id,
        jobs_analyzed=len(per_job),
        required_coverage_avg=(
            round(sum(item.required_coverage for item in per_job) / len(per_job), 6)
            if per_job
            else 0.0
        ),
        preferred_coverage_avg=(
            round(sum(item.preferred_coverage for item in per_job) / len(per_job), 6)
            if per_job
            else 0.0
        ),
        per_job=per_job,
        frequently_missing_required=frequent(required_counts, SkillRequirement.REQUIRED),
        frequently_missing_preferred=frequent(preferred_counts, SkillRequirement.PREFERRED),
        ambiguous_skills=ambiguous,
        notes=[
            "Coverage is based on evidence extracted from the uploaded document, not on a "
            "complete employment history.",
            "A missing skill means it was not evidenced here; it does not prove the candidate "
            "lacks the skill.",
            "Required and preferred gaps are reported separately with their own denominators.",
        ],
    )
    return report

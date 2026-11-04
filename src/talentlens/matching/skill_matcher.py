"""Required/preferred skill coverage with evidence.

Coverage is *evidence in the uploaded document*, not proof of proficiency. Required
and preferred skills are scored and reported separately. A related technology gets
only the partial credit declared in the taxonomy, never full exact credit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from talentlens.config import get_config
from talentlens.schemas import (
    JobPosting,
    JobSkill,
    MatchedSkill,
    MissingSkill,
    RequirementStatus,
    ResumeDocument,
    SkillMention,
    SkillRequirement,
)
from talentlens.skills.taxonomy import SkillTaxonomy, get_taxonomy
from talentlens.utils.text import truncate

#: Coverage applied when a posting states no requirements of that kind. A neutral
#: value avoids awarding a free perfect score for an underspecified posting.
NEUTRAL_COVERAGE = 0.5

_SECTION_PRIORITY = {
    "skills": 1.0,
    "experience": 1.0,
    "projects": 0.9,
    "summary": 0.6,
    "certifications": 0.7,
    "publications": 0.6,
    "additional": 0.4,
    "education": 0.4,
    "other": 0.3,
}


@dataclass
class SkillMatchResult:
    required_coverage: float
    preferred_coverage: float
    matched: list[MatchedSkill] = field(default_factory=list)
    missing_required: list[MissingSkill] = field(default_factory=list)
    missing_preferred: list[MissingSkill] = field(default_factory=list)
    required_total: int = 0
    preferred_total: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def required_matched_count(self) -> int:
        return sum(1 for item in self.matched if item.requirement == SkillRequirement.REQUIRED)

    @property
    def preferred_matched_count(self) -> int:
        return sum(1 for item in self.matched if item.requirement == SkillRequirement.PREFERRED)


def best_evidence(document: ResumeDocument) -> dict[str, SkillMention]:
    """Pick the strongest evidence per canonical skill (section, confidence, exactness)."""
    best: dict[str, SkillMention] = {}
    for mention in document.skills:
        current = best.get(mention.canonical)
        if current is None or _evidence_score(mention) > _evidence_score(current):
            best[mention.canonical] = mention
    return best


def _evidence_score(mention: SkillMention) -> tuple[float, float, int]:
    section_weight = _SECTION_PRIORITY.get(mention.section.value, 0.3)
    exact_bonus = 0.2 if mention.match_status == "canonical" else 0.0
    return (section_weight + exact_bonus, mention.confidence, len(mention.evidence))


def _related_candidate(
    job_skill: str, evidence: dict[str, SkillMention], taxonomy: SkillTaxonomy
) -> tuple[SkillMention, float] | None:
    best: tuple[SkillMention, float] | None = None
    for resume_skill, mention in evidence.items():
        credit = taxonomy.related_credit(resume_skill, job_skill)
        if credit <= 0:
            continue
        if best is None or credit > best[1] or (
            credit == best[1] and _evidence_score(mention) > _evidence_score(best[0])
        ):
            best = (mention, credit)
    return best


def match_skills(
    document: ResumeDocument,
    job: JobPosting,
    *,
    taxonomy: SkillTaxonomy | None = None,
) -> SkillMatchResult:
    taxonomy = taxonomy or get_taxonomy()
    weights = get_config().get("matching.section_weights", {}) or {}
    evidence = best_evidence(document)
    required_names = {skill.canonical for skill in job.required_skills}
    preferred_names = {skill.canonical for skill in job.preferred_skills} - required_names
    result = SkillMatchResult(
        required_coverage=0.0,
        preferred_coverage=0.0,
        required_total=len(required_names),
        preferred_total=len(preferred_names),
    )

    required_scores: list[float] = []
    preferred_scores: list[float] = []
    seen_required: set[str] = set()
    seen_preferred: set[str] = set()

    for job_skill in job.required_skills:
        # A duplicated requirement row must not inflate coverage or evidence counts.
        if job_skill.canonical in seen_required:
            continue
        seen_required.add(job_skill.canonical)
        score = _score_requirement(job_skill, evidence, taxonomy, SkillRequirement.REQUIRED, result, weights)
        required_scores.append(score)
    for job_skill in job.preferred_skills:
        if job_skill.canonical in required_names or job_skill.canonical in seen_preferred:
            # Never double-count: a required skill is not also credited as preferred.
            continue
        seen_preferred.add(job_skill.canonical)
        score = _score_requirement(job_skill, evidence, taxonomy, SkillRequirement.PREFERRED, result, weights)
        preferred_scores.append(score)

    if required_scores:
        result.required_coverage = round(sum(required_scores) / len(required_scores), 6)
    else:
        result.required_coverage = NEUTRAL_COVERAGE
        result.notes.append(
            "The posting specifies no required skills; neutral required-skill coverage (0.50) applied."
        )
    if preferred_scores:
        result.preferred_coverage = round(sum(preferred_scores) / len(preferred_scores), 6)
    else:
        result.preferred_coverage = NEUTRAL_COVERAGE
        result.notes.append(
            "The posting specifies no preferred skills; neutral preferred-skill coverage (0.50) applied."
        )

    if not document.skills:
        result.notes.append("No skills were extracted from this resume; skill coverage is zero or neutral.")
    return result


def _score_requirement(
    job_skill: JobSkill,
    evidence: dict[str, SkillMention],
    taxonomy: SkillTaxonomy,
    requirement: SkillRequirement,
    result: SkillMatchResult,
    section_weights: dict,
) -> float:
    direct = evidence.get(job_skill.canonical)
    if direct is not None:
        result.matched.append(
            MatchedSkill(
                canonical=job_skill.canonical,
                category=job_skill.category,
                requirement=requirement,
                job_evidence=truncate(job_skill.evidence, 400),
                resume_phrase=direct.original_text,
                resume_section=direct.section,
                resume_evidence=truncate(direct.evidence, 400),
                credit=1.0,
                match_type="exact",
                extraction_method=direct.extraction_method,
            )
        )
        return 1.0

    related = _related_candidate(job_skill.canonical, evidence, taxonomy)
    if related is not None:
        mention, credit = related
        result.matched.append(
            MatchedSkill(
                canonical=job_skill.canonical,
                category=job_skill.category,
                requirement=requirement,
                job_evidence=truncate(job_skill.evidence, 400),
                resume_phrase=mention.original_text,
                resume_section=mention.section,
                resume_evidence=truncate(mention.evidence, 400),
                credit=round(float(credit), 3),
                match_type="related",
                extraction_method=mention.extraction_method,
            )
        )
        return float(credit)

    missing = MissingSkill(
        canonical=job_skill.canonical,
        category=job_skill.category,
        requirement=requirement,
        job_evidence=truncate(job_skill.evidence, 400),
        status=RequirementStatus.NOT_EVIDENCED,
        note=(
            f"Not evidenced in the uploaded resume (matched against resume sections with "
            f"section weight {section_weights.get('skills', 0.5):.1f} for the skills list). "
            "Absence from this document does not prove the candidate lacks the skill."
        ),
    )
    if requirement == SkillRequirement.REQUIRED:
        result.missing_required.append(missing)
    else:
        result.missing_preferred.append(missing)
    return 0.0

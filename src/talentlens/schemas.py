"""Shared Pydantic schemas.

These models are the contract between phases: Phase 1 produces
``ResumeDocument`` and ``JobPosting``; Phase 2 consumes them and produces
``JobMatch`` / ``MatchResponse``; Phase 3 attaches ``MatchExplanation``;
Phase 4 persists them and serves them over the API.

Evidence references are first-class: every skill mention, explanation and
match keeps a pointer to the source text (section + evidence snippet + character
offsets where available).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0.0"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=False)


class SectionName(str, Enum):
    HEADER = "header"
    SUMMARY = "summary"
    SKILLS = "skills"
    EXPERIENCE = "experience"
    PROJECTS = "projects"
    EDUCATION = "education"
    CERTIFICATIONS = "certifications"
    PUBLICATIONS = "publications"
    ADDITIONAL = "additional"
    OTHER = "other"


#: Canonical display/iteration order used across parsing, evaluation and the UI.
SECTION_ORDER: tuple[str, ...] = (
    SectionName.SUMMARY.value,
    SectionName.SKILLS.value,
    SectionName.EXPERIENCE.value,
    SectionName.PROJECTS.value,
    SectionName.EDUCATION.value,
    SectionName.CERTIFICATIONS.value,
    SectionName.PUBLICATIONS.value,
    SectionName.ADDITIONAL.value,
    SectionName.OTHER.value,
)

SECTION_LABELS: dict[str, str] = {
    "header": "Header / Contact",
    "summary": "Summary",
    "skills": "Skills",
    "experience": "Experience",
    "projects": "Projects",
    "education": "Education",
    "certifications": "Certifications",
    "publications": "Publications",
    "additional": "Additional Information",
    "other": "Other",
}


class ParsingStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class SourceFormat(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"


class SkillRequirement(str, Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"


class RequirementStatus(str, Enum):
    NOT_EVIDENCED = "not_evidenced"
    AMBIGUOUS = "ambiguous"


class ExperienceStatus(str, Enum):
    CLEAR_MATCH = "clear_match"
    PARTIAL_MATCH = "partial_match"
    BELOW_REQUIREMENT = "below_requirement"
    INSUFFICIENT_INFORMATION = "insufficient_information"


class ProcessingStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
class SectionSpan(_Model):
    """One contiguous block of resume text attributed to a section."""

    section: SectionName
    heading: str | None = None
    text: str
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)
    order: int = Field(default=0, ge=0)
    source_page: int | None = Field(default=None, ge=1)

    @field_validator("end_char")
    @classmethod
    def _end_after_start(cls, value: int | None, info: Any) -> int | None:  # pragma: no cover - simple guard
        start = info.data.get("start_char")
        if value is not None and start is not None and value < start:
            raise ValueError("end_char must be >= start_char")
        return value


class ResumeMetadata(_Model):
    source_format: SourceFormat
    source_filename: str
    sha256: str
    page_count: int | None = Field(default=None, ge=0)
    parsing_status: ParsingStatus = ParsingStatus.SUCCESS
    warnings: list[str] = Field(default_factory=list)
    ocr_used: bool = False
    ocr_confidence: float | None = Field(default=None, ge=0, le=100)
    char_count: int = Field(default=0, ge=0)
    extraction_quality: float = Field(default=0.0, ge=0, le=1)
    parser_version: str = "1.0.0"
    parsed_at: datetime = Field(default_factory=utcnow)
    pii_entity_types: list[str] = Field(default_factory=list)
    #: True when the document looked like a scanned PDF and OCR was not available.
    low_text_warning: bool = False


class SkillMention(_Model):
    """A skill occurrence in a document, with evidence and provenance."""

    original_text: str
    canonical: str
    category: str
    section: SectionName
    evidence: str
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)
    extraction_method: Literal["phrase_matcher", "regex_alias", "section_list", "job_requirement"] = (
        "phrase_matcher"
    )
    match_status: Literal["canonical", "alias", "case_sensitive_alias", "ambiguous"] = "canonical"
    confidence: float = Field(default=1.0, ge=0, le=1)
    normalized_from: str | None = None

    @property
    def is_strong_evidence(self) -> bool:
        return self.section in (SectionName.SKILLS, SectionName.EXPERIENCE, SectionName.PROJECTS)


class ResumeDocument(_Model):
    resume_id: str
    full_text: str
    sections: dict[str, list[str]] = Field(default_factory=dict)
    section_spans: list[SectionSpan] = Field(default_factory=list)
    skills: list[SkillMention] = Field(default_factory=list)
    metadata: ResumeMetadata
    schema_version: str = SCHEMA_VERSION

    @field_validator("resume_id")
    @classmethod
    def _resume_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("resume_id must not be blank")
        return value.strip()

    def section_text(self, name: str | SectionName, *, joiner: str = "\n") -> str:
        key = name.value if isinstance(name, SectionName) else name
        return joiner.join(self.sections.get(key, []))

    def skill_names(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for skill in self.skills:
            if skill.canonical not in seen:
                seen.add(skill.canonical)
                ordered.append(skill.canonical)
        return ordered

    def skills_in_sections(self, sections: set[SectionName]) -> list[SkillMention]:
        return [skill for skill in self.skills if skill.section in sections]

    def evidence_for(self, canonical: str) -> list[SkillMention]:
        return [skill for skill in self.skills if skill.canonical.lower() == canonical.lower()]


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
class JobSkill(_Model):
    canonical: str
    category: str
    original_text: str
    requirement: SkillRequirement
    evidence: str
    confidence: float = Field(default=1.0, ge=0, le=1)


class JobMetadata(_Model):
    source_format: Literal["manual", "csv", "json", "api"] = "manual"
    source_name: str | None = None
    validation_warnings: list[str] = Field(default_factory=list)
    sha256: str = ""
    imported_at: datetime = Field(default_factory=utcnow)
    language: str = "en"


class JobPosting(_Model):
    job_id: str
    title: str
    company: str
    description: str
    responsibilities: list[str] = Field(default_factory=list)
    required_skills: list[JobSkill] = Field(default_factory=list)
    preferred_skills: list[JobSkill] = Field(default_factory=list)
    min_years_experience: float | None = Field(default=None, ge=0)
    max_years_experience: float | None = Field(default=None, ge=0)
    seniority: str | None = None
    education_level: str | None = None
    certifications: list[str] = Field(default_factory=list)
    location: str | None = None
    work_arrangement: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    employment_type: str | None = None
    salary_range: str | None = None
    source: str | None = None
    posted_date: date | None = None
    metadata: JobMetadata = Field(default_factory=JobMetadata)
    schema_version: str = SCHEMA_VERSION

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value.strip()

    @field_validator("max_years_experience")
    @classmethod
    def _max_ge_min(cls, value: float | None, info: Any) -> float | None:
        minimum = info.data.get("min_years_experience")
        if value is not None and minimum is not None and value < minimum:
            raise ValueError("max_years_experience must be >= min_years_experience")
        return value

    @property
    def required_skill_names(self) -> list[str]:
        return _unique(skill.canonical for skill in self.required_skills)

    @property
    def preferred_skill_names(self) -> list[str]:
        return _unique(skill.canonical for skill in self.preferred_skills)

    def searchable_text(self) -> str:
        parts = [self.title, self.company, self.description, *self.responsibilities]
        parts.extend(skill.original_text for skill in self.required_skills)
        parts.extend(skill.original_text for skill in self.preferred_skills)
        return "\n".join(part for part in parts if part)

    def requirements_text(self) -> str:
        parts = [self.description, *self.responsibilities]
        parts.extend(f"Required: {skill.original_text}" for skill in self.required_skills)
        parts.extend(f"Preferred: {skill.original_text}" for skill in self.preferred_skills)
        return "\n".join(part for part in parts if part)


class JobRecord(_Model):
    """A stored job plus the vector/index bookkeeping used by retrieval."""

    job: JobPosting
    content_sha256: str
    embedding_model: str | None = None
    indexed_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #
class ScoreContribution(_Model):
    component: str
    raw: float
    weight: float
    contribution: float
    label: str


class ScoreBreakdown(_Model):
    semantic: float = Field(ge=0, le=1)
    section_relevance: float = Field(ge=0, le=1)
    required_coverage: float = Field(ge=0, le=1)
    preferred_coverage: float = Field(ge=0, le=1)
    experience_alignment: float = Field(ge=0, le=1)
    total: float = Field(ge=0, le=1)
    weights: dict[str, float] = Field(default_factory=dict)
    contributions: list[ScoreContribution] = Field(default_factory=list)
    explanation: str = ""


class MatchedSkill(_Model):
    canonical: str
    category: str
    requirement: SkillRequirement
    job_evidence: str
    resume_phrase: str
    resume_section: SectionName
    resume_evidence: str
    credit: float = Field(ge=0, le=1)
    match_type: Literal["exact", "related"] = "exact"
    extraction_method: str = "phrase_matcher"


class MissingSkill(_Model):
    canonical: str
    category: str
    requirement: SkillRequirement
    job_evidence: str
    status: RequirementStatus = RequirementStatus.NOT_EVIDENCED
    note: str = ""


class ExperienceAlignment(_Model):
    status: ExperienceStatus
    required_years: float | None = None
    resume_years: float | None = None
    score: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    notes: str = ""
    professional_roles: int = Field(default=0, ge=0)
    has_internships: bool = False
    has_projects: bool = False


class SectionEvidence(_Model):
    section: SectionName
    sentence: str
    similarity: float = Field(ge=0, le=1)
    start_char: int | None = None


class MatchExplanation(_Model):
    summary: str
    score_breakdown: ScoreBreakdown
    matched_skills: list[MatchedSkill] = Field(default_factory=list)
    missing_required: list[MissingSkill] = Field(default_factory=list)
    missing_preferred: list[MissingSkill] = Field(default_factory=list)
    experience: ExperienceAlignment
    section_evidence: list[SectionEvidence] = Field(default_factory=list)
    methodology_notes: list[str] = Field(default_factory=list)


class JobMatch(_Model):
    job_id: str
    title: str
    company: str
    location: str | None = None
    work_arrangement: str | None = None
    seniority: str | None = None
    rank: int = Field(ge=1)
    score: float = Field(ge=0, le=1)
    score_breakdown: ScoreBreakdown
    explanation: MatchExplanation
    retrieval_source: Literal["tfidf", "semantic", "hybrid", "reranked", "skill"] = "hybrid"


class JobSkillGap(_Model):
    job_id: str
    title: str
    required_coverage: float = Field(ge=0, le=1)
    preferred_coverage: float = Field(ge=0, le=1)
    required_evidenced: list[MatchedSkill] = Field(default_factory=list)
    required_missing: list[MissingSkill] = Field(default_factory=list)
    preferred_evidenced: list[MatchedSkill] = Field(default_factory=list)
    preferred_missing: list[MissingSkill] = Field(default_factory=list)


class FrequentSkillGap(_Model):
    canonical: str
    category: str
    job_count: int = Field(ge=0)
    requirement: SkillRequirement = SkillRequirement.REQUIRED


class SkillGapReport(_Model):
    resume_id: str
    jobs_analyzed: int = Field(ge=0)
    required_coverage_avg: float = Field(default=0.0, ge=0, le=1)
    preferred_coverage_avg: float = Field(default=0.0, ge=0, le=1)
    per_job: list[JobSkillGap] = Field(default_factory=list)
    frequently_missing_required: list[FrequentSkillGap] = Field(default_factory=list)
    frequently_missing_preferred: list[FrequentSkillGap] = Field(default_factory=list)
    ambiguous_skills: list[MissingSkill] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class IndexMetadata(_Model):
    index_version: str
    index_type: str
    metric: str
    embedding_model: str
    embedding_dim: int = Field(ge=1)
    job_count: int = Field(ge=0)
    job_ids: list[str] = Field(default_factory=list)
    built_at: datetime = Field(default_factory=utcnow)
    content_hashes: dict[str, str] = Field(default_factory=dict)
    config_version: str = "unknown"


class MatchResponse(_Model):
    resume_id: str
    results: list[JobMatch] = Field(default_factory=list)
    query_skills: list[str] = Field(default_factory=list)
    retrieval: str = "hybrid"
    model_id: str
    index_version: str | None = None
    config_version: str
    weights: dict[str, float] = Field(default_factory=dict)
    reranked: bool = False
    generated_at: datetime = Field(default_factory=utcnow)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ParsedResumeResponse(_Model):
    resume_id: str
    sections: dict[str, list[str]] = Field(default_factory=dict)
    skills: list[SkillMention] = Field(default_factory=list)
    metadata: ResumeMetadata
    warnings: list[str] = Field(default_factory=list)


def _unique(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result

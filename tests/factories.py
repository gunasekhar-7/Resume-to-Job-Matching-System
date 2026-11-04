"""Plain factories for matching tests (no pytest fixtures)."""

from __future__ import annotations

from talentlens.schemas import (
    JobMetadata,
    JobPosting,
    JobSkill,
    ResumeDocument,
    ResumeMetadata,
    SectionName,
    SkillMention,
    SkillRequirement,
    SourceFormat,
)


def mention(
    canonical: str,
    section: SectionName = SectionName.SKILLS,
    confidence: float = 1.0,
    evidence: str | None = None,
) -> SkillMention:
    return SkillMention(
        original_text=canonical,
        canonical=canonical,
        category="programming_languages",
        section=section,
        evidence=evidence or f"Used {canonical} in production.",
        extraction_method="section_list",
        match_status="canonical",
        confidence=confidence,
    )


def resume_with(
    skills: list[SkillMention],
    *,
    experience: list[str] | None = None,
    projects: list[str] | None = None,
    education: list[str] | None = None,
    full_text: str = "Test resume",
) -> ResumeDocument:
    sections = {
        "skills": [skill.canonical for skill in skills],
        "experience": experience or [],
        "projects": projects or [],
        "education": education or [],
    }
    return ResumeDocument(
        resume_id="test_resume",
        full_text=full_text,
        sections=sections,
        skills=skills,
        metadata=ResumeMetadata(
            source_format=SourceFormat.TXT,
            source_filename="test.txt",
            sha256="0" * 64,
        ),
    )


def job_with(required: list[str], preferred: list[str] | None = None, **kwargs) -> JobPosting:
    return JobPosting(
        job_id=kwargs.pop("job_id", "job_test"),
        title=kwargs.pop("title", "Machine Learning Engineer"),
        company=kwargs.pop("company", "Test Co"),
        description=kwargs.pop("description", "Build ML systems."),
        required_skills=[
            JobSkill(
                canonical=name,
                category="machine_learning",
                original_text=name,
                requirement=SkillRequirement.REQUIRED,
                evidence=f"Requirements: {name}",
            )
            for name in required
        ],
        preferred_skills=[
            JobSkill(
                canonical=name,
                category="machine_learning",
                original_text=name,
                requirement=SkillRequirement.PREFERRED,
                evidence=f"Preferred: {name}",
            )
            for name in (preferred or [])
        ],
        metadata=JobMetadata(),
        **kwargs,
    )

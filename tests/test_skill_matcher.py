from __future__ import annotations

from factories import job_with, mention, resume_with
from talentlens.matching.skill_matcher import NEUTRAL_COVERAGE, match_skills
from talentlens.schemas import SectionName, SkillRequirement


def test_exact_required_and_missing_preferred_are_separate(taxonomy):
    resume = resume_with([mention("Python")])
    job = job_with(["Python", "Kubernetes"], ["AWS"])
    result = match_skills(resume, job, taxonomy=taxonomy)

    assert result.required_total == 2
    assert result.required_coverage == 0.5
    assert [item.canonical for item in result.matched] == ["Python"]
    assert result.matched[0].credit == 1.0
    assert result.matched[0].requirement == SkillRequirement.REQUIRED
    assert [item.canonical for item in result.missing_required] == ["Kubernetes"]
    assert [item.canonical for item in result.missing_preferred] == ["AWS"]
    assert result.missing_required[0].status.value == "not_evidenced"
    assert "does not prove" in result.missing_required[0].note


def test_related_skill_gets_partial_not_full_credit(taxonomy):
    resume = resume_with([mention("PyTorch")])
    job = job_with(["TensorFlow"])
    result = match_skills(resume, job, taxonomy=taxonomy)

    assert result.required_coverage == 0.5
    assert result.matched[0].match_type == "related"
    assert result.matched[0].credit == 0.5
    assert result.missing_required == []


def test_skill_never_counted_as_required_and_preferred(taxonomy):
    resume = resume_with([mention("Python")])
    job = job_with(["Python"], ["Python"])
    result = match_skills(resume, job, taxonomy=taxonomy)

    assert len(result.matched) == 1
    assert result.matched[0].requirement == SkillRequirement.REQUIRED
    assert result.preferred_coverage == NEUTRAL_COVERAGE


def test_strongest_section_is_used_for_evidence(taxonomy):
    weak = mention("Python", section=SectionName.SUMMARY, confidence=0.7)
    strong = mention(
        "Python",
        section=SectionName.EXPERIENCE,
        confidence=0.95,
        evidence="Built Python services handling 2M requests/day.",
    )
    result = match_skills(resume_with([weak, strong]), job_with(["Python"]), taxonomy=taxonomy)

    assert result.matched[0].resume_section == SectionName.EXPERIENCE
    assert "2M requests" in result.matched[0].resume_evidence
    assert len(result.matched) == 1


def test_duplicate_requirement_rows_are_not_double_counted(taxonomy):
    result = match_skills(resume_with([mention("Python")]), job_with(["Python", "Python"]), taxonomy=taxonomy)
    assert result.required_total == 1
    assert len(result.matched) == 1
    assert result.required_coverage == 1.0


def test_no_requirements_uses_neutral_coverage(taxonomy):
    result = match_skills(resume_with([mention("Python")]), job_with([]), taxonomy=taxonomy)
    assert result.required_coverage == NEUTRAL_COVERAGE
    assert result.preferred_coverage == NEUTRAL_COVERAGE
    assert result.notes


def test_empty_resume_has_zero_required_coverage(taxonomy):
    result = match_skills(resume_with([]), job_with(["Python"]), taxonomy=taxonomy)
    assert result.required_coverage == 0.0
    assert result.missing_required
    assert any("No skills" in note for note in result.notes)

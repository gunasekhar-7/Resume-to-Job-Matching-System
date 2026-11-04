from __future__ import annotations

from datetime import date

import pytest

from factories import job_with, resume_with
from talentlens.matching.experience_matcher import align_experience, extract_experience, parse_period
from talentlens.schemas import ExperienceStatus

TODAY = date(2026, 1, 1)


def test_parse_period_supports_common_formats():
    assert parse_period("2020-01 - 2021-01", today=TODAY) is not None
    assert parse_period("Jan 2020 - Dec 2021", today=TODAY) is not None
    assert parse_period("01/2020 to 06/2022", today=TODAY) is not None
    assert parse_period("2018 - 2020", today=TODAY) is not None
    assert parse_period("Present", today=TODAY) is None
    assert parse_period("2024 - 2020", today=TODAY) is None


def test_extracts_professional_tenure_from_dated_roles():
    document = resume_with(
        [], experience=["Senior ML Engineer | Acme | 2020-01 - present", "Bengaluru, India"]
    )
    evidence = extract_experience(document, today=TODAY)

    assert evidence.professional_roles == 1
    assert evidence.professional_years == pytest.approx(6.08, abs=0.02)
    assert evidence.roles[0]["company"] == "Acme"
    assert not evidence.has_internships


def test_internships_are_counted_partially_and_reported_separately():
    document = resume_with([], experience=["ML Intern | Acme | 2025-06 - 2025-09"])
    evidence = extract_experience(document, today=TODAY)

    assert evidence.has_internships
    assert evidence.professional_roles == 0
    assert evidence.professional_months == 0
    assert evidence.professional_years == 0.0
    assert evidence.internship_months == 4
    assert evidence.effective_years == pytest.approx(4 * 0.5 / 12, abs=0.01)


def test_clear_match_for_required_years():
    document = resume_with([], experience=["Senior ML Engineer | Acme | 2020-01 - present"])
    alignment = align_experience(document, job_with(["Python"], min_years_experience=5), today=TODAY)
    assert alignment.status == ExperienceStatus.CLEAR_MATCH
    assert alignment.score == 1.0
    assert alignment.resume_years == pytest.approx(6.08, abs=0.02)
    assert alignment.evidence


def test_below_requirement_is_partial_and_explained():
    document = resume_with([], experience=["ML Engineer | Acme | 2023-01 - 2024-01"])
    alignment = align_experience(document, job_with(["Python"], min_years_experience=3), today=TODAY)
    assert alignment.status == ExperienceStatus.BELOW_REQUIREMENT
    assert alignment.score < 1.0
    assert alignment.resume_years == pytest.approx(1.08, abs=0.02)
    assert "minimum" in alignment.notes


def test_undated_experience_is_insufficient_not_zero():
    document = resume_with([], experience=["Senior Engineer at Acme", "Built data platforms"])
    alignment = align_experience(document, job_with(["Python"], min_years_experience=3), today=TODAY)
    assert alignment.status == ExperienceStatus.INSUFFICIENT_INFORMATION
    assert alignment.score == 0.5
    assert alignment.resume_years is None
    assert "not treated as zero" in alignment.notes


def test_fresher_role_requires_no_experience():
    document = resume_with([])
    alignment = align_experience(document, job_with(["Python"], min_years_experience=0), today=TODAY)
    assert alignment.status == ExperienceStatus.CLEAR_MATCH
    assert alignment.score == 1.0


def test_junior_upper_bound_still_flags_overqualification():
    document = resume_with([], experience=["Principal Engineer | Acme | 2010-01 - present"])
    alignment = align_experience(
        document,
        job_with(["Python"], min_years_experience=0, max_years_experience=2),
        today=TODAY,
    )
    assert alignment.status == ExperienceStatus.PARTIAL_MATCH
    assert alignment.score == 0.75


def test_absent_requirement_gets_neutral_score():
    document = resume_with([], experience=["ML Engineer | Acme | 2020-01 - 2024-01"])
    alignment = align_experience(document, job_with(["Python"]), today=TODAY)
    assert alignment.status == ExperienceStatus.INSUFFICIENT_INFORMATION
    assert alignment.score == 0.6


def test_overqualified_candidate_is_partial_not_rejected():
    document = resume_with([], experience=["Principal Engineer | Acme | 2010-01 - present"])
    alignment = align_experience(
        document,
        job_with(["Python"], min_years_experience=3, max_years_experience=5),
        today=TODAY,
    )
    assert alignment.status == ExperienceStatus.PARTIAL_MATCH
    assert alignment.score == 0.75
    assert "seniority" in alignment.notes


def test_education_dates_are_never_counted_as_experience():
    document = resume_with([], education=["BSc Computer Science | 2014 - 2018"])
    alignment = align_experience(document, job_with(["Python"], min_years_experience=4), today=TODAY)
    assert alignment.status == ExperienceStatus.INSUFFICIENT_INFORMATION
    assert alignment.resume_years is None


def test_projects_are_not_professional_experience():
    document = resume_with([], projects=["Built a recommendation engine"])
    alignment = align_experience(document, job_with(["Python"], min_years_experience=2), today=TODAY)
    assert alignment.status == ExperienceStatus.INSUFFICIENT_INFORMATION
    assert alignment.has_projects is True
    assert alignment.resume_years is None

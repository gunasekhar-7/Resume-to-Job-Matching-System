"""Experience and seniority alignment.

Rules (see docs/MATCHING_METHODOLOGY.md):
* Only the resume ``experience`` section is used for professional tenure; education
  dates are never treated as work experience and age is never inferred.
* Internships are counted at a configurable partial weight and reported separately.
* Projects are preserved and reported but are not professional experience by default.
* Undated experience produces "insufficient information", never an assumed zero.
* A posting with no explicit experience requirement receives a neutral score rather
  than a free perfect one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from talentlens.config import get_config
from talentlens.schemas import (
    ExperienceAlignment,
    ExperienceStatus,
    JobPosting,
    ResumeDocument,
    SectionName,
)
from talentlens.utils.text import truncate

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_DATE_TOKEN = r"(?:\d{4}-\d{1,2}|\d{1,2}/\d{4}|[A-Za-z]{3,9}\.?\s+\d{4}|\d{4})"
_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE_TOKEN})\s*(?:-|–|—|to)\s*(?P<end>present|current|now|{_DATE_TOKEN})",
    re.IGNORECASE,
)
_INTERN_RE = re.compile(r"\b(intern|internship|trainee|apprentice)\b", re.IGNORECASE)


def _month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


def _parse_token(token: str, *, is_end: bool, today: date) -> int | None:
    token = token.strip().lower().rstrip(".")
    if token in {"present", "current", "now"}:
        return _month_index(today.year, today.month)
    if re.fullmatch(r"\d{4}", token):
        year = int(token)
        return _month_index(year, 12 if is_end else 1)
    match = re.fullmatch(r"(\d{4})-(\d{1,2})", token)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return _month_index(year, month)
        return None
    match = re.fullmatch(r"(\d{1,2})/(\d{4})", token)
    if match:
        month, year = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return _month_index(year, month)
        return None
    match = re.fullmatch(r"([a-z]{3,9})\.?\s+(\d{4})", token)
    if match and match.group(1) in _MONTHS:
        return _month_index(int(match.group(2)), _MONTHS[match.group(1)])
    return None


def parse_period(text: str, *, today: date | None = None) -> tuple[int, int, str] | None:
    """Parse the first date range in ``text`` into inclusive month indexes."""
    today = today or date.today()
    match = _RANGE_RE.search(text or "")
    if not match:
        return None
    start = _parse_token(match.group("start"), is_end=False, today=today)
    end = _parse_token(match.group("end"), is_end=True, today=today)
    if start is None or end is None or end < start:
        return None
    # Guard against typos that would imply an implausible career length.
    if end - start > 600:
        return None
    if start > _month_index(today.year + 1, 12):
        return None
    return start, end, match.group(0)


@dataclass
class ExperienceEvidence:
    professional_months: int = 0
    internship_months: int = 0
    roles: list[dict] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    has_experience_section: bool = False
    has_projects: bool = False

    @property
    def professional_years(self) -> float | None:
        if not self.roles:
            return None
        return round(self.professional_months / 12.0, 2)

    @property
    def effective_years(self) -> float | None:
        if not self.roles:
            return None
        weight = float(get_config().get("experience.internship_weight", 0.5))
        return round((self.professional_months + self.internship_months * weight) / 12.0, 2)

    @property
    def professional_roles(self) -> int:
        return sum(1 for role in self.roles if not role["internship"])

    @property
    def has_internships(self) -> bool:
        return any(role["internship"] for role in self.roles)


def _merge_months(intervals: list[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    ordered = sorted(intervals)
    total = 0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end + 1:
            current_end = max(current_end, end)
        else:
            total += current_end - current_start + 1
            current_start, current_end = start, end
    total += current_end - current_start + 1
    return total


def _split_role_line(line: str, match_start: int, match_text: str) -> tuple[str, str | None]:
    prefix = line[:match_start].strip(" \t|-–—,:;")
    prefix = re.sub(r"\s{2,}", " ", prefix)
    if not prefix:
        return "Role (title not parsed)", None
    if "|" in prefix:
        parts = [part.strip() for part in prefix.split("|") if part.strip()]
        title = parts[0]
        company = parts[1] if len(parts) > 1 else None
        return truncate(title, 100), truncate(company, 100) if company else None
    match = re.split(r"\s+at\s+", prefix, maxsplit=1, flags=re.IGNORECASE)
    if len(match) == 2:
        return truncate(match[0], 100), truncate(match[1], 100)
    # "Title, Company" is common; only split when the tail looks like an organisation.
    if "," in prefix:
        title, tail = [part.strip() for part in prefix.split(",", 1)]
        if len(tail.split()) <= 6:
            return truncate(title, 100), truncate(tail, 100)
    return truncate(prefix, 100), None


def extract_experience(document: ResumeDocument, *, today: date | None = None) -> ExperienceEvidence:
    section_lines = document.sections.get(SectionName.EXPERIENCE.value, [])
    evidence = ExperienceEvidence(
        has_experience_section=bool(section_lines),
        has_projects=bool(document.sections.get(SectionName.PROJECTS.value)),
    )
    professional: list[tuple[int, int]] = []
    internships: list[tuple[int, int]] = []

    for line in section_lines:
        cleaned = " ".join(line.split())
        if not cleaned:
            continue
        period = parse_period(cleaned, today=today)
        if period is None:
            continue
        start, end, matched_text = period
        title, company = _split_role_line(cleaned, cleaned.lower().find(matched_text.lower()), matched_text)
        is_internship = bool(_INTERN_RE.search(title or ""))
        evidence.roles.append(
            {
                "title": title,
                "company": company,
                "start": start,
                "end": end,
                "months": end - start + 1,
                "internship": is_internship,
                "line": truncate(cleaned, 300),
            }
        )
        evidence.evidence.append(truncate(cleaned, 300))
        (internships if is_internship else professional).append((start, end))

    evidence.professional_months = _merge_months(professional)
    evidence.internship_months = _merge_months(internships)
    if not evidence.roles:
        evidence.notes.append(
            "No dated roles were found in the experience section; tenure is reported as unknown rather than zero."
        )
    if evidence.has_internships:
        weight = float(get_config().get("experience.internship_weight", 0.5))
        evidence.notes.append(
            f"Internship months are counted at {weight:.0%} weight for alignment and reported separately."
        )
    if evidence.has_projects and not professional:
        evidence.notes.append(
            "Projects are reported separately and are not counted as professional experience."
        )
    return evidence


def align_experience(
    document: ResumeDocument,
    job: JobPosting,
    *,
    today: date | None = None,
) -> ExperienceAlignment:
    config = get_config()
    evidence = extract_experience(document, today=today)
    minimum = job.min_years_experience
    maximum = job.max_years_experience
    years = evidence.effective_years

    base = ExperienceAlignment(
        status=ExperienceStatus.INSUFFICIENT_INFORMATION,
        required_years=minimum,
        resume_years=evidence.professional_years,
        score=float(config.get("experience.insufficient_information_score", 0.5)),
        evidence=evidence.evidence[:6],
        notes="",
        professional_roles=evidence.professional_roles,
        has_internships=evidence.has_internships,
        has_projects=evidence.has_projects,
    )

    if minimum is None and maximum is None:
        base.status = ExperienceStatus.INSUFFICIENT_INFORMATION
        base.score = float(config.get("experience.neutral_alignment_score", 0.6))
        base.notes = "The posting states no explicit experience requirement; neutral alignment applied."
        return base

    if years is None:
        if minimum is None or minimum == 0:
            base.status = ExperienceStatus.CLEAR_MATCH
            base.score = 1.0
            base.notes = "No professional tenure could be measured, but the posting requires none (fresher-friendly)."
        else:
            base.status = ExperienceStatus.INSUFFICIENT_INFORMATION
            base.score = float(config.get("experience.insufficient_information_score", 0.5))
            base.notes = (
                "The resume does not contain dated professional experience, so alignment cannot be measured. "
                "This is not treated as zero years."
            )
        return base

    base.resume_years = years
    if minimum is None or minimum == 0:
        if maximum is not None and years > maximum + 2:
            base.status = ExperienceStatus.PARTIAL_MATCH
            base.score = 0.75
            base.notes = (
                f"Evidence indicates {years:.1f} years vs a stated maximum of {maximum:g}; "
                "the posting may target a different seniority level."
            )
            return base
        base.status = ExperienceStatus.CLEAR_MATCH
        base.score = 1.0
        base.notes = "The posting requires no minimum professional experience."
        return base

    if years + 0.25 < minimum:
        base.status = ExperienceStatus.BELOW_REQUIREMENT
        base.score = round(max(0.0, min(1.0, years / minimum)), 6)
        base.notes = (
            f"Evidence indicates {years:.1f} years vs a stated minimum of {minimum:g}; "
            "tenure is derived only from dated roles in the experience section."
        )
        return base

    if maximum is not None and years > maximum + 2:
        base.status = ExperienceStatus.PARTIAL_MATCH
        base.score = 0.75
        base.notes = (
            f"Evidence indicates {years:.1f} years vs a stated range of {minimum:g}-{maximum:g}; "
            "the posting may target a different seniority level."
        )
        return base

    base.status = ExperienceStatus.CLEAR_MATCH
    base.score = 1.0
    requirement = f"{minimum:g}+ years" if maximum is None else f"{minimum:g}-{maximum:g} years"
    base.notes = f"Evidence indicates {years:.1f} years against a stated requirement of {requirement}."
    return base

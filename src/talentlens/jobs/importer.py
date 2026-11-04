"""Job import and normalisation.

Supports manual payloads, JSON and CSV, and unstructured text postings. Every
imported job carries validation warnings; rejected records are reported rather
than silently dropped.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from talentlens.config import get_config
from talentlens.errors import JobValidationError
from talentlens.jobs.requirements import (
    extract_experience_range,
    extract_responsibilities,
    infer_education,
    infer_seniority,
    infer_work_arrangement,
    split_requirements,
)
from talentlens.log import get_logger
from talentlens.schemas import (
    JobMetadata,
    JobPosting,
    JobSkill,
    SectionName,
    SkillMention,
    SkillRequirement,
)
from talentlens.skills.extractor import extract_from_phrases
from talentlens.skills.taxonomy import SkillTaxonomy, get_taxonomy
from talentlens.utils.ids import job_id_for, normalise_id
from talentlens.utils.text import content_sha256

logger = get_logger("jobs.importer")

_LIST_SEPARATORS = ("|", ";")


@dataclass
class JobImportReport:
    imported: list[JobPosting] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    duplicates: list[dict[str, str]] = field(default_factory=list)
    warnings: dict[str, int] = field(default_factory=dict)

    @property
    def summary(self) -> dict[str, Any]:
        required = sum(len(job.required_skills) for job in self.imported)
        preferred = sum(len(job.preferred_skills) for job in self.imported)
        return {
            "imported": len(self.imported),
            "rejected": len(self.rejected),
            "duplicates": len(self.duplicates),
            "required_skills_total": required,
            "preferred_skills_total": preferred,
            "jobs_without_required_skills": sum(1 for job in self.imported if not job.required_skills),
            "top_warnings": dict(sorted(self.warnings.items(), key=lambda item: -item[1])[:8]),
        }


class JobImporter:
    def __init__(self, taxonomy: SkillTaxonomy | None = None) -> None:
        self.taxonomy = taxonomy or get_taxonomy()
        self.report = JobImportReport()
        self._by_id: dict[str, JobPosting] = {}
        self._by_hash: dict[str, str] = {}
        self.max_skills = int(get_config().get("matching.max_skills_per_job", 40))

    # ------------------------------------------------------------------ sources
    def import_json(self, source: str | Path | list[dict] | dict, *, source_name: str | None = None) -> list[JobPosting]:
        payload: Any
        name = source_name
        if isinstance(source, (str, Path)):
            path = Path(source)
            payload = json.loads(path.read_text(encoding="utf-8"))
            name = name or path.name
        else:
            payload = source
        records = payload.get("jobs", payload) if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            raise JobValidationError("JSON job import must contain a list of job records")
        return self._import_records(records, source_format="json", source_name=name)

    def import_csv(self, source: str | Path, *, source_name: str | None = None) -> list[JobPosting]:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(path)
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                records.append(dict(row))
        return self._import_records(records, source_format="csv", source_name=source_name or path.name)

    def import_manual(self, payload: dict[str, Any]) -> JobPosting:
        jobs = self._import_records([payload], source_format="manual", source_name="manual")
        if not jobs:
            reason = self.report.rejected[-1]["reason"] if self.report.rejected else "unknown validation error"
            raise JobValidationError(f"Job could not be imported: {reason}")
        return jobs[0]

    def import_text(
        self,
        text: str,
        *,
        title: str,
        company: str = "Unknown company",
        **overrides: Any,
    ) -> JobPosting:
        payload = {"title": title, "company": company, "raw_text": text, **overrides}
        return self.import_manual(payload)

    # ------------------------------------------------------------------ core
    def _import_records(self, records: list[Any], *, source_format: str, source_name: str | None) -> list[JobPosting]:
        imported: list[JobPosting] = []
        for index, record in enumerate(records):
            try:
                job = self.normalize(record, source_format=source_format, source_name=source_name)
            except (JobValidationError, ValidationError, ValueError) as exc:
                reason = getattr(exc, "message", str(exc))
                self.report.rejected.append(
                    {"index": str(index), "title": str(record.get("title", ""))[:80], "reason": reason}
                )
                logger.warning("Rejected job record %d: %s", index, reason)
                continue

            existing = self._by_hash.get(job.metadata.sha256)
            if existing:
                self.report.duplicates.append(
                    {"job_id": job.job_id, "duplicate_of": existing, "reason": "identical content hash"}
                )
                continue
            if job.job_id in self._by_id:
                self.report.rejected.append(
                    {"index": str(index), "title": job.title, "reason": f"duplicate job_id '{job.job_id}' with different content"}
                )
                continue

            self._by_id[job.job_id] = job
            self._by_hash[job.metadata.sha256] = job.job_id
            imported.append(job)
            self.report.imported.append(job)
            for warning in job.metadata.validation_warnings:
                self.report.warnings[warning] = self.report.warnings.get(warning, 0) + 1
        return imported

    def normalize(self, raw: dict[str, Any], *, source_format: str, source_name: str | None = None) -> JobPosting:
        if not isinstance(raw, dict):
            raise JobValidationError("Job record must be an object")
        warnings: list[str] = []

        title = str(raw.get("title") or "").strip()
        if not title:
            raise JobValidationError("Job title is required")
        if len(title) > int(get_config().get("jobs.max_title_chars", 160)):
            raise JobValidationError("Job title is too long")

        company = str(raw.get("company") or "").strip()
        if not company:
            company = "Unknown company"
            warnings.append("Missing company name")

        raw_text = str(raw.get("raw_text") or "").strip()
        summary = str(raw.get("summary") or raw.get("description") or "").strip()
        responsibilities = _as_list(raw.get("responsibilities"))
        if not responsibilities and raw_text:
            responsibilities = extract_responsibilities(raw_text)

        requirements = split_requirements(raw_text or summary)
        if not summary and not responsibilities and not raw_text:
            summary = title
            warnings.append("Job has no description text")

        description = "\n".join(
            part for part in [summary, *responsibilities, raw_text if raw_text and raw_text != summary else ""] if part
        ).strip()
        min_chars = int(get_config().get("jobs.min_description_chars", 60))
        if len(description) < min_chars:
            warnings.append("Job description is unusually short")

        required_phrases = _as_list(raw.get("required_skills"))
        preferred_phrases = _as_list(raw.get("preferred_skills"))
        required_skills: list[JobSkill] = []
        preferred_skills: list[JobSkill] = []

        if required_phrases or preferred_phrases:
            required_skills = self._skills_from_phrases(required_phrases, SkillRequirement.REQUIRED)
            preferred_skills = self._skills_from_phrases(preferred_phrases, SkillRequirement.PREFERRED)
        else:
            # Unstructured posting: required only from explicit requirement language;
            # skills seen only in descriptive prose are recorded as preferred.
            required_skills = self._skills_from_statements(requirements.required, SkillRequirement.REQUIRED)
            preferred_skills = self._skills_from_statements(requirements.preferred, SkillRequirement.PREFERRED)
            narrative_skills = self._skills_from_statements(
                [*requirements.neutral, description], SkillRequirement.PREFERRED, method="job_requirement"
            )
            if narrative_skills:
                preferred_skills = self._merge_skills(preferred_skills, narrative_skills)
                warnings.append("Skills mentioned only in descriptive text recorded as preferred")
            if not required_skills and not preferred_skills:
                warnings.append("No skills could be extracted from this posting")

        required_skills, preferred_skills, conflicts = _dedupe_across_requirements(
            required_skills, preferred_skills
        )
        if conflicts:
            warnings.append(f"{len(conflicts)} skill(s) appeared as both required and preferred; kept as required")
        required_skills = required_skills[: self.max_skills]
        preferred_skills = preferred_skills[: self.max_skills]

        if not required_skills:
            warnings.append("No required skills were identified")

        min_years = _as_float(raw.get("min_years_experience"))
        max_years = _as_float(raw.get("max_years_experience"))
        if min_years is None and max_years is None:
            parsed_min, parsed_max, evidence = extract_experience_range(raw_text or description)
            min_years, max_years = parsed_min, parsed_max
            if evidence:
                warnings.append(f"Experience requirement inferred from text: '{evidence}'")
        if max_years is not None and min_years is not None and max_years < min_years:
            warnings.append("Maximum experience was lower than minimum; maximum discarded")
            max_years = None

        seniority = raw.get("seniority")
        seniority = str(seniority).strip().lower() if seniority else None
        if not seniority:
            inferred = infer_seniority(title, description)
            if inferred:
                seniority = inferred
                warnings.append(f"Seniority inferred from text: {inferred}")

        work_arrangement = str(raw.get("work_arrangement") or "").strip().lower()
        if work_arrangement not in {"remote", "hybrid", "onsite", "unknown"}:
            work_arrangement = infer_work_arrangement(f"{title} {description}")
            if work_arrangement == "unknown":
                warnings.append("Work arrangement could not be determined")

        education = raw.get("education_level")
        education = str(education).strip() if education else infer_education(description)

        posted_date = _parse_date(raw.get("posted_date"))
        if raw.get("posted_date") and posted_date is None:
            warnings.append("Posted date could not be parsed")

        source = str(raw.get("source") or source_name or "") or None
        sha = content_sha256(title.lower(), company.lower(), description)
        job_id = _resolve_job_id(raw.get("id"), title, company, description)
        if raw.get("id") and job_id != str(raw.get("id")).strip():
            warnings.append("Provided job id contained unsupported characters and was normalised")

        try:
            return JobPosting(
                job_id=job_id,
                title=title,
                company=company,
                description=description,
                responsibilities=responsibilities,
                required_skills=required_skills,
                preferred_skills=preferred_skills,
                min_years_experience=min_years,
                max_years_experience=max_years,
                seniority=seniority,
                education_level=education,
                certifications=_as_list(raw.get("certifications")),
                location=str(raw["location"]).strip() if raw.get("location") else None,
                work_arrangement=work_arrangement,  # type: ignore[arg-type]
                employment_type=str(raw["employment_type"]).strip() if raw.get("employment_type") else None,
                salary_range=str(raw["salary_range"]).strip() if raw.get("salary_range") else None,
                source=source,
                posted_date=posted_date,
                metadata=JobMetadata(
                    source_format=source_format,  # type: ignore[arg-type]
                    source_name=source_name,
                    validation_warnings=_dedupe(warnings),
                    sha256=sha,
                ),
            )
        except ValidationError as exc:
            raise JobValidationError(f"Job schema validation failed: {exc.errors()[0].get('msg', 'invalid')}") from exc

    # ------------------------------------------------------------------ skills
    def _skills_from_phrases(self, phrases: list[str], requirement: SkillRequirement) -> list[JobSkill]:
        skills: list[JobSkill] = []
        for phrase in phrases:
            direct = self.taxonomy.resolve(phrase)
            if direct is not None:
                skills.append(
                    JobSkill(
                        canonical=direct.canonical,
                        category=direct.category,
                        original_text=phrase,
                        requirement=requirement,
                        evidence=phrase,
                        confidence=0.99,
                    )
                )
                continue
            mentions = extract_from_phrases([phrase], section=SectionName.SKILLS, taxonomy=self.taxonomy)
            for mention in mentions:
                skills.append(_mention_to_job_skill(mention, phrase, requirement))
        return _dedupe_job_skills(skills)

    def _skills_from_statements(
        self,
        statements: list[str],
        requirement: SkillRequirement,
        *,
        method: str = "job_requirement",
    ) -> list[JobSkill]:
        skills: list[JobSkill] = []
        for statement in statements:
            mentions = extract_from_phrases([statement], section=SectionName.SKILLS, taxonomy=self.taxonomy)
            for mention in mentions:
                skill = _mention_to_job_skill(mention, statement, requirement)
                skills.append(skill)
        return _dedupe_job_skills(skills)

    @staticmethod
    def _merge_skills(existing: list[JobSkill], new: list[JobSkill]) -> list[JobSkill]:
        return _dedupe_job_skills([*existing, *new])


def _mention_to_job_skill(mention: SkillMention, statement: str, requirement: SkillRequirement) -> JobSkill:
    return JobSkill(
        canonical=mention.canonical,
        category=mention.category,
        original_text=mention.original_text,
        requirement=requirement,
        evidence=statement[:400],
        confidence=mention.confidence,
    )


def _dedupe_job_skills(skills: list[JobSkill]) -> list[JobSkill]:
    seen: dict[str, JobSkill] = {}
    for skill in skills:
        current = seen.get(skill.canonical)
        if current is None or skill.confidence > current.confidence:
            seen[skill.canonical] = skill
    return list(seen.values())


def _dedupe_across_requirements(
    required: list[JobSkill], preferred: list[JobSkill]
) -> tuple[list[JobSkill], list[JobSkill], list[str]]:
    required_names = {skill.canonical for skill in required}
    conflicts = [skill.canonical for skill in preferred if skill.canonical in required_names]
    preferred = [skill for skill in preferred if skill.canonical not in required_names]
    return required, preferred, conflicts


def _resolve_job_id(provided: Any, title: str, company: str, description: str) -> str:
    if provided:
        try:
            return normalise_id(str(provided))
        except ValueError:
            pass
    return job_id_for(title, company, description)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    for separator in _LIST_SEPARATORS:
        if separator in text:
            return [part.strip() for part in text.split(separator) if part.strip()]
    return [text]


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def import_jobs_json(path: str | Path, *, taxonomy: SkillTaxonomy | None = None) -> tuple[list[JobPosting], JobImportReport]:
    importer = JobImporter(taxonomy=taxonomy)
    jobs = importer.import_json(path)
    return jobs, importer.report


def import_jobs_csv(path: str | Path, *, taxonomy: SkillTaxonomy | None = None) -> tuple[list[JobPosting], JobImportReport]:
    importer = JobImporter(taxonomy=taxonomy)
    jobs = importer.import_csv(path)
    return jobs, importer.report

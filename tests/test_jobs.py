from __future__ import annotations

import pytest

from talentlens.errors import JobValidationError
from talentlens.jobs.importer import JobImporter
from talentlens.jobs.requirements import (
    extract_experience_range,
    infer_seniority,
    infer_work_arrangement,
    split_requirements,
)


def test_json_import_has_required_and_preferred_separated(job_documents):
    jobs = job_documents
    assert len(jobs) == 23
    ml_job = next(job for job in jobs if job.job_id == "j01")
    required = set(ml_job.required_skill_names)
    preferred = set(ml_job.preferred_skill_names)
    assert {"Python", "PyTorch", "Natural Language Processing", "Transformers", "Docker"} <= required
    assert {"AWS", "MLflow", "FAISS"} <= preferred
    assert required.isdisjoint(preferred)


def test_experience_seniority_and_arrangement_are_preserved(job_documents):
    job = next(item for item in job_documents if item.job_id == "j01")
    assert job.min_years_experience == 3
    assert job.max_years_experience == 6
    assert job.seniority == "mid-senior"
    assert job.work_arrangement == "remote"


def test_unstructured_posting_classifies_only_explicit_requirements(job_documents):
    job = next(item for item in job_documents if item.job_id == "j23")
    required = set(job.required_skill_names)
    preferred = set(job.preferred_skill_names)
    assert {"Natural Language Processing", "Transformers"} <= required
    assert {"AWS", "FAISS"} <= preferred
    assert required.isdisjoint(preferred)
    assert any("preferred" in warning.lower() for warning in job.metadata.validation_warnings)


def test_csv_and_json_imports_agree(jobs_json, jobs_csv):
    json_jobs = JobImporter().import_json(jobs_json)
    csv_jobs = JobImporter().import_csv(jobs_csv)
    assert len(json_jobs) == len(csv_jobs) == 23
    json_required = sum(len(job.required_skills) for job in json_jobs)
    csv_required = sum(len(job.required_skills) for job in csv_jobs)
    assert json_required == csv_required
    assert {job.job_id for job in json_jobs} == {job.job_id for job in csv_jobs}


def test_reimport_into_same_importer_is_deduplicated(jobs_json):
    importer = JobImporter()
    first = importer.import_json(jobs_json)
    second = importer.import_json(jobs_json)
    assert len(first) == 23
    assert second == []
    assert len(importer.report.duplicates) == 23
    assert len(importer.report.imported) == 23


def test_required_skill_wins_over_preferred_duplicate():
    importer = JobImporter()
    job = importer.import_manual(
        {
            "title": "Backend Engineer",
            "company": "Example",
            "description": "Build services in Python.",
            "required_skills": ["Python", "PostgreSQL"],
            "preferred_skills": ["Python", "Docker"],
        }
    )
    assert "Python" in job.required_skill_names
    assert "Python" not in job.preferred_skill_names
    assert any("both required and preferred" in warning for warning in job.metadata.validation_warnings)


def test_experience_range_parsing():
    assert extract_experience_range("You have 3-5 years of experience.")[:2] == (3.0, 5.0)
    assert extract_experience_range("At least 4 years of experience required.")[:2] == (4.0, None)
    assert extract_experience_range("5+ years in backend engineering.")[:2] == (5.0, None)
    assert extract_experience_range("No experience necessary.") == (None, None, None)


def test_seniority_and_arrangement_inference():
    assert infer_seniority("Junior Data Analyst") == "junior"
    assert infer_seniority("Principal ML Engineer") == "principal"
    assert infer_seniority("Data Scientist") is None
    assert infer_work_arrangement("This is a hybrid role") == "hybrid"
    assert infer_work_arrangement("Fully remote team") == "remote"
    assert infer_work_arrangement("On-site in Berlin") == "onsite"


def test_requirement_section_split():
    text = "Requirements:\n- Strong Python\n- SQL\n\nNice to have:\n- AWS\n- Docker"
    split = split_requirements(text)
    assert any("Python" in line for line in split.required)
    assert any("AWS" in line for line in split.preferred)
    assert split.has_explicit_sections


def test_invalid_job_is_rejected_not_silently_dropped():
    importer = JobImporter()
    with pytest.raises(JobValidationError):
        importer.import_manual({"title": "", "company": "Example", "description": "x"})
    assert importer.report.rejected


def test_missing_company_is_flagged():
    job = JobImporter().import_manual(
        {"title": "Data Analyst", "description": "Analyse data with SQL and Tableau.", "required_skills": ["SQL"]}
    )
    assert job.company == "Unknown company"
    assert any("company" in warning.lower() for warning in job.metadata.validation_warnings)


def test_job_ids_are_stable_across_imports():
    payload = {"title": "Data Engineer", "company": "Acme", "description": "Build pipelines with Python and Spark."}
    first = JobImporter().import_manual(dict(payload))
    second = JobImporter().import_manual(dict(payload))
    assert first.job_id == second.job_id
    assert first.metadata.sha256 == second.metadata.sha256

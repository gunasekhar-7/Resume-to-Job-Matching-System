"""Shared test fixtures.

Tests use the synthetic corpus committed under ``data/sample``. Model-heavy tests
are marked ``model`` and are excluded by default CI to keep the unit suite fast.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for entry in (str(SRC), str(TESTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from talentlens.config import get_config  # noqa: E402
from talentlens.parsing.resume_parser import parse_file  # noqa: E402
from talentlens.skills.taxonomy import get_taxonomy  # noqa: E402


@pytest.fixture(scope="session")
def config():
    return get_config()


@pytest.fixture(scope="session")
def taxonomy():
    return get_taxonomy()


@pytest.fixture(scope="session")
def sample_dir(config) -> Path:
    return config.resolve(config.get("paths.sample_dir", "data/sample"))


@pytest.fixture(scope="session")
def resume_dir(sample_dir) -> Path:
    return sample_dir / "resumes"


@pytest.fixture(scope="session")
def fixture_dir(sample_dir) -> Path:
    return sample_dir / "fixtures"


@pytest.fixture(scope="session")
def jobs_json(sample_dir) -> Path:
    return sample_dir / "jobs" / "jobs.json"


@pytest.fixture(scope="session")
def jobs_csv(sample_dir) -> Path:
    return sample_dir / "jobs" / "jobs.csv"


@pytest.fixture(scope="session")
def parsed_r01(resume_dir):
    return parse_file(resume_dir / "r01_priya_single.pdf", resume_id="r01")


@pytest.fixture(scope="session")
def parsed_r04(resume_dir):
    return parse_file(resume_dir / "r04_sofia_two_column.pdf", resume_id="r04")


@pytest.fixture(scope="session")
def parsed_r09(resume_dir):
    return parse_file(resume_dir / "r09_thomas_table_skills.pdf", resume_id="r09")


@pytest.fixture(scope="session")
def corpus_documents(config):
    from talentlens.ingestion.dataset import read_corpus_jsonl

    path = config.resolve("data/processed/resumes.jsonl")
    if not path.exists():
        pytest.skip("Processed corpus missing; run scripts/ingest_resumes.py")
    return read_corpus_jsonl(path)


@pytest.fixture(scope="session")
def job_documents(config):
    from talentlens.jobs.importer import JobImporter

    jobs_path = config.resolve("data/sample/jobs/jobs.json")
    return JobImporter().import_json(jobs_path)

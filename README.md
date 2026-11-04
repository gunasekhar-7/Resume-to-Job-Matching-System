# TalentLens

**Explainable AI-powered resume-to-job matching and recommendation platform.**

TalentLens reads a resume, extracts structured evidence, and ranks job postings by professional
relevance. Every recommendation shows *why* it matches: the skills evidenced, the skills not
evidenced (kept separate from required vs preferred), the relevant resume sentences, and the
experience alignment. It is a decision-support tool for candidates - **not** an automated hiring
decision system, and the score is never a probability of being hired.

> **Status:** Phase 1 (data engineering and document intelligence) is complete and verified.
> Phases 2-4 are in progress. See [`PROJECT_STATUS.md`](PROJECT_STATUS.md).

## What works today

- Resume ingestion for PDF, DOCX and TXT with size/type/magic-byte validation and DOCX ZIP-bomb
  limits. Files are processed in memory; raw uploads are never written to disk.
- Column-aware PDF extraction (two-column resumes keep their reading order) and DOCX body-order
  extraction including tables.
- Cleaning, running header/footer removal, and section detection with character offsets.
- A 214-skill taxonomy with alias normalisation, 15 categories, and evidence-preserving
  extraction (canonical skill, original phrase, section, sentence, offsets).
- Job ingestion from JSON, CSV, manual payloads or unstructured text, with required and
  preferred requirements kept separate.
- Structured PII detection (email, phone, profile URLs) with values excluded from metadata.
- A 140-pair manually labelled relevance set with documented guidelines and grouped splits.
- Reproducible data-quality reports for both corpora.

## Quickstart

```bash
python -m pip install -r requirements.txt

# 1. Build the synthetic corpus (fictional people, reserved example domains)
python scripts/build_sample_data.py --force

# 2. Parse resumes -> data/processed/resumes.jsonl + reports/PHASE1_DATA_QUALITY.md
python scripts/ingest_resumes.py

# 3. Import jobs -> data/processed/jobs.jsonl + reports/PHASE1_JOBS_QUALITY.md
python scripts/ingest_jobs.py

# 4. Tests
python -m pytest tests -q
```

Python 3.10+ is supported; the verified environment uses 3.11.7.

## How it is organised

```text
configs/        YAML configuration + skill taxonomy
data/           synthetic samples, annotations, processed JSONL
src/talentlens/ ingestion, parsing, skills, jobs, embeddings, retrieval, matching,
                evaluation, storage, monitoring, utils
api/            FastAPI application (Phase 4)
frontend/       Streamlit Candidate Mode (Phase 4)
scripts/        reproducible build/ingest/benchmark entry points
tests/          unit and integration tests
docs/           requirements, architecture, methodology, privacy, evaluation
reports/        phase completion and evaluation reports
```

## Documentation

- [Requirements](docs/REQUIREMENTS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Technical decisions](docs/TECHNICAL_DECISIONS.md)
- [Dataset card](docs/DATASET_CARD.md)
- [Resume parsing](docs/RESUME_PARSING.md)
- [Skill extraction](docs/SKILL_EXTRACTION.md)
- [Annotation guidelines](docs/ANNOTATION_GUIDELINES.md)
- [Known limitations](KNOWN_LIMITATIONS.md)
- [Phase 1 completion report](reports/PHASE_1_COMPLETION_REPORT.md)

## Privacy

All sample resumes are synthetic; every person, company, email and phone number is fictional.
Do not commit real resumes. `.gitignore` excludes private data, uploads, model caches, indexes and
databases. Uploaded documents are treated as untrusted input and are never used as instructions.

## Licence

No licence file is included yet. ESCO/O*NET are referenced conceptually; no data from either is
redistributed. Review those terms before redistributing derived taxonomies.

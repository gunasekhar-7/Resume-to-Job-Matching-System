# TalentLens

**Explainable AI-powered resume-to-job matching and recommendation platform.**

TalentLens reads a resume, extracts structured evidence, and ranks job postings by professional
relevance. Every recommendation shows *why* it matches: the skills evidenced, the skills not
evidenced (kept separate from required vs preferred), the relevant resume sentences, and the
experience alignment. It is a decision-support tool for candidates - **not** an automated hiring
decision system, and the score is never a probability of being hired.

> **Status:** Phases 1-2 (data engineering, parsing and the retrieval/matching engine) are complete
> and verified. Phase 3 (explainability, evaluation, responsible AI) is next. See
> [`PROJECT_STATUS.md`](PROJECT_STATUS.md) for measured results.

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
- TF-IDF, semantic and hybrid job retrieval over an exact FAISS index with stable job-ID mapping
  and versioned artifacts.
- Required/preferred skill coverage, evidence records and independent experience alignment.
- Transparent score contributions and optional cross-encoder reranking (off by default).

## Quickstart

```bash
python -m pip install -r requirements.txt

# 1. Build the synthetic corpus (fictional people, reserved example domains)
python scripts/build_sample_data.py --force

# 2. Parse resumes -> data/processed/resumes.jsonl + reports/PHASE1_DATA_QUALITY.md
python scripts/ingest_resumes.py

# 3. Import jobs -> data/processed/jobs.jsonl + reports/PHASE1_JOBS_QUALITY.md
python scripts/ingest_jobs.py

# 4. Build the matching index (downloads/caches the embedding model on first run)
python scripts/build_index.py

# 5. Tests
python -m pytest tests -q

# Optional: validation-only model and reranker benchmarks
python scripts/benchmark_embeddings.py
python scripts/benchmark_reranker.py
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
- [Matching methodology](docs/MATCHING_METHODOLOGY.md)
- [Annotation guidelines](docs/ANNOTATION_GUIDELINES.md)
- [Known limitations](KNOWN_LIMITATIONS.md)
- [Phase 1 completion report](reports/PHASE_1_COMPLETION_REPORT.md)
- [Phase 2 completion report](reports/PHASE_2_COMPLETION_REPORT.md)

## Privacy

All sample resumes are synthetic; every person, company, email and phone number is fictional.
Do not commit real resumes. `.gitignore` excludes private data, uploads, model caches, indexes and
databases. Uploaded documents are treated as untrusted input and are never used as instructions.

## Licence

No licence file is included yet. ESCO/O*NET are referenced conceptually; no data from either is
redistributed. Review those terms before redistributing derived taxonomies.

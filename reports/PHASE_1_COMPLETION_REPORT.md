# Phase 1 Completion Report

**Project:** TalentLens
**Phase:** 1 - Foundation, data engineering and document intelligence
**Date:** 2026-11-04
**Status:** Complete

## 1. Implemented functionality

- Repository foundation: `src/talentlens` package, YAML configuration with environment
  overrides, typed Pydantic schemas, typed domain errors, request-correlated logging, text/ID/
  timing utilities, pytest and ruff configuration.
- Document ingestion: extension allow-list, 10 MB cap, magic-byte validation, DOCX ZIP member
  and uncompressed-size limits, content hashing, no temp files.
- PDF parsing via PyMuPDF with **column-aware reading order** for two-column resumes; DOCX
  parsing in body order including tables; TXT support.
- Cleaning: unicode/ligature normalisation, bullet normalisation, repeated header/footer
  removal, running-footer removal, duplicate-line collapse.
- Section detection for summary, skills, experience, projects, education, certifications,
  publications, additional information, with character offsets. DOCX heading styles supported.
- Skill taxonomy + extraction: 214 canonical skills, 15 categories, alias normalisation,
  case-sensitive matching for ambiguous skills, section/evidence/offset preservation.
- Job ingestion: JSON, CSV, manual and unstructured text; required/preferred separation;
  experience-range parsing; seniority/work-arrangement inference with warnings.
- Privacy foundation: structured PII detection, values excluded from metadata, synthetic
  samples, private-data ignores.
- Evaluation foundation: 140 manually labelled pairs across 14 resumes and 22 jobs, grouped
  splits, annotation guidelines and template.
- Quality reporting: `reports/PHASE1_DATA_QUALITY.md`, `reports/PHASE1_JOBS_QUALITY.md`.

## 2. Files created or modified

Key paths (full tree in `PROJECT_STATUS.md`):

| Area | Files |
| --- | --- |
| Configuration | `configs/default.yaml`, `configs/skills_taxonomy.yaml`, `.env.example`, `pyproject.toml`, `requirements*.txt` |
| Schemas/utilities | `src/talentlens/schemas.py`, `config.py`, `errors.py`, `log.py`, `utils/*` |
| Ingestion | `src/talentlens/ingestion/loader.py`, `dataset.py` |
| Parsing | `src/talentlens/parsing/{pdf_parser,docx_parser,sections,cleaning,pii,ocr,resume_parser}.py` |
| Skills | `src/talentlens/skills/{taxonomy,normalizer,extractor}.py` |
| Jobs | `src/talentlens/jobs/{requirements,importer}.py` |
| Scripts | `scripts/build_sample_data.py`, `scripts/ingest_resumes.py`, `scripts/ingest_jobs.py` |
| Data | `data/sample/**`, `data/annotations/**`, `data/processed/*.jsonl` |
| Tests | `tests/conftest.py`, `tests/test_text_utils.py`, `test_parsing.py`, `test_skills.py`, `test_jobs.py` |
| Docs | `docs/REQUIREMENTS.md`, `ARCHITECTURE.md`, `TECHNICAL_DECISIONS.md`, `DATASET_CARD.md`, `RESUME_PARSING.md`, `SKILL_EXTRACTION.md`, `ANNOTATION_GUIDELINES.md` |

## 3. Data schemas

Implemented in `src/talentlens/schemas.py` with `extra="forbid"`:

- `ResumeDocument` (id, full text, sections, section spans, skills, metadata, schema version).
- `SectionSpan` (section, heading, text, start/end offsets, order, page).
- `SkillMention` (original text, canonical, category, section, evidence, offsets, method,
  status, confidence).
- `ResumeMetadata` (format, filename, SHA-256, pages, status, warnings, OCR, char count,
  quality, parser version, PII entity types).
- `JobPosting` + `JobSkill` + `JobMetadata` (required/preferred split, experience range,
  seniority, arrangement, provenance, validation warnings).

JSON examples are generated in `data/processed/resumes.jsonl` and `data/processed/jobs.jsonl`.

## 4. Dataset sources

- **Synthetic resumes and jobs**, authored for this project. All identities are fictional.
- ESCO and O*NET reviewed as conceptual references for categories; no data redistributed.
- Kaggle resume datasets investigated and deliberately not used (provenance/licensing/consent;
  category labels are not relevance labels).
- Details and licences: `docs/DATASET_CARD.md`.

## 5. Parsing quality observations

Command: `python scripts/ingest_resumes.py`

| Metric | Result |
| --- | --- |
| Files attempted / parsed / failed | 26 / 26 / 0 |
| Unique resumes after dedupe | 14 |
| Format-variant duplicates removed | 12 |
| Status distribution | success 14, partial 0, failed 0 |
| Average extraction quality (heuristic) | 0.961 |
| Section coverage | summary, skills, experience, education, projects 100%; certifications 42.9%; publications 21.4% |

Observations:

- Two-column PDFs (r04, r14) initially interleaved. Block-coordinate gutter detection fixed the
  reading order. Two bugs were found and covered by tests: a phantom gutter caused by the running
  footer, and returning the gutter width instead of the right-column edge.
- The DOCX table variant of the two-column resume yields a different reading order than the PDF
  (cells are emitted left then right); sections still resolve correctly because headings are
  styled.
- Table-based skills (r09) are extracted correctly; the table rows are emitted as separate lines.
- Image-only and empty PDFs produced only a 52-character footer. They are now detected as
  low-text and marked `failed` with warnings instead of being accepted.
- Corrupt PDF, empty PDF, scanned PDF and `.exe` all fail with typed, visible errors.

## 6. Skill extraction results

- Taxonomy: 214 canonical skills, 15 categories, 18 case-sensitive single-token skills.
- Average distinct canonical skills per resume: 16.0.
- All 26 files produced skills where expected; no empty extractions on usable documents.
- Unit tests cover alias normalisation (JS→JavaScript, sklearn→Scikit-Learn), case-sensitive
  false positives (`go to market`, `R and D`), section attribution, evidence offsets and related
  credit.
- Mention ≠ proficiency is enforced in documentation and schema; no proficiency score is stored.

## 7. Job processing results

Command: `python scripts/ingest_jobs.py`

| Metric | JSON | CSV |
| --- | --- | --- |
| Imported | 23 | 23 |
| Rejected | 0 | 0 |
| Required skills | 108 | 108 |
| Preferred skills | 94 | 94 |
| Jobs without required skills | 0 | 0 |

- Required and preferred canonical sets are disjoint per job (conflicts resolve to required with
  a warning).
- The unstructured posting (`j23`) yields required NLP/Transformers (explicit "essential") and
  preferred AWS/FAISS ("a plus") plus narrative skills recorded as preferred.
- Re-importing the same JSON into the same importer prevented 23 duplicates.
- Every inference (seniority, arrangement, experience range, narrative skills) is recorded as a
  validation warning.

## 8. Evaluation dataset

- 140 pairs: 24 strongly relevant, 50 partially relevant, 66 not relevant.
- 14 resumes × 10 judged postings, covering all 22 structured jobs.
- Grouped split by resume: dev r01-r07 (70 pairs), validation r08-r10 (30), test r11-r14 (40).
- Every pair has a rationale; guidelines and template are committed.
- **No inter-annotator agreement** is claimed (single annotator).

## 9. Known limitations

See `KNOWN_LIMITATIONS.md`; Phase 1-specific highlights:

- Synthetic corpus, single annotator, English only, one-page resumes.
- Two-column detection limited to two columns and heuristic geometry.
- OCR disabled by default; scanned documents fail visibly.
- Skill matching is phrase-based and does not model negation or proficiency.

## 10. Test results

| Check | Command | Result |
| --- | --- | --- |
| Unit tests | `python -m pytest tests -q` | **60 passed** |
| Lint | `python -m ruff check src tests scripts` | **clean** |
| Corpus ingest | `python scripts/ingest_resumes.py` | 26/26 parsed, 0 failed |
| Job ingest | `python scripts/ingest_jobs.py` | 23/23 imported, 0 rejected |
| Fixtures | included in ingest script | corrupt/empty/scanned/exe handled as designed |

## 11. Acceptance criteria status

| Criterion | Status | Evidence |
| --- | --- | --- |
| PDF and DOCX ingestion | PASS | 26/26 files parsed |
| Text extracted and cleaned | PASS | quality 0.961; cleaning tests |
| Sections identified | PASS | 100% coverage for core sections |
| Skills extracted and normalised | PASS | 214-skill taxonomy; 16.0 skills/resume |
| Job descriptions structured | PASS | 23/23 JSON + CSV, 0 rejected |
| Required vs preferred distinguished | PASS | 108 / 94 disjoint |
| Source evidence preserved | PASS | offsets + evidence; offset tests |
| Invalid files handled gracefully | PASS | four fixtures produce typed outcomes |
| Dataset provenance documented | PASS | `docs/DATASET_CARD.md` |
| Sensitive information protected | PASS | in-memory uploads; PII types only; `.gitignore` |
| Critical tests pass | PASS | 60 passed |

## 12. Remaining tasks

- Phase 2: embeddings, FAISS, TF-IDF, hybrid scoring, experience matching, reranking, tests.
- Phase 3: explanations, skill-gap reporting, benchmark, error analysis, fairness.
- Phase 4: API, Streamlit, database, Docker, CI, observability, audit.

## 13. Phase 2 readiness

**Ready.** Phase 2 has stable `ResumeDocument` and `JobPosting` contracts, canonical skills with
section evidence, a clean 14-resume/23-job corpus, and a labelled evaluation set with grouped
splits. No Phase 1 component needs to be rebuilt. The main risk carried forward is that all
quality measurements are on synthetic documents.

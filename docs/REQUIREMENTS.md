# TalentLens - Product Requirements

**Version:** 1.0 (Phase 1 baseline)
**Last updated:** 2026-11-04

## 1. Product definition

TalentLens is an **explainable resume-to-job matching and recommendation platform**. It
reads a candidate's resume, extracts structured evidence, and returns ranked job
recommendations with a transparent score breakdown and evidence drawn from the resume and
posting.

### Operating modes

| Mode | Status | Description |
| --- | --- | --- |
| **Candidate Mode** | Primary MVP (Phase 1-4) | A candidate uploads a resume and receives ranked, explained job recommendations and a skill-gap report. |
| **Recruiter Mode** | Future extension (not implemented) | A recruiter submits a job description and receives ranked resumes. Explicitly out of scope until Candidate Mode meets its acceptance criteria. |

TalentLens is **not** an automated hiring decision system. It does not produce hiring
probabilities, make rejection decisions, or rank people by protected attributes. The output is
a **matching/relevance score** with evidence, intended to help a person decide what to read.

## 2. Users and journeys

### Candidate journey (MVP)

1. Upload a PDF or DOCX resume.
2. See parsing status, any warnings, extracted sections and normalised skills.
3. Browse ranked job recommendations with a score breakdown.
4. Open a job to see matched skills, missing evidence, relevant resume sentences, and
   experience alignment.
5. Review the skill-gap dashboard.
6. Delete the resume and its retained data.

### Recruiter journey (future)

Submit a job description, review ranked resumes with evidence, and make a human decision.
No automatic rejection.

## 3. Functional requirements

| ID | Requirement | Phase | Status |
| --- | --- | --- | --- |
| FR-01 | Ingest PDF, DOCX and plain-text resumes with size/type validation | 1 | Done |
| FR-02 | Extract multi-page text including two-column and table layouts | 1 | Done |
| FR-03 | Detect resume sections (summary, skills, experience, projects, education, certifications, publications, additional) | 1 | Done |
| FR-04 | Extract skills with canonical name, category, aliases, section, evidence and offsets | 1 | Done |
| FR-05 | Persist structured, validated resume records | 1 | Done (JSONL; DB in Phase 4) |
| FR-06 | Import job descriptions from manual input, JSON and CSV | 1 | Done |
| FR-07 | Separate required from preferred skills and preserve evidence | 1 | Done |
| FR-08 | Maintain a manually authored relevance-annotation set with documented guidelines | 1 | Done (140 pairs) |
| FR-09 | Detect and redact structured PII; exclude private documents from Git | 1 | Done |
| FR-10 | Provide a TF-IDF retrieval baseline and independent skill-overlap scoring | 2 | Done |
| FR-11 | Generate semantic embeddings for resumes, sections and jobs, with persisted metadata | 2 | Done |
| FR-12 | Provide FAISS retrieval with a stable job-ID mapping and index versioning | 2 | Done |
| FR-13 | Score matches with a configurable, normalised hybrid score | 2 | Done (experimental weights) |
| FR-14 | Compute experience/seniority alignment independently | 2 | Done |
| FR-15 | Support optional cross-encoder reranking | 2 | Done (disabled by default; negative validation result) |
| FR-16 | Explain every recommendation with traceable evidence and a score breakdown | 3 | Pending |
| FR-17 | Report skill gaps with explicit denominators; never claim a candidate lacks a skill | 3 | Pending |
| FR-18 | Evaluate ranking quality on held-out labelled pairs with standard IR metrics | 3 | Pending |
| FR-19 | Run counterfactual fairness tests on name/contact/identity changes | 3 | Pending |
| FR-20 | Serve the workflow through a documented FastAPI backend and Streamlit UI | 4 | Pending |
| FR-21 | Support resume deletion and retention-based purge | 4 | Pending |
| FR-22 | Provide Docker, CI, observability and deployment documentation | 4 | Pending |

## 4. Non-functional requirements

| Area | Requirement |
| --- | --- |
| **Performance** | CPU-only matching path. Target: parse + embed + rank 22 jobs in under 3 seconds after models are warm. Latency is measured, not assumed (Phase 3/4). |
| **Reproducibility** | Fixed seeds, persisted model/index identifiers and configuration versions; evaluation scripts re-runnable from the repo. |
| **Privacy** | Uploaded resumes are private. No external AI APIs are called on personal documents. Uploads are processed in memory; raw files are not persisted by default. Structured PII is detected and redactable. |
| **Security** | File-type and size validation, DOCX zip-bomb limits, no path traversal, no document content in logs, rate limiting, request IDs, structured errors. |
| **Explainability** | Every displayed match must cite resume evidence (phrase/section/sentence) and the job requirement it addresses. No explanation may be generated from the score alone. |
| **Fairness** | Protected attributes (name, gender, age, photo, caste, religion, marital status, college prestige) are excluded from scoring. Counterfactual invariance tests must pass. Demographic fairness cannot be established from this synthetic corpus and must not be claimed. |
| **Maintainability** | Layered modules, typed schemas, unit tests for critical logic, no duplicated matching logic in API/UI layers. |
| **Cost** | CPU inference with small sentence-transformer models; no GPU requirement for the default configuration. |
| **Availability** | Single-node deployment is acceptable for this project. Health/readiness endpoints and graceful degradation when a model or index is unavailable. |

## 5. Scope boundaries

In scope: Candidate Mode, evidence-based ranking, skill-gap analysis, evaluation, fairness
testing, containerised deployment, documentation.

Out of scope for v1: Recruiter Mode, automatic hiring decisions, live job-board scraping,
user accounts with billing, mobile apps, LLM-generated resume rewriting, OCR by default,
non-English documents, salary prediction.

## 6. Supported formats and limits

| Item | Value |
| --- | --- |
| Resume formats | PDF (text-based), DOCX, TXT (TXT is supported for testing and plain exports) |
| Maximum upload size | 10 MB |
| Maximum PDF pages processed | 20 |
| Maximum retained resume text | 120,000 characters |
| OCR | Optional, disabled by default; requires Tesseract and reports confidence |
| Job imports | Manual JSON payload, JSON file, CSV file, unstructured text |
| Languages | English only in v1 (documented limitation) |

## 7. Data schemas (authoritative models)

Defined in `src/talentlens/schemas.py`:

- `ResumeDocument`: `resume_id`, `full_text`, `sections`, `section_spans`, `skills`, `metadata`.
- `SectionSpan`: section enum, heading, text, character offsets, page.
- `SkillMention`: original text, canonical skill, category, section, evidence, offsets,
  extraction method, match status, confidence.
- `ResumeMetadata`: format, filename, SHA-256, page count, parsing status, warnings, OCR flags,
  character count, extraction quality, parser version, PII entity types (never values).
- `JobPosting`: id, title, company, description, responsibilities, required/preferred skills,
  experience range, seniority, education, certifications, location, work arrangement,
  employment type, source, posted date, metadata.
- `JobSkill`: canonical, category, original text, requirement type, evidence, confidence.
- Evaluation/annotation rows: `pair_id`, `resume_id`, `job_id`, `relevance` (0/1/2), rationale,
  annotator, source, date.

All models forbid unknown fields so that schema drift fails loudly.

## 8. Data acquisition strategy

Investigated public sources (details in `docs/DATASET_CARD.md`):

- Kaggle resume datasets: category-labelled, licensing/provenance often unclear; categories are
  **not** relevance labels. Not bundled.
- ESCO and O*NET: used as **conceptual references** for skill categories; no data files
  redistributed; licence terms must be reviewed before any redistribution.
- Job postings: synthetic postings authored for this project, with explicit required/preferred
  fields.

Consequence: v1 is validated on a synthetic corpus, and all results are reported as such.
A production deployment must re-validate on lawfully obtained, consented data.

## 9. Evaluation strategy

- 140 manually labelled resume-job pairs across 14 resumes and 22 postings.
- Relevance scale: 0 = not relevant, 1 = partially relevant, 2 = strongly relevant.
- Grouped splits by resume: dev (r01-r07), validation (r08-r10), test (r11-r14).
- Ranking metrics: Precision@K, Recall@K, NDCG@10, MRR, with explicit thresholds.
- Systems compared on the same protocol: TF-IDF, semantic retrieval, hybrid, hybrid + rerank.
- Weights tuned on validation only; test set used once after freezing.
- Skill extraction and parsing metrics reported separately.
- Latency/memory measured on the host described in the Phase 3 report.

## 10. Deployment constraints

- Containerised FastAPI + Streamlit + PostgreSQL via Docker Compose.
- CPU-only default; embedding model files and FAISS indexes are mounted/cached, not baked into
  the image where practical.
- No cloud deployment is claimed unless it is actually performed and evidenced.
- Model downloads must not be required for unit tests; real-model tests are marked and separate.

## 11. Acceptance criteria traceability

Phase 1 acceptance criteria are verified in `reports/PHASE_1_COMPLETION_REPORT.md` with commands
and measured output. Later phases maintain their own completion reports.

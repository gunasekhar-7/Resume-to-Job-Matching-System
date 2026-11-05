# TalentLens - Final Project Summary

TalentLens is an explainable resume-to-job matching platform built across four phases in
one repository. A candidate uploads a resume, sees the parsed sections and normalised
skills, receives ranked synthetic job recommendations, and can inspect the resume
sentences, matched requirements, missing evidence, experience alignment and score
contributions behind every result.

**The score is a relevance/matching estimate, never a probability of being hired.**
TalentLens is not an automated hiring system. Recruiter Mode is out of scope.

## Phase status

| Phase | Outcome | Evidence |
| --- | --- | --- |
| 1 - Foundation and document intelligence | Complete | PDF/DOCX/TXT parsing, sections, 214-skill taxonomy, job import, 140 labels, quality reports. |
| 2 - Retrieval and matching | Complete | TF-IDF, MiniLM embeddings, exact FAISS, skills/experience, hybrid scoring, optional reranker. |
| 3 - Explainability, evaluation, responsible AI | Complete | Sentence evidence, skill gaps, held-out metrics, weight freeze, 70 fairness checks, error analysis and docs. |
| 4 - Product engineering | Complete (single-node scope) | FastAPI, SQLAlchemy/PostgreSQL or SQLite, session-scoped deletion/retention, Streamlit, Docker Compose, CI, observability. |

## Measured results (held-out test, 40 judged pairs)

| System | NDCG@10 | NDCG@5 | P@5 | R@5 |
| --- | --- | --- | --- | --- |
| TF-IDF | 0.990624 | 0.980872 | 0.400000 | 1.000000 |
| Semantic (MiniLM) | 0.996218 | 0.985067 | 0.400000 | 1.000000 |
| Hybrid, frozen weights | **0.998711** | **1.000000** | 0.400000 | 1.000000 |
| Hybrid + cross-encoder | 0.934082 | 0.852214 | 0.350000 | 0.916667 |

- Weights were selected on validation only. All candidates tied at NDCG@10 = 1.0000, so
  the documented defaults were frozen and the test split was run once.
- Cross-encoder reranking was negative on validation and remained negative on test; it is
  off by default.
- 70/70 counterfactual checks passed across names, contacts, education institution and
  graduation year.
- 16 held-out error cases were documented from actual rankings; see
  [`reports/ERROR_ANALYSIS.md`](reports/ERROR_ANALYSIS.md).

The corpus is synthetic (14 resumes, 23 jobs), the labels have one annotator, and the
differences are small. No general superiority, production-quality or demographic-fairness
claim is made.

## Engineering highlights

- In-memory upload handling with magic-byte and DOCX ZIP-bomb validation; raw files are
  never persisted.
- Explicit FAISS job-ID map, versioned indexes and a NumPy exact fallback.
- Evidence-first explanations: no sentence above the similarity floor means an explicit
  "no evidence" note, not invented text.
- Session-scoped API storage with retention and cascade deletion; PII values are not
  logged or scored.
- Per-request IDs, structured errors, rate limiting, origin checks, security headers,
  `/health`, `/ready` and Prometheus `/metrics`.
- CI runs Ruff, compile checks and the full test suite without downloading models.

## Honest limitations

Synthetic-only data, 40 held-out pairs, single annotator, near-ceiling metrics, English
only, regex experience parsing, exact vector search untested at scale, per-process rate
limiting, no multi-user authentication, and no Docker or cloud deployment verified in this
environment. See [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md) for the maintained list.

## Where to look

- [`README.md`](README.md) - quickstart and map
- [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) - requirements and traceability
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - system design
- [`docs/API.md`](docs/API.md) - API contract
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) - local and Compose deployment
- [`docs/EXPLAINABILITY.md`](docs/EXPLAINABILITY.md), [`docs/EVALUATION_METHODOLOGY.md`](docs/EVALUATION_METHODOLOGY.md),
  [`docs/RESPONSIBLE_AI.md`](docs/RESPONSIBLE_AI.md), [`docs/PRIVACY_AND_SECURITY.md`](docs/PRIVACY_AND_SECURITY.md)
- [`reports/PHASE_3_COMPLETION_REPORT.md`](reports/PHASE_3_COMPLETION_REPORT.md),
  [`reports/PHASE_4_COMPLETION_REPORT.md`](reports/PHASE_4_COMPLETION_REPORT.md)

# TalentLens - Project Status

**Last updated:** 2026-11-05
**Current phase:** All four phases implemented; local verification complete. Docker Compose
is provided but not run in this environment.

## Phase overview

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Foundation, data engineering, document intelligence | **Complete** - verified |
| 2 | Semantic retrieval and matching engine | **Complete** - verified |
| 3 | Explainability, evaluation, responsible AI | **Complete** - verified |
| 4 | API, UI, storage, deployment, observability | **Complete - local scope**; Compose syntax validated, stack not started |

## Verified environment

| Component | Version |
| --- | --- |
| Python | 3.11.7 (Windows 11) |
| FastAPI | 0.142.2 |
| Pydantic | 2.13.5 |
| SQLAlchemy | 2.0.35 |
| scikit-learn | 1.9.1 |
| NumPy / SciPy / pandas | 2.4.6 / 1.17.1 / 3.0.6 |
| PyMuPDF | 2.0 |
| python-docx | 1.2.0 |
| spaCy | 3.8.18 (blank `en` pipeline) |
| sentence-transformers / torch | 6.1.0 / 2.14.1 |
| faiss-cpu | 1.15.1 |
| Streamlit | 1.65.0 |
| pytest | 9.1.1 |

## Current verification

| Check | Result | Command |
| --- | --- | --- |
| Full test suite | **146 passed** | `python -m pytest tests -q` |
| Lint | clean | `python -m ruff check src api frontend tests scripts` |
| Python compile (API/UI) | clean | `python -m py_compile ...` / CI compileall |
| Fairness | **70 / 70 passed** | `python scripts/check_fairness.py` |
| Held-out evaluation | complete, 40 judged pairs | `python scripts/evaluate_ranking.py --split test ...` |
| Real API/UI smoke | checked with the real MiniLM index; see Phase 4 report | local Uvicorn + Streamlit |

## Phase 2/3 measured results

| System | Validation NDCG@10 | Test NDCG@10 | Test NDCG@5 |
| --- | --- | --- | --- |
| TF-IDF | 0.994733 | 0.990624 | 0.980872 |
| Semantic (MiniLM) | 0.983385 | 0.996218 | 0.985067 |
| Hybrid (frozen) | 1.000000 | **0.998711** | **1.000000** |
| Hybrid + cross-encoder | 0.941590 | 0.934082 | 0.852214 |

- Index `v1-sentence-transformers-all-minilm-l6-v2-23-520c99df` (23 jobs, 384-d, FAISS).
- Weights frozen after validation-only selection; the tested default was retained because
  all candidates tied at 1.0000 and none cleared the +0.005 rule.
- Cross-encoder reranking remained negative and is disabled.
- Test set: r11-r14, 40 judged pairs. Synthetic corpus, one annotator, near-ceiling metrics.
- Warm hybrid median total time: **69.69 ms** (4 resumes, real model, same process, evidence
  included). This is a single-host measurement, not a capacity claim.

## Phase 4 delivered

- FastAPI app in `api/` with upload, parse, match, latest matches, skill gaps, jobs,
  deletion, health, readiness, metrics and meta endpoints.
- SQLAlchemy storage (`sessions`, `resumes`, `match_runs`) with SQLite local and PostgreSQL
  Compose configuration. Only a SHA-256 session-token hash is stored.
- Raw uploads are never persisted; parsed documents have a 24-hour default retention and
  cascade deletion. Session-scoped access prevents cross-session reads in the tested flows.
- Middleware: request IDs, structured errors, rate limiting, foreign-origin rejection,
  security headers, no-store API responses and CORS allow-list.
- Streamlit Candidate Mode: upload, parsed review, filters, ranked evidence, score chart,
  skill-gap tabs, all-jobs browser and deletion.
- Dockerfile, `docker-compose.yml` (API + UI + PostgreSQL), `.dockerignore`, idempotent
  `scripts/bootstrap_runtime.py`, and GitHub Actions CI.
- 8 API/storage integration tests and the full suite cover upload, matching, session
  isolation, deletion, invalid files, foreign origin, health, metrics and retention purge.

## Deliberately broken fixtures - observed behaviour

| Fixture | Behaviour |
| --- | --- |
| `corrupt.pdf` | Rejected, `corrupt_document` |
| `empty.pdf` | Parsed as `failed`, low-text warning |
| `scanned.pdf` (image-only) | Parsed as `failed`, low-text warning |
| `not_a_resume.exe` | Rejected, `unsupported_file_type` |

## Known status boundaries

- No real resumes; all quality claims are scoped to the synthetic corpus.
- Single annotator and no inter-annotator agreement.
- Session-scoped access is not multi-user authentication.
- Docker Compose and cloud deployment are not claimed as verified.
- No production load test or distributed rate limiting.
- Cross-encoder remains opt-in and negative on this corpus.

## Next actions

1. Run `docker compose up --build` on a Docker host and verify the three-service stack,
   PostgreSQL persistence and container health checks.
2. Add real authentication and per-user authorization before multi-tenant deployment.
3. Re-validate parsing, ranking and fairness on lawfully obtained, consented real resumes.
4. Add scheduled retention purging and backup/restore runbooks for a production database.
5. Consider an ANN index and pre-filtered retrieval only after measuring a larger corpus.

Detailed reports: [`reports/PHASE_3_COMPLETION_REPORT.md`](reports/PHASE_3_COMPLETION_REPORT.md),
[`reports/PHASE_4_COMPLETION_REPORT.md`](reports/PHASE_4_COMPLETION_REPORT.md) and
[`reports/BASELINE_VS_HYBRID_RESULTS.md`](reports/BASELINE_VS_HYBRID_RESULTS.md).

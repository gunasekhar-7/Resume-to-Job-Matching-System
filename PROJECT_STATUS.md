# TalentLens - Project Status

**Last updated:** 2026-11-06
**Current phase:** All four phases implemented; local verification complete, including
per-user OIDC identity plumbing and migration/retention controls. The Docker Compose stack
was run locally against PostgreSQL and passed end-to-end API and UI checks.

## Phase overview

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Foundation, data engineering, document intelligence | **Complete** - verified |
| 2 | Semantic retrieval and matching engine | **Complete** - verified |
| 3 | Explainability, evaluation, responsible AI | **Complete** - verified |
| 4 | API, UI, storage, deployment, observability | **Complete - local scope**; Compose + PostgreSQL stack verified |

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
| Full test suite | **175 passed, 1 skipped** | `python -m pytest tests -q` |
| Backup & restore drill | passed with SHA-256 validation | `python -m pytest tests/test_backup_restore.py -q` |
| Lint | clean | `python -m ruff check src api frontend tests scripts migrations` |
| Python compile (API/UI) | clean | `python -m py_compile ...` / CI compileall |
| Fairness | **70 / 70 passed** | `python scripts/check_fairness.py` |
| Held-out evaluation | complete, 40 judged pairs | `python scripts/evaluate_ranking.py --split test ...` |
| Real API/UI smoke | checked with the real MiniLM index; see Phase 4 report | local Uvicorn + Streamlit |
| Compose + PostgreSQL E2E | upload **201**; match/latest/list **200**; 5 ranked results | local Docker stack |
| API concurrency smoke | 30 requests at concurrency 10, 0 errors; median batch 30.93 ms | local Docker stack |

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
- Latest warm `match(top_k=5)` measurement: **15.87 ms median / 22.11 ms p95** (32 samples,
  4 resumes, 8 runs, real MiniLM index). The earlier measurement was 17.86 ms / 21.99 ms.
  This is a single-host microbenchmark, not a capacity claim. In the clean CPU-only
  Compose image, the first measured API match was 536 ms during warm-up, followed by
  99 ms and 45 ms (API + pipeline, same session).

## Phase 4 delivered

- FastAPI app in `api/` with upload, parse, match, latest matches, skill gaps, jobs,
  deletion, health, readiness, metrics and meta endpoints.
- SQLAlchemy storage (`sessions`, `resumes`, `match_runs`) with SQLite local and PostgreSQL
  Compose configuration, plus `session_identities` and an Alembic initial migration. Only a
  SHA-256 session-token hash is stored.
- Raw uploads are never persisted; parsed documents have a 24-hour default retention and
  cascade deletion. Session-scoped access prevents cross-session reads in the tested flows.
- Middleware: request IDs, service bearer auth, optional verified OIDC identity, streaming
  request-size enforcement, rate limiting, foreign-origin rejection, security headers,
  no-store API responses and CORS allow-list.
- Streamlit Candidate Mode: upload, parsed review, filters, ranked evidence, score chart,
  skill-gap tabs, all-jobs browser and deletion.
- Dockerfile, `docker-compose.yml` (API + UI + PostgreSQL), `.dockerignore`, idempotent
  `scripts/bootstrap_runtime.py`, and GitHub Actions CI.
- API/storage integration tests cover upload, matching, session and identity isolation,
  deletion, invalid files, pagination, foreign origin, health, metrics and retention purge;
  the offline suite is 170 tests plus one PostgreSQL integration test that runs in CI when a
  database URL is available.

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
- Service bearer authentication protects the API in production/Compose. When OIDC is
  configured, a verified `issuer#subject` is bound to the session and cannot be replayed
  anonymously; without OIDC configuration the deployment remains single-tenant.
- The local Docker Compose stack is verified; cloud deployment is not claimed.
- No production load test or distributed rate limiting.
- Cross-encoder remains opt-in and negative on this corpus.

## Next actions

1. Re-run `docker compose up --build` from a clean checkout and verify restart/recreate
   behavior on the target Docker host.
2. Exercise the OIDC path with a real provider (the automated tests use injected HMAC and
   local-JWKS verifiers); verify discovery, key rotation, logout and two-account isolation in
   the target deployment.
3. Re-validate parsing, ranking and fairness on lawfully obtained, consented real resumes.
4. Add backup/restore and migration-rollback runbooks; PostgreSQL migration and
   `alembic check` are verified locally and in CI.
5. Consider an ANN index and pre-filtered retrieval only after measuring a larger corpus.

Detailed reports: [`reports/PHASE_3_COMPLETION_REPORT.md`](reports/PHASE_3_COMPLETION_REPORT.md),
[`reports/PHASE_4_COMPLETION_REPORT.md`](reports/PHASE_4_COMPLETION_REPORT.md) and
[`reports/BASELINE_VS_HYBRID_RESULTS.md`](reports/BASELINE_VS_HYBRID_RESULTS.md).

# Phase 4 Completion Report - Product Engineering and Deployment

**Status:** Complete in local/single-node scope
**Date:** 2026-11-05
**Full suite:** 146 passed; Ruff clean.

## Delivered

### FastAPI backend

`api/main.py` provides:

- `POST /api/v1/resumes` upload/parse with 10 MB cap, magic-byte validation and in-memory parsing.
- `GET /api/v1/resumes/{id}`, `GET /api/v1/resumes`, `DELETE /api/v1/resumes/{id}`.
- `POST /api/v1/resumes/{id}/matches` and `GET .../matches` (latest persisted run).
- `GET /api/v1/resumes/{id}/skill-gaps`.
- `GET /api/v1/jobs`, `GET /api/v1/jobs/{id}`.
- `GET /health`, `GET /ready`, `GET /metrics`, `GET /api/v1/meta`.
- OpenAPI docs at `/docs`.

The API uses the same `MatchingPipeline` as evaluation. It does not duplicate matching logic.
Errors are structured with codes, request IDs and no traceback/document content. The service
keeps working at startup if the index is missing and reports `degraded` / 503 through readiness,
rather than serving an empty ranking.

### Storage and privacy

`src/talentlens/storage/` implements SQLAlchemy 2.0 models:

- `sessions` (opaque token hash, expiry);
- `resumes` (session-scoped parsed JSON, retention deadline);
- `match_runs` (latest response, cascaded with resume).

SQLite is the local backend; PostgreSQL 16 is in Compose. Raw uploads are never persisted.
Deleting a resume cascades match runs. Expired sessions/resumes are purged at startup and via
`Storage.purge_expired()`. A second browser session cannot read or delete the first session's
resume; this is tested.

### Middleware and controls

- `X-Request-ID` propagation, bounded incoming IDs and response headers.
- Fixed-window per-process rate limit with `Retry-After`.
- Foreign-Origin rejection for state-changing requests.
- CORS allow-list, no-store API responses, `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy` and `Permissions-Policy`.
- Prometheus text metrics and a JSON metrics snapshot.

### Candidate Mode UI

`frontend/app.py` supports upload, parsing warnings, extracted sections/skills, hybrid/semantic/
TF-IDF selection, top-k, location/arrangement/seniority filters, optional reranking, ranked
evidence cards, component chart, matched/missing skills, experience notes, skill-gap tabs,
job browser and deletion. It shows the "not a probability" and "not evidenced" caveats.

### Packaging and CI

- `Dockerfile` (Python 3.11 slim, API default command).
- `docker-compose.yml`: `db` (PostgreSQL 16), `api`, `frontend`, health checks and volumes.
- `scripts/bootstrap_runtime.py`: idempotent processed-data/index bootstrap.
- `.dockerignore`.
- `.github/workflows/ci.yml`: install, Ruff, compileall, full tests and metric rerun.
- `docs/API.md`, `docs/DEPLOYMENT.md`, this report and the final summary.

## Verification actually run

| Check | Result |
| --- | --- |
| `python -m pytest tests -q` | 146 passed |
| `python -m ruff check src api frontend tests scripts` | clean |
| `python -m py_compile frontend/app.py` | clean |
| API integration tests (upload, match, evidence, session isolation, deletion, invalid upload, foreign origin, health, metrics) | pass |
| Storage retention/purge test | pass |
| Real-model API/UI smoke | recorded below |

## Not verified / limitations

- `docker compose config` succeeded, but the full stack was not started here. Container
  startup, PostgreSQL persistence and health checks are therefore unverified.
- No cloud deployment.
- No multi-user authentication; session-scoped access only.
- No production load test; single-node rate limiter.
- Streamlit was smoke-checked locally; this is not a substitute for accessibility or visual
  regression testing.

## Real-model smoke test (executed 2026-11-05)

Local Uvicorn on `127.0.0.1:8765` against the real MiniLM/FAISS artifacts and the SQLite store:

| Step | Observed result |
| --- | --- |
| `GET /ready` | 200, `status=ok`, database true, pipeline true, index `v1-sentence-transformers-all-minilm-l6-v2-23-520c99df`, 23 jobs. |
| Upload `r01_priya_single.pdf` | 201, `resume_id=resume_ce94a6098541`, parsing status `success`, 47 extracted skills. |
| Hybrid match, top 5 | 200, 5 results; top j01 at score 0.856324 with 3 section-evidence records; total 295.86 ms (cold process: retrieval 182.62 ms, scoring 109.63 ms, evidence 2.96 ms). |
| Evidence | First record: `summary`, start character 206, exact resume sentence. |
| Skill gaps | 200 over 5 jobs. |
| Delete | 204, subsequent GET 404. |
| Streamlit `127.0.0.1:8766` | 200; initial page rendered in the preview with no console errors. |

The offline API tests use the deterministic fake embedder, so they do not prove the embedding
model loads; this smoke run covers that real path. It is not a load test and does not verify
the Docker Compose stack.

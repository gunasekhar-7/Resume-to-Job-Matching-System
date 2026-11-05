# Deployment

## Local (verified)

```bash
python -m pip install -r requirements.txt
python scripts/build_sample_data.py --force
python scripts/ingest_resumes.py
python scripts/ingest_jobs.py
python scripts/build_index.py

# terminal 1
uvicorn api.main:app --host 127.0.0.1 --port 8000

# terminal 2
streamlit run frontend/app.py
```

Open `http://localhost:8501`. The API's interactive schema is at
`http://localhost:8000/docs`. The first index build downloads the MiniLM model; later runs
use the local cache. Local SQLite lives at `artifacts/talentlens.db`.

If the index is missing, the API still starts but `/ready` returns 503 and matching
requests return `index_not_built`. This is deliberate: the service never silently serves
an empty ranking.

## Docker Compose

```bash
docker compose up --build
```

Compose starts:

| Service | Port | Role |
| --- | --- | --- |
| `db` | internal | PostgreSQL 16 with a named volume. |
| `api` | 8000 | FastAPI; runs `scripts/bootstrap_runtime.py` then Uvicorn. |
| `frontend` | 8501 | Streamlit Candidate Mode. |

On first start, `bootstrap_runtime.py` runs the same ingestion and index-build commands
documented above if `data/processed` or the index is absent. The model cache and FAISS
artifacts are on the `./artifacts` bind mount, so a restart does not re-download them.
PostgreSQL data is in the `pgdata` volume. `/app/data/sample` and `/app/configs` are
read-only mounts.

Set `TALENTLENS_RESUME_RETENTION_HOURS`, `TALENTLENS_DATABASE_URL`, model settings and
other deployment values through the environment; `.env.example` lists the names. Never
commit `.env` or real resumes.

**Verification status:** `docker compose config` succeeded, validating the Compose syntax and
service references. The full three-service stack was not started in this environment, so
container startup, PostgreSQL persistence and the health checks are not claimed as verified.
The local API path has integration tests and a real-model smoke test.

## Production checklist

1. Put the API behind TLS (reverse proxy or managed ingress); set
   `cookie_secure: true` under `api` / configure the equivalent deployment override.
2. Replace the session-only access model with real authentication before multi-tenant use.
   Session cookies are bearer tokens.
3. Use PostgreSQL, not SQLite, and take encrypted backups according to retention policy.
4. Schedule `Storage.purge_expired()` or an equivalent job; startup purging alone is not a
   retention guarantee.
5. Set a per-client rate limit appropriate to the deployment; the built-in limiter is
   per-process and not distributed.
6. Mount a persistent model/cache volume; build the index as a release step or accept the
   first-start bootstrap cost.
7. Restrict `/docs`, `/metrics` and database access at the network layer as appropriate.
8. Add load testing before making latency or capacity claims. Current numbers are
   single-host, synthetic-corpus measurements.

## Observability

- `GET /health`: process, database and pipeline presence.
- `GET /ready`: dependency readiness (503 when not ready).
- `GET /metrics`: Prometheus counters and latency sums by route/status.
- `GET /api/v1/meta`: versions, non-secret configuration and an in-process metrics snapshot.
- Logs are request-ID correlated and exclude document text. Configure the platform log
  collector to retain them according to policy.

## CI

`.github/workflows/ci.yml` installs dependencies, runs Ruff, compiles Python, runs the
unit/API test suite, and reruns the metric tests. The suite uses a deterministic fake
embedder for matching tests; real-model downloads are not required for CI. Real-model
benchmarks remain explicit scripts and are not run on every push.

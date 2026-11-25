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

## Database migrations

The repository includes Alembic configuration and an initial schema migration. The Compose
API command runs `scripts/migrate_database.py` before the bootstrap and server. For a new
database outside Compose, run the migration before starting the API:

```bash
export TALENTLENS_DATABASE_URL='postgresql+psycopg2://talentlens:...@db:5432/talentlens'
python -m alembic upgrade head
python -m alembic check
```

Local tests and the plain local SQLite path still use `Storage.init()` (`create_all`) for
convenience. The startup helper handles an existing `create_all` database by adding missing
tables and stamping the current head; back it up first and review the schema before using that
compatibility path in production. Fresh and pre-Alembic SQLite paths are tested locally; the
PostgreSQL migration and storage round-trip were verified locally in the Compose stack and
are also exercised in CI.

## Per-user OIDC identity

The service token is deployment-wide. To add per-user ownership, configure all of the
following in the API environment:

```text
TALENTLENS_REQUIRE_IDENTITY=true
TALENTLENS_OIDC_ISSUER=https://your-issuer.example
TALENTLENS_OIDC_AUDIENCE=talentlens
TALENTLENS_OIDC_JWKS_URL=https://your-issuer.example/.well-known/jwks.json
```

Configure Streamlit OIDC using [`.streamlit/secrets.toml.example`](../.streamlit/secrets.toml.example),
set `TALENTLENS_UI_AUTH=true`, and keep `expose_tokens = "id"` so the trusted Streamlit
server can forward the ID token. The API verifies issuer, audience, signature and expiry,
then binds the session to `issuer#subject`. Do not expose the API directly to an untrusted
network in this mode: the token header is trusted only when it reaches the API from the UI
server. Add a real-provider login/logout and key-rotation test before production.

## Docker Compose

```bash
cp .env.example .env
# Set POSTGRES_PASSWORD and TALENTLENS_API_TOKEN to independently generated values:
#   openssl rand -hex 32
docker compose up --build
```

Compose starts:

| Service | Port | Role |
| --- | --- | --- |
| `db` | internal | PostgreSQL 16 with a named volume. |
| `api` | 127.0.0.1:8000 | FastAPI; non-root runtime, service token required. |
| `frontend` | 127.0.0.1:8501 | Streamlit Candidate Mode; sends the token server-side. |

The image installs the CPU-only PyTorch wheel before the remaining dependencies; the default
Linux PyPI wheel pulls several gigabytes of CUDA/NVIDIA libraries that this service does not
use. On first start, `bootstrap_runtime.py` runs the same ingestion and index-build commands
documented above if `data/processed` or the index is absent. The model cache and FAISS
artifacts are on the `./artifacts` bind mount, so a restart does not re-download them.
PostgreSQL data is in the `pgdata` volume. `/app/data/sample` and `/app/configs` are
read-only mounts.

Compose deliberately publishes both ports on loopback only. It requires
`POSTGRES_PASSWORD` and `TALENTLENS_API_TOKEN`; do not use the example placeholder values.
Set `TALENTLENS_RESUME_RETENTION_HOURS`, model settings and other deployment values through
the environment; `.env.example` lists the names. Never commit `.env` or real resumes.
The frontend mounts `./.streamlit` read-only, so local OIDC secrets can be supplied without
being copied into the image; create it from `.streamlit/secrets.toml.example` when needed.

**Verification status:** `docker compose config` succeeded, and the three-service stack was
started locally with PostgreSQL 16. The API migrated the empty database to
`0001_initial_schema`, passed readiness and `alembic check`, and completed a real
upload -> match -> latest-result -> listing flow; Streamlit rendered successfully in the
browser. A 30-request concurrency smoke at 10 in flight returned no errors (median batch wall
time 30.93 ms). This is a local integration result, not a production capacity claim.

## Production checklist

1. Put the API behind TLS (reverse proxy or managed ingress); set
   `TALENTLENS_COOKIE_SECURE=true`. Do not expose the Compose loopback ports directly.
2. Set a high-entropy `TALENTLENS_API_TOKEN`; keep it in the platform secret store. For
   per-user identity, set the three OIDC variables and `TALENTLENS_REQUIRE_IDENTITY=true`, then
   enable Streamlit OIDC with `TALENTLENS_UI_AUTH=true` and `expose_tokens = "id"`.
3. Use PostgreSQL, not SQLite, and take encrypted backups according to retention policy.
4. Run `python -m alembic upgrade head` as a release step. The built-in hourly sweep is a
   convenience, not a guarantee when the process is stopped; add an external scheduler if
   retention must be enforced while the API is down.
5. Set a per-client rate limit appropriate to the deployment; the built-in limiter is
   per-process and not distributed.
6. Mount a persistent model/cache volume; build the index as a release step or accept the
   first-start bootstrap cost.
7. Restrict `/docs`, `/metrics` and database access at the network layer as appropriate.
8. Add load testing before making latency or capacity claims. Current numbers are
   single-host, synthetic-corpus measurements.

## Verified performance baseline

On this host, the synthetic 23-job index and `all-MiniLM-L6-v2` produced a latest warm
`MatchingPipeline.match(top_k=5)` latency of **15.87 ms** median (p95 **22.11 ms**, 32 samples
across 4 resumes and 8 runs; `artifacts/benchmark_matching.json`). The earlier run measured
17.86 ms / 21.99 ms; the pre-change median in the same environment was **43.31 ms**
(p95 **50.96 ms**). In the clean CPU-only Compose image, the first measured API match was
536 ms during warm-up, then 99 ms and 45 ms for the same session. These are lab measurements
on one CPU host, not production SLOs; requests with reranking or different corpora will be
slower.

## Observability

- `GET /health`: process, database and pipeline presence.
- `GET /ready`: dependency readiness (503 when not ready).
- `GET /metrics`: Prometheus counters and latency sums by route/status.
- `GET /api/v1/meta`: versions, non-secret configuration and an in-process metrics snapshot.
- Logs are request-ID correlated and exclude document text. Configure the platform log
  collector to retain them according to policy.

## CI

`.github/workflows/ci.yml` installs dependencies, runs Ruff, compiles Python, runs the
unit/API test suite, and reruns the metric tests. It also starts a PostgreSQL 16 service,
runs the Alembic migration/schema check against it, and executes the PostgreSQL storage
round-trip test. The suite uses a deterministic fake embedder for matching tests; real-model
downloads are not required for CI. Real-model benchmarks remain explicit scripts and are not
run on every push.

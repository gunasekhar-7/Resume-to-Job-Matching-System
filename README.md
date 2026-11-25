# TalentLens

**Explainable resume-to-job matching and recommendation platform.**

TalentLens reads a resume, extracts structured evidence, and ranks job postings by professional
relevance. Every recommendation shows *why* it matches: the skills evidenced, the skills not
evidenced (kept separate from required vs preferred), the relevant resume sentences, and the
experience alignment. It is decision support for candidates - **not** an automated hiring
decision system, and the score is never a probability of being hired.

> **Status:** All four phases are implemented and locally verified, including 170 passing
> offline tests (the PostgreSQL test is skipped without a database URL). The real-model API/UI
> path is exercised separately. The Docker Compose stack was started against PostgreSQL and
> passed upload, match and listing checks; see
> [`PROJECT_STATUS.md`](PROJECT_STATUS.md) and
> [`PROJECT_FINAL_SUMMARY.md`](PROJECT_FINAL_SUMMARY.md).
>
> **Production 9.5 gap plan:** see [`docs/PATH_TO_9.5.md`](docs/PATH_TO_9.5.md) for the
> remaining gates and the inputs that require human/owner intervention.

## What works

- PDF, DOCX and TXT ingestion with size/type/magic-byte validation and DOCX ZIP-bomb limits.
  Raw uploads are processed in memory and never written to disk.
- Column-aware PDF extraction and DOCX body-order extraction including tables.
- Cleaning, running header/footer removal, section detection and character offsets.
- A 214-skill taxonomy with alias normalisation and evidence-preserving extraction.
- Job ingestion from JSON, CSV, manual payloads and unstructured text, with required and
  preferred requirements kept separate.
- Structured PII detection with redaction before storage, section offsets, embeddings and logs;
  only entity types remain in metadata.
- TF-IDF, semantic and hybrid retrieval over an exact FAISS index with stable job IDs.
- Required/preferred skills, evidence records, experience alignment and transparent score
  contributions.
- Sentence-level resume evidence with a configurable similarity floor; no fabricated citations.
- Structured skill-gap reports that distinguish "not evidenced here" from "the candidate lacks it".
- Held-out evaluation (NDCG, P@K, R@K, MRR), validation-only weight selection and a frozen
  test run; cross-encoder reranking stays off after a negative result.
- 70 counterfactual fairness checks and 16 documented held-out error cases.
- FastAPI with service bearer authentication, optional verified per-user OIDC identity,
  session-scoped storage, scheduled retention/deletion, bounded pagination, streaming
  request-size enforcement, per-session quotas, rate limiting, request IDs, structured
  errors, security headers, health/readiness and Prometheus metrics.
- Streamlit Candidate Mode for upload, filters, evidence review, gaps and deletion.
- SQLAlchemy storage with SQLite locally and PostgreSQL in Docker Compose, plus Alembic
  migration scaffolding; CI workflow.

## Quickstart (local)

```bash
python -m pip install -r requirements.txt

python scripts/build_sample_data.py --force
python scripts/ingest_resumes.py
python scripts/ingest_jobs.py
python scripts/build_index.py

# Terminal 1: API
uvicorn api.main:app --host 127.0.0.1 --port 8000

# Terminal 2: UI
streamlit run frontend/app.py
```

Open `http://localhost:8501`; the API schema is at `http://localhost:8000/docs`. If the
index is absent, `/ready` returns 503 rather than serving an empty ranking.

For a multi-user deployment, configure the API's OIDC verifier and Streamlit login as
described in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). Without OIDC configuration, the
service remains a single-tenant, session-scoped deployment.

## Quickstart (Docker Compose)

```bash
cp .env.example .env
# Set POSTGRES_PASSWORD and TALENTLENS_API_TOKEN to independently generated values.
docker compose up --build
```

API on `127.0.0.1:8000`, Streamlit on `127.0.0.1:8501`, PostgreSQL in a named volume. The first start runs the Alembic migration, then
ingestion and the index build; model/index artifacts are mounted under `./artifacts`.
Both services require the service token; the Compose profile fails closed without it.
The local three-service stack was started and passed health, PostgreSQL migration,
upload/match and UI checks. See
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Verification

```bash
python -m pytest tests -q                                  # 175 passed, 1 skipped
python -m ruff check src api frontend tests scripts migrations  # clean
python scripts/backup_restore.py backup                    # verified DB snapshot
python scripts/check_fairness.py                           # 70/70
python scripts/evaluate_ranking.py --split test --output reports/phase3_test_results.json
python scripts/benchmark_matching.py --runs 8 --documents 4
```

The test suite uses a deterministic fake embedder for matching and does not download models.
Real evaluation scripts require the cached MiniLM model and the built index.

## Organised layout

```text
configs/        YAML configuration + 214-skill taxonomy
data/           synthetic samples, annotations, processed JSONL
src/talentlens/ ingestion, parsing, skills, jobs, embeddings, retrieval, matching,
                evaluation, storage, monitoring, utils
api/            FastAPI application, storage integration and middleware
frontend/       Streamlit Candidate Mode
scripts/        ingestion, index, benchmark, evaluation, fairness, bootstrap
tests/          offline unit, integration and API tests
migrations/     Alembic environment and initial storage migration
docs/           requirements, architecture, methodology, privacy, API, deployment
reports/        phase completion and measured evaluation reports
```

## Measured held-out results

Test split r11-r14, 40 judged pairs, frozen weights:

| System | NDCG@10 | NDCG@5 | P@5 | R@5 |
| --- | --- | --- | --- | --- |
| TF-IDF | 0.990624 | 0.980872 | 0.400000 | 1.000000 |
| Semantic (MiniLM) | 0.996218 | 0.985067 | 0.400000 | 1.000000 |
| Hybrid | **0.998711** | **1.000000** | 0.400000 | 1.000000 |
| Hybrid + cross-encoder | 0.934082 | 0.852214 | 0.350000 | 0.916667 |

Synthetic corpus, single annotator, small near-ceiling set. Differences are not evidence of
general superiority. Full method: [`docs/EVALUATION_METHODOLOGY.md`](docs/EVALUATION_METHODOLOGY.md).

## Documentation

- [Requirements](docs/REQUIREMENTS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [API](docs/API.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Technical decisions](docs/TECHNICAL_DECISIONS.md)
- [Dataset card](docs/DATASET_CARD.md)
- [Resume parsing](docs/RESUME_PARSING.md)
- [Skill extraction](docs/SKILL_EXTRACTION.md)
- [Matching methodology](docs/MATCHING_METHODOLOGY.md)
- [Explainability](docs/EXPLAINABILITY.md)
- [Evaluation methodology](docs/EVALUATION_METHODOLOGY.md)
- [Responsible AI](docs/RESPONSIBLE_AI.md)
- [Privacy and security](docs/PRIVACY_AND_SECURITY.md)
- [Known limitations](KNOWN_LIMITATIONS.md)
- [Phase 3 report](reports/PHASE_3_COMPLETION_REPORT.md)
- [Phase 4 report](reports/PHASE_4_COMPLETION_REPORT.md)

## Privacy

All sample resumes are synthetic; every person, company, email and phone number is fictional.
Do not commit real resumes. `.gitignore` excludes private data, uploads, model caches, indexes,
databases and `.env`. Raw uploads are never stored; parsed text has a retention deadline and is
user-deletable. Structured PII is redacted before persistence. No external AI service receives
resume content. The API uses a service bearer token in production/Compose and can bind sessions
to a verified OIDC subject without storing the identity token.

## Performance baseline

With the synthetic 23-job index and `all-MiniLM-L6-v2` on this host, the latest warm
`match(top_k=5)` measurement is **15.87 ms** median (p95 **22.11 ms**, 32 samples across
4 resumes and 8 runs; `artifacts/benchmark_matching.json`). The earlier run measured
17.86 ms median and 21.99 ms p95; the same-host pre-change median was 43.31 ms. These are
lab numbers, not a production SLO; see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Licence

MIT; see [`LICENSE`](LICENSE). ESCO/O*NET are referenced conceptually; no data from either is
redistributed. Review those terms before redistributing derived taxonomies.
"# Resume-to-Job-Matching-System" 

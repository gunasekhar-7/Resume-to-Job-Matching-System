# TalentLens — Final Independent End-to-End Audit

> **Historical snapshot:** This report was captured on 2026-11-05, before the
> 2026-11-06 remediation work. Its findings describe the pre-remediation tree and are
> retained for traceability; see [`PROJECT_STATUS.md`](../PROJECT_STATUS.md),
> [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) and the current test suite for status.

**Audit date:** 2026-11-05  
**Repository:** `C:\Projects\Resume-to-Job Matching System`  
**Commit audited:** `5116357 — Phase 3-4: evidence evaluation, API/UI, storage and deployment`  
**Working tree at start:** clean  
**Audit rule compliance:** application code, configuration and committed data were not modified. The only file created by this audit is this report. Runtime test rows in the local ignored SQLite database were removed after testing.

---

## Requested verdict summary

1. **Overall production-readiness assessment:** **NOT READY for production.** The local synthetic demo is functional, but HIGH-severity privacy, fairness and authentication gaps remain.
2. **Phase-wise completion verification:** Phase 1 is substantially complete but PII redaction is missing; Phase 2 is complete for the 23-job synthetic corpus; Phase 3 is complete with reproduced metrics and structured fairness, but heading-less fairness fails; Phase 4 is partial because Docker/PostgreSQL/migrations/pagination/production auth are unverified or absent.
3. **Functional verification results:** The real PDF → parse → sections → skills → hybrid retrieval → evidence → skill gaps → Streamlit path passed. Upload validation, session isolation and deletion passed. Pagination failed.
4. **Test execution results:** **146 tests passed**, 80% statement coverage, Ruff clean, compileall clean. Mypy, Bandit, pip-audit and Docker health were not passing/available; Docker build did not complete.
5. **ML evaluation results:** 40 held-out pairs; hybrid NDCG@10 **0.998711**, NDCG@5 **1.000000**; TF-IDF **0.990624**; semantic **0.996218**; hybrid+cross-encoder **0.934082**. Structured fairness **70/70**; error analysis **16 cases**; metrics near ceiling and not generalizable.
6. **Security and reliability findings:** Upload hardening, origin checks, security headers, structured errors, rate limiting and session isolation passed. PII redaction is not wired; heading-less documents leak header/education content into scoring; authentication is absent; retention scheduling and per-session caps are missing.
7. **Missing or incomplete requirements:** FR-09 (redaction), FR-19 for heading-less documents, FR-21 scheduling/cap, FR-22 Docker/Postgres runtime; pagination and migrations are also absent.
8. **Prioritized remediation plan:** P0 fix PII, heading-less fairness and auth; P1 migrations, Docker/Postgres, retention, pagination and CI checks; P2 CRLF, docs, license, CSP and UI feedback.
9. **Final recommendation:** **NOT READY** for production; **CONDITIONALLY READY** only as a local synthetic-data demo.

---

## 0. Executive verdict

### Final recommendation

**NOT READY for production.**

The repository is a coherent and substantially working **local/demo** implementation, but it is not production-ready. The highest-impact defects are:

1. **PII is stored unredacted despite a “Done” privacy requirement and an enabled privacy configuration flag.**
2. **Headerless resumes cause protected/irrelevant header and education text to enter the semantic query and alter rankings**, while the 70/70 fairness result covers only structured resumes.
3. **The API has no authentication or multi-user authorization**; session cookies isolate anonymous browser sessions but are not an identity or access-control system.
4. The Docker image build and the PostgreSQL/Compose runtime were not completed during this audit, and no database migrations exist.

There were **no CRITICAL findings** in the sense of a shipped remote-code-execution or cross-session data breach. The HIGH findings are nevertheless release blockers for any real-resume or multi-user deployment.

**Local demo status:** **CONDITIONALLY READY**, with synthetic data only, on localhost, with no claim of production privacy or authentication.

---

## 1. Repository and architecture audit

### 1.1 Repository inventory and phase integration

The repository contains 178 tracked files and is organised into the expected layers:

| Area | Implementation | Integration result |
|---|---|---|
| Parsing | `src/talentlens/parsing/` — PDF, DOCX, TXT loaders, cleaning, sections, PII, optional OCR | Used by `ResumeParser` and API upload |
| Skills | `skills/taxonomy.py`, `normalizer.py`, `extractor.py` | Used during parsing and matching |
| Jobs | `jobs/importer.py`, `jobs/requirements.py` | Produces validated `JobPosting` records |
| Embeddings | `embeddings/embedder.py`, `embedding_cache.py` | Real MiniLM model and deterministic test embedder |
| Retrieval | `retrieval/faiss_store.py`, `semantic_retriever.py`, `tfidf_retriever.py`, `reranker.py` | Loaded by the matching pipeline |
| Matching | `matching/pipeline.py`, `hybrid_scorer.py`, `skill_matcher.py`, `experience_matcher.py`, `explainer.py`, `skill_gaps.py` | Used by API and evaluation scripts |
| Evaluation | `evaluation/metrics.py`, `labels.py`, `fairness.py`, `error_analysis.py` | Reproducible scripts and reports |
| Storage | `storage/database.py`, `models.py` | SQLAlchemy SQLite/PostgreSQL models |
| API | `api/main.py`, `service.py`, `middleware.py`, `schemas.py` | Actual backend used by Streamlit |
| UI | `frontend/app.py` | Calls the API over HTTP; no duplicated matching logic |
| Deployment | `Dockerfile`, `docker-compose.yml`, `scripts/bootstrap_runtime.py`, CI workflow | Present; Compose configuration validates; runtime not verified |

All four phases are wired into one flow. The verified end-to-end path is:

`upload → validation → in-memory parsing → section detection → skill extraction → SQLAlchemy persistence → semantic/FAISS retrieval → TF-IDF baseline → hybrid score → optional rerank → evidence selection → skill-gap report → FastAPI JSON → Streamlit rendering`

The API is the real backend: the Streamlit application sends multipart uploads to `POST /api/v1/resumes`, calls `POST /api/v1/resumes/{id}/matches`, and calls the skill-gap and job endpoints. There is no duplicate matching implementation in the frontend.

### 1.2 Interfaces and schemas

The Pydantic schemas are the shared contract for parsing, matching, storage and API responses. The important interfaces are coherent:

- `ResumeDocument` contains `full_text`, section lists, section spans, skills and metadata.
- `JobPosting` contains validated requirements and searchable requirement text.
- `ScoreBreakdown` exposes five weighted components plus the diagnostic TF-IDF value.
- `MatchResponse` carries rankings, evidence, explanations, model/index/config versions, timings and warnings.
- `ResumeRecord`, `SessionRecord` and `MatchRunRecord` persist the parsed document and match response.
- API request models validate `top_k`, strategy and filters.

The stable job-ID mapping is implemented by sorting jobs by `job_id`, building the vectors in that order, and using a persisted ID map in `FaissStore`. The real index loaded successfully as:

`v1-sentence-transformers-all-minilm-l6-v2-23-520c99df` — 23 jobs, 384-dimensional embeddings, FAISS backend.

### 1.3 Duplicated, unused or disconnected implementations

No duplicated matching engine was found in the API or frontend. The following disconnected controls were found and are material:

| Item | Finding |
|---|---|
| `privacy.pii_redaction_enabled` | Present in `configs/default.yaml`; **no source reference**. Redaction is not applied. |
| `privacy.persist_parsed_text` | Present in config and documented as a storage control; **no source reference**. Parsed text is always persisted. |
| `privacy.max_retained_resumes_per_session` | Present in config; **no source reference**. No cap is enforced. |
| `privacy.redaction_placeholder` | Present in config; **no source reference**. |
| `api.page_size_default` | Only used in config validation; no pagination implementation. |
| `api.page_size_max` | Reused as the maximum match `top_k`; not a page-size control. |
| `TALENTLENS_FRONTEND_API_URL` | Listed in `.env.example` and Compose; the frontend reads only `TALENTLENS_API_URL`. |
| Alembic | Declared as a dependency and claimed in architecture documentation; no `alembic.ini` or migration versions exist. |
| Retention scheduling | `purge_expired()` is called at API startup and can be called manually; no scheduler exists. |

These are not harmless leftovers: two of them concern privacy controls and one concerns the documented database migration strategy.

### 1.4 Documentation consistency

The documentation is generally candid, especially about synthetic data, the lack of demographic fairness evidence, and the unverified Docker stack. However, it contains several contradictions:

- `docs/REQUIREMENTS.md` marks **FR-09 “Detect and redact structured PII” as Done**. The implementation detects PII types but stores the original unredacted text.
- `docs/PRIVACY_AND_SECURITY.md` says parsed-text persistence is controlled by `privacy.persist_parsed_text`, but the setting has no source reference and is not honoured.
- `docs/ARCHITECTURE.md` labels storage as containing migrations, but there are no Alembic files or revision scripts.
- `KNOWN_LIMITATIONS.md` says Docker was unavailable. Docker Desktop was not running at audit start, but the client was installed and the engine was successfully started for a build attempt; the limitation is better phrased as “Compose runtime unverified.”
- `docs/REQUIREMENTS.md` presents FR-22 as Done while also stating the stack was not started. That is honest in the parenthetical, but the status column overstates completion.

---

## 2. Functional verification

### 2.1 Component results

| Stage | Verification | Result |
|---|---|---|
| PDF upload | Real `r01_priya_single.pdf` through FastAPI | **PASSED** — 201, parsed document returned |
| DOCX upload | Existing test suite and corpus ingestion | **PASSED** for tested fixtures; all suite tests passed |
| TXT upload | Real API upload and local parse; including CRLF end-to-end | **PASSED**; parser normalises line endings first |
| File validation | Unsupported extension, corrupt PDF, empty file, >10 MB file | **PASSED** — 400/422/400/413 respectively |
| Section extraction | Real PDF | **PASSED** — summary, skills, experience, projects, education, certifications, publications and header detected |
| Skill extraction | Real PDF | **PASSED** — 47 canonical skill mentions returned |
| Semantic retrieval | `strategy=semantic` through the real API | **PASSED** — 3 results; top `j01`, score `0.79866` |
| TF-IDF baseline | `strategy=tfidf` | **PASSED** — 3 results; top `j23`, score `0.383929` |
| Hybrid ranking | `strategy=hybrid` | **PASSED** — top `j01`, score `0.856324` |
| Evidence | `explanation.section_evidence` | **PASSED** for the real sample — 3 evidence items; every tested sentence was an exact substring and the reported offset matched |
| Reranking | Real held-out evaluation | **PASSED as an optional path**; quality is negative and it remains disabled |
| Skill gaps | API and Streamlit | **PASSED** — report over 23 jobs; UI report over the 3 selected recommendations |
| Latest match | `GET /matches` | **PASSED**; returns the stored response |
| Deletion | `DELETE /resumes/{id}` | **PASSED** — 204, then 404; cascaded match row removed in tested cases |
| Session isolation | Two independent API clients | **PASSED** — second client received 404 for the first client’s resume and could not delete it |
| Frontend | Streamlit `AppTest` against live API | **PASSED** — upload, parsed review, 3 ranked results, skill gaps, all-jobs tab and delete state transition; no script exception |
| Pagination | `/api/v1/jobs?page=2&page_size=5` | **FAILED** — all 23 jobs returned; invalid page parameters also accepted |

### 2.2 Real API smoke values

The real API was already running on `127.0.0.1:8765` against the real MiniLM index and SQLite storage. Independent requests in this audit produced:

- `POST /api/v1/resumes` → **201**, session cookie set, resume `resume_ce94a6098541`.
- Parsing status **success**, 47 skills, section coverage includes summary, skills, experience, projects, education, certifications, publications and header.
- Hybrid `POST /matches` → **200**, top `j01` with score **0.856324**, 3 evidence items. Timings: embed 0.34 ms, retrieve 17.85 ms, score 39.21 ms, evidence 0.94 ms, total **58.46 ms**.
- Semantic top `j01` **0.79866**, total 17.07 ms.
- TF-IDF top `j23` **0.383929**, total 41.72 ms.
- Impossible location filter → **200**, empty results, warning “No jobs matched the supplied filters.”
- `top_k=101` → **422** `validation_error`.
- Skill gaps → **200**, 23 jobs analyzed when no job filter was supplied.
- Delete → **204**; subsequent GET → **404**.

The Streamlit `AppTest` workflow used the actual API and displayed:

- Status **success**, extraction quality **0.97**, 47 skills.
- Three recommendations: **0.856**, **0.809**, **0.766**.
- Three skill-gap jobs; average required coverage **100.0%**, average preferred coverage **88.3%**.
- No Streamlit exceptions during initial load, upload, ranking, tab rendering or deletion.

This is a script-level Streamlit test, not a browser visual inspection. A previous smoke test of the running Streamlit server returned HTTP 200 with no console errors; that is not an exhaustive visual review.

### 2.3 Upload, session and deletion controls

Verified behavior:

| Test | Result |
|---|---|
| Valid PDF upload | 201 |
| Second valid PDF, second client | 201; session B is distinct |
| Client B `GET` client A’s resume | 404 `not_found` |
| Client B `DELETE` client A’s resume | 404 |
| Client B `GET` its own resume | 200 |
| Client A deletes its resume | 204 |
| Client A `GET` deleted resume | 404 |
| Unsupported `.exe` | 400 `unsupported_file_type` |
| Corrupt PDF | 422 `corrupt_document` |
| Empty TXT | 400 `empty_upload` |
| 10 MB + 1 byte PDF | 413 `file_too_large` |
| Foreign `Origin: https://evil.example` | 403 `foreign_origin` |
| Missing session on resume route | 401 `session_required` |
| Rate limiting | 61st request in a minute returned **429**, `Retry-After: 60` |

Security headers observed on API responses:

`X-Request-ID`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`; API responses used `Cache-Control: no-store`.

### 2.4 Missing-header resume test — functional and fairness failure

A heading-less TXT resume was accepted by the API (**201**) with fallback warnings. It was placed in the `other`/`header` buckets. The semantic query for a document with no summary, skills, experience or projects falls back to the entire `full_text`:

- Base query visibly included:
  - `Alex Morgan`
  - `alex.morgan@example.com`
  - `B.Tech in Computer Science, Example University, 2012`
- Variant replaced only name, contact and education institution.
- Base hybrid top five: `j03 0.405183`, `j08 0.402756`, `j16 0.377008`, `j07 0.376496`, `j05 0.374121`.
- Variant top five: `j03 0.412676`, `j08 0.411662`, `j07 0.390644`, `j16 0.386929`, `j05 0.382079`.

The order of `j16` and `j07` changed, and every score changed. The API version of this test returned 201 and three results with **zero section evidence**. This directly contradicts the requirement that name, contact and education prestige be excluded from scoring. The 70/70 counterfactual suite does not catch it because all 14 corpus resumes have detected professional sections.

### 2.5 CRLF latent offset defect

`clean_text()` normalises line endings before parsing, so an uploaded CRLF TXT works end to end. However, calling `detect_sections()` directly with raw CRLF exposes an offset bug:

- LF summary span: text `Python engineer.`, offsets `8–24` — correct.
- CRLF summary span: text `\nPython engineer`, offsets `8–24` — the span starts one character early.
- CRLF skills span: text `s\r\nPyt`, offsets `32–38` — corrupted.

This is a **LOW** latent defect because the current parser cleans first. It should still be fixed or covered by a regression test because `detect_sections()` is a reusable public function and future extraction paths may pass raw text.

---

## 3. Machine-learning verification

### 3.1 Embeddings, FAISS and persistence

- Real MiniLM embedding model loaded successfully (`sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions).
- Real index loaded successfully from `artifacts/index/sentence-transformers-all-minilm-l6-v2`.
- Index version `v1-sentence-transformers-all-minilm-l6-v2-23-520c99df`, 23 jobs.
- TF-IDF artifact loaded as `tfidf-v1-23-75b6622c`.
- `FaissStore` persists vectors, job-ID mapping, version and content hashes. The pipeline checks index jobs against the job store and warns about indexed mismatches.
- A real evaluation process loaded the persisted index and produced the same metrics as the committed report (no rebuild required).
- The test suite covers FAISS mapping and persistence with a temporary directory; the full suite passed.
- LSA fallback exists; it was not the production path used in this audit.

**Result: PASSED** for the real default path. The exact index is a flat inner-product index; no ANN recall/latency claim was tested.

### 3.2 Reproduced held-out metrics

I reran `scripts/evaluate_ranking.py --split test` against the real index and a temporary output path. The run finished with exit code 0 and wrote the temporary artifact. The measured values exactly matched the committed test report:

| System | NDCG@10 | NDCG@5 | P@5 | R@5 | MRR | Mean total ms |
|---|---:|---:|---:|---:|---:|---:|
| TF-IDF | 0.990624 | 0.980872 | 0.400 | 1.000 | 1.000 | 71.09 |
| Semantic | 0.996218 | 0.985067 | 0.400 | 1.000 | 1.000 | 13.96 |
| Hybrid | 0.998711 | 1.000000 | 0.400 | 1.000 | 1.000 | 36.02 |
| Hybrid + cross-encoder | 0.934082 | 0.852214 | 0.350 | 0.916667 | 1.000 | 1787.30 |

The run used 4 held-out resumes and **40 judged pairs**. The protocol removes unjudged jobs and uses graded NDCG. These are real results for this synthetic corpus, not fabricated.

### 3.3 Metric correctness and data leakage

- The metric functions were inspected and tested; the suite passed.
- The test split is frozen by resume ID in `evaluation/labels.py`: dev `r01–r07` (70 pairs), validation `r08–r10` (30 pairs), test `r11–r14` (40 pairs). There is no resume overlap.
- `tune_weights.py` loads only the validation split; it does not load the test split. The default weights were retained because no candidate cleared the improvement rule.
- The held-out test run is independent of the tuning code path. However, the repository history cannot independently prove the historical claim that the test set was touched only once; that remains a process claim rather than a cryptographically verifiable fact.
- The labels are single-annotator synthetic judgments. `j23` has no relevance label; 22 of 23 jobs are labelled. This is acceptable for the stated synthetic scope but limits coverage.
- The metrics are near-ceiling: hybrid NDCG@10 0.998711 on only 40 pairs. The difference from semantic (0.996218) is a few thousandths. This does not establish a meaningful general advantage for hybrid retrieval.
- No production/demographic data was used. No demographic fairness claim is made.

### 3.4 Fairness

The standard counterfactual suite was rerun against the real model and all 14 structured corpus resumes:

- **70 checks** (14 resumes × 5 variants).
- **70 passed**, zero failures.
- Variants: name change, contact change, education-prestige change, graduation-year change, and all changes.
- Invariance rule: same top-10 order, score delta ≤ 1e-9 and component delta ≤ 1e-9.

**PASSED for the tested structured documents.** This result does **not** cover heading-less documents, where the fallback query demonstrably includes protected header/education content and changes rankings (see 2.4). It also does not establish demographic fairness; there are no demographic labels.

### 3.5 Error analysis

The committed error-analysis artifact was independently reproduced from the test rankings:

- **16 cases**
- 8 strong matches in top-k
- 11 partial matches in top-k
- 5 strong-match judgments placed on relevance-0 jobs

Every case carries an actual rank, label, score, missing-skill list and observed evidence. The generated case count and summary matched the committed artifact. This validates the script and the artifact; it does not change the synthetic, single-annotator limitation.

### 3.6 Explainability grounding

For the real `r01` resume and top job `j01`, the three evidence sentences were checked against the cleaned full text:

- Summary sentence at offset 206 — exact match, occurs once.
- Experience heading-like sentence at offset 1165 — exact match.
- Experience sentence at offset 1240 — exact match.
- Skills sentence at offset 443 — exact match.

The UI renders evidence with `st.text`, not Markdown/HTML. This avoids document text being interpreted as instructions or executable markup. No LLM is used anywhere in the matching/explanation path, so prompt-injection exposure is not applicable to this implementation.

For heading-less documents, the API returns matches with **no section evidence** and a note that no sentence crossed the threshold. That is better than fabricating evidence, but it fails the stronger requirement that every recommendation be traceable to evidence for the fallback case.

### 3.7 Reranker, normalization and performance

- Cross-encoder reranking is optional and disabled by default.
- Real held-out NDCG@10 fell from 0.998711 to 0.934082; mean rerank time was 1,746 ms and mean total 1,787 ms. Keeping it disabled is justified.
- Hybrid weights are configured to sum to 1.0 and are exposed in the response. The score is explicitly documented as a relevance estimate, not a probability.
- Warm real hybrid latency was 36 ms mean in evaluation and 58.46 ms in the API smoke test, within the stated <3 s target after models are warm.
- Cold model loading was about 5.4 s in this audit; cold-start Docker/API readiness was not health-checked.
- `P@5=0.4` despite high NDCG is explained by the graded-label protocol and small judged set; it should not be presented as high precision.

---

## 4. Backend and frontend verification

### 4.1 FastAPI

The API surface is implemented as documented: health, readiness, metrics, meta, jobs, upload, resume get/list/delete, match, latest match and skill gaps.

**Passed behavior:** upload validation, structured errors, session-scoped access, deletion cascade, foreign-origin rejection, rate limiting, request IDs, no-store API responses, security headers, readiness 200, job list 23, latest match retrieval, skill gaps, evidence and score breakdown.

**Defects and gaps:**

- No pagination on `/api/v1/jobs` or `/api/v1/resumes`.
- No authentication; anonymous session cookies are bearer capabilities.
- No database migrations; startup calls `create_all`.
- No enforcement of `max_retained_resumes_per_session`.
- `/metrics`, `/docs` and `/api/v1/meta` are unauthenticated; deployment documentation correctly says to restrict them at the network.
- No CSP header.
- No distributed rate limiting; the limiter is per process and keyed by client host. The single-process audit behavior was correct (200 × 60, then 429).

### 4.2 Streamlit

The actual UI flow was exercised with `streamlit.testing.v1.AppTest` against the live API. It successfully:

- accepted and uploaded a PDF;
- displayed parsed sections, status, quality and skills;
- rendered three ranked jobs with metrics and expandable details;
- rendered the score chart without exception (Streamlit 1.65);
- rendered the skill-gap tab for the three recommendations;
- rendered the all-jobs tab;
- removed the resume from session state after deletion.

No script exceptions occurred. The delete action’s success message was not observed because the app calls `st.rerun()` immediately after `st.success()`; the API deletion itself succeeded. This is a minor UX issue, not a data-integrity failure.

The frontend’s API environment variable is `TALENTLENS_API_URL`; `.env.example` lists only `TALENTLENS_FRONTEND_API_URL`, while Compose sets both. A local user following `.env.example` alone will not configure the Streamlit process.

---

## 5. Tests and quality checks actually run

| Check | Command | Actual result |
|---|---|---|
| Full test suite | `python -m pytest tests -q -p no:cacheprovider` | **146 passed**, exit 0 |
| Test coverage | `python -m pytest tests --cov=src --cov=api --cov-report=term-missing -q` | **146 passed**, 80% statement coverage; not a coverage gate |
| Lint | `python -m ruff check src api frontend tests scripts` | **Clean** |
| Compile | `python -m compileall -q src api frontend` | **Clean**, exit 0 |
| Diff hygiene | `git diff --check` | **Clean**, exit 0 |
| Full type check | `python -m mypy ...` | **Not passing**; full run exceeded 240 s; targeted run reported missing `yaml` stubs at `src/talentlens/config.py:18` |
| Security scanner | Bandit | **Not available** (`No module named bandit`) |
| Dependency audit | pip-audit | **Not available** (`No module named pip_audit`) |
| Compose syntax | `docker compose config` | **Passed**, exit 0 |
| Docker image build | `docker compose build` | **Not completed**; command hit the 295 s tool limit while downloading pip wheels; no image was produced |
| Docker health checks | `docker compose up` / service health | **Not run** (no image; no stack) |
| PostgreSQL runtime | Compose `db` service | **Not verified**; no stack run |
| Real held-out evaluation | `scripts/evaluate_ranking.py --split test` with temp output | **Passed**, metrics reproduced |
| Fairness | `run_counterfactual_fairness` against real model | **70/70 passed** |
| Error analysis | `analyse_rankings` against real test rankings | **16 cases reproduced** |
| Live API/UI | real Uvicorn on 8765 + Streamlit AppTest | **Passed** for tested flow |

### Important test limitations

- The automated suite uses a deterministic fake embedder for matching tests. It does not exercise the real MiniLM model or a real FAISS model artifact in CI.
- CI runs Ruff, compileall, pytest and evaluation unit tests. It does **not** run mypy, a security scanner, Docker build/health, or real-model benchmarks.
- No real browser automation was run. Streamlit `AppTest` is a script-level integration test; a prior HTTP smoke of the running Streamlit server returned 200, but no visual/browser review is claimed.
- No PostgreSQL runtime or migration test was performed.
- Docker build reached the `pip install` layer and was downloading `torch` (539.1 MB) and `nvidia_cudnn_cu13` (519.2 MB). The timeout was an environment/tool time limit, not evidence of a Dockerfile syntax failure; the image build remains unverified.

---

## 6. Security and responsible-AI findings

### 6.1 What passed

- **Upload validation:** extension allow-list, magic-byte checks, size cap, DOCX ZIP member/uncompressed-size limits, no filesystem path derived from user input.
- **Raw bytes:** not persisted; only parsed document JSON is stored.
- **Session isolation:** separate clients cannot read or delete each other’s resumes.
- **Cookie handling:** opaque random token, HttpOnly, SameSite=Lax, only a SHA-256 hash stored server-side.
- **CSRF/origin:** foreign `Origin` rejected with 403; CORS allow-list.
- **Rate limiting:** 60/minute observed; 61st request returned 429 with `Retry-After: 60`.
- **Error leakage:** structured errors with request IDs; no traceback or document content in 400/401/403/404/413/422 responses; generic 500 handler.
- **Logging:** parser logs IDs/counts/status; no resume text in observed log statements. `_safe_extract` logs only exception type.
- **No external AI API:** embeddings run locally; no prompt-injection surface in the matching path.
- **No raw SQL injection path:** storage uses SQLAlchemy expressions and bound values.
- **Session expiry/deletion:** deletion cascades match runs; expiry is enforced on read.
- **Security headers:** nosniff, frame denial, referrer and permissions policies present.

### 6.2 Privacy defect — PII redaction is not implemented

`parsing/pii.py` correctly detects email, phone, profile URL and URL values and builds a `redacted_text` copy. However:

- `parse_upload()` sets `ResumeDocument.full_text = text` (the original cleaned text).
- `PIIScan.redacted_text` is not consumed by the parser, API, storage or logs.
- `redact_text()` exists but has no production call site.
- `privacy.pii_redaction_enabled: true`, `privacy.persist_parsed_text: true`, `privacy.redaction_placeholder` and `privacy.max_retained_resumes_per_session` have **zero source references**.
- Reading the stored document from SQLite after a real upload showed the email and phone number in `full_text`; metadata contained only PII types.

This means the system **detects** PII, and excludes values from metadata/logs, but it does **not redact** the persisted parsed text as FR-09 claims. Access is session-scoped and retention is 24 hours by default, but a database compromise or an authorised session exposes the original identifiers. This is a HIGH finding for any real-resume use.

### 6.3 Fairness defect — headerless fallback

The protected-attribute exclusion is implemented for structured documents by building the semantic query from summary, skills, experience and projects, and by excluding header/education from scored sections. The fallback path defeats that design:

`document_query_text()` returns `document.full_text` when none of those four sections exists. A heading-less resume consequently includes name, email, phone and education in the semantic query, and its `other` section is included in section scoring. The controlled name/contact/education change altered scores and swapped ranks.

This is a HIGH fairness finding. The standard 70/70 fairness result is correctly scoped to structured corpus resumes but does not prove the invariant for the fallback path.

### 6.4 Authentication

The API is intentionally session-scoped, not authenticated. Any client can obtain a session by uploading a file; there are no accounts, roles, tenant checks, or user identity. Session cookies isolate browsers but are bearer tokens. This is acceptable for a local single-user demo and documented as such, but **HIGH** for production/multi-user use.

### 6.5 Other security/operations gaps

- Retention purge only runs at startup or via an internal/manual call; no scheduler. The configured per-session resume cap is not enforced.
- `/metrics`, `/docs` and `/api/v1/meta` are open by default; deployment docs recommend network restriction.
- No Content-Security-Policy.
- Per-process rate limit and in-process metrics do not survive multiple workers.
- Type checking and security scanning are not green/available; no dependency vulnerability audit was run.

---

## 7. Deployment and documentation verification

### 7.1 Docker

- Docker client was present; Docker Desktop initially was not running.
- `docker desktop start` succeeded; `docker info` then exited 0.
- `docker compose config` exited 0 and validated service references.
- `docker compose build` was attempted. It progressed through pulling the Python image and downloading requirements, then hit the tool’s 295-second limit while downloading `torch` and CUDA wheels. It left no image and no running containers.
- `docker compose ps` was empty.
- No `/ready` health check was run against the Compose API.
- No PostgreSQL persistence or `pgdata` test was run.

The Dockerfile itself is structurally plausible: it copies `src`, `api`, `frontend`, `configs`, `scripts`, sample data and annotations; `data/annotations` exists; it creates artifacts/data directories and exposes 8000/8501. The build is **unverified**, not proven broken.

The build log also shows a deployment efficiency issue: the CPU-oriented application installs default PyPI `torch`, pulling large CUDA/NVIDIA wheels. A production image should use a CPU-only torch index or a smaller inference base. This is a MEDIUM deployment concern independent of the timeout.

### 7.2 CI/CD

The GitHub Actions workflow installs dependencies, runs Ruff, compiles Python, runs pytest and reruns evaluation tests. It does not build Docker, run real-model tests, run mypy, run a security scanner, or deploy. It is CI, not CD. It is fit for a synthetic local project but not a release gate for production.

### 7.3 Environment and migrations

- `.env.example` uses `TALENTLENS_FRONTEND_API_URL`; the frontend ignores it and reads `TALENTLENS_API_URL`.
- `TALENTLENS_API_HOST`/`TALENTLENS_API_PORT` are settings but the documented Uvicorn command supplies host/port explicitly; Compose does the same.
- There are no Alembic configuration or version files despite the dependency and architecture claim. `Storage.init()` uses `Base.metadata.create_all()`, which cannot evolve an existing production schema safely.
- The retention setting is enforced in storage timestamps, but no scheduler enforces deletion at the deadline.
- The local setup instructions are otherwise coherent and were effectively followed by the running environment.

### 7.4 Documentation and demo readiness

The README, API doc, architecture doc, deployment doc and limitations file are unusually candid about synthetic data, single-annotator labels, no demographic fairness, and unverified Docker. The local demo works. The main documentation errors are the FR-09 “Done” claim, the `persist_parsed_text` control claim, the migration claim, and the stale Docker-availability wording.

---

## 8. Requirement and phase verification

### 8.1 Functional requirements

| ID | Requirement | Audit status |
|---|---|---|
| FR-01 | PDF, DOCX, TXT ingestion with size/type validation | **PASSED** on tested formats and fixtures |
| FR-02 | Multi-page text including layouts/tables | **PASSED for synthetic fixtures**; real-world layout robustness unverified |
| FR-03 | Section detection | **PASSED** on real sample; fallback path has fairness problem |
| FR-04 | Skills with canonical name, aliases, section, evidence, offsets | **PASSED** on real sample; CRLF direct-call offset bug latent |
| FR-05 | Structured persistent resume records | **PASSED** (SQLite); PostgreSQL runtime unverified |
| FR-06 | Job import from manual/JSON/CSV | **PASSED** by tests and corpus |
| FR-07 | Required vs preferred skills with evidence | **PASSED** |
| FR-08 | Manually authored relevance labels | **PASSED** — 140 unique labels with rationales; 22 of 23 jobs covered |
| FR-09 | **Detect and redact structured PII** | **FAILED / PARTIAL** — detection works, redaction is not applied; full text stored with PII |
| FR-10 | TF-IDF baseline and skill-overlap scoring | **PASSED** |
| FR-11 | Semantic embeddings with persisted metadata | **PASSED** |
| FR-12 | FAISS retrieval, stable IDs and versioning | **PASSED** for 23-job real index |
| FR-13 | Configurable normalized hybrid score | **PASSED** |
| FR-14 | Independent experience/seniority alignment | **PASSED** |
| FR-15 | Optional reranking | **PASSED** as optional; negative quality, disabled |
| FR-16 | Evidence-grounded explanations | **PASSED** for structured samples; **fallback returns no evidence** |
| FR-17 | Skill gaps with denominators, no “lacks skill” claim | **PASSED** |
| FR-18 | Held-out IR evaluation | **PASSED** — metrics reproduced; synthetic and near-ceiling |
| FR-19 | Counterfactual fairness | **PASSED 70/70 on structured resumes; FAILED for header-less fallback** |
| FR-20 | FastAPI + Streamlit workflow | **PASSED locally** |
| FR-21 | Deletion and retention purge | **PASSED deletion; PARTIAL retention** (startup only, no scheduler/cap) |
| FR-22 | Docker, CI, observability, deployment docs | **PARTIAL** — docs/CI present; Compose syntax valid; image/stack/Postgres health unverified |

### 8.2 Non-functional requirements

| Area | Status |
|---|---|
| Performance | **PASSED** for warm local measurements; 58 ms API hybrid, <3 s target; no load test |
| Reproducibility | **PASSED** for metrics scripts on this host; dependency versions are lower bounds, not locked |
| Privacy | **PARTIAL/FAILED** — raw bytes not stored, but PII redaction and persistence controls are not wired |
| Security | **PARTIAL** — strong local upload/session/error controls; no authentication, no security scan, per-process limiter |
| Explainability | **PASSED** for structured resumes; fallback has no evidence |
| Fairness | **PARTIAL** — structured invariance passes; headerless fallback leaks protected attributes; no demographic evidence |
| Maintainability | **PARTIAL** — clean layering and tests; no migrations, dead config, 80% coverage |
| Cost | **PASSED** locally on CPU; Docker CPU image is inefficient because of CUDA wheels |
| Availability | **PASSED** health/readiness and graceful degradation; Docker health/runtime unverified |

### 8.3 Phase-wise completion

| Phase | Verification |
|---|---|
| Phase 1 — foundation, parsing, data | **Substantially complete** on synthetic corpus; PII redaction requirement not complete; multi-layout and real-resume robustness unverified |
| Phase 2 — semantic retrieval and hybrid matching | **Complete** for this corpus; real model/index loaded; metrics and evidence verified |
| Phase 3 — evaluation, explainability, fairness | **Complete for the stated synthetic scope**; metrics/error analysis reproduced; structured fairness passes; heading-less fairness fails |
| Phase 4 — API, UI, storage, deployment | **Partial**: local API/UI, SQLite storage and deletion pass; PostgreSQL, Docker image/health, migrations, pagination, production auth and scheduler do not |

---

## 9. Findings register

### CRITICAL

**None identified.** No remote code execution, cross-session data access, authentication bypass in the tested session model, or raw upload persistence was found.

### HIGH

#### H-01 — PII redaction requirement is not implemented
- Evidence: `resume_parser.py` stores `full_text=original text`; `PIIScan.redacted_text` is unused; `redact_text()` has no production caller; privacy settings have zero source references; a real stored document contained the email and phone while metadata had only `['EMAIL', 'PHONE']`.
- Impact: real resumes are stored with direct identifiers for 24 hours; FR-09 is overstated as Done; database or session compromise exposes PII.
- Remediation: apply `redact_text()` or preserve offsets with a redacted representation; wire `persist_parsed_text` and `pii_redaction_enabled`; if redaction is intentionally display-only, change the requirement/docs and do not claim FR-09 Done. Add a database-level test asserting no email/phone in stored JSON and no raw bytes.

#### H-02 — Heading-less resumes leak protected attributes into scoring and rankings
- Evidence: `document_query_text()` falls back to `full_text`; a heading-less resume was accepted with 201; query contained name/email/education; changing only those fields changed scores and swapped `j16`/`j07`; fallback evidence list was empty. The 70/70 fairness suite covers only structured resumes.
- Impact: violates the protected-attribute exclusion and fairness requirement; could systematically affect candidates whose resumes lack conventional headings.
- Remediation: never use raw `full_text` as a scoring query; build a sanitised professional-text fallback that excludes header/education, or require at least one scored section for semantic ranking. Add heading-less counterfactuals to the fairness suite and require zero score/order delta.

#### H-03 — No authentication or multi-user authorization
- Evidence: API session is created by anonymous upload; no login, accounts, roles, tenant identity or ownership beyond the cookie; docs explicitly describe session-scoped access as not authentication. Session isolation passed, but any client can create a session.
- Impact: not safe as a production/multi-tenant resume service; bearer cookie theft grants access.
- Remediation: add an identity provider and user/tenant ownership checks, or deploy only as a single-user localhost demo behind an authenticated gateway. Never accept real resumes until a DPIA and auth model are in place.

### MEDIUM

#### M-01 — Job and resume list endpoints have no pagination
- Evidence: `/api/v1/jobs?page=2&page_size=5` returned all 23 jobs; invalid page parameters were accepted; `api.page_size_default` is unused except for a comparison; `api.page_size_max` is used as the match `top_k` limit.
- Impact: grows linearly with corpus/session data; poor API contract for production and UI scaling.
- Remediation: add bounded `offset`/`limit` or cursor pagination with response metadata; add contract tests for invalid and boundary values; stop reusing a page-size key for `top_k`.

#### M-02 — No database migrations
- Evidence: Alembic is a declared dependency and assumed by `docs/ARCHITECTURE.md`; no `alembic.ini` or versions exist; `Storage.init()` only calls `Base.metadata.create_all()`.
- Impact: schema evolution against existing PostgreSQL data is unsafe; no upgrade/downgrade path.
- Remediation: add Alembic configuration and an initial revision; run migrations in deployment; test upgrade from an existing schema on PostgreSQL.

#### M-03 — Docker image and Compose runtime remain unverified; CPU image pulls CUDA wheels
- Evidence: Compose config exit 0; Docker Desktop started; `docker compose build` timed out at 295 s while downloading `torch 539.1 MB` and `nvidia_cudnn_cu13 519.2 MB`; no image/health/PostgreSQL runtime. The Dockerfile installs default PyPI torch for a CPU project.
- Impact: FR-22’s runtime claim is unverified; image size/build time are unnecessarily large; production startup could fail on memory/disk.
- Remediation: use a CPU-only torch index/base, pin and cache dependencies, build in CI, run `docker compose up` with health checks, test PostgreSQL persistence and deletion, and record actual results.

#### M-04 — Retention cap/scheduler not enforced
- Evidence: `privacy.max_retained_resumes_per_session` has no source reference; retention purge runs at startup or manual call; no scheduler; 8 sessions were created during testing with no cap enforcement observable.
- Impact: unbounded session growth and stale data if the process is never restarted; retention promise depends on operator action.
- Remediation: enforce the cap on upload; add a scheduled purge job; expose/verify a retention operation; test expiry with a short retention window.

#### M-05 — Frontend API environment variable is disconnected
- Evidence: `frontend/app.py` reads `TALENTLENS_API_URL`; `.env.example` supplies `TALENTLENS_FRONTEND_API_URL`; Compose sets both, masking the mismatch; `EnvSettings.frontend_api_url` is not used by the frontend.
- Impact: local `.env`-based setup can point the API at one place while the UI uses the default; confusing deployment configuration.
- Remediation: standardise one variable, update `.env.example`, and add a startup check/log of the effective API URL.

### LOW

#### L-01 — `detect_sections()` mishandles raw CRLF offsets
- Evidence: direct CRLF test produced `\nPython engineer` and `s\r\nPyt` spans; the current parser cleans first, so uploaded CRLF TXT passed.
- Impact: latent offset/evidence corruption for future callers; no current user-facing failure found.
- Remediation: compute offsets from the actual newline match, or normalise line endings inside `detect_sections()`; add LF/CRLF/CR regression tests.

#### L-02 — Type checking is not a passing check
- Evidence: full mypy run exceeded 240 s; targeted mypy reported missing `yaml` stubs (`src/talentlens/config.py:18`); CI does not run mypy.
- Impact: type regressions can reach the repository; CI quality gate is incomplete.
- Remediation: add `types-PyYAML`, resolve or scope the timeout, run mypy in CI with a realistic whitelist, and record a green result.

#### L-03 — No security scanning in CI or this environment
- Evidence: `bandit` and `pip-audit` are not installed; CI has no SAST/dependency audit.
- Impact: known dependency and code-security issues are not automatically surfaced.
- Remediation: add a pinned scanner to CI, triage findings, and keep a documented exception policy.

#### L-04 — Documentation overstates privacy/migration/Docker status
- Evidence: FR-09 Done; `persist_parsed_text` control; architecture claims migrations; Docker limitation wording.
- Impact: reviewers and operators may believe controls exist that do not.
- Remediation: correct the requirement status to partial, document the actual parsed-text retention behavior, add migrations or remove the claim, and phrase Docker as “config validated; build/runtime unverified.”

#### L-05 — No LICENSE file despite MIT metadata
- Evidence: `pyproject.toml` declares MIT; no `LICENSE` file is tracked.
- Impact: distribution/legal clarity is incomplete.
- Remediation: add the MIT license text or change the declared license.

#### L-06 — Open operational endpoints and no CSP
- Evidence: `/metrics`, `/docs`, `/api/v1/meta` are unauthenticated; security headers do not include Content-Security-Policy; docs recommend network restriction.
- Impact: information exposure and reduced browser hardening in a public deployment.
- Remediation: authenticate/restrict operational endpoints at the gateway, disable docs in production, add a CSP appropriate to the Streamlit/API setup.

#### L-07 — Streamlit delete confirmation is not visible
- Evidence: AppTest showed state cleared after delete but `success` count 0 because the app calls `st.rerun()` immediately after `st.success()`.
- Impact: user may not know deletion succeeded; no data-integrity issue.
- Remediation: use `st.toast`/rerun-safe flash state or show confirmation before rerunning.

---

## 10. Prioritized remediation plan

### P0 — Before any real resume or non-local deployment

1. Implement and test PII redaction/persistence controls (H-01).
   - Acceptance: a stored resume contains no detected email/phone/profile URL in `full_text`; `pii_redaction_enabled=false` has a defined behavior; `persist_parsed_text=false` prevents document persistence; tests assert both.
2. Remove the raw-full-text scoring fallback and add heading-less fairness tests (H-02).
   - Acceptance: changing only name/contact/education on a heading-less resume leaves top-k order, scores and components unchanged; no fallback evidence is fabricated.
3. Add authentication or constrain deployment to a single authenticated operator/local host (H-03).
   - Acceptance: no anonymous public upload; per-user ownership enforced; bearer-cookie limitations documented.

### P1 — Production hardening

4. Add database migrations and test PostgreSQL upgrade/persistence (M-02).
5. Make Docker build/runtime a CI and release gate; use CPU-only torch and measure image size/startup/health (M-03).
6. Enforce the per-session cap and scheduled retention purge (M-04).
7. Add pagination and contract tests to job/resume listings (M-01).
8. Fix the frontend API environment variable and local setup docs (M-05).
9. Add mypy, Bandit/pip-audit (or equivalent) to CI (L-02/L-03).

### P2 — Cleanup and robustness

10. Fix raw-CRLF section offsets and add regression tests (L-01).
11. Correct FR-09, privacy, migration and Docker documentation (L-04).
12. Add a LICENSE file (L-05).
13. Restrict `/metrics`, `/docs`, `/meta` and add CSP (L-06).
14. Make the delete confirmation rerun-safe (L-07).
15. Re-evaluate on consented real resumes with inter-annotator agreement, a DPIA, and a load test. Current metrics are not generalizable.

---

## 11. Final recommendation

**Production: NOT READY.**

The implementation is substantially functional and the local synthetic demo works end to end. The test suite, real-model evaluation, structured fairness checks, error analysis, evidence grounding, API workflow, session isolation, deletion and upload hardening all produced credible results. The project is **not** production-ready because:

- FR-09 PII redaction is not implemented despite being marked Done;
- the heading-less fallback violates protected-attribute exclusion and can change rankings;
- there is no authentication/multi-user authorization;
- Docker build, Compose runtime and PostgreSQL persistence were not verified;
- there are no migrations, pagination, enforced retention cap or scheduled purge.

**Suitable use now:** synthetic-data local demonstration on localhost, single user, no production privacy claim.

---

## Appendix A — Key commands and evidence

```text
python -m pytest tests -q -p no:cacheprovider
  -> 146 passed

python -m pytest tests --cov=src --cov=api --cov-report=term-missing -q
  -> 146 passed, 80% statement coverage

python -m ruff check src api frontend tests scripts
  -> clean

python -m compileall -q src api frontend
  -> exit 0

git diff --check
  -> exit 0

python -m mypy ...
  -> full run exceeded 240 s; targeted run:
     src/talentlens/config.py:18: Library stubs not installed for "yaml"

python scripts/evaluate_ranking.py --split test --output <temp>
  -> 40 judged pairs; metrics reproduced exactly (table in section 3.2)

run_counterfactual_fairness(...)
  -> 70 checks, 70 passed

analyse_rankings(...)
  -> 16 cases, summary 8 / 11 / 5

docker compose config
  -> exit 0

docker compose build
  -> tool timeout at 295 s during pip download; no image
```

## Appendix B — Real index and storage observations

- Index: `v1-sentence-transformers-all-minilm-l6-v2-23-520c99df`, 23 jobs, 384 dimensions, FAISS flat inner product.
- TF-IDF: `tfidf-v1-23-75b6622c`.
- Real API health/readiness both returned 200 before testing.
- Real ML evaluation and fairness loaded the persisted artifacts successfully.
- Stored SQLite document inspection before cleanup confirmed email and phone were present in `full_text`, with only PII types in metadata. This is direct evidence for H-01.
- Test sessions/resumes/match rows were removed from the ignored local SQLite database after the audit. No tracked file other than this report was created or modified.

## Appendix C — Scope limitations

- No real resumes, no demographic labels, and no production traffic were available.
- No browser visual review or load test was performed.
- PostgreSQL was not started; no migration/runtime test was possible.
- Docker build did not complete, so container startup, health checks, model download in-container and Compose service dependencies remain unverified.
- No external security audit, penetration test, DPIA or dependency-vulnerability service was run.
- The 70/70 fairness result is a counterfactual invariance result on structured synthetic resumes, not evidence of demographic fairness.

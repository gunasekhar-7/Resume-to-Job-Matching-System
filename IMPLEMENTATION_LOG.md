# Implementation Log

Chronological record of what was built, what was measured, and what failed first.

---

## 2026-11-04 - Phase 1

### Environment and scaffolding
- Inspected the workspace: empty except `.freebuff/`; initialised Git.
- Verified Python 3.11.7 and installed packages; installed `faiss-cpu==1.15.1`.
- Confirmed HuggingFace reachability and that `all-MiniLM-L6-v2` and `bge-small-en-v1.5` are
  already cached locally (used in Phase 2).
- Created config (`configs/default.yaml`), typed schemas, domain errors, request-scoped logging,
  text/ID/timing utilities, and packaging/test configuration.

### Synthetic corpus
- Authored 14 resumes and 23 job postings, including two-column, table-based, fresher,
  career-change and unstructured-posting cases.
- Generated real PDF, DOCX and TXT files with `fpdf2`/`python-docx`; added corrupt, empty and
  image-only fixtures.
- Added `manifest.json` with IDs and content hashes.

### Parsing
- Implemented PyMuPDF block extraction, DOCX body-order extraction, cleaning, section detection,
  PII detection, extraction-quality scoring and the resume parser.
- First PDF run: two-column pages interleaved. Diagnosed by printing block coordinates; added
  gutter detection with balance scoring. A second bug returned the gutter *width* instead of the
  right-column x, which made wide left-column lines look like full-width blocks; fixed and
  covered by a direct unit test.
- Running footers initially prevented gutter detection; excluded margin blocks and added
  running-footer removal during cleaning.
- Empty/scanned PDFs yielded 52 footer characters; added low-text detection so they fail with a
  warning instead of producing an empty resume.

### Skills
- Authored a 214-skill taxonomy (15 categories) with alias normalisation and a conservative
  related-credit map.
- Implemented dual spaCy PhraseMatchers (`LOWER` + `ORTH`), overlap resolution, section and
  sentence evidence, and offsets.
- Fixed `R` matching prose ("R and D") by restricting single-letter matches to skills sections or
  list-like context.

### Jobs
- Implemented requirement splitting, experience-range parsing, seniority/work-arrangement
  inference, and JSON/CSV/manual/text import.
- Fixed an unstructured-posting gap: narrative skills were dropped when a required statement
  existed; they are now recorded as preferred with a warning.
- Fixed a false report claim: the repeat-import check originally used a fresh importer, so it
  could not detect duplicates. It now re-imports into the same importer and reports 23 prevented
  duplicates.

### Verification
- `python scripts/build_sample_data.py --force` -> 26 resume files, 23 jobs, 4 fixtures.
- `python scripts/ingest_resumes.py` -> 26/26 parsed, 14 unique, 0 failures, avg quality 0.961.
- `python scripts/ingest_jobs.py` -> 23/23 imported, 108 required / 94 preferred, 0 rejected.
- `python -m pytest tests -q` -> 60 passed.
- `python -m ruff check src tests scripts` -> clean after fixes.

### Issues found and resolved
| Issue | Resolution |
| --- | --- |
| Inline bullet characters corrupted words | Bullet glyphs removed from global replacements; handled per line |
| Sentence splitting skipped lines just under 60 chars | Always split, with abbreviation protection |
| Two-column reading order interleaved | Gutter detection with balance scoring and correct right-column edge |
| Footer created a phantom gutter | Margin blocks excluded from column detection |
| `max_size_mb=0` ignored | Explicit `None` check |
| `SVM: {}` invalid taxonomy reference | Removed |
| `R` matched prose | Single-letter context guard tightened |
| Duplicate-import check was ineffective | Same-importer re-import, report corrected |

---

## 2026-11-04 - Phase 2

### Review and design
- Read the Phase 1 completion report, schemas, processed JSONL and annotation split.
- Reused parsed `ResumeDocument`, `JobPosting`, the 214-skill taxonomy and job requirement data;
  no Phase 1 component was rebuilt.
- Fixed the interface contract first: added `ScoreBreakdown.tfidf` for the diagnostic baseline and
  `JobMatch.rerank_score` so a reranked order can be audited against the hybrid score.

### Embeddings
- Implemented a Sentence-Transformer embedder (CPU, lazy load, 384-d), an LSA fallback, a shared
  `Embedder` interface and `get_embedder()`.
- Added a hash-keyed npz embedding cache; only SHA-256 keys are stored, never raw text.
- Built `scripts/benchmark_embeddings.py` for validation-only comparison (r08-r10).
- Result: MiniLM NDCG@10 0.9834 / 12.26 ms per doc; BGE 0.9929 / 21.86 ms per doc; TF-IDF
  reference 0.9947. Kept MiniLM as default for CPU cost and because the BGE difference is not
  meaningful on 30 judged pairs. Recorded that semantic retrieval is not yet shown to beat TF-IDF.

### Retrieval
- Implemented TF-IDF word 1-2 grams with persistence and versioning (1,305 features).
- Implemented exact FAISS `IndexFlatIP` + `IndexIDMap2`, an explicit ID map, content/version
  hashes, duplicate rejection, incremental add, load checks and a labelled NumPy fallback.
- Implemented semantic retrieval and candidate-union logic.
- Added `scripts/build_index.py`; built the real 23-job index
  `v1-sentence-transformers-all-minilm-l6-v2-23-520c99df`.

### Matching
- Implemented exact/related skill coverage with required/preferred separation and evidence
  selection; no double counting; neutral coverage for underspecified postings.
- Implemented experience parsing, merged overlapping roles, internship weighting, fresher and
  overqualification handling, and an explicit insufficient-information state. Education dates are
  never used as tenure.
- Implemented the weighted scorer with clamped components, contribution records and strict weight
  validation.
- Implemented the unified pipeline with `hybrid`/`tfidf`/`semantic`, filters, timings, warnings,
  persistence/reload and whole-corpus `rank_ids()` for Phase 3.
- Implemented optional cross-encoder reranking with a labelled lexical fallback.

### Testing and verification
- Added 62 matching tests (122 total) covering embeddings/cache, FAISS, TF-IDF, skill matching,
  experience alignment, scoring, strategies, filters, reranking and reproducibility.
- `python -m pytest tests -q` -> 122 passed.
- `python -m ruff check src tests scripts` -> clean.
- Real MiniLM + FAISS run on r01 and r09 produced valid top-5 rankings and breakdowns.

### Bugs found and fixed
| Issue | Resolution |
| --- | --- |
| Embedding cache batch positions were double-counted (`len(keys) + len(new_keys)` after append), causing `IndexError` on the second real-model call | Assign `len(self._keys)` before appending; added a 3-text batch cache regression test; deleted the disposable cache |
| Zero-minimum junior roles ignored an upper experience bound, giving a senior candidate full experience credit | Check `max_years + 2` first and return `0.75` with a seniority note; added a test |
| Work-arrangement filter compared a mixed-case job value against lower-cased filter values | Lower-case both sides; added a case-insensitive filter test |
| Filters were applied after a top-N cut, so they could hide allowed jobs | Retrieve the whole corpus when a filter is active; documented the scale trade-off |
| Cross-encoder reranking reduced validation NDCG (1.0000 -> 0.9416) | Kept it optional and disabled by default; recorded the negative result and latency |

### Phase 2 artifacts
- `docs/MATCHING_METHODOLOGY.md`
- `reports/PHASE_2_COMPLETION_REPORT.md`
- `reports/phase2_embedding_benchmark.json`
- `reports/phase2_reranker_benchmark.json`
- `artifacts/index/sentence-transformers-all-minilm-l6-v2/` (gitignored, rebuildable)

### Next
Phase 3: sentence-level evidence, skill-gap reports, ranking evaluator, validation-tuned and
frozen weights, held-out comparison, error analysis, counterfactual fairness and privacy review.

---

## 2026-11-05 - Phase 3

### Explainability and gaps
- Added `matching/explainer.py`: section candidates, sentence splitting, deduplication, unique
offsets, cosine selection with `matching.evidence.min_similarity` (0.30) and a maximum of three.
Wired evidence into the pipeline after final ordering, with explicit timing and a note when no
sentence passes.
- Added `matching/skill_gaps.py` and `MatchingPipeline.skill_gap_report()` for per-job required
and preferred coverage, evidenced/missing skills, frequent gaps and ambiguous mentions.
- Added 6 explainer/gap tests. Confirmed real r01 evidence with character offsets.

### Evaluation
- Added `evaluation/metrics.py`, `evaluation/labels.py`, `evaluation/fairness.py` and
`evaluation/error_analysis.py`.
- Added `scripts/tune_weights.py`, `evaluate_ranking.py`, `check_fairness.py` and
`error_analysis.py`.
- Validation-only tuning: six candidates all reached NDCG@10 1.0000, so defaults were frozen.
- One held-out run (r11-r14, 40 judged pairs): hybrid NDCG@10 0.998711, semantic 0.996218,
TF-IDF 0.990624, hybrid+CE 0.934082. Cross-encoder remains off.
- 70/70 counterfactual checks passed. 16 actual held-out error cases written to
`reports/ERROR_ANALYSIS.md`.

### Bugs found and fixed
| Issue | Resolution |
| --- | --- |
| `tune_weights.py` initially reported the number of resumes as `judged_pairs` | Sum per-job labels instead of `len(dict)`; regenerated the JSON. |
| `evaluate_ranking.py` table omitted P@5/R@5 because aggregate keys only included primary K | Aggregate every requested k for precision/recall and reran both splits. |
| The first test expectation counted resumes as labels and used a different P@K denominator | Fixed the test to match the documented `min(K, judged)` protocol. |

### Phase 3 artifacts
- `docs/EXPLAINABILITY.md`, `docs/EVALUATION_METHODOLOGY.md`, `docs/RESPONSIBLE_AI.md`,
  `docs/PRIVACY_AND_SECURITY.md`
- `reports/BASELINE_VS_HYBRID_RESULTS.md`, `reports/RANKING_EVALUATION_REPORT.md`,
  `reports/FAIRNESS_TEST_REPORT.md`, `reports/PHASE_3_COMPLETION_REPORT.md`
- JSON outputs for validation, test, tuning, fairness and error analysis.

---

## 2026-11-05 - Phase 4

### Backend and storage
- Added SQLAlchemy 2.0 storage with `sessions`, `resumes` and `match_runs`; only a SHA-256
session-token hash is stored. SQLite is local, PostgreSQL is Compose. Cascade deletion and a
24-hour default retention are implemented.
- Added FastAPI app factory with injectable pipeline/storage, upload/parse, matching, latest
match, skill gaps, jobs, deletion, health, readiness, metrics and meta routes.
- Added request IDs, structured errors, per-process rate limiting, foreign-Origin rejection,
security headers, CORS allow-list and no-store API responses.

### UI, packaging and tests
- Added Streamlit Candidate Mode with upload, parsed review, filters, evidence cards, component
chart, gaps, job browser and deletion.
- Added Dockerfile, Compose stack, `.dockerignore`, idempotent bootstrap, CI workflow and
API/deployment docs.
- Added 5 API tests, 2 storage tests and 3 fairness tests. Full suite reached 146 passed.

### Bugs found and fixed
| Issue | Resolution |
| --- | --- |
| API session dependency referenced a removed local token helper | Read the cookie directly in `require_session`; tests caught it. |
| Retention purge counted resumes after the session cascade had already removed them | Collect resume IDs before deleting sessions; test asserts both records are gone. |
| API used a generic error for oversized `top_k` (HTTP 500) | Added `InvalidRequestError` (422) and a details payload. |

### Phase 4 artifacts
- `api/`, `frontend/`, `src/talentlens/storage/`, `src/talentlens/monitoring/`
- `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.github/workflows/ci.yml`
- `scripts/bootstrap_runtime.py`, `docs/API.md`, `docs/DEPLOYMENT.md`
- `reports/PHASE_4_COMPLETION_REPORT.md`, `PROJECT_FINAL_SUMMARY.md`

### Status boundary
`docker compose config` validated the Compose syntax, but the three-service stack was not started,
so Compose is configuration-only and is not claimed as verified. The local API and UI path was
smoke-tested with the real model/index.

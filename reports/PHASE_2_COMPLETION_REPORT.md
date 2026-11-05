# Phase 2 Completion Report - Semantic Retrieval and Matching Engine

**Date:** 2026-11-04
**Status:** Complete and verified
**Verification host:** Windows 11, Python 3.11.7, CPU only

## 1. Implemented functionality

- TF-IDF cosine baseline (`TfidfRetriever`) with reproducible fit, persistence, versioning and
  top-N retrieval.
- Skill-overlap matcher with exact and taxonomy-declared related credit, required/preferred
  separation, evidence selection and explicit missing-requirement records.
- Sentence-Transformer embedding backends (`all-MiniLM-L6-v2` default, BGE selectable) with
  L2-normalised vectors, batching, a content-hash cache and metadata.
- FAISS exact inner-product index (`IndexFlatIP` + `IndexIDMap2`) with an explicit job-ID map,
  persistence/loading, version hashes, duplicate rejection, incremental `add`, and a labelled
  NumPy fallback.
- Hybrid scorer with five normalised components, configurable weights, per-component
  contributions and hand-checkable formula text.
- Experience matcher with date-range parsing, merged overlaps, internship weighting, fresher and
  overqualification handling, and an explicit insufficient-information state.
- Optional cross-encoder reranker plus an explicitly labelled lexical fallback.
- Unified `MatchingPipeline` with `hybrid`, `tfidf` and `semantic` strategies, user filters,
  timings, warnings and reproducibility metadata.
- Reproducible build and benchmark scripts.

No Phase 1 component was rebuilt. Phase 1 parsing, taxonomy, job import and annotation outputs are
consumed unchanged.

## 2. Files created or modified

**Created - package code**

- `src/talentlens/embeddings/{__init__,embedder,embedding_cache}.py`
- `src/talentlens/retrieval/{__init__,faiss_store,tfidf_retriever,semantic_retriever,reranker}.py`
- `src/talentlens/matching/{__init__,skill_matcher,experience_matcher,hybrid_scorer,pipeline}.py`

**Modified - package code**

- `src/talentlens/schemas.py` - `ScoreBreakdown.tfidf`, `JobMatch.rerank_score` and matching
  contracts.
- `src/talentlens/errors.py` - duplicate-index and reranker/error types.
- `src/talentlens/ingestion/dataset.py` - job JSONL read/write helpers.

**Created - scripts and tests**

- `scripts/build_index.py`
- `scripts/benchmark_embeddings.py`
- `scripts/benchmark_reranker.py`
- `tests/fakes.py`, `tests/factories.py`
- `tests/test_embeddings.py`, `test_faiss_store.py`, `test_tfidf.py`,
  `test_skill_matcher.py`, `test_experience_matcher.py`, `test_hybrid_scorer.py`,
  `test_matching_pipeline.py`
- `tests/conftest.py` - tests directory on `sys.path` for shared test helpers.

**Created - documentation and measured outputs**

- `docs/MATCHING_METHODOLOGY.md`
- `reports/phase2_embedding_benchmark.json`
- `reports/phase2_reranker_benchmark.json`
- this report.

## 3. Retrieval approaches

| Strategy | What determines the total | Other components |
| --- | --- | --- |
| `tfidf` | L2 TF-IDF cosine | computed for diagnostics only |
| `semantic` | normalised document embedding cosine | computed for diagnostics only |
| `hybrid` | weighted sum of five normalised components | TF-IDF retained as a diagnostic |

The baseline strategies do not quietly inherit hybrid weights. `HybridScorer.baseline()` sets
`weights = {strategy: 1.0}` and includes an explanation saying the other components are
diagnostics.

Candidate retrieval uses exact FAISS search; hybrid mode unions FAISS and TF-IDF candidates. In
hybrid mode the TF-IDF cosine is displayed but has zero weight.

## 4. Embedding models evaluated

Validation split only: resumes r08-r10, 10 judged jobs each. Unjudged jobs are excluded from the
metrics. Held-out test resumes r11-r14 were not used.

| Model | NDCG@10 | NDCG@5 | P@5 | R@5 | MRR | Params | FP32 weights | Model load | Encode |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `all-MiniLM-L6-v2` | 0.9834 | 0.9571 | 0.3333 | 1.0000 | 1.0000 | 22.7M | 86.6 MB | 5,398 ms | 12.26 ms/doc |
| `bge-small-en-v1.5` | 0.9929 | 0.9936 | 0.3333 | 1.0000 | 1.0000 | 33.4M | 127.3 MB | 4,549 ms | 21.86 ms/doc |
| TF-IDF reference | 0.9947 | 0.9707 | 0.3333 | 1.0000 | 1.0000 | - | - | - | - |

MiniLM is retained as the default for CPU latency and footprint. BGE's +0.0095 NDCG@10 over 30
judged pairs is not treated as a real advantage. TF-IDF slightly exceeds both; **no claim is made
that semantic retrieval is superior on this corpus.** The held-out Phase 3 evaluation will
address that. Raw output: `reports/phase2_embedding_benchmark.json`.

## 5. FAISS configuration

- Exact `IndexFlatIP` inside `IndexIDMap2`; cosine because vectors are L2-normalised.
- 23 jobs, 384 dimensions; no approximate index without measured need.
- Persistent explicit mapping from FAISS integer IDs to job IDs; positions are never job IDs.
- Artifacts: `index.faiss`, `vectors.npy`, `metadata.json`, `tfidf.joblib`, `embedding.json`.
- Index version: `v1-sentence-transformers-all-minilm-l6-v2-23-520c99df`.
- Duplicate IDs and duplicate non-empty content hashes are rejected; incremental additions skip
  existing IDs.
- Corrupt/mismatched versions are rejected on load; a NumPy exact backend is available and
  labelled as such.
- Build command: `python scripts/build_index.py` (23 jobs; FAISS backend confirmed).

## 6. Hybrid score formulation

```text
score = 0.30 * semantic
      + 0.15 * section_relevance
      + 0.33 * required_skill_coverage
      + 0.07 * preferred_skill_coverage
      + 0.15 * experience_alignment
```

All components are clamped to `[0, 1]` before weighting. Contributions and weights are stored in
`ScoreBreakdown`; their sum equals the total within rounding. Weights must sum to 1.0 and be
non-negative, enforced by `ScoringWeights.from_config()`.

Neutral values: no required/preferred requirements -> 0.50; no experience requirement -> 0.60;
undated experience -> 0.50. Missing skills are reported as "not evidenced", not as proof of
absence.

## 7. Initial ranking examples

Resume r01 (NLP/ML engineer), real MiniLM model + FAISS:

| Rank | Job | Score | Semantic | Section | Required | Preferred | Experience |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | j01 Machine Learning Engineer, NLP | 0.856 | 0.799 | 0.695 | 1.000 | 1.000 | 0.750 |
| 2 | j23 Machine Learning Engineer (unstructured) | 0.809 | 0.754 | 0.665 | 1.000 | 0.900 | 0.600 |
| 3 | j08 Junior Machine Learning Engineer | 0.766 | 0.629 | 0.547 | 1.000 | 0.750 | 0.750 |
| 4 | j06 NLP Research Engineer | 0.730 | 0.599 | 0.483 | 1.000 | 0.500 | 0.750 |
| 5 | j15 AI Engineer, LLM Applications | 0.632 | 0.628 | 0.540 | 0.600 | 0.750 | 0.750 |

Resume r09 (data analyst): j09 0.817, j02 0.765, j16 0.760, j13 0.682, j18 0.618.

These are illustrative outputs, not quality claims. The junior role at rank 3 for a senior
candidate is a Phase 3 error-analysis case.

## 8. Reranker performance and latency

Validation-only comparison with `cross-encoder/ms-marco-MiniLM-L-6-v2`, all 23 candidates per
resume:

| System | NDCG@10 | MRR |
| --- | --- | --- |
| Hybrid | 1.0000 | 1.0000 |
| Hybrid + cross-encoder | 0.9416 | 1.0000 |

Latency: model load 4.5 s (warm HuggingFace cache; 32.8 s on the first download), first rerank
5.0 s including load, subsequent rerank 461 ms for 23 pairs (~50 pairs/s). Mean hybrid
end-to-end time was 76 ms.

Reranking degraded graded ranking on validation and is therefore **disabled by default**. The
lexical fallback is separately tested and is always labelled `degraded=True`. Raw output:
`reports/phase2_reranker_benchmark.json`.

## 9. Verification

| Check | Result |
| --- | --- |
| `python -m pytest tests -q` | **122 passed** |
| `python -m ruff check src tests scripts` | clean |
| `python scripts/build_index.py` | 23 jobs indexed; FAISS; 384-d |
| Real-model hybrid match (r01/r09) | 5 results each; valid breakdowns; no warnings |
| Phase 1 tests | retained and passing |
| Reproducibility | repeated runs returned identical job IDs and scores |

The test suite covers embedding normalisation, batch cache indexing, cache privacy (no raw text),
FAISS ID mapping/persistence/versioning/duplicates/fallback, TF-IDF ranking/empty query,
exact/related/missing skills, required/preferred separation, experience date parsing, internships,
undated experience, education exclusion, overqualification, weight validation, baseline honesty,
filters, reranking, empty documents and pipeline reload.

### Bug found and fixed during verification

The first real-model run exposed an `IndexError` in the embedding cache. `put_many()` assigned a
row using `len(keys) + len(new_keys)` after already appending to `keys`, so batch positions were
double-counted. The fix assigns `len(self._keys)` before appending and a batch regression test was
added. The cache is disposable and was rebuilt.

The experience matcher also initially ignored an upper bound when the minimum was zero, giving a
senior candidate full credit for a 0-2 year junior role. That path now reports possible
overqualification (`0.75`) and has a dedicated test.

## 10. Acceptance criteria status

| Criterion | Status | Evidence |
| --- | --- | --- |
| Same resume retrieves via multiple strategies | **PASS** | `test_tfidf_and_semantic_baselines_are_honest`; all three strategies exercised |
| FAISS results map correctly to stored jobs | **PASS** | shuffled-ID mapping test; persistence round-trip |
| Hybrid scoring transparent and configurable | **PASS** | contributions sum to total; weight validation; formula in every breakdown |
| Required and preferred skills separate | **PASS** | dedicated tests; no double counting |
| Experience alignment independently computed | **PASS** | 12 experience tests, including fresher, internship, undated and overqualified |
| Reranking can be enabled or disabled | **PASS** | Lexical/CE paths; disabled default; benchmark recorded |
| Whole pipeline reproducible | **PASS** | identical IDs/scores on repeat; versioned index |
| Critical matching tests pass | **PASS** | 122 passed |
| No Phase 1 functionality broken | **PASS** | full suite includes all Phase 1 tests |

## 11. Known limitations

- Synthetic 23-job corpus; exact search at this scale says nothing about 100k+ job performance.
- 30 judged validation pairs and near-ceiling scores; differences are provisional.
- TF-IDF is competitive/superior on this split, so semantic benefit is not yet demonstrated.
- Cross-encoder reranking is negative on validation; only one reranker model was tested.
- Section relevance is section-level, not sentence-level; `section_evidence` was empty at the
  end of Phase 2. **Resolved in Phase 3:** sentence evidence and skill-gap reports are now
  implemented; see `reports/PHASE_3_COMPLETION_REPORT.md`.
- Hybrid weights are experimental and have not been tuned.
- Experience parsing handles common formats, not every real-world date convention.
- With a filter active the pipeline scans the full corpus to guarantee completeness; this needs a
  pre-filtered index at scale.

## 12. Phase 3 readiness

**Ready.** Phase 3 can build on:

- a single `MatchingPipeline` entry point for all strategies;
- a fully populated score breakdown plus matched/missing skill evidence;
- `rank_ids()` over the whole corpus for reproducible evaluation;
- validation/test separation already encoded in the Phase 1 annotation split;
- measured baseline numbers and a documented negative reranker result.

Phase 3 must add sentence-level evidence, skill-gap reporting, the formal ranking evaluator,
weight selection on validation, one frozen held-out run, error analysis and counterfactual
fairness tests. No test-set tuning has occurred in Phase 2.

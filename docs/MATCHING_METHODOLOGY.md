# Matching Methodology - Phases 2-3

**Status:** Phase 2 implementation complete; Phase 3 evaluation and evidence layer complete.
**Config version:** `2026-11-04.1`
**Index version:** `v1-sentence-transformers-all-minilm-l6-v2-23-520c99df`
**TF-IDF version:** `tfidf-v1-23-75b6622c`
**Corpus:** 23 synthetic job postings, 14 synthetic resumes, 140 labelled pairs.

This document describes exactly how a resume becomes a ranked list of jobs. It distinguishes
what was measured from what remains a documented default. The score is a **matching /
relevance score**, never a probability of being hired.

## 1. Scope and inputs

Phase 2 consumes validated Phase 1 records only:

- `ResumeDocument`: cleaned text, sections, skill mentions with evidence and offsets.
- `JobPosting`: title, company, description, responsibilities, required/preferred skills,
  experience range, location/work arrangement and optional seniority.

No raw file is re-read during matching. The processed JSONL corpora are the input. Location and
work arrangement are optional **user filters**; they are never part of the professional score.

## 2. Pipeline

```text
ResumeDocument
  -> query text (summary + skills + experience + projects)
  -> query embedding (L2-normalised)
  -> FAISS exact inner-product search over job vectors  ─┐
  -> TF-IDF cosine search over job text                 ─┤
                                                         ├-> candidate union
  -> per-candidate components:
       whole-document semantic similarity
       section-level semantic relevance
       required-skill coverage (exact / taxonomy-related)
       preferred-skill coverage (separate, never double-counted)
       experience alignment
       TF-IDF cosine (diagnostic in hybrid mode)
  -> weighted hybrid score + contribution breakdown
  -> optional cross-encoder rerank (disabled by default)
  -> deterministic sort, top-k, explanation records
```

The unified entry point is `talentlens.matching.MatchingPipeline`. Strategies are `hybrid`,
`tfidf` and `semantic`; the two latter strategies rank solely by their own score and return the
other components as diagnostics.

## 3. TF-IDF baseline

`TfidfRetriever` uses scikit-learn:

| Setting | Value |
| --- | --- |
| Word n-grams | 1-2 |
| `min_df` / `max_df` | 1 / 0.9 |
| Sublinear TF | yes |
| Stop words | English |
| Norm | L2 (cosine) |
| Vocabulary on the 23-job corpus | 1,305 features |

The baseline is independently fitted, persisted (`tfidf.joblib`) and versioned. Its ranking is
**not** mixed into the TF-IDF baseline total: `HybridScorer.baseline(..., baseline="tfidf")`
sets the total to the cosine score and records the other components as diagnostics only.

## 4. Semantic embeddings

### Text construction

- **Resume query:** summary, skills, experience and projects, joined in that order.
  Header/contact and education are excluded so names, email addresses and institutional
  prestige cannot directly enter similarity.
- **Job document:** title, company, description, responsibilities and skill phrases.
- **Section relevance input:** each resume section is embedded separately and compared with
  the job's description + responsibilities + required/preferred skill phrases.

Inputs are whitespace-normalised and truncated to 6,000 characters for embedding. Every vector
is L2-normalised, so inner product equals cosine similarity.

### Benchmark protocol

`scripts/benchmark_embeddings.py` compares the candidates on the Phase 1 **validation split only**
(resumes r08-r10); the held-out test resumes r11-r14 are not used. Each resume is ranked against
all 23 jobs by semantic cosine. Metrics are computed over the 10 manually judged jobs per resume;
unjudged jobs are excluded rather than counted as false negatives. This is a small,
near-ceiling synthetic set: differences of a few thousandths are not evidence of a general
advantage.

| Model | NDCG@10 | NDCG@5 | P@5 | R@5 | MRR | Params | FP32 weights | Model load | Encode |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `all-MiniLM-L6-v2` | 0.9834 | 0.9571 | 0.3333 | 1.0000 | 1.0000 | 22.7M | 86.6 MB | 5,398 ms | 12.26 ms/doc |
| `bge-small-en-v1.5` | 0.9929 | 0.9936 | 0.3333 | 1.0000 | 1.0000 | 33.4M | 127.3 MB | 4,549 ms | 21.86 ms/doc |
| TF-IDF (reference) | 0.9947 | 0.9707 | 0.3333 | 1.0000 | 1.0000 | - | - | - | - |

Both transformers are 384-dimensional. The first-use cost in a fresh process was 19.0 s for
MiniLM (including the torch/sentence-transformers import) and 4.5 s for BGE, which ran after the
runtime was already imported. Treat load times as single-run, host-specific measurements.

**Selection.** `all-MiniLM-L6-v2` remains the default because it is 1.8× faster per document and
has a smaller footprint; BGE's +0.0095 NDCG@10 on 30 judged pairs is not a reliable advantage.
BGE remains selectable through `--model` / `embeddings.model_name`. Most importantly, TF-IDF
slightly exceeds both on this validation set: the project does **not** claim that semantic
retrieval is already better than lexical retrieval. Phase 3 tested that question on the
held-out split: semantic NDCG@10 was 0.9962 vs TF-IDF 0.9906, a small difference on 40 pairs,
so the project still makes no general superiority claim.

Raw output: `reports/phase2_embedding_benchmark.json`.

## 5. FAISS index

- Exact `IndexFlatIP` with `IndexIDMap2`; cosine similarity because vectors are normalised.
- 23 jobs × 384 dimensions. Exact search is appropriate at this scale; no approximate index was
  introduced without a measured need.
- Explicit `id_map` from FAISS integer IDs to stable job IDs. Vector positions are never treated
  as permanent job identifiers.
- Persisted artifacts: `index.faiss`, `vectors.npy`, `metadata.json`, `tfidf.joblib`,
  `embedding.json`.
- The index version hashes the model ID, index type, sorted job IDs and content hashes. A loaded
  metadata version that does not match its vectors is rejected.
- Duplicate job IDs and duplicate non-empty content hashes are rejected. `add()` skips existing
  job IDs and reports which IDs were added.
- If FAISS is unavailable, an exact NumPy inner-product backend with the same interface is used
  and labelled `numpy_flat_ip`; this is never presented as FAISS.
- The index is disposable and rebuildable from stored job records:

```bash
python scripts/build_index.py
```

## 6. Hybrid score

The frozen default weights are:

| Component | Weight | Symbol |
| --- | --- | --- |
| Whole-document semantic similarity | 0.30 | semantic |
| Section-level semantic relevance | 0.15 | section_relevance |
| Required-skill coverage | 0.33 | required_skills |
| Preferred-skill coverage | 0.07 | preferred_skills |
| Experience alignment | 0.15 | experience |

```text
score = 0.30 * semantic
      + 0.15 * section_relevance
      + 0.33 * required_coverage
      + 0.07 * preferred_coverage
      + 0.15 * experience_alignment
```

Every component is clamped to `[0, 1]` **before** weighting. Contributions are rounded and
returned individually; their sum equals the total (within rounding). The full formula and the
weights are stored in each `ScoreBreakdown`. `ScoringWeights.from_config()` rejects missing,
negative or non-normalised weights.

These weights were frozen before the Phase 2/3 held-out run. Six candidate sets were compared
on validation only; all reached NDCG@10 1.0000, so none cleared the +0.005 adoption rule and
the documented defaults were retained. This is a transparent untuned default, not evidence of
optimality. See `reports/phase3_weight_tuning.json`.

### Missing and underspecified information

- No required skills in the posting -> neutral required coverage `0.50`.
- No preferred skills -> neutral preferred coverage `0.50`.
- No experience requirement -> neutral experience alignment `0.60`.
- Undated experience -> `0.50` (insufficient information), never assumed zero.
- A missing skill means "not evidenced in this document", not "the candidate lacks it".

Neutral values prevent an underspecified posting from receiving a free perfect score.

## 7. Section relevance

Only summary, skills, experience, projects and certifications are used. Header and education are
excluded. For each candidate job:

```text
section_score = max over sections s of (cos(section_s, job_requirements) * weight_s)
                / max section weight
```

The configured section weights are summary 0.6, skills 1.0, experience 1.0, projects 0.9 and
certifications 0.7. The weighted maximum is divided by the largest available weight, so a resume
without a skills section is not penalised simply for having fewer sections. This remains a
section-level measure. Phase 3 adds separate sentence-level evidence through
`matching/explainer.py`: up to three real resume sentences above a cosine floor, with section
labels and unambiguous character offsets.

## 8. Skill matching

- Exact canonical match: credit `1.0`.
- Taxonomy-declared related skill (for example PyTorch -> TensorFlow): partial credit from the
  taxonomy (`0.35`-`0.50`), labelled `related`. It is never full credit.
- Required and preferred requirements are scored and reported separately.
- A skill listed as both required and preferred is counted only once, as required.
- Coverage is the mean credit over the unique requirement set, with the denominator reported
  (`required_total`, `preferred_total`).
- Evidence selection prefers skills/experience sections, then projects, then summary, then
  certifications; exact matches and higher-confidence mentions break ties.
- Matched evidence includes the resume phrase, section, source sentence and the job requirement
  text. Missing requirements are reported with a note that absence from the document is not proof
  of absence of the skill.

## 9. Experience alignment

Only dated roles in the `experience` section count. Education dates are never used to infer age or
tenure, and projects are preserved but not counted as professional experience.

- Inclusive month ranges are parsed (`2020-01 - present`, `Jan 2020 - Dec 2021`, `2018 - 2020`).
- Overlapping roles are merged so concurrent employment is not double-counted.
- Internships are tracked separately and counted at `0.5` weight for alignment.
- Undated experience produces "insufficient information", not zero years.
- No stated requirement -> neutral `0.60`.
- Fresher-friendly posting (`min = 0`) -> `1.0`, unless the candidate exceeds the stated upper
  bound by more than two years, which is reported as possible overqualification (`0.75`).
- Below the minimum by more than 0.25 years -> proportional score `years / minimum`.
- More than two years above the stated maximum -> `0.75` and a seniority note.
- The explanation states the extracted years, the requirement and the evidence lines.

Career gaps and age are not features. A candidate with no dated experience is not treated as
having zero ability; the result says the information is insufficient.

## 10. Optional cross-encoder reranking

Implemented with `cross-encoder/ms-marco-MiniLM-L-6-v2`, scoring resume/job pairs and reordering
the hybrid candidate pool. If the model cannot load, an explicitly labelled lexical fallback can
be used (`degraded=True`), or the call fails when fallback is disabled.

Validation-only comparison (`scripts/benchmark_reranker.py`, 23 candidates per resume):

| System | NDCG@10 | MRR |
| --- | --- | --- |
| Hybrid | 1.0000 | 1.0000 |
| Hybrid + cross-encoder | 0.9416 | 1.0000 |

Latency: model load 4.5 s (warm HF cache), first rerank 5.0 s including load, subsequent rerank
461 ms for 23 pairs (~50 pairs/s). Mean hybrid end-to-end time was 76 ms on this host.

The reranker **reduced** graded ranking quality on the validation split. It therefore remains
disabled by default (`matching.reranker.enabled: false`). This is a negative result, not a
failure to report; the domain mismatch between MS MARCO pairs and resume/job pairs is a plausible
cause, but no causal claim is made.

Raw output: `reports/phase2_reranker_benchmark.json`.

## 11. Worked examples (real model, hybrid)

Resume r01 (NLP/ML engineer), top 5:

| Rank | Job | Score | Semantic | Section | Required | Preferred | Experience |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | j01 Machine Learning Engineer, NLP | 0.856 | 0.799 | 0.695 | 1.000 | 1.000 | 0.750 |
| 2 | j23 Machine Learning Engineer (unstructured) | 0.809 | 0.754 | 0.665 | 1.000 | 0.900 | 0.600 |
| 3 | j08 Junior Machine Learning Engineer | 0.766 | 0.629 | 0.547 | 1.000 | 0.750 | 0.750 |
| 4 | j06 NLP Research Engineer | 0.730 | 0.599 | 0.483 | 1.000 | 0.500 | 0.750 |
| 5 | j15 AI Engineer, LLM Applications | 0.632 | 0.628 | 0.540 | 0.600 | 0.750 | 0.750 |

Resume r09 (data analyst), top 5:

| Rank | Job | Score |
| --- | --- | --- |
| 1 | j09 Business Intelligence Analyst | 0.817 |
| 2 | j02 Data Analyst | 0.765 |
| 3 | j16 Junior Data Analyst | 0.760 |
| 4 | j13 Marketing Data Analyst | 0.682 |
| 5 | j18 Healthcare Data Analyst | 0.618 |

These are illustrative outputs, not a quality claim. r01's third result is a junior role that the
label set marks partially relevant; seniority handling is a documented error-analysis case.

## 12. Reproducibility and verification

- Deterministic tie-break by `job_id`; the same inputs, model and config produce the same order.
- Index, TF-IDF, embedding model, config version and weights travel with every response.
- `python scripts/build_index.py` rebuilds the index from `data/processed/jobs.jsonl`.
- `python -m pytest tests -q` covers embeddings/cache, FAISS mapping and persistence, duplicate
  rejection, TF-IDF, skill matching, experience alignment, weight validation, strategies,
  filters, reranking and pipeline reproducibility.
- `python -m ruff check src tests scripts` is clean.

## 13. Known limitations

- The corpus is synthetic (23 jobs, 14 resumes). Validation has 30 judged pairs and the held-out
  test has 40; confidence intervals would be wide. All test NDCG@10 values exceed 0.99.
- Semantic and TF-IDF results are close; semantic value is not established as a general
  advantage.
- Sentence evidence is selected by cosine similarity, not entailment; it can be topically
  related without proving proficiency. The floor only prevents fabricated citations.
- Cross-encoder reranking was negative on both validation and test and stays off.
- Filters retrieve the whole 23-job corpus to guarantee completeness; at larger scale this
  becomes a full scan and needs a pre-filtered index.
- Experience parsing is regex-based; unusual date formats and part-time overlap are approximated.
- Weights are a frozen documented default; no test-set tuning has occurred.

Held-out results and the full protocol are in
[`reports/BASELINE_VS_HYBRID_RESULTS.md`](../reports/BASELINE_VS_HYBRID_RESULTS.md) and
[`docs/EVALUATION_METHODOLOGY.md`](EVALUATION_METHODOLOGY.md).

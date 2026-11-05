# Baseline vs Hybrid - Held-out Results

**Evaluated:** 2026-11-05
**Split:** test only (`r11`-`r14`), frozen after validation weight selection
**Corpus:** 23 synthetic jobs, 14 synthetic resumes, 140 manually labelled pairs
**Judged pairs in this run:** 40 (10 per resume)
**Config:** `2026-11-04.1`; hybrid weights frozen at semantic 0.30, section 0.15,
required skills 0.33, preferred skills 0.07, experience 0.15
**Index:** `v1-sentence-transformers-all-minilm-l6-v2-23-520c99df`
**Raw output:** [`phase3_test_results.json`](phase3_test_results.json)

## Result

| System | NDCG@10 | NDCG@5 | P@5 | R@5 | MRR | Median total (ms) | Mean total (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TF-IDF | 0.990624 | 0.980872 | 0.400000 | 1.000000 | 1.000000 | 400.27 | 392.63 |
| Semantic (MiniLM) | 0.996218 | 0.985067 | 0.400000 | 1.000000 | 1.000000 | 27.67 | 25.80 |
| Hybrid (frozen) | **0.998711** | **1.000000** | 0.400000 | 1.000000 | 1.000000 | 69.69 | 72.68 |
| Hybrid + cross-encoder | 0.934082 | 0.852214 | 0.350000 | 0.916667 | 1.000000 | 1022.23 | 2565.82 |

`P@5` and `R@5` use binary relevance (label 2); graded NDCG uses labels 0/1/2. Unjudged
jobs are removed before metrics, so they are not counted as false negatives. Full
definitions are in [`docs/EVALUATION_METHODOLOGY.md`](../docs/EVALUATION_METHODOLOGY.md).

## Validation context

Validation (`r08`-`r10`, 30 judged pairs) was used for weight selection. It was already
near-ceiling: every candidate set had NDCG@10 = 1.0000. The documented default was kept
because no candidate cleared the +0.005 adoption rule; this is not evidence that the
weights are uniquely optimal. See [`phase3_weight_tuning.json`](phase3_weight_tuning.json).

## Interpretation

- Hybrid is the best system on the primary metric by 0.0025 NDCG@10 over semantic and
  0.0081 over TF-IDF. Those differences are not meaningful on 40 pairs from a synthetic
  corpus; no statistical-significance claim is made.
- Semantic retrieval did **not** establish a meaningful advantage over TF-IDF. The
  Phase 2 warning was correct: the test-set difference is small and the corpus is easy.
- Cross-encoder reranking remained negative on held-out data, confirming the Phase 2
  validation result. It stays disabled by default. The reranker reran 23 candidates per
  resume and its median end-to-end time was about 1.0 s, with a first-call cold start
  that raises the mean.
- The TF-IDF timing is the first strategy executed in its process and includes model and
  evidence warm-up; it is not a fair per-system latency comparison. Hybrid median
  (69.69 ms) is the useful warm-path number on this host, and it meets the target of
  under 3 seconds after warm-up.
- All four systems have MRR 1.0: the first strongly relevant job was first for every
  resume. NDCG differences come from ordering of partial/zero labels lower in the list.

## What was not tested

No real resumes, no live job board, no demographic labels, no multi-annotator agreement,
and no production load. These are synthetic-corpus results only.

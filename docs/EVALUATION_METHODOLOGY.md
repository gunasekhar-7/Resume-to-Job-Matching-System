# Evaluation Methodology

## Data

- 14 synthetic resumes, 23 synthetic job postings, 140 manually labelled resume-job
  pairs (10 per resume), one annotator.
- Relevance: 0 not relevant, 1 partially relevant, 2 strongly relevant.
- Grouped splits by resume: dev r01-r07 (70 pairs), validation r08-r10 (30), test r11-r14
  (40). No resume appears in more than one split.
- The corpus is synthetic and small. Every metric is a diagnostic on this corpus, not a
  production quality estimate.

## Metrics

Unjudged jobs are removed before computing anything. A job that was never annotated is
not a false negative. This avoids conflating ranking quality with annotation coverage.

- **NDCG@K**: graded gain `2^rel - 1` discounted by `log2(position + 1)`, normalised by
  the ideal ordering of the judged labels. Primary metric: K=10.
- **P@K**: fraction of the top K judged jobs with relevance >= 2. Denominator is
  `min(K, judged jobs)`.
- **R@K**: relevant judged jobs retrieved in the top K divided by all relevant judged jobs.
- **MRR**: reciprocal rank of the first judged job with relevance >= 2.

## Protocol

1. Build the index from the processed 23-job corpus with the frozen model and config.
2. For each resume, rank all jobs; remove unjudged jobs; apply metrics.
3. Tune only on validation. The tuning script evaluates six weight sets, uses NDCG@10
   then NDCG@5/MRR as tie-breaks, and adopts a candidate only if NDCG@10 improves by more
   than 0.005. All validation candidates tied at 1.0000, so defaults were frozen.
4. Run the test split once with the frozen weights. Record model, index, config, weights,
   rankings and timings.
5. Generate error analysis from the actual held-out rankings.

## Results

See [`BASELINE_VS_HYBRID_RESULTS.md`](../reports/BASELINE_VS_HYBRID_RESULTS.md) and
[`RANKING_EVALUATION_REPORT.md`](../reports/RANKING_EVALUATION_REPORT.md).

## Reproduce

```bash
python scripts/tune_weights.py
python scripts/evaluate_ranking.py --split validation --output reports/phase3_validation_results.json
python scripts/evaluate_ranking.py --split test --output reports/phase3_test_results.json
python scripts/error_analysis.py
python scripts/check_fairness.py
```

## Why the numbers are cautious

The test set has 40 pairs and the corpus was authored by the same project that built the
taxonomy. All systems score above 0.99 NDCG@10, so the differences cannot support a
general claim that one retrieval method is superior. There is no confidence interval
analysis, no inter-annotator agreement and no real-world sample. The held-out run was not
used to retune anything.

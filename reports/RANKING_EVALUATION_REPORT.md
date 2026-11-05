# Ranking Evaluation Report - Phase 3

This report records the evaluation protocol and the actual outputs of
`scripts/evaluate_ranking.py`. The test split was run once, after the hybrid weights were
frozen.

## Splits and labels

| Split | Resumes | Judged pairs | Use |
| --- | --- | --- | --- |
| dev | r01-r07 | 70 | development and debugging |
| validation | r08-r10 | 30 | weight selection only |
| test | r11-r14 | 40 | one held-out comparison |

Splits are grouped by resume; every label for a resume remains in that resume's split.
The 140 labels were authored against the synthetic corpus with the documented
[`annotation guidelines`](../docs/ANNOTATION_GUIDELINES.md). There is one annotator and
no inter-annotator agreement.

## Protocol

1. Rank all 23 jobs for each resume in the split.
2. Remove unjudged jobs before computing metrics. A missing annotation is not a negative.
3. Compute graded NDCG@K (`2^rel - 1`), binary P@K / R@K / MRR (relevance >= 2), and
   report both.
4. Use `min(K, judged)` as the P@K denominator when fewer than K jobs are judged.
5. Compare TF-IDF, semantic, hybrid and hybrid+cross-encoder on the same rankings.
6. Record index, model, config, weights and latency with each run.

## Held-out results

| System | NDCG@10 | NDCG@5 | P@5 | R@5 | MRR |
| --- | --- | --- | --- | --- | --- |
| TF-IDF | 0.990624 | 0.980872 | 0.400000 | 1.000000 | 1.000000 |
| Semantic | 0.996218 | 0.985067 | 0.400000 | 1.000000 | 1.000000 |
| Hybrid | **0.998711** | **1.000000** | 0.400000 | 1.000000 | 1.000000 |
| Hybrid + CE | 0.934082 | 0.852214 | 0.350000 | 0.916667 | 1.000000 |

Per-resume scores and complete rankings are in
[`phase3_test_results.json`](phase3_test_results.json). Validation results are in
[`phase3_validation_results.json`](phase3_validation_results.json).

## Weight selection

`scripts/tune_weights.py` evaluated six weight sets on validation only. All six reached
NDCG@10 = 1.0000, so the default set was retained under the stated +0.005 adoption rule.
The test split was not loaded by the tuning script. This near-ceiling validation result
is itself a limitation: it cannot distinguish weight sets.

## Reproduce

```bash
python scripts/tune_weights.py
python scripts/evaluate_ranking.py --split validation --output reports/phase3_validation_results.json
python scripts/evaluate_ranking.py --split test --output reports/phase3_test_results.json
python scripts/error_analysis.py
```

The held-out command should not be repeatedly tuned against. Any future change requires a
new frozen configuration and a documented new evaluation run.

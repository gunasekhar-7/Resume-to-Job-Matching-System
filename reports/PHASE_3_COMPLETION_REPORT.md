# Phase 3 Completion Report - Explainability, Evaluation and Responsible AI

**Status:** Complete
**Date:** 2026-11-05
**Config:** `2026-11-04.1` (weights frozen after validation-only selection)
**Index:** `v1-sentence-transformers-all-minilm-l6-v2-23-520c99df`

## Delivered

### Evidence-based explanations

- `matching/explainer.py` extracts candidate sentences from summary, skills, experience,
  projects and certifications, excludes header/education, deduplicates and records an
  offset only when the sentence occurs exactly once.
- The pipeline attaches up to three `SectionEvidence` records per top-k match, selected by
  cosine similarity against the job requirements, with a configurable floor
  (`matching.evidence.min_similarity`, default 0.30).
- If nothing crosses the floor, the explanation says so explicitly; it does not invent a
  citation. Tests cover the floor, section selection, offsets and pipeline integration.

### Skill-gap reporting

- `matching/skill_gaps.py` produces per-job required and preferred coverage, evidenced and
  missing skills, aggregate frequent gaps, ambiguous extractions and explicit notes.
- Denominators are per job; missing means "not evidenced in this document", never "the
  candidate lacks it".
- `MatchingPipeline.skill_gap_report()` restricts a report to recommended job IDs.

### Evaluation

- `evaluation/metrics.py`: graded NDCG@K, binary P@K, R@K, MRR, unjudged-job exclusion and
  explicit denominators.
- `evaluation/labels.py`: validated label loading, frozen grouped splits and leakage
  checks.
- `scripts/tune_weights.py`: six candidates on validation only; default retained because
  all candidates hit NDCG@10 = 1.0000 and none cleared the +0.005 rule.
- `scripts/evaluate_ranking.py`: validation and one held-out test comparison of TF-IDF,
  semantic, hybrid and hybrid+reranker, with timings and full rankings.

### Responsible AI

- 70 counterfactual checks across all 14 resumes and five name/contact/education variants;
  all passed.
- Error analysis generated from actual held-out rankings (`reports/ERROR_ANALYSIS.md`),
  with 16 concrete cases and their observed evidence, missing skills and experience state.
- Privacy/security review, responsible-AI statement and explainability/methodology docs.

## Measured results

| System | Validation NDCG@10 | Test NDCG@10 | Test NDCG@5 |
| --- | --- | --- | --- |
| TF-IDF | 0.994733 | 0.990624 | 0.980872 |
| Semantic (MiniLM) | 0.983385 | 0.996218 | 0.985067 |
| Hybrid (frozen) | 1.000000 | **0.998711** | **1.000000** |
| Hybrid + cross-encoder | 0.941590 | 0.934082 | 0.852214 |

The differences are small on a 40-pair synthetic held-out set. No significance or
generalisation claim is made. Cross-encoder reranking remained negative and stays off by
default.

## Tests and checks

- `python -m pytest tests -q` -> 146 passed for the combined Phases 1-4 suite.
- `python -m ruff check src api frontend tests scripts` -> clean.
- `python scripts/check_fairness.py` -> 70/70 checks passed.
- `python scripts/error_analysis.py` -> 16 held-out error cases written.

## Artifacts

- `docs/EXPLAINABILITY.md`
- `docs/EVALUATION_METHODOLOGY.md`
- `docs/RESPONSIBLE_AI.md`
- `docs/PRIVACY_AND_SECURITY.md`
- `reports/BASELINE_VS_HYBRID_RESULTS.md`
- `reports/RANKING_EVALUATION_REPORT.md`
- `reports/ERROR_ANALYSIS.md`
- `reports/FAIRNESS_TEST_REPORT.md`
- `reports/phase3_test_results.json`, `phase3_validation_results.json`,
  `phase3_weight_tuning.json`, `phase3_fairness.json`, `phase3_error_analysis.json`

## Limitations

Synthetic corpus; single annotator; near-ceiling labels; no demographic data; no
statistical fairness claim; no test-set tuning after freeze; the evaluation does not
cover real resumes or live postings.

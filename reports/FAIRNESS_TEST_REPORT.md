# Counterfactual Fairness Test Report

**Run:** 2026-11-05
**Checks:** 70 (14 resumes x 5 variants)
**Result:** 70 passed, 0 failed
**Raw output:** [`phase3_fairness.json`](phase3_fairness.json)
**Command:** `python scripts/check_fairness.py`

## What was tested

For each processed resume, the pipeline ranked the original document and five
counterfactual versions:

| Variant | Changed fields |
| --- | --- |
| `name_change` | header name, email, phone, profile URL |
| `contact_change` | contact details only |
| `education_prestige_change` | education institution |
| `graduation_year_change` | graduation year |
| `all_changes` | name, contact, institution and year together |

Professional sections, extracted skill mentions and all other scoring inputs were kept
fixed. A pass requires the same top-10 order, identical scores and identical score
components within 1e-9.

## Result

All 70 comparisons were invariant. This is consistent with the implementation:

- the semantic query excludes the header and education;
- section relevance excludes header and education;
- skill and experience matching read professional sections;
- sentence evidence excludes header and education;
- education is not used to infer age or tenure.

## What this does not establish

The corpus has no demographic labels. This test cannot show statistical parity across
gender, race, age, disability or any other protected group, and no such claim is made.
Counterfactual invariance is a narrow test of the scoring path, not a fairness audit of
the labour market or of every possible document format. Names can affect parsing in
messier real documents; that risk must be re-tested on lawful, consented data.

The full responsible-AI position is in
[`docs/RESPONSIBLE_AI.md`](../docs/RESPONSIBLE_AI.md).

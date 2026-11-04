# Relevance Annotation Guidelines

**Version:** 1.0
**Last updated:** 2026-11-04

## 1. Purpose

Produce a small, defensible relevance set for evaluating ranking quality. The label describes
**resume-job fit**, not whether the candidate would be hired and not whether the job is desirable.

## 2. Scale

| Label | Name | Definition |
| --- | --- | --- |
| 2 | Strongly relevant | Core required skills are evidenced, the role family matches, and experience/seniority is plausibly aligned. A recruiter would shortlist this profile for the role. |
| 1 | Partially relevant | Adjacent role or partial required-skill coverage; or strong skills with a clear seniority/domain mismatch. Worth reviewing, not a direct fit. |
| 0 | Not relevant | Different discipline, or the core required stack is absent. |

Relevance is **content fit**, not hiring probability. Being overqualified can reduce fit (label 1)
but never makes a relevant profile a 0 solely because of years.

## 3. Decision procedure

1. Read the resume's experience and skills sections; ignore name, location, school prestige.
2. Read the job's required skills and responsibilities.
3. Count how many *required* skills are evidenced. Related-but-distinct tools do not count as a
   match; transferable tools can support a 1, not a 2.
4. Check role family and seniority against the stated range (±2 years is plausible).
5. Check domain language in recent experience.
6. Assign 2 only when required coverage is essentially complete and the role family matches.
7. Record a one-sentence rationale.

## 4. Rules and exclusions

- Do **not** use candidate name, gender, age, nationality, photo, caste, religion, marital
  status, or university prestige as signals.
- Do **not** penalise employment gaps or graduation years.
- Do **not** treat location as competence. Location/work arrangement are user filters, not
  relevance labels.
- Do **not** infer skills from job titles alone.
- Do **not** label a pair twice; conflicts are resolved by re-reading, not averaging.

## 5. Sampling strategy

Pairs were selected by role family to guarantee positive and negative examples across all 22
structured postings:

| Resume group | Resume IDs | Judged jobs per resume | Purpose |
| --- | --- | --- | --- |
| Development | r01-r07 | 10 | Tune/iterate |
| Validation | r08-r10 | 10 | Weight/parameter selection |
| Test | r11-r14 | 10 | Held-out comparison, used once |

Result: 140 labelled pairs (24 × label 2, 50 × label 1, 66 × label 0).

## 6. Split integrity

- Splitting is **grouped by resume**: no resume appears in more than one split.
- Jobs may appear in multiple splits because the same posting is judged against different
  resumes; this is intentional and does not leak a resume's labels.
- Test resumes (r11-r14) are never used for weight tuning or error-driven fixes.
- Ranking metrics are computed against each resume's judged pool only. Unjudged jobs are
  excluded rather than assumed irrelevant; this is a pooled evaluation and is documented as a
  limitation.

## 7. Inter-annotator agreement

Not available. The labels were produced by a single annotator (the developer). No Cohen's kappa
or similar statistic is claimed. This is a material limitation: labels may encode the
annotator's judgment of fit and correlate with the taxonomy used by the system.

Mitigation: explicit rules, rationales for every pair, and reporting metrics with sample sizes.

## 8. Template

`data/annotations/annotation_template.csv` has the exact columns:

```text
pair_id,resume_id,job_id,relevance,rationale,annotator,annotated_at
```

Do not label using system output or system scores. If a second annotator is added, label the
same 30-pair subset independently and report raw agreement and kappa. Do not fabricate agreement.

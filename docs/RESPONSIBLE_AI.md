# Responsible AI

## Intended use

TalentLens is decision support for a candidate exploring job postings. It helps a person
decide what to read and where their evidence is thin. It is not an automated hiring
system, does not reject candidates, and does not produce a probability of being hired.

## Non-negotiable boundaries

1. **No protected attributes in scoring.** Names, contact details, age, gender, photo,
   caste, religion, marital status and education prestige are excluded from the score.
   Education is displayed but excluded from semantic and section scoring. Location and
   work arrangement are optional filters, never competency signals.
2. **No fabricated evidence.** Explanations must quote stored resume text; when nothing
   crosses the evidence floor, the UI says so.
3. **No automated adverse decision.** The score ranks postings for a person; a human
   reads the evidence.
4. **No external AI processing of resumes.** The default path runs locally; no resume text
   is sent to an external model API.
5. **Missing is not absent.** A missing skill means it was not evidenced in the uploaded
   document. The UI repeats this caveat.

## Fairness work

`scripts/check_fairness.py` changes names, contact details, education institution and
graduation year while preserving professional sections. All 70 checks (14 resumes x 5
variants) produced identical top-10 order, scores and components. This is a counterfactual
invariance test, not a demographic fairness audit.

The corpus has no demographic labels, so statistical parity across groups cannot be
measured and is not claimed. Real documents may parse differently when names or layouts
change; that must be re-tested on lawfully obtained, consented data before deployment.
Education exclusion also means genuinely education-dependent roles cannot express that
requirement in the score; that trade-off is deliberate and documented.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Score treated as a hiring probability | Repeated disclaimer in API, UI, docs; no probability calibration. |
| Proxy discrimination through school/name | Header and education excluded; counterfactual tests. |
| Over-trust in sentence evidence | Similarity threshold, section labels, human-readable caveats. |
| Synthetic-corpus overfitting | Frozen test split, cautious claims, single-annotator limitation. |
| Resume prompt injection | Document text is data; no LLM instruction path. |
| Private data leakage | In-memory raw uploads, retention, deletion, no content in logs. |
| Accessibility or language exclusion | Documented English-only limitation; no claim of universal support. |

## Human oversight

The candidate sees every component and every citation. The product does not aggregate
people into a ranking or make an employment decision. Recruiter Mode is explicitly out of
scope for v1. Any future use that ranks people must undergo a separate legal, privacy and
fairness review before it is built.

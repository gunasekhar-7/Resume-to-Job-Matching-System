# Explainability

TalentLens explains a ranking with evidence that existed in the uploaded document before
the score was computed. It never asks a language model to invent a rationale from a score.

## What is shown

For every returned job match:

| Field | Meaning |
| --- | --- |
| `summary` | Counts of evidenced required/preferred skills, experience state and missing requirements. |
| `score_breakdown` | Normalised component values, weights and individual contributions that sum to the total. |
| `matched_skills` | Canonical skill, job requirement, resume phrase and section, match type and credit. |
| `missing_required` / `missing_preferred` | Requirements not evidenced, with an explicit non-claim note. |
| `experience` | Parsed years, requirement, alignment status and evidence lines. |
| `section_evidence` | Up to three resume sentences with section and cosine similarity, plus a character offset when unambiguous. |
| `methodology_notes` | Scoring caveats, including that the score is not a hiring probability. |

## Evidence selection

`matching/explainer.py`:

1. Extracts candidates from summary, skills, experience, projects and certifications.
2. Excludes header, contact details, education and other sections, matching the scoring
   exclusion policy.
3. Deduplicates sentences, enforces length bounds and records an offset only if the exact
   sentence occurs once in the cleaned text.
4. Embeds candidates once per resume and compares them with the job requirement vector.
5. Selects up to `matching.evidence.max_items` (default 3) records, preferring section
   diversity, above `matching.evidence.min_similarity` (default 0.30).
6. If nothing passes, emits no evidence and adds an explicit note rather than lowering the
   threshold silently.

The threshold is a presentation guard, not a claim that a sentence proves proficiency. A
skills-list line is weak evidence; an experience bullet is stronger but still requires
human reading.

## Skill gaps

`matching/skill_gaps.py` reports required and preferred coverage separately. Coverage is
the mean credit over the unique requirements for a specific job, with the denominator
visible through the evidenced/missing lists. A related skill receives partial credit and
is labelled `related`; it is never counted as an exact match.

The report describes the uploaded document, not the person. "Not evidenced" is not
"does not have". No inference is made from absence, school, name, contact details or age.

## Failure behaviour

- Empty or unusable document: `empty_document`, no ranking.
- No evidence above the floor: empty evidence list plus a methodology note.
- Missing index or model: `index_not_built` / `model_unavailable`, not a plausible-looking
  empty result.
- Ambiguous skill extraction: surfaced in the gap report for review.

## Limits

Sentence similarity can select a sentence that is topically related but not probative.
Section relevance is still section-level, and evidence is only as good as the parser's
section detection. The explanation is decision support for a human, not a hiring
justification.

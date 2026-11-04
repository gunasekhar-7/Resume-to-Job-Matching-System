# Known Limitations

This file is the single maintained list. Phase reports add detail but must not contradict it.

## Data

1. **Synthetic-only corpus.** 14 resumes and 23 jobs authored for this project. Real resumes are
   messier; parser and extraction quality on this corpus are optimistic.
2. **No real job-board data.** Postings are short and formulaic compared with live listings.
3. **Single annotator, 140 pairs.** No inter-annotator agreement; ranking metrics carry wide
   uncertainty and may correlate with the developer's taxonomy.
4. **No demographic labels.** Statistical fairness cannot be established; only counterfactual
   invariance can be tested.
5. **English only.**

## Parsing and extraction

6. **Two columns maximum.** Column detection is heuristic; three-column or magazine layouts fall
   back to y-order and may lose section structure.
7. **No OCR by default.** Image-only PDFs fail with a warning. OCR requires Tesseract and is
   disabled; its accuracy on real scans is unverified.
8. **One-page synthetic resumes.** Multi-page header/footer removal is implemented and unit
   tested, but the corpus does not exercise long multi-page resumes end to end.
9. **Phrase-based skill extraction.** Negation and context are not modelled; a mention is not
   proof of proficiency.
10. **Finite taxonomy.** 214 hand-curated skills; niche tools are missed. No embedding-based
    skill linking.
11. **Table extraction is line-based.** Complex nested tables may be flattened. A warning is
    emitted for warehouse-style single-line dumps.
12. **Name detection is not attempted by regex.** Presidio is optional and off by default.

## Matching (to be updated in Phase 2/3)

13. **Score components are not probabilities.** Weights are experimental until tuned on
    validation data; the test set is used once, after freezing.
14. **Location and work arrangement are filters, not competence signals.**
15. **No salary, seniority or culture fit modelling.**

## Product and deployment

16. **Recruiter Mode is not implemented.**
17. **No authentication in v1.** Session-scoped access control is implemented in Phase 4;
    multi-tenant auth is out of scope.
18. **Single-node deployment.** No horizontal scaling, queue or distributed index.
19. **No production load testing.** Latency numbers are local measurements on the documented
    host, not capacity guarantees.
20. **No cloud deployment claimed.** Deployment documentation covers Docker Compose and a
    practical single-host procedure only.

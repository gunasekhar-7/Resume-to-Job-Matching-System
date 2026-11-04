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

## Matching

13. **Score components are not probabilities.** The five hybrid weights are experimental defaults;
    they will be selected on validation and frozen before the Phase 3 held-out run.
14. **Validation metrics are near-ceiling and provisional.** The benchmark uses 30 judged pairs
    (10 jobs x 3 resumes). Differences of a few thousandths are not reliable.
15. **Semantic retrieval is not yet shown to beat TF-IDF.** On validation, TF-IDF NDCG@10
    (0.9947) slightly exceeded MiniLM (0.9834) and BGE (0.9929). Phase 3 must test held-out data.
16. **Cross-encoder reranking was negative on validation.** NDCG@10 fell from 1.0000 to 0.9416;
    it remains disabled by default. Only one reranker model was tested and this is not a general
    claim about rerankers.
17. **No sentence-level evidence yet.** Phase 2 explanations include matched/missing skills,
    experience alignment and score contributions, but `MatchExplanation.section_evidence` is
    empty. Phase 3 adds traceable sentence evidence and skill-gap reports.
18. **Section relevance is section-level.** It takes a weighted maximum over whole sections, not
    independent evidence sentences, so it can be dominated by long sections.
19. **Experience parsing is regex-based.** Common ranges are supported; unusual formats,
    part-time overlap and concurrent roles are approximated through merged months.
20. **Filters trigger a full-corpus scan.** With a filter active the pipeline searches all jobs to
    guarantee completeness. This is fine for 23 jobs; larger corpora need a pre-filtered index.
21. **Exact vector search only.** `IndexFlatIP` is exact and untested at 100k+ jobs; no ANN
    recall/latency trade-off has been measured.
22. **Neutral values are configuration, not calibrated estimates.** 0.50 for absent skill sets,
    0.60 for absent experience requirements and 0.50 for undated experience are conservative
    choices documented for review.
23. **Education is excluded from scoring but still displayed.** This reduces prestige leakage;
    it also means a genuinely education-dependent role cannot express that in the score.

## Product and deployment

24. **Recruiter Mode is not implemented.**
25. **No authentication in v1.** Session-scoped access control is implemented in Phase 4;
    multi-tenant auth is out of scope.
26. **Single-node deployment.** No horizontal scaling, queue or distributed index.
27. **No production load testing.** Latency numbers are local measurements on the documented
    host, not capacity guarantees.
28. **No cloud deployment claimed.** Deployment documentation covers Docker Compose and a
    practical single-host procedure only.

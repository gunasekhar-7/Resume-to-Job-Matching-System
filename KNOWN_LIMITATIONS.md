# Known Limitations

This file is the single maintained list. Phase reports add detail but must not contradict it.

## Data

1. **Synthetic-only corpus.** 14 resumes and 23 jobs authored for this project. Real resumes are
   messier; parser and extraction quality on this corpus are optimistic.
2. **No real job-board data.** Postings are short and formulaic compared with live listings.
3. **Single annotator, 140 pairs.** No inter-annotator agreement; ranking metrics carry wide
   uncertainty and may correlate with the developer's taxonomy.
4. **No demographic labels.** Statistical fairness cannot be established; only counterfactual
   invariance is tested. No demographic-fairness claim is made.
5. **English only.**
6. **Near-ceiling labels.** Validation and test NDCG values above 0.99 cannot distinguish
   retrieval methods meaningfully. Differences of a few thousandths are not a basis for a
   general claim.

## Parsing and extraction

7. **Two columns maximum.** Column detection is heuristic; three-column or magazine layouts
   fall back to y-order and may lose section structure.
8. **No OCR by default.** Image-only PDFs fail with a warning. OCR requires Tesseract and is
   disabled; its accuracy on real scans is unverified.
9. **One-page synthetic resumes.** Multi-page header/footer removal is implemented and unit
   tested, but the corpus does not exercise long multi-page resumes end to end.
10. **Phrase-based skill extraction.** Negation and context are not modelled; a mention is not
    proof of proficiency.
11. **Finite taxonomy.** 214 hand-curated skills; niche tools are missed. No embedding-based
    skill linking.
12. **Table extraction is line-based.** Complex nested tables may be flattened. A warning is
    emitted for warehouse-style single-line dumps.
13. **Name detection is not attempted by regex.** Presidio is optional and off by default.

## Matching and explanations

14. **Score components are not probabilities.** The five weights are a documented default,
    frozen after validation-only selection. They are not calibrated estimates of suitability.
15. **Hybrid advantage is tiny and synthetic.** Held-out NDCG@10 differences are a few
    thousandths on 40 pairs. Semantic retrieval did not demonstrate a meaningful advantage over
    TF-IDF.
16. **Cross-encoder reranking was negative.** NDCG@10 fell on validation and test; it remains
    disabled by default. Only one reranker model was tested.
17. **Sentence evidence is similarity-selected, not entailment.** It can select a topically
    related sentence that is not probative. The minimum-similarity floor avoids fabrication but
    does not establish correctness.
18. **Section relevance remains section-level.** It takes a weighted maximum over whole
    sections, not independent evidence sentences.
19. **Experience parsing is regex-based.** Common ranges are supported; unusual formats,
    part-time overlap and concurrent roles are approximated through merged months.
20. **Filters trigger a full-corpus scan.** With a filter active the pipeline searches all jobs
    to guarantee completeness. This is fine for 23 jobs; larger corpora need a pre-filtered index.
21. **Exact vector search only.** `IndexFlatIP` is exact and untested at 100k+ jobs; no ANN
    recall/latency trade-off has been measured.
22. **Neutral values are configuration, not calibrated estimates.** 0.50 for absent skill sets,
    0.60 for absent experience requirements and 0.50 for undated experience are conservative
    choices documented for review.
23. **Education is excluded from scoring but still displayed.** This reduces prestige leakage;
    it also means a genuinely education-dependent role cannot express that in the score.
24. **No test-set tuning after freeze.** Any future change needs a new frozen config and a
    documented new evaluation run.

## Product and deployment

25. **Recruiter Mode is not implemented.**
26. **Session-scoped access is not authentication.** A random cookie scopes one browser
    session; there are no accounts, passwords or multi-tenant authorization. Do not deploy as a
    multi-user service without adding authentication.
27. **Single-node deployment.** No horizontal scaling, queue, distributed rate limit or
    distributed index.
28. **No production load testing.** Latency numbers are local measurements on the documented
    host, not capacity guarantees.
29. **Docker Compose is unverified.** Configs and a bootstrap script exist, but Docker was not
    available in this environment; the Compose stack, PostgreSQL persistence and container
    health checks have not been run here.
30. **No cloud deployment claimed.** Deployment documentation covers local and Compose
    procedures only.
31. **Retention purge runs at API startup and on demand.** There is no built-in scheduler.
    Production needs a scheduled purge and a backup/restore policy.
32. **Per-process rate limiting.** It is not shared across workers or replicas.
33. **Streamlit is a server-side client.** The API cookie is held in Streamlit session state;
    scaling the UI requires session affinity or an external session store.
34. **No CI for model-heavy benchmarks.** CI uses the deterministic fake embedder; real-model
    benchmark scripts are explicit and host-dependent.

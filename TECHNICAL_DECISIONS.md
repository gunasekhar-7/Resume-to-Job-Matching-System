# Technical Decisions - Register

The detailed records live in [`docs/TECHNICAL_DECISIONS.md`](docs/TECHNICAL_DECISIONS.md). This
file is the maintained index and records cross-cutting decisions that affect every phase.

## Decision register

| ID | Decision | Status | Detail |
| --- | --- | --- | --- |
| ADR-001 | Synthetic corpus; no Kaggle/scraped resumes | Accepted | `docs/TECHNICAL_DECISIONS.md#adr-001` |
| ADR-002 | `src/talentlens` package layout | Accepted | same |
| ADR-003 | PyMuPDF with column-aware block ordering | Accepted | same |
| ADR-004 | spaCy PhraseMatcher on a blank pipeline | Accepted | same |
| ADR-005 | Strict taxonomy with conservative related credit | Accepted | same |
| ADR-006 | Required vs preferred is a data property | Accepted | same |
| ADR-007 | In-memory uploads, no temp files | Accepted | same |
| ADR-008 | Low-text documents fail visibly | Accepted | same |
| ADR-009 | Evidence offsets are schema-level | Accepted | same |
| ADR-010 | JSONL in Phase 1, SQL in Phase 4 | Accepted | same |
| ADR-011 | CPU-first embeddings | Accepted | same |
| ADR-012 | Scores are relevance, not hiring probability | Accepted | same |
| ADR-013 | Exact FAISS + explicit job-ID map | Accepted | `docs/TECHNICAL_DECISIONS.md#adr-013` |
| ADR-014 | MiniLM default; BGE selectable after benchmark | Accepted | same |
| ADR-015 | Hybrid weights are experimental until validation tuning | Superseded by ADR-021 | same |
| ADR-016 | Cross-encoder reranker off by default | Accepted | same |
| ADR-017 | Section-aware semantic scoring excludes header/education | Accepted | same |
| ADR-018 | Neutral values for missing requirement information | Accepted | same |
| ADR-019 | Sentence evidence above an explicit similarity floor | Accepted | same |
| ADR-020 | Unjudged jobs excluded from ranking metrics | Accepted | same |
| ADR-021 | Weights frozen despite a validation tie | Accepted | same |
| ADR-022 | Session-scoped access, not v1 authentication | Accepted | same |
| ADR-023 | Parsed JSON storage; raw uploads never persisted | Accepted | same |
| ADR-024 | Compose configuration is unverified until run | Accepted | same |

## Cross-cutting rules

1. **No external AI services on personal documents.** Resume text never leaves the deployment.
2. **No fabricated evidence.** Explanations must cite stored text with offsets; a score alone is
   not an explanation.
3. **No protected attributes in scoring.** Names, contact details and identity fields are
   excluded; counterfactual tests verify invariance.
4. **No silent degradation.** Fallback embeddings are labelled; missing indexes and models raise
   typed errors; low-text documents fail with warnings.
5. **Configurable, versioned scoring.** Weights and model IDs are configuration and are
   persisted with every result.
6. **No test-set tuning.** Weights are selected on validation data and frozen before the final
   test run.
7. **Privacy by default.** Raw uploads are not persisted; parsed text is retention-bound and
   user-deletable.
8. **No claims without measurement.** Performance, fairness and quality statements require
   reproducible commands and recorded outputs.

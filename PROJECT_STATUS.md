# TalentLens - Project Status

**Last updated:** 2026-11-04
**Current phase:** Phase 2 complete; Phase 3 not started.

## Phase overview

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Foundation, data engineering, document intelligence | **Complete** - verified |
| 2 | Semantic retrieval and matching engine | **Complete** - verified |
| 3 | Explainability, evaluation, responsible AI | Not started |
| 4 | Product engineering, deployment, portfolio readiness | Not started |

## Verified environment

| Component | Version |
| --- | --- |
| Python | 3.11.7 (Windows 11) |
| FastAPI | 0.142.2 |
| Pydantic | 2.13.5 |
| SQLAlchemy | 2.0.35 |
| scikit-learn | 1.9.1 |
| NumPy / SciPy / pandas | 2.4.6 / 1.17.1 / 3.0.6 |
| PyMuPDF | 2.0 |
| python-docx | 1.2.0 |
| spaCy | 3.8.18 (blank `en` pipeline; no model download) |
| sentence-transformers / torch | 6.1.0 / 2.14.1 |
| faiss-cpu | 1.15.1 (installed during Phase 1 setup) |
| Streamlit | 1.65.0 |
| pytest | 9.1.1 |

## Phase 1 verified results

| Metric | Value | Source |
| --- | --- | --- |
| Resume files parsed | 26 / 26 | `python scripts/ingest_resumes.py` |
| Unique resumes after dedupe | 14 (12 format-variant duplicates) | same |
| Parse status | 14 success, 0 partial, 0 failed | same |
| Average extraction quality | 0.961 | same |
| Section coverage | summary/skills/experience/education 100%; projects 100%; certifications 42.9%; publications 21.4% | same |
| Canonical skills per resume | 16.0 average | same |
| Job postings imported | 23 (JSON), 23 (CSV), 0 rejected | `python scripts/ingest_jobs.py` |
| Required / preferred skills | 108 / 94, disjoint per job | same |
| Repeat-import duplicates prevented | 23 | same |
| Skill taxonomy | 214 canonical skills, 15 categories | `SkillTaxonomy.load()` |
| Annotated pairs | 140 (24 strong / 50 partial / 66 not relevant) across 14 resumes and 22 jobs | `data/annotations/relevance_labels.jsonl` |
| Tests (end of Phase 1) | 60 passed | `python -m pytest tests -q` |
| Lint | clean (`ruff check`) | `python -m ruff check src tests scripts` |

## Phase 2 verified results

| Metric | Value | Source |
| --- | --- | --- |
| Jobs indexed | 23 (384-d, FAISS `flat_ip`) | `python scripts/build_index.py` |
| Index version | `v1-sentence-transformers-all-minilm-l6-v2-23-520c99df` | same |
| TF-IDF vocabulary | 1,305 features (word 1-2 grams) | build log |
| Embedding benchmark | MiniLM NDCG@10 0.9834; BGE 0.9929; TF-IDF 0.9947 (validation r08-r10, 30 judged pairs) | `scripts/benchmark_embeddings.py` |
| Embedding latency | MiniLM 12.26 ms/doc; BGE 21.86 ms/doc (CPU) | same |
| Reranker comparison | Hybrid NDCG@10 1.0000; hybrid+CE 0.9416 | `scripts/benchmark_reranker.py` |
| Reranker latency | 461 ms per 23-pair rerank (warm); 4.5 s model load | same |
| Tests | 122 passed | `python -m pytest tests -q` |
| Lint | clean | `python -m ruff check src tests scripts` |

## Deliberately broken fixtures - observed behaviour

| Fixture | Behaviour |
| --- | --- |
| `corrupt.pdf` | Rejected, `corrupt_document` |
| `empty.pdf` | Parsed as `failed`, low-text warning |
| `scanned.pdf` (image-only) | Parsed as `failed`, low-text warning |
| `not_a_resume.exe` | Rejected, `unsupported_file_type` |

## What works now

- Upload validation (type, size, magic bytes, DOCX ZIP limits) with no temp files.
- PDF parsing with column-aware reading order; DOCX parsing in body order; TXT support.
- Cleaning, running header/footer removal, section detection with character offsets.
- 214-skill taxonomy, alias normalisation, evidence-preserving extraction.
- Job import from JSON/CSV/manual/text with required/preferred separation and inference warnings.
- Processed JSONL corpora, corpus quality reports, and a manually annotated evaluation set.
- Structured PII detection (emails, phones, URLs) with values never persisted in metadata.
- TF-IDF baseline plus exact FAISS retrieval with an explicit job-ID map, versioning and
  persistence; `hybrid`, `tfidf` and `semantic` strategies.
- Required/preferred skill coverage with exact and taxonomy-related credit, plus missing-skill
  evidence; independent experience alignment.
- Configurable hybrid scoring with a full contribution breakdown; optional cross-encoder
  reranking (disabled by default because it reduced validation NDCG).
- User-controlled location/work-arrangement filters, kept outside the professional score.

## Next actions (Phase 3)

1. Add sentence-level section evidence and structured skill-gap reports.
2. Implement the ranking evaluator (P@K, R@K, NDCG@10, MRR) with grouped splits and unjudged-job
   exclusion.
3. Select weights on validation, freeze them, then run the held-out test comparison of TF-IDF,
   semantic, hybrid and hybrid+reranker.
4. Perform error analysis, counterfactual fairness tests, and the privacy/security review.
5. Write the Phase 3 methodology, reports and completion report.

Detailed methodology and measured numbers: [`docs/MATCHING_METHODOLOGY.md`](docs/MATCHING_METHODOLOGY.md)
and [`reports/PHASE_2_COMPLETION_REPORT.md`](reports/PHASE_2_COMPLETION_REPORT.md).

## Blockers / risks

- No real resume dataset is bundled (privacy/licensing); all quality claims are scoped to the
  synthetic corpus.
- Single annotator for relevance labels; no inter-annotator agreement.
- Two-column detection is heuristic and limited to two columns.

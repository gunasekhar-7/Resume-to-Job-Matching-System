# TalentLens - System Architecture

**Version:** 1.0 (Phase 1)
**Last updated:** 2026-11-04

## 1. Design goals

1. **Evidence first.** Every stage preserves provenance: page → cleaned text → section offsets
   → skill mention offsets → explanation citations.
2. **Layered, not monolithic.** Parsing never imports the matching engine; matching never
   contains API or UI logic.
3. **Fail visibly.** Corrupt files, low-text PDFs, missing indexes and unavailable models
   produce typed errors or explicit warnings, never empty results that look successful.
4. **CPU-reproducible.** The default path runs on CPU with small models and deterministic
   configuration.

## 2. High-level flow

```text
                 ┌──────────────────────────── Phase 1 ────────────────────────────┐
 PDF/DOCX/TXT ──►│ ingestion.validate → parsing.extract → cleaning → sections       │
                 │        → skills.extract (taxonomy + PhraseMatcher) → ResumeDoc   │
                 └───────────────────────────────┬─────────────────────────────────┘
                                                 │ JSONL / database
 Jobs JSON/CSV/text ──► jobs.importer ──► JobPosting (required / preferred split)
                                                 │
                 ┌──────────────────────────── Phase 2 ────────────────────────────┐
                 │ embeddings (MiniLM/BGE, cached) → retrieval (TF-IDF, FAISS)      │
                 │ → matching.skill_matcher + experience_matcher + hybrid_scorer    │
                 │ → optional cross-encoder rerank → ranked JobMatch[]              │
                 └───────────────────────────────┬─────────────────────────────────┘
                                                 │
                 ┌──────────────────────────── Phase 3 ────────────────────────────┐
                 │ explainer (evidence, gaps, score contributions)                  │
                 │ evaluation (metrics, splits, benchmark, fairness, error analysis)│
                 └───────────────────────────────┬─────────────────────────────────┘
                                                 │
                 ┌──────────────────────────── Phase 4 ────────────────────────────┐
                 │ FastAPI (validation, auth-less by default, rate limiting)        │
                 │ PostgreSQL/SQLite + retention + deletion                         │
                 │ Streamlit Candidate Mode + Docker + CI + observability           │
                 └──────────────────────────────────────────────────────────────────┘
```

## 3. Module map

```text
src/talentlens/
├── config.py            YAML + environment configuration, versioned
├── schemas.py           Pydantic contracts shared by all phases
├── errors.py            Typed domain errors with HTTP mapping
├── log.py               Request-correlated logging (no document content)
├── ingestion/           upload validation, dataset assembly, dedupe, quality report
├── parsing/             PDF/DOCX extraction, cleaning, section detection, PII, OCR policy
├── skills/              taxonomy, alias normalisation, PhraseMatcher extraction
├── jobs/                requirement parsing, job normalisation/import
├── embeddings/          Phase 2 - model backends, batching, cache, metadata
├── retrieval/           Phase 2 - TF-IDF, FAISS store, semantic retriever, reranker
├── matching/            Phase 2/3 - skill/experience matchers, hybrid scorer, pipeline, explainer
├── evaluation/          Phase 3 - splits, metrics, benchmark, error analysis, fairness
├── storage/             Phase 4 - SQLAlchemy models, repositories, migrations
├── monitoring/          Phase 4 - metrics, health, timings
└── utils/               text normalisation, IDs, timing
```

Dependency rule: `parsing` and `jobs` depend on `schemas`, `skills`, `utils`, `config`.
They must not import `embeddings`, `retrieval`, `matching`, or `storage`.

## 4. Ingestion and parsing design

- **Uploads are validated before use**: extension allow-list, size cap, magic bytes, DOCX ZIP
  member/size limits. Bytes stay in memory (`BytesIO`); no temp paths, so no path traversal.
- **PDF**: PyMuPDF block extraction. Two-column pages are detected by a vertical gutter and
  emitted header → left column → right column. Ambiguous geometry falls back to y-order.
  Running footers are excluded from column detection and removed during cleaning.
- **DOCX**: body children are walked in document order so paragraphs and tables stay in
  context; heading styles are passed to section detection as forced headings.
- **Cleaning**: unicode/ligature normalisation, bullet normalisation, repeated header/footer
  removal, consecutive-line dedupe, page-artifact removal.
- **Sections**: alias table + heading heuristics + DOCX styles, with character offsets.
- **Skills**: spaCy blank pipeline + PhraseMatcher (no model download), case-sensitive ORTH
  matcher for ambiguous one-word skills, regex fallback, evidence sentence + offsets.
- **Quality**: heuristic score and warnings; low-text documents are `FAILED`, not silently
  accepted.

## 5. Job ingestion design

- Sources: manual payload, JSON file, CSV file, unstructured text.
- Explicit required/preferred fields are authoritative.
- Unstructured postings: required only from explicit requirement language
  ("required", "must", "essential"); narrative mentions become **preferred** with a warning.
- Experience ranges are parsed only when stated; seniority/work arrangement are inferred only
  when absent, and every inference is recorded as a validation warning.

## 6. Storage strategy

- Phase 1 writes processed corpora as JSONL (`data/processed/`), keeping Phase 1 dependency-free.
- Phase 4 adds SQLAlchemy models with SQLite for local development and PostgreSQL for the
  Compose deployment. Content SHA-256 and job content hashes are unique keys for dedupe.
- Raw uploads are not persisted. Parsed text retention is configurable (default 24h) and
  user deletion removes resume rows, sections, skills and match rows via cascade.

## 7. Retrieval and scoring (Phase 2 target)

```text
resume ─┬─► whole-document embedding ─┐
        ├─► section embeddings ───────┤
        └─► canonical skills ─────────┤
                                      ├─► FAISS / TF-IDF candidates (top-K)
jobs ───┴─► job embeddings ───────────┘            │
                                                   ▼
              hybrid score = w1·semantic + w2·section + w3·required + w4·preferred + w5·experience
                                                   │
                                                   ▼
                                optional cross-encoder rerank (top 20-50)
```

All components are normalised to [0, 1] before weighting; weights are configuration, and the
selected weights are frozen before the held-out test evaluation.

## 8. Error handling and degradation

| Failure | Behaviour |
| --- | --- |
| Corrupt PDF/DOCX | `CorruptDocumentError` → HTTP 422 with code, no stack trace |
| Scanned/empty PDF | Parsed document with `FAILED` status + warning (API rejects for matching) |
| Unsupported type / oversize | Validation error before parsing (400/413) |
| Embedding model unavailable | `ModelUnavailableError`; LSA fallback is opt-in, never silent |
| FAISS index missing | `IndexNotBuiltError`; API returns 503 with remediation |
| No relevant jobs | Empty ranked list with explanation, not an error |
| External instruction text inside a resume | Treated as data; never executed or followed |

## 9. Configuration and versioning

- `configs/default.yaml` holds weights, limits and model choices; environment variables
  override deployment values.
- `config_version`, embedding model ID, index version and parser version are persisted with
  outputs so a ranking can be reproduced.
- Retrieval indexes are rebuildable from stored job records; FAISS vector positions are never
  treated as job identifiers.

## 10. Security and privacy boundaries

- No external AI service is called with resume content.
- Logs carry request IDs and counts, never document text or PII values.
- Resume content is untrusted; section/skill extraction treats instructions as text.
- API responses include only what the requesting session owns (Phase 4).
- Uploaded files never enter Git; `.gitignore` excludes private data and artifacts.

## 11. Deployment topology (Phase 4 target)

```text
docker compose
├── api        FastAPI + models/index mounted at /app/artifacts
├── frontend   Streamlit, talks to api over the compose network
├── db         PostgreSQL 16 with a named volume
└── (optional) reverse proxy / TLS terminator
```

CPU-first. Model cache and FAISS index live on a volume so containers stay stateless.

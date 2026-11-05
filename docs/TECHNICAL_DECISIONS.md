# TalentLens - Technical Decision Records

Format: context → decision → consequences. Status is `accepted` unless stated otherwise.

---

## ADR-001 - Synthetic corpus instead of scraped/Kaggle resumes

**Context.** Real resumes contain personal data and cannot be committed. Public Kaggle resume
datasets have unclear provenance and their categories are not relevance labels. Downloading
them at build time would make the project non-reproducible offline.

**Decision.** Author a synthetic corpus (14 resumes, 23 jobs) covering the structural cases the
parser must handle, with fictional PII. Investigate public taxonomies (ESCO/O*NET) as
references only. Document the choice and its limitations prominently.

**Consequences.** Fully reproducible, privacy-safe, commit-friendly. Matching quality measured on
synthetic documents cannot be generalised to real hiring data; every report says so. A
production rollout must re-validate on consented, lawfully obtained data.

---

## ADR-002 - `src/talentlens` layout with `src` on `pythonpath`

**Context.** The brief suggests top-level `src/ingestion`, etc. A flat namespace creates import
collisions (`jobs`, `parsing`) and makes packaging fragile.

**Decision.** Use a single installable package `talentlens` under `src/`, with the requested
subpackages inside it. Configure pytest `pythonpath = ["src"]`.

**Consequences.** Clean imports and packaging; the directory structure still mirrors the brief.
No global install is required for tests or scripts.

---

## ADR-003 - PyMuPDF for PDF text, with column-aware block ordering

**Context.** Resumes frequently use two-column layouts. Naive text extraction interleaves the
columns and destroys section structure, which directly harms skill attribution and matching.

**Decision.** Use PyMuPDF block extraction. Detect a vertical gutter from block x-coordinates,
score candidates by block balance, and emit full-width header blocks, then the left column,
then the right. If geometry is ambiguous, fall back to y-order rather than guessing.

**Consequences.** Two-column and table layouts parse correctly on the corpus. Column detection
is heuristic; a three-column or magazine layout may fall back to y-order and lose structure.
This is documented and produces a warning only when structure looks broken.

---

## ADR-004 - spaCy `PhraseMatcher` on a blank pipeline

**Context.** Skill extraction must be reproducible offline and must not require a large spaCy
model download.

**Decision.** Use `spacy.blank("en")` + two `PhraseMatcher`s: `LOWER` for normal skills and
`ORTH` for case-sensitive, single-token skills (C, R, Go, BERT, FAISS, ...). Provide a regex
fallback if spaCy is unavailable.

**Consequences.** No model download, deterministic output, and control over false positives
(`go to market`, `R and D`). It is phrase matching, not contextual understanding: a mention is
evidence of mention, not proficiency. Singletons like `R` additionally require list context
outside a skills section.

---

## ADR-005 - Strict, versioned skill taxonomy with conservative related credit

**Context.** Alias merging is where skill extractors usually over-merge (e.g. treating
TensorFlow and PyTorch as the same skill).

**Decision.** Author `configs/skills_taxonomy.yaml` (214 canonical skills, 15 categories,
versioned). Reject ambiguous aliases at load time. Represent transferable but distinct tools in
an explicit `related` map with partial credit (e.g. PyTorch↔TensorFlow 0.5). Never merge
canonical skills.

**Consequences.** Deterministic normalisation and testable ambiguity behaviour. The taxonomy is
hand-curated and will miss niche skills; unknown skills are not silently invented.

---

## ADR-006 - Required vs preferred is a data property, not a heuristic guess

**Context.** Job postings state mandatory and optional requirements differently. Treating all
mentions as required would punish candidates unfairly.

**Decision.** Structured postings use their explicit fields. For unstructured text, only
statements containing explicit requirement language ("required", "must", "essential") become
required; narrative mentions become preferred with a recorded warning. Conflicts resolve to
required, with a warning.

**Consequences.** Required coverage is conservative for messy postings. This is intentional:
under-claiming a requirement is safer than over-claiming one.

---

## ADR-007 - Uploads processed in memory; no temp files

**Context.** Writing uploads to disk introduces path-traversal, cleanup and leak risks.

**Decision.** Validate bytes, parse from `BytesIO`, never write raw uploads. Enforce extension,
size, magic bytes and DOCX ZIP limits before parsing.

**Consequences.** Simpler privacy story and no temp-file cleanup. Very large files are bounded by
configuration rather than disk. Phase 4 persists only parsed text (redactable, retention-bound),
not the original binary.

---

## ADR-008 - Low-text documents fail visibly

**Context.** A scanned PDF can yield only a footer. Returning an empty resume as "success"
produces meaningless recommendations.

**Decision.** Compute a transparent extraction-quality score; mark documents with almost no body
text as `FAILED` with a warning. OCR is opt-in and records mean confidence; if OCR is requested
but unavailable, the warning says so.

**Consequences.** Users see an actionable failure instead of silent nonsense. Quality scoring is
heuristic and must not be presented as a probability of correctness.

---

## ADR-009 - Evidence offsets are part of the schema from day one

**Context.** Explanations must cite real resume text, not text generated from a score.

**Decision.** Section spans and skill mentions carry character offsets; evidence sentences are
stored alongside. Parsing tests assert that offsets slice the original text correctly.

**Consequences.** Explanations can be verified mechanically in Phase 3. Offsets refer to the
cleaned text, so callers must use `ResumeDocument.full_text` (not the original file) to resolve
them. This is documented.

---

## ADR-010 - JSONL processed datasets in Phase 1, SQL in Phase 4

**Context.** The brief forbids database work in Phase 1 but requires validated stored records.

**Decision.** Write validated `ResumeDocument`/`JobPosting` records to JSONL, with schema
validation on read. Add SQLAlchemy/PostgreSQL in Phase 4 without changing the schemas.

**Consequences.** Phase 1 stays lightweight and testable. Phase 4 must handle migrations and
retention, and must not duplicate the schema definitions.

---

## ADR-011 - CPU-first embedding strategy

**Context.** Deployment must be practical; GPU hosting is expensive and was not measured.

**Decision.** Default to small sentence-transformer models on CPU (`all-MiniLM-L6-v2` and
`bge-small-en-v1.5` are both benchmarked), with caching and batching. Provision an LSA fallback
only as an explicit, labelled degradation.

**Consequences.** Predictable cost and no GPU dependency. Latency is higher than GPU; measured
numbers go in the Phase 2 report. The fallback must never masquerade as the transformer model.

---

## ADR-012 - Scores are relevance, not hiring probability

**Context.** A numeric match score invites over-interpretation.

**Decision.** Use "matching score" / "relevance score" everywhere in code, UI and docs. Never
calibrate or label it as a probability of being hired. Document the formula and weights in the
UI and in `docs/MATCHING_METHODOLOGY.md`.

**Consequences.** Slightly more explanation for users, but no false precision. Fairness review
focuses on score invariance rather than "fairness through unawareness" claims.

---

## ADR-013 - Exact FAISS search with an explicit job-ID map

**Context.** Phase 2 must provide vector retrieval, stable IDs, persistence and duplicate
protection without introducing approximation error or making vector positions into identifiers.

**Decision.** Use `IndexFlatIP` inside `IndexIDMap2` with L2-normalised vectors. Maintain and
persist an explicit integer-ID -> job-ID map, plus content hashes and a version derived from the
model, index type, sorted job IDs and hashes. Reject duplicate IDs/hashes and mismatched versions.
A NumPy exact backend is allowed only when FAISS is unavailable and is labelled as such.

**Consequences.** Exact and reproducible at the 23-job scale; no recall loss from ANN. At much
larger scale, exact search and full-corpus filtered scans need a measured ANN/pre-filtering
decision. The index is disposable and rebuildable from job records.

---

## ADR-014 - `all-MiniLM-L6-v2` remains the default after validation benchmark

**Context.** Both `all-MiniLM-L6-v2` and `bge-small-en-v1.5` were available locally and needed a
measured comparison on quality, latency and footprint.

**Decision.** Keep MiniLM as the default. On the validation split it scored NDCG@10 0.9834 vs
BGE 0.9929, but it encoded 1.8x faster and is smaller. BGE stays selectable through configuration
and `scripts/build_index.py --model`.

**Consequences.** The default favours CPU latency. The quality difference is small and measured
on only 30 judged pairs, so it is not treated as a general advantage. TF-IDF slightly exceeded
both on this split; Phase 3 must test semantic value on held-out data rather than assume it.

---

## ADR-015 - Hybrid weights stay experimental until Phase 3 (superseded by ADR-021)

**Context.** The five-component weights must be documented but cannot be presented as validated
before the evaluation framework exists.

**Decision.** Ship `0.30 semantic / 0.15 section / 0.33 required / 0.07 preferred / 0.15
experience` as experimental defaults. Enforce non-negative weights summing to 1.0. Select final
weights on validation in Phase 3, freeze them, and run the held-out test once.

**Consequences.** Rankings are transparent and reproducible now. Any change to weights changes
the config version; test results cannot be used for tuning.

---

## ADR-016 - Cross-encoder reranking is optional and off by default

**Context.** A reranker is commonly assumed to improve ranking, but that must be measured on this
domain and latency budget.

**Decision.** Implement `cross-encoder/ms-marco-MiniLM-L-6-v2` as an opt-in component. On the
validation split it reduced NDCG@10 from 1.0000 to 0.9416 and added ~461 ms per 23-pair rerank
(warm), so `matching.reranker.enabled` remains `false`. A lexical fallback is available but is
always labelled `degraded=True`.

**Consequences.** The default path is faster and measured-better on validation. The negative
result is documented rather than hidden. Only one reranker model and a small synthetic set were
tested; this is not a general claim that reranking never helps.

---

## ADR-017 - Section-aware relevance excludes header and education

**Context.** Whole-document similarity can let names, contact details or institutional prestige
influence the score even when those fields are not competence signals.

**Decision.** Build the resume query from summary, skills, experience and projects. For section
relevance, use summary, skills, experience, projects and certifications; exclude header and
education. Education remains visible to users but is not scored. Location and work arrangement
are user filters only.

**Consequences.** Less proxy leakage from identity and prestige. Section relevance is coarser than
sentence-level evidence; Phase 3 adds traceable sentence evidence. The fallback query for a
document with no detected sections uses full text and must be re-checked in the privacy review.

---

## ADR-018 - Neutral values for absent requirement information

**Context.** A posting with no listed required skills or no experience range should not award a
free perfect score, and a resume with undated experience should not be treated as zero years.

**Decision.** Use neutral coverage 0.50 for absent required/preferred sets, 0.60 for an absent
experience requirement, and 0.50 (insufficient information) for undated experience. Report the
reason in the response notes. Missing skills are "not evidenced in this document", never proof
that the candidate lacks them.

**Consequences.** Scores are conservative for underspecified postings and resumes. The values are
configuration, not empirical estimates, and are revisited with the evaluation framework.

---

## ADR-019 - Sentence evidence is selected above an explicit similarity floor

**Context.** A scored component can be explained from the formula, but a formula is not evidence
that the resume contains the claimed experience. The product promises citations.

**Decision.** Extract candidate sentences from scored sections, exclude header/education, embed
them once per resume, and select up to three above a configurable cosine floor (default 0.30),
preferring section diversity. If no sentence passes, return an empty list and an explicit note.
The threshold is a presentation guard, not a claim of entailment.

**Consequences.** Every displayed citation is real resume text with an optional offset. Some
genuine matches may show no evidence when morphology or section detection is poor; that is
preferable to fabricated support and is visible to the user.

---

## ADR-020 - Unjudged jobs are excluded from ranking metrics

**Context.** The annotation set covers 10 selected jobs per resume, not all 23. Treating an
unannotated job as irrelevant would make metrics depend on annotation coverage.

**Decision.** Remove unjudged jobs before P@K, R@K, NDCG and MRR. Record the protocol alongside
every result. Use grouped, resume-level dev/validation/test splits and validate that no resume
leaks across splits.

**Consequences.** Metrics compare rankings only over judged pairs. The P@K denominator is
`min(K, judged)`; recall is relative to judged relevant jobs. This is a defensible small-set
protocol, but it cannot estimate recall over the full corpus.

---

## ADR-021 - Weights were frozen despite a validation tie

**Context.** All six candidate weight sets reached NDCG@10 1.0000 on the 30-pair validation
split. Picking the maximum would be arbitrary and would overfit a near-ceiling metric.

**Decision.** Adopt a candidate only if NDCG@10 improves by more than 0.005. None did, so the
documented defaults (0.30/0.15/0.33/0.07/0.15) were frozen. The test split was then run once.

**Consequences.** The weights are not empirically optimal; they are a transparent, untuned
default. Future changes require a new frozen configuration and a new documented test run.

---

## ADR-022 - Session-scoped access instead of v1 authentication

**Context.** The product brief requires resume privacy and deletion but does not require user
accounts. Adding full authentication would expand scope and create credential-handling risk.

**Decision.** Issue a random, HttpOnly, SameSite=Lax cookie on upload. Store only its SHA-256
hash. Scope every resume query by that session. Reject foreign-origin state changes. Document
that this is not multi-user authentication and must be replaced before a multi-tenant launch.

**Consequences.** Cross-session access is prevented in tests without inventing an account
system. A stolen cookie is a bearer token; TLS, retention and a real auth layer are production
requirements. Streamlit keeps the cookie server-side in its own session state.

---

## ADR-023 - Parsed JSON in SQLAlchemy; raw uploads never persisted

**Context.** Phase 1 used JSONL; Phase 4 needs deletion, session scoping and retention without
rewriting the validated schemas.

**Decision.** Store the validated `ResumeDocument` JSON in a `resumes` row, tied to a session and
an expiry, with cascading `match_runs`. Use SQLite locally and PostgreSQL in Compose. Never store
the uploaded binary. Purge expired sessions/resumes at startup and on demand.

**Consequences.** Schemas remain authoritative and deletion is a single cascade. There is no
built-in scheduler, so production needs a purge job. JSON documents are less queryable than
normalised skill rows; that trade-off is acceptable for the v1 retrieval path.

---

## ADR-024 - Docker Compose is configuration-only until actually executed

**Context.** The brief requests Docker/Compose, but the development host did not have Docker
available.

**Decision.** Ship an explicit Dockerfile, Compose stack, bootstrap script and deployment guide,
but do not claim the stack was verified. Report the limitation in status, Phase 4 report and
known limitations. Keep local path verification separate.

**Consequences.** Reviewers can run the stack, but container startup, PostgreSQL persistence and
health checks remain unverified here. A future run must record the actual command and output.

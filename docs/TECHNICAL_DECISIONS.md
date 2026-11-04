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

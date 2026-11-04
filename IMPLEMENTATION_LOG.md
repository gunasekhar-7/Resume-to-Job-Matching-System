# Implementation Log

Chronological record of what was built, what was measured, and what failed first.

---

## 2026-11-04 - Phase 1

### Environment and scaffolding
- Inspected the workspace: empty except `.freebuff/`; initialised Git.
- Verified Python 3.11.7 and installed packages; installed `faiss-cpu==1.15.1`.
- Confirmed HuggingFace reachability and that `all-MiniLM-L6-v2` and `bge-small-en-v1.5` are
  already cached locally (used in Phase 2).
- Created config (`configs/default.yaml`), typed schemas, domain errors, request-scoped logging,
  text/ID/timing utilities, and packaging/test configuration.

### Synthetic corpus
- Authored 14 resumes and 23 job postings, including two-column, table-based, fresher,
  career-change and unstructured-posting cases.
- Generated real PDF, DOCX and TXT files with `fpdf2`/`python-docx`; added corrupt, empty and
  image-only fixtures.
- Added `manifest.json` with IDs and content hashes.

### Parsing
- Implemented PyMuPDF block extraction, DOCX body-order extraction, cleaning, section detection,
  PII detection, extraction-quality scoring and the resume parser.
- First PDF run: two-column pages interleaved. Diagnosed by printing block coordinates; added
  gutter detection with balance scoring. A second bug returned the gutter *width* instead of the
  right-column x, which made wide left-column lines look like full-width blocks; fixed and
  covered by a direct unit test.
- Running footers initially prevented gutter detection; excluded margin blocks and added
  running-footer removal during cleaning.
- Empty/scanned PDFs yielded 52 footer characters; added low-text detection so they fail with a
  warning instead of producing an empty resume.

### Skills
- Authored a 214-skill taxonomy (15 categories) with alias normalisation and a conservative
  related-credit map.
- Implemented dual spaCy PhraseMatchers (`LOWER` + `ORTH`), overlap resolution, section and
  sentence evidence, and offsets.
- Fixed `R` matching prose ("R and D") by restricting single-letter matches to skills sections or
  list-like context.

### Jobs
- Implemented requirement splitting, experience-range parsing, seniority/work-arrangement
  inference, and JSON/CSV/manual/text import.
- Fixed an unstructured-posting gap: narrative skills were dropped when a required statement
  existed; they are now recorded as preferred with a warning.
- Fixed a false report claim: the repeat-import check originally used a fresh importer, so it
  could not detect duplicates. It now re-imports into the same importer and reports 23 prevented
  duplicates.

### Verification
- `python scripts/build_sample_data.py --force` -> 26 resume files, 23 jobs, 4 fixtures.
- `python scripts/ingest_resumes.py` -> 26/26 parsed, 14 unique, 0 failures, avg quality 0.961.
- `python scripts/ingest_jobs.py` -> 23/23 imported, 108 required / 94 preferred, 0 rejected.
- `python -m pytest tests -q` -> 60 passed.
- `python -m ruff check src tests scripts` -> clean after fixes.

### Issues found and resolved
| Issue | Resolution |
| --- | --- |
| Inline bullet characters corrupted words | Bullet glyphs removed from global replacements; handled per line |
| Sentence splitting skipped lines just under 60 chars | Always split, with abbreviation protection |
| Two-column reading order interleaved | Gutter detection with balance scoring and correct right-column edge |
| Footer created a phantom gutter | Margin blocks excluded from column detection |
| `max_size_mb=0` ignored | Explicit `None` check |
| `SVM: {}` invalid taxonomy reference | Removed |
| `R` matched prose | Single-letter context guard tightened |
| Duplicate-import check was ineffective | Same-importer re-import, report corrected |

---

## 2026-11-04 - Phase 2 (starting)

- Next: embedding benchmark, FAISS, hybrid scoring, tests, and completion report.

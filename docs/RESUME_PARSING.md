# Resume Parsing

**Version:** 1.0
**Last updated:** 2026-11-04

## 1. Pipeline

```text
validate_upload → format dispatch → extract (PDF blocks / DOCX body) → clean pages
→ detect sections (offsets) → extract skills (offsets + evidence) → PII scan
→ quality assessment → ResumeDocument
```

Entry points: `talentlens.parsing.parse_upload`, `parse_file`, `parse_bytes`.
Every upload is validated first (extension, size, magic bytes, DOCX ZIP limits).

## 2. PDF extraction

- Library: PyMuPDF (`pymupdf`).
- Text is read as blocks, not as a single page stream, so geometry is available.
- Running footers/headers are excluded from column detection (content area only).
- **Column detection**: candidate gutters are x-gaps between block starts wider than 12% of the
  page, with at least four blocks left and three right, no left block crossing into the right
  column, and vertical overlap between columns. Candidates are scored by the smaller side's
  block count. Chosen output order: full-width header blocks, left column, right column.
- If geometry is ambiguous, the extractor falls back to y-order and does not fabricate a
  reading order.
- Password-protected PDFs raise `ParsingError`. Corrupt files raise `CorruptDocumentError`.
- Page limit (default 20) is enforced with a warning.

Known limitation: the heuristic assumes at most two columns. A three-column or magazine layout
will fall back to y-order.

## 3. DOCX extraction

- Library: `python-docx`.
- The body is walked in document order (`w:p`, `w:tbl`) so tables stay in context.
- Table cells are emitted as separate lines; table rows do not collapse into a single line.
- Paragraph styles starting with `Heading`/`Title` are passed to section detection as forced
  headings, making detection independent of casing.
- List-style paragraphs get `- ` prefixes so bullet context is preserved.
- ZIP validation limits member count (2,000) and uncompressed size (50 MB).

## 4. Cleaning

1. Unicode NFKC, ligature and smart-quote normalisation.
2. Bullet normalisation (leading glyphs → `- `; inline glyphs → `, `).
3. Repeated header/footer removal across pages (fingerprint ignores digits).
4. Running footer and page-number removal (`Page 2`, `Confidential | Page 2`).
5. Consecutive duplicate line removal, excessive blank-line collapse, control-character removal.

## 5. Section detection

Alias table covering summary/profile/objective, skills/core competencies/tech stack, experience/
work history/employment, projects, education, certifications, publications, additional info.
Heading rules:

- exact alias match on a short standalone line (case-insensitive, `&` → `and`);
- DOCX heading styles (forced headings);
- combined headings (`Education & Certifications`) map to the first known part with a warning;
- otherwise a heading must be ALL CAPS, 2-4 words, no digits, no commas, and followed by bullets.

Header content before the first heading becomes the `header` section. If no headings are found,
a fallback split puts contact-like lines in `header` and the remainder in `other`, with a warning.

Every span stores `start_char`/`end_char` into `ResumeDocument.full_text`; tests assert
`full_text[start:end] == span.text`.

## 6. Extraction quality and failure policy

`extraction_quality` is a transparent heuristic: character volume, word volume, alphabetic
ratio, line diversity, section coverage, and a per-page word-density penalty. It is **not** a
probability.

A document is `FAILED` when it has almost no body text (< 120 chars, < 20 words, or fewer than
three content lines). This catches image-only PDFs that yield only a footer. Scanned documents
with OCR disabled therefore fail visibly; enabling OCR records mean word confidence and a
warning.

Statuses:

| Status | Meaning |
| --- | --- |
| `success` | Parsed with no warnings |
| `partial` | Parsed, but warnings exist (missing sections, low quality, combined headings) |
| `failed` | No usable text (scanned/empty/corrupt → typed error for corrupt) |

## 7. Measured results (synthetic corpus, 2026-11-04)

Command: `python scripts/ingest_resumes.py`

- 26 files attempted, 26 parsed, 0 failed; 14 unique resumes after 12 format-variant duplicates.
- All 14 records returned `success`; average extraction quality 0.961.
- Section coverage: summary 100%, skills 100%, experience 100%, education 100%; projects 100%;
  certifications 42.9%; publications 21.4% (only resumes that actually have them).
- Fixtures: corrupt PDF rejected (`corrupt_document`); empty and image-only PDFs failed with
  `low_text`; `.exe` rejected (`unsupported_file_type`).

## 8. Privacy

- PII detection covers emails, phone numbers, profile URLs and URLs; only entity types are
  stored in metadata, never values.
- Name detection is not attempted with regex heuristics; Presidio is optional and off by default.
- Raw uploads are not written to disk in this phase.
- Resume content is untrusted: instructions inside a document are treated as text and never
  executed.

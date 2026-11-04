# Dataset Card - TalentLens

**Version:** 1.0
**Last updated:** 2026-11-04

## 1. What is in this repository

| Dataset | Location | Size | Origin |
| --- | --- | --- | --- |
| Synthetic resume corpus | `data/sample/resumes/` | 14 resumes, 26 files (PDF/DOCX) | Authored for this project |
| Synthetic job corpus | `data/sample/jobs/` | 23 postings (JSON + CSV) | Authored for this project |
| Error fixtures | `data/sample/fixtures/` | 4 files | Generated for failure testing |
| Relevance annotations | `data/annotations/relevance_labels.jsonl` | 140 pairs | Single annotator (developer) |
| Annotation template | `data/annotations/annotation_template.csv` | header + examples | Authored for this project |
| Processed corpora | `data/processed/` | JSONL, regenerated | Derived from the above |

**No real person's resume, contact detail, or employer data is included.** All names, emails,
phone numbers, companies and URLs are fictional. Emails use `example.com`; phone numbers use
reserved/fictional ranges.

## 2. Provenance investigation

### Kaggle resume datasets
Common public resume datasets are category-labelled (e.g. "Data Science", "Java Developer") and
are widely used for classification demos. They were **not** used here because:

- licence and consent provenance are frequently unclear or unverifiable;
- the category label describes the resume, not the relevance of a specific resume-job pair;
- committing or redistributing personal documents is inappropriate for a public repository.

Category labels must never be treated as ground-truth relevance labels. This is stated in
`docs/ANNOTATION_GUIDELINES.md`.

### ESCO and O*NET
Both were reviewed as conceptual sources for skill categories and aliases:

- **ESCO** (European Commission) publishes occupations, skills and qualifications. Reuse terms
  and attribution requirements apply; no ESCO data files are bundled.
- **O*NET** (U.S. Department of Labor) publishes occupation/skill descriptors. Its terms of use
  apply; no O*NET data files are bundled.

The taxonomy in `configs/skills_taxonomy.yaml` is hand-authored for TalentLens using common
industry terminology and category names inspired by these frameworks. It is not a derivative
database of either.

### Job postings
All 23 postings are synthetic, written to exercise required/preferred separation, experience
ranges and unstructured text. They do not represent live vacancies.

## 3. Corpus composition

### Resumes (14)

| ID | Profile | Layout | Formats | Years (approx.) |
| --- | --- | --- | --- | --- |
| r01 | Senior ML engineer (NLP) | single | PDF, DOCX | 8 |
| r02 | Data analyst | single | PDF, DOCX | 4 |
| r03 | Backend engineer (Python) | single | PDF, DOCX | 6 |
| r04 | Frontend engineer | **two-column** | PDF, DOCX | 5 |
| r05 | Data engineer | single | PDF, DOCX | 6 |
| r06 | NLP research engineer | single | PDF only | 4 |
| r07 | DevOps engineer | single | PDF, DOCX | 7 |
| r08 | Early-career ML engineer | single | PDF, DOCX | 0-1 |
| r09 | BI analyst | **table skills** | PDF, DOCX | 5 |
| r10 | Full-stack engineer | single | PDF, DOCX | 4 |
| r11 | Computer vision engineer | single | PDF only | 5 |
| r12 | MLOps engineer | single | PDF, DOCX | 6 |
| r13 | Career-changing junior analyst | single | PDF, DOCX | 3 (marketing) |
| r14 | Senior data scientist | **two-column** | PDF, DOCX | 7 |

Structural coverage: multiple pages? Not present in v1 (all single page) - recorded as a
limitation. Two-column PDFs and DOCX tables are present. Unusual headings ("Work History",
"Core Competencies", "Selected Projects") are exercised in tests. Empty, corrupt, image-only and
unsupported files are in `fixtures/`.

### Jobs (23)
Includes ML/NLP, data analyst/BI, backend, frontend, data engineering, DevOps/platform, MLOps,
computer vision, LLM applications, fraud, management, QA automation, healthcare and product
analytics roles. `j23` is intentionally unstructured text to exercise requirement extraction.

## 4. Annotation dataset

- 140 resume-job pairs, sampled by role family (not by system scores).
- Relevance scale 0/1/2; each row has a short rationale.
- Distribution: 24 strongly relevant, 50 partially relevant, 66 not relevant.
- Grouped splits: dev = r01-r07, validation = r08-r10, test = r11-r14.
- Single annotator (the developer). No inter-annotator agreement is claimed.

## 5. Intended use

- Regression testing of parsing, skill extraction and ranking.
- Reproducible evaluation of retrieval and hybrid scoring approaches.
- Demonstration of explainability and fairness counterfactuals.

## 6. Prohibited / inappropriate use

- Do not treat the synthetic corpus as representative of the labour market.
- Do not use model outputs from this corpus to make hiring decisions.
- Do not infer demographic fairness from a corpus with no demographic labels.
- Do not redistribute ESCO/O*NET content through this repository.

## 7. Known limitations

1. Synthetic documents are cleaner and more formulaic than real resumes; parser and extraction
   performance will be optimistic.
2. Single annotator and 140 pairs: ranking metrics have wide uncertainty.
3. No scanned documents with OCR enabled (OCR is optional and untested against real scans).
4. English only.
5. Job postings are short relative to real postings, which limits semantic retrieval difficulty.
6. No demographic attributes: fairness can only be tested counterfactually (identity fields),
   not statistically.

## 8. Maintenance

Rebuild all derived data with:

```bash
python scripts/build_sample_data.py --force
python scripts/ingest_resumes.py
python scripts/ingest_jobs.py
```

Any change to the corpus must be reflected in this card, the annotation rationales, and the
Phase 1 quality report.

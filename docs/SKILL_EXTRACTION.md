# Skill Extraction and Normalisation

**Version:** 1.0
**Last updated:** 2026-11-04

## 1. Taxonomy

File: `configs/skills_taxonomy.yaml` (version 1.0.0).

- 214 canonical skills across 15 categories: programming languages, machine learning, deep
  learning, NLP, data engineering, databases/vector stores, cloud, DevOps, backend, frontend,
  testing, data analytics, MLOps, professional skills, domain knowledge.
- Each entry: canonical name, category, aliases, optional `case_sensitive`.
- Aliases are normalised (lowercase, punctuation folded) before indexing.
- **Ambiguous aliases are rejected at load time** rather than resolved by iteration order.
- A separate `related` map grants partial credit for genuinely transferable tools
  (e.g. PyTorch↔TensorFlow 0.5, PostgreSQL↔MySQL 0.4). It never merges canonical skills.

Provenance: hand-authored; ESCO and O*NET were reviewed as conceptual references only. No
taxonomy data files from either source are redistributed.

## 2. Matching implementation

- spaCy blank English pipeline + `PhraseMatcher` (no model download).
- Two matchers:
  - `LOWER` for normal skills and multi-word aliases;
  - `ORTH` for case-sensitive single-token skills (`C`, `R`, `Go`, `Swift`, `BERT`, `FAISS`,
    `spaCy`, `dbt`, `Flask`, `FastAPI`, `pytest`, `Jest`).
- Overlaps resolve longest-first, then highest confidence.
- A regex fallback exists if spaCy is unavailable; it is labelled in tests but not used in the
  verified environment.
- Single-letter skills (`R`, `C`) require a curated skills section or list punctuation around
  the token, preventing `R and D` or prose letters from matching.

## 3. What is stored per mention

| Field | Example |
| --- | --- |
| `original_text` | `"sklearn"` |
| `canonical` | `"Scikit-Learn"` |
| `category` | `"machine_learning"` |
| `section` | `"experience"` |
| `evidence` | `"Built churn models with sklearn and XGBoost."` |
| `start_char` / `end_char` | offsets into cleaned full text |
| `extraction_method` | `phrase_matcher`, `section_list`, `job_requirement` |
| `match_status` | `canonical`, `alias`, `case_sensitive_alias` |
| `confidence` | 1.0 canonical, 0.96 alias, 0.9 case-sensitive alias |

Confidence reflects *matching certainty*, not proficiency. A skill mentioned once in a summary
is not evidence of professional experience with it; the section is preserved so downstream
logic can weight evidence appropriately.

## 4. Normalisation examples

| Input | Canonical |
| --- | --- |
| `JS`, `Javascript` | JavaScript |
| `sklearn`, `scikit learn` | Scikit-Learn |
| `ML`, `Statistical Learning` | Machine Learning |
| `NLP` | Natural Language Processing |
| `Postgres`, `psql` | PostgreSQL |
| `k8s` | Kubernetes |
| `Golang` | Go (case-sensitive canonical) |

## 5. Deliberate non-merges

- PyTorch and TensorFlow remain distinct; only partial related credit (0.5) applies in matching.
- Java and JavaScript are distinct; the alias table avoids short substrings.
- `ML` maps only to Machine Learning, not to MLOps.
- React (frontend) and React Native are not aliased; only React is in the taxonomy.
- "Deep Learning" does not imply "Computer Vision" or "NLP".

## 6. Evaluation

Skill extraction is evaluated against a hand-checked gold set per resume in Phase 3
(precision/recall/F1 and alias-normalisation accuracy). The gold set is stored in
`data/annotations/skill_gold.json` and must not be derived from extractor output.

Current unit coverage (60 tests total, Phase 1):

- alias resolution and case-insensitive matching;
- false-positive guards (`go to market`, `R and D`, `Jacksonville`, `JavaScripters`);
- duplicate canonical mentions;
- section attribution and evidence sentences;
- offsets slicing the original text;
- related-credit behaviour;
- job-requirement phrase extraction.

## 7. Known limitations

1. Phrase matching cannot disambiguate context: "Python" in "Python is not used here" is still
   extracted. Negation is not modelled.
2. The taxonomy is finite and hand-curated; niche or emerging tools are missed.
3. Synonym coverage outside the alias table is absent (no embedding-based skill linking).
4. Multi-word aliases can overlap section headings; deduplication is by span, not semantics.
5. Non-English documents are unsupported.
6. Mention ≠ proficiency, and years-with-skill is not inferred.

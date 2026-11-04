"""Parse the synthetic corpus into a processed dataset and quality report.

Usage:
    python scripts/ingest_resumes.py [--manifest data/sample/manifest.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from talentlens.config import get_config  # noqa: E402
from talentlens.errors import TalentLensError  # noqa: E402
from talentlens.ingestion.dataset import (  # noqa: E402
    ingest_resume_files,
    load_manifest,
    quality_report_markdown,
    sample_corpus_entries,
    write_corpus_jsonl,
)
from talentlens.ingestion.loader import load_path  # noqa: E402
from talentlens.parsing.resume_parser import parse_upload  # noqa: E402


def parse_error_fixtures() -> list[dict[str, str]]:
    """Run the deliberately broken fixtures and record what the system actually does."""
    config = get_config()
    fixture_dir = config.resolve(config.get("paths.sample_dir", "data/sample")) / "fixtures"
    results: list[dict[str, str]] = []
    for path in sorted(fixture_dir.glob("*")):
        if path.is_dir():
            continue
        entry = {"file": path.name, "outcome": "unknown", "code": "", "message": ""}
        try:
            upload = load_path(path)
            document = parse_upload(upload, resume_id=f"fixture_{path.stem}")
            entry["outcome"] = document.metadata.parsing_status.value
            entry["code"] = "low_text" if document.metadata.low_text_warning else "parsed"
            entry["message"] = "; ".join(document.metadata.warnings[:2])
        except TalentLensError as exc:
            entry["outcome"] = "rejected"
            entry["code"] = exc.code
            entry["message"] = exc.message
        except Exception as exc:  # pragma: no cover - defensive
            entry["outcome"] = "error"
            entry["code"] = type(exc).__name__
            entry["message"] = str(exc)
        results.append(entry)
    return results


def main(manifest_path: str | None = None) -> int:
    config = get_config()
    sample_dir = config.resolve(config.get("paths.sample_dir", "data/sample"))
    manifest = load_manifest(manifest_path or sample_dir / "manifest.json")
    entries = sample_corpus_entries(manifest)

    result = ingest_resume_files(entries)
    processed_dir = config.resolve(config.get("paths.processed_dir", "data/processed"))
    reports_dir = config.reports_dir
    processed_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    corpus_path = write_corpus_jsonl(result.documents, processed_dir / "resumes.jsonl")

    fixtures = parse_error_fixtures()
    payload = {
        "corpus": manifest.get("corpus", "synthetic"),
        "stats": result.stats,
        "duplicates": result.duplicates,
        "error_fixtures": fixtures,
        "outputs": {"corpus": str(corpus_path.relative_to(config.project_root))},
    }
    (reports_dir / "phase1_data_quality.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (reports_dir / "PHASE1_DATA_QUALITY.md").write_text(
        quality_report_markdown(result.stats, manifest.get("corpus", "synthetic"))
        + "\n## Deliberately broken fixtures\n\n| File | Outcome | Code | Message |\n| --- | --- | --- | --- |\n"
        + "\n".join(
            f"| {item['file']} | {item['outcome']} | {item['code']} | {item['message']} |" for item in fixtures
        )
        + "\n",
        encoding="utf-8",
    )

    stats = result.stats
    print(f"Attempted: {stats['files_attempted']}  parsed: {stats['files_parsed']}  failed: {stats['files_failed']}")
    print(f"Unique resumes: {stats['unique_resumes']}  duplicates: {stats['duplicates_removed']}")
    print(f"Status: {stats['status_counts']}")
    print(f"Avg quality: {stats['avg_extraction_quality']}  avg skills: {stats['avg_skills_per_resume']}")
    print("Section coverage:", stats["section_coverage_pct"])
    print(f"Corpus: {corpus_path}")
    print(f"Report: {reports_dir / 'PHASE1_DATA_QUALITY.md'}")
    for failure in stats["failed_attempts"]:
        print(f"  FAILED {Path(failure['path']).name}: {failure['error_code']} {failure['error_message']}")
    for item in fixtures:
        print(f"  FIXTURE {item['file']}: {item['outcome']} ({item['code']}) {item['message'][:80]}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest synthetic resumes")
    parser.add_argument("--manifest", default=None)
    args = parser.parse_args()
    raise SystemExit(main(args.manifest))

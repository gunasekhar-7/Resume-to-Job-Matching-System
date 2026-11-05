"""Generate held-out error analysis from actual rankings.

Usage:
    python scripts/error_analysis.py

Uses the test split only and writes reports/phase3_error_analysis.json and
reports/ERROR_ANALYSIS.md. Run this after the held-out evaluation has been frozen.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from talentlens.config import get_config  # noqa: E402
from talentlens.embeddings.embedder import get_embedder  # noqa: E402
from talentlens.evaluation.error_analysis import analyse_rankings, render_markdown  # noqa: E402
from talentlens.evaluation.labels import load_labels, split_labels  # noqa: E402
from talentlens.ingestion.dataset import read_corpus_jsonl, read_jobs_jsonl  # noqa: E402
from talentlens.matching.pipeline import MatchingPipeline  # noqa: E402


def main() -> int:
    config = get_config()
    labels = load_labels(ROOT / "data" / "annotations" / "relevance_labels.jsonl")
    judged = split_labels(labels, "test")
    documents = {
        document.resume_id: document
        for document in read_corpus_jsonl(ROOT / "data" / "processed" / "resumes.jsonl")
        if document.resume_id in judged
    }
    jobs = read_jobs_jsonl(ROOT / "data" / "processed" / "jobs.jsonl")
    pipeline = MatchingPipeline.load(jobs, embedder=get_embedder(), config=config)
    rankings = {}
    for resume_id, document in sorted(documents.items()):
        response = pipeline.match(document, top_k=len(jobs))
        rankings[resume_id] = response.results
    report = analyse_rankings(rankings, judged, pipeline.jobs_by_id(), top_k=10)
    report["split"] = "test"
    report["config_version"] = config.config_version
    report["index_version"] = pipeline.store.version
    destination = ROOT / "reports" / "phase3_error_analysis.json"
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (ROOT / "reports" / "ERROR_ANALYSIS.md").write_text(render_markdown(report), encoding="utf-8")
    print(f"Cases: {len(report['cases'])}; summary: {report['summary']}")
    print(f"Wrote {destination.relative_to(ROOT)} and reports/ERROR_ANALYSIS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

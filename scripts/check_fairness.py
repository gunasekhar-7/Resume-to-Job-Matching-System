"""Run counterfactual fairness checks over the processed corpus.

Usage:
    python scripts/check_fairness.py

Writes reports/phase3_fairness.json. The check changes names, contacts, education
institution and graduation year while preserving professional sections, then verifies
that the top-10 order, scores and score components are unchanged.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from talentlens.config import get_config  # noqa: E402
from talentlens.embeddings.embedder import get_embedder  # noqa: E402
from talentlens.evaluation.fairness import run_counterfactual_fairness  # noqa: E402
from talentlens.ingestion.dataset import read_corpus_jsonl, read_jobs_jsonl  # noqa: E402
from talentlens.matching.pipeline import MatchingPipeline  # noqa: E402


def main() -> int:
    config = get_config()
    documents = read_corpus_jsonl(ROOT / "data" / "processed" / "resumes.jsonl")
    jobs = read_jobs_jsonl(ROOT / "data" / "processed" / "jobs.jsonl")
    pipeline = MatchingPipeline.load(jobs, embedder=get_embedder(), config=config)
    report = run_counterfactual_fairness(pipeline, documents, top_k=10)
    report["model_id"] = pipeline.embedder.model_id
    report["index_version"] = pipeline.store.version
    destination = ROOT / "reports" / "phase3_fairness.json"
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Checks: {report['checks']}; passed: {report['passed']}; failures: {len(report['failures'])}")
    if report["failures"]:
        for failure in report["failures"][:5]:
            print(failure)
        return 1
    print(f"Wrote {destination.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

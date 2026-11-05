"""Select hybrid weights on the validation split only.

Usage:
    python scripts/tune_weights.py

Candidate weight sets are scored with the validation resumes (r08-r10). The held-out
test resumes (r11-r14) are not loaded. If the best candidate does not improve NDCG@10
meaningfully, the documented defaults are retained. The chosen weights are written to
``reports/phase3_weight_tuning.json``; updating ``configs/default.yaml`` is a deliberate
manual step so the freeze is auditable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from talentlens.config import get_config  # noqa: E402
from talentlens.embeddings.embedder import get_embedder  # noqa: E402
from talentlens.evaluation.labels import load_labels, split_labels  # noqa: E402
from talentlens.evaluation.metrics import evaluate_rankings  # noqa: E402
from talentlens.ingestion.dataset import read_corpus_jsonl, read_jobs_jsonl  # noqa: E402
from talentlens.matching.hybrid_scorer import ScoringWeights  # noqa: E402
from talentlens.matching.pipeline import MatchingPipeline  # noqa: E402

CANDIDATES = {
    "default": {"semantic": 0.30, "section_relevance": 0.15, "required_skills": 0.33, "preferred_skills": 0.07, "experience": 0.15},
    "skills_heavy": {"semantic": 0.24, "section_relevance": 0.10, "required_skills": 0.45, "preferred_skills": 0.06, "experience": 0.15},
    "semantic_heavy": {"semantic": 0.45, "section_relevance": 0.15, "required_skills": 0.20, "preferred_skills": 0.05, "experience": 0.15},
    "experience_heavy": {"semantic": 0.25, "section_relevance": 0.10, "required_skills": 0.30, "preferred_skills": 0.05, "experience": 0.30},
    "section_heavy": {"semantic": 0.25, "section_relevance": 0.25, "required_skills": 0.30, "preferred_skills": 0.05, "experience": 0.15},
    "balanced": {"semantic": 0.30, "section_relevance": 0.15, "required_skills": 0.30, "preferred_skills": 0.10, "experience": 0.15},
}


def main() -> int:
    config = get_config()
    labels = load_labels(ROOT / "data" / "annotations" / "relevance_labels.jsonl")
    validation = split_labels(labels, "validation")
    resumes = {
        resume.resume_id: resume
        for resume in read_corpus_jsonl(ROOT / "data" / "processed" / "resumes.jsonl")
        if resume.resume_id in validation
    }
    jobs = read_jobs_jsonl(ROOT / "data" / "processed" / "jobs.jsonl")
    pipeline = MatchingPipeline.load(jobs, embedder=get_embedder(), config=config)

    results = {}
    for name, weights in CANDIDATES.items():
        parsed = ScoringWeights.from_config(weights)
        rankings = {}
        for resume_id, resume in sorted(resumes.items()):
            response = pipeline.match(resume, top_k=len(jobs), weights=parsed)
            rankings[resume_id] = [match.job_id for match in response.results]
        metrics = evaluate_rankings(rankings, validation)
        results[name] = {"weights": weights, "metrics": metrics}

    def rank(name: str):
        aggregate = results[name]["metrics"]["aggregate"]
        return (
            aggregate.get("ndcg@10", 0.0),
            aggregate.get("ndcg@5", 0.0),
            aggregate.get("mrr", 0.0),
            aggregate.get("precision@10", 0.0),
        )

    ordered = sorted(results, key=lambda name: (rank(name), name == "default"), reverse=True)
    best = ordered[0]
    baseline = results["default"]["metrics"]["aggregate"]
    best_metrics = results[best]["metrics"]["aggregate"]
    improved = best_metrics.get("ndcg@10", 0.0) - baseline.get("ndcg@10", 0.0)
    # A difference below 0.005 on 30 judged pairs is not a basis for changing defaults.
    chosen = best if improved > 0.005 else "default"
    payload = {
        "split": "validation (r08-r10); test resumes r11-r14 not loaded",
        "judged_pairs": sum(len(items) for items in validation.values()),
        "candidates": results,
        "best_candidate": best,
        "chosen": chosen,
        "ndcg_gain_over_default": round(improved, 6),
        "decision_rule": "adopt only if NDCG@10 improves by more than 0.005",
        "frozen_weights": results[chosen]["weights"],
        "config_version": config.config_version,
    }
    output = ROOT / "reports" / "phase3_weight_tuning.json"
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"Wrote {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

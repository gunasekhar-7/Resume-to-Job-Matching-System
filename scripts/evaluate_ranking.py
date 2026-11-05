"""Evaluate TF-IDF, semantic, hybrid and hybrid+reranker on a frozen split.

Usage:
    python scripts/evaluate_ranking.py --split validation --output reports/phase3_validation_results.json
    python scripts/evaluate_ranking.py --split test --output reports/phase3_test_results.json

The test split must be run once, after weights are frozen. Unjudged jobs are removed by
the metric layer; they are never treated as false negatives.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from talentlens.config import get_config  # noqa: E402
from talentlens.embeddings.embedder import get_embedder  # noqa: E402
from talentlens.evaluation.labels import load_labels, split_labels  # noqa: E402
from talentlens.evaluation.metrics import evaluate_rankings  # noqa: E402
from talentlens.ingestion.dataset import read_corpus_jsonl, read_jobs_jsonl  # noqa: E402
from talentlens.matching.pipeline import MatchingPipeline  # noqa: E402
from talentlens.retrieval.reranker import CrossEncoderReranker  # noqa: E402

STRATEGIES = ("tfidf", "semantic", "hybrid", "hybrid_rerank")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["validation", "test"], required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    config = get_config()
    labels = load_labels(ROOT / "data" / "annotations" / "relevance_labels.jsonl")
    judged = split_labels(labels, args.split)
    resumes = {
        resume.resume_id: resume
        for resume in read_corpus_jsonl(ROOT / "data" / "processed" / "resumes.jsonl")
        if resume.resume_id in judged
    }
    if len(resumes) != len(judged):
        print(f"Missing resumes for split {args.split}: {sorted(set(judged) - set(resumes))}")
        return 1

    jobs = read_jobs_jsonl(ROOT / "data" / "processed" / "jobs.jsonl")
    pipeline = MatchingPipeline.load(jobs, embedder=get_embedder(), config=config)
    reranker = CrossEncoderReranker(
        str(config.get("matching.reranker.model_name", "cross-encoder/ms-marco-MiniLM-L-6-v2")),
        batch_size=int(config.get("matching.reranker.batch_size", 16)),
        max_length=int(config.get("matching.reranker.max_length", 256)),
        lexical_fallback=False,
    )

    output: dict[str, object] = {
        "generated_by": "scripts/evaluate_ranking.py",
        "split": args.split,
        "resume_ids": sorted(resumes),
        "judged_pairs": sum(len(items) for items in judged.values()),
        "jobs": len(jobs),
        "config_version": config.config_version,
        "index_version": pipeline.store.version,
        "embedding_model": pipeline.embedder.model_id,
        "weights": pipeline.weights,
        "metrics_protocol": (
            "unjudged jobs removed; P@K denominator min(K, judged); graded NDCG; "
            "relevance>=2 for precision/recall/MRR"
        ),
        "systems": {},
    }

    for system in STRATEGIES:
        rankings = {}
        totals: list[float] = []
        reranks: list[float] = []
        strategy = "hybrid" if system == "hybrid_rerank" else system
        for resume_id, resume in sorted(resumes.items()):
            response = pipeline.match(
                resume,
                top_k=len(jobs),
                strategy=strategy,
                rerank=reranker if system == "hybrid_rerank" else None,
            )
            rankings[resume_id] = [match.job_id for match in response.results]
            totals.append(response.timings_ms.get("total_ms", 0.0))
            if system == "hybrid_rerank":
                reranks.append(response.timings_ms.get("rerank_ms", 0.0))
        metrics = evaluate_rankings(rankings, judged)
        output["systems"][system] = {
            **metrics,
            "rankings": rankings,
            "latency_ms": {
                "mean_total": round(statistics.mean(totals), 2),
                "median_total": round(statistics.median(totals), 2),
                "rerank_mean": round(statistics.mean(reranks), 2) if reranks else None,
            },
            "degraded": reranker.degraded if system == "hybrid_rerank" else None,
        }

    destination = Path(args.output)
    if not destination.is_absolute():
        destination = ROOT / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"Split: {args.split}; resumes={len(resumes)}; judged pairs={output['judged_pairs']}")
    print("| System | NDCG@10 | NDCG@5 | P@5 | R@5 | MRR | Mean ms |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for system, result in output["systems"].items():
        aggregate = result["aggregate"]
        print(
            f"| {system} | {aggregate.get('ndcg@10')} | {aggregate.get('ndcg@5')} | "
            f"{aggregate.get('precision@5')} | {aggregate.get('recall@5')} | "
            f"{aggregate.get('mrr')} | {result['latency_ms']['mean_total']} |"
        )
    print(f"Wrote {destination.relative_to(ROOT) if destination.is_relative_to(ROOT) else destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

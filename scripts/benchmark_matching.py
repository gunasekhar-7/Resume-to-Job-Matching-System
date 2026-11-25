"""Measure warm end-to-end matching latency on the locally built index.

Usage:
    python scripts/benchmark_matching.py --runs 8 --documents 4 --top-k 5

This is a host-specific microbenchmark, not a production load test or capacity
claim. It loads the configured embedding backend and the persisted FAISS/TF-IDF
index, warms every document once, then records wall-clock matching time.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from talentlens.config import get_config  # noqa: E402
from talentlens.embeddings.embedder import get_embedder  # noqa: E402
from talentlens.ingestion.dataset import read_corpus_jsonl, read_jobs_jsonl  # noqa: E402
from talentlens.matching.pipeline import MatchingPipeline  # noqa: E402


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--documents", type=int, default=4)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", default="artifacts/benchmark_matching.json")
    args = parser.parse_args()
    if args.runs < 1 or args.documents < 1 or args.top_k < 1:
        parser.error("runs, documents and top-k must be positive")

    config = get_config()
    jobs = read_jobs_jsonl(config.resolve("data/processed/jobs.jsonl"))
    documents = [
        document
        for document in read_corpus_jsonl(config.resolve("data/processed/resumes.jsonl"))
        if document.metadata.parsing_status.value != "failed"
    ][: args.documents]
    if not documents:
        print("No parsed documents available; run the ingestion scripts first.")
        return 1

    pipeline = MatchingPipeline.load(jobs, embedder=get_embedder(), config=config)
    for document in documents:
        pipeline.match(document, top_k=args.top_k)

    samples: list[float] = []
    for _ in range(args.runs):
        for document in documents:
            started = time.perf_counter()
            pipeline.match(document, top_k=args.top_k)
            samples.append((time.perf_counter() - started) * 1000)

    result = {
        "generated_by": "scripts/benchmark_matching.py",
        "embedding_model": pipeline.embedder.model_id,
        "index_version": pipeline.store.version,
        "jobs": len(jobs),
        "documents": [document.resume_id for document in documents],
        "runs": args.runs,
        "top_k": args.top_k,
        "warmup": len(documents),
        "latency_ms": {
            "median": round(statistics.median(samples), 2),
            "mean": round(statistics.mean(samples), 2),
            "p95": round(percentile(samples, 0.95), 2),
            "min": round(min(samples), 2),
            "max": round(max(samples), 2),
            "samples": len(samples),
        },
        "note": "Single-host warm microbenchmark; not a capacity or production SLO claim.",
    }
    destination = Path(args.output)
    if not destination.is_absolute():
        destination = ROOT / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    values = result["latency_ms"]
    print(
        f"Warm match(top_k={args.top_k}): {values['samples']} samples; "
        f"median={values['median']} ms; p95={values['p95']} ms"
    )
    print(f"Wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

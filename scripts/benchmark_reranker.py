"""Compare hybrid ranking with and without the cross-encoder on validation resumes.

Uses only r08-r10 (Phase 1 validation split) and reports metrics over manually
judged jobs. The cross-encoder is optional; a lexical fallback is labelled, not
presented as a cross-encoder result.

Usage:
    python scripts/benchmark_reranker.py
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from talentlens.config import get_config  # noqa: E402
from talentlens.embeddings.embedder import get_embedder  # noqa: E402
from talentlens.ingestion.dataset import read_corpus_jsonl, read_jobs_jsonl  # noqa: E402
from talentlens.matching.pipeline import MatchingPipeline  # noqa: E402
from talentlens.retrieval.reranker import CrossEncoderReranker  # noqa: E402

VALIDATION_RESUME_IDS = ("r08", "r09", "r10")


def _labels() -> dict[str, dict[str, int]]:
    labels: dict[str, dict[str, int]] = {}
    with (ROOT / "data" / "annotations" / "relevance_labels.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                labels.setdefault(record["resume_id"], {})[record["job_id"]] = int(record["relevance"])
    return labels


def _dcg(relevances: list[int]) -> float:
    return sum((2**rel - 1) / math.log2(index + 2) for index, rel in enumerate(relevances))


def _metrics(ranked: list[str], judgements: dict[str, int], k: int = 10) -> dict[str, float]:
    judged = [job_id for job_id in ranked if job_id in judgements]
    relevances = [judgements[job_id] for job_id in judged]
    ideal = sorted(judgements.values(), reverse=True)
    ideal_dcg = _dcg(ideal[:k])
    return {
        f"ndcg@{k}": round(_dcg(relevances[:k]) / ideal_dcg, 4) if ideal_dcg else 0.0,
        "mrr": round(
            next((1.0 / (i + 1) for i, rel in enumerate(relevances) if rel >= 2), 0.0), 4
        ),
        "judged": len(relevances),
    }


def _mean(rows: list[dict[str, float]], key: str) -> float:
    values = [row[key] for row in rows if key in row]
    return round(sum(values) / len(values), 4) if values else 0.0


def main() -> int:
    config = get_config()
    jobs = read_jobs_jsonl(ROOT / "data" / "processed" / "jobs.jsonl")
    resumes = [
        resume
        for resume in read_corpus_jsonl(ROOT / "data" / "processed" / "resumes.jsonl")
        if resume.resume_id in VALIDATION_RESUME_IDS
    ]
    labels = _labels()
    pipeline = MatchingPipeline.load(jobs, embedder=get_embedder(), config=config)
    reranker = CrossEncoderReranker(
        str(config.get("matching.reranker.model_name", "cross-encoder/ms-marco-MiniLM-L-6-v2")),
        batch_size=int(config.get("matching.reranker.batch_size", 16)),
        max_length=int(config.get("matching.reranker.max_length", 256)),
        lexical_fallback=False,
    )

    hybrid_rows: list[dict[str, float]] = []
    reranked_rows: list[dict[str, float]] = []
    rerank_latencies: list[float] = []
    hybrid_latencies: list[float] = []
    examples: dict[str, dict[str, list[str]]] = {}
    for resume in resumes:
        hybrid = pipeline.match(resume, top_k=len(jobs))
        reranked = pipeline.match(resume, top_k=len(jobs), rerank=reranker)
        hybrid_rows.append(_metrics([match.job_id for match in hybrid.results], labels.get(resume.resume_id, {})))
        reranked_rows.append(
            _metrics([match.job_id for match in reranked.results], labels.get(resume.resume_id, {}))
        )
        hybrid_latencies.append(hybrid.timings_ms.get("total_ms", 0.0))
        rerank_latencies.append(reranked.timings_ms.get("rerank_ms", 0.0))
        examples[resume.resume_id] = {
            "hybrid_top5": [match.job_id for match in hybrid.results[:5]],
            "reranked_top5": [match.job_id for match in reranked.results[:5]],
        }

    payload = {
        "generated_by": "scripts/benchmark_reranker.py",
        "split": "validation (r08-r10); held-out test resumes r11-r14 excluded",
        "reranker_model": reranker.model_id,
        "reranker_load_ms": round(reranker.load_ms, 1) if reranker.load_ms else None,
        "degraded": reranker.degraded,
        "degradation_reason": reranker.degradation_reason,
        "latency_ms": {
            "hybrid_total_mean": round(statistics.mean(hybrid_latencies), 1),
            "rerank_mean_including_load": round(statistics.mean(rerank_latencies), 1),
            "rerank_warm_mean": round(statistics.mean(rerank_latencies[1:]), 1)
            if len(rerank_latencies) > 1
            else None,
            "rerank_per_resume": rerank_latencies,
            "rerank_candidates_per_resume": len(jobs),
            "rerank_warm_candidates_per_s": round(
                len(jobs) / (statistics.mean(rerank_latencies[1:]) / 1000), 1
            )
            if len(rerank_latencies) > 1 and statistics.mean(rerank_latencies[1:]) > 0
            else None,
        },
        "hybrid": {
            "ndcg@10": _mean(hybrid_rows, "ndcg@10"),
            "mrr": _mean(hybrid_rows, "mrr"),
            "per_resume": hybrid_rows,
        },
        "hybrid_plus_rerank": {
            "ndcg@10": _mean(reranked_rows, "ndcg@10"),
            "mrr": _mean(reranked_rows, "mrr"),
            "per_resume": reranked_rows,
        },
        "top5_examples": examples,
    }
    output = ROOT / "reports" / "phase2_reranker_benchmark.json"
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"Wrote {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

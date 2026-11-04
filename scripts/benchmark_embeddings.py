"""Benchmark embedding candidates on the validation resumes (r08-r10).

This is a Phase 2 model-selection benchmark, not the final evaluation. It uses
only the validation split from Phase 1 (never the held-out r11-r14 test resumes)
and reports ranking quality on the manually judged pairs, excluding unjudged jobs.

Usage:
    python scripts/benchmark_embeddings.py
    python scripts/benchmark_embeddings.py --models sentence-transformers/all-MiniLM-L6-v2

Outputs ``reports/phase2_embedding_benchmark.json`` and prints a Markdown table.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from talentlens.config import get_config  # noqa: E402
from talentlens.embeddings.embedder import SentenceTransformerEmbedder  # noqa: E402
from talentlens.errors import TalentLensError  # noqa: E402
from talentlens.ingestion.dataset import read_corpus_jsonl, read_jobs_jsonl  # noqa: E402
from talentlens.retrieval.semantic_retriever import document_query_text  # noqa: E402
from talentlens.retrieval.tfidf_retriever import TfidfRetriever  # noqa: E402
from talentlens.utils.timing import Timer  # noqa: E402

DEFAULT_MODELS = (
    "sentence-transformers/all-MiniLM-L6-v2",
    "BAAI/bge-small-en-v1.5",
)
VALIDATION_RESUME_IDS = ("r08", "r09", "r10")
PRIMARY_K = 10


def _load_labels(path: Path) -> dict[str, dict[str, int]]:
    labels: dict[str, dict[str, int]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            labels.setdefault(record["resume_id"], {})[record["job_id"]] = int(record["relevance"])
    return labels


def _dcg(relevances: list[int]) -> float:
    return sum((2**rel - 1) / math.log2(index + 2) for index, rel in enumerate(relevances))


def _ranking_metrics(ranked: list[str], judgements: dict[str, int]) -> dict[str, float]:
    """Metrics over judged jobs only; unjudged jobs never count as false negatives."""
    judged_ranked = [job_id for job_id in ranked if job_id in judgements]
    if not judged_ranked:
        return {}
    relevances = [judgements[job_id] for job_id in judged_ranked]
    ideal = sorted(judgements.values(), reverse=True)

    def ndcg_at(k: int) -> float:
        ideal_dcg = _dcg(ideal[:k])
        return _dcg(relevances[:k]) / ideal_dcg if ideal_dcg else 0.0

    def precision_at(k: int) -> float:
        top = relevances[:k]
        return sum(1 for rel in top if rel >= 2) / k if top else 0.0

    relevant_total = sum(1 for rel in ideal if rel >= 2)
    top5 = relevances[:5]
    recall_at_5 = (
        sum(1 for rel in top5 if rel >= 2) / relevant_total if relevant_total else 0.0
    )
    reciprocal_rank = next(
        (1.0 / (index + 1) for index, rel in enumerate(relevances) if rel >= 2), 0.0
    )
    return {
        f"ndcg@{PRIMARY_K}": ndcg_at(PRIMARY_K),
        "ndcg@5": ndcg_at(5),
        "precision@5": precision_at(5),
        "recall@5": recall_at_5,
        "mrr": reciprocal_rank,
        "judged": len(relevances),
    }


def _rss_mb() -> float:
    try:
        import psutil

        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        return float("nan")


def _model_footprint(embedder: SentenceTransformerEmbedder) -> dict[str, float]:
    model = embedder._ensure_model()
    parameters = sum(parameter.numel() for parameter in model.parameters())
    return {
        "parameters": int(parameters),
        "fp32_weights_mb": round(parameters * 4 / (1024 * 1024), 1),
        "dimension": int(embedder.dimension),
    }


def _benchmark_model(
    model_name: str,
    jobs,
    resumes,
    labels: dict[str, dict[str, int]],
) -> dict:
    config = get_config()
    job_ids = [job.job_id for job in jobs]
    job_texts = [job.searchable_text() for job in jobs]
    resume_texts = [document_query_text(resume) for resume in resumes]

    gc.collect()
    before_mb = _rss_mb()
    embedder = SentenceTransformerEmbedder(
        model_name,
        device=str(config.get("embeddings.device", "cpu")),
        max_seq_length=int(config.get("embeddings.max_seq_length", 256)),
        batch_size=int(config.get("embeddings.batch_size", 32)),
        normalize=True,
        cache_enabled=False,
    )
    load_timer = Timer().start()
    _ = embedder.dimension  # triggers the lazy model load
    process_first_use_ms = load_timer.stop()
    load_ms = embedder.load_latency_ms or process_first_use_ms
    after_mb = _rss_mb()

    encode_timer = Timer().start()
    job_vectors = embedder.encode(job_texts, use_cache=False)
    encode_ms = encode_timer.stop()

    resume_timer = Timer().start()
    resume_vectors = embedder.encode(resume_texts, use_cache=False)
    resume_encode_ms = resume_timer.stop()
    similarity = resume_vectors @ job_vectors.T

    per_resume: dict[str, dict[str, float]] = {}
    for row, resume in enumerate(resumes):
        order = np.argsort(-similarity[row], kind="stable")
        ranked = [job_ids[index] for index in order]
        per_resume[resume.resume_id] = _ranking_metrics(ranked, labels.get(resume.resume_id, {}))

    aggregate = {
        key: round(float(np.mean([metrics[key] for metrics in per_resume.values() if key in metrics])), 4)
        for key in ("ndcg@10", "ndcg@5", "precision@5", "recall@5", "mrr")
    }
    footprint = _model_footprint(embedder)
    result = {
        "model": model_name,
        "backend": embedder.backend,
        "dimension": footprint["dimension"],
        "parameters": footprint["parameters"],
        "fp32_weights_mb": footprint["fp32_weights_mb"],
        "load_ms": round(load_ms, 1),
        "process_first_use_ms": round(process_first_use_ms, 1),
        "job_encode_ms": round(encode_ms, 1),
        "job_encode_per_doc_ms": round(encode_ms / len(job_texts), 2),
        "job_throughput_docs_per_s": round(len(job_texts) / (encode_ms / 1000), 1)
        if encode_ms
        else None,
        "resume_encode_ms": round(resume_encode_ms, 1),
        "peak_rss_delta_mb": round(after_mb - before_mb, 1),
        "validation_resumes": list(VALIDATION_RESUME_IDS),
        "per_resume": {
            resume_id: {key: round(value, 4) for key, value in metrics.items()}
            for resume_id, metrics in per_resume.items()
        },
        **aggregate,
    }
    del embedder
    gc.collect()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        nargs="+",
        default=list(DEFAULT_MODELS),
        help="Sentence-Transformer model names to compare",
    )
    args = parser.parse_args()

    config = get_config()
    jobs = read_jobs_jsonl(ROOT / "data" / "processed" / "jobs.jsonl")
    resumes = [
        resume
        for resume in read_corpus_jsonl(ROOT / "data" / "processed" / "resumes.jsonl")
        if resume.resume_id in VALIDATION_RESUME_IDS
    ]
    labels = _load_labels(ROOT / "data" / "annotations" / "relevance_labels.jsonl")
    if len(resumes) != len(VALIDATION_RESUME_IDS):
        print(f"Expected {len(VALIDATION_RESUME_IDS)} validation resumes, found {len(resumes)}")
        return 1

    results = []
    for model_name in args.models:
        try:
            results.append(_benchmark_model(model_name, jobs, resumes, labels))
        except TalentLensError as exc:
            print(f"SKIPPED {model_name}: {exc}")
        except Exception as exc:  # keep the other candidate measurable
            print(f"FAILED {model_name}: {type(exc).__name__}: {exc}")

    tfidf = TfidfRetriever(config=config).fit({job.job_id: job.searchable_text() for job in jobs})
    tfidf_per_resume = {}
    for resume in resumes:
        hits = tfidf.search(document_query_text(resume), top_k=len(jobs))
        tfidf_per_resume[resume.resume_id] = _ranking_metrics(
            [hit.job_id for hit in hits], labels.get(resume.resume_id, {})
        )
    tfidf_aggregate = {
        key: round(float(np.mean([metrics[key] for metrics in tfidf_per_resume.values() if key in metrics])), 4)
        for key in ("ndcg@10", "ndcg@5", "precision@5", "recall@5", "mrr")
    }
    results.append(
        {
            "model": "tfidf-word-1-2 (reference)",
            "backend": "tfidf",
            "dimension": None,
            "parameters": None,
            "fp32_weights_mb": None,
            "load_ms": None,
            "job_encode_ms": None,
            "job_encode_per_doc_ms": None,
            "job_throughput_docs_per_s": None,
            "peak_rss_delta_mb": None,
            "validation_resumes": list(VALIDATION_RESUME_IDS),
            "per_resume": {
                resume_id: {key: round(value, 4) for key, value in metrics.items()}
                for resume_id, metrics in tfidf_per_resume.items()
            },
            **tfidf_aggregate,
        }
    )

    payload = {
        "generated_by": "scripts/benchmark_embeddings.py",
        "split": "validation (r08-r10); held-out test resumes r11-r14 excluded",
        "judged_jobs_per_resume": len(next(iter(labels.values()))),
        "jobs": len(jobs),
        "config_version": config.config_version,
        "results": results,
    }
    output = ROOT / "reports" / "phase2_embedding_benchmark.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    header = (
        "| Model | NDCG@10 | NDCG@5 | P@5 | R@5 | MRR | Dim | Load ms | "
        "Encode ms/doc | RSS delta MB |"
    )
    print(header)
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for result in results:
        print(
            f"| {result['model']} | {result.get('ndcg@10')} | {result.get('ndcg@5')} | "
            f"{result.get('precision@5')} | {result.get('recall@5')} | {result.get('mrr')} | "
            f"{result.get('dimension') or '-'} | {result.get('load_ms') or '-'} | "
            f"{result.get('job_encode_per_doc_ms') or '-'} | {result.get('peak_rss_delta_mb') or '-'} |"
        )
    print(f"\nWrote {output.relative_to(ROOT)}")
    return 0 if len(results) > 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())

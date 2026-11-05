"""Ranking metrics over judged jobs.

Protocol: unjudged jobs are removed before computing metrics. A job that was never
annotated is not a false negative; counting it as one would make the metric depend on
annotation coverage rather than ranking quality. Precision@K uses K as the denominator
when at least K judged jobs exist, otherwise the number of judged jobs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

DEFAULT_K_VALUES = (1, 3, 5, 10)


def _judged(ranked: Sequence[str], labels: Mapping[str, int]) -> list[str]:
    return [job_id for job_id in ranked if job_id in labels]


def precision_at_k(ranked: Sequence[str], labels: Mapping[str, int], k: int, threshold: int = 2) -> float:
    if k <= 0:
        return 0.0
    judged = _judged(ranked, labels)[:k]
    if not judged:
        return 0.0
    return sum(1 for job_id in judged if labels[job_id] >= threshold) / min(k, len(judged))


def recall_at_k(ranked: Sequence[str], labels: Mapping[str, int], k: int, threshold: int = 2) -> float:
    relevant = sum(1 for relevance in labels.values() if relevance >= threshold)
    if relevant == 0 or k <= 0:
        return 0.0
    judged = _judged(ranked, labels)[:k]
    return sum(1 for job_id in judged if labels[job_id] >= threshold) / relevant


def _dcg(relevances: Sequence[int]) -> float:
    return sum((2**relevance - 1) / math.log2(index + 2) for index, relevance in enumerate(relevances))


def ndcg_at_k(ranked: Sequence[str], labels: Mapping[str, int], k: int) -> float:
    if k <= 0 or not labels:
        return 0.0
    judged = _judged(ranked, labels)[:k]
    relevances = [labels[job_id] for job_id in judged]
    ideal = sorted(labels.values(), reverse=True)[:k]
    ideal_dcg = _dcg(ideal)
    return _dcg(relevances) / ideal_dcg if ideal_dcg else 0.0


def mrr(ranked: Sequence[str], labels: Mapping[str, int], threshold: int = 2) -> float:
    for index, job_id in enumerate(_judged(ranked, labels), start=1):
        if labels[job_id] >= threshold:
            return 1.0 / index
    return 0.0


def evaluate_ranking(
    ranked: Sequence[str],
    labels: Mapping[str, int],
    *,
    k_values: Sequence[int] = DEFAULT_K_VALUES,
    primary_k: int = 10,
    threshold: int = 2,
) -> dict[str, float]:
    metrics: dict[str, float] = {
        "mrr": round(mrr(ranked, labels, threshold), 6),
        "judged": float(len(labels)),
        "retrieved": float(len(_judged(ranked, labels))),
    }
    for k in k_values:
        metrics[f"precision@{k}"] = round(precision_at_k(ranked, labels, k, threshold), 6)
        metrics[f"recall@{k}"] = round(recall_at_k(ranked, labels, k, threshold), 6)
        metrics[f"ndcg@{k}"] = round(ndcg_at_k(ranked, labels, k), 6)
    metrics["primary_k"] = float(primary_k)
    return metrics


def evaluate_rankings(
    rankings: Mapping[str, Sequence[str]],
    labels_by_resume: Mapping[str, Mapping[str, int]],
    *,
    k_values: Sequence[int] = DEFAULT_K_VALUES,
    primary_k: int = 10,
    threshold: int = 2,
) -> dict[str, object]:
    per_resume: dict[str, dict[str, float]] = {}
    for resume_id, ranked in rankings.items():
        labels = labels_by_resume.get(resume_id, {})
        per_resume[resume_id] = evaluate_ranking(
            ranked,
            labels,
            k_values=k_values,
            primary_k=primary_k,
            threshold=threshold,
        )

    aggregate: dict[str, float] = {}
    keys = [
        metric
        for k in k_values
        for metric in (f"ndcg@{k}", f"precision@{k}", f"recall@{k}")
    ] + ["mrr"]
    for key in keys:
        values = [metrics[key] for metrics in per_resume.values() if key in metrics]
        aggregate[key] = round(sum(values) / len(values), 6) if values else 0.0
    return {
        "aggregate": aggregate,
        "per_resume": per_resume,
        "resumes": len(per_resume),
        "judged_pairs": sum(len(labels_by_resume.get(resume_id, {})) for resume_id in rankings),
        "protocol": (
            "unjudged jobs removed before metrics; P@K denominator is min(K, judged jobs); "
            "graded relevance 0/1/2; NDCG uses 2^rel-1"
        ),
    }

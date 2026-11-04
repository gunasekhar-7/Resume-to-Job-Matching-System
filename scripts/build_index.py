"""Build the persisted semantic + TF-IDF index used by matching.

Usage:
    python scripts/build_index.py
    python scripts/build_index.py --model sentence-transformers/bge-small-en-v1.5

The build is deterministic for a fixed job corpus, model and configuration: the
index version is derived from those inputs, and rebuilding overwrites the previous
artifacts. Job records remain the source of truth; the index is disposable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from talentlens.config import get_config  # noqa: E402
from talentlens.embeddings.embedder import get_embedder  # noqa: E402
from talentlens.errors import TalentLensError  # noqa: E402
from talentlens.ingestion.dataset import read_jobs_jsonl  # noqa: E402
from talentlens.jobs.importer import JobImporter  # noqa: E402
from talentlens.log import get_logger  # noqa: E402
from talentlens.matching.pipeline import MatchingPipeline, default_index_dir  # noqa: E402

logger = get_logger("scripts.build_index")


def _load_jobs(path: Path):
    if path.exists():
        return read_jobs_jsonl(path)
    sample = ROOT / "data" / "sample" / "jobs" / "jobs.json"
    logger.warning("Processed jobs missing at %s; importing %s instead", path, sample)
    return JobImporter().import_json(sample)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--jobs",
        default=str(ROOT / "data" / "processed" / "jobs.jsonl"),
        help="Processed job JSONL (default: data/processed/jobs.jsonl)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Sentence-Transformer model name (default: configs/default.yaml)",
    )
    args = parser.parse_args()

    config = get_config()
    jobs_path = Path(args.jobs)
    if not jobs_path.is_absolute():
        jobs_path = ROOT / jobs_path
    jobs = _load_jobs(jobs_path)
    if not jobs:
        logger.error("No job records found at %s", jobs_path)
        return 1

    embedder = get_embedder(model_name=args.model)
    target = default_index_dir(config, embedder.model_id)
    try:
        pipeline = MatchingPipeline.build(
            jobs,
            embedder=embedder,
            config=config,
            artifact_dir=target,
            persist=True,
        )
    except TalentLensError as exc:
        logger.error("Index build failed: %s", exc)
        return 1

    summary = {
        "jobs": len(jobs),
        "index_dir": str(target.relative_to(ROOT)) if target.is_relative_to(ROOT) else str(target),
        "embedding_model": pipeline.embedder.model_id,
        "embedding_dimension": pipeline.embedder.dimension,
        "index_version": pipeline.store.version,
        "index_backend": pipeline.store.backend,
        "tfidf_version": pipeline.tfidf.version,
        "config_version": config.config_version,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

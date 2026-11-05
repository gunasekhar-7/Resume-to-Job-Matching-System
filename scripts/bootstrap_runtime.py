"""Prepare processed data and the matching index for a fresh container.

Usage:
    python scripts/bootstrap_runtime.py

This is idempotent: existing processed files and an existing index are reused. It does
not fabricate data; it runs the same ingestion and index-build commands documented in the
README. The first run may download the sentence-transformer model.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from talentlens.config import get_config  # noqa: E402


def run(script: str) -> None:
    print(f"[bootstrap] running {script}", flush=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT, check=True)


def main() -> int:
    config = get_config()
    processed = config.resolve("data/processed")
    jobs = processed / "jobs.jsonl"
    resumes = processed / "resumes.jsonl"
    if not jobs.exists():
        run("ingest_jobs.py")
    if not resumes.exists():
        run("ingest_resumes.py")

    # The index is disposable; any existing model directory is reused to avoid a
    # needless rebuild and model load on every container start.
    index_root = config.artifacts_dir / "index"
    if not any(index_root.glob("*/index.faiss")):
        run("build_index.py")
    else:
        print("[bootstrap] existing index found; skipping rebuild", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

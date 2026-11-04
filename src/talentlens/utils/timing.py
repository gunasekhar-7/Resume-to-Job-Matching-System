"""Timing helpers used by the pipeline and by evaluation latency reports."""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import numpy as np


class Timer:
    """Measure elapsed wall-clock time in milliseconds."""

    def __init__(self) -> None:
        self._start: float | None = None
        self.elapsed_ms: float = 0.0

    def start(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def stop(self) -> float:
        if self._start is None:
            raise RuntimeError("Timer.stop() called before start()")
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000.0
        return self.elapsed_ms

    def __enter__(self) -> Timer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


@contextmanager
def measure() -> Iterator[dict[str, float]]:
    """``with measure() as result:`` gives ``result["ms"]`` after the block."""
    holder: dict[str, float] = {"ms": 0.0}
    start = time.perf_counter()
    try:
        yield holder
    finally:
        holder["ms"] = (time.perf_counter() - start) * 1000.0


def latency_stats(samples: Sequence[float]) -> dict[str, float]:
    """Return mean/p50/p95/max/min in milliseconds; empty input yields zeros."""
    if not samples:
        return {"count": 0.0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0, "min": 0.0}
    array = np.asarray(samples, dtype=float)
    return {
        "count": float(array.size),
        "mean": float(array.mean()),
        "p50": float(np.percentile(array, 50)),
        "p95": float(np.percentile(array, 95)),
        "max": float(array.max()),
        "min": float(array.min()),
    }

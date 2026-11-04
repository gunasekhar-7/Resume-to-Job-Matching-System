"""Deterministic hash embedder used by unit tests.

It is a lexical bag-of-tokens model with no semantic knowledge. It exists so tests
can exercise the full matching stack without downloading a transformer or requiring
network access; results from it are never used in project reports.
"""

from __future__ import annotations

import hashlib
import re

import numpy as np

from talentlens.embeddings.embedder import Embedder

_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")


class FakeEmbedder(Embedder):
    backend = "fake"

    def __init__(
        self,
        dimension: int = 48,
        *,
        cache_dir=None,
        cache_enabled: bool = False,
    ) -> None:
        super().__init__(
            "fake-hash-v1",
            cache_dir=cache_dir,
            cache_enabled=cache_enabled and cache_dir is not None,
        )
        self._dimension = dimension
        self.calls = 0

    @property
    def dimension(self) -> int:
        return self._dimension

    def _encode(self, texts: list[str], batch_size: int | None) -> np.ndarray:
        self.calls += 1
        vectors = np.zeros((len(texts), self._dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = _TOKEN_RE.findall(text.lower())
            for token in tokens:
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                vectors[row, int.from_bytes(digest, "big") % self._dimension] += 1.0
            for first, second in zip(tokens, tokens[1:], strict=False):
                digest = hashlib.blake2b(
                    f"{first}_{second}".encode(), digest_size=8
                ).digest()
                vectors[row, int.from_bytes(digest, "big") % self._dimension] += 0.5
        return vectors

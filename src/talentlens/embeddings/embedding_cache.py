"""Persistent embedding cache keyed by content hash.

Only SHA-256 digests of prepared text are stored, never the document text itself.
The cache lives under ``artifacts/embeddings/<model-slug>/`` and is safe to delete.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import numpy as np

from talentlens.log import get_logger
from talentlens.utils.text import slugify

logger = get_logger("embeddings.cache")

_MAX_ENTRIES = 20_000


class EmbeddingCache:
    def __init__(self, directory: str | Path, model_id: str) -> None:
        self.directory = Path(directory) / slugify(model_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.model_id = model_id
        self._vectors_path = self.directory / "vectors.npz"
        self._index_path = self.directory / "index.json"
        self._lock = threading.Lock()
        self._keys: list[str] = []
        self._rows: dict[str, int] = {}
        self._vectors: np.ndarray | None = None
        self._dirty = False
        self._load()

    # ------------------------------------------------------------------ storage
    def _load(self) -> None:
        if not (self._vectors_path.exists() and self._index_path.exists()):
            return
        try:
            with np.load(self._vectors_path) as payload:
                self._vectors = payload["vectors"].astype(np.float32)
            self._keys = json.loads(self._index_path.read_text(encoding="utf-8")).get("keys", [])
            self._rows = {key: index for index, key in enumerate(self._keys)}
            if self._vectors.shape[0] != len(self._keys):
                raise ValueError("cache index does not match vector count")
            logger.debug("Loaded %d cached embeddings for %s", len(self._keys), self.model_id)
        except Exception as exc:  # pragma: no cover - corrupt cache is disposable
            logger.warning("Ignoring unreadable embedding cache (%s)", type(exc).__name__)
            self._vectors = None
            self._keys, self._rows = [], {}

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

    def get(self, text: str) -> np.ndarray | None:
        if not text:
            return None
        with self._lock:
            row = self._rows.get(self._key(text))
            if row is None or self._vectors is None:
                return None
            return self._vectors[row].copy()

    def put_many(self, texts: list[str], vectors: np.ndarray) -> None:
        if not texts or vectors.size == 0:
            return
        if len(texts) != vectors.shape[0]:
            raise ValueError("texts and vectors must have the same length")
        with self._lock:
            new_rows: list[np.ndarray] = []
            new_keys: list[str] = []
            for text, vector in zip(texts, vectors, strict=False):
                key = self._key(text)
                if key in self._rows:
                    continue
                self._rows[key] = len(self._keys)
                self._keys.append(key)
                new_keys.append(key)
                new_rows.append(vector.astype(np.float32))
            if not new_rows:
                return
            matrix = np.vstack(new_rows)
            self._vectors = matrix if self._vectors is None else np.vstack([self._vectors, matrix])
            self._dirty = True
            if len(self._keys) > _MAX_ENTRIES:
                self._trim()

    def _trim(self) -> None:
        # Keep the most recent N entries (rows are append-only, so tail is newest).
        keep = _MAX_ENTRIES
        self._keys = self._keys[-keep:]
        self._vectors = self._vectors[-keep:] if self._vectors is not None else None
        self._rows = {key: index for index, key in enumerate(self._keys)}

    def flush(self) -> None:
        with self._lock:
            if not self._dirty or self._vectors is None:
                return
            tmp_vectors = self._vectors_path.with_suffix(".tmp.npz")
            np.savez_compressed(tmp_vectors, vectors=self._vectors)
            tmp_vectors.replace(self._vectors_path)
            tmp_index = self._index_path.with_suffix(".tmp.json")
            tmp_index.write_text(
                json.dumps({"model_id": self.model_id, "keys": self._keys}, indent=0), encoding="utf-8"
            )
            tmp_index.replace(self._index_path)
            self._dirty = False

    @property
    def size(self) -> int:
        return len(self._keys)

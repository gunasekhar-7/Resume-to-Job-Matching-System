"""FAISS vector store with persistent job-ID mapping and index versioning.

Design rules:
* Vector *positions* are never job identifiers. An explicit ``id_map`` maps FAISS
  integer IDs to job IDs, and is persisted with the index.
* The index is rebuildable from stored job records; it is not a source of truth.
* Exact ``IndexFlatIP`` is the default. With tens to low-thousands of jobs, exact
  search is fast and removes approximation error from evaluation.
* If FAISS cannot be imported, ``NumpyFlatStore`` provides the same interface with
  exact inner-product search. The backend is recorded in metadata, never hidden.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from talentlens.config import get_config
from talentlens.errors import DuplicateJobError, IndexLoadError
from talentlens.log import get_logger
from talentlens.schemas import IndexMetadata, utcnow
from talentlens.utils.text import slugify

logger = get_logger("retrieval.faiss")

try:  # pragma: no cover - import availability differs by environment
    import faiss  # type: ignore

    FAISS_AVAILABLE = True
except Exception:  # pragma: no cover
    faiss = None  # type: ignore
    FAISS_AVAILABLE = False


@dataclass(frozen=True)
class SearchHit:
    job_id: str
    score: float
    rank: int


def _normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vectors / norms).astype(np.float32)


class FaissStore:
    def __init__(
        self,
        *,
        vectors: np.ndarray,
        job_ids: Sequence[str],
        model_id: str,
        index_type: str = "flat_ip",
        content_hashes: dict[str, str] | None = None,
        config_version: str | None = None,
        backend: str | None = None,
    ) -> None:
        self._vectors = _normalise(np.asarray(vectors, dtype=np.float32))
        self._job_ids = list(job_ids)
        self.model_id = model_id
        self.index_type = index_type
        self.content_hashes = dict(content_hashes or {})
        self.config_version = config_version or get_config().config_version
        self.backend = backend or ("faiss" if FAISS_AVAILABLE else "numpy")
        self._id_map = dict(enumerate(self._job_ids))
        self._row_by_job = {job_id: position for position, job_id in enumerate(self._job_ids)}
        self._lock = threading.Lock()
        self._index = None
        self._validate()
        if self.backend == "faiss":
            self._build_faiss()

    # ------------------------------------------------------------------ construction
    def _validate(self) -> None:
        if self._vectors.ndim != 2 or self._vectors.shape[0] == 0:
            raise IndexLoadError("Cannot build an index from an empty vector matrix")
        if self._vectors.shape[0] != len(self._job_ids):
            raise IndexLoadError("Vector count does not match job ID count")
        if len(set(self._job_ids)) != len(self._job_ids):
            raise DuplicateJobError("Duplicate job IDs cannot be indexed")
        hashes = [value for value in self.content_hashes.values() if value]
        if len(hashes) != len(set(hashes)):
            raise DuplicateJobError("Duplicate job content hashes cannot be indexed")
        if np.isnan(self._vectors).any() or np.isinf(self._vectors).any():
            raise IndexLoadError("Vectors contain NaN or infinite values")

    def _build_faiss(self) -> None:
        assert faiss is not None
        dimension = int(self._vectors.shape[1])
        if self.index_type not in {"flat_ip", "flat_l2"}:
            raise IndexLoadError(
                f"Unsupported FAISS index type '{self.index_type}'. Supported: flat_ip, flat_l2."
            )
        base = faiss.IndexFlatIP(dimension) if self.index_type == "flat_ip" else faiss.IndexFlatL2(dimension)
        index_class = getattr(faiss, "IndexIDMap2", faiss.IndexIDMap)
        index = index_class(base)
        ids = np.arange(len(self._job_ids), dtype=np.int64)
        index.add_with_ids(self._vectors, ids)
        self._index = index

    # ------------------------------------------------------------------ properties
    @property
    def dimension(self) -> int:
        return int(self._vectors.shape[1])

    @property
    def size(self) -> int:
        return len(self._job_ids)

    @property
    def job_ids(self) -> list[str]:
        return list(self._job_ids)

    @property
    def vectors(self) -> np.ndarray:
        return self._vectors.copy()

    def contains(self, job_id: str) -> bool:
        return job_id in self._row_by_job

    def vector_for(self, job_id: str) -> np.ndarray | None:
        row = self._row_by_job.get(job_id)
        return None if row is None else self._vectors[row].copy()

    def _version(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.model_id.encode())
        digest.update(self.index_type.encode())
        for job_id in sorted(self._job_ids):
            digest.update(job_id.encode())
            digest.update(self.content_hashes.get(job_id, "").encode())
        return f"v1-{slugify(self.model_id)}-{len(self._job_ids)}-{digest.hexdigest()[:8]}"

    @property
    def version(self) -> str:
        return self._version()

    # ------------------------------------------------------------------ search
    def search(self, query: np.ndarray, top_k: int = 10) -> list[SearchHit]:
        if top_k <= 0:
            return []
        vector = np.asarray(query, dtype=np.float32).reshape(1, -1)
        if vector.shape[1] != self.dimension:
            raise IndexLoadError(
                f"Query dimension {vector.shape[1]} does not match index dimension {self.dimension}"
            )
        vector = _normalise(vector)
        k = min(top_k, self.size)

        with self._lock:
            if self.backend == "faiss" and self._index is not None:
                scores, ids = self._index.search(vector, k)
                raw_scores = scores[0]
                raw_ids = ids[0]
            else:
                similarities = (self._vectors @ vector[0]).astype(np.float32)
                raw_ids = np.argsort(-similarities)[:k]
                raw_scores = similarities[raw_ids]

        hits: list[SearchHit] = []
        for rank, (score, vector_id) in enumerate(zip(raw_scores, raw_ids, strict=False), start=1):
            if int(vector_id) < 0:
                continue
            job_id = self._id_map.get(int(vector_id))
            if job_id is None:
                logger.warning("FAISS returned an unmapped vector id %s; ignoring", vector_id)
                continue
            hits.append(SearchHit(job_id=job_id, score=float(score), rank=rank))
        return hits

    # ------------------------------------------------------------------ mutation
    def add(
        self,
        vectors: np.ndarray,
        job_ids: Sequence[str],
        content_hashes: dict[str, str] | None = None,
    ) -> list[str]:
        """Add new jobs, skipping duplicates. Returns the IDs actually added."""
        new_vectors: list[np.ndarray] = []
        new_ids: list[str] = []
        skipped: list[str] = []
        for vector, job_id in zip(vectors, job_ids, strict=False):
            if job_id in self._row_by_job:
                skipped.append(job_id)
                continue
            new_ids.append(job_id)
            new_vectors.append(np.asarray(vector, dtype=np.float32))
        if not new_ids:
            return []
        combined = np.vstack([self._vectors, _normalise(np.vstack(new_vectors))])
        self.__init__(
            vectors=combined,
            job_ids=[*self._job_ids, *new_ids],
            model_id=self.model_id,
            index_type=self.index_type,
            content_hashes={**self.content_hashes, **(content_hashes or {})},
            config_version=self.config_version,
            backend=self.backend,
        )
        if skipped:
            logger.info("Skipped %d jobs already present in the index", len(skipped))
        return new_ids

    # ------------------------------------------------------------------ persistence
    def metadata(self) -> IndexMetadata:
        return IndexMetadata(
            index_version=self.version,
            index_type=self.index_type if self.backend == "faiss" else f"numpy_{self.index_type}",
            metric="inner_product",
            embedding_model=self.model_id,
            embedding_dim=self.dimension,
            job_count=self.size,
            job_ids=self.job_ids,
            built_at=utcnow(),
            content_hashes=self.content_hashes,
            config_version=self.config_version,
        )

    def save(self, directory: str | Path) -> Path:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        np.save(target / "vectors.npy", self._vectors)
        (target / "metadata.json").write_text(
            self.metadata().model_dump_json(indent=2), encoding="utf-8"
        )
        if self.backend == "faiss" and self._index is not None:
            assert faiss is not None
            faiss.write_index(self._index, str(target / "index.faiss"))
        logger.info("Saved index %s (%d jobs) to %s", self.version, self.size, target)
        return target

    @classmethod
    def load(cls, directory: str | Path, *, model_id: str | None = None) -> FaissStore:
        source = Path(directory)
        metadata_path = source / "metadata.json"
        vectors_path = source / "vectors.npy"
        if not metadata_path.exists() or not vectors_path.exists():
            raise IndexLoadError(
                f"No index found in {source}. Build it with scripts/build_index.py."
            )
        try:
            metadata = IndexMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
            vectors = np.load(vectors_path).astype(np.float32)
        except Exception as exc:
            raise IndexLoadError(f"Index metadata could not be read: {type(exc).__name__}") from exc

        if model_id and metadata.embedding_model != model_id:
            raise IndexLoadError(
                f"Index was built with '{metadata.embedding_model}', not '{model_id}'. Rebuild the index."
            )
        if vectors.shape[0] != metadata.job_count or vectors.shape[1] != metadata.embedding_dim:
            raise IndexLoadError("Index vectors do not match the stored metadata dimensions")

        backend = "faiss" if FAISS_AVAILABLE and (source / "index.faiss").exists() else "numpy"
        store = cls(
            vectors=vectors,
            job_ids=metadata.job_ids,
            model_id=metadata.embedding_model,
            index_type=metadata.index_type if backend == "faiss" else "flat_ip",
            content_hashes=metadata.content_hashes,
            config_version=metadata.config_version,
            backend=backend,
        )
        if backend == "faiss":
            assert faiss is not None
            try:
                store._index = faiss.read_index(str(source / "index.faiss"))
            except Exception as exc:
                raise IndexLoadError(f"FAISS index could not be loaded: {type(exc).__name__}") from exc
        if store.version != metadata.index_version:
            raise IndexLoadError(
                "Index version mismatch: the stored metadata does not match the vectors. Rebuild the index."
            )
        logger.info("Loaded index %s (%d jobs, backend=%s)", store.version, store.size, backend)
        return store


def build_store(
    vectors: np.ndarray,
    job_ids: Sequence[str],
    *,
    model_id: str,
    content_hashes: dict[str, str] | None = None,
    directory: str | Path | None = None,
) -> FaissStore:
    config = get_config()
    store = FaissStore(
        vectors=vectors,
        job_ids=job_ids,
        model_id=model_id,
        index_type=str(config.get("retrieval.faiss.index_type", "flat_ip")),
        content_hashes=content_hashes,
        config_version=config.config_version,
    )
    if directory is not None:
        store.save(directory)
    return store

"""TF-IDF retrieval baseline.

Kept deliberately independent from the semantic stack: it is the reference system
against which embedding retrieval is compared, and it must stay reproducible.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from talentlens.config import get_config
from talentlens.errors import IndexLoadError
from talentlens.log import get_logger
from talentlens.retrieval.faiss_store import SearchHit
from talentlens.utils.text import slugify

logger = get_logger("retrieval.tfidf")


@dataclass
class TfidfMetadata:
    version: str
    job_count: int
    vocab_size: int
    ngram_range: tuple[int, int]
    model_id: str = "tfidf-word-1-2"


class TfidfRetriever:
    def __init__(self, *, config=None) -> None:
        self.config = config or get_config()
        self._vectorizer = None
        self._matrix = None
        self._job_ids: list[str] = []
        self._version: str | None = None

    # ------------------------------------------------------------------ fitting
    def fit(self, job_texts: Mapping[str, str]) -> TfidfRetriever:
        from sklearn.feature_extraction.text import TfidfVectorizer

        if not job_texts:
            raise IndexLoadError("Cannot fit TF-IDF without job documents")
        self._job_ids = list(job_texts)
        corpus = [job_texts[job_id] or job_id for job_id in self._job_ids]
        ngram = tuple(self.config.get("retrieval.tfidf.ngram_range", [1, 2]))
        self._vectorizer = TfidfVectorizer(
            ngram_range=(int(ngram[0]), int(ngram[1])),
            min_df=int(self.config.get("retrieval.tfidf.min_df", 1)),
            max_df=float(self.config.get("retrieval.tfidf.max_df", 0.9)),
            sublinear_tf=bool(self.config.get("retrieval.tfidf.sublinear_tf", True)),
            max_features=int(self.config.get("retrieval.tfidf.max_features", 50000)),
            stop_words="english",
            norm="l2",
        )
        self._matrix = self._vectorizer.fit_transform(corpus)
        self._version = self._compute_version(corpus)
        logger.info(
            "Fitted TF-IDF on %d jobs (%d features)", len(self._job_ids), self._matrix.shape[1]
        )
        return self

    def _compute_version(self, texts: list[str]) -> str:
        digest = hashlib.sha256()
        digest.update(str(self.config.get("retrieval.tfidf.ngram_range")).encode())
        digest.update(str(self.config.get("retrieval.tfidf.min_df")).encode())
        for job_id, text in zip(self._job_ids, texts, strict=False):
            digest.update(job_id.encode())
            digest.update(" ".join(text.lower().split()).encode("utf-8", errors="replace"))
        return f"tfidf-v1-{len(self._job_ids)}-{digest.hexdigest()[:8]}"

    @property
    def version(self) -> str:
        if self._version is None:
            raise IndexLoadError("TF-IDF retriever is not fitted")
        return self._version

    @property
    def job_ids(self) -> list[str]:
        return list(self._job_ids)

    # ------------------------------------------------------------------ search
    def search(self, query: str, top_k: int = 10) -> list[SearchHit]:
        if self._matrix is None or self._vectorizer is None:
            raise IndexLoadError("TF-IDF retriever is not fitted or loaded")
        if not query or not query.strip() or top_k <= 0:
            return []
        vector = self._vectorizer.transform([query])
        scores = np.asarray((self._matrix @ vector.T).todense()).ravel()
        k = min(top_k, len(self._job_ids))
        top = np.argsort(-scores, kind="stable")[:k]
        return [
            SearchHit(job_id=self._job_ids[index], score=float(scores[index]), rank=rank)
            for rank, index in enumerate(top, start=1)
        ]

    def score(self, query: str, job_id: str) -> float:
        """Cosine score for one job (used by evaluation to score all judged jobs)."""
        if self._matrix is None or self._vectorizer is None:
            raise IndexLoadError("TF-IDF retriever is not fitted or loaded")
        if job_id not in self._job_ids:
            return 0.0
        vector = self._vectorizer.transform([query or ""])
        row = self._job_ids.index(job_id)
        return float((self._matrix[row] @ vector.T).toarray().ravel()[0])

    def scores(self, query: str, job_ids: list[str] | None = None) -> dict[str, float]:
        """Score several jobs while transforming the query only once.

        The per-job ``score`` method is retained for evaluation call sites; the API
        matching path uses this method so a request does not pay for a new sparse
        vectorisation per candidate.
        """
        if self._matrix is None or self._vectorizer is None:
            raise IndexLoadError("TF-IDF retriever is not fitted or loaded")
        requested = list(job_ids) if job_ids is not None else list(self._job_ids)
        if not requested:
            return {}
        positions = {job_id: index for index, job_id in enumerate(self._job_ids)}
        rows = [(job_id, positions[job_id]) for job_id in requested if job_id in positions]
        if not rows:
            return {}
        vector = self._vectorizer.transform([query or ""])
        values = np.asarray((self._matrix[[row for _, row in rows]] @ vector.T).todense()).ravel()
        return {job_id: float(value) for (job_id, _), value in zip(rows, values, strict=False)}

    # ------------------------------------------------------------------ persistence
    def save(self, directory: str | Path) -> Path:
        import joblib

        if self._matrix is None or self._vectorizer is None:
            raise IndexLoadError("Cannot save an unfitted TF-IDF retriever")
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "vectorizer": self._vectorizer,
                "matrix": self._matrix,
                "job_ids": self._job_ids,
                "version": self.version,
                "ngram_range": list(self.config.get("retrieval.tfidf.ngram_range", [1, 2])),
            },
            target / "tfidf.joblib",
        )
        logger.info("Saved TF-IDF index %s to %s", self.version, target)
        return target

    @classmethod
    def load(cls, directory: str | Path, *, config=None) -> TfidfRetriever:
        import joblib

        path = Path(directory) / "tfidf.joblib"
        if not path.exists():
            raise IndexLoadError(
                f"TF-IDF index not found at {path}. Build it with scripts/build_index.py."
            )
        try:
            payload = joblib.load(path)
        except Exception as exc:
            raise IndexLoadError(f"TF-IDF index could not be read: {type(exc).__name__}") from exc
        retriever = cls(config=config)
        retriever._vectorizer = payload["vectorizer"]
        retriever._matrix = payload["matrix"]
        retriever._job_ids = list(payload["job_ids"])
        retriever._version = payload["version"]
        logger.info("Loaded TF-IDF index %s (%d jobs)", retriever._version, len(retriever._job_ids))
        return retriever

    def metadata(self) -> TfidfMetadata:
        if self._vectorizer is None:
            raise IndexLoadError("TF-IDF retriever is not fitted")
        ngram = self.config.get("retrieval.tfidf.ngram_range", [1, 2])
        return TfidfMetadata(
            version=self.version,
            job_count=len(self._job_ids),
            vocab_size=len(self._vectorizer.vocabulary_),
            ngram_range=(int(ngram[0]), int(ngram[1])),
            model_id=f"tfidf-{slugify(str(ngram))}",
        )

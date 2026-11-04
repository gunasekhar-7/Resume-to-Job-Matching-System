"""Embedding backends.

Default backend: a small Sentence-Transformer on CPU. Every vector is L2-normalised
so cosine similarity is an inner product (which is what FAISS FlatIP computes).

Two explicit alternatives exist and are *never* selected silently:

* ``lsa`` - TF-IDF + Truncated SVD fitted on the job corpus. Deterministic and
  dependency-light, but lexical rather than semantic.
* test-only hash embedders live in the test suite, not here.

The model identifier, dimension and backend are persisted with every index so a
ranking can be reproduced.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from talentlens.config import get_config
from talentlens.embeddings.embedding_cache import EmbeddingCache
from talentlens.errors import ModelUnavailableError
from talentlens.log import get_logger
from talentlens.utils.text import slugify
from talentlens.utils.timing import Timer

logger = get_logger("embeddings.embedder")

#: Keep per-document embedding inputs bounded; resumes/posts are truncated for vectors only.
MAX_EMBED_CHARS = 6000


def prepare_text(text: str, *, max_chars: int = MAX_EMBED_CHARS) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned[:max_chars]


@dataclass(frozen=True)
class EmbeddingMetadata:
    backend: str
    model_id: str
    dimension: int
    normalized: bool
    max_seq_length: int | None
    cache_enabled: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "model_id": self.model_id,
            "dimension": self.dimension,
            "normalized": self.normalized,
            "max_seq_length": self.max_seq_length,
            "cache_enabled": self.cache_enabled,
        }


class Embedder(ABC):
    backend: str = "abstract"

    def __init__(
        self,
        model_id: str,
        *,
        normalize: bool = True,
        cache_dir: str | Path | None = None,
        cache_enabled: bool = True,
        max_chars: int = MAX_EMBED_CHARS,
    ) -> None:
        self.model_id = model_id
        self.normalize = normalize
        self.max_chars = max_chars
        self._cache = (
            EmbeddingCache(cache_dir, model_id) if cache_enabled and cache_dir is not None else None
        )

    # ------------------------------------------------------------------ API
    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    def _encode(self, texts: list[str], batch_size: int | None) -> np.ndarray: ...

    def encode(
        self,
        texts: Sequence[str],
        *,
        batch_size: int | None = None,
        use_cache: bool = True,
    ) -> np.ndarray:
        prepared = [prepare_text(text, max_chars=self.max_chars) for text in texts]
        if not prepared:
            return np.zeros((0, self.dimension), dtype=np.float32)

        vectors = np.zeros((len(prepared), self.dimension), dtype=np.float32)
        if self._cache is None or not use_cache:
            non_empty = [(index, text) for index, text in enumerate(prepared) if text]
            if non_empty:
                encoded = self._encode([text for _, text in non_empty], batch_size)
                for position, (index, _) in enumerate(non_empty):
                    vectors[index] = encoded[position]
            return self._normalise(vectors)

        missing: list[tuple[int, str]] = []
        for index, text in enumerate(prepared):
            if not text:
                continue
            cached = self._cache.get(text)
            if cached is not None and cached.shape[0] == self.dimension:
                vectors[index] = cached
            else:
                missing.append((index, text))

        if missing:
            encoded = self._encode([text for _, text in missing], batch_size)
            for position, (index, _text) in enumerate(missing):
                vectors[index] = encoded[position]
            self._cache.put_many([text for _, text in missing], encoded)
            self._cache.flush()
        return self._normalise(vectors)

    def encode_one(self, text: str, *, use_cache: bool = True) -> np.ndarray:
        return self.encode([text], use_cache=use_cache)[0]

    def _normalise(self, vectors: np.ndarray) -> np.ndarray:
        if not self.normalize:
            return vectors
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (vectors / norms).astype(np.float32)

    def metadata(self) -> EmbeddingMetadata:
        return EmbeddingMetadata(
            backend=self.backend,
            model_id=self.model_id,
            dimension=self.dimension,
            normalized=self.normalize,
            max_seq_length=None,
            cache_enabled=self._cache is not None,
        )

    def cache_size(self) -> int:
        return self._cache.size if self._cache else 0


class SentenceTransformerEmbedder(Embedder):
    backend = "sentence_transformers"

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        *,
        device: str = "cpu",
        max_seq_length: int = 256,
        batch_size: int = 32,
        normalize: bool = True,
        cache_dir: str | Path | None = None,
        cache_enabled: bool = True,
        model_cache_folder: str | None = None,
    ) -> None:
        super().__init__(
            model_name, normalize=normalize, cache_dir=cache_dir, cache_enabled=cache_enabled
        )
        self.device = device
        self.max_seq_length = max_seq_length
        self.default_batch_size = batch_size
        self.model_cache_folder = model_cache_folder
        self._model = None
        self._dimension: int | None = None
        self._lock = threading.Lock()
        self._load_ms: float | None = None

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except Exception as exc:  # pragma: no cover - dependency should be installed
                raise ModelUnavailableError(
                    "sentence-transformers is not installed; install requirements.txt"
                ) from exc
            timer = Timer().start()
            try:
                model = SentenceTransformer(
                    self.model_id, device=self.device, cache_folder=self.model_cache_folder
                )
            except Exception as exc:
                raise ModelUnavailableError(
                    f"Embedding model '{self.model_id}' could not be loaded: {type(exc).__name__}. "
                    "Check the model name, network access, or pre-download it into the HF cache."
                ) from exc
            if self.max_seq_length:
                model.max_seq_length = int(self.max_seq_length)
            self._dimension = int(model.get_sentence_embedding_dimension())
            self._model = model
            self._load_ms = timer.stop()
            logger.info(
                "Loaded embedding model %s (dim=%d) in %.0f ms", self.model_id, self._dimension, self._load_ms
            )
            return model

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._ensure_model()
        assert self._dimension is not None
        return self._dimension

    def metadata(self) -> EmbeddingMetadata:
        base = super().metadata()
        return EmbeddingMetadata(
            backend=base.backend,
            model_id=base.model_id,
            dimension=base.dimension,
            normalized=base.normalized,
            max_seq_length=self.max_seq_length,
            cache_enabled=base.cache_enabled,
        )

    def _encode(self, texts: list[str], batch_size: int | None) -> np.ndarray:
        model = self._ensure_model()
        try:
            vectors = model.encode(
                texts,
                batch_size=batch_size or self.default_batch_size,
                normalize_embeddings=False,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as exc:  # pragma: no cover - runtime failure
            raise ModelUnavailableError(
                f"Embedding failed for model '{self.model_id}': {type(exc).__name__}"
            ) from exc
        return np.asarray(vectors, dtype=np.float32)

    @property
    def load_latency_ms(self) -> float | None:
        return self._load_ms


class LSAEmbedder(Embedder):
    """Explicit lexical fallback: TF-IDF followed by Truncated SVD.

    Must be fitted on the job corpus before use. It is labelled ``lsa`` in every
    index and report and must not be presented as a semantic transformer model.
    """

    backend = "lsa"

    def __init__(
        self,
        *,
        components: int = 192,
        min_df: int = 1,
        max_features: int = 30000,
        random_state: int = 42,
        cache_dir: str | Path | None = None,
        cache_enabled: bool = True,
    ) -> None:
        super().__init__(
            "lsa-tfidf-svd-v1", cache_dir=cache_dir, cache_enabled=cache_enabled
        )
        self.components = components
        self.min_df = min_df
        self.max_features = max_features
        self.random_state = random_state
        self._vectorizer = None
        self._svd = None
        self._dimension = components

    def fit(self, texts: Sequence[str]) -> LSAEmbedder:
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        corpus = [text for text in texts if text and text.strip()]
        if len(corpus) < 2:
            raise ModelUnavailableError("LSA fallback needs at least two non-empty documents")
        self._vectorizer = TfidfVectorizer(
            sublinear_tf=True,
            min_df=self.min_df,
            max_features=self.max_features,
            stop_words="english",
            ngram_range=(1, 2),
        )
        matrix = self._vectorizer.fit_transform(corpus)
        components = max(2, min(self.components, matrix.shape[1] - 1))
        self._svd = TruncatedSVD(n_components=components, random_state=self.random_state)
        self._svd.fit(matrix)
        self._dimension = components
        logger.info("Fitted LSA fallback: %d docs, %d components", len(corpus), components)
        return self

    @property
    def dimension(self) -> int:
        return self._dimension

    def _encode(self, texts: list[str], batch_size: int | None) -> np.ndarray:
        if self._vectorizer is None or self._svd is None:
            raise ModelUnavailableError("LSA fallback is not fitted; call fit() on the job corpus first")
        matrix = self._vectorizer.transform(texts)
        return np.asarray(self._svd.transform(matrix), dtype=np.float32)

    def save(self, path: str | Path) -> Path:
        import joblib

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "vectorizer": self._vectorizer,
                "svd": self._svd,
                "model_id": self.model_id,
                "components": self._dimension,
            },
            target,
        )
        return target

    def load(self, path: str | Path) -> LSAEmbedder:
        import joblib

        payload = joblib.load(path)
        self._vectorizer = payload["vectorizer"]
        self._svd = payload["svd"]
        self._dimension = int(payload["components"])
        return self


_EMBEDDER_CACHE: dict[tuple[str, str], Embedder] = {}
_CACHE_LOCK = threading.Lock()


def get_embedder(
    *,
    backend: str | None = None,
    model_name: str | None = None,
    use_cache: bool = True,
) -> Embedder:
    config = get_config()
    resolved_backend = (backend or config.get("embeddings.backend", "sentence_transformers")).lower()
    resolved_model = model_name or config.get("embeddings.model_name")
    key = (resolved_backend, resolved_model or "")

    with _CACHE_LOCK:
        if use_cache and key in _EMBEDDER_CACHE:
            return _EMBEDDER_CACHE[key]

        cache_dir = config.resolve(config.get("embeddings.cache_dir", "artifacts/embeddings"))
        common = {
            "cache_dir": cache_dir,
            "cache_enabled": bool(config.get("embeddings.cache_enabled", True)),
        }
        if resolved_backend == "sentence_transformers":
            embedder: Embedder = SentenceTransformerEmbedder(
                resolved_model or "sentence-transformers/all-MiniLM-L6-v2",
                device=str(config.get("embeddings.device", "cpu")),
                max_seq_length=int(config.get("embeddings.max_seq_length", 256)),
                batch_size=int(config.get("embeddings.batch_size", 32)),
                normalize=bool(config.get("embeddings.normalize", True)),
                model_cache_folder=config.get("embeddings.model_cache_folder"),
                **common,
            )
        elif resolved_backend == "lsa":
            embedder = LSAEmbedder(
                components=int(config.get("embeddings.lsa_components", 192)),
                min_df=int(config.get("embeddings.lsa_min_df", 1)),
                max_features=int(config.get("embeddings.lsa_max_features", 30000)),
                **common,
            )
        else:
            raise ModelUnavailableError(
                f"Unknown embedding backend '{resolved_backend}'. Use sentence_transformers or lsa."
            )

        if use_cache:
            _EMBEDDER_CACHE[key] = embedder
        return embedder


def reset_embedder_cache() -> None:
    with _CACHE_LOCK:
        _EMBEDDER_CACHE.clear()


def model_slug(model_id: str) -> str:
    return slugify(model_id)

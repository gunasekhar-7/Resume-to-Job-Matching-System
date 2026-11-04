"""Optional cross-encoder reranking with an explicit lexical fallback.

The cross-encoder is never assumed to improve results; Phase 2/3 benchmarks compare
rankings with and without it and record latency. If the model cannot be loaded and
``lexical_fallback`` is enabled, a clearly labelled lexical reranker is used and the
degradation is reported in the match response.
"""

from __future__ import annotations

import math
import re
import threading
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from talentlens.config import get_config
from talentlens.log import get_logger
from talentlens.utils.timing import Timer

logger = get_logger("retrieval.reranker")

_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall((text or "").lower()) if len(token) > 1}


@dataclass
class RerankResult:
    job_id: str
    score: float


class Reranker(ABC):
    model_id: str

    @abstractmethod
    def rerank(self, resume_text: str, candidates: Sequence[tuple[str, str]], top_n: int) -> list[RerankResult]:
        """Return candidates ordered by rerank relevance."""

    @property
    def degraded(self) -> bool:
        return False

    @property
    def degradation_reason(self) -> str | None:
        return None


class LexicalReranker(Reranker):
    """Transparent fallback: token coverage + Jaccard similarity."""

    model_id = "lexical-overlap-v1"

    def rerank(self, resume_text: str, candidates: Sequence[tuple[str, str]], top_n: int) -> list[RerankResult]:
        resume_tokens = _tokens(resume_text)
        results: list[RerankResult] = []
        for job_id, job_text in candidates:
            job_tokens = _tokens(job_text)
            if not resume_tokens or not job_tokens:
                score = 0.0
            else:
                overlap = len(resume_tokens & job_tokens)
                coverage = overlap / len(job_tokens)
                jaccard = overlap / len(resume_tokens | job_tokens)
                score = 0.65 * coverage + 0.35 * jaccard
            results.append(RerankResult(job_id=job_id, score=round(min(1.0, max(0.0, score)), 6)))
        results.sort(key=lambda item: (-item.score, item.job_id))
        return results[:top_n]

    @property
    def degraded(self) -> bool:
        return True

    @property
    def degradation_reason(self) -> str | None:
        return "Cross-encoder unavailable; lexical reranker used. Rankings are not cross-encoder results."


class CrossEncoderReranker(Reranker):
    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        *,
        batch_size: int = 16,
        max_length: int = 256,
        lexical_fallback: bool = True,
    ) -> None:
        self.model_id = model_name
        self.batch_size = batch_size
        self.max_length = max_length
        self.lexical_fallback = lexical_fallback
        self._model = None
        self._fallback: LexicalReranker | None = None
        self._reason: str | None = None
        self._lock = threading.Lock()
        self.load_ms: float | None = None

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            timer = Timer().start()
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(self.model_id, max_length=self.max_length)
                self.load_ms = timer.stop()
                logger.info("Loaded cross-encoder %s in %.0f ms", self.model_id, self.load_ms)
            except Exception as exc:
                self._reason = f"{type(exc).__name__}: cross-encoder '{self.model_id}' unavailable"
                logger.warning(self._reason)
                if not self.lexical_fallback:
                    raise
                self._fallback = LexicalReranker()
            return self._model

    def rerank(self, resume_text: str, candidates: Sequence[tuple[str, str]], top_n: int) -> list[RerankResult]:
        if not candidates:
            return []
        model = self._ensure_model()
        if model is None:
            assert self._fallback is not None
            return self._fallback.rerank(resume_text, candidates, top_n)

        pairs = [(resume_text[:6000], job_text[:6000]) for _, job_text in candidates]
        try:
            logits = model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)
        except Exception as exc:
            logger.exception("Cross-encoder scoring failed")
            if self.lexical_fallback:
                self._fallback = LexicalReranker()
                self._reason = f"Cross-encoder scoring failed: {type(exc).__name__}"
                return self._fallback.rerank(resume_text, candidates, top_n)
            raise

        results: list[RerankResult] = []
        for (job_id, _), logit in zip(candidates, logits, strict=False):
            score = 1.0 / (1.0 + math.exp(-float(logit)))
            results.append(RerankResult(job_id=job_id, score=round(score, 6)))
        results.sort(key=lambda item: (-item.score, item.job_id))
        return results[:top_n]

    @property
    def degraded(self) -> bool:
        return self._fallback is not None

    @property
    def degradation_reason(self) -> str | None:
        return self._reason


def build_reranker(enabled: bool | None = None) -> Reranker | None:
    config = get_config()
    rerank_enabled = config.get("matching.reranker.enabled", False) if enabled is None else enabled
    if not rerank_enabled:
        return None
    return CrossEncoderReranker(
        str(config.get("matching.reranker.model_name", "cross-encoder/ms-marco-MiniLM-L-6-v2")),
        batch_size=int(config.get("matching.reranker.batch_size", 16)),
        max_length=int(config.get("matching.reranker.max_length", 256)),
        lexical_fallback=bool(config.get("matching.reranker.lexical_fallback", True)),
    )

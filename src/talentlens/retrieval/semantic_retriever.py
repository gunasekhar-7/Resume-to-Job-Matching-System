"""Semantic retrieval: resume text -> embedding -> FAISS hits."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from talentlens.embeddings.embedder import Embedder
from talentlens.errors import IndexNotBuiltError
from talentlens.log import get_logger
from talentlens.retrieval.faiss_store import FaissStore, SearchHit
from talentlens.schemas import ResumeDocument
from talentlens.utils.timing import Timer

logger = get_logger("retrieval.semantic")


@dataclass
class SemanticSearchResult:
    hits: list[SearchHit]
    query_vector: np.ndarray
    latency_ms: float


class SemanticRetriever:
    def __init__(self, embedder: Embedder, store: FaissStore) -> None:
        if store.dimension != embedder.dimension:
            raise IndexNotBuiltError(
                f"Index dimension {store.dimension} does not match embedder dimension {embedder.dimension}. "
                "Rebuild the index with the configured model."
            )
        self.embedder = embedder
        self.store = store

    def search_text(self, text: str, top_k: int = 10) -> SemanticSearchResult:
        timer = Timer().start()
        vector = self.embedder.encode_one(text)
        hits = self.store.search(vector, top_k=top_k)
        return SemanticSearchResult(hits=hits, query_vector=vector, latency_ms=timer.stop())

    def search_document(self, document: ResumeDocument, top_k: int = 10) -> SemanticSearchResult:
        return self.search_text(document_query_text(document), top_k=top_k)


def document_query_text(document: ResumeDocument) -> str:
    """Build the retrieval query from the richest available resume text.

    Skills, experience and summary are emphasised; contact/header text is excluded so
    that an email address cannot influence similarity.
    """
    parts: list[str] = []
    for section in ("summary", "skills", "experience", "projects"):
        text = document.section_text(section)
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else document.full_text

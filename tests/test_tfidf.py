from __future__ import annotations

import pytest

from talentlens.errors import IndexLoadError
from talentlens.retrieval.tfidf_retriever import TfidfRetriever

DOCS = {
    "job_ml": "Python machine learning scikit-learn model deployment",
    "job_backend": "Java Spring Boot REST API microservices",
    "job_nlp": "Natural language processing PyTorch transformers NLP",
}


def test_relevant_document_ranks_first():
    retriever = TfidfRetriever().fit(DOCS)
    hits = retriever.search("PyTorch NLP transformers", top_k=3)
    assert hits[0].job_id == "job_nlp"
    assert hits[0].score > 0
    assert [hit.rank for hit in hits] == [1, 2, 3]


def test_empty_query_returns_no_hits():
    retriever = TfidfRetriever().fit(DOCS)
    assert retriever.search("", top_k=3) == []
    assert retriever.search("   ", top_k=3) == []


def test_unfitted_retriever_raises():
    with pytest.raises(IndexLoadError):
        TfidfRetriever().search("python", top_k=1)
    with pytest.raises(IndexLoadError):
        TfidfRetriever().fit({})


def test_persistence_round_trip(tmp_path):
    retriever = TfidfRetriever().fit(DOCS)
    retriever.save(tmp_path)
    loaded = TfidfRetriever.load(tmp_path)
    assert loaded.version == retriever.version
    assert loaded.search("Spring Boot", top_k=1)[0].job_id == "job_backend"
    assert loaded.score("Spring Boot", "job_backend") > 0


def test_score_unknown_job_is_zero():
    retriever = TfidfRetriever().fit(DOCS)
    assert retriever.score("python", "missing") == 0.0


def test_metadata_counts_vocabulary():
    metadata = TfidfRetriever().fit(DOCS).metadata()
    assert metadata.job_count == 3
    assert metadata.vocab_size > 0

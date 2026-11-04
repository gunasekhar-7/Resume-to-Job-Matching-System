from __future__ import annotations

import numpy as np
import pytest

from fakes import FakeEmbedder
from talentlens.embeddings.embedder import EmbeddingCache, prepare_text


def test_prepare_text_collapses_and_truncates():
    assert prepare_text("  Python\n\nSQL\t") == "Python SQL"
    assert len(prepare_text("x" * 7000)) == 6000


def test_encode_normalises_and_handles_empty_text():
    embedder = FakeEmbedder(dimension=16)
    vectors = embedder.encode(["Python SQL", "", "Python SQL"])
    assert vectors.shape == (3, 16)
    norms = np.linalg.norm(vectors, axis=1)
    assert norms[0] == pytest.approx(1.0)
    assert norms[1] == 0.0
    assert np.allclose(vectors[0], vectors[2])
    assert np.allclose(embedder.encode_one("Python SQL"), vectors[0])


def test_deterministic_encoding():
    embedder = FakeEmbedder(dimension=32)
    first = embedder.encode(["machine learning with Python"])
    second = embedder.encode(["machine learning with Python"])
    assert np.array_equal(first, second)


def test_cache_indexes_batch_positions_correctly(tmp_path):
    embedder = FakeEmbedder(cache_dir=tmp_path, cache_enabled=True)
    texts = ["alpha beta", "gamma delta", "epsilon zeta"]
    first = embedder.encode(texts)
    assert embedder.cache_size() == 3
    second = embedder.encode(texts)
    assert embedder.calls == 1, "all three texts should be served from cache"
    assert np.allclose(first, second)


def test_embedding_cache_round_trip_and_privacy(tmp_path):
    first = FakeEmbedder(cache_dir=tmp_path, cache_enabled=True)
    vector = first.encode(["Kubernetes and Terraform"])[0]
    assert first.calls == 1

    second = FakeEmbedder(cache_dir=tmp_path, cache_enabled=True)
    cached = second.encode(["Kubernetes and Terraform"])[0]
    assert second.calls == 0, "cache should avoid re-encoding"
    assert np.allclose(vector, cached)

    cache_file = tmp_path / "fake-hash-v1" / "index.json"
    assert cache_file.exists()
    assert "Kubernetes" not in cache_file.read_text(encoding="utf-8")
    assert "Terraform" not in cache_file.read_text(encoding="utf-8")


def test_cache_rejects_text_of_wrong_dimension(tmp_path):
    cache = EmbeddingCache(tmp_path, "fake-hash-v1")
    cache.put_many(["alpha"], np.ones((1, 8), dtype=np.float32))
    cache.flush()
    assert cache.get("missing") is None
    assert cache.get("alpha").shape == (8,)


def test_metadata_reports_backend_and_dimension():
    metadata = FakeEmbedder(dimension=24).metadata()
    assert metadata.backend == "fake"
    assert metadata.dimension == 24
    assert metadata.normalized is True

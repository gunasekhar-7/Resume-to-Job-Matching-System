from __future__ import annotations

import numpy as np
import pytest

from talentlens.errors import DuplicateJobError, IndexLoadError
from talentlens.retrieval.faiss_store import FAISS_AVAILABLE, FaissStore


def _store(vectors, job_ids, **kwargs):
    return FaissStore(vectors=np.asarray(vectors, dtype=np.float32), job_ids=list(job_ids), model_id="fake-model", **kwargs)


def test_search_maps_vectors_to_job_ids_not_positions():
    # Deliberately non-sorted IDs and a shuffled matrix: position 0 is job "c".
    vectors = np.eye(4, dtype=np.float32)
    store = _store(vectors, ["c", "a", "d", "b"])
    hits = store.search(np.array([0, 1, 0, 0], dtype=np.float32), top_k=2)
    assert hits[0].job_id == "a"
    assert hits[0].rank == 1
    assert hits[0].score == pytest.approx(1.0, abs=1e-5)
    assert store.vector_for("b") is not None


def test_persistence_round_trip_preserves_mapping_and_version(tmp_path):
    vectors = np.eye(3, dtype=np.float32)
    store = _store(
        vectors,
        ["job_a", "job_b", "job_c"],
        content_hashes={"job_a": "aaa", "job_b": "bbb", "job_c": "ccc"},
    )
    store.save(tmp_path)
    loaded = FaissStore.load(tmp_path, model_id="fake-model")
    assert loaded.version == store.version
    assert loaded.job_ids == store.job_ids
    hits = loaded.search(np.array([0, 0, 1], dtype=np.float32), top_k=1)
    assert hits[0].job_id == "job_c"
    assert loaded.size == 3


def test_load_rejects_wrong_model(tmp_path):
    _store(np.eye(2), ["a", "b"]).save(tmp_path)
    with pytest.raises(IndexLoadError, match="built with"):
        FaissStore.load(tmp_path, model_id="other-model")


def test_duplicate_job_ids_rejected():
    with pytest.raises(DuplicateJobError):
        _store(np.eye(2), ["same", "same"])


def test_duplicate_content_hashes_rejected():
    with pytest.raises(DuplicateJobError, match="content"):
        _store(
            np.eye(2),
            ["a", "b"],
            content_hashes={"a": "same-hash", "b": "same-hash"},
        )


def test_add_skips_existing_and_indexes_new_job():
    store = _store(np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32), ["a", "b"])
    added = store.add(np.array([[0, 0, 1]], dtype=np.float32), ["c", "a"])
    assert added == ["c"]
    assert store.size == 3
    assert store.contains("c")
    with pytest.raises(IndexLoadError, match="dimension"):
        store.search(np.zeros(2, dtype=np.float32), top_k=1)


def test_version_changes_with_content_hash():
    first = _store(np.eye(2), ["a", "b"], content_hashes={"a": "1", "b": "2"})
    second = _store(np.eye(2), ["a", "b"], content_hashes={"a": "1", "b": "3"})
    assert first.version != second.version


def test_numpy_fallback_backend_returns_same_order():
    store = _store(np.eye(3), ["a", "b", "c"], backend="numpy")
    hits = store.search(np.array([0, 1, 0], dtype=np.float32), top_k=2)
    assert [hit.job_id for hit in hits] == ["b", "a"]
    assert store.metadata().index_type == "numpy_flat_ip"


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="faiss-cpu not installed")
def test_faiss_backend_is_reported():
    store = _store(np.eye(2), ["a", "b"])
    assert store.backend == "faiss"
    assert store.metadata().index_type == "flat_ip"

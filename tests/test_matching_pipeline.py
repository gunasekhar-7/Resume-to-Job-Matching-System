from __future__ import annotations

import pytest

from fakes import FakeEmbedder
from talentlens.errors import EmptyDocumentError, IndexNotBuiltError
from talentlens.matching.pipeline import MatchFilters, MatchingPipeline
from talentlens.retrieval.reranker import LexicalReranker
from talentlens.schemas import ResumeDocument


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory, job_documents, config, taxonomy):
    directory = tmp_path_factory.mktemp("phase2-index")
    return MatchingPipeline.build(
        job_documents,
        embedder=FakeEmbedder(dimension=48),
        config=config,
        taxonomy=taxonomy,
        artifact_dir=directory,
        persist=True,
    )


def test_build_reports_index_metadata(pipeline, job_documents):
    stats = pipeline.stats()
    assert stats["jobs"] == len(job_documents)
    assert stats["embedding_model"] == "fake-hash-v1"
    assert stats["index_version"]
    assert stats["tfidf_version"]


def test_match_returns_ranked_results_with_breakdown(pipeline, parsed_r01):
    response = pipeline.match(parsed_r01, top_k=5, strategy="hybrid")
    assert len(response.results) == 5
    assert response.model_id == "fake-hash-v1"
    assert response.retrieval == "hybrid"
    assert response.results[0].rank == 1
    scores = [match.score for match in response.results]
    assert scores == sorted(scores, reverse=True)
    for match in response.results:
        assert match.score == match.score_breakdown.total
        assert sum(item.contribution for item in match.score_breakdown.contributions) == pytest.approx(
            match.score, abs=1e-6
        )
        assert match.explanation.score_breakdown == match.score_breakdown
        assert match.explanation.experience.status is not None
        assert "not a probability" in " ".join(match.explanation.methodology_notes)


def test_matching_is_reproducible(pipeline, parsed_r01):
    first = pipeline.match(parsed_r01, top_k=10)
    second = pipeline.match(parsed_r01, top_k=10)
    assert [item.job_id for item in first.results] == [item.job_id for item in second.results]
    assert [item.score for item in first.results] == [item.score for item in second.results]


def test_tfidf_and_semantic_baselines_are_honest(pipeline, parsed_r01):
    tfidf = pipeline.match(parsed_r01, top_k=5, strategy="tfidf")
    semantic = pipeline.match(parsed_r01, top_k=5, strategy="semantic")
    assert all(match.retrieval_source == "tfidf" for match in tfidf.results)
    assert all(match.retrieval_source == "semantic" for match in semantic.results)
    for match in tfidf.results:
        assert match.score == match.score_breakdown.tfidf
        assert match.score_breakdown.weights == {"tfidf": 1.0}
    for match in semantic.results:
        assert match.score == match.score_breakdown.semantic
        assert match.score_breakdown.weights == {"semantic": 1.0}


def test_top_k_can_cover_the_whole_corpus(pipeline, parsed_r01, job_documents):
    response = pipeline.match(parsed_r01, top_k=100)
    assert len(response.results) == len(job_documents)
    assert len({match.job_id for match in response.results}) == len(job_documents)


def test_reranking_can_be_enabled(pipeline, parsed_r01):
    response = pipeline.match(parsed_r01, top_k=5, rerank=LexicalReranker())
    assert response.reranked is True
    assert "rerank_ms" in response.timings_ms
    assert all(match.retrieval_source == "reranked" for match in response.results)
    assert all(match.rerank_score is not None for match in response.results)


def test_location_filter_is_applied_before_ranking(pipeline, parsed_r01, job_documents):
    location = next((job.location for job in job_documents if job.location), None)
    if not location:
        pytest.skip("Synthetic jobs have no locations")
    response = pipeline.match(parsed_r01, top_k=5, filters=MatchFilters(location=location))
    assert response.results
    assert all(location.lower() in (match.location or "").lower() for match in response.results)


def test_work_arrangement_filter_is_case_insensitive(pipeline, parsed_r01, job_documents):
    arrangement = next((job.work_arrangement for job in job_documents if job.work_arrangement), None)
    if not arrangement:
        pytest.skip("Synthetic jobs have no work arrangements")
    response = pipeline.match(
        parsed_r01,
        top_k=5,
        filters=MatchFilters(work_arrangement=(arrangement.upper(),)),
    )
    assert response.results
    assert all((match.work_arrangement or "").lower() == arrangement.lower() for match in response.results)


def test_filter_with_no_matches_returns_empty_response(pipeline, parsed_r01):
    response = pipeline.match(parsed_r01, top_k=5, filters=MatchFilters(location="zzzz-not-a-place"))
    assert response.results == []
    assert any("filters" in warning for warning in response.warnings)


def test_empty_document_raises(pipeline):
    document = ResumeDocument(
        resume_id="empty",
        full_text="",
        sections={},
        skills=[],
        metadata={
            "source_format": "txt",
            "source_filename": "empty.txt",
            "sha256": "0" * 64,
        },
    )
    with pytest.raises(EmptyDocumentError):
        pipeline.match(document, top_k=5)


def test_document_without_skills_still_matches_with_warning(pipeline):
    document = ResumeDocument(
        resume_id="no-skills",
        full_text="A resume with narrative text but no recognizable skills.",
        sections={"summary": ["Generalist engineer."]},
        skills=[],
        metadata={
            "source_format": "txt",
            "source_filename": "no-skills.txt",
            "sha256": "0" * 64,
        },
    )
    response = pipeline.match(document, top_k=3)
    assert response.results
    assert any("No skills" in warning for warning in response.warnings)
    assert all(match.score_breakdown.required_coverage == 0.0 for match in response.results)


def test_persisted_index_can_be_reloaded(pipeline, parsed_r01, job_documents, config, taxonomy):
    original = pipeline.match(parsed_r01, top_k=3)
    reloaded = MatchingPipeline.load(
        job_documents,
        embedder=FakeEmbedder(dimension=48),
        config=config,
        taxonomy=taxonomy,
        artifact_dir=pipeline.index_dir,
    )
    restored = reloaded.match(parsed_r01, top_k=3)
    assert [item.job_id for item in restored.results] == [item.job_id for item in original.results]
    assert reloaded.store.version == pipeline.store.version


def test_rank_ids_covers_corpus(pipeline, parsed_r01, job_documents):
    ranked = pipeline.rank_ids(parsed_r01)
    assert len(ranked) == len(job_documents)
    assert set(ranked) == {job.job_id for job in job_documents}


def test_build_requires_jobs():
    with pytest.raises(IndexNotBuiltError):
        MatchingPipeline.build([], embedder=FakeEmbedder())

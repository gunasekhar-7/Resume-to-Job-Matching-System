"""Unified matching pipeline: retrieve, score, optionally rerank, explain.

The pipeline is the single entry point used by evaluation (Phase 3) and the API
(Phase 4). It never reads files hidden from the caller: jobs are supplied as
validated ``JobPosting`` objects and indexes are persisted under ``artifacts``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from talentlens.config import Config, get_config
from talentlens.embeddings.embedder import Embedder, LSAEmbedder, get_embedder
from talentlens.errors import EmptyDocumentError, IndexLoadError, IndexNotBuiltError
from talentlens.log import get_logger
from talentlens.matching.experience_matcher import align_experience
from talentlens.matching.hybrid_scorer import HybridScorer
from talentlens.matching.skill_matcher import SkillMatchResult, match_skills
from talentlens.retrieval.faiss_store import FaissStore, build_store
from talentlens.retrieval.reranker import Reranker, build_reranker
from talentlens.retrieval.semantic_retriever import document_query_text
from talentlens.retrieval.tfidf_retriever import TfidfRetriever
from talentlens.schemas import (
    JobMatch,
    JobPosting,
    MatchExplanation,
    MatchResponse,
    ParsingStatus,
    ResumeDocument,
    SectionName,
)
from talentlens.skills.taxonomy import SkillTaxonomy, get_taxonomy
from talentlens.utils.text import slugify
from talentlens.utils.timing import Timer

logger = get_logger("matching.pipeline")

_SECTION_ORDER = ("summary", "skills", "experience", "projects", "certifications")
#: Education is deliberately excluded from semantic scoring to avoid institutional
#: prestige acting as a proxy for candidate quality; it is still shown to users.
_EXCLUDED_SECTIONS = {"header", "education", "other"}


@dataclass
class MatchFilters:
    seniority: tuple[str, ...] = ()
    location: str | None = None
    work_arrangement: tuple[str, ...] = ()
    employment_type: str | None = None

    def allows(self, job: JobPosting) -> bool:
        if self.seniority and (job.seniority or "").lower() not in {
            value.lower() for value in self.seniority
        }:
            return False
        if self.location and self.location.lower() not in (job.location or "").lower():
            return False
        if self.work_arrangement and (job.work_arrangement or "unknown").lower() not in {
            value.lower() for value in self.work_arrangement
        }:
            return False
        return not (
            self.employment_type
            and self.employment_type.lower() not in (job.employment_type or "").lower()
        )


@dataclass
class PipelineConfig:
    weights: dict[str, float] = field(default_factory=dict)
    top_k: int = 10
    candidate_multiplier: int = 3
    reranker_top_n: int = 30
    max_section_evidence: int = 3
    section_weights: dict[str, float] = field(default_factory=dict)


def default_index_dir(config: Config, model_id: str) -> Path:
    return config.artifacts_dir / "index" / slugify(model_id)


class MatchingPipeline:
    def __init__(
        self,
        jobs: list[JobPosting],
        *,
        embedder: Embedder,
        store: FaissStore,
        tfidf: TfidfRetriever,
        config: Config | None = None,
        taxonomy: SkillTaxonomy | None = None,
        reranker: Reranker | None = None,
        index_dir: Path | None = None,
        extra_warnings: list[str] | None = None,
    ) -> None:
        self.config = config or get_config()
        self.taxonomy = taxonomy or get_taxonomy()
        self.embedder = embedder
        self.store = store
        self.tfidf = tfidf
        self.reranker = reranker
        self.index_dir = index_dir
        self.warnings = list(extra_warnings or [])
        self.jobs = {job.job_id: job for job in sorted(jobs, key=lambda item: item.job_id)}
        if not self.jobs:
            raise IndexNotBuiltError("Cannot match without job postings")
        if store.dimension != embedder.dimension:
            raise IndexNotBuiltError(
                f"Index dimension {store.dimension} != embedder dimension {embedder.dimension}"
            )
        missing = set(store.job_ids) - set(self.jobs)
        if missing:
            raise IndexLoadError(
                f"Index references {len(missing)} job(s) not present in the job store: {sorted(missing)[:5]}"
            )
        not_indexed = set(self.jobs) - set(store.job_ids)
        if not_indexed:
            self.warnings.append(
                f"{len(not_indexed)} job(s) are stored but not indexed and cannot be retrieved: "
                f"{sorted(not_indexed)[:5]}"
            )
        self.scorer = HybridScorer()
        self.section_weights = {
            str(key): float(value)
            for key, value in (self.config.get("matching.section_weights", {}) or {}).items()
        }
        self.weights = self.config.weights

    # ------------------------------------------------------------------ construction
    @classmethod
    def build(
        cls,
        jobs: list[JobPosting],
        *,
        embedder: Embedder | None = None,
        config: Config | None = None,
        taxonomy: SkillTaxonomy | None = None,
        reranker: Reranker | None = None,
        artifact_dir: str | Path | None = None,
        persist: bool = True,
    ) -> MatchingPipeline:
        config = config or get_config()
        taxonomy = taxonomy or get_taxonomy()
        embedder = embedder or get_embedder()
        if not jobs:
            raise IndexNotBuiltError("Cannot build an index from zero jobs")
        ordered = sorted(jobs, key=lambda item: item.job_id)
        texts = [job.searchable_text() for job in ordered]

        if isinstance(embedder, LSAEmbedder):
            embedder.fit(texts)
            if persist:
                target = Path(artifact_dir) if artifact_dir else default_index_dir(config, embedder.model_id)
                target.mkdir(parents=True, exist_ok=True)
                embedder.save(target / "lsa_state.joblib")

        vectors = embedder.encode(texts)
        directory = Path(artifact_dir) if artifact_dir else default_index_dir(config, embedder.model_id)
        store = build_store(
            vectors,
            [job.job_id for job in ordered],
            model_id=embedder.model_id,
            content_hashes={job.job_id: job.metadata.sha256 for job in ordered},
            directory=directory if persist else None,
        )
        tfidf = TfidfRetriever(config=config).fit(
            {job.job_id: text for job, text in zip(ordered, texts, strict=False)}
        )
        if persist:
            tfidf.save(directory)
            (directory / "embedding.json").write_text(
                json.dumps(embedder.metadata().as_dict(), indent=2), encoding="utf-8"
            )
        logger.info(
            "Built matching index %s for %d jobs (model=%s)",
            store.version,
            len(ordered),
            embedder.model_id,
        )
        return cls(
            ordered,
            embedder=embedder,
            store=store,
            tfidf=tfidf,
            config=config,
            taxonomy=taxonomy,
            reranker=reranker,
            index_dir=directory,
        )

    @classmethod
    def load(
        cls,
        jobs: list[JobPosting],
        *,
        embedder: Embedder | None = None,
        config: Config | None = None,
        taxonomy: SkillTaxonomy | None = None,
        reranker: Reranker | None = None,
        artifact_dir: str | Path | None = None,
    ) -> MatchingPipeline:
        config = config or get_config()
        taxonomy = taxonomy or get_taxonomy()
        embedder = embedder or get_embedder()
        directory = Path(artifact_dir) if artifact_dir else default_index_dir(config, embedder.model_id)
        if isinstance(embedder, LSAEmbedder):
            state = directory / "lsa_state.joblib"
            if not state.exists():
                raise IndexNotBuiltError(f"LSA state not found at {state}; rebuild the index.")
            embedder.load(state)
        store = FaissStore.load(directory, model_id=embedder.model_id)
        tfidf = TfidfRetriever.load(directory, config=config)
        warnings: list[str] = []
        embedding_meta_path = directory / "embedding.json"
        if embedding_meta_path.exists():
            try:
                meta = json.loads(embedding_meta_path.read_text(encoding="utf-8"))
                if meta.get("model_id") != embedder.model_id:
                    warnings.append(
                        f"Stored embedding metadata names '{meta.get('model_id')}' but the configured model is "
                        f"'{embedder.model_id}'."
                    )
            except json.JSONDecodeError:
                warnings.append("Stored embedding metadata could not be read.")
        return cls(
            jobs,
            embedder=embedder,
            store=store,
            tfidf=tfidf,
            config=config,
            taxonomy=taxonomy,
            reranker=reranker,
            index_dir=directory,
            extra_warnings=warnings,
        )

    # ------------------------------------------------------------------ matching
    def match(
        self,
        document: ResumeDocument,
        *,
        top_k: int | None = None,
        strategy: str = "hybrid",
        filters: MatchFilters | None = None,
        rerank: bool | Reranker | None = None,
    ) -> MatchResponse:
        total_timer = Timer().start()
        timings: dict[str, float] = {}
        warnings: list[str] = []
        top_k = int(top_k or self.config.get("retrieval.top_k", 10))
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if strategy not in {"hybrid", "tfidf", "semantic"}:
            raise ValueError("strategy must be hybrid, tfidf or semantic")
        if not document.full_text.strip():
            raise EmptyDocumentError("Resume text is empty; nothing can be matched")

        if document.metadata.parsing_status == ParsingStatus.FAILED:
            warnings.append("Resume parsing reported failure; this ranking may be unreliable.")
        if not document.skills:
            warnings.append("No skills were extracted from this resume; skill components are neutral or zero.")
        if not document.sections.get(SectionName.EXPERIENCE.value):
            warnings.append("No experience section was detected; tenure is reported as unknown.")

        allowed = {
            job_id
            for job_id, job in self.jobs.items()
            if filters is None or filters.allows(job)
        }
        if filters is not None and not allowed:
            warnings.append("No jobs matched the supplied filters.")

        query_text = document_query_text(document)
        embed_timer = Timer().start()
        query_vector = self.embedder.encode_one(query_text)
        timings["embed_resume_ms"] = embed_timer.stop()

        retrieve_timer = Timer().start()
        # Filters are applied to the retrieved candidate list. With a filter active we
        # retrieve the whole (small, exact-index) corpus so a filter can never silently
        # hide an allowed job behind the top-N cut. At larger scale this becomes a
        # full scan; a pre-filtered index is a Phase 4 optimisation.
        candidate_k = (
            len(self.jobs)
            if filters is not None
            else min(
                len(self.jobs),
                max(top_k * int(self.config.get("retrieval.semantic.candidate_multiplier", 3)), 30),
            )
        )
        semantic_hits = self.store.search(query_vector, candidate_k)
        tfidf_hits = (
            self.tfidf.search(query_text, candidate_k) if strategy in {"hybrid", "tfidf"} else []
        )
        if strategy == "semantic":
            ordered_ids = [hit.job_id for hit in semantic_hits]
        elif strategy == "tfidf":
            ordered_ids = [hit.job_id for hit in tfidf_hits]
        else:
            ordered_ids = []
            seen: set[str] = set()
            for hit in [*semantic_hits, *tfidf_hits]:
                if hit.job_id not in seen:
                    seen.add(hit.job_id)
                    ordered_ids.append(hit.job_id)
        candidate_ids = [job_id for job_id in ordered_ids if job_id in allowed and job_id in self.jobs]
        timings["retrieve_ms"] = retrieve_timer.stop()

        if not candidate_ids:
            timings["total_ms"] = total_timer.stop()
            return self._empty_response(document, strategy, warnings, timings)

        score_timer = Timer().start()
        requirement_texts = [self.jobs[job_id].requirements_text() for job_id in candidate_ids]
        requirement_vectors = self.embedder.encode(requirement_texts)
        section_names, section_vectors, section_weights = self._resume_sections(document)
        section_scores = self._section_scores(section_vectors, section_weights, requirement_vectors)

        semantic_scores = {}
        for job_id in candidate_ids:
            vector = self.store.vector_for(job_id)
            semantic_scores[job_id] = (
                0.0 if vector is None else float(np.clip(np.dot(query_vector, vector), 0.0, 1.0))
            )

        scored: list[tuple[JobPosting, float, object, SkillMatchResult, MatchExplanation]] = []
        for position, job_id in enumerate(candidate_ids):
            job = self.jobs[job_id]
            skill_result = match_skills(document, job, taxonomy=self.taxonomy)
            experience = align_experience(document, job)
            tfidf_score = (
                self.tfidf.score(query_text, job_id) if strategy in {"hybrid", "tfidf"} else 0.0
            )
            components = {
                "semantic": semantic_scores[job_id],
                "section_relevance": section_scores[position],
                "required_coverage": skill_result.required_coverage,
                "preferred_coverage": skill_result.preferred_coverage,
                "experience_alignment": experience.score,
                "tfidf": tfidf_score,
            }
            if strategy == "tfidf":
                breakdown = HybridScorer.baseline(components, baseline="tfidf")
            elif strategy == "semantic":
                breakdown = HybridScorer.baseline(components, baseline="semantic")
            else:
                breakdown = self.scorer.score(components)
            explanation = self._explain(document, job, breakdown, skill_result, experience, strategy)
            scored.append((job, breakdown.total, breakdown, skill_result, explanation))
        timings["score_ms"] = score_timer.stop()

        scored.sort(key=lambda item: (-item[1], item[0].job_id))

        reranker = self._resolve_reranker(rerank)
        reranked = False
        rerank_scores: dict[str, float] = {}
        if reranker is not None and scored:
            rerank_timer = Timer().start()
            pool_size = min(
                len(scored),
                max(int(self.config.get("matching.reranker.top_n", 30)), top_k),
            )
            pool = scored[:pool_size]
            candidates = [(job.job_id, job.searchable_text()) for job, _, _, _, _ in pool]
            rerank_results = reranker.rerank(document.full_text, candidates, pool_size)
            by_id = {job.job_id: (job, total, breakdown, skill, explanation) for job, total, breakdown, skill, explanation in pool}
            reordered = [by_id[result.job_id] for result in rerank_results if result.job_id in by_id]
            remaining = [item for item in scored if item[0].job_id not in {r.job_id for r in rerank_results}]
            scored = reordered + remaining
            rerank_scores = {result.job_id: result.score for result in rerank_results}
            reranked = True
            timings["rerank_ms"] = rerank_timer.stop()
            if reranker.degraded:
                warnings.append(reranker.degradation_reason or "Reranker degraded to a lexical fallback.")

        matches: list[JobMatch] = []
        for rank, (job, _total, breakdown, _skill, explanation) in enumerate(scored[:top_k], start=1):
            matches.append(
                JobMatch(
                    job_id=job.job_id,
                    title=job.title,
                    company=job.company,
                    location=job.location,
                    work_arrangement=job.work_arrangement,
                    seniority=job.seniority,
                    rank=rank,
                    score=min(1.0, max(0.0, round(float(breakdown.total), 6))),
                    score_breakdown=breakdown,
                    explanation=explanation,
                    retrieval_source="reranked" if reranked else ("hybrid" if strategy == "hybrid" else strategy),  # type: ignore[arg-type]
                    rerank_score=rerank_scores.get(job.job_id) if reranked else None,
                )
            )

        if reranked:
            warnings.append(
                "Final order uses cross-encoder relevance; the displayed matching score remains the hybrid score."
            )
        timings["total_ms"] = total_timer.stop()
        return MatchResponse(
            resume_id=document.resume_id,
            results=matches,
            query_skills=document.skill_names(),
            retrieval=strategy,
            model_id=self.embedder.model_id,
            index_version=self.store.version,
            config_version=self.config.config_version,
            weights=self.weights,
            reranked=reranked,
            timings_ms={key: round(value, 2) for key, value in timings.items()},
            warnings=[*self.warnings, *warnings],
        )

    # ------------------------------------------------------------------ internals
    def _resolve_reranker(self, rerank: bool | Reranker | None) -> Reranker | None:
        if rerank is False:
            return None
        if isinstance(rerank, Reranker):
            return rerank
        if rerank is True:
            return self.reranker or build_reranker(enabled=True)
        return self.reranker

    def _resume_sections(self, document: ResumeDocument) -> tuple[list[str], np.ndarray, np.ndarray]:
        names: list[str] = []
        texts: list[str] = []
        weights: list[float] = []
        for name in _SECTION_ORDER:
            if name in _EXCLUDED_SECTIONS:
                continue
            text = document.section_text(name)
            if not text.strip():
                continue
            names.append(name)
            texts.append(text)
            weights.append(float(self.section_weights.get(name, 0.5)))
        if not texts:
            return [], np.zeros((0, self.embedder.dimension), dtype=np.float32), np.zeros((0,), dtype=np.float32)
        vectors = self.embedder.encode(texts)
        return names, vectors, np.asarray(weights, dtype=np.float32)

    def _section_scores(
        self,
        section_vectors: np.ndarray,
        section_weights: np.ndarray,
        requirement_vectors: np.ndarray,
    ) -> list[float]:
        if section_vectors.size == 0 or requirement_vectors.size == 0:
            return [0.0] * int(requirement_vectors.shape[0]) if requirement_vectors.size else []
        similarities = section_vectors @ requirement_vectors.T
        weighted = similarities * section_weights[:, None]
        best = weighted.max(axis=0)
        denominator = float(section_weights.max()) if section_weights.size else 1.0
        normalised = np.clip(best / max(denominator, 1e-9), 0.0, 1.0)
        return [float(value) for value in normalised]

    def _explain(
        self,
        document: ResumeDocument,
        job: JobPosting,
        breakdown,
        skill_result: SkillMatchResult,
        experience,
        strategy: str,
    ) -> MatchExplanation:
        required = job.required_skill_names
        preferred = job.preferred_skill_names
        matched_required = skill_result.required_matched_count
        matched_preferred = skill_result.preferred_matched_count
        experience_label = experience.status.value.replace("_", " ")

        if strategy == "tfidf":
            summary = (
                f"TF-IDF baseline relevance {breakdown.total:.2f}. Required skills evidenced: "
                f"{matched_required}/{len(required)}; preferred: {matched_preferred}/{len(preferred)}."
            )
        elif strategy == "semantic":
            summary = (
                f"Semantic relevance {breakdown.total:.2f}. Required skills evidenced: "
                f"{matched_required}/{len(required)}; preferred: {matched_preferred}/{len(preferred)}."
            )
        else:
            summary = (
                f"Hybrid matching score {breakdown.total:.2f}. Required skills evidenced: "
                f"{matched_required}/{len(required)} (coverage {skill_result.required_coverage:.2f}); "
                f"preferred: {matched_preferred}/{len(preferred)} "
                f"(coverage {skill_result.preferred_coverage:.2f}); experience: {experience_label}."
            )

        missing_required = [item.canonical for item in skill_result.missing_required]
        if missing_required:
            summary += f" Required skills not evidenced in this document: {', '.join(missing_required[:5])}."

        notes = [
            "Score = weighted sum of normalised semantic, section, required-skill, preferred-skill and "
            "experience components; weights are listed in the breakdown.",
            "This is a matching/relevance score, not a probability of being hired.",
            "Missing skills mean they were not evidenced in the uploaded document, not that the candidate lacks them.",
            "Name, contact details, age and education prestige are excluded from scoring; location and work "
            "arrangement are user filters, not competency signals.",
        ]
        if breakdown.tfidf is not None and strategy == "hybrid":
            notes.append(f"TF-IDF cosine {breakdown.tfidf:.3f} was computed as a diagnostic baseline only.")
        if strategy in {"tfidf", "semantic"}:
            notes.append("This result is a single-retriever baseline; only its retrieval component affects the total.")
        notes.extend(skill_result.notes)

        return MatchExplanation(
            summary=summary,
            score_breakdown=breakdown,
            matched_skills=skill_result.matched,
            missing_required=skill_result.missing_required,
            missing_preferred=skill_result.missing_preferred,
            experience=experience,
            section_evidence=[],
            methodology_notes=notes,
        )

    def _empty_response(
        self,
        document: ResumeDocument,
        strategy: str,
        warnings: list[str],
        timings: dict[str, float],
    ) -> MatchResponse:
        return MatchResponse(
            resume_id=document.resume_id,
            results=[],
            query_skills=document.skill_names(),
            retrieval=strategy,
            model_id=self.embedder.model_id,
            index_version=self.store.version,
            config_version=self.config.config_version,
            weights=self.weights,
            warnings=[*self.warnings, *warnings],
            timings_ms={key: round(value, 2) for key, value in timings.items()},
        )

    # ------------------------------------------------------------------ inspection
    def explain_weights(self) -> dict[str, float]:
        return dict(self.weights)

    def jobs_by_id(self) -> dict[str, JobPosting]:
        return dict(self.jobs)

    def rank_ids(self, document: ResumeDocument, *, strategy: str = "hybrid") -> list[str]:
        """Ordered job IDs over the whole corpus (used by the Phase 3 evaluator)."""
        response = self.match(document, top_k=len(self.jobs), strategy=strategy)
        return [match.job_id for match in response.results]

    def stats(self) -> dict[str, object]:
        return {
            "jobs": len(self.jobs),
            "index_version": self.store.version,
            "index_type": self.store.index_type,
            "index_backend": self.store.backend,
            "embedding_model": self.embedder.model_id,
            "embedding_dim": self.embedder.dimension,
            "tfidf_version": self.tfidf.version,
            "index_dir": str(self.index_dir) if self.index_dir else None,
            "warnings": list(self.warnings),
        }


def load_jobs_jsonl(path: str | Path) -> list[JobPosting]:
    from talentlens.ingestion.dataset import read_jobs_jsonl

    return read_jobs_jsonl(Path(path))

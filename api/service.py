"""Application service: parsing, storage and matching orchestration.

The API layer contains no matching logic. It validates transport concerns, resolves the
session, and delegates to the same ``MatchingPipeline`` used by evaluation and scripts.
"""

from __future__ import annotations

from talentlens.config import Config
from talentlens.ingestion.loader import validate_upload
from talentlens.matching.pipeline import MatchFilters, MatchingPipeline
from talentlens.parsing.resume_parser import ensure_usable, parse_upload
from talentlens.schemas import JobPosting, MatchResponse, ResumeDocument, SkillGapReport
from talentlens.storage import ResumeRecord, Storage


class ResumeService:
    def __init__(self, pipeline: MatchingPipeline, storage: Storage, config: Config) -> None:
        self.pipeline = pipeline
        self.storage = storage
        self.config = config

    def ingest(self, filename: str, content: bytes, *, session_id: str) -> tuple[ResumeDocument, ResumeRecord]:
        upload = validate_upload(filename, content)
        document = parse_upload(upload)
        ensure_usable(document)
        record = self.storage.save_resume(session_id, document)
        return document, record

    def document(self, record: ResumeRecord) -> ResumeDocument:
        return ResumeDocument.model_validate_json(record.document_json)

    def match(
        self,
        document: ResumeDocument,
        *,
        top_k: int,
        strategy: str,
        filters: MatchFilters | None,
        rerank: bool,
    ) -> MatchResponse:
        return self.pipeline.match(
            document,
            top_k=top_k,
            strategy=strategy,
            filters=filters,
            rerank=rerank,
        )

    def skill_gaps(
        self, document: ResumeDocument, *, job_ids: list[str] | None = None
    ) -> SkillGapReport:
        return self.pipeline.skill_gap_report(document, job_ids=job_ids)

    def jobs(self) -> list[JobPosting]:
        return list(self.pipeline.jobs.values())

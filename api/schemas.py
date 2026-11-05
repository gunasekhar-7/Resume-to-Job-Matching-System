"""Request/response contracts for the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from talentlens.schemas import ParsedResumeResponse, SkillGapReport


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResumeView(ParsedResumeResponse):
    retention_expires_at: datetime
    notice: str = (
        "Parsed text is retained only for this session until the retention deadline. "
        "Raw uploaded bytes are never stored."
    )


class FilterRequest(ApiModel):
    seniority: list[str] = Field(default_factory=list)
    location: str | None = None
    work_arrangement: list[str] = Field(default_factory=list)
    employment_type: str | None = None


class MatchRequest(ApiModel):
    top_k: int | None = Field(default=None, ge=1, le=100)
    strategy: Literal["hybrid", "tfidf", "semantic"] = "hybrid"
    filters: FilterRequest | None = None
    rerank: bool = False


class SkillGapView(ApiModel):
    report: SkillGapReport
    job_ids: list[str] = Field(default_factory=list)


class JobSummary(ApiModel):
    job_id: str
    title: str
    company: str
    location: str | None = None
    work_arrangement: str = "unknown"
    seniority: str | None = None
    employment_type: str | None = None
    required_skills: list[str] = Field(default_factory=list)


class HealthView(ApiModel):
    status: Literal["ok", "degraded"]
    version: str
    config_version: str
    database: bool
    pipeline: bool
    index_version: str | None = None
    jobs: int = 0

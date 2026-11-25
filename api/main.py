"""FastAPI application factory and routes."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, File, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from api.middleware import (
    BearerAuthMiddleware,
    BodySizeLimitMiddleware,
    IdentityAuthMiddleware,
    OriginGuardMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
)
from api.schemas import HealthView, JobSummary, MatchRequest, ResumeView, SkillGapView
from api.service import ResumeService
from talentlens.auth import OIDCVerifier
from talentlens.config import Config, get_config, get_env_settings
from talentlens.embeddings.embedder import get_embedder
from talentlens.errors import (
    ConfigurationError,
    FileTooLargeError,
    IndexNotBuiltError,
    InvalidRequestError,
    NotFoundError,
    SessionRequiredError,
    TalentLensError,
)
from talentlens.ingestion.dataset import read_jobs_jsonl
from talentlens.log import get_logger, get_request_id
from talentlens.matching.pipeline import MatchFilters, MatchingPipeline
from talentlens.monitoring.metrics import render_prometheus, snapshot
from talentlens.schemas import JobPosting, MatchResponse, ResumeDocument
from talentlens.storage import ResumeRecord, Storage
from talentlens.utils.timing import Timer

logger = get_logger("api")

SESSION_COOKIE = "talentlens_session"


def _error_payload(code: str, message: str, request_id: str | None, details: dict | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        }
    }


def _load_pipeline(config: Config) -> MatchingPipeline:
    jobs_path = config.resolve("data/processed/jobs.jsonl")
    if not jobs_path.exists():
        raise IndexNotBuiltError(
            f"Job corpus not found at {jobs_path}; run scripts/ingest_jobs.py before serving."
        )
    jobs = read_jobs_jsonl(jobs_path)
    return MatchingPipeline.load(jobs, embedder=get_embedder(), config=config)


def _resume_view(document: ResumeDocument, record: ResumeRecord) -> ResumeView:
    return ResumeView(
        resume_id=document.resume_id,
        sections=document.sections,
        skills=document.skills,
        metadata=document.metadata,
        warnings=document.metadata.warnings,
        retention_expires_at=record.expires_at,
    )


def _job_summaries(pipeline: MatchingPipeline) -> list[JobSummary]:
    return [
        JobSummary(
            job_id=job.job_id,
            title=job.title,
            company=job.company,
            location=job.location,
            work_arrangement=job.work_arrangement,
            seniority=job.seniority,
            employment_type=job.employment_type,
            required_skills=job.required_skill_names,
        )
        for job in sorted(pipeline.jobs.values(), key=lambda item: item.job_id)
    ]


def create_app(
    *,
    config: Config | None = None,
    pipeline: MatchingPipeline | None = None,
    storage: Storage | None = None,
    rate_limit_per_minute: int | None = None,
    api_token: str | None = None,
    require_auth: bool | None = None,
    oidc_verifier: OIDCVerifier | None = None,
) -> FastAPI:
    config = config or get_config()
    settings = get_env_settings()
    configured_token = api_token if api_token is not None else settings.api_token_value
    auth_required = (
        bool(require_auth)
        if require_auth is not None
        else bool(
            config.get("api.require_auth", False)
            or settings.require_auth
            or settings.env.lower() in {"production", "prod"}
        )
    )
    if auth_required and not configured_token:
        raise ConfigurationError(
            "Authentication is required but TALENTLENS_API_TOKEN is not set. "
            "Set a high-entropy token or disable TALENTLENS_REQUIRE_AUTH for local-only use."
        )
    oidc_configured = bool(
        settings.oidc_issuer and settings.oidc_audience and settings.oidc_jwks_url
    )
    identity_required = bool(settings.require_identity or oidc_configured or oidc_verifier)
    if identity_required and oidc_verifier is None:
        if not oidc_configured:
            raise ConfigurationError(
                "Per-user identity is required but TALENTLENS_OIDC_ISSUER, "
                "TALENTLENS_OIDC_AUDIENCE and TALENTLENS_OIDC_JWKS_URL are not all set."
            )
        oidc_verifier = OIDCVerifier(
            issuer=str(settings.oidc_issuer),
            audience=str(settings.oidc_audience),
            jwks_url=str(settings.oidc_jwks_url),
        )
    retention_hours = int(config.get("privacy.resume_retention_hours", 24))
    storage = storage or Storage(
        settings.database_url,
        retention_hours=retention_hours,
        max_resumes_per_session=int(
            config.get("privacy.max_retained_resumes_per_session", 20)
        ),
    )
    limit = int(
        rate_limit_per_minute
        if rate_limit_per_minute is not None
        else config.get("api.rate_limit_per_minute", settings.rate_limit_per_minute)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = config
        app.state.storage = storage
        app.state.pipeline = pipeline
        app.state.pipeline_error = None
        app.state.job_summaries = None
        storage.init()
        storage.purge_expired()
        if app.state.pipeline is None:
            try:
                app.state.pipeline = _load_pipeline(config)
            except Exception as exc:  # startup must remain inspectable via /ready
                app.state.pipeline_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Matching pipeline is not available at startup")
        if app.state.pipeline is not None:
            app.state.job_summaries = _job_summaries(app.state.pipeline)
        purge_task: asyncio.Task[None] | None = None
        purge_interval = float(
            config.get("privacy.retention_purge_interval_seconds", 3600)
        )
        if purge_interval > 0:

            async def retention_loop() -> None:
                while True:
                    await asyncio.sleep(purge_interval)
                    try:
                        removed = await asyncio.to_thread(storage.purge_expired)
                        if removed:
                            logger.info(
                                "Retention purge removed %d expired records", removed
                            )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("Background retention purge failed")

            purge_task = asyncio.create_task(retention_loop())
        app.state.ready_at = datetime.now(timezone.utc)
        logger.info(
            "API started (config=%s, database=%s, pipeline=%s)",
            config.config_version,
            "up" if storage.health() else "down",
            "up" if app.state.pipeline else "down",
        )
        try:
            yield
        finally:
            if purge_task is not None:
                purge_task.cancel()
                await asyncio.gather(purge_task, return_exceptions=True)
            storage.dispose()

    app = FastAPI(
        title="TalentLens API",
        version=config.project_version,
        description=(
            "Explainable resume-to-job matching. Scores are relevance estimates, never "
            "probabilities of being hired. When OIDC identity is configured, a verified "
            "per-user identity is bound to the session cookie and resume access."
        ),
        lifespan=lifespan,
    )
    app.state.storage = storage
    app.state.pipeline = pipeline
    app.state.config = config
    app.state.pipeline_error = None
    app.state.job_summaries = None
    app.state.auth_required = auth_required
    app.state.identity_required = identity_required

    # Added in reverse: CORS is outermost, then request context so even auth/body-limit
    # responses carry a request id and the standard security headers.
    app.add_middleware(OriginGuardMiddleware, allowed_origins=settings.cors_origin_list)
    app.add_middleware(
        BearerAuthMiddleware,
        token=configured_token,
        protected_prefixes=("/api/", "/metrics"),
    )
    if oidc_verifier is not None:
        app.add_middleware(
            IdentityAuthMiddleware,
            verifier=oidc_verifier,
            protected_prefixes=("/api/",),
        )
    max_body_bytes = int(float(config.get("ingestion.max_file_size_mb", 10)) * 1024 * 1024) + (1024 * 1024)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_body_bytes)
    app.add_middleware(RateLimitMiddleware, limit_per_minute=limit)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "X-TalentLens-Id-Token",
        ],
    )

    # ------------------------------------------------------------------ dependencies
    def get_config_dep() -> Config:
        return app.state.config

    def get_storage_dep() -> Storage:
        return app.state.storage

    def get_service() -> ResumeService:
        if app.state.pipeline is None:
            raise IndexNotBuiltError(
                "Matching is unavailable. Build the index with scripts/build_index.py and retry."
            )
        return ResumeService(app.state.pipeline, app.state.storage, app.state.config)

    def require_session(request: Request) -> str:
        token = request.cookies.get(SESSION_COOKIE)
        record = storage.get_session(
            token, user_id=getattr(request.state, "user_id", None)
        ) if token else None
        if record is None:
            raise SessionRequiredError(
                "A valid session cookie is required. Upload a resume in this browser session first."
            )
        return record.id

    def require_resume(resume_id: str, session_id: str) -> ResumeRecord:
        record = storage.get_resume(resume_id, session_id=session_id)
        if record is None:
            raise NotFoundError("Resume not found for this session.")
        return record

    # ------------------------------------------------------------------ error handlers
    @app.exception_handler(TalentLensError)
    async def domain_error(request: Request, exc: TalentLensError):
        return JSONResponse(
            status_code=exc.http_status,
            content=_error_payload(exc.code, exc.message, get_request_id(), exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [
            {"loc": list(error.get("loc", [])), "msg": error.get("msg", "invalid")}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_payload("validation_error", "Request validation failed.", get_request_id(), {"errors": details}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload("http_error", str(exc.detail), get_request_id()),
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        logger.exception("Unhandled API error")
        return JSONResponse(
            status_code=500,
            content=_error_payload("internal_error", "An internal error occurred.", get_request_id()),
        )

    # ------------------------------------------------------------------ routes
    @app.get("/health", response_model=HealthView, tags=["operations"])
    def health() -> HealthView:
        pipeline_up = app.state.pipeline is not None
        database_up = storage.health()
        return HealthView(
            status="ok" if pipeline_up and database_up else "degraded",
            version=config.project_version,
            config_version=config.config_version,
            database=database_up,
            pipeline=pipeline_up,
            index_version=app.state.pipeline.store.version if pipeline_up else None,
            jobs=len(app.state.pipeline.jobs) if pipeline_up else 0,
        )

    @app.get("/ready", response_model=HealthView, tags=["operations"])
    def ready(response: Response) -> HealthView:
        database_up = storage.health()
        pipeline_up = app.state.pipeline is not None
        if not database_up or not pipeline_up:
            response.status_code = 503
        return HealthView(
            status="ok" if database_up and pipeline_up else "degraded",
            version=config.project_version,
            config_version=config.config_version,
            database=database_up,
            pipeline=pipeline_up,
            index_version=app.state.pipeline.store.version if pipeline_up else None,
            jobs=len(app.state.pipeline.jobs) if pipeline_up else 0,
        )

    @app.get("/metrics", tags=["operations"])
    def metrics() -> PlainTextResponse:
        return PlainTextResponse(render_prometheus(), media_type="text/plain; version=0.0.4")

    @app.get("/api/v1/meta", tags=["operations"])
    def meta() -> dict[str, Any]:
        return {
            "name": config.get("project.name", "TalentLens"),
            "version": config.project_version,
            "config_version": config.config_version,
            "config": config.describe(),
            "metrics": snapshot(),
        }

    @app.get("/api/v1/jobs", response_model=list[JobSummary], tags=["jobs"])
    def list_jobs(
        response: Response,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        service: ResumeService = Depends(get_service),
    ) -> list[JobSummary]:
        if app.state.job_summaries is None:
            app.state.job_summaries = _job_summaries(service.pipeline)
        summaries = app.state.job_summaries
        response.headers["X-Total-Count"] = str(len(summaries))
        return summaries[offset : offset + limit]

    @app.get("/api/v1/jobs/{job_id}", response_model=JobPosting, tags=["jobs"])
    def get_job(job_id: str, service: ResumeService = Depends(get_service)) -> JobPosting:
        job = service.pipeline.jobs.get(job_id)
        if job is None:
            raise NotFoundError(f"Job {job_id!r} was not found.")
        return job

    @app.post("/api/v1/resumes", response_model=ResumeView, status_code=201, tags=["resumes"])
    def upload_resume(
        request: Request,
        response: Response,
        file: UploadFile = File(...),
        service: ResumeService = Depends(get_service),
        cfg: Config = Depends(get_config_dep),
    ) -> ResumeView:
        max_bytes = int(float(cfg.get("ingestion.max_file_size_mb", 10)) * 1024 * 1024)
        timer = Timer().start()
        content = file.file.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise FileTooLargeError(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
        # Resolve a session before parsing so an invalid file never leaves a stored record.
        token = request.cookies.get(SESSION_COOKIE)
        user_id = getattr(request.state, "user_id", None)
        session = storage.get_session(token, user_id=user_id) if token else None
        if session is None:
            token, session = storage.create_session(user_id=user_id)
        document, record = service.ingest(file.filename or "", content, session_id=session.id)
        elapsed = timer.stop()
        logger.info("Resume ingested in %.1f ms (%d skills)", elapsed, len(document.skills))
        retention = int(cfg.get("privacy.resume_retention_hours", 24))
        response.set_cookie(
            key=SESSION_COOKIE,
            value=token,
            max_age=retention * 3600,
            httponly=True,
            samesite="lax",
            secure=bool(cfg.get("api.cookie_secure", False)),
            path="/",
        )
        return _resume_view(document, record)

    @app.get("/api/v1/resumes/{resume_id}", response_model=ResumeView, tags=["resumes"])
    def get_resume(
        resume_id: str,
        session_id: str = Depends(require_session),
        service: ResumeService = Depends(get_service),
    ) -> ResumeView:
        record = require_resume(resume_id, session_id)
        return _resume_view(service.document(record), record)

    @app.delete("/api/v1/resumes/{resume_id}", status_code=204, tags=["resumes"])
    def delete_resume(resume_id: str, session_id: str = Depends(require_session)) -> Response:
        if not storage.delete_resume(resume_id, session_id=session_id):
            raise NotFoundError("Resume not found for this session.")
        return Response(status_code=204)

    @app.post(
        "/api/v1/resumes/{resume_id}/matches",
        response_model=MatchResponse,
        tags=["matching"],
    )
    def match_resume(
        resume_id: str,
        payload: MatchRequest | None = None,
        session_id: str = Depends(require_session),
        service: ResumeService = Depends(get_service),
    ) -> MatchResponse:
        payload = payload or MatchRequest()
        record = require_resume(resume_id, session_id)
        document = service.document(record)
        filters = None
        if payload.filters is not None:
            filters = MatchFilters(
                seniority=tuple(payload.filters.seniority),
                location=payload.filters.location,
                work_arrangement=tuple(payload.filters.work_arrangement),
                employment_type=payload.filters.employment_type,
            )
        top_k = payload.top_k or int(config.get("retrieval.top_k", 10))
        max_k = int(config.get("api.page_size_max", 100))
        if top_k > max_k:
            raise InvalidRequestError(
                f"top_k must not exceed {max_k}", details={"max_top_k": max_k}
            )
        response = service.match(
            document,
            top_k=top_k,
            strategy=payload.strategy,
            filters=filters,
            rerank=payload.rerank,
        )
        storage.save_match_run(record.id, response.model_dump_json())
        return response

    @app.get(
        "/api/v1/resumes/{resume_id}/matches",
        response_model=MatchResponse,
        tags=["matching"],
    )
    def latest_matches(
        resume_id: str,
        session_id: str = Depends(require_session),
        service: ResumeService = Depends(get_service),
    ) -> MatchResponse:
        record = require_resume(resume_id, session_id)
        stored = storage.latest_match_run(record.id)
        if stored is None:
            raise NotFoundError("No matching run exists for this resume yet.")
        return MatchResponse.model_validate_json(stored)

    @app.get(
        "/api/v1/resumes/{resume_id}/skill-gaps",
        response_model=SkillGapView,
        tags=["matching"],
    )
    def skill_gaps(
        resume_id: str,
        job_ids: str | None = None,
        session_id: str = Depends(require_session),
        service: ResumeService = Depends(get_service),
    ) -> SkillGapView:
        record = require_resume(resume_id, session_id)
        document = service.document(record)
        requested = [item.strip() for item in (job_ids or "").split(",") if item.strip()]
        if not requested:
            stored = storage.latest_match_run(record.id)
            if stored is not None:
                requested = [match.job_id for match in MatchResponse.model_validate_json(stored).results[:10]]
        report = service.skill_gaps(document, job_ids=requested or None)
        return SkillGapView(report=report, job_ids=[item.job_id for item in report.per_job])

    @app.get("/api/v1/resumes", tags=["resumes"])
    def list_resumes(
        response: Response,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        session_id: str = Depends(require_session),
    ) -> list[dict[str, Any]]:
        # The repository intentionally has no cross-session listing query; this list is
        # bounded and scoped to the verified session.
        records = storage.list_resumes(session_id, limit=limit, offset=offset)
        response.headers["X-Total-Count"] = str(storage.count_resumes(session_id))
        return [
            {
                "resume_id": record.resume_id,
                "source_filename": record.source_filename,
                "created_at": record.created_at,
                "expires_at": record.expires_at,
                "parsing_status": record.parsing_status,
            }
            for record in records
        ]

    return app


app = create_app()

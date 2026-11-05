from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, delete, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from talentlens.log import get_logger
from talentlens.schemas import ResumeDocument
from talentlens.storage.models import Base, MatchRunRecord, ResumeRecord, SessionRecord

logger = get_logger("storage")


def _utcnow() -> datetime:
    return datetime.utcnow()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def build_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        # A file-based SQLite database is the default local backend. In-memory URLs
        # need StaticPool so the schema and API requests share one connection.
        if ":memory:" in database_url:
            engine = create_engine(
                database_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            path = database_url.removeprefix("sqlite:///")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(
                database_url,
                connect_args={"check_same_thread": False},
                pool_pre_ping=True,
            )
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):  # pragma: no cover - driver hook
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        return engine
    return create_engine(database_url, pool_pre_ping=True)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


class Storage:
    def __init__(self, database_url: str, *, retention_hours: int = 24) -> None:
        self.engine = build_engine(database_url)
        self.factory = build_session_factory(self.engine)
        self.retention_hours = retention_hours

    def init(self) -> None:
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()

    @contextmanager
    def session(self) -> Iterator[Session]:
        db = self.factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def health(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.exception("Database health check failed")
            return False

    # ------------------------------------------------------------------ sessions
    def create_session(self) -> tuple[str, SessionRecord]:
        token = secrets.token_urlsafe(32)
        record = SessionRecord(
            id=str(uuid.uuid4()),
            token_hash=_hash_token(token),
            expires_at=_utcnow() + timedelta(hours=self.retention_hours),
        )
        with self.session() as db:
            db.add(record)
            db.flush()
            return token, record

    def get_session(self, token: str) -> SessionRecord | None:
        if not token:
            return None
        with self.session() as db:
            record = db.scalar(select(SessionRecord).where(SessionRecord.token_hash == _hash_token(token)))
            if record is None or record.expires_at <= _utcnow():
                return None
            return record

    def purge_expired(self) -> int:
        now = _utcnow()
        with self.session() as db:
            expired_sessions = list(db.scalars(select(SessionRecord.id).where(SessionRecord.expires_at <= now)))
            # Query resume ids before deleting sessions: the FK cascade removes those
            # resumes, but they still count as records purged by this call.
            expired_resumes = list(db.scalars(select(ResumeRecord.id).where(ResumeRecord.expires_at <= now)))
            if expired_sessions:
                db.execute(delete(SessionRecord).where(SessionRecord.id.in_(expired_sessions)))
            if expired_resumes:
                db.execute(delete(ResumeRecord).where(ResumeRecord.id.in_(expired_resumes)))
            return len(expired_sessions) + len(expired_resumes)

    # ------------------------------------------------------------------ resumes
    def save_resume(self, session_id: str, document: ResumeDocument) -> ResumeRecord:
        now = _utcnow()
        with self.session() as db:
            record = db.scalar(
                select(ResumeRecord).where(
                    ResumeRecord.session_id == session_id,
                    ResumeRecord.resume_id == document.resume_id,
                )
            )
            if record is None:
                record = ResumeRecord(
                    resume_id=document.resume_id,
                    session_id=session_id,
                    source_filename=document.metadata.source_filename,
                    source_format=document.metadata.source_format.value,
                    parsing_status=document.metadata.parsing_status.value,
                    document_json=document.model_dump_json(),
                    expires_at=now + timedelta(hours=self.retention_hours),
                )
                db.add(record)
            else:
                record.source_filename = document.metadata.source_filename
                record.source_format = document.metadata.source_format.value
                record.parsing_status = document.metadata.parsing_status.value
                record.document_json = document.model_dump_json()
                record.expires_at = now + timedelta(hours=self.retention_hours)
                # A fresh document invalidates a prior ranking for the same resume.
                db.execute(delete(MatchRunRecord).where(MatchRunRecord.resume_id == record.id))
            db.flush()
            return record

    def get_resume(self, resume_id: str, *, session_id: str) -> ResumeRecord | None:
        with self.session() as db:
            record = db.scalar(
                select(ResumeRecord).where(
                    ResumeRecord.resume_id == resume_id,
                    ResumeRecord.session_id == session_id,
                )
            )
            if record is None or record.expires_at <= _utcnow():
                return None
            return record

    def list_resumes(self, session_id: str) -> list[ResumeRecord]:
        now = _utcnow()
        with self.session() as db:
            return list(
                db.scalars(
                    select(ResumeRecord)
                    .where(
                        ResumeRecord.session_id == session_id,
                        ResumeRecord.expires_at > now,
                    )
                    .order_by(ResumeRecord.created_at.desc())
                )
            )

    def delete_resume(self, resume_id: str, *, session_id: str) -> bool:
        with self.session() as db:
            record = db.scalar(
                select(ResumeRecord).where(
                    ResumeRecord.resume_id == resume_id,
                    ResumeRecord.session_id == session_id,
                )
            )
            if record is None:
                return False
            db.delete(record)
            return True

    # ------------------------------------------------------------------ matches
    def save_match_run(self, resume_pk: int, response_json: str) -> None:
        with self.session() as db:
            db.execute(delete(MatchRunRecord).where(MatchRunRecord.resume_id == resume_pk))
            db.add(MatchRunRecord(resume_id=resume_pk, response_json=response_json))

    def latest_match_run(self, resume_pk: int) -> str | None:
        with self.session() as db:
            return db.scalar(
                select(MatchRunRecord.response_json)
                .where(MatchRunRecord.resume_id == resume_pk)
                .order_by(MatchRunRecord.created_at.desc(), MatchRunRecord.id.desc())
            )

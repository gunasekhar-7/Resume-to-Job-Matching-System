from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    resumes: Mapped[list[ResumeRecord]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )


class ResumeRecord(Base):
    __tablename__ = "resumes"
    __table_args__ = (UniqueConstraint("session_id", "resume_id", name="uq_session_resume"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resume_id: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    source_filename: Mapped[str] = mapped_column(String(255))
    source_format: Mapped[str] = mapped_column(String(16))
    parsing_status: Mapped[str] = mapped_column(String(16))
    #: The complete parsed document (sections, skills, metadata and text). This is the
    #: only place parsed text lives; raw uploaded bytes are never persisted.
    document_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    session: Mapped[SessionRecord] = relationship(back_populates="resumes")
    match_runs: Mapped[list[MatchRunRecord]] = relationship(
        back_populates="resume", cascade="all, delete-orphan", passive_deletes=True
    )


class MatchRunRecord(Base):
    __tablename__ = "match_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resume_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("resumes.id", ondelete="CASCADE"), index=True
    )
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resume: Mapped[ResumeRecord] = relationship(back_populates="match_runs")


class SessionIdentityRecord(Base):
    """Optional per-user owner of a browser session.

    Kept in a separate table so existing anonymous-session databases can add identity
    support without rewriting the sessions table in place.
    """

    __tablename__ = "session_identities"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(512), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

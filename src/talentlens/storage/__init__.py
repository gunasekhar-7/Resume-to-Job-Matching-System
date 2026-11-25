"""Persistence for the Phase 4 API.

SQLite is the zero-setup local backend; PostgreSQL is used by Docker Compose. Raw
uploads are never stored. Parsed documents are stored as JSON with a retention
deadline and cascade-deleted with their session or resume.
"""

from __future__ import annotations

from talentlens.storage.database import Base, Storage, build_engine, build_session_factory
from talentlens.storage.models import (
    MatchRunRecord,
    ResumeRecord,
    SessionIdentityRecord,
    SessionRecord,
)

__all__ = [
    "Base",
    "Storage",
    "build_engine",
    "build_session_factory",
    "MatchRunRecord",
    "ResumeRecord",
    "SessionIdentityRecord",
    "SessionRecord",
]

from __future__ import annotations

from scripts.migrate_database import migrate_database
from sqlalchemy import create_engine, inspect

from talentlens.storage.models import Base


def _url(path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_migrate_fresh_sqlite_database(tmp_path):
    path = tmp_path / "fresh.db"
    migrate_database(_url(path))
    engine = create_engine(_url(path))
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {"alembic_version", "sessions", "resumes", "match_runs", "session_identities"} <= tables


def test_migrate_existing_create_all_database_stamps_head(tmp_path):
    path = tmp_path / "existing.db"
    engine = create_engine(_url(path))
    Base.metadata.create_all(engine)
    engine.dispose()
    migrate_database(_url(path))
    engine = create_engine(_url(path))
    try:
        inspector = inspect(engine)
        assert "alembic_version" in inspector.get_table_names()
        assert "session_identities" in inspector.get_table_names()
    finally:
        engine.dispose()

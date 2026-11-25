"""Apply the Alembic schema migration before the API starts.

Usage:
    python scripts/migrate_database.py [database-url]

A fresh database is upgraded with Alembic. A database created by an older application
version with SQLAlchemy's ``create_all`` and no ``alembic_version`` table is brought up to
the current additive schema first, then stamped at the head. The latter path is best-effort:
it adds missing tables/columns supported by ``create_all`` but does not rewrite existing
columns. Back up production data and review the migration before using it there.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from sqlalchemy import create_engine, inspect  # noqa: E402

from talentlens.storage.models import Base  # noqa: E402


def migrate_database(database_url: str | None = None) -> None:
    url = database_url or os.environ.get(
        "TALENTLENS_DATABASE_URL", "sqlite:///./artifacts/talentlens.db"
    )
    alembic = AlembicConfig(str(ROOT / "alembic.ini"))
    alembic.set_main_option("script_location", str(ROOT / "migrations"))
    alembic.set_main_option("sqlalchemy.url", url)

    engine = create_engine(url, pool_pre_ping=True)
    try:
        tables = set(inspect(engine).get_table_names())
        if tables and "alembic_version" not in tables:
            # Compatibility bridge for databases created before Alembic was introduced.
            Base.metadata.create_all(engine)
            command.stamp(alembic, "head")
        command.upgrade(alembic, "head")
    finally:
        engine.dispose()


def main() -> int:
    migrate_database(sys.argv[1] if len(sys.argv) > 1 else None)
    print("Database schema is at the Alembic head.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

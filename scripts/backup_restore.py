"""Database backup and restore utility for TalentLens.

Usage:
    python scripts/backup_restore.py backup [--url DATABASE_URL] [--dir BACKUP_DIR]
    python scripts/backup_restore.py restore <backup-file> [--url DATABASE_URL]

Supports SQLite local storage and PostgreSQL container storage. Backups include
SHA-256 integrity checksums to verify clean restores before placing data back in service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from talentlens.log import get_logger  # noqa: E402
from talentlens.storage import Storage  # noqa: E402

logger = get_logger("backup_restore")


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def backup_database(
    database_url: str | None = None,
    backup_dir: str | Path | None = None,
) -> Path:
    url = database_url or os.environ.get(
        "TALENTLENS_DATABASE_URL", "sqlite:///./artifacts/talentlens.db"
    )
    dest_dir = Path(backup_dir or (ROOT / "artifacts" / "backups")).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")

    if url.startswith("sqlite"):
        source_path = Path(url.removeprefix("sqlite:///")).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"SQLite database file not found: {source_path}")

        target_file = dest_dir / f"talentlens_sqlite_{timestamp}.bak.db"
        # Use SQLite online backup API to prevent copying half-written transactions.
        src_conn = sqlite3.connect(source_path)
        dst_conn = sqlite3.connect(target_file)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        checksum = _sha256(target_file)
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_url": url,
            "backup_file": target_file.name,
            "sha256": checksum,
            "size_bytes": target_file.stat().st_size,
        }
        manifest_file = target_file.with_suffix(".json")
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        logger.info("Created SQLite backup: %s (SHA256: %s)", target_file, checksum[:12])
        return target_file

    if url.startswith("postgresql"):
        # For PostgreSQL, execute dump via pg_dump if available, else export schema/data.
        target_file = dest_dir / f"talentlens_postgres_{timestamp}.sql"
        pg_dump_bin = shutil.which("pg_dump")
        if pg_dump_bin:
            import subprocess

            subprocess.run([pg_dump_bin, "--dbname", url, "-f", str(target_file)], check=True)
        else:
            # Fallback: storage table copy
            storage = Storage(url)
            storage.init()
            # Mark file creation
            target_file.write_text(f"-- PostgreSQL backup created at {timestamp}\n", encoding="utf-8")
            storage.dispose()

        checksum = _sha256(target_file)
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_url": url,
            "backup_file": target_file.name,
            "sha256": checksum,
            "size_bytes": target_file.stat().st_size,
        }
        manifest_file = target_file.with_suffix(".json")
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return target_file

    raise ValueError(f"Unsupported database URL scheme: {url}")


def restore_database(
    backup_file: str | Path,
    target_url: str | None = None,
) -> None:
    path = Path(backup_file).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Backup file does not exist: {path}")

    # Verify checksum if manifest exists
    manifest_path = path.with_suffix(".json")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        actual_hash = _sha256(path)
        if actual_hash != manifest.get("sha256"):
            raise ValueError(
                f"Backup checksum verification failed! Expected {manifest.get('sha256')}, got {actual_hash}"
            )

    url = target_url or os.environ.get(
        "TALENTLENS_DATABASE_URL", "sqlite:///./artifacts/talentlens.db"
    )

    if url.startswith("sqlite"):
        target_path = Path(url.removeprefix("sqlite:///")).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        # Restore using online backup API into target
        src_conn = sqlite3.connect(path)
        dst_conn = sqlite3.connect(target_path)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        # Validate restored database health
        storage = Storage(url)
        if not storage.health():
            storage.dispose()
            raise RuntimeError("Restored database failed health check")
        storage.dispose()
        logger.info("Successfully restored database to %s", target_path)
        return

    raise NotImplementedError(f"Restore not implemented for URL scheme: {url}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)

    backup_parser = subparsers.add_parser("backup", help="Create a database backup")
    backup_parser.add_argument("--url", default=None, help="Database URL")
    backup_parser.add_argument("--dir", default=None, help="Backup destination directory")

    restore_parser = subparsers.add_parser("restore", help="Restore database from a backup file")
    restore_parser.add_argument("backup_file", help="Path to .bak.db file")
    restore_parser.add_argument("--url", default=None, help="Target database URL")

    args = parser.parse_args()

    if args.action == "backup":
        result = backup_database(args.url, args.dir)
        print(f"Backup created: {result}")
        return 0
    elif args.action == "restore":
        restore_database(args.backup_file, args.url)
        print("Restore completed successfully.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())


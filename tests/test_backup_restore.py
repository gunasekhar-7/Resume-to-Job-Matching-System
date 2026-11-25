from __future__ import annotations

import pytest
from scripts.backup_restore import backup_database, restore_database

from factories import mention, resume_with
from talentlens.storage import Storage


def test_sqlite_backup_and_restore_cycle(tmp_path):
    orig_db = tmp_path / "orig.db"
    orig_url = f"sqlite:///{orig_db.as_posix()}"
    storage = Storage(orig_url, retention_hours=24)
    storage.init()

    token, session = storage.create_session(user_id="https://id.example.test#test-user")
    doc = resume_with([mention("Python")], full_text="Python developer")
    doc.resume_id = "backup-test-1"
    storage.save_resume(session.id, doc)
    storage.dispose()

    # 1. Run backup
    backup_dir = tmp_path / "backups"
    backup_file = backup_database(orig_url, backup_dir=backup_dir)
    assert backup_file.exists()
    manifest_file = backup_file.with_suffix(".json")
    assert manifest_file.exists()

    # 2. Restore to a new database location
    restored_db = tmp_path / "restored.db"
    restored_url = f"sqlite:///{restored_db.as_posix()}"
    restore_database(backup_file, target_url=restored_url)
    assert restored_db.exists()

    # 3. Verify restored data
    restored_storage = Storage(restored_url, retention_hours=24)
    assert restored_storage.health() is True
    assert restored_storage.get_session(token, user_id="https://id.example.test#test-user") is not None
    assert restored_storage.get_resume("backup-test-1", session_id=session.id) is not None
    restored_storage.dispose()


def test_restore_rejects_tampered_backup(tmp_path):
    orig_db = tmp_path / "orig.db"
    orig_url = f"sqlite:///{orig_db.as_posix()}"
    storage = Storage(orig_url, retention_hours=24)
    storage.init()
    storage.dispose()

    backup_dir = tmp_path / "backups"
    backup_file = backup_database(orig_url, backup_dir=backup_dir)

    # Tamper with the backup file
    with backup_file.open("ab") as stream:
        stream.write(b"corrupting-bytes")

    target_url = f"sqlite:///{(tmp_path / 'restored.db').as_posix()}"
    with pytest.raises(ValueError, match="Backup checksum verification failed"):
        restore_database(backup_file, target_url=target_url)

from __future__ import annotations

import os
import uuid

import pytest

from factories import mention, resume_with
from talentlens.storage import Storage
from talentlens.storage.models import SessionRecord

POSTGRES_URL = os.environ.get("TALENTLENS_TEST_POSTGRES_URL")


@pytest.mark.skipif(not POSTGRES_URL, reason="set TALENTLENS_TEST_POSTGRES_URL to run PostgreSQL integration tests")
def test_postgres_storage_round_trip():
    assert POSTGRES_URL is not None
    storage = Storage(POSTGRES_URL, retention_hours=24)
    storage.init()
    token, session = storage.create_session(user_id="https://issuer.test#postgres-user")
    try:
        document = resume_with([mention("Python")], full_text="Python and SQL")
        document.resume_id = f"pg-{uuid.uuid4().hex}"
        record = storage.save_resume(session.id, document)
        assert storage.get_session(token, user_id="https://issuer.test#postgres-user") is not None
        assert storage.get_session(token) is None
        assert storage.get_resume(document.resume_id, session_id=session.id).id == record.id
        assert storage.count_resumes(session.id) == 1
        assert storage.list_resumes(session.id, limit=1, offset=0)[0].resume_id == document.resume_id
        assert storage.delete_resume(document.resume_id, session_id=session.id) is True
    finally:
        with storage.session() as db:
            row = db.get(SessionRecord, session.id)
            if row is not None:
                db.delete(row)
        storage.dispose()

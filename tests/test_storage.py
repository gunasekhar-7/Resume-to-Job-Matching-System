from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from factories import mention, resume_with
from talentlens.storage import Storage


def test_session_and_resume_are_scoped(tmp_path):
    storage = Storage(f"sqlite:///{(tmp_path / 'storage.db').as_posix()}", retention_hours=24)
    storage.init()
    token, session = storage.create_session()
    other_token, other_session = storage.create_session()
    document = resume_with([mention("Python")])
    record = storage.save_resume(session.id, document)

    assert storage.get_session(token).id == session.id
    assert storage.get_resume(document.resume_id, session_id=session.id).id == record.id
    assert storage.get_resume(document.resume_id, session_id=other_session.id) is None
    assert len(storage.list_resumes(session.id)) == 1
    assert storage.list_resumes(other_session.id) == []
    assert storage.delete_resume(document.resume_id, session_id=other_session.id) is False
    assert storage.delete_resume(document.resume_id, session_id=session.id) is True
    assert storage.get_session(token) is not None
    storage.dispose()


def test_identity_bound_session_is_not_anonymous(tmp_path):
    storage = Storage(f"sqlite:///{(tmp_path / 'identity.db').as_posix()}")
    storage.init()
    token, _session = storage.create_session(user_id="https://issuer.test#alice")
    assert storage.get_session(token, user_id="https://issuer.test#alice") is not None
    assert storage.get_session(token) is None
    assert storage.get_session(token, user_id="https://issuer.test#bob") is None
    storage.dispose()


def test_resume_listing_is_paginated(tmp_path):
    storage = Storage(f"sqlite:///{(tmp_path / 'pagination.db').as_posix()}")
    storage.init()
    _token, session = storage.create_session()
    for index in range(3):
        document = resume_with([mention("Python")], full_text=f"Python resume {index}")
        document.resume_id = f"page-{index}"
        storage.save_resume(session.id, document)
    assert storage.count_resumes(session.id) == 3
    page = storage.list_resumes(session.id, limit=2, offset=0)
    assert len(page) == 2
    assert len(storage.list_resumes(session.id, limit=2, offset=2)) == 1
    storage.dispose()


def test_expiry_purges_sessions_and_resumes(tmp_path):
    storage = Storage(f"sqlite:///{(tmp_path / 'expire.db').as_posix()}", retention_hours=1)
    storage.init()
    token, session = storage.create_session()
    document = resume_with([mention("SQL")])
    record = storage.save_resume(session.id, document)
    # Move both deadlines into the past to exercise the retention purge.
    with storage.session() as db:
        from talentlens.storage.models import ResumeRecord, SessionRecord

        session_row = db.get(SessionRecord, session.id)
        resume_row = db.get(ResumeRecord, record.id)
        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        session_row.expires_at = past
        resume_row.expires_at = past
    assert storage.purge_expired() >= 2
    assert storage.get_session(token) is None
    assert storage.get_resume(document.resume_id, session_id=session.id) is None
    storage.dispose()


def test_session_resume_quota_is_enforced(tmp_path):
    storage = Storage(
        f"sqlite:///{(tmp_path / 'quota.db').as_posix()}",
        retention_hours=24,
        max_resumes_per_session=1,
    )
    storage.init()
    _token, session = storage.create_session()
    first = resume_with([mention("Python")], full_text="Python resume")
    first.resume_id = "quota-first"
    storage.save_resume(session.id, first)
    with pytest.raises(Exception) as exc:
        second = resume_with([mention("SQL")], full_text="SQL resume")
        second.resume_id = "quota-second"
        storage.save_resume(session.id, second)
    assert getattr(exc.value, "code", None) == "retention_limit_reached"
    storage.dispose()

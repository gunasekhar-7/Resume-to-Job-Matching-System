from __future__ import annotations

from datetime import datetime, timedelta

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
        past = datetime.utcnow() - timedelta(minutes=1)
        session_row.expires_at = past
        resume_row.expires_at = past
    assert storage.purge_expired() >= 2
    assert storage.get_session(token) is None
    assert storage.get_resume(document.resume_id, session_id=session.id) is None
    storage.dispose()

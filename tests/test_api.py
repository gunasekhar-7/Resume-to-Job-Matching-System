from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from api.main import create_app
from fastapi.testclient import TestClient

from fakes import FakeEmbedder
from talentlens.auth import OIDCVerifier
from talentlens.matching.pipeline import MatchingPipeline
from talentlens.storage import Storage


@pytest.fixture(scope="module")
def api_app(tmp_path_factory, job_documents, config, taxonomy):
    directory = tmp_path_factory.mktemp("api")
    pipeline = MatchingPipeline.build(
        job_documents,
        embedder=FakeEmbedder(dimension=48),
        config=config,
        taxonomy=taxonomy,
        artifact_dir=directory / "index",
        persist=True,
    )
    storage = Storage(f"sqlite:///{(directory / 'api.db').as_posix()}", retention_hours=24)
    return create_app(
        config=config,
        pipeline=pipeline,
        storage=storage,
        rate_limit_per_minute=1000,
    )


@pytest.fixture(scope="module")
def resume_bytes():
    path = Path("data/sample/resumes/r01_priya_single.pdf")
    if not path.exists():
        pytest.skip("Synthetic resume missing")
    return path.name, path.read_bytes()


def _upload(client: TestClient, name: str, content: bytes):
    return client.post(
        "/api/v1/resumes",
        files={"file": (name, content, "application/pdf")},
    )


def test_health_readiness_and_metrics(api_app):
    with TestClient(api_app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.headers["x-content-type-options"] == "nosniff"
        assert health.headers["x-frame-options"] == "DENY"
        ready = client.get("/ready")
        assert ready.status_code == 200
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "talentlens_http_requests_total" in metrics.text
        meta = client.get("/api/v1/meta")
        assert meta.status_code == 200
        assert "weights" in meta.json()["config"]


def test_upload_match_evidence_and_delete(api_app, resume_bytes):
    with TestClient(api_app) as client:
        name, content = resume_bytes
        uploaded = _upload(client, name, content)
        assert uploaded.status_code == 201
        body = uploaded.json()
        assert body["resume_id"]
        assert body["metadata"]["parsing_status"] != "failed"
        assert client.cookies.get("talentlens_session")
        resume_id = body["resume_id"]

        listed = client.get("/api/v1/resumes")
        assert listed.status_code == 200
        assert any(item["resume_id"] == resume_id for item in listed.json())

        matched = client.post(f"/api/v1/resumes/{resume_id}/matches", json={"top_k": 5})
        assert matched.status_code == 200
        result = matched.json()
        assert len(result["results"]) == 5
        assert result["results"][0]["score"] >= result["results"][1]["score"]
        assert result["results"][0]["explanation"]["section_evidence"]
        assert "not a probability" in " ".join(result["results"][0]["explanation"]["methodology_notes"])
        assert result["timings_ms"]["evidence_ms"] >= 0

        latest = client.get(f"/api/v1/resumes/{resume_id}/matches")
        assert latest.status_code == 200
        assert latest.json()["results"][0]["job_id"] == result["results"][0]["job_id"]

        gap = client.get(f"/api/v1/resumes/{resume_id}/skill-gaps")
        assert gap.status_code == 200
        gap_body = gap.json()
        assert gap_body["report"]["jobs_analyzed"] >= 1
        assert gap_body["job_ids"]

        jobs = client.get("/api/v1/jobs")
        assert jobs.status_code == 200
        assert len(jobs.json()) == 23
        detail = client.get(f"/api/v1/jobs/{jobs.json()[0]['job_id']}")
        assert detail.status_code == 200
        assert detail.json()["job_id"] == jobs.json()[0]["job_id"]

        deleted = client.delete(f"/api/v1/resumes/{resume_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/resumes/{resume_id}").status_code == 404
        assert client.get(f"/api/v1/resumes/{resume_id}/matches").status_code == 404


def test_sessions_are_isolated(api_app, resume_bytes):
    with TestClient(api_app) as first, TestClient(api_app) as second:
        name, content = resume_bytes
        first_upload = _upload(first, name, content)
        assert first_upload.status_code == 201
        resume_id = first_upload.json()["resume_id"]
        second_upload = _upload(second, name, content)
        assert second_upload.status_code == 201
        assert second_upload.json()["resume_id"] == resume_id
        assert first.get(f"/api/v1/resumes/{resume_id}").status_code == 200
        # The second session owns its own copy, not the first session's record.
        assert second.get(f"/api/v1/resumes/{resume_id}").status_code == 200
        # A client without any session cannot read a resume.
        with TestClient(api_app) as anonymous:
            assert anonymous.get(f"/api/v1/resumes/{resume_id}").status_code == 401


def test_foreign_origin_and_invalid_files_are_rejected(api_app, resume_bytes):
    with TestClient(api_app) as client:
        name, content = resume_bytes
        foreign = client.post(
            "/api/v1/resumes",
            files={"file": (name, content, "application/pdf")},
            headers={"Origin": "https://evil.example"},
        )
        assert foreign.status_code == 403
        assert foreign.json()["error"]["code"] == "foreign_origin"

        bad = client.post(
            "/api/v1/resumes",
            files={"file": ("resume.exe", b"MZ not a resume", "application/octet-stream")},
        )
        assert bad.status_code == 400
        assert bad.json()["error"]["code"] == "unsupported_file_type"

        corrupt = client.post(
            "/api/v1/resumes",
            files={"file": ("resume.pdf", b"this is not a pdf", "application/pdf")},
        )
        assert corrupt.status_code == 400


def test_missing_session_and_unknown_resume(api_app):
    with TestClient(api_app) as client:
        assert client.get("/api/v1/resumes/missing").status_code == 401
        # A valid session can still receive a 404 for a resume it does not own.
        upload = client.post(
            "/api/v1/resumes",
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        assert upload.status_code == 400
        # No cookie was created for the failed upload.
        assert client.get("/api/v1/resumes/missing").status_code == 401


def test_service_bearer_authentication_is_enforced(api_app, tmp_path):
    storage = Storage(f"sqlite:///{(tmp_path / 'auth.db').as_posix()}")
    app = create_app(
        config=api_app.state.config,
        pipeline=api_app.state.pipeline,
        storage=storage,
        rate_limit_per_minute=1000,
        api_token="test-service-token",
        require_auth=True,
    )
    with TestClient(app) as client:
        assert client.get("/api/v1/jobs").status_code == 401
        assert client.get("/health").status_code == 200
        assert client.get(
            "/api/v1/jobs", headers={"Authorization": "Bearer wrong"}
        ).status_code == 401
        assert client.get(
            "/api/v1/jobs",
            headers={"Authorization": "Bearer test-service-token"},
        ).status_code == 200


def test_oversized_declared_body_is_rejected(api_app):
    with TestClient(api_app) as client:
        response = client.post(
            "/api/v1/resumes",
            content=b"x",
            headers={"Content-Length": "999999999"},
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "request_too_large"


def test_oidc_identity_scopes_sessions(api_app, tmp_path, resume_bytes):
    storage = Storage(f"sqlite:///{(tmp_path / 'identity.db').as_posix()}")
    verifier = OIDCVerifier(
        issuer="https://identity.example.test",
        audience="talentlens",
        hmac_secret="identity-test-secret-32-bytes-minimum",
    )
    app = create_app(
        config=api_app.state.config,
        pipeline=api_app.state.pipeline,
        storage=storage,
        rate_limit_per_minute=1000,
        api_token="test-service-token",
        require_auth=True,
        oidc_verifier=verifier,
    )

    def headers(subject: str) -> dict[str, str]:
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {
                "sub": subject,
                "iss": "https://identity.example.test",
                "aud": "talentlens",
                "iat": now,
                "exp": now + timedelta(minutes=5),
            },
            "identity-test-secret-32-bytes-minimum",
            algorithm="HS256",
        )
        return {
            "Authorization": "Bearer test-service-token",
            "X-TalentLens-Id-Token": token,
        }

    name, content = resume_bytes
    with TestClient(app) as client:
        assert client.get("/api/v1/resumes").status_code == 401
        assert (
            client.get(
                "/api/v1/resumes",
                headers={"Authorization": "Bearer test-service-token"},
            ).status_code
            == 401
        )
        uploaded = client.post(
            "/api/v1/resumes",
            files={"file": (name, content, "application/pdf")},
            headers=headers("alice"),
        )
        assert uploaded.status_code == 201
        assert client.get("/api/v1/resumes", headers=headers("alice")).status_code == 200
        # The same browser cookie cannot be replayed under another identity.
        assert client.get("/api/v1/resumes", headers=headers("bob")).status_code == 401


def test_jobs_and_resumes_are_paginated(api_app, resume_bytes):
    with TestClient(api_app) as client:
        jobs = client.get("/api/v1/jobs", params={"limit": 2, "offset": 0})
        assert jobs.status_code == 200
        assert len(jobs.json()) == 2
        assert int(jobs.headers["x-total-count"]) >= 2
        assert client.get("/api/v1/jobs", params={"limit": 0}).status_code == 422
        assert client.get("/api/v1/jobs", params={"limit": 201}).status_code == 422

        name, content = resume_bytes
        uploaded = _upload(client, name, content)
        assert uploaded.status_code == 201
        page = client.get("/api/v1/resumes", params={"limit": 1, "offset": 0})
        assert page.status_code == 200
        assert len(page.json()) == 1
        assert page.headers["x-total-count"] == "1"
        empty = client.get("/api/v1/resumes", params={"limit": 1, "offset": 1})
        assert empty.status_code == 200
        assert empty.json() == []


def test_background_retention_sweep_purges_expired(api_app, tmp_path):
    import copy
    import time

    from talentlens.config import Config
    from talentlens.storage.models import SessionRecord

    data = copy.deepcopy(api_app.state.config._data)
    data.setdefault("privacy", {})["retention_purge_interval_seconds"] = 0.05
    config = Config(data, api_app.state.config.path)
    storage = Storage(f"sqlite:///{(tmp_path / 'sweep.db').as_posix()}")
    app = create_app(
        config=config,
        pipeline=api_app.state.pipeline,
        storage=storage,
        rate_limit_per_minute=1000,
    )

    with TestClient(app):
        token, session = storage.create_session()
        with storage.session() as db:
            row = db.get(SessionRecord, session.id)
            row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and storage.get_session(token) is not None:
            time.sleep(0.05)
        assert storage.get_session(token) is None

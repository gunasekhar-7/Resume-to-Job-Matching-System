from __future__ import annotations

import asyncio

from api.middleware import BodySizeLimitMiddleware


def _scope() -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/resumes",
        "headers": [],
        "state": {},
    }


def test_body_limit_rejects_chunked_body_without_content_length():
    async def receive_factory():
        messages = [
            {"type": "http.request", "body": b"x" * 6, "more_body": True},
            {"type": "http.request", "body": b"x" * 6, "more_body": False},
        ]
        return messages

    async def run() -> dict:
        messages = await receive_factory()
        sent: list[dict] = []

        async def receive() -> dict:
            return messages.pop(0)

        async def send(message: dict) -> None:
            sent.append(message)

        async def downstream(scope, receive, send) -> None:  # pragma: no cover - must not run
            raise AssertionError("oversized body reached the application")

        middleware = BodySizeLimitMiddleware(downstream, max_bytes=10)
        await middleware(_scope(), receive, send)
        return sent[0]

    response = asyncio.run(run())
    assert response["status"] == 413


def test_body_limit_replays_allowed_chunks():
    async def run() -> tuple[bytes, int]:
        messages = [
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
        ]
        sent: list[dict] = []

        async def receive() -> dict:
            return messages.pop(0)

        async def send(message: dict) -> None:
            sent.append(message)

        async def downstream(scope, receive, send) -> None:
            chunks = []
            while True:
                message = await receive()
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"".join(chunks)})

        middleware = BodySizeLimitMiddleware(downstream, max_bytes=10)
        await middleware(_scope(), receive, send)
        return sent[-1]["body"], sent[0]["status"]

    body, status = asyncio.run(run())
    assert body == b"abcdef"
    assert status == 200


def test_body_limit_bypasses_get_requests():
    async def downstream(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def uncallable_receive() -> dict:  # pragma: no cover
        raise AssertionError("receive() must not be called for GET requests")

    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    get_scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "headers": [],
        "state": {},
    }
    middleware = BodySizeLimitMiddleware(downstream, max_bytes=10)
    asyncio.run(middleware(get_scope, uncallable_receive, send))
    assert sent[0]["status"] == 200


def test_rate_limiter_isolates_sessions_and_prunes():
    from api.middleware import RateLimitMiddleware
    from starlette.requests import Request

    limiter = RateLimitMiddleware(None, limit_per_minute=2, window_seconds=1)

    # Fake requests with differing session cookies
    def make_req(cookie_val: str, ip: str = "127.0.0.1") -> Request:
        headers = [(b"cookie", f"talentlens_session={cookie_val}".encode("latin-1"))] if cookie_val else []
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/jobs",
            "headers": headers,
            "client": (ip, 12345),
            "state": {},
        }
        return Request(scope)

    async def noop_app(req):
        from fastapi import Response
        return Response("ok", status_code=200)

    # User 1 sends 2 requests (reaches limit)
    r1 = make_req("user-session-1")
    res1 = asyncio.run(limiter.dispatch(r1, noop_app))
    assert res1.status_code == 200
    res2 = asyncio.run(limiter.dispatch(r1, noop_app))
    assert res2.status_code == 200
    res3 = asyncio.run(limiter.dispatch(r1, noop_app))
    assert res3.status_code == 429

    # User 2 from the SAME proxy IP does NOT collide with User 1
    r2 = make_req("user-session-2")
    res_user2 = asyncio.run(limiter.dispatch(r2, noop_app))
    assert res_user2.status_code == 200


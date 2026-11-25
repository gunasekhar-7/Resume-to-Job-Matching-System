"""ASGI middleware: correlation, rate limiting, CSRF-origin checks and headers."""

from __future__ import annotations

import asyncio
import hmac
import threading
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from talentlens.auth import OIDCVerifier
from talentlens.log import get_logger, set_request_id
from talentlens.monitoring.metrics import record_request

logger = get_logger("api.middleware")

RequestHandler = Callable[[Request], Awaitable[Response]]


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request ID, record latency, and add security/cache headers."""

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        incoming = (request.headers.get("X-Request-ID") or "").strip()
        request_id = incoming[:128] if incoming.replace("-", "").isalnum() else str(uuid.uuid4())
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
            response.headers["Cross-Origin-Resource-Policy"] = "same-site"
            if request.url.path.startswith("/api/") or request.url.path == "/metrics":
                response.headers.setdefault("Cache-Control", "no-store")
                response.headers.setdefault(
                    "Content-Security-Policy",
                    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
                )
            forwarded_proto = request.headers.get("X-Forwarded-Proto", "").lower()
            if request.url.scheme == "https" or forwarded_proto == "https":
                response.headers.setdefault(
                    "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                )
            return response
        finally:
            route = request.scope.get("route")
            path = getattr(route, "path", "unmatched")
            record_request(request.method, path, status, round((time.perf_counter() - started) * 1000, 3))
            set_request_id(None)
            del token


class RateLimitMiddleware(BaseHTTPMiddleware):
    """A small fixed-window limiter keyed by client address.

    This is per-process and intentionally simple. It is a safety valve for a single-node
    deployment, not a distributed quota service.
    """

    def __init__(self, app, *, limit_per_minute: int = 60, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.limit = max(1, int(limit_per_minute))
        self.window = max(1, int(window_seconds))
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        session_token = request.cookies.get("talentlens_session")
        forwarded = request.headers.get("X-Forwarded-For", "").partition(",")[0].strip()
        client = session_token or forwarded or (request.client.host if request.client else "unknown")
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.get(client)
            if bucket:
                while bucket and now - bucket[0] >= self.window:
                    bucket.popleft()
                if not bucket:
                    del self._hits[client]
                    bucket = None
            if bucket is not None and len(bucket) >= self.limit:
                logger.warning("Rate limit exceeded")
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "rate_limit_exceeded",
                            "message": "Too many requests; retry later.",
                            "details": {},
                            "request_id": getattr(request.state, "request_id", None),
                        }
                    },
                    headers={"Retry-After": str(self.window)},
                )
            if bucket is None:
                bucket = deque()
                self._hits[client] = bucket
            bucket.append(now)
        return await call_next(request)


class OriginGuardMiddleware(BaseHTTPMiddleware):
    """Reject cookie-bearing state-changing requests from foreign browser origins."""

    def __init__(self, app, *, allowed_origins: list[str] | None = None) -> None:
        super().__init__(app)
        self.allowed = {origin.rstrip("/") for origin in (allowed_origins or [])}

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("Origin")
            if origin:
                normalised = origin.rstrip("/")
                request_origin = f"{request.url.scheme}://{request.url.netloc}".rstrip("/")
                if normalised != request_origin and normalised not in self.allowed:
                    logger.warning("Rejected state-changing request from a foreign Origin")
                    return JSONResponse(
                        status_code=403,
                        content={
                            "error": {
                                "code": "foreign_origin",
                                "message": "State-changing requests must come from an allowed origin.",
                                "details": {},
                                "request_id": getattr(request.state, "request_id", None),
                            }
                        },
                    )
        return await call_next(request)


class BodySizeLimitMiddleware:
    """Enforce a streaming body cap before multipart/file parsing.

    A declared ``Content-Length`` is checked immediately. Chunked requests are
    buffered only up to the configured cap and replayed to the application, so an
    omitted or dishonest length cannot bypass the upload limit.
    """

    def __init__(self, app, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max(1, int(max_bytes))

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET").upper()
        if method in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return
        request_id = None
        state = scope.get("state")
        if isinstance(state, dict):
            request_id = state.get("request_id")
        declared = next(
            (
                value.decode("latin-1")
                for key, value in scope.get("headers", [])
                if key.lower() == b"content-length"
            ),
            None,
        )
        if declared:
            try:
                if int(declared) > self.max_bytes:
                    await self._reject(scope, receive, send, request_id)
                    return
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            total += len(body)
            if total > self.max_bytes:
                await self._reject(scope, receive, send, request_id)
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break

        index = 0

        async def replay() -> dict:
            nonlocal index
            if index < len(chunks):
                body = chunks[index]
                index += 1
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": index < len(chunks),
                }
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(self, scope, receive, send, request_id) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "request_too_large",
                    "message": "Request body exceeds the configured limit.",
                    "details": {"max_bytes": self.max_bytes},
                    "request_id": request_id,
                }
            },
            headers={"Connection": "close"},
        )
        await response(scope, receive, send)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Require a service bearer token for data and metrics routes when configured.

    This is service-to-service authentication, not a replacement for per-user
    identity. The session cookie remains the ownership boundary for resumes.
    """

    def __init__(self, app, *, token: str | None, protected_prefixes: tuple[str, ...]) -> None:
        super().__init__(app)
        self.token = (token or "").strip()
        self.protected_prefixes = protected_prefixes

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        if not self.token or not any(
            request.url.path == prefix or request.url.path.startswith(prefix)
            for prefix in self.protected_prefixes
        ):
            return await call_next(request)
        authorization = request.headers.get("Authorization", "")
        scheme, _, provided = authorization.partition(" ")
        if scheme.lower() != "bearer" or not provided or not hmac.compare_digest(
            provided, self.token
        ):
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "authentication_required",
                        "message": "A valid service bearer token is required.",
                        "details": {},
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)


class IdentityAuthMiddleware(BaseHTTPMiddleware):
    """Verify a per-user OIDC ID token forwarded by the trusted UI server."""

    def __init__(
        self,
        app,
        *,
        verifier: OIDCVerifier,
        header_name: str = "X-TalentLens-Id-Token",
        protected_prefixes: tuple[str, ...] = ("/api/",),
    ) -> None:
        super().__init__(app)
        self.verifier = verifier
        self.header_name = header_name
        self.protected_prefixes = protected_prefixes

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        if not any(
            request.url.path == prefix or request.url.path.startswith(prefix)
            for prefix in self.protected_prefixes
        ):
            return await call_next(request)
        token = request.headers.get(self.header_name, "").strip()
        if not token:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "identity_required",
                        "message": "A valid user identity token is required.",
                        "details": {},
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
            )
        try:
            identity = await asyncio.to_thread(self.verifier.verify, token)
        except Exception as exc:  # noqa: BLE001 - invalid identity must not leak details
            logger.warning("Identity token rejected (%s)", type(exc).__name__)
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "invalid_identity",
                        "message": "The user identity token is invalid or expired.",
                        "details": {},
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
            )
        request.state.user_id = identity.key
        request.state.user_email = identity.email
        request.state.identity_issuer = identity.issuer
        return await call_next(request)


def origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

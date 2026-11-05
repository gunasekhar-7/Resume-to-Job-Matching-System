"""ASGI middleware: correlation, rate limiting, CSRF-origin checks and headers."""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

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
            if request.url.path.startswith("/api/"):
                response.headers.setdefault("Cache-Control", "no-store")
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
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[client]
            while bucket and now - bucket[0] >= self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
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


def origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

"""Logging with request correlation.

Uploaded document content is never logged. Only identifiers, timings and
counts are emitted. ``request_id`` is propagated via a context variable so
that API request logs and pipeline logs can be joined.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

from talentlens.config import get_env_settings

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_configured = False


def set_request_id(request_id: str | None) -> None:
    _request_id.set(request_id)


def get_request_id() -> str | None:
    return _request_id.get()


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib API
        record.request_id = _request_id.get() or "-"
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        extra_keys = getattr(record, "extra_fields", None)
        if isinstance(extra_keys, dict):
            payload.update(extra_keys)
        return json.dumps(payload, default=str)


def configure_logging(level: str | None = None, *, json_logs: bool | None = None) -> None:
    global _configured
    settings = get_env_settings()
    log_level = (level or settings.log_level or "INFO").upper()
    use_json = json_logs if json_logs is not None else False

    root = logging.getLogger("talentlens")
    root.setLevel(log_level)
    if _configured:
        for handler in root.handlers:
            handler.setLevel(log_level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.addFilter(_RequestIdFilter())
    if use_json:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s")
        )
    root.addHandler(handler)
    root.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name if name.startswith("talentlens") else f"talentlens.{name}")

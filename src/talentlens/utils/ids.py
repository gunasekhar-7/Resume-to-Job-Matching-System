"""Stable identifier helpers.

IDs are content-derived so that re-ingesting the same job does not create a
duplicate record, and so that evaluation splits are reproducible across runs.
"""

from __future__ import annotations

import hashlib
import re


def stable_id(prefix: str, *parts: str, length: int = 12) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8", errors="replace")).hexdigest()
    return f"{prefix}_{digest[:length]}"


def resume_id_for(source_sha256: str) -> str:
    return f"resume_{source_sha256[:12]}"


def job_id_for(title: str, company: str, description: str) -> str:
    return stable_id("job", title.strip().lower(), company.strip().lower(), description.strip())


def normalise_id(value: str) -> str:
    """Guard against path traversal / injection when an ID arrives from a client."""
    if not isinstance(value, str):
        raise ValueError("identifier must be a string")
    cleaned = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", cleaned):
        raise ValueError("identifier contains unsupported characters")
    return cleaned

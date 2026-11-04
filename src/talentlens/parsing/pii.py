"""PII detection and redaction.

Scope and honesty
-----------------
This module reliably detects *structured* identifiers: email addresses, phone
numbers, profile URLs and plain URLs. Name detection is deliberately not
attempted with regex heuristics because they are error-prone; when Presidio and
a spaCy NER model are installed, ``detect_pii(use_presidio=True)`` can add
PERSON entities, but it is off by default because it requires a model download.

Only entity *types and counts* are ever logged or stored in metadata. Values are
returned only inside the in-memory redaction result used for display.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from talentlens.log import get_logger

logger = get_logger("parsing.pii")

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[\s.\-]?)?(?:\(?\d{2,4}\)?[\s.\-]?){2,4}\d{2,4}(?!\w)"
)
URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>()]+", re.IGNORECASE)
PROFILE_RE = re.compile(r"\b(?:linkedin\.com|github\.com|gitlab\.com)/[^\s<>()]+", re.IGNORECASE)

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", EMAIL_RE),
    ("URL", PROFILE_RE),
    ("URL", URL_RE),
    ("PHONE", PHONE_RE),
)


@dataclass
class PIIScan:
    entity_types: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    redacted_text: str = ""

    @property
    def has_pii(self) -> bool:
        return bool(self.entity_types)


def _normalise_phone_candidates(text: str) -> list[re.Match[str]]:
    """Filter date-like and year-like numeric strings out of phone matches."""
    matches: list[re.Match[str]] = []
    for match in PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) < 7 or len(digits) > 15:
            continue
        # Avoid matching date ranges such as "2021-03 - present" or "2019 - 2022".
        if re.fullmatch(r"[\d\s.\-()]+", match.group(0)) and 4 <= digits.__len__() <= 8:
            context = text[max(0, match.start() - 3): match.end() + 3]
            if re.search(r"(19|20)\d{2}", context) and len(digits) <= 8:
                continue
        matches.append(match)
    return matches


def detect_pii(text: str, *, use_presidio: bool = False) -> PIIScan:
    """Detect PII, returning entity types/counts and a redacted copy."""
    if not text:
        return PIIScan()

    replacements: list[tuple[int, int, str]] = []
    counts: dict[str, int] = {}

    def add(kind: str, start: int, end: int) -> None:
        replacements.append((start, end, f"[{kind}]"))
        counts[kind] = counts.get(kind, 0) + 1

    # Profiles before generic URLs so the more specific label wins.
    for kind, pattern in _PATTERNS:
        if kind == "PHONE":
            for match in _normalise_phone_candidates(text):
                add(kind, match.start(), match.end())
        else:
            for match in pattern.finditer(text):
                add(kind, match.start(), match.end())

    if use_presidio:
        try:
            from presidio_analyzer import AnalyzerEngine

            analyzer = AnalyzerEngine()
            for result in analyzer.analyze(text=text, language="en", entities=["PERSON"]):
                add(result.entity_type, result.start, result.end)
        except Exception as exc:  # pragma: no cover - optional dependency/model
            logger.info("Presidio unavailable or model missing; structured PII only (%s)", type(exc).__name__)

    # Resolve overlaps: keep the first (earlier start, longer) replacement.
    replacements.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str]] = []
    last_end = -1
    for start, end, label in replacements:
        if start >= last_end:
            selected.append((start, end, label))
            last_end = end

    redacted_parts: list[str] = []
    cursor = 0
    for start, end, label in selected:
        redacted_parts.append(text[cursor:start])
        redacted_parts.append(label)
        cursor = end
    redacted_parts.append(text[cursor:])

    return PIIScan(
        entity_types=sorted(counts),
        counts=counts,
        redacted_text="".join(redacted_parts),
    )


def redact_text(text: str, placeholder: str = "[REDACTED]") -> str:
    """Replace structured PII with a single placeholder (used before logging)."""
    scan = detect_pii(text)
    if not scan.has_pii:
        return text
    result = text
    for pattern in (EMAIL_RE, PROFILE_RE, URL_RE):
        result = pattern.sub(placeholder, result)
    for match in _normalise_phone_candidates(result):
        result = result.replace(match.group(0), placeholder)
    return result


def pii_summary(scan: PIIScan) -> dict[str, object]:
    """Metadata-safe summary: types and counts, never values."""
    return {"entity_types": scan.entity_types, "counts": scan.counts}

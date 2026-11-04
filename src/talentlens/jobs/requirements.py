"""Requirement parsing for job descriptions.

Job postings are treated as untrusted input: nothing is executed, and the
parser only records what the text supports. Required vs preferred skills are
kept strictly separate. When a posting has no explicit requirement sections,
skills found in narrative text are *not* silently promoted to mandatory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_REQUIRED_MARKERS = (
    "required", "requirements", "must have", "must-have", "minimum qualifications",
    "minimum requirements", "essential", "you have", "what you'll need", "what you need",
    "basic qualifications", "required qualifications",
)
_PREFERRED_MARKERS = (
    "preferred", "nice to have", "nice-to-have", "bonus", "desired", "good to have",
    "preferred qualifications", "additional qualifications", "plus",
)
_REQUIRED_SENTENCE_RE = re.compile(
    r"\b(required|requirements?|must|essential|minimum)\b", re.IGNORECASE
)
_PREFERRED_SENTENCE_RE = re.compile(
    r"\b(preferred|nice to have|bonus|a plus|desired|good to have)\b", re.IGNORECASE
)

_EXPERIENCE_PATTERNS = (
    (re.compile(r"(?P<min>\d{1,2})\s*(?:-|–|to)\s*(?P<max>\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I), "range"),
    (re.compile(r"(?P<min>\d{1,2})\s*\+\s*(?:years?|yrs?)", re.I), "min"),
    (re.compile(r"(?:at least|minimum(?: of)?)\s*(?P<min>\d{1,2})\s*(?:years?|yrs?)", re.I), "min"),
    (re.compile(r"(?P<min>\d{1,2})\s*(?:years?|yrs?)(?:\s+of)?\s+(?:relevant\s+|professional\s+)?experience", re.I), "min"),
)

_SENIORITY_TOKENS = (
    ("intern", "intern"),
    ("internship", "intern"),
    ("principal", "principal"),
    ("staff", "staff"),
    ("lead", "lead"),
    ("head of", "manager"),
    ("manager", "manager"),
    ("director", "director"),
    ("senior", "senior"),
    ("sr.", "senior"),
    ("sr ", "senior"),
    ("junior", "junior"),
    ("jr.", "junior"),
    ("entry level", "junior"),
    ("entry-level", "junior"),
    ("graduate", "junior"),
    ("associate", "junior"),
    ("mid-level", "mid"),
    ("mid level", "mid"),
)

_EDUCATION_RE = re.compile(
    r"\b(ph\.?d|doctorate|master'?s?|m\.?sc|m\.?s\.?|bachelor'?s?|b\.?sc|b\.?s\.?|b\.?tech|m\.?tech|degree)\b",
    re.IGNORECASE,
)


@dataclass
class RequirementSplit:
    required: list[str] = field(default_factory=list)
    preferred: list[str] = field(default_factory=list)
    neutral: list[str] = field(default_factory=list)

    @property
    def has_explicit_sections(self) -> bool:
        return bool(self.required or self.preferred)


def _clean_line(line: str) -> str:
    cleaned = line.strip().strip("•·-–—*").strip()
    return re.sub(r"\s+", " ", cleaned)


def split_requirements(text: str) -> RequirementSplit:
    """Split free text into required / preferred / neutral statements.

    Two passes cooperate: heading-based bucketing (``Requirements:`` followed by
    bullets) and sentence-level markers (``Experience with X is essential``).
    """
    split = RequirementSplit()
    if not text or not text.strip():
        return split

    bucket = "neutral"
    for raw_line in text.split("\n"):
        line = _clean_line(raw_line)
        if not line:
            continue
        normalized = line.lower().rstrip(":")
        if any(marker == normalized or normalized.endswith(marker) for marker in _REQUIRED_MARKERS) and len(line) <= 80:
            bucket = "required"
            continue
        if any(marker == normalized or normalized.endswith(marker) for marker in _PREFERRED_MARKERS) and len(line) <= 80:
            bucket = "preferred"
            continue

        sentences = re.split(r"(?<=[.!?])\s+", line)
        for sentence in sentences:
            sentence = _clean_line(sentence)
            if not sentence:
                continue
            if _PREFERRED_SENTENCE_RE.search(sentence):
                split.preferred.append(sentence)
            elif _REQUIRED_SENTENCE_RE.search(sentence) or bucket == "required":
                split.required.append(sentence)
            elif bucket == "preferred":
                split.preferred.append(sentence)
            else:
                split.neutral.append(sentence)

    return RequirementSplit(
        required=_dedupe(split.required),
        preferred=_dedupe(split.preferred),
        neutral=_dedupe(split.neutral),
    )


def extract_experience_range(text: str) -> tuple[float | None, float | None, str | None]:
    """Return ``(min_years, max_years, evidence)`` from explicit statements only."""
    if not text:
        return None, None, None
    for pattern, kind in _EXPERIENCE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            minimum = float(match.group("min"))
        except (TypeError, ValueError):
            continue
        maximum: float | None = None
        if kind == "range":
            try:
                maximum = float(match.group("max"))
            except (TypeError, ValueError):
                maximum = None
        if minimum > 50 or (maximum is not None and maximum > 50):
            continue
        if maximum is not None and maximum < minimum:
            continue
        return minimum, maximum, match.group(0)
    return None, None, None


def infer_seniority(title: str, text: str = "") -> str | None:
    haystack = f"{title} {text[:200]}".lower()
    for token, level in _SENIORITY_TOKENS:
        if token in haystack:
            return level
    return None


def infer_work_arrangement(text: str) -> str:
    lowered = (text or "").lower()
    if "hybrid" in lowered:
        return "hybrid"
    if "remote" in lowered or "work from home" in lowered or "distributed team" in lowered:
        return "remote"
    if "on-site" in lowered or "onsite" in lowered or "in office" in lowered or "in-office" in lowered:
        return "onsite"
    return "unknown"


def infer_education(text: str) -> str | None:
    match = _EDUCATION_RE.search(text or "")
    return match.group(0) if match else None


def extract_responsibilities(text: str) -> list[str]:
    """Pull bullet-like responsibility statements out of raw job text."""
    responsibilities: list[str] = []
    for raw in (text or "").split("\n"):
        line = _clean_line(raw)
        if not line:
            continue
        if raw.strip().startswith(("-", "•", "*")) or re.match(r"^\d+[.)]\s", raw.strip()):
            responsibilities.append(line)
    return _dedupe(responsibilities)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            output.append(value)
    return output

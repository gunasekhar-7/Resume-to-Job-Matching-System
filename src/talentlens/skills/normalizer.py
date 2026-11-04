"""Skill phrase normalisation helpers.

Kept separate from the taxonomy loader so that the rules for turning messy
document text into a lookup key are independently testable.
"""

from __future__ import annotations

import re

from talentlens.skills.taxonomy import SkillTaxonomy
from talentlens.utils.text import normalize_for_match

_TRAILING_NOISE = re.compile(r"\s*[\(\[\{].*?[\)\]\}]\s*$")
_LEADING_VERBS = re.compile(
    r"^(?:experience (?:with|in)|proficient (?:with|in)|knowledge of|familiarity with|strong|expertise in)\s+",
    re.IGNORECASE,
)
_PLURAL_TECH = {"apis": "api", "models": "model"}


def normalize_phrase(phrase: str) -> str:
    """Normalise a phrase for alias lookup without destroying meaningful symbols.

    ``"Scikit-Learn (sklearn)"`` -> ``"scikit learn"``; ``"C++"`` stays ``"c++"``.
    """
    cleaned = normalize_for_match(phrase.strip().strip(".,;:"))
    cleaned = _TRAILING_NOISE.sub("", cleaned)
    cleaned = _LEADING_VERBS.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def resolve_phrase(taxonomy: SkillTaxonomy, phrase: str) -> tuple[str, str] | None:
    """Return ``(canonical, match_status)`` for a free-text phrase, or ``None``."""
    match = taxonomy.resolve(phrase)
    if match is None:
        normalized = normalize_phrase(phrase)
        match = taxonomy.resolve(normalized)
    if match is None:
        return None
    return match.canonical, match.match_status


def is_ambiguous_alias(taxonomy: SkillTaxonomy, phrase: str) -> bool:
    """True when an alias is intentionally excluded because it maps to several skills.

    The loader rejects ambiguous aliases outright; this helper exists so callers
    can document and test the *behaviour* when such a phrase is encountered
    (it is reported as ambiguous rather than guessed).
    """
    key = normalize_phrase(phrase)
    hits = taxonomy.resolve(key)
    return hits is None and bool(key)


def canonical_sort_key(canonical: str) -> tuple[str, str]:
    return canonical.lower(), canonical


def plural_variants(phrase: str) -> list[str]:
    """Small, explicit plural handling for skill lists (``REST API`` -> ``REST APIs``)."""
    words = phrase.split()
    if not words:
        return [phrase]
    variants = [phrase]
    last = words[-1]
    if last.lower() in _PLURAL_TECH:
        variants.append(" ".join([*words[:-1], _PLURAL_TECH[last.lower()]]))
    elif not last.endswith("s"):
        variants.append(" ".join([*words[:-1], last + "s"]))
    return variants

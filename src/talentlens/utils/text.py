"""Text normalisation and structural helpers shared by parsing and matching.

The functions are intentionally deterministic and dependency-light: parsing
quality is a core deliverable, and these primitives are unit tested directly.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u2060"), None)
_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\u00a0": " ",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
}
#: Bullet glyphs are separator candidates inline and markers at line start.
_BULLET_GLYPHS = "\u2022\u2023\u25e6\u2043\u2219\u00b7\u25aa\u25ab\u25a0\u25cf\u27a2\u2794\u2192>"
_BULLET_RE = re.compile(r"^\s*(?:[-*\u2022\u25aa\u25cf>]+|\d{1,2}[.)])\s+")
_PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:page\s*)?\d{1,3}\s*(?:of|/)\s*\d{1,3}\s*$|^\s*page\s+\d{1,3}\s*$|^\s*\d{1,3}\s*$",
    re.IGNORECASE,
)
#: Running footers such as "Confidential | Page 2" carry no candidate content.
_RUNNING_FOOTER_RE = re.compile(r"^.{0,80}\b(?:page|pg\.?)\s*\d+\s*$", re.IGNORECASE)
_WS_RE = re.compile(r"[ \t\u00a0]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_ABBREVIATION_RE = re.compile(
    r"\b(e\.g|i\.e|etc|vs|mr|ms|mrs|dr|prof|inc|ltd|co|no|fig|approx)\.", re.IGNORECASE
)
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def normalize_unicode(text: str) -> str:
    """NFKC normalise, unify curly quotes/dashes, remove zero-width characters."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    for source, target in _LIGATURES.items():
        normalized = normalized.replace(source, target)
    return normalized.translate(_ZERO_WIDTH)


def normalize_whitespace(text: str) -> str:
    """Collapse intra-line whitespace and excessive blank lines, preserving line breaks."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WS_RE.sub(" ", line).strip() for line in text.split("\n")]
    joined = "\n".join(lines)
    return _MULTI_NEWLINE_RE.sub("\n\n", joined).strip()


def normalize_bullets(text: str) -> str:
    """Convert line-leading bullets to ``- `` and inline bullets to separators."""
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if _BULLET_RE.match(stripped):
            stripped = "- " + _BULLET_RE.sub("", stripped, count=1).strip()
        # Inline bullet glyphs act as list separators ("Python - SQL - AWS").
        stripped = re.sub(rf"\s*[{re.escape(_BULLET_GLYPHS)}]+\s*", ", ", stripped)
        lines.append(stripped)
    return "\n".join(lines)


def clean_text(text: str) -> str:
    """Standard cleaning applied to every extracted document."""
    return normalize_bullets(normalize_whitespace(normalize_unicode(text)))


def dedupe_consecutive_lines(text: str) -> str:
    """Remove immediately repeated lines (common with PDF extraction artefacts)."""
    result: list[str] = []
    previous: str | None = None
    for line in text.split("\n"):
        key = line.strip()
        if key and key == previous:
            continue
        result.append(line)
        previous = key
    return "\n".join(result)


def strip_page_artifacts(text: str) -> str:
    """Remove standalone page numbers, 'Page x of y' lines and running footers."""
    lines = [
        line
        for line in text.split("\n")
        if not _PAGE_NUMBER_RE.match(line) and not _RUNNING_FOOTER_RE.match(line.strip())
    ]
    return "\n".join(lines)


def remove_repeated_page_lines(pages: Sequence[str], *, min_ratio: float = 0.6, max_words: int = 10) -> list[str]:
    """Detect running headers/footers repeated across pages and drop those lines.

    A line is considered boilerplate when the same short line appears on at
    least ``min_ratio`` of pages (and at least two pages). Matching is
    case-insensitive and digit-insensitive so page numbers in a footer do not
    defeat detection.
    """
    if len(pages) < 2:
        return [strip_page_artifacts(page) for page in pages]

    def fingerprint(line: str) -> str:
        return re.sub(r"\d+", "#", line.strip().lower())

    counts: Counter[str] = Counter()
    for page in pages:
        seen_on_page = {fingerprint(line) for line in page.split("\n") if line.strip()}
        counts.update(seen_on_page)

    threshold = max(2, int(len(pages) * min_ratio + 0.999))
    boilerplate = {
        key
        for key, count in counts.items()
        if count >= threshold and len(key.split()) <= max_words
    }

    cleaned: list[str] = []
    for page in pages:
        kept = [
            line
            for line in page.split("\n")
            if not (line.strip() and fingerprint(line) in boilerplate)
        ]
        cleaned.append(strip_page_artifacts("\n".join(kept)))
    return cleaned


def split_sentences(text: str, *, max_chars: int = 500) -> list[str]:
    """Split text into sentences, also breaking very long bullet fragments."""
    if not text.strip():
        return []
    candidates: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        stripped = _BULLET_RE.sub("", stripped).strip()
        if not stripped:
            continue
        # Protect common abbreviations so "e.g. AWS" is not split into a fake sentence.
        protected = _ABBREVIATION_RE.sub(lambda match: match.group(0)[:-1] + "\u2024", stripped)
        parts = [part.replace("\u2024", ".") for part in _SENTENCE_SPLIT_RE.split(protected)]
        for part in parts:
            part = part.strip(" ;,")
            if not part:
                continue
            if len(part) > max_chars:
                # Split on commas/semicolons for dense requirement lists.
                buffer = ""
                for chunk in re.split(r"(?<=[,;])\s+", part):
                    if len(buffer) + len(chunk) > max_chars and buffer:
                        candidates.append(buffer.strip())
                        buffer = chunk
                    else:
                        buffer = f"{buffer} {chunk}".strip()
                if buffer:
                    candidates.append(buffer.strip())
            else:
                candidates.append(part)
    return candidates


def sentence_spans(text: str) -> list[tuple[str, int, int]]:
    """Return ``(sentence, start, end)`` triples with offsets into ``text``."""
    spans: list[tuple[str, int, int]] = []
    cursor = 0
    for line in text.split("\n"):
        line_start = cursor
        cursor += len(line) + 1
        stripped = line.strip()
        if not stripped:
            continue
        offset = line_start + (len(line) - len(line.lstrip()))
        for sentence in split_sentences(stripped):
            index = text.find(sentence, offset)
            if index == -1:
                index = offset
                spans.append((sentence, index, index + len(sentence)))
            else:
                spans.append((sentence, index, index + len(sentence)))
            offset = index + len(sentence)
    return spans


def slugify(value: str) -> str:
    value = normalize_unicode(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return re.sub(r"-{2,}", "-", value)


def normalize_for_match(text: str) -> str:
    """Lowercase, strip punctuation variants and collapse whitespace.

    Used for alias lookups and duplicate detection, never for display.
    """
    text = normalize_unicode(text).lower()
    text = text.replace("-", " ").replace("/", " ").replace("&", " and ")
    text = re.sub(r"[^a-z0-9+#.\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def content_sha256(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update((part or "").encode("utf-8", errors="replace"))
        digest.update(b"\x00")
    return digest.hexdigest()


def is_probably_heading(line: str, *, max_words: int = 6) -> bool:
    """Heuristic used by section detection (kept here so it can be unit tested)."""
    candidate = line.strip().strip(":").strip()
    if not candidate or len(candidate) > 60:
        return False
    words = candidate.split()
    if len(words) > max_words:
        return False
    if candidate.endswith("."):
        return False
    letters = [char for char in candidate if char.isalpha()]
    if not letters:
        return False
    # ALL CAPS or Title Case headings are the common resume conventions.
    uppercase_ratio = sum(1 for char in letters if char.isupper()) / len(letters)
    if uppercase_ratio >= 0.8:
        return True
    return candidate[0].isupper() and all(
        word[0].isupper() or word.lower() in _HEADING_CONNECTORS for word in words
    )


_HEADING_CONNECTORS = {"and", "of", "for", "&", "the", "in", "to"}


def truncate(text: str, limit: int = 240, suffix: str = "...") -> str:
    cleaned = " ".join(text.split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - len(suffix)].rstrip() + suffix


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        key = value.strip().lower()
        if key and key not in seen:
            seen.add(key)
            output.append(value.strip())
    return output


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w+#.-]+\b", text))


def mask_urls(text: str) -> str:
    """Remove URLs before logging or displaying untrusted text in logs."""
    return _URL_RE.sub("[URL]", text)

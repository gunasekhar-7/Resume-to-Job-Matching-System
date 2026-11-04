"""Document-level cleaning and extraction-quality assessment."""

from __future__ import annotations

import re
from dataclasses import dataclass

from talentlens.utils.text import (
    clean_text,
    dedupe_consecutive_lines,
    remove_repeated_page_lines,
    word_count,
)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class CleaningResult:
    text: str
    warnings: list[str]
    chars_removed: int


def clean_pages(pages: list[str], *, keep_page_break_markers: bool = False) -> CleaningResult:
    """Remove running headers/footers and normalise the extracted page text."""
    warnings: list[str] = []
    if not pages:
        return CleaningResult("", ["No pages were extracted"], 0)

    stripped_pages = remove_repeated_page_lines(pages)
    if len(pages) > 1:
        removed = sum(len(page) for page in pages) - sum(len(page) for page in stripped_pages)
        if removed > 0:
            warnings.append("Removed repeated header/footer text across pages")

    joined = "\n\n".join(stripped_pages) if keep_page_break_markers else "\n".join(stripped_pages)
    before = len(joined)
    text = clean_text(joined)
    text = dedupe_consecutive_lines(text)
    text = _CONTROL_CHARS_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    chars_removed = max(0, before - len(text))
    if chars_removed > before * 0.35 and before > 200:
        warnings.append("Large amount of character noise removed during cleaning")
    return CleaningResult(text=text, warnings=warnings, chars_removed=chars_removed)


def extraction_quality(text: str, *, page_count: int | None = None, section_count: int = 0) -> float:
    """Heuristic 0-1 measure of how usable the extracted text is.

    Deliberately transparent and bounded: character volume, word volume, alphabetic
    ratio, line diversity and section coverage. It is a diagnostic, not a probability.
    """
    if not text.strip():
        return 0.0
    chars = len(text)
    words = word_count(text)
    letters = sum(1 for char in text if char.isalpha())
    alpha_ratio = letters / max(1, chars)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    diversity = len(set(lines)) / max(1, len(lines))

    volume = min(1.0, chars / 900.0)
    lexical = min(1.0, words / 160.0)
    section_component = min(1.0, section_count / 3.0)
    page_penalty = 1.0
    if page_count and page_count > 0 and words / page_count < 25:
        page_penalty = 0.7

    score = 0.35 * volume + 0.25 * lexical + 0.15 * alpha_ratio + 0.10 * diversity + 0.15 * section_component
    return round(max(0.0, min(1.0, score * page_penalty)), 3)


def is_low_text(text: str, *, min_chars: int = 120, min_words: int = 20) -> bool:
    """True for image-only/scanned documents that produced almost no body text."""
    content_lines = [line for line in text.split("\n") if line.strip()]
    return len(text.strip()) < min_chars or word_count(text) < min_words or len(content_lines) < 3


def looks_like_warehouse_dump(text: str) -> bool:
    """Detect the common failure mode of table rows collapsed into one giant line."""
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return False
    longest = max(len(line) for line in lines)
    return longest > 1200 and len(lines) < 10

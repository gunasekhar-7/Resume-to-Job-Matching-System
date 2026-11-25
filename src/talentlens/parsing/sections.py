"""Resume section detection.

Strategy (in priority order):
1. Exact heading-alias match on a short standalone line (covers most resumes and
   all common heading variants, including ALL CAPS and Title Case).
2. DOCX heading styles supplied by the extractor (``forced_headings``), even
   when the text is not a recognised alias.
3. Conservative ALL-CAPS 2-4 word headings that are followed by bullet text.

Every section keeps character offsets into the cleaned full text so that skill
mentions and explanations can point back to the source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from talentlens.config import get_config
from talentlens.log import get_logger
from talentlens.schemas import SECTION_ORDER, SectionName, SectionSpan
from talentlens.utils.text import normalize_unicode

logger = get_logger("parsing.sections")

SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "summary": (
        "summary", "professional summary", "profile", "professional profile", "about me",
        "about", "objective", "career objective", "executive summary", "overview", "bio",
    ),
    "skills": (
        "skills", "technical skills", "core competencies", "competencies", "technical expertise",
        "technologies", "tech stack", "technology stack", "areas of expertise", "skills and tools",
        "skills & tools", "technical proficiencies", "tools and technologies", "toolkit",
        "core skills", "key skills", "skills summary",
    ),
    "experience": (
        "experience", "professional experience", "work experience", "employment history",
        "work history", "career history", "relevant experience", "professional background",
        "employment", "industry experience", "professional experience & achievements",
    ),
    "projects": (
        "projects", "selected projects", "personal projects", "academic projects", "key projects",
        "project experience", "side projects", "portfolio", "notable projects",
    ),
    "education": (
        "education", "academic background", "education and training", "education & training",
        "qualifications", "academic qualifications", "educational background", "academics",
    ),
    "certifications": (
        "certifications", "certificates", "professional certifications", "licenses and certifications",
        "licenses & certifications", "certification", "licences", "courses and certifications",
        "training and certifications",
    ),
    "publications": (
        "publications", "research", "research publications", "papers", "patents",
        "selected publications", "talks and publications",
    ),
    "additional": (
        "additional information", "additional", "awards", "honors", "honours", "awards and honors",
        "awards & honors", "languages", "volunteer experience", "volunteer", "interests", "hobbies",
        "activities", "extracurricular activities", "references", "achievements",
    ),
    "header": ("contact", "contact information", "header"),
}

def normalize_heading(line: str) -> str:
    text = normalize_unicode(line).strip().lower()
    text = re.sub(r"[\u2013\u2014]", "-", text)
    text = text.strip(" \t:.-_*#")
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_ALIAS_TO_SECTION: dict[str, str] = {}
for _section, _aliases in SECTION_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_TO_SECTION.setdefault(normalize_heading(_alias), _section)

_COMBINED_SPLIT_RE = re.compile(r"\s+(?:and|&|/)\s+", re.IGNORECASE)


@dataclass
class SectionDetectionResult:
    spans: list[SectionSpan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detected_headings: list[str] = field(default_factory=list)
    used_fallback: bool = False


@dataclass(frozen=True)
class _Line:
    text: str
    start: int
    end: int


def _lines_with_offsets(text: str) -> list[_Line]:
    lines: list[_Line] = []
    offset = 0
    for raw in text.splitlines(keepends=True):
        content = raw.rstrip("\r\n")
        start = offset
        end = start + len(content)
        lines.append(_Line(text=content.strip(), start=start, end=end))
        offset += len(raw)
    return lines


def _config_max_words() -> int:
    try:
        return int(get_config().get("parsing.max_heading_words", 6))
    except Exception:  # pragma: no cover - config always available in practice
        return 6


def match_heading(line: str, *, forced_headings: set[str] | None = None) -> tuple[str, str] | None:
    """Return ``(section, heading_text)`` if the line is a heading, else ``None``."""
    raw = line.strip()
    if not raw or len(raw) > 70:
        return None
    if raw.endswith(".") or any(char in raw for char in ",;|"):
        return None
    if raw.count(":") > 1 or (":" in raw and not raw.endswith(":")):
        return None

    normalized = normalize_heading(raw)
    if not normalized:
        return None
    if normalized in _ALIAS_TO_SECTION:
        return _ALIAS_TO_SECTION[normalized], raw

    # Combined heading such as "Education & Certifications": keep the first known part.
    if any(separator in raw for separator in ("&", "/")) or re.search(r"\band\b", raw, re.IGNORECASE):
        parts = _COMBINED_SPLIT_RE.split(raw)
        if len(parts) > 1:
            first = _ALIAS_TO_SECTION.get(normalize_heading(parts[0]))
            second = _ALIAS_TO_SECTION.get(normalize_heading(parts[1]))
            if first and second and first != second:
                return first, raw

    if forced_headings and normalized in forced_headings:
        # Styled heading with a non-standard name: keep it visible as "other".
        return "other", raw

    # Unknown headings must be unambiguous: ALL CAPS, 2-4 words, no digits.
    if not raw[0].isupper():
        return None
    if raw.isupper() and 2 <= len(raw.split()) <= 4 and not any(char.isdigit() for char in raw):
        return "other", raw
    return None


def detect_sections(
    text: str,
    *,
    forced_headings: set[str] | None = None,
) -> SectionDetectionResult:
    """Segment cleaned resume text into sections with character offsets."""
    result = SectionDetectionResult()
    if not text.strip():
        return result

    lines = _lines_with_offsets(text)
    max_words = _config_max_words()

    headings: list[tuple[int, str, str]] = []  # (line index, section, heading text)
    for index, line in enumerate(lines):
        if not line.text:
            continue
        matched = match_heading(line.text, forced_headings=forced_headings)
        if matched is None:
            continue
        section, heading_text = matched
        if section == "other":
            # Only accept an unknown heading when bullets follow, to avoid false positives.
            next_line = next((item.text for item in lines[index + 1:] if item.text), "")
            if not next_line.startswith("-"):
                continue
        if len(heading_text.split()) > max_words * 2:
            continue
        headings.append((index, section, heading_text))
        result.detected_headings.append(heading_text)

    if not headings:
        result.used_fallback = True
        result.warnings.append("No section headings detected; applied fallback layout heuristics")
        return _fallback_detection(text, lines, result)

    # Header block before the first heading (name, contact details, headline).
    first_heading_index = headings[0][0]
    header_lines = [line for line in lines[:first_heading_index] if line.text]
    if header_lines:
        start = header_lines[0].start
        end = header_lines[-1].end
        result.spans.append(
            SectionSpan(
                section=SectionName.HEADER,
                heading=None,
                text=text[start:end],
                start_char=start,
                end_char=end,
                order=0,
            )
        )

    order = 1
    for position, (line_index, section, heading_text) in enumerate(headings):
        next_line_index = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body_lines = [line for line in lines[line_index + 1: next_line_index] if line.text]
        if not body_lines:
            continue
        start = body_lines[0].start
        end = body_lines[-1].end
        result.spans.append(
            SectionSpan(
                section=SectionName(section),
                heading=heading_text,
                text=text[start:end],
                start_char=start,
                end_char=end,
                order=order,
            )
        )
        order += 1

    if not result.spans:
        result.warnings.append("Headings were found but contained no body content")
    _warn_combined_headings(result)
    return result


def _fallback_detection(text: str, lines: list[_Line], result: SectionDetectionResult) -> SectionDetectionResult:
    """Split a heading-less resume into a header block and an 'other' block."""
    body = [line for line in lines if line.text]
    if not body:
        return result
    header_end_index = 0
    for index, line in enumerate(body[:8]):
        if any(separator in line.text for separator in ("@", "|", "linkedin.", "github.")):
            header_end_index = index
    header_lines = body[: header_end_index + 1]
    remaining = body[header_end_index + 1:]

    if header_lines:
        start, end = header_lines[0].start, header_lines[-1].end
        result.spans.append(
            SectionSpan(
                section=SectionName.HEADER,
                heading=None,
                text=text[start:end],
                start_char=start,
                end_char=end,
                order=0,
            )
        )
    if remaining:
        start, end = remaining[0].start, remaining[-1].end
        result.spans.append(
            SectionSpan(
                section=SectionName.OTHER,
                heading=None,
                text=text[start:end],
                start_char=start,
                end_char=end,
                order=1,
            )
        )
    return result


def _warn_combined_headings(result: SectionDetectionResult) -> None:
    for heading in result.detected_headings:
        normalized = normalize_heading(heading)
        if any(separator in heading for separator in ("&", "/")) or " and " in normalized:
            parts = [part for part in _COMBINED_SPLIT_RE.split(heading) if part.strip()]
            mapped = [_ALIAS_TO_SECTION.get(normalize_heading(part)) for part in parts]
            if len([item for item in mapped if item]) > 1:
                result.warnings.append(
                    f"Combined heading '{heading}' kept as a single section; verify content placement"
                )


def build_section_lists(
    spans: list[SectionSpan],
    *,
    include_canonical_empty: bool = True,
) -> dict[str, list[str]]:
    """Turn spans into ``{section: [paragraph, ...]}`` for the ResumeDocument schema."""
    sections: dict[str, list[str]] = {}
    if include_canonical_empty:
        for name in (
            SectionName.SUMMARY,
            SectionName.SKILLS,
            SectionName.EXPERIENCE,
            SectionName.PROJECTS,
            SectionName.EDUCATION,
            SectionName.CERTIFICATIONS,
        ):
            sections[name.value] = []

    for span in sorted(spans, key=lambda item: item.order):
        bucket = sections.setdefault(span.section.value, [])
        if span.section.value == SectionName.HEADER.value:
            bucket.extend(line for line in span.text.split("\n") if line.strip())
            continue
        for line in span.text.split("\n"):
            cleaned = line.strip()
            if not cleaned:
                continue
            if span.heading and normalize_heading(cleaned) == normalize_heading(span.heading):
                continue
            bucket.append(cleaned)

    # Drop optional empty sections to keep the payload honest about what was found.
    # The six canonical sections are always present (possibly empty).
    for optional in ("publications", "additional", "other", "header"):
        if not sections.get(optional):
            sections.pop(optional, None)
    return {key: sections[key] for key in [*SECTION_ORDER, *sections] if key in sections}


def section_coverage(sections: dict[str, list[str]]) -> dict[str, bool]:
    return {name: bool(sections.get(name)) for name in SECTION_ORDER if name in sections}

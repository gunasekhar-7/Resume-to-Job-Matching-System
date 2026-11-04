"""Skill extraction from resume and job text.

Implementation: spaCy ``PhraseMatcher`` over a blank English pipeline (no model
download required), plus a regex fallback if spaCy cannot be imported. Every
mention keeps its original phrase, canonical skill, section, evidence sentence
and character offsets.

Design constraints (see docs/SKILL_EXTRACTION.md):
* A mention is evidence of *mention*, not of proficiency.
* Case-sensitive skills (C, R, Go, Swift, BERT, ...) use an ORTH matcher so that
  ordinary prose does not create false positives.
* Single-letter skills additionally require list-like context.
* Overlapping matches are resolved longest-first, then by canonical priority.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from talentlens.config import get_config
from talentlens.errors import SkillTaxonomyError
from talentlens.log import get_logger
from talentlens.schemas import SectionName, SectionSpan, SkillMention
from talentlens.skills.normalizer import normalize_phrase
from talentlens.skills.taxonomy import SkillTaxonomy, get_taxonomy
from talentlens.utils.text import sentence_spans, split_sentences

logger = get_logger("skills.extractor")

_SINGLE_LETTER_CONTEXT = re.compile(r"[,;/|()\n\t]")


@dataclass(frozen=True)
class _RawMatch:
    canonical: str
    category: str
    phrase: str
    start_char: int
    end_char: int
    status: str
    confidence: float
    case_sensitive: bool


class _SectionIndex:
    """Map a character offset to the resume section that contains it."""

    def __init__(self, spans: Sequence[SectionSpan]) -> None:
        ordered = sorted(spans, key=lambda span: span.start_char if span.start_char is not None else 0)
        self._spans = ordered
        self._starts = [span.start_char or 0 for span in ordered]

    def section_at(self, offset: int) -> SectionName:
        if not self._spans:
            return SectionName.OTHER
        index = bisect.bisect_right(self._starts, offset) - 1
        if index < 0:
            return self._spans[0].section
        span = self._spans[index]
        if span.end_char is not None and offset > span.end_char:
            # Offset falls in a gap (e.g. heading whitespace): keep the preceding section.
            return span.section
        return span.section


class _SentenceIndex:
    def __init__(self, text: str) -> None:
        self._sentences = sentence_spans(text)
        self._starts = [start for _, start, _ in self._sentences]

    def sentence_at(self, offset: int) -> str:
        if not self._sentences:
            return ""
        index = bisect.bisect_right(self._starts, offset) - 1
        if index < 0:
            index = 0
        sentence, start, end = self._sentences[index]
        if offset > end and index + 1 < len(self._sentences):
            return self._sentences[index + 1][0]
        return sentence


def _load_spacy():
    try:
        import spacy
        from spacy.matcher import PhraseMatcher
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("spaCy unavailable, falling back to regex skill matching: %s", exc)
        return None, None, None
    try:
        nlp = spacy.blank("en")
    except Exception as exc:  # pragma: no cover
        logger.warning("spaCy blank pipeline unavailable: %s", exc)
        return None, None, None
    return spacy, PhraseMatcher, nlp


def _build_matchers(taxonomy: SkillTaxonomy):
    _, PhraseMatcher, nlp = _load_spacy()
    if PhraseMatcher is None or nlp is None:
        return None, None, None

    ci_matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
    cs_matcher = PhraseMatcher(nlp.vocab, attr="ORTH")

    for skill in taxonomy:
        ci_phrases: list[str] = []
        cs_phrases: list[str] = []
        for phrase in skill.all_phrases:
            single_token = len(phrase.split()) == 1
            if skill.case_sensitive and single_token:
                cs_phrases.append(phrase)
            else:
                ci_phrases.append(phrase)
        if ci_phrases:
            ci_matcher.add(skill.canonical, [nlp.make_doc(phrase) for phrase in ci_phrases])
        if cs_phrases:
            cs_matcher.add(skill.canonical, [nlp.make_doc(phrase) for phrase in cs_phrases])

    return ci_matcher, cs_matcher, nlp


_MATCHER_CACHE: dict[str, tuple] = {}


def _get_matchers(taxonomy: SkillTaxonomy):
    cached = _MATCHER_CACHE.get(taxonomy.version)
    if cached is None:
        cached = _build_matchers(taxonomy)
        _MATCHER_CACHE[taxonomy.version] = cached
    return cached


def _confidence(status: str) -> float:
    return {"canonical": 1.0, "alias": 0.96, "case_sensitive_alias": 0.9}.get(status, 0.8)


def _spacy_matches(text: str, taxonomy: SkillTaxonomy) -> list[_RawMatch]:
    ci_matcher, cs_matcher, nlp = _get_matchers(taxonomy)
    if ci_matcher is None or cs_matcher is None or nlp is None:
        return []

    doc = nlp(text)
    matches: list[_RawMatch] = []

    for matcher, is_case_sensitive in ((ci_matcher, False), (cs_matcher, True)):
        for match_id, start, end in matcher(doc):
            canonical = doc.vocab.strings[match_id]
            skill = taxonomy.get(canonical)
            if skill is None:
                continue
            span = doc[start:end]
            phrase = span.text
            start_char = doc[start].idx
            end_char = doc[end - 1].idx + len(doc[end - 1].text)
            status = "canonical" if normalize_phrase(phrase) == normalize_phrase(canonical) else "alias"
            if is_case_sensitive:
                status = "case_sensitive_alias"
            matches.append(
                _RawMatch(
                    canonical=canonical,
                    category=skill.category,
                    phrase=phrase,
                    start_char=start_char,
                    end_char=end_char,
                    status=status,
                    confidence=_confidence(status),
                    case_sensitive=is_case_sensitive,
                )
            )
    return matches


def _regex_matches(text: str, taxonomy: SkillTaxonomy) -> list[_RawMatch]:
    """Fallback matcher used only when spaCy is unavailable."""
    matches: list[_RawMatch] = []
    for skill in taxonomy:
        for phrase in skill.all_phrases:
            flags = 0 if skill.case_sensitive and len(phrase.split()) == 1 else re.IGNORECASE
            pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(phrase)}(?![A-Za-z0-9_])", flags)
            for found in pattern.finditer(text):
                status = "case_sensitive_alias" if skill.case_sensitive else (
                    "canonical" if phrase == skill.canonical else "alias"
                )
                matches.append(
                    _RawMatch(
                        canonical=skill.canonical,
                        category=skill.category,
                        phrase=found.group(0),
                        start_char=found.start(),
                        end_char=found.end(),
                        status=status,
                        confidence=_confidence(status) - 0.05,
                        case_sensitive=skill.case_sensitive,
                    )
                )
    return matches


def _single_letter_is_plausible(text: str, match: _RawMatch, section: SectionName) -> bool:
    """Guard against 'R' / 'C' appearing as an ordinary letter in prose."""
    if len(match.canonical) != 1:
        return True
    # A curated skills list is the one place a bare "R" or "C" is unambiguous.
    if section == SectionName.SKILLS:
        return True
    before = text[match.start_char - 1] if match.start_char > 0 else "\n"
    after = text[match.end_char] if match.end_char < len(text) else "\n"
    return bool(_SINGLE_LETTER_CONTEXT.match(before) or _SINGLE_LETTER_CONTEXT.match(after))


def _resolve_overlaps(matches: Iterable[_RawMatch]) -> list[_RawMatch]:
    """Longest match wins; identical spans collapse to the highest-confidence one."""
    ordered = sorted(matches, key=lambda item: (item.start_char, -(item.end_char - item.start_char), -item.confidence))
    accepted: list[_RawMatch] = []
    seen_spans: set[tuple[int, int]] = set()
    for candidate in ordered:
        key = (candidate.start_char, candidate.end_char)
        if key in seen_spans:
            continue
        overlaps = any(
            candidate.start_char < item.end_char and item.start_char < candidate.end_char
            for item in accepted
        )
        if overlaps:
            continue
        seen_spans.add(key)
        accepted.append(candidate)
    return sorted(accepted, key=lambda item: item.start_char)


def _evidence_method(section: SectionName, evidence: str, canonical: str) -> str:
    """Distinguish a curated skill list from a skill mentioned in prose."""
    if section != SectionName.SKILLS:
        return "phrase_matcher"
    tokens = re.findall(r"[A-Za-z0-9+#.]+", evidence)
    if len(tokens) <= 6 and canonical.split()[0].lower() in evidence.lower():
        return "section_list"
    return "phrase_matcher"


def extract_skills(
    text: str,
    *,
    taxonomy: SkillTaxonomy | None = None,
    section_spans: Sequence[SectionSpan] | None = None,
    min_confidence: float | None = None,
    max_mentions_per_section: int = 4,
) -> list[SkillMention]:
    """Extract skill mentions with evidence, section and character offsets."""
    if not text or not text.strip():
        return []

    taxonomy = taxonomy or get_taxonomy()
    settings = get_config()
    threshold = settings.get("skills.min_confidence", 0.6) if min_confidence is None else min_confidence

    regex_only = not _MATCHER_CACHE.get(taxonomy.version, (None,))[0]
    raw = _regex_matches(text, taxonomy) if regex_only else _spacy_matches(text, taxonomy)
    if not raw and not regex_only:
        raw = _regex_matches(text, taxonomy)

    sections = _SectionIndex(section_spans or [])
    sentences = _SentenceIndex(text)

    filtered: list[_RawMatch] = []
    for match in raw:
        section = sections.section_at(match.start_char)
        if not _single_letter_is_plausible(text, match, section):
            continue
        if match.confidence < threshold:
            continue
        filtered.append(match)

    mentions: list[SkillMention] = []
    per_key: dict[tuple[str, str], int] = {}
    for match in _resolve_overlaps(filtered):
        section = sections.section_at(match.start_char)
        key = (match.canonical, section.value)
        if per_key.get(key, 0) >= max_mentions_per_section:
            continue
        evidence = sentences.sentence_at(match.start_char) or text[match.start_char:match.end_char]
        per_key[key] = per_key.get(key, 0) + 1
        mentions.append(
            SkillMention(
                original_text=match.phrase,
                canonical=match.canonical,
                category=match.category,
                section=section,
                evidence=evidence,
                start_char=match.start_char,
                end_char=match.end_char,
                extraction_method=_evidence_method(section, evidence, match.canonical),
                match_status="case_sensitive_alias" if match.case_sensitive else match.status,
                confidence=round(match.confidence, 3),
                normalized_from=None if match.status == "canonical" else match.phrase,
            )
        )

    if not mentions and text.strip():
        logger.debug("No skills extracted from %d characters", len(text))
    return mentions


def extract_skills_from_section(
    text: str,
    section: SectionName,
    *,
    taxonomy: SkillTaxonomy | None = None,
    min_confidence: float | None = None,
) -> list[SkillMention]:
    """Extract from a section that has no ResumeDocument yet (job requirements)."""
    spans = [SectionSpan(section=section, text=text, start_char=0, end_char=len(text), order=0)]
    return extract_skills(
        text, taxonomy=taxonomy, section_spans=spans, min_confidence=min_confidence
    )


def extract_from_phrases(
    phrases: Iterable[str],
    *,
    section: SectionName = SectionName.SKILLS,
    taxonomy: SkillTaxonomy | None = None,
) -> list[SkillMention]:
    """Extract from a list of structured phrases (e.g. a job's skill list).

    Unlike free-text extraction, each phrase is expected to *be* a skill; if the
    phrase contains a known alias it is captured with its own evidence.
    """
    taxonomy = taxonomy or get_taxonomy()
    text = "\n".join(phrases)
    if not text.strip():
        return []
    spans = [SectionSpan(section=section, text=text, start_char=0, end_char=len(text), order=0)]
    return extract_skills(text, taxonomy=taxonomy, section_spans=spans, min_confidence=0.5)


def extract_skills_safe(text: str, **kwargs) -> tuple[list[SkillMention], str | None]:
    """Extraction that degrades to an empty list with a visible warning on failure."""
    try:
        return extract_skills(text, **kwargs), None
    except SkillTaxonomyError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Skill extraction failed")
        return [], f"Skill extraction failed: {type(exc).__name__}"


def count_unique(mentions: Sequence[SkillMention]) -> int:
    return len({mention.canonical for mention in mentions})


def sentences_for_section(text: str, section_text: str) -> list[str]:
    """Helper used by explanations to keep sentence evidence aligned to source text."""
    return split_sentences(section_text) if section_text else split_sentences(text)

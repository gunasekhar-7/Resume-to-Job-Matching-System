"""Sentence-level evidence selection for explanations.

Explanations must point at actual resume text, not text generated from a score. This
module extracts candidate sentences from scored sections, embeds them once per resume,
and selects the highest-similarity sentences for a job's requirements. If nothing
crosses the configured similarity floor, the result is empty rather than fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from talentlens.config import get_config
from talentlens.embeddings.embedder import Embedder
from talentlens.schemas import ResumeDocument, SectionEvidence, SectionName

_EVIDENCE_SECTIONS = (
    SectionName.SUMMARY,
    SectionName.SKILLS,
    SectionName.EXPERIENCE,
    SectionName.PROJECTS,
    SectionName.CERTIFICATIONS,
)
_MIN_SENTENCE_CHARS = 20
_MAX_SENTENCE_CHARS = 400


@dataclass(frozen=True)
class ResumeSentence:
    section: SectionName
    text: str
    start_char: int | None


def _split_sentences(line: str) -> list[str]:
    import re

    parts = re.split(r"(?<=[.!?])\s+|\s*[•;]\s*", line)
    return [part.strip(" \t-–—") for part in parts if part.strip()]


def extract_resume_sentences(document: ResumeDocument) -> list[ResumeSentence]:
    """Extract unique, evidence-sized sentences from sections that may be scored.

    Header and education are deliberately excluded, matching the scoring policy. An
    offset is recorded only when the sentence occurs exactly once in the cleaned text,
    so a displayed offset is never ambiguous.
    """
    sentences: list[ResumeSentence] = []
    seen: set[str] = set()
    for section in _EVIDENCE_SECTIONS:
        for line in document.sections.get(section.value, []):
            for candidate in _split_sentences(line):
                cleaned = " ".join(candidate.split())
                if not (_MIN_SENTENCE_CHARS <= len(cleaned) <= _MAX_SENTENCE_CHARS):
                    continue
                key = cleaned.lower()
                if key in seen:
                    continue
                seen.add(key)
                first = document.full_text.find(cleaned)
                start = first if first >= 0 and document.full_text.find(cleaned, first + 1) < 0 else None
                sentences.append(ResumeSentence(section=section, text=cleaned, start_char=start))
    return sentences


class EvidenceBuilder:
    """Precompute sentence vectors once, then select evidence for each job."""

    def __init__(
        self,
        document: ResumeDocument,
        embedder: Embedder,
        *,
        min_similarity: float | None = None,
        max_items: int | None = None,
    ) -> None:
        config = get_config()
        self.min_similarity = float(
            config.get("matching.evidence.min_similarity", 0.30)
            if min_similarity is None
            else min_similarity
        )
        self.max_items = int(
            config.get("matching.evidence.max_items", 3) if max_items is None else max_items
        )
        self.sentences = extract_resume_sentences(document)
        if self.sentences:
            self.vectors = embedder.encode([sentence.text for sentence in self.sentences])
        else:
            self.vectors = np.zeros((0, embedder.dimension), dtype=np.float32)

    def for_requirement(self, requirement_vector: np.ndarray) -> list[SectionEvidence]:
        if not self.sentences or self.vectors.size == 0:
            return []
        vector = np.asarray(requirement_vector, dtype=np.float32).reshape(-1)
        if vector.shape[0] != self.vectors.shape[1]:
            return []
        similarities = np.clip(self.vectors @ vector, 0.0, 1.0)
        order = np.argsort(-similarities, kind="stable")
        selected: list[SectionEvidence] = []
        used_sections: set[SectionName] = set()
        # Prefer section diversity first, then fill by score. This avoids showing three
        # near-identical skills-list lines as three independent explanations.
        for index in order:
            if len(selected) >= self.max_items:
                break
            score = float(similarities[index])
            if score < self.min_similarity:
                break
            sentence = self.sentences[int(index)]
            if sentence.section in used_sections:
                continue
            used_sections.add(sentence.section)
            selected.append(
                SectionEvidence(
                    section=sentence.section,
                    sentence=sentence.text,
                    similarity=round(score, 6),
                    start_char=sentence.start_char,
                )
            )
        if len(selected) < self.max_items:
            for index in order:
                if len(selected) >= self.max_items:
                    break
                score = float(similarities[index])
                if score < self.min_similarity:
                    break
                sentence = self.sentences[int(index)]
                if any(item.sentence == sentence.text for item in selected):
                    continue
                selected.append(
                    SectionEvidence(
                        section=sentence.section,
                        sentence=sentence.text,
                        similarity=round(score, 6),
                        start_char=sentence.start_char,
                    )
                )
        return selected

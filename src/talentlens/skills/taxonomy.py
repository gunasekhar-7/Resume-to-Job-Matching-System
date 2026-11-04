"""Skill taxonomy: canonical names, categories, aliases and related-skill credit.

The taxonomy is data, not code (``configs/skills_taxonomy.yaml``). Loading is
strict: duplicate canonical names or alias collisions abort with an explicit
error rather than silently producing order-dependent extraction.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from talentlens.config import get_config
from talentlens.errors import SkillTaxonomyError
from talentlens.log import get_logger
from talentlens.utils.text import normalize_for_match

logger = get_logger("skills.taxonomy")


@dataclass(frozen=True)
class Skill:
    canonical: str
    category: str
    category_label: str
    aliases: tuple[str, ...] = ()
    case_sensitive: bool = False
    related: dict[str, float] = field(default_factory=dict)

    @property
    def all_phrases(self) -> tuple[str, ...]:
        return (self.canonical, *self.aliases)


@dataclass(frozen=True)
class AliasMatch:
    canonical: str
    matched_phrase: str
    matched_alias: str
    category: str
    case_sensitive: bool
    match_status: str  # canonical | alias | case_sensitive_alias


class SkillTaxonomy:
    def __init__(self, skills: dict[str, Skill], category_labels: dict[str, str], version: str) -> None:
        self._skills = skills
        self.category_labels = category_labels
        self.version = version
        self._alias_index: dict[str, list[AliasMatch]] = {}
        self._case_sensitive_index: dict[str, list[AliasMatch]] = {}
        self._build_indexes()

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, path: str | Path | None = None) -> SkillTaxonomy:
        taxonomy_path = Path(path) if path else get_config().resolve(get_config().get("skills.taxonomy_path"))
        if not taxonomy_path.exists():
            raise SkillTaxonomyError(f"Skill taxonomy not found: {taxonomy_path}")
        with taxonomy_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}

        category_labels = {str(key): str(value) for key, value in (payload.get("categories") or {}).items()}
        entries = payload.get("skills") or []
        if not entries:
            raise SkillTaxonomyError("Skill taxonomy contains no skills")

        skills: dict[str, Skill] = {}
        for entry in entries:
            name = str(entry.get("name", "")).strip()
            category = str(entry.get("category", "")).strip()
            if not name or not category:
                raise SkillTaxonomyError(f"Skill entry missing name/category: {entry}")
            if category not in category_labels:
                raise SkillTaxonomyError(f"Unknown category '{category}' for skill '{name}'")
            if name in skills:
                raise SkillTaxonomyError(f"Duplicate canonical skill: {name}")
            aliases = tuple(dict.fromkeys(str(alias).strip() for alias in entry.get("aliases") or [] if str(alias).strip()))
            skills[name] = Skill(
                canonical=name,
                category=category,
                category_label=category_labels[category],
                aliases=aliases,
                case_sensitive=bool(entry.get("case_sensitive", False)),
            )

        related_payload = payload.get("related") or {}
        for source, targets in related_payload.items():
            if source not in skills:
                raise SkillTaxonomyError(f"Related-skill source is not a canonical skill: {source}")
            for target, credit in (targets or {}).items():
                if target not in skills:
                    raise SkillTaxonomyError(f"Related-skill target is not a canonical skill: {target}")
                credit_value = float(credit)
                if not 0.0 < credit_value < 1.0:
                    raise SkillTaxonomyError(f"Related credit for {source}->{target} must be in (0, 1)")
                skills[source].related[target] = credit_value

        return cls(skills, category_labels, str(payload.get("version", "unknown")))

    def _build_indexes(self) -> None:
        for skill in self._skills.values():
            entries: list[AliasMatch] = []
            for phrase in skill.all_phrases:
                status = "canonical" if phrase == skill.canonical else "alias"
                entries.append(
                    AliasMatch(
                        canonical=skill.canonical,
                        matched_phrase=phrase,
                        matched_alias=phrase,
                        category=skill.category,
                        case_sensitive=skill.case_sensitive,
                        match_status=("case_sensitive_alias" if skill.case_sensitive else status),
                    )
                )

            for entry in entries:
                single_token = len(entry.matched_phrase.split()) == 1
                if entry.case_sensitive and single_token:
                    self._case_sensitive_index.setdefault(entry.matched_phrase, []).append(entry)
                    continue
                key = normalize_for_match(entry.matched_phrase)
                if not key:
                    continue
                bucket = self._alias_index.setdefault(key, [])
                # Identical canonical/alias (case variants) collapse to one match.
                if not any(item.canonical == entry.canonical for item in bucket):
                    bucket.append(entry)

        for key, matches in self._alias_index.items():
            canonicals = {match.canonical for match in matches}
            if len(canonicals) > 1:
                raise SkillTaxonomyError(
                    f"Alias '{key}' is ambiguous across skills: {sorted(canonicals)}. "
                    "Add a disambiguating alias or mark the skill case-sensitive."
                )
        logger.debug("Loaded %d canonical skills (%d aliases)", len(self._skills), len(self._alias_index))

    # ------------------------------------------------------------------ lookup
    def __contains__(self, canonical: str) -> bool:
        return canonical in self._skills

    def __len__(self) -> int:
        return len(self._skills)

    def __iter__(self) -> Iterable[Skill]:
        return iter(self._skills.values())

    def get(self, canonical: str) -> Skill | None:
        return self._skills.get(canonical)

    @property
    def canonical_names(self) -> list[str]:
        return list(self._skills)

    def category_of(self, canonical: str) -> str:
        skill = self._skills.get(canonical)
        return skill.category if skill else "unknown"

    def label_for_category(self, category: str) -> str:
        return self.category_labels.get(category, category.replace("_", " ").title())

    def resolve(self, phrase: str, *, case_sensitive: bool = False) -> AliasMatch | None:
        """Resolve a free-text phrase to a canonical skill, if it is a known alias."""
        cleaned = phrase.strip()
        if not cleaned:
            return None
        if case_sensitive:
            cs_hits = self._case_sensitive_index.get(cleaned)
            if cs_hits:
                return cs_hits[0]
        key = normalize_for_match(cleaned)
        hits = self._alias_index.get(key)
        return hits[0] if hits else None

    def case_sensitive_phrases(self) -> list[str]:
        return sorted(self._case_sensitive_index)

    def case_insensitive_phrases(self) -> list[str]:
        phrases: dict[str, str] = {}
        for skill in self._skills.values():
            for phrase in skill.all_phrases:
                if skill.case_sensitive and len(phrase.split()) == 1:
                    continue
                phrases.setdefault(normalize_for_match(phrase), phrase)
        return [phrase for phrase in phrases.values() if phrase]

    def related_credit(self, resume_skill: str, job_skill: str) -> float:
        """Partial credit if the two skills are explicitly related in the taxonomy."""
        if resume_skill == job_skill:
            return 1.0
        source = self._skills.get(resume_skill)
        target = self._skills.get(job_skill)
        if not source or not target:
            return 0.0
        credits = [source.related.get(job_skill, 0.0), target.related.get(resume_skill, 0.0)]
        return max(credits)

    def describe(self) -> dict:
        categories: dict[str, int] = {}
        for skill in self._skills.values():
            categories[skill.category] = categories.get(skill.category, 0) + 1
        return {
            "version": self.version,
            "skills": len(self._skills),
            "categories": categories,
            "case_sensitive": len(self._case_sensitive_index),
        }


_TAXONOMY: SkillTaxonomy | None = None


def get_taxonomy() -> SkillTaxonomy:
    global _TAXONOMY
    if _TAXONOMY is None:
        _TAXONOMY = SkillTaxonomy.load()
    return _TAXONOMY


def reset_taxonomy_cache() -> None:
    global _TAXONOMY
    _TAXONOMY = None

"""Configurable weighted hybrid scorer.

Each component is normalised to [0, 1] *before* weighting. The total is the weighted
sum, and every contribution is returned so a ranking can be reproduced by hand.

The score is a relevance/match score. It is not a probability of being hired.
"""

from __future__ import annotations

from dataclasses import dataclass

from talentlens.config import get_config
from talentlens.errors import ConfigurationError
from talentlens.schemas import ScoreBreakdown, ScoreContribution

COMPONENT_LABELS = {
    "semantic": "Whole-document semantic similarity",
    "section_relevance": "Section-level semantic relevance",
    "required_skills": "Required skill coverage",
    "preferred_skills": "Preferred skill coverage",
    "experience": "Experience alignment",
    "tfidf": "TF-IDF cosine baseline",
}

#: Maps config weight names to the field names used in ``ScoreBreakdown``.
_WEIGHT_TO_FIELD = {
    "semantic": "semantic",
    "section_relevance": "section_relevance",
    "required_skills": "required_coverage",
    "preferred_skills": "preferred_coverage",
    "experience": "experience_alignment",
}


@dataclass(frozen=True)
class ScoringWeights:
    semantic: float
    section_relevance: float
    required_skills: float
    preferred_skills: float
    experience: float

    @classmethod
    def from_config(cls, weights: dict[str, float] | None = None) -> ScoringWeights:
        payload = weights or get_config().weights
        missing = set(_WEIGHT_TO_FIELD) - set(payload)
        if missing:
            raise ConfigurationError(f"Missing matching weights: {sorted(missing)}")
        values = cls(
            semantic=float(payload["semantic"]),
            section_relevance=float(payload["section_relevance"]),
            required_skills=float(payload["required_skills"]),
            preferred_skills=float(payload["preferred_skills"]),
            experience=float(payload["experience"]),
        )
        if any(value < 0 for value in values.as_dict().values()):
            raise ConfigurationError("Matching weights must be non-negative")
        if abs(sum(values.as_dict().values()) - 1.0) > 1e-6:
            raise ConfigurationError(
                f"Matching weights must sum to 1.0 (got {sum(values.as_dict().values()):.6f})"
            )
        return values

    def as_dict(self) -> dict[str, float]:
        return {
            "semantic": self.semantic,
            "section_relevance": self.section_relevance,
            "required_skills": self.required_skills,
            "preferred_skills": self.preferred_skills,
            "experience": self.experience,
        }


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 6)


def _fmt(value: float) -> str:
    return f"{value:.3f}"


class HybridScorer:
    def __init__(self, weights: ScoringWeights | None = None) -> None:
        self.weights = weights or ScoringWeights.from_config()

    def score(self, components: dict[str, float]) -> ScoreBreakdown:
        missing = set(_WEIGHT_TO_FIELD.values()) - set(components)
        if missing:
            raise ConfigurationError(f"Missing score components: {sorted(missing)}")
        values = {key: _clamp(value) for key, value in components.items()}
        weights = self.weights.as_dict()

        contributions: list[ScoreContribution] = []
        total = 0.0
        for weight_key, field in _WEIGHT_TO_FIELD.items():
            raw = values[field]
            weight = weights[weight_key]
            contribution = round(raw * weight, 6)
            total += contribution
            contributions.append(
                ScoreContribution(
                    component=weight_key,
                    raw=raw,
                    weight=weight,
                    contribution=contribution,
                    label=COMPONENT_LABELS[weight_key],
                )
            )

        total = _clamp(total)
        formula = " + ".join(
            f"{item.weight:.2f}×{item.component} {_fmt(item.raw)}" for item in contributions
        )
        return ScoreBreakdown(
            semantic=values["semantic"],
            section_relevance=values["section_relevance"],
            required_coverage=values["required_coverage"],
            preferred_coverage=values["preferred_coverage"],
            experience_alignment=values["experience_alignment"],
            tfidf=values.get("tfidf"),
            total=total,
            weights=weights,
            contributions=contributions,
            explanation=(
                f"Hybrid score = {formula} = {_fmt(total)}. "
                "Each component is normalised to 0-1 before weighting."
            ),
        )

    @staticmethod
    def baseline(components: dict[str, float], *, baseline: str) -> ScoreBreakdown:
        """Breakdown for a single-retriever baseline (TF-IDF or semantic only).

        Other components are still computed and returned for diagnostics, but the
        total equals the baseline score and the contribution list says so explicitly.
        """
        if baseline not in {"tfidf", "semantic"}:
            raise ConfigurationError(f"Unknown baseline '{baseline}'")
        if baseline not in components:
            raise ConfigurationError(f"Baseline component '{baseline}' missing")
        score = _clamp(components[baseline])
        contributions = [
            ScoreContribution(
                component=baseline,
                raw=score,
                weight=1.0,
                contribution=score,
                label=COMPONENT_LABELS[baseline],
            )
        ]
        return ScoreBreakdown(
            semantic=_clamp(components.get("semantic", 0.0)),
            section_relevance=_clamp(components.get("section_relevance", 0.0)),
            required_coverage=_clamp(components.get("required_coverage", 0.0)),
            preferred_coverage=_clamp(components.get("preferred_coverage", 0.0)),
            experience_alignment=_clamp(components.get("experience_alignment", 0.0)),
            tfidf=_clamp(components["tfidf"]) if "tfidf" in components else None,
            total=score,
            weights={baseline: 1.0},
            contributions=contributions,
            explanation=(
                f"{COMPONENT_LABELS[baseline]} baseline = {_fmt(score)}. "
                "Other components are diagnostics only and do not affect this total."
            ),
        )

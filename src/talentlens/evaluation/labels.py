"""Relevance labels and the frozen Phase 1 split.

The split is grouped by resume: every job judged for a resume stays in that resume's
split. This prevents a resume (or a format variant of it) from leaking across
development, validation and test. The test split is used exactly once, after weights
are frozen.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Frozen Phase 1 assignment. Changing this requires a new evaluation run and an ADR.
SPLIT_RESUME_IDS: dict[str, tuple[str, ...]] = {
    "dev": ("r01", "r02", "r03", "r04", "r05", "r06", "r07"),
    "validation": ("r08", "r09", "r10"),
    "test": ("r11", "r12", "r13", "r14"),
}


class RelevanceLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair_id: str
    resume_id: str
    job_id: str
    relevance: int = Field(ge=0, le=2)
    rationale: str = ""
    annotator: str = ""
    source: str = ""
    annotated_at: date | None = None

    @field_validator("pair_id", "resume_id", "job_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifier must not be blank")
        return value.strip()


def load_labels(path: str | Path) -> list[RelevanceLabel]:
    labels: list[RelevanceLabel] = []
    seen: set[str] = set()
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                label = RelevanceLabel.model_validate_json(line)
            except Exception as exc:
                raise ValueError(f"Invalid relevance label on line {line_number}: {exc}") from exc
            if label.pair_id in seen:
                raise ValueError(f"Duplicate pair_id {label.pair_id!r} on line {line_number}")
            seen.add(label.pair_id)
            labels.append(label)
    return labels


def split_for_resume(resume_id: str) -> str:
    for split, resume_ids in SPLIT_RESUME_IDS.items():
        if resume_id in resume_ids:
            return split
    raise KeyError(f"Resume {resume_id!r} is not assigned to a split")


def split_labels(
    labels: list[RelevanceLabel], split: str
) -> dict[str, dict[str, int]]:
    if split not in SPLIT_RESUME_IDS:
        raise ValueError(f"Unknown split {split!r}; expected one of {sorted(SPLIT_RESUME_IDS)}")
    allowed = set(SPLIT_RESUME_IDS[split])
    result: dict[str, dict[str, int]] = {}
    for label in labels:
        if label.resume_id in allowed:
            result.setdefault(label.resume_id, {})[label.job_id] = label.relevance
    return result


def validate_splits() -> None:
    seen: dict[str, str] = {}
    for split, resume_ids in SPLIT_RESUME_IDS.items():
        if not resume_ids:
            raise ValueError(f"Split {split!r} is empty")
        for resume_id in resume_ids:
            if resume_id in seen:
                raise ValueError(
                    f"Resume {resume_id!r} appears in both {seen[resume_id]!r} and {split!r}"
                )
            seen[resume_id] = split

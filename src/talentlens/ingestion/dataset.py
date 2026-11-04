"""Dataset assembly, duplicate detection and data-quality reporting.

The processed corpus is written as JSONL (one ``ResumeDocument`` per line) so
that downstream phases can load it without re-parsing documents. Duplicate
detection works at two levels:

* source hash - identical uploads;
* normalised text fingerprint - the same resume rendered as PDF and DOCX.

Format variants of the same resume are expected; the canonical record is chosen
by measured extraction quality (with a deterministic format tie-break), and the
others are recorded as duplicates rather than silently discarded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from talentlens.config import get_config
from talentlens.errors import TalentLensError
from talentlens.ingestion.loader import load_path
from talentlens.log import get_logger
from talentlens.parsing.resume_parser import parse_upload
from talentlens.schemas import ResumeDocument
from talentlens.utils.text import content_sha256

logger = get_logger("ingestion.dataset")

_FORMAT_PRIORITY = {"pdf": 0, "docx": 1, "txt": 2}


@dataclass
class ParseAttempt:
    resume_id: str
    path: str
    source_format: str
    status: str
    error_code: str | None = None
    error_message: str | None = None
    quality: float = 0.0
    section_count: int = 0
    skill_count: int = 0
    document: ResumeDocument | None = None


@dataclass
class CorpusResult:
    documents: list[ResumeDocument] = field(default_factory=list)
    attempts: list[ParseAttempt] = field(default_factory=list)
    duplicates: list[dict[str, str]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def text_fingerprint(document: ResumeDocument) -> str:
    normalized = " ".join(document.full_text.lower().split())
    return content_sha256(normalized)


def load_manifest(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Sample manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def ingest_resume_files(
    entries: list[tuple[str, Path]],
    *,
    prefer_format: str = "pdf",
    reject_failed: bool = False,
) -> CorpusResult:
    """Parse ``(resume_id, path)`` pairs, de-duplicate and choose canonical records."""
    result = CorpusResult()
    grouped: dict[str, list[ParseAttempt]] = {}

    for resume_id, path in entries:
        attempt = _attempt(resume_id, path)
        result.attempts.append(attempt)
        if attempt.document is not None:
            grouped.setdefault(resume_id, []).append(attempt)
        if reject_failed and attempt.document is None:
            continue

    for resume_id, attempts in grouped.items():
        usable = [item for item in attempts if item.document is not None]
        if not usable:
            continue
        usable.sort(
            key=lambda item: (
                -round(item.quality, 3),
                _FORMAT_PRIORITY.get(item.source_format, 9),
                0 if item.source_format == prefer_format else 1,
            )
        )
        canonical = usable[0]
        assert canonical.document is not None
        result.documents.append(canonical.document)
        for other in usable[1:]:
            assert other.document is not None
            result.duplicates.append(
                {
                    "kept": canonical.path,
                    "duplicate": other.path,
                    "resume_id": resume_id,
                    "reason": "same resume, alternate format",
                    "text_fingerprint": text_fingerprint(other.document)[:16],
                }
            )

    # Cross-resume duplicate detection (different IDs, near-identical text).
    seen: dict[str, str] = {}
    unique_documents: list[ResumeDocument] = []
    for document in result.documents:
        fingerprint = text_fingerprint(document)
        if fingerprint in seen:
            result.duplicates.append(
                {
                    "kept": seen[fingerprint],
                    "duplicate": document.resume_id,
                    "resume_id": document.resume_id,
                    "reason": "identical text fingerprint",
                    "text_fingerprint": fingerprint[:16],
                }
            )
            continue
        seen[fingerprint] = document.resume_id
        unique_documents.append(document)
    result.documents = unique_documents
    result.stats = compute_stats(result)
    return result


def _attempt(resume_id: str, path: Path) -> ParseAttempt:
    attempt = ParseAttempt(resume_id=resume_id, path=str(path), source_format=path.suffix.lstrip("."), status="failed")
    try:
        upload = load_path(path)
        document = parse_upload(upload, resume_id=resume_id)
    except TalentLensError as exc:
        attempt.error_code = exc.code
        attempt.error_message = exc.message
        logger.warning("Parse failed for %s: %s (%s)", path.name, exc.code, exc.message)
        return attempt
    except Exception as exc:  # pragma: no cover - defensive
        attempt.error_code = "unexpected_error"
        attempt.error_message = f"{type(exc).__name__}: {exc}"
        logger.exception("Unexpected parse failure for %s", path.name)
        return attempt

    attempt.status = document.metadata.parsing_status.value
    attempt.quality = document.metadata.extraction_quality
    attempt.section_count = sum(1 for lines in document.sections.values() if lines)
    attempt.skill_count = len({skill.canonical for skill in document.skills})
    attempt.document = document
    return attempt


def compute_stats(result: CorpusResult) -> dict[str, Any]:
    documents = result.documents
    attempts = result.attempts
    status_counts: dict[str, int] = {}
    for document in documents:
        key = document.metadata.parsing_status.value
        status_counts[key] = status_counts.get(key, 0) + 1

    section_presence: dict[str, int] = {}
    for document in documents:
        for name, lines in document.sections.items():
            if lines:
                section_presence[name] = section_presence.get(name, 0) + 1

    skills = [skill for document in documents for skill in document.skills]
    warnings: dict[str, int] = {}
    for document in documents:
        for warning in document.metadata.warnings:
            warnings[warning] = warnings.get(warning, 0) + 1

    total = max(1, len(documents))
    return {
        "files_attempted": len(attempts),
        "files_parsed": sum(1 for attempt in attempts if attempt.document is not None),
        "files_failed": sum(1 for attempt in attempts if attempt.document is None),
        "unique_resumes": len(documents),
        "duplicates_removed": len(result.duplicates),
        "status_counts": status_counts,
        "section_presence": section_presence,
        "section_coverage_pct": {
            name: round(100 * count / total, 1) for name, count in sorted(section_presence.items())
        },
        "avg_extraction_quality": round(
            sum(document.metadata.extraction_quality for document in documents) / total, 3
        ),
        "avg_skills_per_resume": round(sum(len({s.canonical for s in d.skills}) for d in documents) / total, 1),
        "skill_mentions": len(skills),
        "unique_canonical_skills": len({skill.canonical for skill in skills}),
        "warnings_top": dict(sorted(warnings.items(), key=lambda item: -item[1])[:10]),
        "failed_attempts": [
            {
                "path": attempt.path,
                "format": attempt.source_format,
                "error_code": attempt.error_code,
                "error_message": attempt.error_message,
            }
            for attempt in attempts
            if attempt.document is None
        ],
        "per_resume": [
            {
                "resume_id": document.resume_id,
                "format": document.metadata.source_format.value,
                "status": document.metadata.parsing_status.value,
                "quality": document.metadata.extraction_quality,
                "chars": document.metadata.char_count,
                "sections": sorted(name for name, lines in document.sections.items() if lines),
                "skills": len({skill.canonical for skill in document.skills}),
                "warnings": len(document.metadata.warnings),
            }
            for document in sorted(documents, key=lambda item: item.resume_id)
        ],
    }


def write_corpus_jsonl(documents: list[ResumeDocument], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for document in documents:
            handle.write(document.model_dump_json() + "\n")
    return output


def read_corpus_jsonl(path: str | Path) -> list[ResumeDocument]:
    documents: list[ResumeDocument] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                documents.append(ResumeDocument.model_validate_json(line))
    return documents


def quality_report_markdown(stats: dict[str, Any], corpus_name: str) -> str:
    lines = [
        f"# Data quality report - {corpus_name}",
        "",
        "Generated by `scripts/ingest_resumes.py`. Figures below come from the actual parse run.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Files attempted | {stats['files_attempted']} |",
        f"| Files parsed | {stats['files_parsed']} |",
        f"| Files failed | {stats['files_failed']} |",
        f"| Unique resumes | {stats['unique_resumes']} |",
        f"| Duplicates removed | {stats['duplicates_removed']} |",
        f"| Average extraction quality | {stats['avg_extraction_quality']} |",
        f"| Average canonical skills per resume | {stats['avg_skills_per_resume']} |",
        f"| Skill mentions (all occurrences) | {stats['skill_mentions']} |",
        f"| Unique canonical skills | {stats['unique_canonical_skills']} |",
        "",
        "## Parsing status",
        "",
        "| Status | Resumes |",
        "| --- | --- |",
    ]
    for status, count in sorted(stats["status_counts"].items()):
        lines.append(f"| {status} | {count} |")

    lines += ["", "## Section coverage", "", "| Section | Resumes | Coverage |", "| --- | --- | --- |"]
    for section, count in stats["section_coverage_pct"].items():
        lines.append(f"| {section} | {stats['section_presence'].get(section, 0)} | {count}% |")

    lines += [
        "",
        "## Per-resume results",
        "",
        "| Resume | Format | Status | Quality | Chars | Skills | Sections |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in stats["per_resume"]:
        lines.append(
            f"| {row['resume_id']} | {row['format']} | {row['status']} | {row['quality']} | "
            f"{row['chars']} | {row['skills']} | {', '.join(row['sections'])} |"
        )

    if stats["failed_attempts"]:
        lines += ["", "## Failed files", "", "| File | Format | Error | Message |", "| --- | --- | --- | --- |"]
        for failure in stats["failed_attempts"]:
            lines.append(
                f"| {Path(failure['path']).name} | {failure['format']} | {failure['error_code']} | "
                f"{failure['error_message']} |"
            )

    if stats["warnings_top"]:
        lines += ["", "## Most common warnings", "", "| Warning | Count |", "| --- | --- |"]
        for warning, count in stats["warnings_top"].items():
            lines.append(f"| {warning} | {count} |")

    lines += [
        "",
        "## Interpretation notes",
        "",
        "- Extraction quality is a transparent heuristic (volume, lexical richness, alphabetic ratio, line",
        "  diversity, section coverage), not a probability of correctness.",
        "- A `partial` status means the document parsed but surfaced warnings (missing sections, low quality,",
        "  or ambiguous structure). Warnings are retained on the document metadata.",
        "- Section coverage counts only resumes where the section contains body text.",
        "",
    ]
    return "\n".join(lines)


def sample_corpus_entries(manifest: dict[str, Any]) -> list[tuple[str, Path]]:
    root = get_config().project_root
    entries: list[tuple[str, Path]] = []
    for resume in manifest.get("resumes", []):
        for file_info in resume.get("files", []):
            entries.append((resume["resume_id"], root / file_info["path"]))
    return entries

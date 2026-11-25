"""Resume parsing orchestration.

``parse_upload`` is the single entry point used by the API, CLI scripts and
tests. It never silently swallows a failure: structural problems are reflected
in ``metadata.parsing_status`` and ``metadata.warnings``, and corrupt files raise
a typed ``ParsingError``.
"""

from __future__ import annotations

from pathlib import Path

from talentlens.config import Config, get_config
from talentlens.errors import EmptyDocumentError, ParsingError
from talentlens.ingestion.loader import UploadedDocument, load_path, read_text_file
from talentlens.log import get_logger
from talentlens.parsing.cleaning import (
    clean_pages,
    extraction_quality,
    is_low_text,
    looks_like_warehouse_dump,
)
from talentlens.parsing.docx_parser import extract_docx
from talentlens.parsing.pdf_parser import extract_pdf
from talentlens.parsing.pii import detect_pii, redact_text, redact_with_placeholder
from talentlens.parsing.sections import build_section_lists, detect_sections
from talentlens.schemas import (
    ParsingStatus,
    ResumeDocument,
    ResumeMetadata,
    SectionName,
    SourceFormat,
)
from talentlens.skills.extractor import count_unique, extract_skills
from talentlens.skills.taxonomy import SkillTaxonomy, get_taxonomy
from talentlens.utils.ids import resume_id_for
from talentlens.utils.text import content_sha256, word_count

logger = get_logger("parsing.resume")

#: Hard cap on text handed to embeddings/LLM-free analysis (bounds cost and memory).
MAX_RESUME_CHARS = 120_000

#: Sections whose absence is worth surfacing to the user.
CRITICAL_SECTIONS = (SectionName.SKILLS, SectionName.EXPERIENCE)


def parse_upload(
    upload: UploadedDocument,
    *,
    resume_id: str | None = None,
    taxonomy: SkillTaxonomy | None = None,
    keep_page_break_markers: bool | None = None,
    config: Config | None = None,
) -> ResumeDocument:
    config = config or get_config()
    parser_version = str(config.get("parsing.parser_version", "1.0.0"))
    warnings: list[str] = []

    pages: list[str]
    page_count: int | None = None
    forced_headings: set[str] = set()
    ocr_used = False
    ocr_confidence: float | None = None

    if upload.source_format == SourceFormat.PDF:
        extraction = extract_pdf(upload.content, filename=upload.filename)
        pages = extraction.pages
        page_count = extraction.page_count
        warnings.extend(extraction.warnings)
        ocr_used = extraction.ocr_used
        ocr_confidence = extraction.ocr_confidence
    elif upload.source_format == SourceFormat.DOCX:
        extraction = extract_docx(upload.content, filename=upload.filename)
        pages = [extraction.text]
        forced_headings = extraction.forced_headings
        warnings.extend(extraction.warnings)
    elif upload.source_format == SourceFormat.TXT:
        pages = [read_text_file(upload)]
    else:  # pragma: no cover - guarded by the upload validator
        raise ParsingError(f"Unsupported source format: {upload.source_format}")

    keep_markers = (
        bool(config.get("parsing.keep_page_break_markers", False))
        if keep_page_break_markers is None
        else keep_page_break_markers
    )
    cleaning = clean_pages(pages, keep_page_break_markers=keep_markers)
    text = cleaning.text
    warnings.extend(cleaning.warnings)

    if len(text) > MAX_RESUME_CHARS:
        warnings.append(
            f"Resume text truncated from {len(text)} to {MAX_RESUME_CHARS} characters for processing"
        )
        text = text[:MAX_RESUME_CHARS]

    if not text.strip():
        warnings.append("No extractable text found; the document may be scanned or image-only")
        return _failed_document(upload, warnings, parser_version, page_count, ocr_used, ocr_confidence)

    # Detect once, then redact before section/skill extraction so stored text, offsets,
    # evidence and embeddings all refer to the same privacy-safe representation.
    use_presidio = bool(config.get("privacy.presidio_enabled", False))
    pii_scan = detect_pii(text, use_presidio=use_presidio)
    if pii_scan.has_pii and bool(config.get("privacy.pii_redaction_enabled", True)):
        placeholder = str(config.get("privacy.redaction_placeholder", "[REDACTED]"))
        text = redact_with_placeholder(
            text,
            pii_scan,
            placeholder,
        )
        source_path = Path(upload.filename)
        source_filename = redact_text(source_path.stem, placeholder) + source_path.suffix
    else:
        source_filename = upload.filename

    if looks_like_warehouse_dump(text):
        warnings.append("Table content was extracted as very long lines; section structure may be unreliable")

    section_result = detect_sections(text, forced_headings=forced_headings)
    warnings.extend(section_result.warnings)
    sections = build_section_lists(section_result.spans)

    for critical in CRITICAL_SECTIONS:
        if not sections.get(critical.value):
            warnings.append(f"No '{critical.value}' section was detected")

    if len(section_result.spans) <= 1:
        warnings.append("Only one content block was detected; resume structure may be incomplete")

    low_text = is_low_text(text)
    if low_text:
        warnings.append(
            "Insufficient extractable text (possible scanned or image-only document); "
            "parsing did not produce a usable resume"
        )

    skills, extraction_warning = _safe_extract(text, section_result.spans, taxonomy)
    if extraction_warning:
        warnings.append(extraction_warning)
    if text.strip() and not skills:
        warnings.append("No known skills were extracted from this document")

    quality = extraction_quality(text, page_count=page_count, section_count=len(sections))
    if quality < 0.45 and not low_text:
        warnings.append(f"Low extraction quality score ({quality:.2f}); review the parsed output carefully")

    missing_skill_section = not sections.get(SectionName.SKILLS.value)
    if missing_skill_section and skills:
        warnings.append("Skills were found outside a dedicated skills section")

    status = ParsingStatus.FAILED if low_text else (
        ParsingStatus.PARTIAL if warnings else ParsingStatus.SUCCESS
    )

    metadata = ResumeMetadata(
        source_format=upload.source_format,
        source_filename=source_filename,
        sha256=upload.sha256,
        page_count=page_count,
        parsing_status=status,
        warnings=_dedupe(warnings),
        ocr_used=ocr_used,
        ocr_confidence=ocr_confidence,
        char_count=len(text),
        extraction_quality=quality,
        parser_version=parser_version,
        pii_entity_types=pii_scan.entity_types,
        low_text_warning=low_text,
    )

    document = ResumeDocument(
        resume_id=resume_id or resume_id_for(upload.sha256),
        full_text=text,
        sections=sections,
        section_spans=section_result.spans,
        skills=skills,
        metadata=metadata,
    )
    logger.info(
        "Parsed %s (%s, %d chars, %d sections, %d skills, status=%s)",
        document.resume_id,
        upload.source_format.value,
        len(text),
        len(sections),
        len(skills),
        status.value,
    )
    return document


def _safe_extract(text, spans, taxonomy):
    try:
        mentions = extract_skills(text, section_spans=spans, taxonomy=taxonomy or get_taxonomy())
        return mentions, None
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Skill extraction error")
        return [], f"Skill extraction failed: {type(exc).__name__}"


def _failed_document(
    upload: UploadedDocument,
    warnings: list[str],
    parser_version: str,
    page_count: int | None,
    ocr_used: bool,
    ocr_confidence: float | None,
) -> ResumeDocument:
    metadata = ResumeMetadata(
        source_format=upload.source_format,
        source_filename=upload.filename,
        sha256=upload.sha256,
        page_count=page_count,
        parsing_status=ParsingStatus.FAILED,
        warnings=_dedupe([*warnings, "Parsing failed: no usable text content"]),
        ocr_used=ocr_used,
        ocr_confidence=ocr_confidence,
        char_count=0,
        extraction_quality=0.0,
        parser_version=parser_version,
        low_text_warning=True,
    )
    logger.warning("Parsing produced no text for %s", upload.sha256[:12])
    return ResumeDocument(
        resume_id=resume_id_for(upload.sha256),
        full_text="",
        sections={},
        section_spans=[],
        skills=[],
        metadata=metadata,
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def parse_file(
    path: str | Path,
    *,
    resume_id: str | None = None,
    taxonomy: SkillTaxonomy | None = None,
    config: Config | None = None,
) -> ResumeDocument:
    upload = load_path(path)
    return parse_upload(
        upload,
        resume_id=resume_id or Path(path).stem,
        taxonomy=taxonomy,
        config=config,
    )


def parse_bytes(
    filename: str,
    content: bytes,
    *,
    resume_id: str | None = None,
    taxonomy: SkillTaxonomy | None = None,
    config: Config | None = None,
) -> ResumeDocument:
    from talentlens.ingestion.loader import validate_upload

    upload = validate_upload(filename, content)
    return parse_upload(upload, resume_id=resume_id, taxonomy=taxonomy, config=config)


def ensure_usable(document: ResumeDocument) -> None:
    """Raise when a parsed resume cannot support matching."""
    if document.metadata.parsing_status == ParsingStatus.FAILED:
        detail = "; ".join(document.metadata.warnings) or "no extractable text"
        raise EmptyDocumentError(f"Resume could not be used: {detail}")
    if word_count(document.full_text) < 15:
        raise EmptyDocumentError("Resume contains too little text to match against jobs")


def resume_summary(document: ResumeDocument) -> dict[str, object]:
    """Compact, non-sensitive summary for logs and API responses."""
    return {
        "resume_id": document.resume_id,
        "status": document.metadata.parsing_status.value,
        "sections": {name: len(lines) for name, lines in document.sections.items()},
        "skill_count": count_unique(document.skills),
        "has_pii": bool(document.metadata.pii_entity_types),
        "fingerprint": content_sha256(*document.sections.get("experience", []))[:16],
    }

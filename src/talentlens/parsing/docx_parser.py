"""DOCX extraction preserving document body order (paragraphs and tables)."""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from talentlens.errors import CorruptDocumentError
from talentlens.log import get_logger
from talentlens.parsing.sections import normalize_heading

logger = get_logger("parsing.docx")


@dataclass
class DocxExtraction:
    text: str = ""
    forced_headings: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    table_count: int = 0
    paragraph_count: int = 0


def _is_heading_style(style_name: str) -> bool:
    normalized = (style_name or "").lower()
    return normalized.startswith("heading") or normalized in {"title", "subtitle"}


def _is_list_style(style_name: str) -> bool:
    return "list" in (style_name or "").lower()


def extract_docx(content: bytes, *, filename: str = "document.docx") -> DocxExtraction:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:  # pragma: no cover - python-docx is a hard dependency
        raise CorruptDocumentError("python-docx is not installed") from exc

    try:
        document = Document(io.BytesIO(content))
    except Exception as exc:
        raise CorruptDocumentError(f"Could not open DOCX '{filename}': {type(exc).__name__}") from exc

    result = DocxExtraction()
    lines: list[str] = []

    def add_paragraph(paragraph) -> None:
        text = (paragraph.text or "").strip()
        style_name = getattr(paragraph.style, "name", "") or ""
        if not text:
            lines.append("")
            return
        if _is_heading_style(style_name):
            result.forced_headings.add(normalize_heading(text))
            lines.append(text)
        elif _is_list_style(style_name):
            lines.append(f"- {text}")
        else:
            lines.append(text)
        result.paragraph_count += 1

    try:
        body = document.element.body
        for child in body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                add_paragraph(Paragraph(child, document))
            elif tag == "tbl":
                table = Table(child, document)
                result.table_count += 1
                lines.append("")
                for row in table.rows:
                    for cell in row.cells:
                        for paragraph in cell.paragraphs:
                            add_paragraph(paragraph)
                    lines.append("")
            elif tag == "sdt":
                # Content controls wrap paragraphs/tables; fall back to the whole-document order.
                continue
    except Exception as exc:
        raise CorruptDocumentError(f"DOCX body could not be read: {type(exc).__name__}") from exc

    text = "\n".join(lines).strip()
    if not text:
        result.warnings.append("DOCX document contains no extractable text")
    result.text = text
    logger.debug(
        "Extracted DOCX: %d paragraphs, %d tables, %d chars",
        result.paragraph_count,
        result.table_count,
        len(text),
    )
    return result

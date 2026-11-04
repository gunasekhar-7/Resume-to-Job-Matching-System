"""PDF text extraction with column-aware reading order.

PyMuPDF returns text blocks. For two-column resumes, naive y-ordering
interleaves the columns and destroys section structure. ``_order_blocks``
detects a vertical gutter and emits: full-width header blocks (top of page),
then the left column, then the right column. If the geometry is ambiguous the
extractor falls back to plain y-ordering rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from talentlens.config import get_config
from talentlens.errors import CorruptDocumentError, EmptyDocumentError, ParsingError
from talentlens.log import get_logger
from talentlens.parsing.ocr import OCRUnavailableError, ocr_pdf_page

logger = get_logger("parsing.pdf")

#: Minimum horizontal gap (as a fraction of page width) to treat as a column gutter.
_MIN_GUTTER_RATIO = 0.12


@dataclass
class PDFExtraction:
    pages: list[str] = field(default_factory=list)
    page_count: int = 0
    warnings: list[str] = field(default_factory=list)
    ocr_used: bool = False
    ocr_confidence: float | None = None
    encrypted: bool = False


def _block_records(page) -> list[tuple[float, float, float, float, str]]:
    records: list[tuple[float, float, float, float, str]] = []
    page_height = float(page.rect.height)
    for block in page.get_text("blocks"):
        if len(block) < 5:
            continue
        x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
        block_type = block[6] if len(block) > 6 else 0
        if block_type != 0:
            continue
        # Running footers/headers sit outside the content area and would otherwise
        # create a spurious column gutter (their x position is unrelated to body text).
        if page_height > 0 and (y0 > page_height * 0.94 or y1 < page_height * 0.02):
            continue
        cleaned = (text or "").replace("\n", " ").strip()
        if cleaned:
            records.append((float(x0), float(y0), float(x1), float(y1), cleaned))
    return records


def _detect_gutter(
    blocks: list[tuple[float, float, float, float, str]], page_width: float
) -> tuple[float, float] | None:
    """Return ``(split_x, right_column_start_x)`` for a two-column page, else ``None``."""
    if len(blocks) < 8 or page_width <= 0:
        return None
    starts = sorted({round(block[0], 1) for block in blocks})
    candidates: list[tuple[float, float, float]] = []
    for left_edge, right_edge in zip(starts, starts[1:], strict=False):
        gap = right_edge - left_edge
        if gap < page_width * _MIN_GUTTER_RATIO:
            continue
        if left_edge > page_width * 0.55 or right_edge < page_width * 0.3:
            continue
        candidates.append((gap, left_edge, right_edge))
    if not candidates:
        return None

    # Score candidates by how many blocks sit on each side so that a stray
    # element (e.g. a wide footer) cannot define the gutter on its own.
    best: tuple[int, float, float, float] | None = None
    for gap, left_edge, right_edge in candidates:
        left_blocks = [block for block in blocks if block[0] <= left_edge + 2]
        right_blocks = [block for block in blocks if block[0] >= right_edge - 2]
        if len(left_blocks) < 4 or len(right_blocks) < 3:
            continue
        # A block that extends past the gutter means the layout is not cleanly two-column.
        if max(block[2] for block in left_blocks) > right_edge + 8:
            continue
        # Columns must overlap vertically; otherwise this is just indented single-column text.
        if min(block[1] for block in right_blocks) > max(block[3] for block in left_blocks) - 40:
            continue
        score = min(len(left_blocks), len(right_blocks))
        if best is None or score > best[0] or (score == best[0] and gap > best[1]):
            best = (score, gap, (left_edge + right_edge) / 2, right_edge)
    return (best[2], best[3]) if best else None


def _order_blocks(blocks: list[tuple[float, float, float, float, str]], page_width: float) -> list[str]:
    if not blocks:
        return []
    gutter = _detect_gutter(blocks, page_width)
    if gutter is None:
        ordered = sorted(blocks, key=lambda block: (round(block[1], 1), block[0]))
        return [block[4] for block in ordered]
    split, right_column_start = gutter

    # Only text that genuinely crosses from the left column into the right column is
    # "spanning". Wide left-column lines end before the right column starts.
    spanning = [
        block for block in blocks if block[0] < split - 5 and block[2] > right_column_start + 5
    ]
    left = [block for block in blocks if block[0] < split - 5 and block[2] <= right_column_start + 5]
    right = [block for block in blocks if block[0] >= split - 5]

    min_left_y = min((block[1] for block in left), default=0.0)
    if any(block[1] > min_left_y + 60 for block in spanning):
        # A wide block partway down the page: ordering is ambiguous, do not guess.
        ordered = sorted(blocks, key=lambda block: (round(block[1], 1), block[0]))
        return [block[4] for block in ordered]

    header = sorted(spanning, key=lambda block: block[1])
    left_sorted = sorted(left, key=lambda block: (round(block[1], 1), block[0]))
    right_sorted = sorted(right, key=lambda block: (round(block[1], 1), block[0]))
    return [block[4] for block in [*header, *left_sorted, *right_sorted]]


def extract_pdf(content: bytes, *, filename: str = "document.pdf") -> PDFExtraction:
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - PyMuPDF is a hard dependency
        import fitz as pymupdf  # type: ignore

    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise CorruptDocumentError(f"Could not open PDF '{filename}': {type(exc).__name__}") from exc

    result = PDFExtraction()
    try:
        if document.needs_pass:
            result.encrypted = True
            raise ParsingError("PDF is password protected and cannot be parsed")
        if document.page_count == 0:
            raise EmptyDocumentError("PDF contains no pages")

        settings = get_config()
        max_pages = int(settings.get("ingestion.max_pages", 20))
        ocr_enabled = bool(settings.get("ingestion.ocr_enabled", False))
        ocr_min_chars = int(settings.get("ingestion.ocr_min_chars_per_page", 25))

        if document.page_count > max_pages:
            result.warnings.append(
                f"PDF has {document.page_count} pages; only the first {max_pages} were processed"
            )

        for index in range(min(document.page_count, max_pages)):
            page = document.load_page(index)
            page_blocks = _block_records(page)
            page_text = "\n".join(_order_blocks(page_blocks, page.rect.width))

            if ocr_enabled and len(page_text.strip()) < ocr_min_chars:
                try:
                    ocr_result = ocr_pdf_page(page)
                    if ocr_result.words:
                        page_text = ocr_result.text
                        result.ocr_used = True
                        result.ocr_confidence = ocr_result.mean_confidence
                        result.warnings.append(
                            f"OCR fallback used on page {index + 1} "
                            f"(mean confidence {ocr_result.mean_confidence:.1f})"
                        )
                    else:
                        result.warnings.append(f"OCR produced no text on page {index + 1}")
                except OCRUnavailableError as exc:
                    result.warnings.append(f"OCR fallback unavailable: {exc.message}")

            result.pages.append(page_text)

        result.page_count = min(document.page_count, max_pages)
        return result
    finally:
        document.close()


def page_count(content: bytes) -> int:
    try:
        import pymupdf

        with pymupdf.open(stream=content, filetype="pdf") as document:
            return document.page_count
    except Exception:  # pragma: no cover - defensive
        return 0

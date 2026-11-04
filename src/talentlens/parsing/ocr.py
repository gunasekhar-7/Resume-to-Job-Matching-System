"""Optional OCR fallback for image-only PDF pages.

OCR is never silent: if the fallback is used, the caller records ``ocr_used`` and
the mean word confidence. If OCR is requested but unavailable, an
``OCRUnavailableError`` is raised so the pipeline can report a partial parse
instead of pretending the document was empty.
"""

from __future__ import annotations

from dataclasses import dataclass

from talentlens.errors import OCRUnavailableError
from talentlens.log import get_logger

logger = get_logger("parsing.ocr")


@dataclass(frozen=True)
class OCRResult:
    text: str
    mean_confidence: float
    words: int


def is_ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_pdf_page(page, *, dpi: int = 200, min_confidence: float = 0.0) -> OCRResult:
    """OCR a PyMuPDF page object. Raises OCRUnavailableError when unsupported."""
    try:
        import pytesseract
        from PIL import Image
    except Exception as exc:
        raise OCRUnavailableError(
            "OCR fallback requires pytesseract and Pillow (see requirements-ocr.txt)"
        ) from exc

    try:
        pixmap = page.get_pixmap(dpi=dpi)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    except Exception as exc:
        raise OCRUnavailableError(f"OCR failed: {type(exc).__name__}") from exc

    words: list[str] = []
    confidences: list[float] = []
    for text, confidence in zip(data.get("text", []), data.get("conf", []), strict=False):
        cleaned = (text or "").strip()
        if not cleaned:
            continue
        try:
            value = float(confidence)
        except (TypeError, ValueError):
            value = -1.0
        if value < min_confidence:
            continue
        words.append(cleaned)
        if value >= 0:
            confidences.append(value)

    mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    logger.info("OCR produced %d words with mean confidence %.1f", len(words), mean_confidence)
    return OCRResult(text=" ".join(words), mean_confidence=round(mean_confidence, 2), words=len(words))

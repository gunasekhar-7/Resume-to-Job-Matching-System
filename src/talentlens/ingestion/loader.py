"""Upload validation and safe file handling.

Design decisions:
* Uploaded bytes stay in memory; they are parsed from ``BytesIO`` and never
  written to a temp path. This removes an entire class of path-traversal and
  temp-file-leak problems.
* The filename is used for display only, never for filesystem access.
* Validation checks extension, size, magic bytes, and (for DOCX) ZIP member
  count / uncompressed size to bound decompression bombs.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from talentlens.config import get_config
from talentlens.errors import (
    EmptyUploadError,
    FileTooLargeError,
    UnsafeUploadError,
    UnsupportedFileTypeError,
)
from talentlens.log import get_logger
from talentlens.schemas import SourceFormat
from talentlens.utils.text import content_sha256

logger = get_logger("ingestion.loader")

_EXTENSION_FORMATS = {
    ".pdf": SourceFormat.PDF,
    ".docx": SourceFormat.DOCX,
    ".txt": SourceFormat.TXT,
}

_MAX_DOCX_MEMBERS = 2000
_MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024


@dataclass(frozen=True)
class UploadedDocument:
    filename: str
    extension: str
    content: bytes
    sha256: str
    size_bytes: int
    source_format: SourceFormat

    def stream(self) -> io.BytesIO:
        return io.BytesIO(self.content)


def safe_filename(filename: str) -> str:
    """Return a display-safe basename with control characters removed."""
    base = Path(filename.replace("\\", "/")).name.strip()
    base = "".join(char for char in base if char.isprintable())
    if not base or base in {".", ".."}:
        raise UnsafeUploadError("Filename is empty or invalid")
    if len(base) > 200:
        base = base[:200]
    return base


def validate_upload(
    filename: str,
    content: bytes,
    *,
    allowed_extensions: list[str] | None = None,
    max_size_mb: int | None = None,
) -> UploadedDocument:
    """Validate an upload and return an immutable descriptor."""
    config = get_config()
    allowed = [ext.lower() for ext in (allowed_extensions or config.get("ingestion.allowed_extensions"))]
    limit_mb = max_size_mb if max_size_mb is not None else config.get("ingestion.max_file_size_mb", 10)
    max_bytes = int(float(limit_mb) * 1024 * 1024)

    if not content:
        raise EmptyUploadError("The uploaded file is empty")

    clean_name = safe_filename(filename)
    extension = Path(clean_name).suffix.lower()
    if extension not in allowed or extension not in _EXTENSION_FORMATS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{extension or 'unknown'}'. Allowed: {', '.join(sorted(allowed))}"
        )
    if len(content) > max_bytes:
        raise FileTooLargeError(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")

    source_format = _EXTENSION_FORMATS[extension]
    _check_magic(extension, content)

    return UploadedDocument(
        filename=clean_name,
        extension=extension,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        source_format=source_format,
    )


def _check_magic(extension: str, content: bytes) -> None:
    if extension == ".pdf":
        if not content.lstrip()[:5] == b"%PDF-":
            raise UnsafeUploadError("File does not have a valid PDF signature")
    elif extension == ".docx":
        if not content.startswith(b"PK"):
            raise UnsafeUploadError("File does not have a valid DOCX (ZIP) signature")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = archive.namelist()
                if "[Content_Types].xml" not in names:
                    raise UnsafeUploadError("DOCX archive is missing [Content_Types].xml")
                if len(names) > _MAX_DOCX_MEMBERS:
                    raise UnsafeUploadError("DOCX archive contains too many entries")
                uncompressed = sum(info.file_size for info in archive.infolist())
                if uncompressed > _MAX_DOCX_UNCOMPRESSED:
                    raise UnsafeUploadError("DOCX archive expands beyond the allowed size")
        except zipfile.BadZipFile as exc:
            raise UnsafeUploadError("DOCX file is not a readable ZIP archive") from exc
    elif extension == ".txt":
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                decoded = content.decode("latin-1")
            except UnicodeDecodeError as exc:
                raise UnsafeUploadError("Text file is not decodable") from exc
        if not decoded.strip():
            raise EmptyUploadError("The uploaded text file is empty")


def read_text_file(upload: UploadedDocument) -> str:
    self_check = hashlib.sha256(upload.content).hexdigest()
    if self_check != upload.sha256:  # pragma: no cover - defensive
        raise UnsafeUploadError("Upload content changed after validation")
    try:
        return upload.content.decode("utf-8")
    except UnicodeDecodeError:
        return upload.content.decode("latin-1")


def load_path(path: str | Path) -> UploadedDocument:
    """Load a trusted local file (sample corpus, CLI ingestion) through the same validation."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    return validate_upload(file_path.name, file_path.read_bytes())


def document_fingerprint(text: str) -> str:
    """Content hash of normalised text, used for duplicate detection."""
    return content_sha256(" ".join(text.lower().split()))

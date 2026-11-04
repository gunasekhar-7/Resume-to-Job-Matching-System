"""Domain errors.

Every error carries a stable ``code`` so the API can map it to a response
without leaking internals, and so tests can assert on behaviour rather than text.
"""

from __future__ import annotations


class TalentLensError(Exception):
    code = "talentlens_error"
    http_status = 500

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(TalentLensError):
    code = "configuration_error"


class IngestionError(TalentLensError):
    code = "ingestion_error"
    http_status = 400


class UnsupportedFileTypeError(IngestionError):
    code = "unsupported_file_type"


class FileTooLargeError(IngestionError):
    code = "file_too_large"
    http_status = 413


class EmptyUploadError(IngestionError):
    code = "empty_upload"


class UnsafeUploadError(IngestionError):
    code = "unsafe_upload"


class ParsingError(TalentLensError):
    code = "parsing_error"
    http_status = 422


class EmptyDocumentError(ParsingError):
    code = "empty_document"


class CorruptDocumentError(ParsingError):
    code = "corrupt_document"


class OCRUnavailableError(ParsingError):
    code = "ocr_unavailable"


class JobValidationError(TalentLensError):
    code = "job_validation_error"
    http_status = 422


class SkillTaxonomyError(TalentLensError):
    code = "skill_taxonomy_error"


class ModelUnavailableError(TalentLensError):
    code = "model_unavailable"
    http_status = 503


class IndexNotBuiltError(TalentLensError):
    code = "index_not_built"
    http_status = 503


class IndexLoadError(TalentLensError):
    code = "index_load_error"
    http_status = 503


class DuplicateJobError(TalentLensError):
    code = "duplicate_job"
    http_status = 409


class RerankerUnavailableError(TalentLensError):
    code = "reranker_unavailable"
    http_status = 503


class NotFoundError(TalentLensError):
    code = "not_found"
    http_status = 404


class EvaluationError(TalentLensError):
    code = "evaluation_error"


class FairnessTestError(TalentLensError):
    code = "fairness_test_error"

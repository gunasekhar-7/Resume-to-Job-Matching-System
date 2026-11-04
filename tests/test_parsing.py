from __future__ import annotations

import pytest

from talentlens.errors import (
    CorruptDocumentError,
    FileTooLargeError,
    UnsafeUploadError,
    UnsupportedFileTypeError,
)
from talentlens.ingestion.loader import validate_upload
from talentlens.parsing.resume_parser import parse_file
from talentlens.parsing.sections import match_heading
from talentlens.schemas import ParsingStatus, SectionName


def test_pdf_parsing_extracts_sections_skills_and_evidence(parsed_r01):
    document = parsed_r01
    assert document.metadata.parsing_status == ParsingStatus.SUCCESS
    assert document.metadata.source_format.value == "pdf"
    assert document.sections["summary"], "summary should be detected"
    assert document.sections["skills"], "skills should be detected"
    assert document.sections["experience"], "experience should be detected"
    assert document.sections["education"], "education should be detected"

    python = [skill for skill in document.skills if skill.canonical == "Python"]
    assert python, "Python should be extracted"
    mention = python[0]
    assert mention.evidence
    assert mention.start_char is not None and mention.end_char is not None
    assert document.full_text[mention.start_char:mention.end_char].lower().startswith("python")
    assert mention.section in {SectionName.SKILLS, SectionName.EXPERIENCE}


def test_section_spans_offsets_are_consistent(parsed_r01):
    for span in parsed_r01.section_spans:
        assert span.start_char is not None and span.end_char is not None
        assert 0 <= span.start_char < span.end_char <= len(parsed_r01.full_text)
        assert parsed_r01.full_text[span.start_char:span.end_char] == span.text


def test_docx_parsing_matches_pdf_sections(resume_dir):
    document = parse_file(resume_dir / "r01_priya_single.docx", resume_id="r01")
    assert document.metadata.source_format.value == "docx"
    assert document.sections["experience"]
    assert {skill.canonical for skill in document.skills} >= {"Python", "PyTorch", "Natural Language Processing"}
    assert document.metadata.parsing_status == ParsingStatus.SUCCESS


def test_column_detection_returns_right_column_start():
    from talentlens.parsing.pdf_parser import _detect_gutter

    def block(x0, y0, x1, text):
        return (x0, y0, x1, y0 + 10, text)

    blocks = [
        *[block(36.8, 30 + index * 20, 180, f"left {index}") for index in range(6)],
        *[block(236.0, 35 + index * 20, 480, f"right {index}") for index in range(5)],
    ]
    gutter = _detect_gutter(blocks, 595.3)
    assert gutter is not None
    split, right_start = gutter
    assert right_start == 236.0
    assert split < right_start


def test_two_column_pdf_keeps_summary_and_experience(parsed_r04):
    document = parsed_r04
    assert document.sections["summary"], "summary must survive two-column reflow"
    assert document.sections["experience"]
    assert "React" in {skill.canonical for skill in document.skills}
    # Reading order must not interleave the columns.
    text = document.full_text
    assert text.index("SKILLS") < text.index("EXPERIENCE")


def test_table_layout_skills_are_extracted(parsed_r09):
    document = parsed_r09
    skills = {skill.canonical for skill in document.skills}
    assert {"Power BI", "SQL", "Tableau"} <= skills
    assert document.sections["experience"]


def test_corrupt_pdf_raises_typed_error(fixture_dir):
    with pytest.raises(CorruptDocumentError):
        parse_file(fixture_dir / "corrupt.pdf")


@pytest.mark.parametrize("name", ["empty.pdf", "scanned.pdf"])
def test_empty_and_scanned_pdfs_fail_visibly(fixture_dir, name):
    document = parse_file(fixture_dir / name)
    assert document.metadata.parsing_status == ParsingStatus.FAILED
    assert document.metadata.low_text_warning is True
    assert any("text" in warning.lower() for warning in document.metadata.warnings)
    assert document.skills == []


def test_unsupported_file_type_is_rejected(fixture_dir):
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload("resume.exe", (fixture_dir / "not_a_resume.exe").read_bytes())


def test_empty_upload_is_rejected():
    from talentlens.errors import EmptyUploadError

    with pytest.raises(EmptyUploadError):
        validate_upload("resume.pdf", b"")


def test_file_size_limit_is_enforced():
    with pytest.raises(FileTooLargeError):
        validate_upload("resume.pdf", b"%PDF-1.4" + b"0" * 5000, max_size_mb=0)


def test_pdf_magic_bytes_are_validated():
    with pytest.raises(UnsafeUploadError):
        validate_upload("resume.pdf", b"not a pdf at all")


def test_pii_is_detected_but_values_are_not_persisted(parsed_r01):
    types = set(parsed_r01.metadata.pii_entity_types)
    assert {"EMAIL", "PHONE"} <= types
    dumped = parsed_r01.metadata.model_dump_json()
    assert "priya.raghavan@example.com" not in dumped
    assert "+91 98765 43210" not in dumped


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("TECHNICAL SKILLS", "skills"),
        ("Work History", "experience"),
        ("Professional Summary", "summary"),
        ("Education & Certifications", "education"),
        ("Selected Projects", "projects"),
        ("PUBLICATIONS", "publications"),
    ],
)
def test_section_heading_variants(heading, expected):
    matched = match_heading(heading)
    assert matched is not None
    assert matched[0] == expected


def test_non_heading_lines_are_not_sections():
    assert match_heading("Built a semantic search service with Python and FAISS") is None
    assert match_heading("Random Heading") is None
    assert match_heading("Senior Machine Learning Engineer | Northwind Analytics | 2021") is None


def test_resume_id_override_is_respected(resume_dir):
    document = parse_file(resume_dir / "r02_daniel_single.pdf", resume_id="custom_resume_id")
    assert document.resume_id == "custom_resume_id"

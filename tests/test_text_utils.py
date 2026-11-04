from __future__ import annotations

import pytest

from talentlens.utils.text import (
    clean_text,
    content_sha256,
    is_probably_heading,
    normalize_for_match,
    normalize_unicode,
    remove_repeated_page_lines,
    sentence_spans,
    split_sentences,
    strip_page_artifacts,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("\ufb01le \u2013 test", "file - test"),
        ("Caf\u00e9\u200b r\u00e9sum\u00e9", "Caf\u00e9 r\u00e9sum\u00e9"),
        ("a\u00a0b", "a b"),
    ],
)
def test_normalize_unicode(raw, expected):
    assert normalize_unicode(raw) == expected


def test_clean_text_normalises_inline_bullets():
    assert clean_text("Python \u2022 SQL \u2022 AWS") == "Python, SQL, AWS"


def test_clean_text_normalises_leading_bullets():
    assert clean_text("\u2022 Built a pipeline\n\u2022 Deployed it") == "- Built a pipeline\n- Deployed it"


def test_clean_text_collapses_whitespace_and_blank_lines():
    assert clean_text("  a   b \n\n\n\n c  ") == "a b\n\nc"


def test_strip_page_artifacts_removes_page_numbers_and_running_footers():
    text = "Body line\nPage 2 of 4\n17\nConfidential - sample | Page 2\nMore body"
    cleaned = strip_page_artifacts(text)
    assert cleaned.splitlines() == ["Body line", "More body"]


def test_remove_repeated_page_lines_drops_running_header():
    pages = ["ACME Corp\nAlice\nExperience A", "ACME Corp\nAlice\nExperience B"]
    cleaned = remove_repeated_page_lines(pages)
    assert all("ACME Corp" not in page for page in cleaned)
    assert "Experience A" in cleaned[0] and "Experience B" in cleaned[1]


def test_split_sentences_keeps_abbreviations_together():
    sentences = split_sentences("Use e.g. AWS and GCP. Then deploy the model.")
    assert len(sentences) == 2
    assert sentences[0].startswith("Use e.g. AWS")


def test_split_sentences_splits_bullet_lists():
    sentences = split_sentences("- Python\n- SQL\n- Docker")
    assert sentences == ["Python", "SQL", "Docker"]


def test_sentence_spans_offsets_point_at_sentence():
    text = "Built a pipeline. Reduced latency."
    for sentence, start, end in sentence_spans(text):
        assert text[start:end] == sentence


def test_normalize_for_match_preserves_technology_symbols():
    assert normalize_for_match("C++") == "c++"
    assert normalize_for_match("Scikit-Learn") == "scikit learn"
    assert normalize_for_match("Node.js") == "node.js"


def test_content_hash_is_deterministic_and_order_sensitive():
    assert content_sha256("a", "b") == content_sha256("a", "b")
    assert content_sha256("a", "b") != content_sha256("b", "a")


def test_is_probably_heading():
    assert is_probably_heading("TECHNICAL SKILLS")
    assert is_probably_heading("Professional Experience")
    assert not is_probably_heading("Built a pipeline with Python and deployed it to production.")
    assert not is_probably_heading("")

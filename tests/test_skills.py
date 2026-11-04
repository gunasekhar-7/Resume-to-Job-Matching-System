from __future__ import annotations

from talentlens.schemas import SectionName, SectionSpan
from talentlens.skills.extractor import extract_from_phrases, extract_skills


def test_taxonomy_loads_and_is_substantial(taxonomy):
    assert len(taxonomy) > 180
    assert taxonomy.get("Python") is not None
    assert taxonomy.category_of("PyTorch") == "deep_learning"
    assert taxonomy.label_for_category("nlp") == "Natural Language Processing"


def test_alias_normalisation(taxonomy):
    assert taxonomy.resolve("sklearn").canonical == "Scikit-Learn"
    assert taxonomy.resolve("JS").canonical == "JavaScript"
    assert taxonomy.resolve("stats libraries") is None


def test_alias_normalisation_is_case_insensitive_for_normal_skills(taxonomy):
    assert taxonomy.resolve("python").canonical == "Python"
    assert taxonomy.resolve("MACHINE LEARNING").canonical == "Machine Learning"


def test_case_sensitive_skills_do_not_match_prose(taxonomy):
    prose = "We go to market quickly and led R and D initiatives."
    canonicals = {mention.canonical for mention in extract_skills(prose, taxonomy=taxonomy)}
    assert "Go" not in canonicals
    assert "R" not in canonicals


def test_case_sensitive_skills_match_in_skill_lists(taxonomy):
    text = "SKILLS\nGo, R, Python\n"
    spans = [SectionSpan(section=SectionName.SKILLS, text="Go, R, Python", start_char=7, end_char=20, order=0)]
    canonicals = {m.canonical for m in extract_skills(text, taxonomy=taxonomy, section_spans=spans)}
    assert {"Go", "R", "Python"} <= canonicals


def test_aliases_are_captured_with_original_phrase(taxonomy):
    mentions = extract_from_phrases(["sklearn", "scikit learn"], taxonomy=taxonomy)
    assert mentions
    assert {mention.canonical for mention in mentions} == {"Scikit-Learn"}
    assert mentions[0].original_text.lower().replace("-", " ") in {"sklearn", "scikit learn"}


def test_duplicate_mentions_do_not_duplicate_canonical_skills(taxonomy):
    text = "Machine learning (ML) experience required."
    mentions = extract_skills(text, taxonomy=taxonomy)
    assert {mention.canonical for mention in mentions} == {"Machine Learning"}


def test_section_attribution_and_evidence(taxonomy):
    text = "SKILLS\nPython, SQL\n\nEXPERIENCE\nBuilt Python services at Acme."
    skills_start = text.index("Python")
    exp_start = text.index("Built")
    spans = [
        SectionSpan(section=SectionName.SKILLS, text="Python, SQL", start_char=skills_start, end_char=skills_start + 11, order=0),
        SectionSpan(
            section=SectionName.EXPERIENCE,
            text="Built Python services at Acme.",
            start_char=exp_start,
            end_char=len(text),
            order=1,
        ),
    ]
    mentions = [m for m in extract_skills(text, taxonomy=taxonomy, section_spans=spans) if m.canonical == "Python"]
    assert len(mentions) == 2
    sections = {mention.section for mention in mentions}
    assert sections == {SectionName.SKILLS, SectionName.EXPERIENCE}
    experience_mention = next(m for m in mentions if m.section == SectionName.EXPERIENCE)
    assert "Built Python services" in experience_mention.evidence


def test_no_false_positive_inside_words(taxonomy):
    mentions = extract_skills("The Roster of JavaScripters met in Jacksonville.", taxonomy=taxonomy)
    assert {mention.canonical for mention in mentions} == set()


def test_related_skill_credit_is_partial_and_conservative(taxonomy):
    assert taxonomy.related_credit("PyTorch", "PyTorch") == 1.0
    assert taxonomy.related_credit("PyTorch", "TensorFlow") == 0.5
    assert taxonomy.related_credit("Python", "PyTorch") == 0.0
    assert taxonomy.related_credit("Python", "Java") == 0.0


def test_skill_extraction_on_job_requirement_phrase(taxonomy):
    mentions = extract_from_phrases(["Strong Python programming"], taxonomy=taxonomy)
    assert {mention.canonical for mention in mentions} == {"Python"}


def test_empty_text_returns_no_mentions(taxonomy):
    assert extract_skills("", taxonomy=taxonomy) == []
    assert extract_skills("   \n\n", taxonomy=taxonomy) == []

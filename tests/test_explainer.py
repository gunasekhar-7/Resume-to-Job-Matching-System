from __future__ import annotations

from factories import job_with, mention, resume_with
from fakes import FakeEmbedder
from talentlens.matching.explainer import EvidenceBuilder, extract_resume_sentences
from talentlens.matching.skill_gaps import build_skill_gap_report
from talentlens.schemas import SectionName, SkillMention


def test_sentence_extraction_excludes_header_and_education_and_deduplicates():
    document = resume_with(
        [],
        experience=[
            "Built Python machine learning services for search.",
            "Built Python machine learning services for search.",
        ],
        education=["BSc Computer Science at Example University."],
    )
    document = document.model_copy(
        update={
            "full_text": (
                "Header\nBuilt Python machine learning services for search.\n"
                "BSc Computer Science at Example University."
            ),
            "sections": {
                **document.sections,
                "header": ["Priya Example priya@example.com"],
            },
        }
    )
    sentences = extract_resume_sentences(document)
    assert len(sentences) == 1
    assert sentences[0].section == SectionName.EXPERIENCE
    assert sentences[0].start_char == document.full_text.find(sentences[0].text)


def test_evidence_selects_sentences_above_threshold():
    document = resume_with(
        [],
        experience=["Built Python machine learning services for NLP search."],
        projects=["Designed a Kubernetes deployment pipeline."],
    )
    job = job_with(["Python", "Natural Language Processing"])
    builder = EvidenceBuilder(document, FakeEmbedder(), min_similarity=0.05, max_items=2)
    # Use the same deterministic embedding space for the job requirement.
    requirement = FakeEmbedder().encode_one(job.requirements_text())
    evidence = builder.for_requirement(requirement)
    assert evidence
    assert evidence[0].section == SectionName.EXPERIENCE
    assert "Python machine learning" in evidence[0].sentence
    assert 0.0 <= evidence[0].similarity <= 1.0


def test_evidence_is_not_fabricated_below_threshold():
    document = resume_with([], experience=["Built Python machine learning services."])
    builder = EvidenceBuilder(document, FakeEmbedder(), min_similarity=0.99)
    job = job_with(["Python", "Natural Language Processing"])
    assert builder.for_requirement(FakeEmbedder().encode_one(job.requirements_text())) == []


def test_skill_gap_report_separates_required_and_preferred(taxonomy):
    document = resume_with([mention("Python")])
    jobs = [
        job_with(["Python", "Kubernetes"], ["AWS"], job_id="job_a"),
        job_with(["Python"], ["Docker"], job_id="job_b"),
    ]
    report = build_skill_gap_report(document, jobs, taxonomy=taxonomy)
    assert report.jobs_analyzed == 2
    assert len(report.per_job) == 2
    assert report.per_job[0].required_missing[0].canonical == "Kubernetes"
    assert report.per_job[0].preferred_missing[0].canonical == "AWS"
    assert report.frequently_missing_required[0].canonical == "Kubernetes"
    assert report.frequently_missing_required[0].job_count == 1
    assert report.required_coverage_avg == 0.75
    assert any("does not prove" in note for note in report.notes)


def test_ambiguous_extraction_is_reported(taxonomy):
    ambiguous = SkillMention(
        original_text="R",
        canonical="R",
        category="programming_languages",
        section=SectionName.SKILLS,
        evidence="R",
        match_status="ambiguous",
    )
    report = build_skill_gap_report(
        resume_with([ambiguous]), [job_with(["Python"], job_id="job_a")], taxonomy=taxonomy
    )
    assert report.ambiguous_skills
    assert report.ambiguous_skills[0].status.value == "ambiguous"


def test_empty_job_list_is_explicit(taxonomy):
    report = build_skill_gap_report(resume_with([]), [], taxonomy=taxonomy)
    assert report.jobs_analyzed == 0
    assert report.required_coverage_avg == 0.0
    assert report.per_job == []

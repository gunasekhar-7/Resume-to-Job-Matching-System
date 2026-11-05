"""Matching subpackage."""

from talentlens.matching.experience_matcher import align_experience, extract_experience
from talentlens.matching.explainer import EvidenceBuilder, extract_resume_sentences
from talentlens.matching.hybrid_scorer import HybridScorer, ScoringWeights
from talentlens.matching.pipeline import MatchFilters, MatchingPipeline
from talentlens.matching.skill_gaps import build_skill_gap_report
from talentlens.matching.skill_matcher import SkillMatchResult, match_skills

__all__ = [
    "MatchingPipeline",
    "MatchFilters",
    "HybridScorer",
    "ScoringWeights",
    "match_skills",
    "SkillMatchResult",
    "align_experience",
    "extract_experience",
    "EvidenceBuilder",
    "extract_resume_sentences",
    "build_skill_gap_report",
]

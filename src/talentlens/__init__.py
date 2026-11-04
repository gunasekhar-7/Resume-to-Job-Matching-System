"""TalentLens package.

Explainable resume-to-job matching. The package is deliberately layered:

    ingestion -> parsing -> skills -> jobs -> embeddings -> retrieval -> matching
                                     |
                                  evaluation, storage, monitoring, explainability

Phase 1 code (ingestion/parsing/skills/jobs) must not import Phase 2+ modules.
"""

__version__ = "1.0.0"

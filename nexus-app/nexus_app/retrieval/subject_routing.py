"""Data-backed subject disambiguation for scenario routing.

Scenario selection must distinguish the business entity being queried (a job
role versus a major) from the requested representation (graph, skills, etc.).
This module only overrides an LLM route when a known structured entity can be
resolved unambiguously from the query.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from sqlalchemy import literal, select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.retrieval.intent_v2 import IntentV2Result


@dataclass(frozen=True)
class QuerySubject:
    kind: str  # job | major | ambiguous | unknown
    value: str | None = None


def resolve_query_subject(session: Session, query: str) -> QuerySubject:
    """Resolve the longest unambiguous known business entity in ``query``."""
    query_key = _key(query)
    if len(query_key) < 2:
        return QuerySubject("unknown")
    jobs = _matches(query_key, _job_titles(session, query))
    majors = _matches(query_key, _major_names(session, query))
    best_job = jobs[0] if jobs else None
    best_major = majors[0] if majors else None
    if best_job and best_major:
        if len(_key(best_job)) == len(_key(best_major)):
            return QuerySubject("ambiguous")
        return QuerySubject("job" if len(_key(best_job)) > len(_key(best_major)) else "major",
                            best_job if len(_key(best_job)) > len(_key(best_major)) else best_major)
    if best_job:
        return QuerySubject("job", best_job)
    if best_major:
        return QuerySubject("major", best_major)
    return QuerySubject("unknown")


def apply_subject_route_guard(
    intent: IntentV2Result, subject: QuerySubject,
) -> IntentV2Result:
    """Prevent a known job entity from entering the major-only scenario."""
    if subject.kind == "job" and intent.intent == "scenario_3":
        return replace(
            intent,
            intent="scenario_2",
            warnings=(*intent.warnings, "subject_route_override:job_to_scenario_2"),
        )
    return intent


def _job_titles(session: Session, query: str) -> list[str]:
    return list(session.scalars(
        select(models.JobDemandRecord.job_title)
        .where(literal(query).contains(models.JobDemandRecord.job_title))
        .distinct()
        .limit(16)
    ))


def _major_names(session: Session, query: str) -> list[str]:
    values: set[str] = set()
    for model in (
        models.OccupationalAbilityAnalysis,
        models.MajorDistributionRecord,
        models.CapabilityGraphStagingBuild,
    ):
        values.update(
            value for value in session.scalars(
                select(model.major_name)
                .where(literal(query).contains(model.major_name))
                .distinct()
                .limit(16)
            ).all()
            if isinstance(value, str) and value.strip()
        )
    return sorted(values)


def _matches(query_key: str, candidates: list[str | None]) -> list[str]:
    return sorted(
        {
            candidate.strip() for candidate in candidates
            if isinstance(candidate, str) and len(_key(candidate)) >= 2
            and _key(candidate) in query_key
        },
        key=lambda value: (-len(_key(value)), value),
    )


def _key(value: str) -> str:
    return re.sub(r"[\s，,。.．:：、]", "", value).lower()

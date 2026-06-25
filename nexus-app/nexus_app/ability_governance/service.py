"""Orchestrate the 10 PGSD governance rules over an ability_analysis tree.

`govern_ability_analysis` loads everything one of the rules needs from the
session, builds the typed view objects, runs each rule in
`validators.RULES_IN_ORDER`, and aggregates the findings.

Failure modes (never raise — return a skipped result):
- analysis row was deleted between writer success and this call
- the analysis's profile_id no longer points at a real profile row
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ability_governance import validators as V
from nexus_app.ability_governance.schemas import (
    Finding,
    GovernanceFindings,
)

logger = logging.getLogger(__name__)


def govern_ability_analysis(
    session: Session,
    analysis: models.OccupationalAbilityAnalysis,
    *,
    overview_work_content_codes: set[str] | None = None,
) -> GovernanceFindings:
    """Run all 10 rules and return aggregated findings.

    `overview_work_content_codes` is supplied by the worker stage from
    `payload.record_body`'s overview matrix when available (e.g. sample
    2's "典型工作任务和工作内容分析表" sheet). Passing None disables the
    cross-sheet rule cleanly — rule 6 short-circuits without flagging.
    """
    profile = session.get(models.AbilityAnalysisProfile, analysis.profile_id)
    if profile is None:
        logger.warning(
            "ability_governance: profile %s missing for analysis %s; skipping",
            analysis.profile_id, analysis.id,
        )
        return GovernanceFindings(
            analysis_id=analysis.id,
            profile_id=analysis.profile_id or "",
            skipped=True,
            skipped_reason="profile_not_found",
        )

    view = _build_view(
        session, analysis, profile,
        overview_work_content_codes=overview_work_content_codes,
    )

    findings: list[Finding] = []
    for rule in V.RULES_IN_ORDER:
        findings.extend(rule(view))

    return GovernanceFindings(
        analysis_id=analysis.id,
        profile_id=profile.id,
        findings=findings,
    )


def _build_view(
    session: Session,
    analysis: models.OccupationalAbilityAnalysis,
    profile: models.AbilityAnalysisProfile,
    *,
    overview_work_content_codes: set[str] | None,
) -> V.AnalysisView:
    tasks_rows = list(session.scalars(
        select(models.OccupationalWorkTask).where(
            models.OccupationalWorkTask.analysis_id == analysis.id
        )
    ))
    wc_rows = list(session.scalars(
        select(models.OccupationalWorkContent).where(
            models.OccupationalWorkContent.analysis_id == analysis.id
        )
    ))
    ability_rows = list(session.scalars(
        select(models.OccupationalAbilityItem).where(
            models.OccupationalAbilityItem.analysis_id == analysis.id
        )
    ))

    wc_by_task: dict[str, list[V.WorkContentView]] = {}
    for wc in wc_rows:
        wc_by_task.setdefault(wc.task_id, []).append(
            V.WorkContentView(id=wc.id, content_code=wc.content_code)
        )
    tasks = [
        V.TaskView(
            id=t.id,
            task_code=t.task_code,
            work_contents=wc_by_task.get(t.id, []),
        )
        for t in tasks_rows
    ]
    abilities = [
        V.AbilityItemView(
            id=a.id,
            ability_code=a.ability_code,
            ability_major_category_code=a.ability_major_category_code or "",
            ability_content=a.ability_content or "",
            task_id=a.task_id,
            work_content_id=a.work_content_id,
        )
        for a in ability_rows
    ]

    source_dataset_declared = analysis.source_job_demand_dataset_id is not None
    source_dataset_linked = False
    if source_dataset_declared:
        source_dataset_linked = session.scalar(
            select(models.AbilityAnalysisSourceDataset.id).where(
                models.AbilityAnalysisSourceDataset.analysis_id == analysis.id
            )
        ) is not None

    return V.AnalysisView(
        id=analysis.id,
        analysis_model=analysis.analysis_model,
        profile_model_code=profile.model_code,
        profile_category_schema=list(profile.category_schema or []),
        profile_code_pattern=dict(profile.code_pattern or {}),
        tasks=tasks,
        abilities=abilities,
        source_dataset_declared=source_dataset_declared,
        source_dataset_linked=source_dataset_linked,
        overview_work_content_codes=overview_work_content_codes,
    )


__all__ = ["govern_ability_analysis"]

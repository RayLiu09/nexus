"""Persistence helpers for Task Outline profiles and nodes."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.task_outline.schemas import (
    TaskOutlineNodeCreate,
    TaskOutlineProfileCreate,
)


def get_profile_by_ref(
    session: Session,
    *,
    normalized_ref_id: str,
    asset_profile: str = "course_textbook",
) -> models.TaskOutlineProfile | None:
    return session.scalar(
        select(models.TaskOutlineProfile).where(
            models.TaskOutlineProfile.normalized_ref_id == normalized_ref_id,
            models.TaskOutlineProfile.asset_profile == asset_profile,
        )
    )


def upsert_profile(
    session: Session,
    payload: TaskOutlineProfileCreate,
) -> models.TaskOutlineProfile:
    """Create or update the effective profile for a normalized ref/profile pair."""
    existing = get_profile_by_ref(
        session,
        normalized_ref_id=payload.normalized_ref_id,
        asset_profile=payload.asset_profile,
    )
    values = _profile_values(payload)
    if existing is None:
        profile = models.TaskOutlineProfile(**values)
        session.add(profile)
        session.flush()
        return profile

    for key, value in values.items():
        if key not in {"normalized_ref_id", "asset_profile"}:
            setattr(existing, key, value)
    session.flush()
    return existing


def replace_nodes(
    session: Session,
    *,
    profile: models.TaskOutlineProfile,
    nodes: list[TaskOutlineNodeCreate],
) -> list[models.TaskOutlineNode]:
    """Replace all nodes for a profile in one idempotent operation."""
    session.execute(
        delete(models.TaskOutlineNode).where(
            models.TaskOutlineNode.profile_id == profile.id
        )
    )
    session.flush()

    persisted: list[models.TaskOutlineNode] = []
    for payload in nodes:
        node = models.TaskOutlineNode(
            **_node_values(payload, profile=profile),
        )
        session.add(node)
        persisted.append(node)
    session.flush()
    return persisted


def list_nodes(
    session: Session,
    *,
    profile_id: str | None = None,
    normalized_ref_id: str | None = None,
) -> list[models.TaskOutlineNode]:
    """List nodes in deterministic tree display order."""
    stmt = select(models.TaskOutlineNode)
    if profile_id is not None:
        stmt = stmt.where(models.TaskOutlineNode.profile_id == profile_id)
    if normalized_ref_id is not None:
        stmt = stmt.where(models.TaskOutlineNode.normalized_ref_id == normalized_ref_id)
    stmt = stmt.order_by(
        models.TaskOutlineNode.depth.asc(),
        models.TaskOutlineNode.order_no.asc(),
        models.TaskOutlineNode.id.asc(),
    )
    return list(session.scalars(stmt))


def _profile_values(payload: TaskOutlineProfileCreate) -> dict:
    return {
        "normalized_ref_id": payload.normalized_ref_id,
        "asset_version_id": payload.asset_version_id,
        "asset_profile": payload.asset_profile,
        "title": payload.title,
        "textbook_subtype": payload.textbook_subtype,
        "task_profile": payload.task_profile,
        "subtype_confidence": payload.subtype_confidence,
        "processing_profile": payload.processing_profile,
        "evidence_graph_admission": payload.evidence_graph_admission,
        "source_block_ids": list(payload.source_block_ids),
        "quality": dict(payload.quality),
        "profile_metadata": dict(payload.metadata),
    }


def _node_values(
    payload: TaskOutlineNodeCreate,
    *,
    profile: models.TaskOutlineProfile,
) -> dict:
    values = {
        "normalized_ref_id": payload.normalized_ref_id or profile.normalized_ref_id,
        "profile_id": profile.id,
        "parent_id": payload.parent_id,
        "node_type": payload.node_type,
        "section_type": payload.section_type,
        "title": payload.title,
        "content": payload.content,
        "summary": payload.summary,
        "order_no": payload.order_no,
        "depth": payload.depth,
        "source_block_ids": list(payload.source_block_ids),
        "locator": payload.locator,
        "node_metadata": dict(payload.metadata),
    }
    if payload.id:
        values["id"] = payload.id
    return values


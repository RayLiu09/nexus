"""Outline node → ``tag_asset_index`` projection helper (PR-7).

Thin wrapper around :func:`project_record_to_tag_rows` +
:func:`persist_tag_rows` for the two outline node tables
(``knowledge_outline_node`` and ``task_outline_node``).  Both project
``title → topic`` per the v1.3 ``PROJECTION_WHITELIST_V1_3``; the
``metadata_projections`` extension (``node_metadata.keywords → topic``)
is declared in the whitelist but its engine implementation is deferred
to PR-8 (governance source projection) — see the projection_config
docstring.

Callers use this module from the outline build/rebuild path.  Two hooks
land in production:

* :func:`nexus_app.knowledge_outline.service.build_and_persist_outline`
  after ``_replace_outline_rows``.  Consumes ``OutlineNodeSpec`` (which
  carries ``.id`` and ``.title`` — the DB rows have been added but not
  yet reloaded).
* :func:`nexus_app.task_outline.orchestrator.rebuild_task_outline_for_ref`
  after ``replace_nodes``.  Consumes the returned ``TaskOutlineNode``
  models directly.

Idempotency contract (I-10): every call routes through ``persist_tag_rows``
which delete-then-inserts per ``(target_type, target_id, source)``
triple, so re-running the outline build reliably yields the same set
of tag rows.  Empty outline builds (no nodes) are a no-op — no wipe is
needed because a missing node id has no prior projection to remove.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from sqlalchemy import delete

from nexus_app import models
from nexus_app.ai_governance.tag_projection import (
    persist_tag_rows,
    project_record_to_tag_rows,
)
from nexus_app.enums import TagAssetIndexSource, TagAssetIndexTargetType

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session


__all__ = [
    "OutlineProjectionResult",
    "project_and_persist_outline_nodes",
]


# ---------------------------------------------------------------------------
# Node protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _OutlineTagInput:
    """Minimal shape the projection needs.

    Kept as a dataclass so callers can pass either an SQLAlchemy model
    (``TaskOutlineNode``) or a build-time spec (``OutlineNodeSpec``) via
    a small adapter without wrapping the whole node.
    """

    id: str
    title: str | None


def _as_tag_input(node: object) -> _OutlineTagInput | None:
    """Extract ``(id, title)`` from an outline node.

    Silently drops nodes with a missing id — every outline node created
    via the build path assigns an id, so this can only happen if a
    caller hand-constructed something invalid.
    """
    node_id = getattr(node, "id", None)
    if not node_id:
        return None
    title = getattr(node, "title", None)
    return _OutlineTagInput(id=str(node_id), title=title)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutlineProjectionResult:
    """Summary emitted by :func:`project_and_persist_outline_nodes`.

    ``node_count`` is the number of outline nodes examined (regardless
    of whether they produced any tag row); ``rows_persisted`` sums the
    ``persist_tag_rows`` return codes so audits / metrics can report
    how much taxonomy actually landed in ``tag_asset_index``.
    """

    node_count: int
    rows_persisted: int
    empty_title_count: int


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def project_and_persist_outline_nodes(
    session: "Session",
    *,
    table_name: str,
    nodes: Iterable[object],
    asset_version_id: str,
    trace_id: str | None = None,
    source: TagAssetIndexSource = TagAssetIndexSource.OUTLINE_PROJECTION,
    wipe_orphans_for_asset_version: bool = True,
) -> OutlineProjectionResult:
    """Project every outline node's projection-eligible fields to tag
    rows and persist them idempotently.

    Parameters
    ----------
    session:
        The caller's active SQLAlchemy Session.  Not committed — the
        caller owns the transaction boundary (typically the outline
        build/rebuild service).
    table_name:
        ``"knowledge_outline_node"`` or ``"task_outline_node"``.  Any
        other value raises via ``project_record_to_tag_rows`` (the
        projection engine's own contract).
    nodes:
        Iterable of outline nodes.  Each must expose ``.id`` and
        ``.title`` — either an SQLAlchemy model or a build-time spec.
    asset_version_id:
        The parent ``asset_version.id``.  Every outline row belongs to
        exactly one asset version, so we take it once at the call site
        rather than looking it up per-node.
    wipe_orphans_for_asset_version:
        When True (default), delete every prior OUTLINE_PROJECTION row
        for this ``asset_version_id`` before inserting the current
        payload.  Outline rebuilds assign fresh node UUIDs, so keying
        idempotency only on the per-node ``(target_type, target_id,
        source)`` triple leaves orphans behind.  Callers that manage
        cleanup themselves (e.g. a governance-side projection updating
        one node in isolation) can set this to False.
    """
    if table_name not in {"knowledge_outline_node", "task_outline_node"}:
        raise ValueError(
            f"outline projection expects knowledge_outline_node or "
            f"task_outline_node table_name; got {table_name!r}"
        )

    target_type = (
        TagAssetIndexTargetType.OUTLINE_NODE  # both tables map here
    )

    if wipe_orphans_for_asset_version:
        # Delete-then-insert at the version level so a rebuild that
        # reassigns node UUIDs doesn't leave stale rows anchored to
        # deleted nodes.
        session.execute(
            delete(models.TagAssetIndex).where(
                models.TagAssetIndex.target_type == target_type,
                models.TagAssetIndex.asset_version_id == asset_version_id,
                models.TagAssetIndex.source == source,
            )
        )
        session.flush()

    node_count = 0
    empty_title_count = 0
    rows_persisted = 0

    for node in nodes:
        tag_input = _as_tag_input(node)
        if tag_input is None:
            continue
        node_count += 1
        if not (tag_input.title or "").strip():
            empty_title_count += 1
            # Still call persist_tag_rows with an empty payload so a
            # prior projection for this node (if any) is wiped.  I-10:
            # the projection contract is "the state after this call
            # matches the current record", not "add new rows".
            rows_persisted += persist_tag_rows(
                session, [],
                target_type=target_type,
                target_id=tag_input.id,
                source=source,
            )
            continue

        payloads = project_record_to_tag_rows(
            table_name=table_name,
            record={"title": tag_input.title},
            target_id=tag_input.id,
            asset_version_id=asset_version_id,
            source=source,
            target_type=target_type,
            trace_id=trace_id,
        )
        rows_persisted += persist_tag_rows(
            session, payloads,
            target_type=target_type,
            target_id=tag_input.id,
            source=source,
        )

    return OutlineProjectionResult(
        node_count=node_count,
        rows_persisted=rows_persisted,
        empty_title_count=empty_title_count,
    )

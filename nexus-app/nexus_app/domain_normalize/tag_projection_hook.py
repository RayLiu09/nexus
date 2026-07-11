"""Pipeline B write-side tag projection helper — PR-6b.

PR-6 shipped the projection engine (``ai_governance/tag_projection.py``)
plus the ``PROJECTION_WHITELIST_V1_3`` config for every structured
target table (``job_demand_record`` / ``job_demand_requirement_item`` /
``major_distribution_record`` / ``occupational_ability_item``).  What
it *didn't* ship was the plumbing so those writers automatically
persist ``tag_asset_index`` rows after a successful write.

PR-6b closes that gap with the same "outline projection hook" pattern
PR-7 landed for ``KnowledgeOutlineNode``: a shared best-effort
orchestrator, one call site per writer, projection failures never
abort the write.  Summary is embedded in the writer's existing audit
event payload so operators see per-write projection counts without a
new event type.

Design contract:

* **Best-effort** — any exception during projection is caught and
  logged; the writer's own commit still succeeds and its audit fires.
* **Idempotent** — reuses ``persist_tag_rows``'s
  delete-then-insert-per-``(target_type, target_id, source)`` triple,
  so re-running the writer (or backfilling later) is safe.
* **Whitelist-driven** — table_name → target_type mapping comes from
  the projection engine's own ``_TABLE_TO_TARGET_TYPE`` (via
  ``project_record_to_tag_rows``), keeping this hook thin.
* **Source is FIELD_PROJECTION** — this is the write-side pipeline
  hook; governance_tag / expert_manual sources are separate paths.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping

from nexus_app.ai_governance.tag_projection import (
    persist_tag_rows,
    project_record_to_tag_rows,
)
from nexus_app.enums import TagAssetIndexSource, TagAssetIndexTargetType

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


__all__ = [
    "TagProjectionSummary",
    "project_writer_records",
]


# Table name → the tag_asset_index target_type that its records land on.
# Kept in-module rather than reaching into ``tag_projection._TABLE_TO_TARGET_TYPE``
# so a rename downstream is caught here at import time.
_WRITER_TABLE_TARGET_TYPES: Mapping[str, TagAssetIndexTargetType] = {
    "job_demand_record": TagAssetIndexTargetType.JOB_DEMAND_RECORD,
    "job_demand_requirement_item": TagAssetIndexTargetType.JOB_DEMAND_REQUIREMENT_ITEM,
    "major_distribution_record": TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
    "occupational_ability_item": TagAssetIndexTargetType.OCCUPATIONAL_ABILITY_ITEM,
}


@dataclass(frozen=True)
class TagProjectionSummary:
    """Emitted per hook invocation and folded into the writer's audit.

    ``rows_persisted`` — count of tag_asset_index rows created (post
    persist_tag_rows).  ``skipped_records`` — records dropped before
    projection (invalid shape, missing target_id).  ``error`` is a
    stringified exception when best-effort catches something; None on
    the happy path.
    """

    table_name: str
    record_count: int
    rows_persisted: int
    skipped_records: int
    error: str | None = None

    def to_audit_payload(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "record_count": self.record_count,
            "rows_persisted": self.rows_persisted,
            "skipped_records": self.skipped_records,
            "error": self.error,
        }


def project_writer_records(
    session: "Session",
    *,
    table_name: str,
    records: Iterable[Any],
    asset_version_id: str,
    record_to_dict: Callable[[Any], dict[str, Any] | None],
    target_id_getter: Callable[[Any], str | None] = lambda r: getattr(r, "id", None),
    trace_id: str | None = None,
    source: TagAssetIndexSource = TagAssetIndexSource.FIELD_PROJECTION,
) -> TagProjectionSummary:
    """Project every writer-persisted record onto ``tag_asset_index``.

    Parameters
    ----------
    session:
        Caller's active SQLAlchemy Session (not committed here — the
        writer owns the transaction boundary).
    table_name:
        The writer's SQLAlchemy ``__tablename__``.  Must be in
        ``_WRITER_TABLE_TARGET_TYPES`` and in
        ``PROJECTION_WHITELIST_V1_3``.  Unknown names produce an
        ``error`` summary and zero rows persisted.
    records:
        The freshly-inserted ORM rows (or spec dataclasses).
    asset_version_id:
        The parent asset_version — same for every record in this batch.
        Cheaper to pass once than lookup per record.
    record_to_dict:
        Adapter that turns one ORM row into the flat dict the
        projection engine expects (mirror of the whitelist's field
        names).  Returning ``None`` skips the record.
    target_id_getter:
        Extracts the ``target_id`` from an ORM row.  Default reads
        ``.id``; requirement-item / analysis-item writers may pass a
        callable that reaches into an id column with a different name.

    Best-effort: any exception is captured on the summary; the writer
    is unaffected.  Errors during projection of one record don't stop
    the others in the same batch — each record projection is wrapped
    independently.
    """
    target_type = _WRITER_TABLE_TARGET_TYPES.get(table_name)
    if target_type is None:
        message = (
            f"unsupported writer table {table_name!r}; "
            f"known={sorted(_WRITER_TABLE_TARGET_TYPES)}"
        )
        logger.warning("tag_projection_hook %s", message)
        return TagProjectionSummary(
            table_name=table_name,
            record_count=0,
            rows_persisted=0,
            skipped_records=0,
            error=message,
        )

    records_list = list(records)
    record_count = len(records_list)
    skipped = 0
    rows_persisted = 0
    per_record_errors: list[str] = []

    for record in records_list:
        target_id = target_id_getter(record)
        if not target_id or not isinstance(target_id, str):
            skipped += 1
            continue
        try:
            record_dict = record_to_dict(record)
        except Exception as exc:  # noqa: BLE001 - best-effort per row
            per_record_errors.append(f"{type(exc).__name__}:{exc}")
            skipped += 1
            continue
        if record_dict is None:
            skipped += 1
            continue
        try:
            payloads = project_record_to_tag_rows(
                table_name=table_name,
                record=record_dict,
                target_id=target_id,
                asset_version_id=asset_version_id,
                source=source,
                target_type=target_type,
                trace_id=trace_id,
            )
            rows_persisted += persist_tag_rows(
                session, payloads,
                target_type=target_type,
                target_id=target_id,
                source=source,
            )
        except Exception as exc:  # noqa: BLE001
            per_record_errors.append(f"{type(exc).__name__}:{exc}")
            skipped += 1
            continue

    # Aggregate per-record errors into a single string on the summary so
    # the audit payload stays flat (per PR-7 outline pattern).
    error = (
        "; ".join(per_record_errors[:5])
        if per_record_errors
        else None
    )
    if error is not None:
        logger.warning(
            "tag_projection_hook table=%s errors=%d first=%s",
            table_name, len(per_record_errors), per_record_errors[0],
        )
    return TagProjectionSummary(
        table_name=table_name,
        record_count=record_count,
        rows_persisted=rows_persisted,
        skipped_records=skipped,
        error=error,
    )

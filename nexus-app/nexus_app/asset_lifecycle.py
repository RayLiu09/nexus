"""Manual asset archive and irreversible deletion operations."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.database import Base
from nexus_app.enums import AssetVersionStatus, AuditEventType


class AssetLifecycleError(Exception):
    pass


def archive_asset(
    session: Session,
    asset: models.Asset,
    *,
    actor_id: str,
    trace_id: str | None,
) -> dict[str, int | str]:
    """Archive every version of an asset while retaining its lineage."""
    versions = list(
        session.scalars(
            select(models.AssetVersion).where(models.AssetVersion.asset_id == asset.id)
        ).all()
    )
    changed = sum(version.version_status != AssetVersionStatus.ARCHIVED for version in versions)
    for version in versions:
        version.version_status = AssetVersionStatus.ARCHIVED
    asset.status = AssetVersionStatus.ARCHIVED
    write_audit(
        session,
        AuditEventType.ASSET_ARCHIVED,
        "asset",
        asset.id,
        trace_id,
        {"asset_id": asset.id, "version_count": len(versions), "changed_version_count": changed},
        actor_type="user",
        actor_id=actor_id,
    )
    session.commit()
    return {"asset_id": asset.id, "status": AssetVersionStatus.ARCHIVED.value, "version_count": len(versions)}


def delete_asset(
    session: Session,
    asset: models.Asset,
    *,
    actor_id: str,
    trace_id: str | None,
) -> dict[str, int | str]:
    """Permanently remove an asset and all reachable derivatives.

    Audit rows have no foreign keys and are deliberately handled separately:
    historical asset-targeted logs are removed, then one bounded deletion event
    is retained after the data purge.
    """
    asset_id = asset.id
    title = asset.title
    version_rows = list(
        session.scalars(
            select(models.AssetVersion).where(models.AssetVersion.asset_id == asset_id)
        ).all()
    )
    version_ids = {row.id for row in version_rows}
    raw_ids = {row.raw_object_id for row in version_rows}
    exclusive_raw_ids = {
        raw_id
        for raw_id in raw_ids
        if session.scalar(
            select(func.count())
            .select_from(models.AssetVersion)
            .where(
                models.AssetVersion.raw_object_id == raw_id,
                models.AssetVersion.asset_id != asset_id,
            )
        ) == 0
    }
    roots = {"asset": {asset_id}, "asset_version": version_ids, "raw_object": exclusive_raw_ids}
    rows_by_table = _collect_descendants(session, roots)

    # An audit entry is retained only for this deletion itself, not as asset lineage.
    audit_targets = set().union(*rows_by_table.values())
    session.execute(
        delete(models.AuditLog).where(
            models.AuditLog.target_id.in_(audit_targets),
        )
    )
    deleted_counts = _delete_descendants(session, rows_by_table)
    write_audit(
        session,
        AuditEventType.ASSET_DELETED,
        "asset",
        asset_id,
        trace_id,
        {
            "asset_id": asset_id,
            "asset_title": title,
            "version_count": len(version_ids),
            "exclusive_raw_object_count": len(exclusive_raw_ids),
        },
        actor_type="user",
        actor_id=actor_id,
    )
    session.commit()
    session.expire_all()
    return {
        "asset_id": asset_id,
        "deleted": True,
        "version_count": len(version_ids),
        "exclusive_raw_object_count": len(exclusive_raw_ids),
        "deleted_row_count": sum(deleted_counts.values()),
    }


def _collect_descendants(
    session: Session, roots: dict[str, set[str]]
) -> dict[str, set[str]]:
    """Collect FK descendants for the supplied table/id roots.

    Every NEXUS entity uses ``id`` as its primary key. Walking SQLAlchemy's
    metadata therefore keeps hard deletion aligned with newly added derivative
    tables without treating parent links (for example raw_object -> batch) as
    delete targets.
    """
    rows = {name: set(ids) for name, ids in roots.items() if ids}
    changed = True
    while changed:
        changed = False
        for table in Base.metadata.tables.values():
            if table.name == models.AuditLog.__tablename__ or "id" not in table.c:
                continue
            for foreign_key in table.foreign_keys:
                parent_ids = rows.get(foreign_key.column.table.name)
                if not parent_ids or foreign_key.column.name != "id":
                    continue
                found = set(
                    session.scalars(
                        select(table.c.id).where(foreign_key.parent.in_(parent_ids))
                    ).all()
                )
                if not found:
                    continue
                known = rows.setdefault(table.name, set())
                additions = found - known
                if additions:
                    known.update(additions)
                    changed = True
            # A few projections deliberately use logical identifiers instead
            # of hard FKs (for example tag_asset_index). They are still
            # derived asset data and must be removed by a permanent delete.
            for column_name, parent_table in (
                ("asset_id", "asset"),
                ("asset_version_id", "asset_version"),
                ("normalized_ref_id", "normalized_asset_ref"),
            ):
                parent_ids = rows.get(parent_table)
                if not parent_ids or column_name not in table.c:
                    continue
                found = set(
                    session.scalars(
                        select(table.c.id).where(table.c[column_name].in_(parent_ids))
                    ).all()
                )
                known = rows.setdefault(table.name, set())
                additions = found - known
                if additions:
                    known.update(additions)
                    changed = True
    return rows


def _delete_descendants(session: Session, rows_by_table: dict[str, set[str]]) -> dict[str, int]:
    dependencies: dict[str, set[str]] = defaultdict(set)
    for table in Base.metadata.tables.values():
        if table.name not in rows_by_table:
            continue
        for foreign_key in table.foreign_keys:
            parent = foreign_key.column.table.name
            if parent in rows_by_table and parent != table.name:
                dependencies[table.name].add(parent)

    ordered: list[str] = []
    remaining = set(rows_by_table)
    while remaining:
        ready = sorted(name for name in remaining if not (dependencies[name] & remaining))
        if not ready:
            raise AssetLifecycleError("asset deletion encountered a cyclic dependent relation")
        ordered.extend(ready)
        remaining.difference_update(ready)

    deleted_counts: dict[str, int] = {}
    for table_name in reversed(ordered):
        table = Base.metadata.tables[table_name]
        result = session.execute(delete(table).where(table.c.id.in_(rows_by_table[table_name])))
        deleted_counts[table_name] = int(result.rowcount or 0)
    return deleted_counts

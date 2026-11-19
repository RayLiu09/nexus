"""Bounded, audited maintenance for derived vector projections only."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from sqlalchemy import delete, exists, or_, select, text
from sqlalchemy.orm import Session, load_only

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.enums import AuditEventType, IndexManifestStatus
from nexus_app.index.semantic_policy import STRUCTURED_ONLY_ASSET_TYPES
from nexus_app.index.vector_metadata import (
    CANONICAL_FIELDS, compact_metadata, hydrate_metadata, same_json_value,
)


def _audit(session: Session, operation: str, trace_id: str, summary: dict[str, Any]) -> None:
    write_audit(
        session, AuditEventType.KNOWLEDGE_CHUNKS_INDEXED,
        target_type="vector_projection_maintenance", target_id=trace_id,
        trace_id=trace_id, actor_type="system", actor_id="pgvector-projection-maintenance",
        summary={"operation": operation, **summary},
    )


def compact_batch(
    session: Session, *, after_id: str = "", batch_size: int = 250,
    apply: bool = False, trace_id: str = "pgvector-metadata-dry-run",
    after_ref_id: str | None = None,
) -> dict[str, Any]:
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    if session.get_bind().dialect.name == "postgresql":
        return _compact_postgresql_batch(
            session, after_id=after_id, batch_size=batch_size, apply=apply, trace_id=trace_id,
            after_ref_id=after_ref_id,
        )
    if after_ref_id is not None:
        raise ValueError("normalized-ref maintenance cursor requires PostgreSQL")
    query = select(models.KnowledgeEmbeddingPgvector).where(
        models.KnowledgeEmbeddingPgvector.id > after_id,
    ).order_by(models.KnowledgeEmbeddingPgvector.id).limit(batch_size).options(load_only(
        models.KnowledgeEmbeddingPgvector.id,
        models.KnowledgeEmbeddingPgvector.normalized_ref_id,
        models.KnowledgeEmbeddingPgvector.vector_metadata,
    ))
    if apply:
        query = query.with_for_update()
    rows = list(session.scalars(query))
    ref_query = select(models.NormalizedAssetRef).where(
        models.NormalizedAssetRef.id.in_({row.normalized_ref_id for row in rows}),
    ).order_by(models.NormalizedAssetRef.id).options(load_only(
        models.NormalizedAssetRef.id, models.NormalizedAssetRef.governance,
        models.NormalizedAssetRef.quality, models.NormalizedAssetRef.lineage,
    ))
    if apply:
        # Keep checked canonical copies stable until the projection update and
        # audit commit; never remove data based on an unlocked stale snapshot.
        ref_query = ref_query.with_for_update(read=True)
    refs = {ref.id: ref for ref in session.scalars(ref_query)}
    result: dict[str, Any] = {
        "scanned": len(rows), "changed": 0, "removed_fields": 0,
        "mismatched_fields": 0, "missing_sources": 0,
        "json_bytes_before": 0, "json_bytes_after": 0,
        "last_id": rows[-1].id if rows else after_id,
    }
    for row in rows:
        ref = refs.get(row.normalized_ref_id)
        old = row.vector_metadata or {}
        parent = old.get("normalized_ref")
        if ref is None or not isinstance(parent, dict) or parent.get("normalized_ref_id") != ref.id:
            result["missing_sources"] += 1
            continue
        result["mismatched_fields"] += sum(
            field in parent and not same_json_value(parent[field], getattr(ref, field))
            for field in CANONICAL_FIELDS
        )
        compact, removed = compact_metadata(old, ref)
        if not removed:
            continue
        expected = deepcopy(hydrate_metadata(old, ref))
        for field in removed:
            expected["normalized_ref"][field] = deepcopy(getattr(ref, field))
        if "governance" in removed and isinstance(expected.get("asset"), dict) and isinstance(ref.governance, dict):
            for field in ("classification", "level", "tags", "org_scope"):
                if field in expected["asset"] and field in ref.governance:
                    expected["asset"][field] = deepcopy(ref.governance[field])
        if not same_json_value(hydrate_metadata(compact, ref), expected):
            raise ValueError("vector metadata hydration changed fields beyond canonical snapshots")
        result["changed"] += 1
        result["removed_fields"] += len(removed)
        result["json_bytes_before"] += len(json.dumps(old, ensure_ascii=False).encode())
        result["json_bytes_after"] += len(json.dumps(compact, ensure_ascii=False).encode())
        if apply:
            row.vector_metadata = compact
    if apply and result["changed"]:
        _audit(session, "compact_metadata", trace_id, result)
    return result


def _compact_postgresql_batch(
    session: Session, *, after_id: str, batch_size: int, apply: bool, trace_id: str,
    after_ref_id: str | None = None,
    block_range: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Compact inside PostgreSQL so multi-GB snapshots never cross the network.

    Lock only the bounded vector batch and its canonical refs. The rewrite
    changes precisely the three normalized snapshots and their private marker;
    embedding, identifiers, locator and every other metadata key are untouched.
    Invalid markers cause the caller's whole transaction to roll back.
    """
    vector_lock = "FOR UPDATE" if apply else ""
    ref_lock = "FOR SHARE" if apply else ""
    cursor_filter = "id > :after_id"
    cursor_order = "id"
    cursor_result = "COALESCE(max(id), :after_id) AS last_id"
    batch_limit = "LIMIT :batch_size"
    if after_ref_id is not None:
        # Ingested chunks of one normalized asset share nearby TOAST pages.
        # UUID-only order creates random reads across the entire multi-GB table.
        # This stable composite cursor uses the existing normalized-ref index.
        cursor_filter = "(normalized_ref_id, id) > (:after_ref_id, :after_id)"
        cursor_order = "normalized_ref_id, id"
        cursor_result = """COALESCE((SELECT id FROM batch
            ORDER BY normalized_ref_id DESC, id DESC LIMIT 1), :after_id) AS last_id,
            COALESCE(max(normalized_ref_id), :after_ref_id) AS last_ref_id"""
    if block_range is not None:
        # A fixed physical range avoids random UUID/secondary-index heap reads.
        # The caller fixes the original upper block before updates append rows.
        # Each range is committed once; already compacted rows are idempotent.
        cursor_filter = "ctid >= CAST(:start_tid AS tid) AND ctid < CAST(:end_tid AS tid)"
        cursor_order = "ctid"
        batch_limit = ""
    update_cte = """, updated AS (
        UPDATE knowledge_embedding_pgvector e
        SET metadata = r.compact, updated_at = CURRENT_TIMESTAMP
        FROM rewritten r
        WHERE e.id = r.id AND cardinality(r.removed) > 0 AND r.valid_marker
        RETURNING e.id
    )""" if apply else ""
    sql = f"""
    WITH batch AS MATERIALIZED (
        SELECT id, normalized_ref_id, CAST(metadata AS jsonb) AS old
        FROM knowledge_embedding_pgvector
        WHERE {cursor_filter} ORDER BY {cursor_order} {batch_limit} {vector_lock}
    ), refs AS MATERIALIZED (
        SELECT id, CAST(governance AS jsonb) AS governance,
            CAST(quality AS jsonb) AS quality, CAST(lineage AS jsonb) AS lineage,
            jsonb_build_object(
                'governance', COALESCE(jsonb_typeof(CAST(governance AS jsonb)) <> 'null', false),
                'quality', COALESCE(jsonb_typeof(CAST(quality AS jsonb)) <> 'null', false),
                'lineage', COALESCE(jsonb_typeof(CAST(lineage AS jsonb)) <> 'null', false)
            ) AS available
        FROM normalized_asset_ref WHERE id IN (SELECT normalized_ref_id FROM batch)
        ORDER BY id {ref_lock}
    ), joined AS MATERIALIZED (
        SELECT b.*, n.id AS source_id,
            n.available,
            CASE WHEN b.old->'normalized_ref' ? 'governance'
                AND b.old->'normalized_ref'->'governance' IS DISTINCT FROM n.governance THEN 1 ELSE 0 END
            + CASE WHEN b.old->'normalized_ref' ? 'quality'
                AND b.old->'normalized_ref'->'quality' IS DISTINCT FROM n.quality THEN 1 ELSE 0 END
            + CASE WHEN b.old->'normalized_ref' ? 'lineage'
                AND b.old->'normalized_ref'->'lineage' IS DISTINCT FROM n.lineage THEN 1 ELSE 0 END AS differences,
            n.id IS NOT NULL AND jsonb_typeof(b.old->'normalized_ref') = 'object'
                AND b.old->'normalized_ref'->>'normalized_ref_id' = n.id AS valid_source,
            NOT (b.old ? '_normalized_ref_fields') OR (
                jsonb_typeof(b.old->'_normalized_ref_fields') = 'array'
                AND NOT EXISTS (
                    SELECT 1 FROM jsonb_array_elements(
                        CASE WHEN jsonb_typeof(b.old->'_normalized_ref_fields') = 'array'
                        THEN b.old->'_normalized_ref_fields' ELSE '[]'::jsonb END
                    ) marker(value)
                    WHERE marker.value NOT IN ('"governance"'::jsonb, '"quality"'::jsonb, '"lineage"'::jsonb)
                )
            ) AS valid_marker
        FROM batch b LEFT JOIN refs n ON n.id = b.normalized_ref_id
    ), prepared AS MATERIALIZED (
        SELECT j.*,
            ARRAY(SELECT field FROM unnest(ARRAY['governance','quality','lineage']) AS field
                WHERE valid_source AND old->'normalized_ref' ? field
                AND available->field = 'true'::jsonb) AS removed,
            CASE WHEN valid_source THEN differences ELSE 0 END AS mismatches,
            ARRAY(SELECT field FROM unnest(ARRAY['governance','quality','lineage']) AS field
                WHERE (old->'_normalized_ref_fields' ? field)
                    OR (valid_source AND old->'normalized_ref' ? field
                        AND available->field = 'true'::jsonb)) AS omitted
        FROM joined j
    ), rewritten AS MATERIALIZED (
        SELECT p.*, CASE WHEN cardinality(removed) > 0 THEN
            jsonb_set(old, '{{normalized_ref}}', (old->'normalized_ref') - removed)
                || jsonb_build_object('_normalized_ref_fields', to_jsonb(omitted))
            ELSE old END AS compact
        FROM prepared p
    ) {update_cte}
    SELECT count(*) AS scanned,
        count(*) FILTER (WHERE cardinality(removed) > 0) AS changed,
        COALESCE(sum(cardinality(removed)), 0) AS removed_fields,
        COALESCE(sum(mismatches), 0) AS mismatched_fields,
        count(*) FILTER (WHERE valid_source IS NOT TRUE) AS missing_sources,
        count(*) FILTER (WHERE NOT valid_marker) AS invalid_markers,
        COALESCE(sum(octet_length(old::text)) FILTER (WHERE cardinality(removed) > 0), 0) AS json_bytes_before,
        COALESCE(sum(octet_length(compact::text)) FILTER (WHERE cardinality(removed) > 0), 0) AS json_bytes_after,
        {cursor_result}
        {', (SELECT count(*) FROM updated) AS applied' if apply else ''}
    FROM rewritten
    """
    result = dict(session.execute(text(sql), {
        "after_id": after_id, "after_ref_id": after_ref_id, "batch_size": batch_size,
        "start_tid": f"({block_range[0]},0)" if block_range else None,
        "end_tid": f"({block_range[1]},0)" if block_range else None,
    }).mappings().one())
    if result.pop("invalid_markers"):
        raise ValueError("invalid compact vector metadata marker")
    if apply and result.pop("applied") != result["changed"]:
        raise ValueError("vector metadata compaction count mismatch")
    # PostgreSQL numeric aggregates may arrive as Decimal.
    result = {key: value if key in {"last_id", "last_ref_id"} else int(value) for key, value in result.items()}
    if apply and result["changed"]:
        _audit(session, "compact_metadata", trace_id, result)
    return result


def cleanup_retired_batch(
    session: Session, *, batch_size: int = 250, apply: bool = False,
    trace_id: str = "pgvector-retired-dry-run",
) -> dict[str, Any]:
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    E, C = models.KnowledgeEmbeddingPgvector, models.VectorCollection
    retired_collection = or_(
        C.normalized_type == "record", C.asset_domain_type.in_(STRUCTURED_ONLY_ASSET_TYPES),
    )
    collection_ids = list(session.scalars(select(C.id).where(retired_collection)))
    retired_vector = or_(
        E.collection_id.in_(collection_ids), E.normalized_type == "record",
        E.asset_domain_type.in_(STRUCTURED_ONLY_ASSET_TYPES),
        E.knowledge_type_code.in_(STRUCTURED_ONLY_ASSET_TYPES),
    )
    query = select(E).where(retired_vector).order_by(E.id).limit(batch_size).options(load_only(
        E.id, E.normalized_ref_id, E.knowledge_type_code, E.normalized_type,
    ))
    if apply:
        query = query.with_for_update()
    rows = list(session.scalars(query))
    ids = [row.id for row in rows]
    pairs = {(row.normalized_ref_id, row.knowledge_type_code) for row in rows}
    record_refs = set(session.scalars(select(models.NormalizedAssetRef.id).where(
        models.NormalizedAssetRef.id.in_({row.normalized_ref_id for row in rows}),
        models.NormalizedAssetRef.normalized_type == "record",
    )))
    manifests = list(session.scalars(select(models.IndexManifest).where(
        models.IndexManifest.normalized_ref_id.in_({ref for ref, _ in pairs}),
    )))
    stale = [m for m in manifests if (
        m.normalized_ref_id in record_refs or (m.normalized_ref_id, m.knowledge_type_code) in pairs
    ) and m.index_status != IndexManifestStatus.STALE]
    if apply:
        if ids:
            session.execute(delete(E).where(E.id.in_(ids)))
        for manifest in stale:
            manifest.index_status = IndexManifestStatus.STALE
            manifest.chunk_count = 0
            manifest.error_message = "retired semantic projection: domain-table retrieval only"
        session.flush()
    empty = list(session.scalars(select(C.id).where(
        retired_collection, ~exists(select(E.id).where(E.collection_id == C.id)),
    )))
    if apply and empty:
        session.execute(delete(C).where(C.id.in_(empty)))
    result = {
        "vectors": len(ids), "collections": len(empty), "stale_manifests": len(stale),
        "normalized_refs_preserved": len({ref for ref, _ in pairs}),
        "batch_full": len(rows) == batch_size,
    }
    if apply and (ids or empty or stale):
        _audit(session, "retire_structured_projections", trace_id, result)
    return result

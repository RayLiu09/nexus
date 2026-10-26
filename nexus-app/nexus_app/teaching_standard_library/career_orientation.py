"""Deterministic repair of source-scoped career facts, without course/AI writes."""
from __future__ import annotations

from sqlalchemy import select

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.enums import AuditEventType
from nexus_app.teaching_standard_library.extractor import extract

_FIELDS = ("dimension_type", "source_code", "source_name", "source_text", "evidence_block_ids", "locator")


def refresh_career_orientation(session, library, payload, *, apply_changes=False):
    projection = extract(payload)
    facts = projection.get("occupations", []) if projection else []
    if not facts:
        return {"library_id": library.id, "status": "no_source_facts", "fact_count": 0}
    previous = list(session.scalars(select(models.TeachingStandardOccupation).where(
        models.TeachingStandardOccupation.library_id == library.id,
    ).order_by(models.TeachingStandardOccupation.dimension_type, models.TeachingStandardOccupation.item_index)))
    desired = sorted(facts, key=lambda item: item["dimension_type"])
    same = [{key: getattr(row, key) for key in _FIELDS} for row in previous] == [
        {key: item.get(key, [] if key == "evidence_block_ids" else {} if key == "locator" else None) for key in _FIELDS}
        for item in desired
    ]
    if same:
        return {"library_id": library.id, "status": "unchanged", "fact_count": len(facts)}
    if apply_changes:
        for row in previous:
            session.delete(row)
        session.flush()
        counters = {}
        for item in desired:
            dimension = item["dimension_type"]
            counters[dimension] = counters.get(dimension, 0) + 1
            session.add(models.TeachingStandardOccupation(
                library_id=library.id, item_index=counters[dimension],
                **{key: item.get(key, [] if key == "evidence_block_ids" else {} if key == "locator" else None) for key in _FIELDS},
            ))
        flags = dict(library.quality_flags or {})
        flags.pop("occupation_orientation_missing", None)
        library.quality_flags = flags
        session.flush()
        session.expire(library, ["occupations"])
        write_audit(session, AuditEventType.TEACHING_STANDARD_LIBRARY_GENERATED, trace_id=None,
                    actor_type="system", actor_id="career_orientation_backfill",
                    target_type="teaching_standard_library", target_id=library.id,
                    summary={"projection_scope": "career_orientation", "fact_count": len(facts),
                             "normalized_ref_id": library.normalized_ref_id, "ai_called": False})
    return {"library_id": library.id, "status": "updated" if apply_changes else "would_update", "fact_count": len(facts)}

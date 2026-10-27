"""Insert school/year/major/duration facts; repeated facts never overwrite values."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from nexus_app import models
from nexus_app.data_sync.adapters.moe_major_offering import (
    MoeQuery,
    PROVINCES,
    SOURCE_URL,
)
from nexus_app.data_sync.job_posting_intake import IntakeCounts
from nexus_app.data_sync.runtime import SyncRuntimeError


def school_name_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


class MajorOfferingResultHandler:
    def accept_page(self, session, run, records) -> IntakeCounts:
        query = MoeQuery.model_validate(run.query_snapshot)
        accepted = 0
        for record in records:
            if not isinstance(record, dict):
                raise SyncRuntimeError(
                    "invalid school fact", code="invalid_major_offering"
                )
            required = (
                "prov_name",
                "major_code",
                "major_name",
                "school_name",
                "school_system",
            )
            if any(
                not isinstance(record.get(k), str) or not record[k].strip()
                for k in required
            ):
                raise SyncRuntimeError(
                    "missing school fact field", code="invalid_major_offering"
                )
            province_name = record["prov_name"].strip()
            province_code = next(
                (code for code, name in PROVINCES.items() if name == province_name),
                None,
            )
            major_code = record["major_code"].strip()
            if province_code is None or not re.fullmatch(r"\d{6}", major_code):
                raise SyncRuntimeError(
                    "invalid province or major code", code="invalid_major_offering"
                )
            if (
                (query.province is not None and province_code != query.province)
                or (query.major_code is not None and major_code != query.major_code)
                or (
                    query.major_name is not None
                    and query.major_name not in record["major_name"].strip()
                )
            ):
                raise SyncRuntimeError(
                    "source scope mismatch", code="major_offering_scope_mismatch"
                )
            code = record.get("school_code")
            remark = record.get("remark")
            if any(v is not None and not isinstance(v, str) for v in (code, remark)):
                raise SyncRuntimeError(
                    "invalid optional field", code="invalid_major_offering"
                )
            code = code.strip() or None if code is not None else None
            accepted += insert_offering(session, {
                "sync_run_id": run.id,
                "provider_code": run.provider_code,
                "year": query.year,
                "province_code": province_code,
                "province_name": province_name,
                "major_code": major_code,
                "major_name": record["major_name"].strip(),
                "school_code": code,
                "school_name": record["school_name"].strip(),
                "study_duration": record["school_system"].strip(),
                "remark": remark,
                "source_url": SOURCE_URL,
            })
        return IntakeCounts(accepted=accepted, duplicate=len(records) - accepted)


def insert_offering(session, values: dict) -> int:
    """Shared API/Excel identity check and concurrent insert protection."""
    code = values.get("school_code")
    name_key = school_name_key(values["school_name"])
    model = models.MajorOfferingRecord
    predicates = [model.school_name_key == name_key]
    if code:
        predicates.append(model.school_code == code)
    statement = select(model).where(
        model.year == values["year"],
        model.major_code == values["major_code"],
        model.study_duration == values["study_duration"],
        or_(*predicates),
    )

    def duplicate():
        matches = list(session.scalars(statement))
        if len(matches) > 1:
            raise SyncRuntimeError("ambiguous school identity", code="school_identity_conflict")
        existing = matches[0] if matches else None
        if existing and code and existing.school_code and existing.school_code != code:
            raise SyncRuntimeError("school identity conflict", code="school_identity_conflict")
        return existing is not None

    if duplicate():
        return 0
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    inserted = session.execute(
        insert(model).values(
            **values, school_name_key=name_key, fetched_at=datetime.now(timezone.utc),
        ).on_conflict_do_nothing().returning(model.id)
    ).scalar_one_or_none()
    if inserted is not None:
        return 1
    if not duplicate():
        raise SyncRuntimeError("unresolved uniqueness conflict", code="school_identity_conflict")
    return 0

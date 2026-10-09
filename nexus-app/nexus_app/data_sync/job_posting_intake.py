"""Persist crawler-engine job fields and their immutable collection provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.data_sync.runtime import SyncRuntimeError


FIELD_COLUMNS = {
    "title": "title_raw",
    "companyName": "company_name_raw",
    "addressText": "address_raw",
    "salaryText": "salary_raw",
    "experienceText": "experience_raw",
    "degreeText": "degree_raw",
    "hiringText": "hiring_raw",
    "description": "description_raw",
    "skillsText": "skills_raw",
    "jobTagsText": "job_tags_raw",
    "jobResponsibilitiesText": "responsibilities_raw",
    "jobRequirementsText": "requirements_raw",
    "qualificationsText": "qualifications_raw",
    "otherMattersText": "other_matters_raw",
    "companyIndustryText": "company_industry_raw",
    "companyScaleText": "company_scale_raw",
    "companyFinancingText": "company_financing_raw",
}


@dataclass(frozen=True)
class IntakeCounts:
    accepted: int
    duplicate: int


def _canonical_hash(record: dict[str, Any]) -> str:
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _existing(session: Session, provider_code: str, record_id: str) -> models.RawJobProvenance | None:
    return session.scalar(select(models.RawJobProvenance).where(
        models.RawJobProvenance.provider_code == provider_code,
        models.RawJobProvenance.upstream_record_id == record_id,
    ))


class JobPostingResultHandler:
    def accept_page(
        self, session: Session, run: models.DataSyncRun, records: list[dict[str, Any]],
    ) -> IntakeCounts:
        accepted = 0
        for record in records:
            fields = record.get("fields")
            record_id = record.get("recordId")
            if not isinstance(fields, dict) or not isinstance(record_id, str):
                raise SyncRuntimeError("invalid raw job record", code="invalid_job_record")
            values = {column: fields.get(field) for field, column in FIELD_COLUMNS.items()}
            if not isinstance(values["title_raw"], str) or not values["title_raw"]:
                raise SyncRuntimeError("invalid raw job title", code="invalid_job_record")
            if any(value is not None and not isinstance(value, str) for value in values.values()):
                raise SyncRuntimeError("invalid raw job field", code="invalid_job_record")
            digest = _canonical_hash(record)
            existing = _existing(session, run.provider_code, record_id)
            if existing is not None:
                if existing.raw_record_hash != digest:
                    raise SyncRuntimeError("upstream record ID changed payload", code="raw_record_conflict")
                continue
            try:
                collected_at = datetime.fromisoformat(record["collectedAt"].replace("Z", "+00:00"))
                with session.begin_nested():
                    job = models.RawJob(**values)
                    session.add(job)
                    session.flush()
                    session.add(models.RawJobProvenance(
                        raw_job_id=job.id,
                        provider_code=run.provider_code,
                        upstream_record_id=record_id,
                        source_name=record["source"],
                        source_job_id=record.get("sourceJobId"),
                        source_url=record["sourceUrl"],
                        external_job_id=run.external_task_id,
                        external_task_id=record["taskId"],
                        source_page=record["page"],
                        keyword=record["keyword"],
                        query_region=record.get("region"),
                        collected_at=collected_at,
                        upstream_payload_hash=record["payloadHash"],
                        raw_record_hash=digest,
                        raw_record=record,
                    ))
                    session.flush()
            except IntegrityError:
                existing = _existing(session, run.provider_code, record_id)
                if existing is None:
                    raise
                if existing.raw_record_hash != digest:
                    raise SyncRuntimeError("upstream record ID changed payload", code="raw_record_conflict")
            except (KeyError, TypeError, ValueError) as exc:
                raise SyncRuntimeError("invalid raw job record", code="invalid_job_record") from exc
            else:
                accepted += 1
        return IntakeCounts(accepted=accepted, duplicate=len(records) - accepted)

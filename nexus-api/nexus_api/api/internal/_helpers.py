"""Shared helpers for `/internal/v1` sub-routers.

Kept private to the `internal` package — anything external should import from
the module that owns the concern (e.g. `nexus_api.responses` for envelopes).
"""
from __future__ import annotations

from pydantic import ValidationError

from fastapi import HTTPException

from nexus_app import models, schemas as domain_schemas
from nexus_app.ai_governance.rules_registry import (
    GovernanceRulesRegistry,
    get_governance_rules_registry,
)
from nexus_app.ai_governance.services import (
    AIGovernanceService,
    PromptProfileService,
)
from nexus_app.enums import DataSourceType
from nexus_app.ingest import batch as ingest_batch
from nexus_app.ingest import gateway as ingest_gateway

# Shared service singletons. Stateless — safe to share across requests.
prompt_svc = PromptProfileService()
ai_gov_svc = AIGovernanceService()

# Production fail-fast load is in main.py lifespan. We additionally do a
# tolerant eager load here so test harnesses that instantiate TestClient(app)
# without the `with` context (which would trigger lifespan) still get a
# populated registry.
_rules_registry = get_governance_rules_registry()
try:
    if _rules_registry._config is None:
        _rules_registry.load()
except Exception:
    pass  # lifespan will surface the failure in production startup


def get_rules_registry() -> GovernanceRulesRegistry | None:
    return _rules_registry if _rules_registry._config is not None else None


def rules_registry() -> GovernanceRulesRegistry:
    """Direct access for handlers that need the registry without a None check."""
    return _rules_registry


_CONNECTION_CONFIG_SCHEMAS = {
    DataSourceType.NAS: domain_schemas.NasConnectionConfig,
    DataSourceType.CRAWLER: domain_schemas.CrawlerConnectionConfig,
    DataSourceType.DATABASE: domain_schemas.DatabaseConnectionConfig,
    DataSourceType.WEBHOOK: domain_schemas.WebhookConnectionConfig,
}


def validate_connection_config(source_type: DataSourceType, config: dict) -> None:
    schema_cls = _CONNECTION_CONFIG_SCHEMAS.get(source_type)
    if schema_cls is None:
        return
    try:
        schema_cls.model_validate(config)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"connection_config invalid for source_type={source_type}: {exc}",
        ) from exc


def append_read(
    result: ingest_batch.BatchAppendResult,
) -> domain_schemas.IngestFileAppendRead:
    return domain_schemas.IngestFileAppendRead(
        raw_object_id=result.raw_object.id,
        job_id=result.job.id,
        job_status=result.job.status,
        file_idempotency_key=result.raw_object.file_idempotency_key or "",
        duplicate=result.duplicate,
    )


def accepted_read(
    result: ingest_gateway.IngestAccepted,
) -> domain_schemas.IngestAcceptedRead:
    return domain_schemas.IngestAcceptedRead(
        batch=domain_schemas.IngestBatchRead.model_validate(result.batch),
        raw_object=domain_schemas.RawObjectRead.model_validate(result.raw_object),
        job=domain_schemas.JobRead.model_validate(result.job),
    )


_VALID_TRAIL_VIEWS = {"full", "operator", "public"}


def validate_view(view: str) -> str:
    if view not in _VALID_TRAIL_VIEWS:
        raise HTTPException(
            status_code=422,
            detail=f"invalid view '{view}'; must be one of "
            f"{sorted(_VALID_TRAIL_VIEWS)}",
        )
    return view


def serialize_result_with_view(
    result: models.GovernanceResult, view: str
) -> dict:
    """Run the result through GovernanceResultRead, then apply the redaction."""
    from nexus_app.governance.redaction import redact_governance_result

    serialized = domain_schemas.GovernanceResultRead.model_validate(result).model_dump()
    return redact_governance_result(serialized, view)  # type: ignore[arg-type]

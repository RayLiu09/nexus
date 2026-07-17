"""Internal console endpoints for Pipeline B record assets.

These mirror the read shape of the public `/open/v1/record-assets/*`
endpoints, but are mounted under `/internal/v1` and protected by the console
operator JWT via the parent internal router. The console must not call the
API-caller-gated `/open` surface for asset detail tabs.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.dependencies.user import require_user
from nexus_api.responses import list_response, response
from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.capability_graph.whitelists import (
    BuildStatus,
    BuildType,
    EdgeType,
    NodeType,
)
from nexus_app.database import get_db
from nexus_app.enums import AuditEventType

router = APIRouter()


class MajorDistributionRecordPatch(BaseModel):
    year: int | None = Field(None, ge=1900, le=2200)
    province_name: str | None = Field(None, min_length=1, max_length=128)
    region_scope: str | None = Field(None, min_length=1, max_length=64)
    major_name: str | None = Field(None, min_length=1, max_length=256)
    major_code: str | None = Field(None, min_length=1, max_length=64)
    education_level: str | None = Field(None, max_length=64)
    distribution_count: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


def _serialize_job_demand_dataset(dataset: models.JobDemandDataset) -> dict:
    return {
        "id": dataset.id,
        "normalized_ref_id": dataset.normalized_ref_id,
        "asset_version_id": dataset.asset_version_id,
        "major_name": dataset.major_name,
        "industry_name": dataset.industry_name,
        "source_channel": dataset.source_channel,
        "schema_version": dataset.schema_version,
        "record_count": dataset.record_count,
        "invalid_count": dataset.invalid_count,
        "duplicate_count": dataset.duplicate_count,
        "quality_summary": dataset.quality_summary or {},
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
    }


def _serialize_job_demand_record(record: models.JobDemandRecord) -> dict:
    return {
        "id": record.id,
        "dataset_id": record.dataset_id,
        "normalized_ref_id": record.normalized_ref_id,
        "source_record_key": record.source_record_key,
        "source_url": record.source_url,
        "source_platform": record.source_platform,
        "source_published_at": (
            record.source_published_at.isoformat()
            if record.source_published_at
            else None
        ),
        "job_title": record.job_title,
        "employment_type": record.employment_type,
        "job_function_category": record.job_function_category,
        "job_count": record.job_count,
        "city": record.city,
        "region": record.region,
        "salary_min": float(record.salary_min) if record.salary_min is not None else None,
        "salary_max": float(record.salary_max) if record.salary_max is not None else None,
        "salary_text": record.salary_text,
        "experience_requirement": record.experience_requirement,
        "education_requirement": record.education_requirement,
        "company_name": record.company_name,
        "company_address": record.company_address,
        "enterprise_size": record.enterprise_size,
        "industry_name": record.industry_name,
        "job_skill_text": record.job_skill_text,
        "job_description": record.job_description,
        "responsibility_text": record.responsibility_text,
        "requirement_text": record.requirement_text,
        "quality_flags": record.quality_flags or {},
        "trace": record.trace or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _serialize_requirement_item(item: models.JobDemandRequirementItem) -> dict:
    return {
        "id": item.id,
        "record_id": item.record_id,
        "dataset_id": item.dataset_id,
        "item_type": item.item_type,
        "item_name": item.item_name,
        "raw_text": item.raw_text,
        "normalized_name": item.normalized_name,
        "taxonomy_code": item.taxonomy_code,
        "confidence": float(item.confidence) if item.confidence is not None else None,
        "extractor_version": item.extractor_version,
        "evidence_field": item.evidence_field,
        "ai_model_alias": item.ai_model_alias,
    }


def _serialize_capability_graph_node(
    node: models.CapabilityGraphStagingNode,
) -> dict:
    return {
        "id": node.id,
        "node_type": node.node_type,
        "node_key": node.node_key,
        "display_name": node.display_name,
        "canonical_name": node.canonical_name,
        "properties": node.properties or {},
        "confidence": float(node.confidence) if node.confidence is not None else None,
    }


def _serialize_capability_graph_edge(
    edge: models.CapabilityGraphStagingEdge,
) -> dict:
    return {
        "id": edge.id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "edge_type": edge.edge_type,
        "confidence": float(edge.confidence) if edge.confidence is not None else None,
    }


def _serialize_major_distribution_dataset(
    dataset: models.MajorDistributionDataset,
) -> dict:
    return {
        "id": dataset.id,
        "normalized_ref_id": dataset.normalized_ref_id,
        "asset_version_id": dataset.asset_version_id,
        "dataset_name": dataset.dataset_name,
        "source_channel": dataset.source_channel,
        "major_scope": dataset.major_scope,
        "major_name": dataset.major_name,
        "major_code": dataset.major_code,
        "education_level": dataset.education_level,
        "year_min": dataset.year_min,
        "year_max": dataset.year_max,
        "province_count": dataset.province_count,
        "record_count": dataset.record_count,
        "invalid_count": dataset.invalid_count,
        "placeholder_count": dataset.placeholder_count,
        "ignored_summary_count": dataset.ignored_summary_count,
        "duplicate_count": dataset.duplicate_count,
        "schema_version": dataset.schema_version,
        "quality_summary": dataset.quality_summary or {},
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
    }


def _serialize_major_distribution_record(record: models.MajorDistributionRecord) -> dict:
    return {
        "id": record.id,
        "dataset_id": record.dataset_id,
        "normalized_ref_id": record.normalized_ref_id,
        "source_record_key": record.source_record_key,
        "source_row_no": record.source_row_no,
        "year": record.year,
        "year_text": record.year_text,
        "province_name": record.province_name,
        "region_scope": record.region_scope,
        "major_name": record.major_name,
        "major_code": record.major_code,
        "education_level": record.education_level,
        "distribution_count": record.distribution_count,
        "quality_flags": record.quality_flags or {},
        "trace": record.trace or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _major_distribution_record_snapshot(
    record: models.MajorDistributionRecord,
) -> dict:
    return {
        "year": record.year,
        "province_name": record.province_name,
        "region_scope": record.region_scope,
        "major_name": record.major_name,
        "major_code": record.major_code,
        "education_level": record.education_level,
        "distribution_count": record.distribution_count,
    }


def _recompute_major_distribution_dataset_summary(
    session: Session,
    dataset: models.MajorDistributionDataset,
) -> None:
    records = list(
        session.scalars(
            select(models.MajorDistributionRecord).where(
                models.MajorDistributionRecord.dataset_id == dataset.id
            )
        ).all()
    )
    dataset.record_count = len(records)
    dataset.province_count = len({r.province_name for r in records if r.province_name})
    years = [r.year for r in records if r.year is not None]
    dataset.year_min = min(years) if years else None
    dataset.year_max = max(years) if years else None
    dataset.invalid_count = sum(1 for r in records if r.quality_flags)
    dataset.major_name = _single_value_or_none(r.major_name for r in records)
    dataset.major_code = _single_value_or_none(r.major_code for r in records)
    dataset.education_level = _single_value_or_none(
        r.education_level for r in records if r.education_level
    )


def _single_value_or_none(values) -> str | None:
    unique = {value for value in values if value}
    return next(iter(unique)) if len(unique) == 1 else None


def _apply_major_distribution_dataset_filters(
    stmt,
    *,
    normalized_ref_id: str | None,
    major_code: str | None,
    major_name: str | None,
    education_level: str | None,
    year: int | None,
):
    if normalized_ref_id is not None:
        stmt = stmt.where(
            models.MajorDistributionDataset.normalized_ref_id == normalized_ref_id
        )
    if major_code is not None:
        stmt = stmt.where(models.MajorDistributionDataset.major_code == major_code)
    if major_name is not None:
        stmt = stmt.where(models.MajorDistributionDataset.major_name.contains(major_name))
    if education_level is not None:
        stmt = stmt.where(
            models.MajorDistributionDataset.education_level == education_level
        )
    if year is not None:
        stmt = stmt.where(
            models.MajorDistributionDataset.year_min <= year,
            models.MajorDistributionDataset.year_max >= year,
        )
    return stmt


def _apply_major_distribution_record_filters(
    stmt,
    *,
    normalized_ref_id: str | None = None,
    year: int | None = None,
    major_code: str | None = None,
    major_name: str | None = None,
    province_name: str | None = None,
    education_level: str | None = None,
    region_scope: str | None = None,
    min_count: int | None = None,
    max_count: int | None = None,
):
    if normalized_ref_id is not None:
        stmt = stmt.where(
            models.MajorDistributionRecord.normalized_ref_id == normalized_ref_id
        )
    if year is not None:
        stmt = stmt.where(models.MajorDistributionRecord.year == year)
    if major_code is not None:
        stmt = stmt.where(models.MajorDistributionRecord.major_code == major_code)
    if major_name is not None:
        stmt = stmt.where(models.MajorDistributionRecord.major_name.contains(major_name))
    if province_name is not None:
        stmt = stmt.where(models.MajorDistributionRecord.province_name == province_name)
    if education_level is not None:
        stmt = stmt.where(
            models.MajorDistributionRecord.education_level == education_level
        )
    if region_scope is not None:
        stmt = stmt.where(models.MajorDistributionRecord.region_scope == region_scope)
    if min_count is not None:
        stmt = stmt.where(models.MajorDistributionRecord.distribution_count >= min_count)
    if max_count is not None:
        stmt = stmt.where(models.MajorDistributionRecord.distribution_count <= max_count)
    return stmt


@router.get(
    "/record-assets/job-demand-datasets",
    response_model=schemas.ListResponse[dict],
)
def list_job_demand_datasets(
    request: Request,
    normalized_ref_id: str | None = Query(None, description="Exact match"),
    major: str | None = Query(None, description="`major_name` exact match"),
    industry: str | None = Query(None, description="`industry_name` exact match"),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    """Paginated list of B4 datasets for console-internal reads."""
    stmt = select(models.JobDemandDataset)
    count_stmt = select(func.count(models.JobDemandDataset.id))
    if normalized_ref_id is not None:
        stmt = stmt.where(models.JobDemandDataset.normalized_ref_id == normalized_ref_id)
        count_stmt = count_stmt.where(
            models.JobDemandDataset.normalized_ref_id == normalized_ref_id
        )
    if major is not None:
        stmt = stmt.where(models.JobDemandDataset.major_name == major)
        count_stmt = count_stmt.where(models.JobDemandDataset.major_name == major)
    if industry is not None:
        stmt = stmt.where(models.JobDemandDataset.industry_name == industry)
        count_stmt = count_stmt.where(models.JobDemandDataset.industry_name == industry)

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(models.JobDemandDataset.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_job_demand_dataset(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/record-assets/job-demand-datasets/{dataset_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_job_demand_dataset(
    dataset_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    dataset = session.get(models.JobDemandDataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail=f"job_demand_dataset '{dataset_id}' not found",
        )
    return response(_serialize_job_demand_dataset(dataset), request)


# ---------------------------------------------------------------------------
# A1b (§10 阶段 A + §1.14 §1.15 B1) — cross-dataset job-demand-records
# ---------------------------------------------------------------------------
#
# Scope narrowed by 4 rounds of review:
# * §1.9 决策 #2 — drop dataset-level filters, focus on the record list
# * §1.11 闭合 — major filter goes through job_demand_dataset.major_name
#   JOIN (no industry_name fallback that would collapse the semantic
#   distinction between "专业" and "行业")
# * §1.14 收窄 — remove even `job_title` (and every other细粒度 filter);
#   Composer takes care of追问 for narrower slices
# * §1.15 B1 (initial) — `fields=industry_distribution` opts into a Top-K
#   industry aggregation.
# * Batch B0.1 (post-registry-review) — the tool contract now says this
#   aggregation is **default on** and returns **Top-10** so scenario_2
#   dispatcher can render the "岗位行业分布图" without having to know
#   the opt-in flag exists. The `fields` whitelist is retained so a
#   caller CAN suppress the aggregation by passing a non-inclusive
#   `fields` list (e.g. `fields=count`) — useful for `LIST` UIs that
#   don't need the chart panel.
#
# `_INDUSTRY_DISTRIBUTION_TOP_K` is a hard cap; changing it moves the
# scenario_2 chart contract with dispatcher and Composer.

_INDUSTRY_DISTRIBUTION_FIELD = "industry_distribution"
_INDUSTRY_DISTRIBUTION_TOP_K = 10
_JOB_DEMAND_KNOWN_FIELDS: frozenset[str] = frozenset({
    "count",
    "industry_distribution",
    "tasks",
    "capability_requirements",
})


@router.get(
    "/record-assets/job-demand-records",
    response_model=schemas.ListResponse[dict],
)
def list_job_demand_records(
    request: Request,
    major: str = Query(
        ...,
        min_length=1,
        max_length=256,
        description=(
            "Required — substring match on `job_demand_dataset.major_name` "
            "(JOIN'd through `dataset_id`). §1.11 决策：do NOT fall back to "
            "`industry_name` — 专业 (major) ≠ 行业 (industry)."
        ),
    ),
    normalized_ref_id: str | None = Query(
        None,
        max_length=36,
        description="Optional trace-scoped narrowing (users referencing a specific dataset).",
    ),
    fields: list[str] | None = Query(
        None,
        description=(
            "Optional aggregation whitelist. `industry_distribution` (Top-10) "
            "is returned by DEFAULT when `fields` is omitted (Batch B0.1); "
            "pass a fields list that OMITS `industry_distribution` to "
            "suppress the aggregation (e.g. `?fields=count`). Unknown values "
            "are rejected (422) so typos don't silently no-op."
        ),
    ),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    """A1b — cross-dataset list of job_demand_records filtered by major.

    Response is `ListResponse[dict]` with an additional `aggregations`
    object riding on the top-level meta payload — see `list_response`
    below for how the aggregation is threaded in.

    §1.14 explicitly forbids `job_title` / `salary_*` / `region` /
    `experience_requirement` / `education_requirement` /
    `source_published_at` filters on this endpoint. Callers sending
    unknown query params should get FastAPI's default warn behaviour
    (silently ignored) — that's fine here because query param typos are
    a display problem, not a data-correctness one. The `fields` list is
    the one exception: unknown *field* names are rejected to keep the
    aggregation contract tight.
    """
    if fields:
        unknown = sorted(set(fields) - _JOB_DEMAND_KNOWN_FIELDS)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "unknown_field_name",
                    "unknown_fields": unknown,
                    "known_fields": sorted(_JOB_DEMAND_KNOWN_FIELDS),
                },
            )

    major_pattern = f"%{major}%"
    # Base filter — the JOIN + ILIKE + optional trace narrowing is shared
    # by both the record page query and the industry_distribution
    # aggregation, so keep it in one place.
    filter_clauses = [
        models.JobDemandRecord.dataset_id == models.JobDemandDataset.id,
        models.JobDemandDataset.major_name.ilike(major_pattern),
    ]
    if normalized_ref_id is not None:
        filter_clauses.append(
            models.JobDemandRecord.normalized_ref_id == normalized_ref_id
        )

    stmt = (
        select(models.JobDemandRecord)
        .join(models.JobDemandDataset,
              models.JobDemandRecord.dataset_id == models.JobDemandDataset.id)
        .where(*filter_clauses)
    )
    count_stmt = (
        select(func.count(models.JobDemandRecord.id))
        .join(models.JobDemandDataset,
              models.JobDemandRecord.dataset_id == models.JobDemandDataset.id)
        .where(*filter_clauses)
    )

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(models.JobDemandRecord.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )

    # Batch B0.1 — aggregation is default-on. It's only suppressed when
    # the caller sends an explicit `fields` list that omits the key.
    # (Explicit `?fields=industry_distribution&fields=count` still ON.)
    aggregations: dict[str, Any] = {}
    should_aggregate = fields is None or _INDUSTRY_DISTRIBUTION_FIELD in fields
    if should_aggregate:
        aggregations[_INDUSTRY_DISTRIBUTION_FIELD] = (
            _industry_distribution_top_k(session, filter_clauses)
        )

    return list_response(
        [_serialize_job_demand_record(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
        aggregations=aggregations or None,
    )


def _industry_distribution_top_k(
    session: Session,
    filter_clauses: list,
) -> list[dict[str, Any]]:
    """Aggregate `industry_name` counts under the same major/join filter.

    Returns Top-5 non-null industries with counts, ordered by count DESC
    then industry_name ASC. Null industries (records missing the field)
    are folded out — the "distribution of KNOWN industries" is what the
    scenario_2 chart expects.
    """
    industry_col = models.JobDemandRecord.industry_name
    agg_stmt = (
        select(industry_col, func.count(models.JobDemandRecord.id).label("count"))
        .join(models.JobDemandDataset,
              models.JobDemandRecord.dataset_id == models.JobDemandDataset.id)
        .where(*filter_clauses, industry_col.isnot(None))
        .group_by(industry_col)
        .order_by(func.count(models.JobDemandRecord.id).desc(),
                  industry_col.asc())
        .limit(_INDUSTRY_DISTRIBUTION_TOP_K)
    )
    rows = list(session.execute(agg_stmt).all())
    return [{"industry_name": row[0], "count": int(row[1])} for row in rows]


@router.get(
    "/record-assets/job-demand-datasets/{dataset_id}/records",
    response_model=schemas.ListResponse[dict],
)
def list_job_demand_records_for_dataset(
    dataset_id: str,
    request: Request,
    city: str | None = Query(None),
    industry: str | None = Query(None, description="`industry_name` exact match"),
    enterprise_size: str | None = Query(None),
    employment_type: str | None = Query(None),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    if session.get(models.JobDemandDataset, dataset_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"job_demand_dataset '{dataset_id}' not found",
        )

    stmt = select(models.JobDemandRecord).where(
        models.JobDemandRecord.dataset_id == dataset_id
    )
    count_stmt = select(func.count(models.JobDemandRecord.id)).where(
        models.JobDemandRecord.dataset_id == dataset_id
    )
    if city is not None:
        stmt = stmt.where(models.JobDemandRecord.city == city)
        count_stmt = count_stmt.where(models.JobDemandRecord.city == city)
    if industry is not None:
        stmt = stmt.where(models.JobDemandRecord.industry_name == industry)
        count_stmt = count_stmt.where(models.JobDemandRecord.industry_name == industry)
    if enterprise_size is not None:
        stmt = stmt.where(models.JobDemandRecord.enterprise_size == enterprise_size)
        count_stmt = count_stmt.where(
            models.JobDemandRecord.enterprise_size == enterprise_size
        )
    if employment_type is not None:
        stmt = stmt.where(models.JobDemandRecord.employment_type == employment_type)
        count_stmt = count_stmt.where(
            models.JobDemandRecord.employment_type == employment_type
        )

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(models.JobDemandRecord.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_job_demand_record(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


# ---------------------------------------------------------------------------
# B0.2 (§10 Batch B0) — cross-dataset job-demand-role-graph lookup
# ---------------------------------------------------------------------------
#
# The tool registry (§1.15) says scenario_2's `get_job_demand_role_graph`
# takes `job_title` as its primary key — no dataset_id, per the §2.5.0
# cross-asset rule. We keep the existing dataset-scoped endpoint intact
# (console UI still uses it) and add a sibling that fans out across every
# GENERATED job_demand staging build, unions the matching JOB_ROLE nodes
# by exact `display_name`, and returns each match's capability subgraph
# plus a `builds` list that surfaces the trace fields (build_id +
# normalized_ref_id + dataset_id) so Composer can cite each source.


def _load_job_demand_role_subgraph(
    session: Session,
    *,
    build: models.CapabilityGraphStagingBuild,
    role_node: models.CapabilityGraphStagingNode,
) -> tuple[list[dict], list[dict]]:
    """Given a JOB_ROLE node, load its capability edges + endpoint nodes.

    Extracted from `get_job_demand_role_graph` so the cross-dataset
    endpoint can reuse the exact same subgraph shape.
    """
    capability_edges = list(session.scalars(
        select(models.CapabilityGraphStagingEdge).where(
            models.CapabilityGraphStagingEdge.build_id == build.id,
            models.CapabilityGraphStagingEdge.source_node_id == role_node.id,
            models.CapabilityGraphStagingEdge.edge_type
            != EdgeType.JOB_ROLE_AGGREGATES_RECORD,
        )
    ))
    node_ids = {role_node.id}
    for edge in capability_edges:
        node_ids.add(edge.source_node_id)
        node_ids.add(edge.target_node_id)
    nodes = list(session.scalars(
        select(models.CapabilityGraphStagingNode)
        .where(models.CapabilityGraphStagingNode.id.in_(node_ids))
        .order_by(
            models.CapabilityGraphStagingNode.node_type,
            models.CapabilityGraphStagingNode.id,
        )
    ))
    return (
        [_serialize_capability_graph_node(n) for n in nodes],
        [_serialize_capability_graph_edge(e) for e in capability_edges],
    )


@router.get(
    "/record-assets/job-demand-role-graph",
    response_model=schemas.ApiResponse[dict],
)
def get_job_demand_role_graph_cross_dataset(
    request: Request,
    job_title: str = Query(
        ...,
        min_length=1,
        max_length=256,
        description=(
            "Required — case-insensitive substring match on JOB_ROLE "
            "`display_name` across every GENERATED `job_demand` staging "
            "build. §2.5.0 forbids trace fields (dataset_id / build_id) as "
            "primary business input; the response carries them under "
            "`builds[]` for Composer citation."
        ),
    ),
    session: Session = Depends(get_db),
):
    """B0.2 — cross-dataset role-graph lookup by `job_title`.

    Walks every GENERATED `build_type=job_demand` build, picks the
    JOB_ROLE node whose `display_name == job_title`, and returns the
    union of each match's capability subgraph. Multiple builds
    contributing the same role are merged into one `nodes` / `edges`
    list (deduped by node.id / edge.id — build IDs are UUIDs so
    collisions are safe to treat as duplicates from replay).

    Returns 404 when no build carries the exact `job_title`. The caller
    typically obtained the job_title from
    `/record-assets/job-demand-records` first, so a 404 here means the
    role staging pipeline hasn't run for any dataset containing that
    role yet.
    """
    # ILIKE substring match — mirrors A1b `major` semantics so a query
    # like `job_title=数据分析` picks up both "数据分析师" and
    # "高级数据分析师" without the caller having to know the exact
    # role naming convention.
    job_title_pattern = f"%{job_title}%"
    matches = list(session.execute(
        select(
            models.CapabilityGraphStagingBuild,
            models.CapabilityGraphStagingNode,
        )
        .join(
            models.CapabilityGraphStagingNode,
            models.CapabilityGraphStagingNode.build_id
            == models.CapabilityGraphStagingBuild.id,
        )
        .where(
            models.CapabilityGraphStagingBuild.build_type == BuildType.JOB_DEMAND,
            models.CapabilityGraphStagingBuild.status == BuildStatus.GENERATED,
            models.CapabilityGraphStagingNode.node_type == NodeType.JOB_ROLE,
            models.CapabilityGraphStagingNode.display_name.ilike(job_title_pattern),
        )
        .order_by(
            models.CapabilityGraphStagingBuild.created_at.desc(),
            models.CapabilityGraphStagingBuild.id.desc(),
        )
    ).all())
    if not matches:
        raise HTTPException(
            status_code=404,
            detail=f"no job_demand staging role found for job_title '{job_title}'",
        )

    # Resolve each build's dataset_id via normalized_ref (a dataset is
    # 1:1 with its normalized_ref; we look up by ref_id — see
    # `_seed_dataset` for the invariant).
    ref_ids = list({build.normalized_ref_id for build, _ in matches})
    datasets_by_ref = {
        ds.normalized_ref_id: ds
        for ds in session.scalars(
            select(models.JobDemandDataset)
            .where(models.JobDemandDataset.normalized_ref_id.in_(ref_ids))
        ).all()
    }

    build_summaries: list[dict[str, Any]] = []
    nodes_by_id: dict[str, dict[str, Any]] = {}
    edges_by_id: dict[str, dict[str, Any]] = {}

    for build, role_node in matches:
        node_rows, edge_rows = _load_job_demand_role_subgraph(
            session, build=build, role_node=role_node,
        )
        for node in node_rows:
            nodes_by_id.setdefault(node["id"], node)
        for edge in edge_rows:
            edges_by_id.setdefault(edge["id"], edge)
        ds = datasets_by_ref.get(build.normalized_ref_id)
        build_summaries.append({
            "build_id": build.id,
            "normalized_ref_id": build.normalized_ref_id,
            "dataset_id": ds.id if ds else None,
            "major_name": ds.major_name if ds else None,
            "industry_name": ds.industry_name if ds else None,
            "role_node_id": role_node.id,
        })

    return response(
        {
            "job_title": job_title,
            "match_count": len(build_summaries),
            "builds": build_summaries,
            "nodes": sorted(nodes_by_id.values(),
                             key=lambda n: (n.get("node_type", ""), n["id"])),
            "edges": sorted(edges_by_id.values(),
                             key=lambda e: e["id"]),
        },
        request,
    )


@router.get(
    "/record-assets/job-demand-datasets/{dataset_id}/role-graph",
    response_model=schemas.ApiResponse[dict],
)
def get_job_demand_role_graph(
    dataset_id: str,
    request: Request,
    job_title: str | None = Query(None, min_length=1),
    session: Session = Depends(get_db),
):
    """Read one selected role subgraph from the latest B8 staging build."""
    dataset = session.get(models.JobDemandDataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail=f"job_demand_dataset '{dataset_id}' not found",
        )

    build = session.scalar(
        select(models.CapabilityGraphStagingBuild)
        .where(
            models.CapabilityGraphStagingBuild.normalized_ref_id
            == dataset.normalized_ref_id,
            models.CapabilityGraphStagingBuild.build_type == BuildType.JOB_DEMAND,
            models.CapabilityGraphStagingBuild.status == BuildStatus.GENERATED,
        )
        .order_by(
            models.CapabilityGraphStagingBuild.created_at.desc(),
            models.CapabilityGraphStagingBuild.id.desc(),
        )
    )
    if build is None:
        raise HTTPException(
            status_code=404,
            detail="job_demand capability graph staging build not found",
        )

    role_nodes = list(session.scalars(
        select(models.CapabilityGraphStagingNode)
        .where(
            models.CapabilityGraphStagingNode.build_id == build.id,
            models.CapabilityGraphStagingNode.node_type == NodeType.JOB_ROLE,
        )
        .order_by(
            func.lower(models.CapabilityGraphStagingNode.display_name),
            models.CapabilityGraphStagingNode.display_name,
            models.CapabilityGraphStagingNode.id,
        )
    ))
    if not role_nodes:
        return response(
            {
                "dataset_id": dataset_id,
                "build_id": build.id,
                "selected_job_title": None,
                "roles": [],
                "nodes": [],
                "edges": [],
            },
            request,
        )

    role_ids = [node.id for node in role_nodes]
    record_counts = dict(session.execute(
        select(
            models.CapabilityGraphStagingEdge.source_node_id,
            func.count(models.CapabilityGraphStagingEdge.id),
        )
        .where(
            models.CapabilityGraphStagingEdge.build_id == build.id,
            models.CapabilityGraphStagingEdge.source_node_id.in_(role_ids),
            models.CapabilityGraphStagingEdge.edge_type
            == EdgeType.JOB_ROLE_AGGREGATES_RECORD,
        )
        .group_by(models.CapabilityGraphStagingEdge.source_node_id)
    ).all())
    roles = [
        {
            "job_title": node.display_name,
            "record_count": int(record_counts.get(node.id, 0)),
        }
        for node in role_nodes
    ]
    selected_title = job_title or roles[0]["job_title"]
    selected_role = next(
        (node for node in role_nodes if node.display_name == selected_title), None
    )
    if selected_role is None:
        raise HTTPException(
            status_code=404,
            detail=f"job title '{selected_title}' not found in staging build",
        )

    capability_edges = list(session.scalars(
        select(models.CapabilityGraphStagingEdge).where(
            models.CapabilityGraphStagingEdge.build_id == build.id,
            models.CapabilityGraphStagingEdge.source_node_id == selected_role.id,
            models.CapabilityGraphStagingEdge.edge_type
            != EdgeType.JOB_ROLE_AGGREGATES_RECORD,
        )
    ))
    node_ids = {selected_role.id}
    for edge in capability_edges:
        node_ids.add(edge.source_node_id)
        node_ids.add(edge.target_node_id)
    nodes = list(session.scalars(
        select(models.CapabilityGraphStagingNode)
        .where(models.CapabilityGraphStagingNode.id.in_(node_ids))
        .order_by(
            models.CapabilityGraphStagingNode.node_type,
            models.CapabilityGraphStagingNode.id,
        )
    ))
    return response(
        {
            "dataset_id": dataset_id,
            "build_id": build.id,
            "selected_job_title": selected_title,
            "roles": roles,
            "nodes": [_serialize_capability_graph_node(node) for node in nodes],
            "edges": [_serialize_capability_graph_edge(edge) for edge in capability_edges],
        },
        request,
    )


@router.get(
    "/record-assets/job-demand-records/{record_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_job_demand_record(
    record_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    record = session.get(models.JobDemandRecord, record_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"job_demand_record '{record_id}' not found",
        )
    return response(_serialize_job_demand_record(record), request)


@router.get(
    "/record-assets/job-demand-records/{record_id}/requirement-items",
    response_model=schemas.ListResponse[dict],
)
def list_requirement_items_for_record(
    record_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    if session.get(models.JobDemandRecord, record_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"job_demand_record '{record_id}' not found",
        )
    rows = list(
        session.scalars(
            select(models.JobDemandRequirementItem)
            .where(models.JobDemandRequirementItem.record_id == record_id)
            .order_by(models.JobDemandRequirementItem.created_at.asc())
        ).all()
    )
    return list_response(
        [_serialize_requirement_item(row) for row in rows],
        request,
        page=1,
        page_size=len(rows) or 1,
        total=len(rows),
    )


@router.get(
    "/record-assets/major-distribution-datasets",
    response_model=schemas.ListResponse[dict],
)
def list_major_distribution_datasets(
    request: Request,
    normalized_ref_id: str | None = Query(None, description="Exact match"),
    major_code: str | None = Query(None),
    major_name: str | None = Query(None, description="Substring match"),
    education_level: str | None = Query(None),
    year: int | None = Query(None),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    stmt = select(models.MajorDistributionDataset)
    count_stmt = select(func.count(models.MajorDistributionDataset.id))
    stmt = _apply_major_distribution_dataset_filters(
        stmt,
        normalized_ref_id=normalized_ref_id,
        major_code=major_code,
        major_name=major_name,
        education_level=education_level,
        year=year,
    )
    count_stmt = _apply_major_distribution_dataset_filters(
        count_stmt,
        normalized_ref_id=normalized_ref_id,
        major_code=major_code,
        major_name=major_name,
        education_level=education_level,
        year=year,
    )

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(models.MajorDistributionDataset.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_major_distribution_dataset(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/record-assets/major-distribution-datasets/{dataset_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_major_distribution_dataset(
    dataset_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    dataset = session.get(models.MajorDistributionDataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail=f"major_distribution_dataset '{dataset_id}' not found",
        )
    return response(_serialize_major_distribution_dataset(dataset), request)


@router.get(
    "/record-assets/major-distribution-datasets/{dataset_id}/records",
    response_model=schemas.ListResponse[dict],
)
def list_major_distribution_records_for_dataset(
    dataset_id: str,
    request: Request,
    year: int | None = Query(None),
    major_code: str | None = Query(None),
    major_name: str | None = Query(None, description="Substring match"),
    province_name: str | None = Query(None),
    education_level: str | None = Query(None),
    region_scope: str | None = Query(None),
    min_count: int | None = Query(None),
    max_count: int | None = Query(None),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    if session.get(models.MajorDistributionDataset, dataset_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"major_distribution_dataset '{dataset_id}' not found",
        )

    stmt = select(models.MajorDistributionRecord).where(
        models.MajorDistributionRecord.dataset_id == dataset_id
    )
    count_stmt = select(func.count(models.MajorDistributionRecord.id)).where(
        models.MajorDistributionRecord.dataset_id == dataset_id
    )
    stmt = _apply_major_distribution_record_filters(
        stmt,
        year=year,
        major_code=major_code,
        major_name=major_name,
        province_name=province_name,
        education_level=education_level,
        region_scope=region_scope,
        min_count=min_count,
        max_count=max_count,
    )
    count_stmt = _apply_major_distribution_record_filters(
        count_stmt,
        year=year,
        major_code=major_code,
        major_name=major_name,
        province_name=province_name,
        education_level=education_level,
        region_scope=region_scope,
        min_count=min_count,
        max_count=max_count,
    )

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(
                models.MajorDistributionRecord.year.desc(),
                models.MajorDistributionRecord.major_code.asc(),
                models.MajorDistributionRecord.province_name.asc(),
                models.MajorDistributionRecord.source_record_key.asc(),
            )
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_major_distribution_record(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/record-assets/major-distribution-records",
    response_model=schemas.ListResponse[dict],
)
def list_major_distribution_records(
    request: Request,
    normalized_ref_id: str | None = Query(None, description="Exact match"),
    year: int | None = Query(None),
    major_code: str | None = Query(None),
    major_name: str | None = Query(None, description="Substring match"),
    province_name: str | None = Query(None),
    education_level: str | None = Query(None),
    region_scope: str | None = Query(None),
    min_count: int | None = Query(None),
    max_count: int | None = Query(None),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    stmt = _apply_major_distribution_record_filters(
        select(models.MajorDistributionRecord),
        normalized_ref_id=normalized_ref_id,
        year=year,
        major_code=major_code,
        major_name=major_name,
        province_name=province_name,
        education_level=education_level,
        region_scope=region_scope,
        min_count=min_count,
        max_count=max_count,
    )
    count_stmt = _apply_major_distribution_record_filters(
        select(func.count(models.MajorDistributionRecord.id)),
        normalized_ref_id=normalized_ref_id,
        year=year,
        major_code=major_code,
        major_name=major_name,
        province_name=province_name,
        education_level=education_level,
        region_scope=region_scope,
        min_count=min_count,
        max_count=max_count,
    )

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(
                models.MajorDistributionRecord.year.desc(),
                models.MajorDistributionRecord.major_code.asc(),
                models.MajorDistributionRecord.province_name.asc(),
                models.MajorDistributionRecord.source_record_key.asc(),
            )
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_major_distribution_record(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/record-assets/major-distribution-records/{record_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_major_distribution_record(
    record_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    record = session.get(models.MajorDistributionRecord, record_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"major_distribution_record '{record_id}' not found",
        )
    return response(_serialize_major_distribution_record(record), request)


@router.patch(
    "/record-assets/major-distribution-records/{record_id}",
    response_model=schemas.ApiResponse[dict],
)
def update_major_distribution_record(
    record_id: str,
    payload: MajorDistributionRecordPatch,
    request: Request,
    operator: models.UserAccount = Depends(require_user),
    session: Session = Depends(get_db),
):
    record = session.get(models.MajorDistributionRecord, record_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"major_distribution_record '{record_id}' not found",
        )
    dataset = session.get(models.MajorDistributionDataset, record.dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=409,
            detail=f"major_distribution_dataset '{record.dataset_id}' not found",
        )

    before = _major_distribution_record_snapshot(record)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(record, field, value)
    if "year" in updates:
        record.year_text = f"{record.year}年"

    _recompute_major_distribution_dataset_summary(session, dataset)
    after = _major_distribution_record_snapshot(record)
    write_audit(
        session,
        AuditEventType.MAJOR_DISTRIBUTION_RECORD_UPDATED,
        target_type="major_distribution_record",
        target_id=record.id,
        trace_id=str(getattr(request.state, "trace_id", "")),
        actor_type="user",
        actor_id=operator.id,
        summary={
            "dataset_id": dataset.id,
            "normalized_ref_id": record.normalized_ref_id,
            "before": before,
            "after": after,
            "dataset_summary": {
                "record_count": dataset.record_count,
                "province_count": dataset.province_count,
                "year_min": dataset.year_min,
                "year_max": dataset.year_max,
            },
        },
    )
    session.commit()
    session.refresh(record)
    return response(_serialize_major_distribution_record(record), request)


@router.delete(
    "/record-assets/major-distribution-records/{record_id}",
    response_model=schemas.ApiResponse[dict],
)
def delete_major_distribution_record(
    record_id: str,
    request: Request,
    operator: models.UserAccount = Depends(require_user),
    session: Session = Depends(get_db),
):
    record = session.get(models.MajorDistributionRecord, record_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"major_distribution_record '{record_id}' not found",
        )
    dataset = session.get(models.MajorDistributionDataset, record.dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=409,
            detail=f"major_distribution_dataset '{record.dataset_id}' not found",
        )

    snapshot = _serialize_major_distribution_record(record)
    session.delete(record)
    session.flush()
    _recompute_major_distribution_dataset_summary(session, dataset)
    write_audit(
        session,
        AuditEventType.MAJOR_DISTRIBUTION_RECORD_DELETED,
        target_type="major_distribution_record",
        target_id=record_id,
        trace_id=str(getattr(request.state, "trace_id", "")),
        actor_type="user",
        actor_id=operator.id,
        summary={
            "dataset_id": dataset.id,
            "normalized_ref_id": snapshot["normalized_ref_id"],
            "deleted_record": snapshot,
            "dataset_summary": {
                "record_count": dataset.record_count,
                "province_count": dataset.province_count,
                "year_min": dataset.year_min,
                "year_max": dataset.year_max,
            },
        },
    )
    session.commit()
    return response({"id": record_id, "deleted": True}, request)



def _serialize_analysis(analysis: models.OccupationalAbilityAnalysis) -> dict:
    return {
        "id": analysis.id,
        "normalized_ref_id": analysis.normalized_ref_id,
        "asset_version_id": analysis.asset_version_id,
        "profile_id": analysis.profile_id,
        "analysis_model": analysis.analysis_model,
        "major_name": analysis.major_name,
        "major_direction": analysis.major_direction,
        "source_job_demand_dataset_id": analysis.source_job_demand_dataset_id,
        "task_count": analysis.task_count,
        "work_content_count": analysis.work_content_count,
        "ability_item_count": analysis.ability_item_count,
        "schema_version": analysis.schema_version,
        "quality_summary": analysis.quality_summary or {},
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "updated_at": analysis.updated_at.isoformat() if analysis.updated_at else None,
    }


def _serialize_profile(profile: models.AbilityAnalysisProfile) -> dict:
    return {
        "id": profile.id,
        "model_code": profile.model_code,
        "model_name": profile.model_name,
        "schema_version": profile.schema_version,
        "category_schema": profile.category_schema or [],
        "code_pattern": profile.code_pattern or {},
        "is_active": profile.is_active,
        "is_builtin": profile.is_builtin,
    }


def _serialize_work_content(wc: models.OccupationalWorkContent) -> dict:
    return {
        "id": wc.id,
        "content_code": wc.content_code,
        "content_name": wc.content_name,
        "content_description": wc.content_description,
        "display_order": wc.display_order,
        "trace": wc.trace or {},
    }


def _serialize_task(
    task: models.OccupationalWorkTask,
    work_contents: list[models.OccupationalWorkContent],
) -> dict:
    return {
        "id": task.id,
        "task_code": task.task_code,
        "task_name": task.task_name,
        "task_description": task.task_description,
        "task_description_structured": task.task_description_structured or {},
        "display_order": task.display_order,
        "trace": task.trace or {},
        "work_contents": [_serialize_work_content(wc) for wc in work_contents],
    }


def _serialize_ability_item(item: models.OccupationalAbilityItem) -> dict:
    return {
        "id": item.id,
        "analysis_id": item.analysis_id,
        "task_id": item.task_id,
        "work_content_id": item.work_content_id,
        "ability_code": item.ability_code,
        "ability_major_category_code": item.ability_major_category_code,
        "ability_major_category_name": item.ability_major_category_name,
        "ability_sequence": item.ability_sequence,
        "ability_content": item.ability_content,
        "normalized_terms": item.normalized_terms or {},
        "confidence": float(item.confidence) if item.confidence is not None else None,
        "quality_flags": item.quality_flags or {},
        "trace": item.trace or {},
    }


def _get_analysis_or_404(
    session: Session, analysis_id: str
) -> models.OccupationalAbilityAnalysis:
    analysis = session.get(models.OccupationalAbilityAnalysis, analysis_id)
    if analysis is None:
        raise HTTPException(
            status_code=404,
            detail=f"ability_analysis '{analysis_id}' not found",
        )
    return analysis


_ABILITY_ANALYSES_INCLUDE_ALLOWED: frozenset[str] = frozenset({
    "tasks",
    "ability_items",
})


@router.get(
    "/record-assets/ability-analyses",
    response_model=schemas.ListResponse[dict],
)
def list_ability_analyses(
    request: Request,
    normalized_ref_id: str | None = Query(None, max_length=36),
    profile_id: str | None = Query(None, max_length=36),
    major_name: str | None = Query(
        None,
        max_length=256,
        description=(
            "专业名称过滤，走 ILIKE substring 匹配（自 v2.0.1 起从 exact 升级为 substring，"
            "配合 §1.13 归一化的 build.major_name 命中父子专业）"
        ),
    ),
    include: list[str] | None = Query(
        None,
        description=(
            "Batch B0.3 — inline nested payloads to avoid dispatcher "
            "fan-out. Allowed values: `tasks`, `ability_items`. When "
            "present, each analysis row carries the corresponding array. "
            "Unknown values return 422 so typos don't silently no-op."
        ),
    ),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    if include:
        unknown = sorted(set(include) - _ABILITY_ANALYSES_INCLUDE_ALLOWED)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "unknown_include_value",
                    "unknown": unknown,
                    "allowed": sorted(_ABILITY_ANALYSES_INCLUDE_ALLOWED),
                },
            )
    include_tasks = bool(include and "tasks" in include)
    include_ability_items = bool(include and "ability_items" in include)

    stmt = select(models.OccupationalAbilityAnalysis)
    count_stmt = select(func.count(models.OccupationalAbilityAnalysis.id))
    if normalized_ref_id is not None:
        stmt = stmt.where(
            models.OccupationalAbilityAnalysis.normalized_ref_id == normalized_ref_id
        )
        count_stmt = count_stmt.where(
            models.OccupationalAbilityAnalysis.normalized_ref_id == normalized_ref_id
        )
    if profile_id is not None:
        stmt = stmt.where(models.OccupationalAbilityAnalysis.profile_id == profile_id)
        count_stmt = count_stmt.where(
            models.OccupationalAbilityAnalysis.profile_id == profile_id
        )
    if major_name is not None:
        pattern = f"%{major_name}%"
        stmt = stmt.where(models.OccupationalAbilityAnalysis.major_name.ilike(pattern))
        count_stmt = count_stmt.where(
            models.OccupationalAbilityAnalysis.major_name.ilike(pattern)
        )

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(models.OccupationalAbilityAnalysis.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )

    tasks_by_analysis: dict[str, list[dict]] = {}
    items_by_analysis: dict[str, list[dict]] = {}
    if rows and (include_tasks or include_ability_items):
        analysis_ids = [row.id for row in rows]
        if include_tasks:
            tasks_by_analysis = _load_tasks_for_analyses(session, analysis_ids)
        if include_ability_items:
            items_by_analysis = _load_ability_items_for_analyses(
                session, analysis_ids,
            )

    serialized: list[dict] = []
    for row in rows:
        payload = _serialize_analysis(row)
        if include_tasks:
            payload["tasks"] = tasks_by_analysis.get(row.id, [])
        if include_ability_items:
            payload["ability_items"] = items_by_analysis.get(row.id, [])
        serialized.append(payload)

    return list_response(
        serialized,
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


def _load_tasks_for_analyses(
    session: Session, analysis_ids: list[str],
) -> dict[str, list[dict]]:
    """Batch-load tasks + their work_contents for many analyses at once.

    Reuses the composition logic from `get_ability_analysis_tasks` but
    across N analyses in one round-trip — critical for `include=tasks`
    on a page of 20 analyses (avoids 20 separate task queries).
    """
    tasks = list(session.scalars(
        select(models.OccupationalWorkTask)
        .where(models.OccupationalWorkTask.analysis_id.in_(analysis_ids))
        .order_by(
            models.OccupationalWorkTask.analysis_id,
            models.OccupationalWorkTask.display_order,
            models.OccupationalWorkTask.task_code,
        )
    ))
    task_ids = [task.id for task in tasks]
    work_contents = []
    if task_ids:
        work_contents = list(session.scalars(
            select(models.OccupationalWorkContent)
            .where(models.OccupationalWorkContent.task_id.in_(task_ids))
            .order_by(
                models.OccupationalWorkContent.task_id,
                models.OccupationalWorkContent.display_order,
                models.OccupationalWorkContent.content_code,
            )
        ))
    by_task: dict[str, list[models.OccupationalWorkContent]] = {}
    for wc in work_contents:
        by_task.setdefault(wc.task_id, []).append(wc)

    out: dict[str, list[dict]] = {}
    for task in tasks:
        out.setdefault(task.analysis_id, []).append(
            _serialize_task(task, by_task.get(task.id, [])),
        )
    return out


def _load_ability_items_for_analyses(
    session: Session, analysis_ids: list[str],
) -> dict[str, list[dict]]:
    items = list(session.scalars(
        select(models.OccupationalAbilityItem)
        .where(models.OccupationalAbilityItem.analysis_id.in_(analysis_ids))
        .order_by(
            models.OccupationalAbilityItem.analysis_id,
            models.OccupationalAbilityItem.ability_sequence,
            models.OccupationalAbilityItem.ability_code,
        )
    ))
    out: dict[str, list[dict]] = {}
    for item in items:
        out.setdefault(item.analysis_id, []).append(_serialize_ability_item(item))
    return out


@router.get(
    "/record-assets/ability-analyses/{analysis_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_ability_analysis(
    analysis_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    analysis = _get_analysis_or_404(session, analysis_id)
    profile = session.get(models.AbilityAnalysisProfile, analysis.profile_id)
    payload = _serialize_analysis(analysis)
    payload["profile"] = _serialize_profile(profile) if profile is not None else None
    return response(payload, request)


@router.get(
    "/record-assets/ability-analyses/{analysis_id}/tasks",
    response_model=schemas.ListResponse[dict],
)
def get_ability_analysis_tasks(
    analysis_id: str,
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    _get_analysis_or_404(session, analysis_id)
    tasks = list(
        session.scalars(
            select(models.OccupationalWorkTask)
            .where(models.OccupationalWorkTask.analysis_id == analysis_id)
            .order_by(
                models.OccupationalWorkTask.display_order,
                models.OccupationalWorkTask.task_code,
            )
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    task_ids = [task.id for task in tasks]
    work_contents = []
    if task_ids:
        work_contents = list(
            session.scalars(
                select(models.OccupationalWorkContent)
                .where(models.OccupationalWorkContent.task_id.in_(task_ids))
                .order_by(
                    models.OccupationalWorkContent.task_id,
                    models.OccupationalWorkContent.display_order,
                    models.OccupationalWorkContent.content_code,
                )
            ).all()
        )
    by_task: dict[str, list[models.OccupationalWorkContent]] = {}
    for wc in work_contents:
        by_task.setdefault(wc.task_id, []).append(wc)
    total = session.scalar(
        select(func.count(models.OccupationalWorkTask.id)).where(
            models.OccupationalWorkTask.analysis_id == analysis_id
        )
    ) or 0
    return list_response(
        [_serialize_task(task, by_task.get(task.id, [])) for task in tasks],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/record-assets/ability-analyses/{analysis_id}/ability-items",
    response_model=schemas.ListResponse[dict],
)
def list_ability_items(
    analysis_id: str,
    request: Request,
    category: str | None = Query(None, max_length=16),
    task_code: str | None = Query(None, max_length=64),
    work_content_code: str | None = Query(None, max_length=64),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    _get_analysis_or_404(session, analysis_id)
    stmt = select(models.OccupationalAbilityItem).where(
        models.OccupationalAbilityItem.analysis_id == analysis_id
    )
    count_stmt = select(func.count(models.OccupationalAbilityItem.id)).where(
        models.OccupationalAbilityItem.analysis_id == analysis_id
    )
    if category is not None:
        stmt = stmt.where(
            models.OccupationalAbilityItem.ability_major_category_code == category
        )
        count_stmt = count_stmt.where(
            models.OccupationalAbilityItem.ability_major_category_code == category
        )
    if task_code is not None:
        task_id = session.scalar(
            select(models.OccupationalWorkTask.id).where(
                models.OccupationalWorkTask.analysis_id == analysis_id,
                models.OccupationalWorkTask.task_code == task_code,
            )
        )
        if task_id is None:
            return list_response(
                [], request,
                page=pagination.page, page_size=pagination.page_size, total=0,
            )
        stmt = stmt.where(models.OccupationalAbilityItem.task_id == task_id)
        count_stmt = count_stmt.where(
            models.OccupationalAbilityItem.task_id == task_id
        )
    if work_content_code is not None:
        wc_id = session.scalar(
            select(models.OccupationalWorkContent.id).where(
                models.OccupationalWorkContent.analysis_id == analysis_id,
                models.OccupationalWorkContent.content_code == work_content_code,
            )
        )
        if wc_id is None:
            return list_response(
                [], request,
                page=pagination.page, page_size=pagination.page_size, total=0,
            )
        stmt = stmt.where(models.OccupationalAbilityItem.work_content_id == wc_id)
        count_stmt = count_stmt.where(
            models.OccupationalAbilityItem.work_content_id == wc_id
        )

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(models.OccupationalAbilityItem.ability_code)
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_ability_item(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )

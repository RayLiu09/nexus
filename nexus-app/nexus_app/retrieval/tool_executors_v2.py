"""B6/B7 (§10 阶段 B) — Real tool executors for the v2 dispatcher.

One in-process executor per tool registered in
``config/query_router_tools.json``. Each executor runs the underlying
query DIRECTLY against nexus-app SQLAlchemy models — the mirror-image
of the endpoint in ``nexus-api`` — so B6/B7 doesn't take an HTTP hop
back to itself.

Design contract carried in:

* Executor signature is fixed by
  ``nexus_app.retrieval.dispatcher_v2.ToolExecutor`` — every executor
  accepts ``session`` / ``arguments`` / ``tool_call_id`` /
  ``chart_registry`` and returns a JSON-serialisable dict. Composer
  reads the dict as free-form context per the compose_v2 prompt.
* Chart-producing executors register their payload on the shared
  ``ChartRegistry`` and include the returned ``chart_id`` in their
  response so Composer's ``[[CHART:xxx]]`` placeholders can reference
  it (§7.3).
* Executors return **raw** business data — permission filtering,
  response envelopes, pagination beyond the tool's semantics belong to
  the endpoint layer, not the executor. The dispatcher hands the raw
  dict to Composer which is the sole consumer.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from nexus_app import models
from nexus_app.capability_graph.whitelists import (
    BuildStatus,
    BuildType,
    EdgeType,
    NodeType,
)
from nexus_app.evidence_graph.service import KnowledgeGraphBuildStatus
from nexus_app.index.pgvector_search import PgvectorSearchAdapter
from nexus_app.retrieval.chart_adapter import (
    ChartRegistry,
    capability_graph_to_chart,
    knowledge_graph_to_chart,
)
from nexus_app.retrieval.dispatcher_v2 import ToolExecutor, ToolExecutorRegistry
from nexus_app.retrieval.semantic_context import (
    assemble_semantic_context,
    resolve_semantic_scope,
    weak_evidence_chunk_ids,
)

logger = logging.getLogger(__name__)

_AUTO_OUTLINE_KNOWLEDGE_TYPES = frozenset({
    "course_textbook",
    "practical_training_kb",
})

_MAJOR_INFORMATION_UNITS = frozenset({
    "basic_identity",
    "admission_requirements",
    "basic_study_duration",
    "occupation_oriented",
    "training_goal",
    "training_specification",
    "curriculum",
    "public_basic_courses",
    "professional_basic_courses",
    "professional_core_courses",
    "professional_extension_courses",
})

_MAJOR_INFORMATION_CHUNK_TYPES = (
    "major_profile_knowledge",
    "course_standard_authoring_process",
)

_UNIT_SECTION_TERMS: dict[str, tuple[str, ...]] = {
    "basic_identity": ("专业名称", "专业代码"),
    "admission_requirements": ("入学基本要求", "入学要求"),
    "basic_study_duration": ("基本修业年限", "修业年限"),
    "occupation_oriented": ("职业面向", "面向职业", "就业面向"),
    "training_goal": ("培养目标", "培养目标定位"),
    "training_specification": ("培养规格",),
    "curriculum": ("课程设置", "专业课程", "实习实训"),
    "public_basic_courses": ("公共基础课程",),
    "professional_basic_courses": ("专业基础课程",),
    "professional_core_courses": ("专业核心课程",),
    "professional_extension_courses": ("专业拓展课程",),
}


# ---------------------------------------------------------------------------
# Tool: internal.search_chunks_by_semantic
# ---------------------------------------------------------------------------


def make_search_chunks_executor(adapter: PgvectorSearchAdapter) -> ToolExecutor:
    """Wraps ``PgvectorSearchAdapter.search`` for scenario_1 / 3 / 4 use.

    Accepts the tool's parameter set: ``query`` (required), ``kb``
    (knowledge_type_code, optional/const per scenario), ``top_k``
    (default 8), ``similarity_threshold`` (default 0.7),
    ``expand_queries`` (default False — the adapter defaults it too),
    ``outline_node`` is retained for contract compatibility.  First-stage
    retrieval remains vector based; after it returns, NEXUS-owned outline
    relations provide a bounded answer context for section/task questions.
    """

    def _run(
        *,
        session: Session,
        arguments: dict[str, Any],
        tool_call_id: str,
        chart_registry: ChartRegistry,
    ) -> dict[str, Any]:
        requested_kb = arguments.get("kb")
        top_k = int(arguments.get("top_k", 8))
        # Default threshold dropped from 0.7 → 0.5 for wider recall on
        # knowledge/concept queries; scenario_1's tool schema had 0.7
        # baked in (const kb) so this only affects scenario_3/4 which
        # don't set a schema default at the tool level.
        similarity_threshold = float(arguments.get("similarity_threshold", 0.5))
        expand_queries = bool(arguments.get("expand_queries", False))

        scope = resolve_semantic_scope(
            session,
            query=arguments["query"],
            requested_outline_node=arguments.get("outline_node"),
            # Industry reports and policy assets do not use textbook/task
            # outlines. Their tool schemas always provide their own KB code;
            # only textbook queries (or scenario_4's omitted KB) may auto-scope.
            allow_auto_scope=(
                requested_kb is None
                or requested_kb in _AUTO_OUTLINE_KNOWLEDGE_TYPES
            ),
        )
        scope_chunk_ids = list(scope.chunk_ids) if scope.applied else None
        hits = adapter.search(
            session,
            query=arguments["query"],
            knowledge_type_code=requested_kb,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            expand_queries=expand_queries,
            chunk_ids=scope_chunk_ids,
        )

        # Cross-kb fallback (§4.2.5): if the LLM picked a specific kb
        # and it returned nothing, retry with kb=None so we cover the
        # entire semantic index before the router declares "no hits".
        # This is the recall-side analogue of the intent-classifier
        # unknown-fallback path — a wrong kb guess shouldn't sink an
        # otherwise-answerable knowledge query.  Records the widen for
        # Composer / audit awareness.
        kb_widened = False
        if not hits and requested_kb:
            widened = adapter.search(
                session,
                query=arguments["query"],
                knowledge_type_code=None,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
                expand_queries=expand_queries,
                chunk_ids=scope_chunk_ids,
            )
            if widened:
                hits = widened
                kb_widened = True

        # An automatically resolved scope is an optimization, not an access
        # boundary. If it has no vector evidence, fail open to broad recall so
        # a title mismatch or legacy relation gap cannot hide valid knowledge.
        # A caller-selected outline node is mandatory and never escapes scope.
        scope_fallback = False
        if not hits and scope.applied and not scope.mandatory:
            scope_fallback = True
            hits = adapter.search(
                session,
                query=arguments["query"],
                knowledge_type_code=requested_kb,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
                expand_queries=expand_queries,
            )
            if not hits and requested_kb:
                widened = adapter.search(
                    session,
                    query=arguments["query"],
                    knowledge_type_code=None,
                    top_k=top_k,
                    similarity_threshold=similarity_threshold,
                    expand_queries=expand_queries,
                )
                if widened:
                    hits = widened
                    kb_widened = True

        contexts = assemble_semantic_context(
            session,
            query=arguments["query"],
            hits=hits,
        )
        return {
            "hits": hits,
            "query": arguments["query"],
            "kb": requested_kb,
            "kb_widened_to_all": kb_widened,
            "outline_node": arguments.get("outline_node"),
            "scope": scope.to_api_dict(fallback_to_unscoped=scope_fallback),
            # Original vector hits remain the retrieval evidence. Contexts
            # only expand those hits through NEXUS-owned outline relations.
            "answer_contexts": contexts,
            "weak_evidence_chunk_ids": weak_evidence_chunk_ids(session, hits),
        }

    return _run


# ---------------------------------------------------------------------------
# Tool: internal.query_major_information
# ---------------------------------------------------------------------------


def query_major_information(
    *,
    session: Session,
    arguments: dict[str, Any],
    tool_call_id: str,
    chart_registry: ChartRegistry,
) -> dict[str, Any]:
    """Read professional facts by requested unit, with chunk-only fallback.

    ``MajorProfile`` is the normalized read model for professional
    introductions.  Users do not need to choose a source asset, so a field
    that is absent from that read model is filled from the evidence chunks of
    either professional introductions or teaching standards.  A teaching
    standard is deliberately *not* mapped to textbook outline nodes here.
    """
    major_name = _clean_text(arguments.get("major_name"))
    major_code = _clean_text(arguments.get("major_code"))
    requested_units = _normalise_major_information_units(arguments.get("units"))

    profile = _find_major_profile(
        session, major_name=major_name, major_code=major_code,
    )
    resolved_name = major_name or (profile.major_name if profile else None)
    resolved_code = major_code or (profile.major_code if profile else None)

    units: dict[str, dict[str, Any]] = {}
    missing_units: list[str] = []
    for unit in requested_units:
        structured = _structured_major_information_unit(profile, unit)
        if structured is not None:
            units[unit] = {
                "status": "structured",
                "value": structured,
                "source": _major_profile_source(profile),
                "evidence": _structured_major_evidence(profile, unit),
            }
        else:
            missing_units.append(unit)

    # A missing unit is not evidence that a professional fact is absent.  It
    # is a signal to search only the two professional knowledge collections
    # for that unit's section evidence.
    for unit in missing_units:
        chunks = _find_major_information_chunks(
            session,
            major_name=resolved_name,
            major_code=resolved_code,
            unit=unit,
        )
        units[unit] = {
            "status": "chunk_fallback" if chunks else "unavailable",
            "value": [item["content"] for item in chunks] if chunks else None,
            "source": "knowledge_chunk",
            "evidence": chunks,
        }

    return {
        "found_profile": profile is not None,
        "major_name": resolved_name,
        "major_code": resolved_code,
        "requested_units": requested_units,
        "units": units,
        "missing_structured_units": missing_units,
        "chunk_fallback_knowledge_types": list(_MAJOR_INFORMATION_CHUNK_TYPES),
    }


def _normalise_major_information_units(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    units: list[str] = []
    for raw in value:
        if not isinstance(raw, str) or raw not in _MAJOR_INFORMATION_UNITS:
            continue
        if raw not in seen:
            seen.add(raw)
            units.append(raw)
    return units


def _find_major_profile(
    session: Session,
    *,
    major_name: str | None,
    major_code: str | None,
) -> models.MajorProfile | None:
    stmt = select(models.MajorProfile).options(
        selectinload(models.MajorProfile.occupations),
        selectinload(models.MajorProfile.abilities),
        selectinload(models.MajorProfile.courses),
    )
    if major_code:
        profile = session.scalars(
            stmt.where(models.MajorProfile.major_code == major_code)
            .order_by(models.MajorProfile.updated_at.desc())
        ).first()
        if profile is not None:
            return profile
    if major_name:
        return session.scalars(
            stmt.where(models.MajorProfile.major_name.ilike(f"%{major_name}%"))
            .order_by(models.MajorProfile.updated_at.desc())
        ).first()
    return None


def _structured_major_information_unit(
    profile: models.MajorProfile | None,
    unit: str,
) -> Any | None:
    if profile is None:
        return None
    if unit == "basic_identity":
        return {
            "major_name": profile.major_name,
            "major_code": profile.major_code,
            "education_level": profile.education_level,
        }
    if unit == "basic_study_duration":
        return profile.basic_study_duration or None
    if unit == "occupation_oriented":
        items = [
            {
                "text": item.text,
                "normalized_name": item.normalized_name,
                "occupation_type": item.occupation_type,
            }
            for item in sorted(profile.occupations, key=lambda item: item.item_index)
            if item.text.strip()
        ]
        return items or None
    if unit == "training_goal":
        return profile.training_goal or None
    if unit in {
        "curriculum",
        "public_basic_courses",
        "professional_basic_courses",
        "professional_core_courses",
        "professional_extension_courses",
    }:
        courses = [
            {"text": item.text, "course_group": item.course_group, "course_type": item.course_type}
            for item in sorted(profile.courses, key=lambda item: (item.course_group, item.item_index))
            if item.text.strip() and _course_matches_unit(item.course_group, unit)
        ]
        return courses or None
    return None


def _course_matches_unit(course_group: str, unit: str) -> bool:
    if unit == "curriculum":
        return True
    terms = _UNIT_SECTION_TERMS[unit]
    normalized = course_group.replace(" ", "")
    return any(term.replace(" ", "") in normalized for term in terms)


def _major_profile_source(profile: models.MajorProfile) -> dict[str, Any]:
    return {
        "source": "major_profile",
        "profile_id": profile.id,
        "normalized_ref_id": profile.normalized_ref_id,
        "asset_version_id": profile.asset_version_id,
    }


def _structured_major_evidence(
    profile: models.MajorProfile,
    unit: str,
) -> list[dict[str, Any]]:
    if unit == "occupation_oriented":
        return [
            {
                "normalized_ref_id": item.normalized_ref_id,
                "locator": item.locator or {},
                "evidence_block_ids": item.evidence_block_ids or [],
                "source_text": item.source_text,
            }
            for item in sorted(profile.occupations, key=lambda item: item.item_index)
        ]
    if unit in {
        "curriculum", "public_basic_courses", "professional_basic_courses",
        "professional_core_courses", "professional_extension_courses",
    }:
        return [
            {
                "normalized_ref_id": item.normalized_ref_id,
                "locator": item.locator or {},
                "evidence_block_ids": item.evidence_block_ids or [],
                "source_text": item.source_text,
            }
            for item in profile.courses
            if _course_matches_unit(item.course_group, unit)
        ]
    evidence = profile.evidence or {}
    return [{
        "normalized_ref_id": profile.normalized_ref_id,
        "locator": evidence.get("locator", {}),
        "evidence_block_ids": evidence.get("source_block_ids", []),
    }]


def _find_major_information_chunks(
    session: Session,
    *,
    major_name: str | None,
    major_code: str | None,
    unit: str,
) -> list[dict[str, Any]]:
    if not major_name and not major_code:
        return []
    stmt = (
        select(models.KnowledgeChunk)
        .outerjoin(
            models.NormalizedAssetRef,
            models.NormalizedAssetRef.id == models.KnowledgeChunk.normalized_ref_id,
        )
        .where(models.KnowledgeChunk.knowledge_type_code.in_(_MAJOR_INFORMATION_CHUNK_TYPES))
    )
    # Bound candidates by a professional entity in either asset title or
    # chunk body.  Heading matching happens in Python because historical
    # heading paths are stored in locator or metadata with different shapes.
    entity_conditions = []
    if major_name:
        entity_conditions.extend((
            models.NormalizedAssetRef.title.ilike(f"%{major_name}%"),
            models.KnowledgeChunk.content.ilike(f"%{major_name}%"),
        ))
    if major_code:
        entity_conditions.extend((
            models.NormalizedAssetRef.title.ilike(f"%{major_code}%"),
            models.KnowledgeChunk.content.ilike(f"%{major_code}%"),
        ))
    if entity_conditions:
        from sqlalchemy import or_
        stmt = stmt.where(or_(*entity_conditions))

    terms = _UNIT_SECTION_TERMS[unit]
    ranked: list[tuple[int, models.KnowledgeChunk]] = []
    for chunk in session.scalars(stmt.order_by(models.KnowledgeChunk.chunk_index)).all():
        score = _major_chunk_unit_score(chunk, terms)
        if score:
            ranked.append((score, chunk))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].chunk_index, pair[1].id))
    return [_serialise_major_chunk(chunk) for _, chunk in ranked[:8]]


def _major_chunk_unit_score(
    chunk: models.KnowledgeChunk,
    terms: tuple[str, ...],
) -> int:
    headings = _chunk_heading_text(chunk)
    content_start = chunk.content[:500]
    heading_hits = sum(1 for term in terms if term in headings)
    content_hits = sum(1 for term in terms if term in content_start)
    return heading_hits * 100 + content_hits * 10


def _chunk_heading_text(chunk: models.KnowledgeChunk) -> str:
    values: list[str] = []
    for payload in (chunk.locator or {}, chunk.chunk_metadata or {}):
        path = payload.get("heading_path")
        if not isinstance(path, list):
            continue
        for item in path:
            if isinstance(item, dict) and isinstance(item.get("title"), str):
                values.append(item["title"])
            elif isinstance(item, str):
                values.append(item)
    return "\n".join(values)


def _serialise_major_chunk(chunk: models.KnowledgeChunk) -> dict[str, Any]:
    return {
        "chunk_id": chunk.id,
        "normalized_ref_id": chunk.normalized_ref_id,
        "knowledge_type_code": chunk.knowledge_type_code,
        "content": chunk.content,
        "locator": chunk.locator or {},
        "heading_path": _chunk_heading_text(chunk),
    }


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


# ---------------------------------------------------------------------------
# Tool: internal.query_capability_graph_by_major
# ---------------------------------------------------------------------------


def query_capability_graph_by_major(
    *,
    session: Session,
    arguments: dict[str, Any],
    tool_call_id: str,
    chart_registry: ChartRegistry,
) -> dict[str, Any]:
    """A1f by-major lookup — used in scenario_2 (ability_analysis) AND
    scenario_3 (teaching_standard) via the ``build_type`` const.

    Returns nodes / edges of the latest GENERATED build for the major,
    and registers a chart on the shared registry so Composer can embed
    it via a ``[[CHART:xxx]]`` placeholder.
    """
    build_type = arguments["build_type"]
    major_name = arguments.get("major_name")
    major_code = arguments.get("major_code")
    node_type = arguments.get("node_type")

    stmt = select(models.CapabilityGraphStagingBuild).where(
        models.CapabilityGraphStagingBuild.build_type == build_type,
    )
    if major_code:
        stmt = stmt.where(
            models.CapabilityGraphStagingBuild.major_code == major_code,
        )
    if major_name:
        stmt = stmt.where(
            models.CapabilityGraphStagingBuild.major_name.ilike(
                f"%{major_name}%",
            ),
        )
    # Prefer the most recent build so major updates propagate on the
    # next successful build cycle; SQLite lacks NULLS LAST so we rely
    # on created_at ordering.
    stmt = stmt.order_by(
        models.CapabilityGraphStagingBuild.created_at.desc(),
    )
    build = session.scalars(stmt).first()
    if build is None:
        return {
            "found": False,
            "build_type": build_type,
            "major_name": major_name,
            "major_code": major_code,
        }

    node_stmt = select(models.CapabilityGraphStagingNode).where(
        models.CapabilityGraphStagingNode.build_id == build.id,
    )
    if node_type:
        node_stmt = node_stmt.where(
            models.CapabilityGraphStagingNode.node_type == node_type,
        )
    nodes = list(session.scalars(node_stmt))
    edges = list(session.scalars(
        select(models.CapabilityGraphStagingEdge).where(
            models.CapabilityGraphStagingEdge.build_id == build.id,
        )
    ))

    chart_payload = capability_graph_to_chart(
        nodes=nodes,
        edges=edges,
        title=(
            f"{build.major_name or major_name or ''} "
            f"{build_type} 能力图谱"
        ).strip(),
        source_ref=build.normalized_ref_id,
    )
    chart_id = chart_registry.register(
        tool_call_id=tool_call_id, payload=chart_payload,
    )
    graph_nodes, graph_edges = _serialise_capability_graph_facts(nodes, edges)

    return {
        "found": True,
        "build_id": build.id,
        "build_type": build.build_type,
        "major_name": build.major_name,
        "major_code": build.major_code,
        "normalized_ref_id": build.normalized_ref_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "graph_nodes": graph_nodes,
        "graph_edges": graph_edges,
        "chart_id": chart_id,
    }


# ---------------------------------------------------------------------------
# Tool: internal.get_evidence_graph_by_ref
# ---------------------------------------------------------------------------


def get_evidence_graph_by_ref(
    *,
    session: Session,
    arguments: dict[str, Any],
    tool_call_id: str,
    chart_registry: ChartRegistry,
) -> dict[str, Any]:
    normalized_ref_id = arguments["normalized_ref_id"]
    stmt = select(models.KnowledgeGraphBuild).where(
        models.KnowledgeGraphBuild.normalized_ref_id == normalized_ref_id,
        models.KnowledgeGraphBuild.status
        == KnowledgeGraphBuildStatus.SUCCEEDED,
    ).order_by(models.KnowledgeGraphBuild.created_at.desc())
    build = session.scalars(stmt).first()
    if build is None:
        return {
            "found": False,
            "normalized_ref_id": normalized_ref_id,
        }

    nodes = list(session.scalars(
        select(models.KnowledgeGraphNode).where(
            models.KnowledgeGraphNode.build_id == build.id,
        )
    ))
    edges = list(session.scalars(
        select(models.KnowledgeGraphEdge).where(
            models.KnowledgeGraphEdge.build_id == build.id,
        )
    ))

    chart_payload = knowledge_graph_to_chart(
        nodes=nodes,
        edges=edges,
        title=f"章节知识图谱 (ref {normalized_ref_id[:8]})",
        source_ref=normalized_ref_id,
    )
    chart_id = chart_registry.register(
        tool_call_id=tool_call_id, payload=chart_payload,
    )

    return {
        "found": True,
        "build_id": build.id,
        "normalized_ref_id": normalized_ref_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "chart_id": chart_id,
    }


# ---------------------------------------------------------------------------
# Tool: internal.query_job_demand
# ---------------------------------------------------------------------------


_INDUSTRY_DISTRIBUTION_TOP_K = 10


def query_job_demand(
    *,
    session: Session,
    arguments: dict[str, Any],
    tool_call_id: str,
    chart_registry: ChartRegistry,
) -> dict[str, Any]:
    """A1b cross-dataset job_demand records lookup.

    ``fields`` — when omitted OR when it contains ``industry_distribution``
    the response carries the Top-10 industry aggregation (Batch B0.1
    default-on decision, §1.15). Records themselves are capped so a
    single tool call doesn't dump thousands of rows into the Composer
    prompt.
    """
    major = arguments["major"]
    normalized_ref_id = arguments.get("normalized_ref_id")
    fields = arguments.get("fields") or []
    include_distribution = (not fields) or ("industry_distribution" in fields)

    major_pattern = f"%{major}%"

    record_stmt = (
        select(models.JobDemandRecord, models.JobDemandDataset.major_name)
        .join(
            models.JobDemandDataset,
            models.JobDemandRecord.dataset_id == models.JobDemandDataset.id,
        )
        .where(models.JobDemandDataset.major_name.ilike(major_pattern))
        .limit(50)
    )
    if normalized_ref_id is not None:
        record_stmt = record_stmt.where(
            models.JobDemandRecord.normalized_ref_id == normalized_ref_id,
        )

    rows = list(session.execute(record_stmt))
    records = [
        {
            "id": rec.id,
            "job_title": rec.job_title,
            "industry_name": rec.industry_name,
            "city": rec.city,
            "salary_min": rec.salary_min,
            "salary_max": rec.salary_max,
            "education_requirement": rec.education_requirement,
            "experience_requirement": rec.experience_requirement,
            "normalized_ref_id": rec.normalized_ref_id,
            "dataset_id": rec.dataset_id,
            "major_name": dataset_major,
        }
        for rec, dataset_major in rows
    ]

    aggregations: dict[str, Any] = {}
    if include_distribution:
        distribution_stmt = (
            select(
                models.JobDemandRecord.industry_name,
                func.count(models.JobDemandRecord.id).label("count"),
            )
            .join(
                models.JobDemandDataset,
                models.JobDemandRecord.dataset_id == models.JobDemandDataset.id,
            )
            .where(models.JobDemandDataset.major_name.ilike(major_pattern))
        )
        if normalized_ref_id is not None:
            distribution_stmt = distribution_stmt.where(
                models.JobDemandRecord.normalized_ref_id == normalized_ref_id,
            )
        distribution_stmt = (
            distribution_stmt
            .group_by(models.JobDemandRecord.industry_name)
            .order_by(func.count(models.JobDemandRecord.id).desc())
            .limit(_INDUSTRY_DISTRIBUTION_TOP_K)
        )
        aggregations["industry_distribution"] = [
            {"industry_name": name, "count": int(count)}
            for name, count in session.execute(distribution_stmt)
        ]

    return {
        "records": records,
        "aggregations": aggregations,
        "record_count": len(records),
        "major": major,
    }


# ---------------------------------------------------------------------------
# Tool: internal.get_job_demand_role_graph
# ---------------------------------------------------------------------------


def get_job_demand_role_graph(
    *,
    session: Session,
    arguments: dict[str, Any],
    tool_call_id: str,
    chart_registry: ChartRegistry,
) -> dict[str, Any]:
    """B0.2 cross-dataset role-graph lookup by ``job_title``.

    Mirrors ``GET /internal/v1/record-assets/job-demand-role-graph``:
    walks every GENERATED ``build_type=job_demand`` build, finds JOB_ROLE
    nodes whose ``display_name`` substring-matches ``job_title``, and
    returns the merged capability subgraph (union across builds, deduped
    by node.id / edge.id).  Registers ONE chart covering the union so
    Composer can reference it with a single ``[[CHART:xxx]]`` placeholder.

    §2.5.0 forbids trace fields as primary business input — the schema
    only accepts ``job_title``; ``builds[]`` in the response carries
    trace fields (dataset_id / build_id / normalized_ref_id / major_name)
    for Composer citation.
    """
    job_title = arguments["job_title"]
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
        return {
            "found": False,
            "job_title": job_title,
            "match_count": 0,
        }

    ref_ids = list({build.normalized_ref_id for build, _ in matches})
    datasets_by_ref = {
        ds.normalized_ref_id: ds
        for ds in session.scalars(
            select(models.JobDemandDataset)
            .where(models.JobDemandDataset.normalized_ref_id.in_(ref_ids))
        ).all()
    }

    # Merge subgraphs across every matched build.
    nodes_by_id: dict[str, models.CapabilityGraphStagingNode] = {}
    edges_by_id: dict[str, models.CapabilityGraphStagingEdge] = {}
    build_summaries: list[dict[str, Any]] = []

    for build, role_node in matches:
        capability_edges = list(session.scalars(
            select(models.CapabilityGraphStagingEdge).where(
                models.CapabilityGraphStagingEdge.build_id == build.id,
                models.CapabilityGraphStagingEdge.source_node_id == role_node.id,
                models.CapabilityGraphStagingEdge.edge_type
                != EdgeType.JOB_ROLE_AGGREGATES_RECORD,
            )
        ))
        endpoint_ids = {role_node.id}
        for edge in capability_edges:
            endpoint_ids.add(edge.source_node_id)
            endpoint_ids.add(edge.target_node_id)
        endpoint_nodes = list(session.scalars(
            select(models.CapabilityGraphStagingNode)
            .where(models.CapabilityGraphStagingNode.id.in_(endpoint_ids))
        ))
        for node in endpoint_nodes:
            nodes_by_id.setdefault(node.id, node)
        for edge in capability_edges:
            edges_by_id.setdefault(edge.id, edge)

        ds = datasets_by_ref.get(build.normalized_ref_id)
        build_summaries.append({
            "build_id": build.id,
            "normalized_ref_id": build.normalized_ref_id,
            "dataset_id": ds.id if ds else None,
            "major_name": ds.major_name if ds else None,
            "industry_name": ds.industry_name if ds else None,
            "role_node_id": role_node.id,
        })

    merged_nodes = list(nodes_by_id.values())
    merged_edges = list(edges_by_id.values())

    chart_payload = capability_graph_to_chart(
        nodes=merged_nodes,
        edges=merged_edges,
        title=f"{job_title} 岗位能力图谱",
        source_ref=build_summaries[0]["build_id"],
    )
    chart_id = chart_registry.register(
        tool_call_id=tool_call_id, payload=chart_payload,
    )
    graph_nodes, graph_edges = _serialise_capability_graph_facts(
        merged_nodes, merged_edges,
    )

    return {
        "found": True,
        "job_title": job_title,
        "match_count": len(build_summaries),
        "builds": build_summaries,
        "node_count": len(merged_nodes),
        "edge_count": len(merged_edges),
        "graph_nodes": graph_nodes,
        "graph_edges": graph_edges,
        "chart_id": chart_id,
    }


def _serialise_capability_graph_facts(
    nodes: list[models.CapabilityGraphStagingNode],
    edges: list[models.CapabilityGraphStagingEdge],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Expose graph facts for deterministic answer rendering, not LLM prose."""
    node_by_id = {node.id: node for node in nodes}
    graph_nodes = [
        {
            "node_id": node.id,
            "node_type": node.node_type,
            "display_name": node.display_name,
            "properties": node.properties or {},
            "confidence": float(node.confidence) if node.confidence is not None else None,
        }
        for node in nodes
    ]
    graph_edges = [
        {
            "edge_id": edge.id,
            "edge_type": edge.edge_type,
            "source_node_id": edge.source_node_id,
            "source_name": node_by_id.get(edge.source_node_id).display_name
            if edge.source_node_id in node_by_id else None,
            "target_node_id": edge.target_node_id,
            "target_name": node_by_id.get(edge.target_node_id).display_name
            if edge.target_node_id in node_by_id else None,
            "evidence": edge.evidence or {},
            "confidence": float(edge.confidence) if edge.confidence is not None else None,
        }
        for edge in edges
    ]
    return graph_nodes, graph_edges


# ---------------------------------------------------------------------------
# Tool: internal.query_ability_analysis
# ---------------------------------------------------------------------------


def query_ability_analysis(
    *,
    session: Session,
    arguments: dict[str, Any],
    tool_call_id: str,
    chart_registry: ChartRegistry,
) -> dict[str, Any]:
    """B0.3 include-driven lookup — analyses filtered by major with
    optional embedded tasks / ability_items.

    Uses ``OccupationalAbilityAnalysis`` (per-ref analysis) rather than
    ``AbilityAnalysisProfile`` (system-seeded schema descriptor).
    """
    # Schema declares `major_name` (required); we accept the historical
    # `major` key as a fallback so a stale prompt / hand-crafted
    # tool_call doesn't 500 the executor. §2.5.0 business dimension is
    # the major name — no trace fields here.
    major = arguments.get("major_name") or arguments.get("major")
    if not major:
        return {"analyses": [], "count": 0,
                "error": "missing required argument major_name"}
    include = set(arguments.get("include") or [])
    include_tasks = "tasks" in include
    include_items = "ability_items" in include

    analyses = list(session.scalars(
        select(models.OccupationalAbilityAnalysis)
        .where(
            models.OccupationalAbilityAnalysis.major_name.ilike(f"%{major}%"),
        )
        .limit(20)
    ))
    if not analyses:
        return {"analyses": [], "count": 0, "major_name": major}

    analysis_ids = [a.id for a in analyses]

    tasks_by_analysis: dict[str, list[dict[str, Any]]] = {a.id: []
                                                          for a in analyses}
    if include_tasks:
        for task in session.scalars(
            select(models.OccupationalWorkTask).where(
                models.OccupationalWorkTask.analysis_id.in_(analysis_ids),
            )
        ):
            tasks_by_analysis.setdefault(task.analysis_id, []).append({
                "id": task.id,
                "task_code": task.task_code,
                "task_name": task.task_name,
                "task_description": task.task_description,
                "display_order": task.display_order,
            })

    items_by_analysis: dict[str, list[dict[str, Any]]] = {a.id: []
                                                          for a in analyses}
    if include_items:
        for item in session.scalars(
            select(models.OccupationalAbilityItem).where(
                models.OccupationalAbilityItem.analysis_id.in_(analysis_ids),
            )
        ):
            items_by_analysis.setdefault(item.analysis_id, []).append({
                "id": item.id,
                "ability_code": item.ability_code,
                "ability_content": item.ability_content,
                "ability_major_category_name": item.ability_major_category_name,
                "ability_sequence": item.ability_sequence,
            })

    payload_analyses = []
    for a in analyses:
        entry: dict[str, Any] = {
            "id": a.id,
            "major_name": a.major_name,
            "major_direction": a.major_direction,
            "analysis_model": a.analysis_model,
            "normalized_ref_id": a.normalized_ref_id,
            "task_count": a.task_count,
            "ability_item_count": a.ability_item_count,
        }
        if include_tasks:
            entry["tasks"] = tasks_by_analysis.get(a.id, [])
        if include_items:
            entry["ability_items"] = items_by_analysis.get(a.id, [])
        payload_analyses.append(entry)

    return {
        "analyses": payload_analyses,
        "count": len(payload_analyses),
        "major_name": major,
    }


# ---------------------------------------------------------------------------
# Tool: internal.query_major_distribution
# ---------------------------------------------------------------------------


def query_major_distribution(
    *,
    session: Session,
    arguments: dict[str, Any],
    tool_call_id: str,
    chart_registry: ChartRegistry,
) -> dict[str, Any]:
    # Read every optional arg through `.get()` up-front so the
    # schema-alignment contract test can statically distinguish
    # required from optional access — a mixed `arguments[X]` inside an
    # `if arguments.get(X):` guard reads as required to AST scanners
    # even though it's safe.
    major_code = arguments.get("major_code")
    major_name = arguments.get("major_name")
    year = arguments.get("year")
    province_name = arguments.get("province_name")
    education_level = arguments.get("education_level")
    region_scope = arguments.get("region_scope")
    min_count = arguments.get("min_count")
    max_count = arguments.get("max_count")

    stmt = (
        select(
            models.MajorDistributionRecord, models.MajorDistributionDataset,
        )
        .join(
            models.MajorDistributionDataset,
            models.MajorDistributionRecord.dataset_id
            == models.MajorDistributionDataset.id,
        )
    )
    if major_code:
        stmt = stmt.where(
            models.MajorDistributionRecord.major_code == major_code,
        )
    if major_name:
        stmt = stmt.where(
            models.MajorDistributionRecord.major_name.ilike(f"%{major_name}%"),
        )
    if year is not None:
        # Records carry their own `year` — filter directly rather than
        # via dataset year_min/year_max envelope which spans multiple years.
        stmt = stmt.where(models.MajorDistributionRecord.year == year)
    if province_name:
        stmt = stmt.where(
            models.MajorDistributionRecord.province_name == province_name,
        )
    if education_level:
        stmt = stmt.where(
            models.MajorDistributionRecord.education_level == education_level,
        )
    if region_scope:
        stmt = stmt.where(
            models.MajorDistributionRecord.region_scope == region_scope,
        )
    if min_count is not None:
        stmt = stmt.where(
            models.MajorDistributionRecord.distribution_count >= min_count,
        )
    if max_count is not None:
        stmt = stmt.where(
            models.MajorDistributionRecord.distribution_count <= max_count,
        )
    stmt = stmt.limit(100)

    records = []
    for rec, ds in session.execute(stmt):
        records.append({
            "id": rec.id,
            "major_code": rec.major_code,
            "major_name": rec.major_name,
            "province_name": rec.province_name,
            "education_level": rec.education_level,
            "region_scope": rec.region_scope,
            "distribution_count": rec.distribution_count,
            "year": rec.year,
            "dataset_year_min": ds.year_min,
            "dataset_year_max": ds.year_max,
            "normalized_ref_id": rec.normalized_ref_id,
        })
    return {
        "records": records,
        "count": len(records),
    }


# ---------------------------------------------------------------------------
# Tool: internal.get_outline_subtree
# ---------------------------------------------------------------------------


_OUTLINE_MAX_DEPTH = 5


def get_outline_subtree(
    *,
    session: Session,
    arguments: dict[str, Any],
    tool_call_id: str,
    chart_registry: ChartRegistry,
) -> dict[str, Any]:
    node_id = arguments["node_id"]
    include_chunks = bool(arguments.get("include_chunks", False))
    # Honour the schema's optional `max_depth` when the LLM asks for a
    # shallower subtree (Composer might want just the immediate
    # chapter-level headings for a summary). We CAP at
    # _OUTLINE_MAX_DEPTH so a bad tool_call arg can never OOM us — the
    # cap remains the safety floor.
    requested_depth = arguments.get("max_depth")
    if isinstance(requested_depth, int) and requested_depth > 0:
        effective_depth = min(requested_depth, _OUTLINE_MAX_DEPTH)
    else:
        effective_depth = _OUTLINE_MAX_DEPTH

    root = session.get(models.KnowledgeOutlineNode, node_id)
    if root is None:
        return {"found": False, "node_id": node_id}

    # Iterative BFS bounded to `effective_depth` — the outline is at
    # most 3 levels in current data but the cap keeps anomalous cases
    # from OOMing.
    visited: set[str] = {root.id}
    layer: list[models.KnowledgeOutlineNode] = [root]
    all_nodes: list[models.KnowledgeOutlineNode] = [root]
    for _depth in range(effective_depth):
        if not layer:
            break
        parent_ids = [n.id for n in layer]
        children = list(session.scalars(
            select(models.KnowledgeOutlineNode).where(
                models.KnowledgeOutlineNode.parent_id.in_(parent_ids),
            )
        ))
        next_layer = []
        for c in children:
            if c.id in visited:
                continue
            visited.add(c.id)
            all_nodes.append(c)
            next_layer.append(c)
        layer = next_layer

    def _serialise(n: models.KnowledgeOutlineNode) -> dict[str, Any]:
        return {
            "id": n.id,
            "parent_id": n.parent_id,
            "level": n.level,
            "title": n.title,
            "order_index": n.order_index,
            "chunk_count": n.chunk_count,
        }

    return {
        "root_id": root.id,
        "nodes": [_serialise(n) for n in all_nodes],
        "node_count": len(all_nodes),
        "include_chunks_requested": include_chunks,
        "effective_depth": effective_depth,
    }


# ---------------------------------------------------------------------------
# Default registry factory
# ---------------------------------------------------------------------------


def default_v2_executor_registry(
    *, pgvector_adapter: PgvectorSearchAdapter | None = None,
) -> ToolExecutorRegistry:
    """Ready-to-use executor registry covering every registered tool.

    Callers (nexus-api entry points) construct one at request-scope so
    each request gets its own registry — this doesn't matter today
    because executors are stateless, but keeps future per-request
    hooks (rate limiting, per-caller logging) clean to add.
    """
    adapter = pgvector_adapter or PgvectorSearchAdapter()
    registry = ToolExecutorRegistry()
    registry.register(
        "internal.search_chunks_by_semantic",
        make_search_chunks_executor(adapter),
    )
    registry.register(
        "internal.query_major_information",
        query_major_information,
    )
    registry.register(
        "internal.query_capability_graph_by_major",
        query_capability_graph_by_major,
    )
    registry.register(
        "internal.get_evidence_graph_by_ref",
        get_evidence_graph_by_ref,
    )
    registry.register("internal.query_job_demand", query_job_demand)
    registry.register(
        "internal.get_job_demand_role_graph", get_job_demand_role_graph,
    )
    registry.register(
        "internal.query_ability_analysis", query_ability_analysis,
    )
    registry.register(
        "internal.query_major_distribution", query_major_distribution,
    )
    registry.register("internal.get_outline_subtree", get_outline_subtree)
    return registry


__all__ = [
    "default_v2_executor_registry",
    "get_evidence_graph_by_ref",
    "get_job_demand_role_graph",
    "get_outline_subtree",
    "make_search_chunks_executor",
    "query_ability_analysis",
    "query_capability_graph_by_major",
    "query_job_demand",
    "query_major_information",
    "query_major_distribution",
]

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
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.evidence_graph.service import KnowledgeGraphBuildStatus
from nexus_app.index.pgvector_search import PgvectorSearchAdapter
from nexus_app.retrieval.chart_adapter import (
    ChartRegistry,
    capability_graph_to_chart,
    knowledge_graph_to_chart,
)
from nexus_app.retrieval.dispatcher_v2 import ToolExecutor, ToolExecutorRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool: internal.search_chunks_by_semantic
# ---------------------------------------------------------------------------


def make_search_chunks_executor(adapter: PgvectorSearchAdapter) -> ToolExecutor:
    """Wraps ``PgvectorSearchAdapter.search`` for scenario_1 / 3 / 4 use.

    Accepts the tool's parameter set: ``query`` (required), ``kb``
    (knowledge_type_code, optional/const per scenario), ``top_k``
    (default 8), ``similarity_threshold`` (default 0.7),
    ``expand_queries`` (default False — the adapter defaults it too),
    ``outline_node`` (informational — the underlying adapter doesn't yet
    scope by outline heading; passed through in the response for
    Composer awareness).
    """

    def _run(
        *,
        session: Session,
        arguments: dict[str, Any],
        tool_call_id: str,
        chart_registry: ChartRegistry,
    ) -> dict[str, Any]:
        hits = adapter.search(
            session,
            query=arguments["query"],
            knowledge_type_code=arguments.get("kb"),
            top_k=int(arguments.get("top_k", 8)),
            similarity_threshold=float(
                arguments.get("similarity_threshold", 0.7),
            ),
            expand_queries=bool(arguments.get("expand_queries", False)),
        )
        return {
            "hits": hits,
            "query": arguments["query"],
            "kb": arguments.get("kb"),
            "outline_node": arguments.get("outline_node"),
        }

    return _run


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

    return {
        "found": True,
        "build_id": build.id,
        "build_type": build.build_type,
        "major_name": build.major_name,
        "major_code": build.major_code,
        "normalized_ref_id": build.normalized_ref_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
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
    """P0 impl uses ``build_type='job_demand'`` staging graph as the
    canonical role-graph source (see A1b / B0.2 endpoint mirror).
    """
    dataset_id = arguments["dataset_id"]
    job_title = arguments.get("job_title")

    # For P0 we anchor on normalized_ref_id via dataset_id → normalized_ref_id.
    ref_stmt = select(models.JobDemandDataset.normalized_ref_id).where(
        models.JobDemandDataset.id == dataset_id,
    )
    normalized_ref_id = session.scalar(ref_stmt)
    if normalized_ref_id is None:
        return {"found": False, "dataset_id": dataset_id}

    build = session.scalars(
        select(models.CapabilityGraphStagingBuild)
        .where(
            models.CapabilityGraphStagingBuild.normalized_ref_id
            == normalized_ref_id,
            models.CapabilityGraphStagingBuild.build_type == "job_demand",
        )
        .order_by(models.CapabilityGraphStagingBuild.created_at.desc())
    ).first()
    if build is None:
        return {
            "found": False,
            "dataset_id": dataset_id,
            "normalized_ref_id": normalized_ref_id,
        }

    node_stmt = select(models.CapabilityGraphStagingNode).where(
        models.CapabilityGraphStagingNode.build_id == build.id,
    )
    if job_title:
        node_stmt = node_stmt.where(
            models.CapabilityGraphStagingNode.display_name.ilike(
                f"%{job_title}%",
            ),
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
        title=f"岗位角色图 (dataset {dataset_id[:8]})",
        source_ref=build.id,
    )
    chart_id = chart_registry.register(
        tool_call_id=tool_call_id, payload=chart_payload,
    )

    return {
        "found": True,
        "dataset_id": dataset_id,
        "build_id": build.id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "chart_id": chart_id,
    }


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
    major = arguments["major"]
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
        return {"analyses": [], "major": major}

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
        "major": major,
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
    if arguments.get("major_code"):
        stmt = stmt.where(
            models.MajorDistributionRecord.major_code == arguments["major_code"],
        )
    if arguments.get("major_name"):
        stmt = stmt.where(
            models.MajorDistributionRecord.major_name.ilike(
                f"%{arguments['major_name']}%",
            ),
        )
    if arguments.get("year") is not None:
        # Records carry their own `year` — filter directly rather than
        # via dataset year_min/year_max envelope which spans multiple years.
        stmt = stmt.where(
            models.MajorDistributionRecord.year == arguments["year"],
        )
    if arguments.get("province_name"):
        stmt = stmt.where(
            models.MajorDistributionRecord.province_name == arguments["province_name"],
        )
    if arguments.get("education_level"):
        stmt = stmt.where(
            models.MajorDistributionRecord.education_level == arguments["education_level"],
        )
    if arguments.get("region_scope"):
        stmt = stmt.where(
            models.MajorDistributionRecord.region_scope == arguments["region_scope"],
        )
    if arguments.get("min_count") is not None:
        stmt = stmt.where(
            models.MajorDistributionRecord.distribution_count >= arguments["min_count"],
        )
    if arguments.get("max_count") is not None:
        stmt = stmt.where(
            models.MajorDistributionRecord.distribution_count <= arguments["max_count"],
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

    root = session.get(models.KnowledgeOutlineNode, node_id)
    if root is None:
        return {"found": False, "node_id": node_id}

    # Iterative BFS bounded to depth _OUTLINE_MAX_DEPTH — the outline
    # is at most 3 levels in the current data but headroom keeps
    # anomalous cases from OOMing.
    visited: set[str] = {root.id}
    layer: list[models.KnowledgeOutlineNode] = [root]
    all_nodes: list[models.KnowledgeOutlineNode] = [root]
    for _depth in range(_OUTLINE_MAX_DEPTH):
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
    "query_major_distribution",
]

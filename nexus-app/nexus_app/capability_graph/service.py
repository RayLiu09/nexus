"""Persist NodeSpec / EdgeSpec lists under a single build envelope.

`build_capability_staging` is the public entry point invoked by the
worker stage. Resolves the right builders based on `build_type`, loads
the source rows in one pass, runs the builder, dedupes by
`(node_type, node_key)`, materialises the build / nodes / edges, and
returns a summary.
"""
from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.capability_graph import builders
from nexus_app.capability_graph.schemas import (
    BuildResult,
    EdgeSpec,
    NodeSpec,
)
from nexus_app.capability_graph.whitelists import (
    BUILD_TYPES,
    STAGING_SCHEMA_VERSION,
    BuildStatus,
    BuildType,
)

logger = logging.getLogger(__name__)


def build_capability_staging(
    session: Session,
    normalized_ref: models.NormalizedAssetRef,
    *,
    build_type: str,
    domain: str = "occupation",
    teaching_standard_payload: dict[str, object] | None = None,
    force: bool = False,
) -> BuildResult:
    """Materialise staging nodes + edges for `normalized_ref`.

    Returns a BuildResult capturing counts + quality_summary. Caller owns
    commit (we only flush so FK targets settle).

    Skipped when:
    - `build_type` isn't in the whitelist
    - the source domain rows produce zero nodes (no point writing an
      empty build envelope)
    """
    if build_type not in BUILD_TYPES:
        return BuildResult(
            build_id="", build_type=build_type,
            skipped=True, skipped_reason="unsupported_build_type",
        )

    if build_type == BuildType.TEACHING_STANDARD:
        existing = session.scalar(
            select(models.CapabilityGraphStagingBuild).where(
                models.CapabilityGraphStagingBuild.normalized_ref_id == normalized_ref.id,
                models.CapabilityGraphStagingBuild.build_type == build_type,
                models.CapabilityGraphStagingBuild.status == BuildStatus.GENERATED,
            ).order_by(models.CapabilityGraphStagingBuild.created_at.desc())
        )
        if existing is not None and not force:
            summary = existing.quality_summary or {}
            return BuildResult(
                build_id=existing.id, build_type=build_type,
                nodes_written=int(summary.get("nodes_total", 0)),
                edges_written=int(summary.get("edges_total", 0)),
                quality_summary=summary, skipped=True,
                skipped_reason="existing_generated_build",
            )
        if existing is not None and force:
            session.delete(existing)
            session.flush()

    nodes, edges = _collect_specs(session, normalized_ref, build_type, teaching_standard_payload)
    if not nodes:
        return BuildResult(
            build_id="", build_type=build_type,
            skipped=True, skipped_reason="no_domain_data",
        )

    # Dedupe nodes by (node_type, node_key); first occurrence wins so we
    # don't try to insert two rows with the same uq_cgsn key.
    unique_nodes: dict[tuple[str, str], NodeSpec] = {}
    for node in nodes:
        key = (node.node_type, node.node_key)
        if key not in unique_nodes:
            unique_nodes[key] = node

    # Resolve edge endpoints against the deduped node set; drop edges
    # whose endpoints didn't materialise (defence-in-depth — should never
    # happen, but a partially-constructed analysis can leave dangling refs).
    resolved_edges: list[EdgeSpec] = []
    dropped_edges = 0
    for edge in edges:
        if (
            edge.source_node_key not in unique_nodes
            or edge.target_node_key not in unique_nodes
        ):
            dropped_edges += 1
            continue
        resolved_edges.append(edge)

    # Dedupe edges by (source, target, edge_type) so uq_cgse insertions
    # don't collide.
    unique_edges: dict[tuple[tuple[str, str], tuple[str, str], str], EdgeSpec] = {}
    duplicate_edges = 0
    for edge in resolved_edges:
        edge_key = (edge.source_node_key, edge.target_node_key, edge.edge_type)
        if edge_key in unique_edges:
            duplicate_edges += 1
            continue
        unique_edges[edge_key] = edge

    # ------------------------------------------------------------------ #
    # Persist build envelope + nodes (with id assignment) + edges
    # ------------------------------------------------------------------ #
    quality_summary = _aggregate_quality(
        nodes_unique=len(unique_nodes),
        nodes_duplicates=len(nodes) - len(unique_nodes),
        edges_dropped=dropped_edges,
        edges_duplicates=duplicate_edges,
        nodes=list(unique_nodes.values()),
        edges=list(unique_edges.values()),
    )
    build = models.CapabilityGraphStagingBuild(
        id=str(uuid4()),
        normalized_ref_id=normalized_ref.id,
        domain=domain,
        build_type=build_type,
        status=BuildStatus.GENERATED,
        schema_version=STAGING_SCHEMA_VERSION,
        quality_summary=quality_summary,
    )
    session.add(build)
    session.flush()

    node_id_by_key: dict[tuple[str, str], str] = {}
    for key, spec in unique_nodes.items():
        node_id = str(uuid4())
        node_id_by_key[key] = node_id
        session.add(models.CapabilityGraphStagingNode(
            id=node_id,
            build_id=build.id,
            node_type=spec.node_type,
            node_key=spec.node_key,
            display_name=spec.display_name,
            canonical_name=spec.canonical_name,
            source_table=spec.source_table,
            source_id=spec.source_id,
            properties=dict(spec.properties),
            confidence=spec.confidence,
        ))
    session.flush()  # need node IDs available for the edge FK

    for spec in unique_edges.values():
        session.add(models.CapabilityGraphStagingEdge(
            id=str(uuid4()),
            build_id=build.id,
            source_node_id=node_id_by_key[spec.source_node_key],
            target_node_id=node_id_by_key[spec.target_node_key],
            edge_type=spec.edge_type,
            source_table=spec.source_table,
            source_id=spec.source_id,
            evidence=dict(spec.evidence),
            confidence=spec.confidence,
        ))
    session.flush()

    return BuildResult(
        build_id=build.id,
        build_type=build_type,
        nodes_written=len(unique_nodes),
        edges_written=len(unique_edges),
        quality_summary=quality_summary,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _collect_specs(
    session: Session,
    normalized_ref: models.NormalizedAssetRef,
    build_type: str,
    teaching_standard_payload: dict[str, object] | None = None,
) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    """Run the relevant builder(s) for `build_type` and concat results."""
    nodes: list[NodeSpec] = []
    edges: list[EdgeSpec] = []

    if build_type == BuildType.TEACHING_STANDARD and teaching_standard_payload:
        return builders.build_teaching_standard(teaching_standard_payload)

    if build_type in (BuildType.JOB_DEMAND, BuildType.COMBINED):
        dataset = session.scalar(
            select(models.JobDemandDataset).where(
                models.JobDemandDataset.normalized_ref_id == normalized_ref.id
            )
        )
        if dataset is not None:
            records = list(session.scalars(
                select(models.JobDemandRecord).where(
                    models.JobDemandRecord.dataset_id == dataset.id
                )
            ))
            requirement_items = list(session.scalars(
                select(models.JobDemandRequirementItem).where(
                    models.JobDemandRequirementItem.dataset_id == dataset.id
                )
            )) if records else []
            jd_nodes, jd_edges = builders.build_job_demand(
                dataset=dataset, records=records, requirement_items=requirement_items,
            )
            nodes.extend(jd_nodes)
            edges.extend(jd_edges)

    if build_type in (BuildType.ABILITY_ANALYSIS, BuildType.COMBINED):
        analysis = session.scalar(
            select(models.OccupationalAbilityAnalysis).where(
                models.OccupationalAbilityAnalysis.normalized_ref_id
                == normalized_ref.id
            )
        )
        if analysis is not None:
            tasks = list(session.scalars(
                select(models.OccupationalWorkTask).where(
                    models.OccupationalWorkTask.analysis_id == analysis.id
                )
            ))
            work_contents = list(session.scalars(
                select(models.OccupationalWorkContent).where(
                    models.OccupationalWorkContent.analysis_id == analysis.id
                )
            ))
            abilities = list(session.scalars(
                select(models.OccupationalAbilityItem).where(
                    models.OccupationalAbilityItem.analysis_id == analysis.id
                )
            ))
            aa_nodes, aa_edges = builders.build_ability_analysis(
                analysis=analysis, tasks=tasks,
                work_contents=work_contents, abilities=abilities,
            )
            nodes.extend(aa_nodes)
            edges.extend(aa_edges)

            if build_type == BuildType.COMBINED:
                links = list(session.scalars(
                    select(models.AbilityAnalysisSourceDataset).where(
                        models.AbilityAnalysisSourceDataset.analysis_id == analysis.id
                    )
                ))
                if links:
                    # Combined builds always go through the job_demand
                    # branch above, so the linked records are already in
                    # the spec list. Reload here to keep this function
                    # self-contained.
                    linked_dataset_ids = {link.job_demand_dataset_id for link in links}
                    linked_records = list(session.scalars(
                        select(models.JobDemandRecord).where(
                            models.JobDemandRecord.dataset_id.in_(linked_dataset_ids)
                        )
                    ))
                    edges.extend(builders.combined_ability_derived_edges(
                        source_dataset_links=links,
                        abilities=abilities,
                        job_demand_records=linked_records,
                    ))

    return nodes, edges


def _aggregate_quality(
    *,
    nodes_unique: int,
    nodes_duplicates: int,
    edges_dropped: int,
    edges_duplicates: int,
    nodes: list[NodeSpec],
    edges: list[EdgeSpec],
) -> dict[str, int | str]:
    """Produce the staging build's `quality_summary` JSONB payload.

    Keys are stable so console / search can pivot on them without parsing.
    `orphan_*_count` requires inspecting the resolved graph — we count
    nodes that don't appear as either endpoint of any edge.
    """
    edge_endpoints: set[tuple[str, str]] = set()
    for e in edges:
        edge_endpoints.add(e.source_node_key)
        edge_endpoints.add(e.target_node_key)
    orphan_nodes = sum(
        1 for n in nodes if (n.node_type, n.node_key) not in edge_endpoints
    )

    low_conf_edges = sum(
        1 for e in edges
        if e.confidence is not None and e.confidence < 0.5
    )

    summary: dict[str, int | str] = {
        "nodes_total": nodes_unique,
        "edges_total": len(edges),
        "nodes_duplicates_collapsed": nodes_duplicates,
        "edges_duplicates_collapsed": edges_duplicates,
        "edges_dropped_missing_endpoint": edges_dropped,
        "orphan_nodes_count": orphan_nodes,
        "low_confidence_edges_count": low_conf_edges,
        "schema_version": STAGING_SCHEMA_VERSION,
    }
    return summary


__all__ = ["build_capability_staging"]

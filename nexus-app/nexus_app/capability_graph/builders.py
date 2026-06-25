"""Pure-logic builders that turn domain reads into NodeSpec / EdgeSpec lists.

Each builder takes typed input (ORM-row sequences) and returns
`(nodes, edges)` ready for the service to dedupe + persist. No session
work happens here — service.py does all IO.

Three build types per design §7.2:
- `job_demand`: just job_demand_dataset + records + requirement_items
- `ability_analysis`: just occupational_*
- `combined`: both, plus ABILITY_DERIVED_FROM_JOB_REQUIREMENT edges
  derived from `ability_analysis_source_dataset` links

Skill / literacy node deduplication is by `(item_type, normalized_name OR
item_name)` so multiple records mentioning "Python" collapse into one
Skill node with edges from each record.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from nexus_app import models
from nexus_app.capability_graph.schemas import EdgeSpec, NodeSpec
from nexus_app.capability_graph.whitelists import EdgeType, NodeType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _skill_key(item: models.JobDemandRequirementItem) -> str:
    """Stable Skill / Literacy node_key: prefer normalized_name, fall back
    to item_name. Lowercased + stripped so dedup is case-insensitive."""
    raw = (item.normalized_name or item.item_name or "").strip().lower()
    return raw or f"unknown:{item.id}"


def _job_role_key(record: models.JobDemandRecord) -> str:
    """Stable JobRole node_key: lowercased job_title. Empty title falls
    back to record id so we don't produce a single bogus "unknown" hub."""
    title = (record.job_title or "").strip().lower()
    return title or f"unknown_role:{record.id}"


# ---------------------------------------------------------------------------
# job_demand build
# ---------------------------------------------------------------------------


def build_job_demand(
    *,
    dataset: models.JobDemandDataset,
    records: list[models.JobDemandRecord],
    requirement_items: list[models.JobDemandRequirementItem],
) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    """Build nodes + edges for the `job_demand` build_type.

    Node strategy:
    - One `JobDemandRecord` per row.
    - One `JobRole` per distinct job_title (records aggregate up).
    - One `Skill` per distinct `professional_skill` / `tool` item.
    - One `ProfessionalLiteracy` per distinct `professional_literacy` item.
      (`certificate` is currently mapped to Skill too — design §7.3 only
       names Skill / Literacy as item-derived node types; certificates
       are treated as skills with a `category=certificate` property.)

    Edge strategy:
    - `JOB_ROLE_AGGREGATES_RECORD`     role → record (one per record)
    - `JOB_RECORD_HAS_SKILL`           record → skill (one per item)
    - `JOB_RECORD_HAS_LITERACY`        record → literacy (one per item)
    - `JOB_ROLE_REQUIRES_SKILL`        role → skill (collapsed)
    - `JOB_ROLE_REQUIRES_LITERACY`     role → literacy (collapsed)
    """
    nodes: list[NodeSpec] = []
    edges: list[EdgeSpec] = []

    role_keys: set[str] = set()
    skill_keys: dict[str, NodeSpec] = {}
    literacy_keys: dict[str, NodeSpec] = {}

    items_by_record: dict[str, list[models.JobDemandRequirementItem]] = defaultdict(list)
    for it in requirement_items:
        items_by_record[it.record_id].append(it)

    for record in records:
        # JobDemandRecord node — one per record.
        record_props = {
            "city": record.city,
            "company_name": record.company_name,
            "salary_text": record.salary_text,
            "enterprise_size": record.enterprise_size,
        }
        nodes.append(NodeSpec(
            node_type=NodeType.JOB_DEMAND_RECORD,
            node_key=record.id,           # record id is its own stable key
            display_name=record.job_title or record.source_record_key or record.id,
            source_table="job_demand_record",
            source_id=record.id,
            properties={k: v for k, v in record_props.items() if v is not None},
        ))

        # JobRole node — aggregate by job_title.
        role_key = _job_role_key(record)
        if role_key not in role_keys:
            role_keys.add(role_key)
            nodes.append(NodeSpec(
                node_type=NodeType.JOB_ROLE,
                node_key=role_key,
                display_name=record.job_title or role_key,
                source_table="job_demand_record",
            ))
        # JOB_ROLE_AGGREGATES_RECORD edge
        edges.append(EdgeSpec(
            edge_type=EdgeType.JOB_ROLE_AGGREGATES_RECORD,
            source_node_key=(NodeType.JOB_ROLE, role_key),
            target_node_key=(NodeType.JOB_DEMAND_RECORD, record.id),
            source_table="job_demand_record",
            source_id=record.id,
        ))

        # Item-derived nodes + edges.
        for item in items_by_record.get(record.id, []):
            key = _skill_key(item)
            if item.item_type in ("professional_skill", "tool", "certificate"):
                if key not in skill_keys:
                    skill_keys[key] = NodeSpec(
                        node_type=NodeType.SKILL,
                        node_key=key,
                        display_name=item.normalized_name or item.item_name,
                        canonical_name=item.normalized_name,
                        source_table="job_demand_requirement_item",
                        properties={"item_type": item.item_type},
                    )
                edges.append(EdgeSpec(
                    edge_type=EdgeType.JOB_RECORD_HAS_SKILL,
                    source_node_key=(NodeType.JOB_DEMAND_RECORD, record.id),
                    target_node_key=(NodeType.SKILL, key),
                    source_table="job_demand_requirement_item",
                    source_id=item.id,
                    confidence=item.confidence,
                ))
                edges.append(EdgeSpec(
                    edge_type=EdgeType.JOB_ROLE_REQUIRES_SKILL,
                    source_node_key=(NodeType.JOB_ROLE, role_key),
                    target_node_key=(NodeType.SKILL, key),
                    source_table="job_demand_requirement_item",
                    source_id=item.id,
                    confidence=item.confidence,
                ))
            elif item.item_type == "professional_literacy":
                if key not in literacy_keys:
                    literacy_keys[key] = NodeSpec(
                        node_type=NodeType.PROFESSIONAL_LITERACY,
                        node_key=key,
                        display_name=item.normalized_name or item.item_name,
                        canonical_name=item.normalized_name,
                        source_table="job_demand_requirement_item",
                    )
                edges.append(EdgeSpec(
                    edge_type=EdgeType.JOB_RECORD_HAS_LITERACY,
                    source_node_key=(NodeType.JOB_DEMAND_RECORD, record.id),
                    target_node_key=(NodeType.PROFESSIONAL_LITERACY, key),
                    source_table="job_demand_requirement_item",
                    source_id=item.id,
                    confidence=item.confidence,
                ))
                edges.append(EdgeSpec(
                    edge_type=EdgeType.JOB_ROLE_REQUIRES_LITERACY,
                    source_node_key=(NodeType.JOB_ROLE, role_key),
                    target_node_key=(NodeType.PROFESSIONAL_LITERACY, key),
                    source_table="job_demand_requirement_item",
                    source_id=item.id,
                    confidence=item.confidence,
                ))
            # `work_task_candidate` items are NOT graphed here — they're
            # B5.4-style hints for surfacing tasks in the UI, not first-
            # class WorkTask nodes (WorkTask is owned by the ability
            # analysis path).

    nodes.extend(skill_keys.values())
    nodes.extend(literacy_keys.values())
    return nodes, edges


# ---------------------------------------------------------------------------
# ability_analysis build
# ---------------------------------------------------------------------------


def build_ability_analysis(
    *,
    analysis: models.OccupationalAbilityAnalysis,
    tasks: list[models.OccupationalWorkTask],
    work_contents: list[models.OccupationalWorkContent],
    abilities: list[models.OccupationalAbilityItem],
) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    """Build nodes + edges for the `ability_analysis` build_type.

    Node strategy:
    - One `WorkTask` per task; node_key = `<analysis_id>:<task_code>` so
      different analyses can coexist if they later share a build.
    - One `WorkContent` per work_content; node_key includes task_code so
      "1.1" under different tasks doesn't collide.
    - One `Ability` per ability_item; node_key = ability_code (already
      unique per analysis).

    Edge strategy:
    - `TASK_HAS_WORK_CONTENT`            task → work_content
    - `WORK_CONTENT_REQUIRES_ABILITY`    work_content → ability (P only)
    - G/S/D abilities hang off the task directly — no work_content edge
      (per §10.2 requires_work_content=False).
    """
    nodes: list[NodeSpec] = []
    edges: list[EdgeSpec] = []
    wc_by_id: dict[str, models.OccupationalWorkContent] = {wc.id: wc for wc in work_contents}

    for task in tasks:
        task_key = f"{analysis.id}:{task.task_code}"
        nodes.append(NodeSpec(
            node_type=NodeType.WORK_TASK,
            node_key=task_key,
            display_name=task.task_name,
            source_table="occupational_work_task",
            source_id=task.id,
            properties={"task_code": task.task_code},
        ))

    for wc in work_contents:
        task = next((t for t in tasks if t.id == wc.task_id), None)
        if task is None:
            continue  # orphan — flagged at quality_summary aggregation time
        task_key = f"{analysis.id}:{task.task_code}"
        wc_key = f"{task_key}:{wc.content_code}"
        nodes.append(NodeSpec(
            node_type=NodeType.WORK_CONTENT,
            node_key=wc_key,
            display_name=wc.content_name,
            source_table="occupational_work_content",
            source_id=wc.id,
            properties={"content_code": wc.content_code},
        ))
        edges.append(EdgeSpec(
            edge_type=EdgeType.TASK_HAS_WORK_CONTENT,
            source_node_key=(NodeType.WORK_TASK, task_key),
            target_node_key=(NodeType.WORK_CONTENT, wc_key),
            source_table="occupational_work_content",
            source_id=wc.id,
        ))

    for ability in abilities:
        task = next((t for t in tasks if t.id == ability.task_id), None)
        if task is None:
            continue  # task missing → graph layer skips silently; B7 flags it
        ability_key = ability.ability_code
        nodes.append(NodeSpec(
            node_type=NodeType.ABILITY,
            node_key=ability_key,
            display_name=ability.ability_content or ability.ability_code,
            source_table="occupational_ability_item",
            source_id=ability.id,
            properties={
                "ability_code": ability.ability_code,
                "category": ability.ability_major_category_code,
            },
            confidence=ability.confidence,
        ))
        if ability.work_content_id and ability.work_content_id in wc_by_id:
            wc = wc_by_id[ability.work_content_id]
            task_key = f"{analysis.id}:{task.task_code}"
            wc_key = f"{task_key}:{wc.content_code}"
            edges.append(EdgeSpec(
                edge_type=EdgeType.WORK_CONTENT_REQUIRES_ABILITY,
                source_node_key=(NodeType.WORK_CONTENT, wc_key),
                target_node_key=(NodeType.ABILITY, ability_key),
                source_table="occupational_ability_item",
                source_id=ability.id,
                confidence=ability.confidence,
            ))

    return nodes, edges


# ---------------------------------------------------------------------------
# combined build — extra cross-domain edges on top of ability_analysis
# ---------------------------------------------------------------------------


def combined_ability_derived_edges(
    *,
    source_dataset_links: list[models.AbilityAnalysisSourceDataset],
    abilities: list[models.OccupationalAbilityItem],
    job_demand_records: list[models.JobDemandRecord],
) -> list[EdgeSpec]:
    """Emit ABILITY_DERIVED_FROM_JOB_REQUIREMENT edges.

    P0 contract: when an `ability_analysis_source_dataset` row links an
    analysis to a job_demand_dataset, every ability in the analysis is
    presumed to derive from every record in the linked dataset. This is
    coarse but matches the design §6.2 evidence model (the LLM-driven
    refinement to per-ability evidence is a later slice).
    """
    if not source_dataset_links or not abilities or not job_demand_records:
        return []
    edges: list[EdgeSpec] = []
    for ability in abilities:
        for record in job_demand_records:
            edges.append(EdgeSpec(
                edge_type=EdgeType.ABILITY_DERIVED_FROM_JOB_REQUIREMENT,
                source_node_key=(NodeType.ABILITY, ability.ability_code),
                target_node_key=(NodeType.JOB_DEMAND_RECORD, record.id),
                source_table="ability_analysis_source_dataset",
                source_id=source_dataset_links[0].id,
                evidence={"linkage": "dataset_level"},
            ))
    return edges


__all__ = [
    "build_ability_analysis",
    "build_job_demand",
    "combined_ability_derived_edges",
]

"""Whitelists + constants for CapabilityGraphStaging.

Sourced from design §7.3 (node types) and §7.4 (edge types). The
evidence-bound course-standard path emits `CourseModule` and its dedicated
task/skill/knowledge requirement relations; other capability-graph paths do
not reuse those terms.

Adding a new node / edge type = adding the constant here + an emitter in
`builders.py`. Removing one requires a contract amendment.
"""
from __future__ import annotations


STAGING_SCHEMA_VERSION: str = "capability_graph_staging.v1"


class BuildType:
    """`capability_graph_staging_build.build_type` whitelist."""
    JOB_DEMAND = "job_demand"
    ABILITY_ANALYSIS = "ability_analysis"
    COMBINED = "combined"
    TEACHING_STANDARD = "teaching_standard"
    COURSE_STANDARD = "course_standard"


BUILD_TYPES: frozenset[str] = frozenset({
    BuildType.JOB_DEMAND,
    BuildType.ABILITY_ANALYSIS,
    BuildType.COMBINED,
    BuildType.TEACHING_STANDARD,
    BuildType.COURSE_STANDARD,
})


class BuildStatus:
    """`capability_graph_staging_build.status` whitelist.

    `promoted` is reserved for the future "ship to formal graph" path —
    B8 only produces `generated` / `failed`; `validated` is reserved for
    human review (B9+).
    """
    GENERATED = "generated"
    VALIDATED = "validated"
    FAILED = "failed"
    PROMOTED = "promoted"


STAGING_STATUSES: frozenset[str] = frozenset({
    BuildStatus.GENERATED,
    BuildStatus.VALIDATED,
    BuildStatus.FAILED,
    BuildStatus.PROMOTED,
})


class NodeType:
    """`capability_graph_staging_node.node_type` whitelist (design §7.3).

    `CourseModule` is emitted only by the evidence-bound course-standard path.
    """
    JOB_ROLE = "JobRole"
    JOB_DEMAND_RECORD = "JobDemandRecord"
    SKILL = "Skill"
    PROFESSIONAL_LITERACY = "ProfessionalLiteracy"
    WORK_TASK = "WorkTask"
    WORK_CONTENT = "WorkContent"
    ABILITY = "Ability"
    COURSE = "Course"
    COURSE_MODULE = "CourseModule"
    COURSE_CONTENT = "CourseContent"
    MAJOR = "Major"
    OCCUPATIONAL_DOMAIN = "OccupationalDomain"
    TYPICAL_WORK_TASK = "TypicalWorkTask"
    SKILL_KNOWLEDGE_REQUIREMENT = "SkillKnowledgeRequirement"
    SKILL_REQUIREMENT = "SkillRequirement"
    KNOWLEDGE_REQUIREMENT = "KnowledgeRequirement"


NODE_TYPES: frozenset[str] = frozenset({
    NodeType.JOB_ROLE,
    NodeType.JOB_DEMAND_RECORD,
    NodeType.SKILL,
    NodeType.PROFESSIONAL_LITERACY,
    NodeType.WORK_TASK,
    NodeType.WORK_CONTENT,
    NodeType.ABILITY,
    NodeType.COURSE,
    NodeType.COURSE_MODULE,
    NodeType.COURSE_CONTENT,
    NodeType.MAJOR,
    NodeType.OCCUPATIONAL_DOMAIN,
    NodeType.TYPICAL_WORK_TASK,
    NodeType.SKILL_KNOWLEDGE_REQUIREMENT,
    NodeType.SKILL_REQUIREMENT,
    NodeType.KNOWLEDGE_REQUIREMENT,
})


class EdgeType:
    """`capability_graph_staging_edge.edge_type` whitelist (design §7.4).

    Course-standard edges are emitted only by the evidence-bound course-standard path.
    """
    JOB_RECORD_HAS_SKILL = "JOB_RECORD_HAS_SKILL"
    JOB_RECORD_HAS_LITERACY = "JOB_RECORD_HAS_LITERACY"
    JOB_RECORD_HAS_WORK_CONTENT = "JOB_RECORD_HAS_WORK_CONTENT"
    JOB_ROLE_AGGREGATES_RECORD = "JOB_ROLE_AGGREGATES_RECORD"
    JOB_ROLE_REQUIRES_SKILL = "JOB_ROLE_REQUIRES_SKILL"
    JOB_ROLE_REQUIRES_LITERACY = "JOB_ROLE_REQUIRES_LITERACY"
    JOB_ROLE_REQUIRES_WORK_CONTENT = "JOB_ROLE_REQUIRES_WORK_CONTENT"
    TASK_HAS_WORK_CONTENT = "TASK_HAS_WORK_CONTENT"
    TASK_REQUIRES_ABILITY = "TASK_REQUIRES_ABILITY"
    WORK_CONTENT_REQUIRES_ABILITY = "WORK_CONTENT_REQUIRES_ABILITY"
    ABILITY_MAPS_TO_SKILL = "ABILITY_MAPS_TO_SKILL"
    ABILITY_DERIVED_FROM_JOB_REQUIREMENT = "ABILITY_DERIVED_FROM_JOB_REQUIREMENT"
    SKILL_COVERED_BY_COURSE_MODULE = "SKILL_COVERED_BY_COURSE_MODULE"  # reserved
    ABILITY_COVERED_BY_COURSE_MODULE = "ABILITY_COVERED_BY_COURSE_MODULE"  # reserved
    MAJOR_HAS_OCCUPATIONAL_DOMAIN = "MAJOR_HAS_OCCUPATIONAL_DOMAIN"
    OCCUPATIONAL_DOMAIN_HAS_TYPICAL_WORK_TASK = "OCCUPATIONAL_DOMAIN_HAS_TYPICAL_WORK_TASK"
    OCCUPATIONAL_DOMAIN_HAS_SKILL_KNOWLEDGE_REQUIREMENT = "OCCUPATIONAL_DOMAIN_HAS_SKILL_KNOWLEDGE_REQUIREMENT"
    COURSE_HAS_COURSE_MODULE = "COURSE_HAS_COURSE_MODULE"
    COURSE_MODULE_HAS_COURSE_CONTENT = "COURSE_MODULE_HAS_COURSE_CONTENT"
    COURSE_CONTENT_HAS_SKILL_REQUIREMENT = "COURSE_CONTENT_HAS_SKILL_REQUIREMENT"
    COURSE_CONTENT_HAS_KNOWLEDGE_REQUIREMENT = "COURSE_CONTENT_HAS_KNOWLEDGE_REQUIREMENT"
    SKILL_REQUIREMENT_HAS_KNOWLEDGE_REQUIREMENT = "SKILL_REQUIREMENT_HAS_KNOWLEDGE_REQUIREMENT"


EDGE_TYPES: frozenset[str] = frozenset({
    EdgeType.JOB_RECORD_HAS_SKILL,
    EdgeType.JOB_RECORD_HAS_LITERACY,
    EdgeType.JOB_RECORD_HAS_WORK_CONTENT,
    EdgeType.JOB_ROLE_AGGREGATES_RECORD,
    EdgeType.JOB_ROLE_REQUIRES_SKILL,
    EdgeType.JOB_ROLE_REQUIRES_LITERACY,
    EdgeType.JOB_ROLE_REQUIRES_WORK_CONTENT,
    EdgeType.TASK_HAS_WORK_CONTENT,
    EdgeType.TASK_REQUIRES_ABILITY,
    EdgeType.WORK_CONTENT_REQUIRES_ABILITY,
    EdgeType.ABILITY_MAPS_TO_SKILL,
    EdgeType.ABILITY_DERIVED_FROM_JOB_REQUIREMENT,
    EdgeType.SKILL_COVERED_BY_COURSE_MODULE,
    EdgeType.ABILITY_COVERED_BY_COURSE_MODULE,
    EdgeType.MAJOR_HAS_OCCUPATIONAL_DOMAIN,
    EdgeType.OCCUPATIONAL_DOMAIN_HAS_TYPICAL_WORK_TASK,
    EdgeType.OCCUPATIONAL_DOMAIN_HAS_SKILL_KNOWLEDGE_REQUIREMENT,
    EdgeType.COURSE_HAS_COURSE_MODULE,
    EdgeType.COURSE_MODULE_HAS_COURSE_CONTENT,
    EdgeType.COURSE_CONTENT_HAS_SKILL_REQUIREMENT,
    EdgeType.COURSE_CONTENT_HAS_KNOWLEDGE_REQUIREMENT,
    EdgeType.SKILL_REQUIREMENT_HAS_KNOWLEDGE_REQUIREMENT,
})


__all__ = [
    "BUILD_TYPES",
    "BuildStatus",
    "BuildType",
    "EDGE_TYPES",
    "EdgeType",
    "NODE_TYPES",
    "NodeType",
    "STAGING_SCHEMA_VERSION",
    "STAGING_STATUSES",
]

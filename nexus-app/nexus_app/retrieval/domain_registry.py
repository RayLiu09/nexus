"""Static domain/query-profile registry for retrieval/recall v1.0."""
from __future__ import annotations

from dataclasses import dataclass

from nexus_app.enums import TagAssetIndexTargetType
from nexus_app.retrieval.schemas import BusinessDomain, RetrievalChannel


@dataclass(frozen=True)
class QueryProfile:
    key: str
    channel: RetrievalChannel
    description: str
    executor_key: str
    table_profile: str | None = None
    allowed_filters: tuple[str, ...] = ()
    allowed_group_by: tuple[str, ...] = ()
    allowed_metrics: tuple[str, ...] = ()
    default_limit: int = 50
    max_limit: int = 200
    # v1.3 §5.3 R3 addition — allowed tag_filters for this profile.
    # Values are plural bucket names ("regions" / "industries" / …) that
    # match the v1.3 TagFilter dict keys.  An empty tuple means the
    # profile does not participate in tag_asset_index projection (e.g.
    # pre-v1.3 unstructured profiles).  Guardrails reject tag_filter
    # keys outside this set (F2-4 unrelated-domain protection).
    allowed_tag_types: tuple[str, ...] = ()
    # v1.3 R3 — declares whether the executor supports the
    # ``__target_id_in__`` structured_filters slot for id IN (?) set
    # injection produced by ``TagAssetIndexResolver`` (F6-1 / F6-2).
    # Structured domains default to True; unstructured/hybrid profiles
    # can opt out.
    id_in_supported: bool = True
    # v1.3 PR-9 — the polymorphic ``tag_asset_index.target_type`` that
    # this profile's records anchor to.  Phase A of the two-phase
    # structured executor narrows resolver lookups to a single target
    # type; the executor injects the resolved id set into
    # ``TARGET_ID_IN_KEY``.  Left as ``None`` for profiles whose join
    # shape doesn't have a clean anchor column (e.g. competency
    # task_tree with outer-joined items) — those profiles emit
    # ``tag_target_type_not_configured`` and skip Phase A.
    tag_target_type: TagAssetIndexTargetType | None = None


@dataclass(frozen=True)
class DomainDefinition:
    domain: BusinessDomain
    display_name: str
    default_channel: RetrievalChannel
    allowed_channels: tuple[RetrievalChannel, ...]
    executor_key: str
    default_query_profile_key: str
    query_profiles: tuple[QueryProfile, ...]

    def get_query_profile(self, key: str | None = None) -> QueryProfile:
        target_key = key or self.default_query_profile_key
        for profile in self.query_profiles:
            if profile.key == target_key:
                return profile
        raise KeyError(f"query profile {target_key!r} is not registered for {self.domain}")


MAJOR_DISTRIBUTION_FIELDS = (
    "year",
    "province_name",
    "major_code",
    "major_name",
    "education_level",
    "region_scope",
    "distribution_count",
)

JOB_DEMAND_FIELDS = (
    "major_name",
    "industry_name",
    "job_title",
    "city",
    "region",
    "education_requirement",
    "employment_type",
    "enterprise_size",
    "company_name",
    "salary_min",
    "salary_max",
    "job_count",
    "source_platform",
)

COMPETENCY_TASK_TREE_FIELDS = (
    "analysis_id",
    "major_name",
    "profile_id",
    "analysis_model",
    "task_code",
    "task_name",
    "content_code",
    "ability_major_category_code",
    "ability_code",
)

COMPETENCY_ABILITY_ITEM_FIELDS = (
    "analysis_id",
    "major_name",
    "profile_id",
    "analysis_model",
    "task_code",
    "task_name",
    "content_code",
    "ability_major_category_code",
    "ability_code",
)

COMPETENCY_RELATION_FIELDS = (
    "analysis_id",
    "major_name",
    "profile_id",
    "analysis_model",
    "relation_type",
    "source_type",
    "source_id",
    "target_type",
    "target_id",
)


DOMAIN_REGISTRY: dict[BusinessDomain, DomainDefinition] = {
    BusinessDomain.COURSE_TEXTBOOK: DomainDefinition(
        domain=BusinessDomain.COURSE_TEXTBOOK,
        display_name="课程教材",
        default_channel=RetrievalChannel.UNSTRUCTURED,
        allowed_channels=(RetrievalChannel.UNSTRUCTURED,),
        executor_key="unstructured_pgvector",
        default_query_profile_key="semantic_chunk",
        query_profiles=(
            QueryProfile(
                key="semantic_chunk",
                channel=RetrievalChannel.UNSTRUCTURED,
                description="教材内容语义 chunk 召回",
                executor_key="unstructured_pgvector",
                default_limit=8,
                max_limit=50,
                allowed_tag_types=("majors", "abilities", "topics"),
                # Unstructured pgvector executor uses normalized_ref_id
                # filter (see F7/F8 in reliability matrix) — no direct
                # id_in slot on the chunk table.
                id_in_supported=False,
                # PR-10: Phase A narrows tag_filters to normalized_ref
                # rows; Phase B (pgvector) filters chunks by ref set.
                tag_target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            ),
            QueryProfile(
                key="task_outline_context",
                channel=RetrievalChannel.UNSTRUCTURED,
                description="任务型教材 Task Outline 上下文召回",
                executor_key="unstructured_pgvector",
                default_limit=8,
                max_limit=50,
                allowed_tag_types=("majors", "abilities", "topics"),
                id_in_supported=False,
                # PR-7b — Phase A resolves tag_filters against OUTLINE_NODE
                # rows in tag_asset_index (written by the PR-7 outline
                # projection hook), then translates the outline_node ids
                # to chunk ids via KnowledgeChunk.knowledge_outline_node_id.
                # The chunk_ids get passed to the pgvector adapter's
                # chunk-level filter so semantic scoring only runs on
                # chunks that belong to matching outline nodes.
                tag_target_type=TagAssetIndexTargetType.OUTLINE_NODE,
            ),
        ),
    ),
    BusinessDomain.MAJOR_PROFILE: DomainDefinition(
        domain=BusinessDomain.MAJOR_PROFILE,
        display_name="专业简介",
        default_channel=RetrievalChannel.HYBRID,
        allowed_channels=(RetrievalChannel.UNSTRUCTURED, RetrievalChannel.HYBRID),
        executor_key="unstructured_pgvector",
        default_query_profile_key="major_profile_semantic",
        query_profiles=(
            QueryProfile(
                key="major_profile_semantic",
                channel=RetrievalChannel.UNSTRUCTURED,
                description="专业简介、职业面向、课程、能力等语义召回",
                executor_key="unstructured_pgvector",
                default_limit=8,
                max_limit=50,
                allowed_tag_types=("majors", "occupations", "abilities", "topics"),
                id_in_supported=False,
                tag_target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            ),
        ),
    ),
    BusinessDomain.MAJOR_DISTRIBUTION: DomainDefinition(
        domain=BusinessDomain.MAJOR_DISTRIBUTION,
        display_name="专业布点",
        default_channel=RetrievalChannel.STRUCTURED,
        allowed_channels=(RetrievalChannel.STRUCTURED,),
        executor_key="major_distribution_sql",
        default_query_profile_key="major_distribution.trend_by_year",
        query_profiles=(
            QueryProfile(
                key="major_distribution.trend_by_year",
                channel=RetrievalChannel.STRUCTURED,
                description="按年份聚合专业布点数",
                executor_key="major_distribution_sql",
                table_profile="major_distribution.v1",
                allowed_filters=MAJOR_DISTRIBUTION_FIELDS,
                allowed_group_by=("year",),
                allowed_metrics=("sum:distribution_count", "count:record"),
                allowed_tag_types=("regions", "majors", "time_ranges"),
                tag_target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            ),
            QueryProfile(
                key="major_distribution.by_province",
                channel=RetrievalChannel.STRUCTURED,
                description="按省份聚合专业布点数",
                executor_key="major_distribution_sql",
                table_profile="major_distribution.v1",
                allowed_filters=MAJOR_DISTRIBUTION_FIELDS,
                allowed_group_by=("province_name",),
                allowed_metrics=("sum:distribution_count", "count:record"),
                allowed_tag_types=("regions", "majors", "time_ranges"),
                tag_target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            ),
            QueryProfile(
                key="major_distribution.by_education_level",
                channel=RetrievalChannel.STRUCTURED,
                description="按培养层次聚合专业布点数",
                executor_key="major_distribution_sql",
                table_profile="major_distribution.v1",
                allowed_filters=MAJOR_DISTRIBUTION_FIELDS,
                allowed_group_by=("education_level",),
                allowed_metrics=("sum:distribution_count", "count:record"),
                allowed_tag_types=("regions", "majors", "time_ranges"),
                tag_target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            ),
            QueryProfile(
                key="major_distribution.record_list",
                channel=RetrievalChannel.STRUCTURED,
                description="专业布点明细记录查询",
                executor_key="major_distribution_sql",
                table_profile="major_distribution.v1",
                allowed_filters=MAJOR_DISTRIBUTION_FIELDS,
                allowed_tag_types=("regions", "majors", "time_ranges"),
                tag_target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            ),
        ),
    ),
    BusinessDomain.JOB_DEMAND: DomainDefinition(
        domain=BusinessDomain.JOB_DEMAND,
        display_name="岗位需求",
        default_channel=RetrievalChannel.STRUCTURED,
        allowed_channels=(RetrievalChannel.STRUCTURED,),
        executor_key="job_demand_sql",
        default_query_profile_key="job_demand.record_list",
        query_profiles=(
            QueryProfile(
                key="job_demand.record_list",
                channel=RetrievalChannel.STRUCTURED,
                description="岗位需求明细记录查询",
                executor_key="job_demand_sql",
                table_profile="job_demand.v1",
                allowed_filters=JOB_DEMAND_FIELDS,
                allowed_tag_types=("regions", "industries", "occupations", "time_ranges"),
                tag_target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            ),
            QueryProfile(
                key="job_demand.count_by_city",
                channel=RetrievalChannel.STRUCTURED,
                description="按城市聚合岗位需求记录数",
                executor_key="job_demand_sql",
                table_profile="job_demand.v1",
                allowed_filters=JOB_DEMAND_FIELDS,
                allowed_group_by=("city",),
                allowed_metrics=("count:record", "sum:job_count"),
                allowed_tag_types=("regions", "industries", "occupations", "time_ranges"),
                tag_target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            ),
            QueryProfile(
                key="job_demand.count_by_education",
                channel=RetrievalChannel.STRUCTURED,
                description="按学历要求聚合岗位需求记录数",
                executor_key="job_demand_sql",
                table_profile="job_demand.v1",
                allowed_filters=JOB_DEMAND_FIELDS,
                allowed_group_by=("education_requirement",),
                allowed_metrics=("count:record", "sum:job_count"),
                allowed_tag_types=("regions", "industries", "occupations", "time_ranges"),
                tag_target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            ),
            QueryProfile(
                key="job_demand.salary_distribution",
                channel=RetrievalChannel.STRUCTURED,
                description="按城市或学历聚合薪资区间",
                executor_key="job_demand_sql",
                table_profile="job_demand.v1",
                allowed_filters=JOB_DEMAND_FIELDS,
                allowed_group_by=("city", "education_requirement", "job_title"),
                allowed_metrics=(
                    "avg:salary_min",
                    "avg:salary_max",
                    "count:record",
                ),
                allowed_tag_types=("regions", "industries", "occupations", "time_ranges"),
                tag_target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            ),
            QueryProfile(
                key="job_demand.requirement_keyword",
                channel=RetrievalChannel.STRUCTURED,
                description="岗位需求项关键词明细查询",
                executor_key="job_demand_sql",
                table_profile="job_demand.v1",
                allowed_filters=(
                    *JOB_DEMAND_FIELDS,
                    "item_type",
                    "item_name",
                    "normalized_name",
                    "taxonomy_code",
                    "evidence_field",
                ),
                # requirement_item flows into ability + topic (v1.3 §2.4
                # conditional projection); other job dimensions still
                # apply at the parent-record level.
                allowed_tag_types=(
                    "regions", "industries", "occupations",
                    "abilities", "topics", "time_ranges",
                ),
                tag_target_type=TagAssetIndexTargetType.JOB_DEMAND_REQUIREMENT_ITEM,
            ),
        ),
    ),
    BusinessDomain.COMPETENCY_ANALYSIS: DomainDefinition(
        domain=BusinessDomain.COMPETENCY_ANALYSIS,
        display_name="职业能力分析",
        default_channel=RetrievalChannel.STRUCTURED,
        allowed_channels=(RetrievalChannel.STRUCTURED,),
        executor_key="competency_sql",
        default_query_profile_key="competency.task_tree",
        query_profiles=(
            QueryProfile(
                key="competency.task_tree",
                channel=RetrievalChannel.STRUCTURED,
                description="工作任务、工作内容、能力项树查询",
                executor_key="competency_sql",
                table_profile="ability_analysis.pgsd.v1",
                allowed_filters=COMPETENCY_TASK_TREE_FIELDS,
                allowed_tag_types=("occupations", "abilities", "majors"),
                # PR-13b — item is outer-joined, but ``WHERE item.id IN
                # (…)`` filters out NULL rows so the outer join
                # effectively becomes an inner join for tag_filter
                # queries.  Callers that need the full tree shape
                # should omit tag_filters.
                tag_target_type=TagAssetIndexTargetType.OCCUPATIONAL_ABILITY_ITEM,
            ),
            QueryProfile(
                key="competency.ability_items_by_category",
                channel=RetrievalChannel.STRUCTURED,
                description="按能力大类查询能力项",
                executor_key="competency_sql",
                table_profile="ability_analysis.pgsd.v1",
                allowed_filters=COMPETENCY_ABILITY_ITEM_FIELDS,
                allowed_group_by=("ability_major_category_code",),
                allowed_metrics=("count:record",),
                allowed_tag_types=("occupations", "abilities", "majors"),
                tag_target_type=TagAssetIndexTargetType.OCCUPATIONAL_ABILITY_ITEM,
            ),
            QueryProfile(
                key="competency.ability_items_by_task",
                channel=RetrievalChannel.STRUCTURED,
                description="按工作任务查询能力项",
                executor_key="competency_sql",
                table_profile="ability_analysis.pgsd.v1",
                allowed_filters=COMPETENCY_ABILITY_ITEM_FIELDS,
                allowed_group_by=("task_code",),
                allowed_metrics=("count:record",),
                allowed_tag_types=("occupations", "abilities", "majors"),
                tag_target_type=TagAssetIndexTargetType.OCCUPATIONAL_ABILITY_ITEM,
            ),
            QueryProfile(
                key="competency.relations_by_ability",
                channel=RetrievalChannel.STRUCTURED,
                description="能力分析关系查询",
                executor_key="competency_sql",
                table_profile="ability_analysis.pgsd.v1",
                allowed_filters=COMPETENCY_RELATION_FIELDS,
                allowed_tag_types=("occupations", "abilities", "majors"),
                # PR-13b — relation.target_id is polymorphic (points at
                # work_content OR ability_item OR task depending on
                # relation_type); a plain ID IN clause would be
                # semantically wrong.  PR-13b.2 will add the co-
                # condition ``AND target_type='ability_item'``.
                tag_target_type=None,
            ),
        ),
    ),
}


def get_domain_definition(domain: BusinessDomain | str) -> DomainDefinition:
    try:
        domain_key = domain if isinstance(domain, BusinessDomain) else BusinessDomain(domain)
    except ValueError as exc:
        raise KeyError(f"retrieval domain {domain!r} is not registered") from exc
    try:
        return DOMAIN_REGISTRY[domain_key]
    except KeyError as exc:
        raise KeyError(f"retrieval domain {domain_key!r} is not registered") from exc


def get_query_profile(domain: BusinessDomain | str, key: str | None = None) -> QueryProfile:
    return get_domain_definition(domain).get_query_profile(key)


def list_domain_definitions() -> list[DomainDefinition]:
    return [DOMAIN_REGISTRY[key] for key in BusinessDomain]


def domains_for_channel(channel: RetrievalChannel | str) -> list[DomainDefinition]:
    channel_key = channel if isinstance(channel, RetrievalChannel) else RetrievalChannel(channel)
    return [
        definition
        for definition in list_domain_definitions()
        if channel_key in definition.allowed_channels
    ]

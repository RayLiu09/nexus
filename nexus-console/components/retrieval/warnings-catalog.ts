/**
 * M-C v1.3 warning-code catalog.
 *
 * The retrieval orchestrator / rerank / tag resolver emit stable string
 * codes rather than translated messages, so this dictionary is the
 * single place that turns those codes into user-facing labels + tooltips.
 *
 * Consumed by:
 * - `components/retrieval/WarningsPanel.tsx` (retrieval-test panel today)
 * - Future `/search` v1.3 conversation UI (PR-search-v1_3-conversational-uplift)
 *
 * Contract with backend:
 * - Codes emitted by `nexus_app.retrieval.tag_resolver.ResolverResult.add_warning`
 * - Codes emitted by `nexus_app.retrieval.rerank` (WEIGHTED + unstructured gate ladder)
 * - Codes emitted by executors (`outline_chunk_lift_empty`, `tag_filters_empty_intersection`)
 * - Codes emitted by planner (`retrieval_plan_fallback_used`)
 *
 * When backend adds a new code, add an entry here — codes not in the
 * catalog fall through to a generic "info" tone with the raw code shown
 * so they never disappear from the UI.
 */

/**
 * Visual tone tiers, ordered by severity.  Each maps to an Antd Tag color.
 */
export type WarningTone = "info" | "notice" | "warning";

export interface WarningCatalogEntry {
  /** Short Chinese label rendered in the Tag body (max ~14 chars). */
  label: string;
  /** Longer explanation shown in the Tooltip and inline caption. */
  description: string;
  tone: WarningTone;
  /** Semantic category — reserved for future filtering. */
  category:
    | "tag_resolver"
    | "rerank"
    | "executor"
    | "planner"
    | "fallback";
}

const CATALOG: Record<string, WarningCatalogEntry> = {
  // --- Tag resolver ------------------------------------------------------
  tag_target_type_not_configured: {
    label: "target_type 未配置",
    description:
      "查询用到了 tag_filter，但 query_profile 未声明 tag_target_type — Phase A 无法收窄，回退到不过滤。",
    tone: "warning",
    category: "tag_resolver",
  },
  tag_asset_index_not_ready: {
    label: "tag 索引尚未就绪",
    description:
      "tag_asset_index 表不可读（可能未运行 alembic upgrade 或后端切换未完成），resolver 返回空结果并跳过。",
    tone: "warning",
    category: "tag_resolver",
  },
  tag_filters_empty_intersection: {
    label: "tag 过滤交集为空",
    description:
      "多个 required tag 桶的 AND 交集为空 — 没有资产同时满足全部条件，Phase A 空短路。",
    tone: "warning",
    category: "tag_resolver",
  },
  optional_bucket_empty: {
    label: "可选桶未命中",
    description:
      "某个 optional=true 的 tag 桶未命中；已从 combine 中丢弃而不 collapse 整个 AND。",
    tone: "info",
    category: "tag_resolver",
  },
  target_ids_truncated: {
    label: "候选被截断",
    description:
      "命中量超过 hard_limit（默认 10 000）— 已按稳定顺序截断；如需完整集合，请细化 query。",
    tone: "notice",
    category: "tag_resolver",
  },
  embedding_lag_bypass: {
    label: "embedding 尚在补齐",
    description:
      "L4 语义层扫描到候选 tag 行，但它们的 tag_embedding 仍为空 — 已跳过 L4。运行 backfill_tag_embeddings.py 可补齐。",
    tone: "notice",
    category: "tag_resolver",
  },
  hnsw_query_failed: {
    label: "L4 查询失败",
    description:
      "L4 SQL / HNSW 索引查询抛错，已回退到只用 L1/L1.5/L2 的结果。错误详情见后端日志。",
    tone: "warning",
    category: "tag_resolver",
  },
  l4_no_embedding_client: {
    label: "L4 无 embedding 客户端",
    description:
      "调用侧要求 L4，但未注入 embedding_client — L4 是无操作（no-op）。测试环境常见。",
    tone: "info",
    category: "tag_resolver",
  },
  l4_no_query_vectors: {
    label: "L4 未返回向量",
    description:
      "embedding 服务返回空 vectors 数组 — L4 无法比对，已跳过。",
    tone: "warning",
    category: "tag_resolver",
  },
  l4_embedding_call_failed: {
    label: "L4 embedding 失败",
    description:
      "embedding 服务调用抛错，L4 跳过；L1/L1.5/L2 的结果仍会返回。",
    tone: "warning",
    category: "tag_resolver",
  },
  layer_l3_not_implemented: {
    label: "L3 尚未落地",
    description:
      "调用侧要求 L3（标准编码字典）匹配，但目前仍是 stub；已跳过该层。",
    tone: "info",
    category: "tag_resolver",
  },
  layer_l5_chunk_fallback_out_of_scope: {
    label: "L5 未启用",
    description:
      "L5 chunk-level 语义回退已显式关闭；只走 L1/L1.5/L2/L4。",
    tone: "info",
    category: "tag_resolver",
  },
  layer_l2_not_implemented: {
    label: "L2 已下线（legacy）",
    description:
      "旧告警：L2 别名字典尚未落地。当前 L2 已经 live 于 dim_tag_alias — 若仍看到，说明后端还在 legacy 分支。",
    tone: "info",
    category: "tag_resolver",
  },

  // --- Rerank (WEIGHTED + unstructured) ----------------------------------
  weighted_rerank_applied: {
    label: "WEIGHTED 已重排",
    description:
      "PR-13 WEIGHTED combine op 已生效 — records 按 target_scores 汇总重排。",
    tone: "info",
    category: "rerank",
  },
  weighted_rerank_disabled_by_config: {
    label: "WEIGHTED 已关闭",
    description:
      "WEIGHTED 重排被配置显式关闭（kill switch），records 保持原始顺序。",
    tone: "info",
    category: "rerank",
  },
  weighted_rerank_skipped_no_target_scores: {
    label: "WEIGHTED 无分数",
    description:
      "候选没有 target_scores — WEIGHTED 无输入可算，已跳过；结果保持 planner 顺序。",
    tone: "info",
    category: "rerank",
  },
  weighted_rerank_suppressed_by_order_by: {
    label: "ORDER BY 屏蔽 WEIGHTED",
    description:
      "SQL 明确带了 ORDER BY，WEIGHTED 不再介入 — 尊重用户的排序意图。",
    tone: "info",
    category: "rerank",
  },
  unstructured_rerank_applied: {
    label: "非结构化重排已生效",
    description:
      "PR-7 unstructured rerank 已生效 — chunk 结果按 target_scores 重新排序。",
    tone: "info",
    category: "rerank",
  },
  unstructured_rerank_disabled_by_config: {
    label: "非结构化重排关闭",
    description:
      "unstructured rerank 被 kill switch 关闭 — chunks 保持召回顺序。",
    tone: "info",
    category: "rerank",
  },
  unstructured_rerank_skipped_no_target_scores: {
    label: "无 target_scores",
    description:
      "没有 target_scores 可用（tag_asset_index 无匹配 anchor），rerank 跳过；chunks 按召回顺序返回。",
    tone: "info",
    category: "rerank",
  },
  unstructured_rerank_skipped_outline_anchor: {
    label: "outline anchor 缺失",
    description:
      "unstructured 走的是 outline 路径但拿不到 outline_node anchor — rerank 跳过。",
    tone: "notice",
    category: "rerank",
  },
  unstructured_rerank_skipped_single_item: {
    label: "只有一个候选",
    description:
      "候选数量 ≤ 1，rerank 没有意义 — 跳过。",
    tone: "info",
    category: "rerank",
  },
  unstructured_rerank_skipped_zero_weights: {
    label: "权重全为 0",
    description:
      "所有 target_scores 的权重都是 0 — rerank 无净效果，跳过。",
    tone: "info",
    category: "rerank",
  },

  // --- Executor ----------------------------------------------------------
  outline_chunk_lift_empty: {
    label: "outline chunk 反查为空",
    description:
      "task_outline_context 命中了 outline_node，但对应的 knowledge_chunk 反查为空 — 空集短路。章节可能尚未切片。",
    tone: "warning",
    category: "executor",
  },

  // --- Planner / fallback ------------------------------------------------
  retrieval_plan_fallback_used: {
    label: "planner 走 fallback",
    description:
      "LLM planner 输出无法通过 schema 校验，已回退到规则-based 兜底 plan。质量降级但结果仍可用。",
    tone: "warning",
    category: "planner",
  },
  tag_filter_bucket_out_of_domain: {
    label: "桶不在 domain 白名单",
    description:
      "查询桶不在 query_profile.allowed_tag_types 白名单里 — sql_guardrails 已拦截，仅作提示。",
    tone: "warning",
    category: "fallback",
  },
  tag_filter_resolver_error: {
    label: "resolver 抛错",
    description:
      "Phase A tag resolver 抛错（bucket 格式非法或桶名未知）— 视为空 bucket 处理。",
    tone: "warning",
    category: "fallback",
  },
};

/**
 * Some codes carry inline detail after a `:` separator, e.g.
 * ``tag_filter_resolver_error:regions:bucket_out_of_domain``.  The
 * catalog is keyed by the head token; look up by the first segment.
 */
export function extractCode(raw: string): string {
  const idx = raw.indexOf(":");
  return idx === -1 ? raw : raw.slice(0, idx);
}

export function lookupWarning(raw: string): WarningCatalogEntry | null {
  return CATALOG[extractCode(raw)] ?? null;
}

/**
 * The full catalog, exported for tests and downstream tooling.  Consumers
 * should prefer {@link lookupWarning} for single-code lookups.
 */
export const WARNING_CATALOG: Readonly<Record<string, WarningCatalogEntry>> = CATALOG;

/**
 * Antd Tag `color` value per tone.  Kept close to the catalog so any UI
 * component using the catalog renders with consistent styling.
 */
export const TONE_TO_TAG_COLOR: Readonly<Record<WarningTone, string>> = {
  info: "blue",
  notice: "gold",
  warning: "orange",
};

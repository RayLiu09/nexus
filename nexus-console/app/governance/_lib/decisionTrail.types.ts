/**
 * 决策追踪相关契约（与后端 GovernanceResultRead + redact_governance_result 对齐）。
 *
 * - decision_trail 是按字段（classification / level / tags / quality）逐条记录的裁定证据。
 * - 后端按 view 做角色化脱敏（见 nexus_app/governance/redaction.py）：
 *   - full：业务/管理员可见 ai_suggestion / ai_confidence / threshold_check 内部值
 *   - operator：仅最终值 + adoption_status + review_reason；与 final_value 不同的
 *     ai_suggestion 会替换为 "***redacted***"
 *   - public：decision_trail 直接返回 []
 */

/** decision_trail 字段维度（与后端 DecisionTrailEntry.field_name 一致） */
export type DecisionField = "classification" | "level" | "tags" | "quality";

/** 单条字段裁定记录（按 view 不同部分字段可能缺失） */
export interface DecisionTrailEntry {
  field_name: DecisionField;
  ai_suggestion?: unknown; // full view 可见；operator 在 ≠ final 时为 "***redacted***"
  ai_confidence?: number; // full view 可见
  threshold_check: Record<string, unknown>;
  final_value: unknown;
  adoption_status: AdoptionStatus;
  review_reason: string | null;
}

export type AdoptionStatus = "auto_adopted" | "review_required" | "rejected";

/** 决策追踪视图角色（与后端 _VALID_TRAIL_VIEWS 对齐） */
export type DecisionTrailView = "full" | "operator" | "public";

/** GovernanceResult 序列化结构（GovernanceResultRead + redaction 应用后的形态） */
export interface GovernanceResultRead {
  id: string;
  normalized_ref_id: string;
  ai_run_id: string | null;
  classification: string | null;
  level: string | null;
  tags: string[];
  org_scope: string | null;
  index_admission: boolean;
  quality_summary: Record<string, unknown> | null;
  decision_trail: DecisionTrailEntry[];
  rules_schema_version: string | null;
  rules_content_hash: string | null;
  status: string;
  created_by: string | null;
  trace_id: string | null;
  created_at: string;
  updated_at: string;
}

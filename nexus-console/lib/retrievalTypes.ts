/**
 * Canonical M-C v1.3 retrieval wire types.
 *
 * Sourced from the backend `KnowledgeRetrievalResponse` envelope
 * exposed by `POST /internal/v1/knowledge-retrieval/query` and
 * `/knowledge-retrieval/plans`. Both `/retrieval-test` and `/search`
 * consume these types; playground-specific wire types (SearchResponse,
 * QaResponse) stay in `app/search/_lib/searchTypes.ts`.
 */

export type RetrievalStatus =
  | "planned"
  | "running"
  | "completed"
  | "needs_clarification"
  | "partial"
  | "failed";

export type RetrievalStepStatus =
  | "pending"
  | "running"
  | "completed"
  | "needs_clarification"
  | "blocked"
  | "failed"
  | "skipped";

export interface RetrievalIntent {
  business_domains: string[];
  retrieval_channels: string[];
  question_type: string;
  output_expectation?: string[];
  constraints?: Record<string, unknown>;
  confidence: number;
  confidence_threshold: number;
  candidate_intents?: Array<Record<string, unknown>>;
  missing_constraints?: string[];
  suggested_refinements?: string[];
}

export interface RetrievalSubQuery {
  query_id: string;
  channel: string;
  domain: string;
  purpose: string;
  query_text: string;
  structured_plan?: Record<string, unknown> | null;
  unstructured_plan?: Record<string, unknown> | null;
}

export interface RetrievalPlan {
  original_query: string;
  sub_queries: RetrievalSubQuery[];
  merge_goal: string;
  /**
   * v1.3 §5.5 friendly_view — planner-emitted natural-language projection
   * meant for direct rendering in the conversation UI. Chinese labels
   * are sourced from `nexus_app.retrieval.display_labels`; the console
   * consumes them verbatim without client-side derivation.
   */
  friendly_view?: FriendlyRetrievalPlanView | null;
}

// ---------------------------------------------------------------------------
// v1.3 §5.5 friendly_view contract (mirror of `nexus_app.retrieval.tag_schemas`)
// ---------------------------------------------------------------------------

export type ConfidenceLevel = "high" | "medium" | "low";

export type FriendlySubQueryStatus =
  | "pending"
  | "running"
  | "completed"
  | "blocked"
  | "degraded"
  | "failed"
  | "skipped";

export type FriendlySubQueryAction =
  | "rerun"
  | "cancel"
  | "skip"
  | "view_details"
  | "view_raw";

export type EvidenceStrength = "strong" | "medium" | "weak";

export interface FriendlyDisplayConstraint {
  label: string;
  value: string;
  confidence?: number | null;
  source_display: string;
}

export interface FriendlyIntentSummary {
  natural_language: string;
  business_domains_display: string[];
  identified_constraints: FriendlyDisplayConstraint[];
  unresolved_terms: string[];
  confidence: number;
  confidence_level: ConfidenceLevel;
  clarification_suggestions: string[];
}

export interface FriendlyDisplayFilter {
  label: string;
  values: string[];
  match_strategy_display: string;
  is_optional: boolean;
  is_from_binding?: boolean | null;
  binding_source_display?: string | null;
}

export interface FriendlySubQueryResult {
  hit_count: number;
  hit_count_display: string;
  duration_ms: number;
  duration_display: string;
  match_layer_summary: string;
  evidence_strength: EvidenceStrength;
  evidence_strength_display: string;
  warnings: string[];
}

export interface FriendlySubQueryCard {
  query_id: string;
  display_index: string;
  title: string;
  purpose_display: string;
  channel_display: string;
  domain_display: string;
  depends_on_display: string[];
  filter_summary: FriendlyDisplayFilter[];
  status: FriendlySubQueryStatus;
  status_display: string;
  degraded_reasons: string[];
  result_summary?: FriendlySubQueryResult | null;
  actions_available: FriendlySubQueryAction[];
}

export interface FriendlyOverallSummary {
  total_sub_queries: number;
  max_depth: number;
  estimated_duration_ms?: number | null;
  combine_summary: string;
}

export interface FriendlyRetrievalPlanView {
  intent_summary: FriendlyIntentSummary;
  sub_query_cards: FriendlySubQueryCard[];
  overall: FriendlyOverallSummary;
}

export interface RetrievalSourceRef {
  source_ref_id: string;
  channel: string;
  domain: string;
  asset_id?: string | null;
  asset_version_id?: string | null;
  normalized_ref_id?: string | null;
  chunk_id?: string | null;
  record_ref?: string | null;
  locator?: Record<string, unknown>;
  score?: number | null;
  metadata?: Record<string, unknown>;
}

export interface RetrievalResult {
  query_id: string;
  channel: string;
  domain: string;
  status: RetrievalStepStatus;
  result_shape?: string | null;
  items?: Array<Record<string, unknown>>;
  records?: Array<Record<string, unknown>>;
  aggregations?: Array<Record<string, unknown>>;
  source_refs?: RetrievalSourceRef[];
  elapsed_ms?: number | null;
  error_message?: string | null;
}

export interface RetrievalConversationStep {
  step: string;
  status: RetrievalStepStatus;
  title: string;
  display_to_user: boolean;
  message?: string | null;
  progress?: Record<string, unknown>;
  display_payload?: Record<string, unknown>;
}

export interface RetrievalClarification {
  message: string;
  suggested_refinements?: string[];
  missing_constraints?: string[];
  candidate_intents?: Array<Record<string, unknown>>;
}

export interface RetrievalSummary {
  format: string;
  content: string;
  source_ref_ids: string[];
  model_alias?: string | null;
  warnings?: string[];
}

export interface KnowledgeRetrievalResponse {
  query_id: string;
  status: RetrievalStatus;
  original_query: string;
  intent: RetrievalIntent;
  retrieval_plan?: RetrievalPlan | null;
  retrieval_results: RetrievalResult[];
  llm_summary?: RetrievalSummary | null;
  markdown?: string | null;
  access_scope: "all_assets";
  conversation_steps: RetrievalConversationStep[];
  source_refs: RetrievalSourceRef[];
  clarification?: RetrievalClarification | null;
  warnings: string[];
}

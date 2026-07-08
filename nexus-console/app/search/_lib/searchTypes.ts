/**
 * Wire types specific to the search / QA playground envelopes.
 *
 * Shared chunk-citation types (LocatorInfo, KnowledgeChunkHit, RawDownloadResponse)
 * live in `lib/chunkTypes.ts` and are used by both this playground and the
 * asset detail lineage view.
 */
import type { KnowledgeChunkHit } from "@/lib/chunkTypes";

export interface SearchResponse {
  query: string;
  kb: string | null;
  results: KnowledgeChunkHit[];
  count: number;
  caller_id: string;
}

export interface QaResponse {
  question: string;
  kb: string | null;
  caller_id: string;
  answer: string;
  /** P0 derived: max(sources[].score). Null when no scored sources. */
  answer_confidence: number | null;
  sources: KnowledgeChunkHit[];
}

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

/** Knowledge type option (Select uses only code + name). */
export interface KnowledgeTypeOption {
  code: string;
  name: string;
}

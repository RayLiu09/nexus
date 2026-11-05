/**
 * B8 (§10 Batch B3b) — wire types for /internal/v1/query response.
 *
 * Kept in a client-safe module so the proxy fetcher and result renderer
 * share one source of truth without dragging server-only imports into
 * the client bundle.
 */

export type QueryRouterIntent =
  | "public_tools"
  | "scenario_1"
  | "scenario_2"
  | "scenario_3"
  | "scenario_4"
  | "scenario_5"
  | "unknown";

export type QueryRouterFallbackReason =
  | (string & {})
  | "unknown_fallback"
  | "scenario_5_template_not_implemented"
  | null;

export type StepId = string;

export type StepStatus = "running" | "completed" | "failed" | "cancelled";

export interface StepPayload {
  id: StepId;
  status: StepStatus;
  label: string;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  started_at_ms: number;
  completed_at_ms: number;
  error: string | null;
  tool_name?: string | null;
  action_type?: string | null;
  parent_action_id?: string | null;
}

export interface QueryRouterAuditSummary {
  route?: string;
  caller_type?: string;
  intent?: QueryRouterIntent;
  intent_confidence?: number;
  invoked_tools?: string[];
  generated_ratio?: number;
  template_id?: string | null;
  query_route?: "v2" | "public_tools_v1";
  chart_hallucination_ids?: string[];
  chart_unused_ids?: string[];
  query_hash?: string;
  dispatch_fallback?: string | null;
  [extra: string]: unknown;
}

export interface ExternalWebResult {
  source_type: "external_web";
  provider: string;
  title: string;
  url: string;
  domain: string;
  snippet: string | null;
  published_at: string | null;
  retrieved_at: string;
  rank: number;
}

export interface QueryRouterResponse {
  markdown: string;
  intent: QueryRouterIntent;
  intent_confidence: number;
  invoked_tools: string[];
  fallback_reason: QueryRouterFallbackReason;
  warnings: string[];
  audit_summary: QueryRouterAuditSummary;
  external_web_results: ExternalWebResult[];
  citations?: QueryCitation[];
}

export interface QueryCitation {
  citation_id: string;
  source_type: "document" | "record" | "aggregate" | "external_web";
  title: string;
  excerpt: string;
  tool: string;
  evidence_level?: "metadata" | "content" | "record" | "aggregate" | "external_web";
  url?: string | null;
  record_id?: string | null;
  asset_id?: string | null;
  version_id?: string | null;
  normalized_ref_id?: string | null;
  chunk_id?: string | null;
  section_id?: string | null;
  locator?: Record<string, unknown>;
  scope?: Record<string, unknown>;
  published_at?: string | null;
  collected_at?: string | null;
  truncated?: boolean;
  next_offset?: number | null;
}

export interface ProxySuccessEnvelope<T> {
  ok: true;
  status: number;
  data: T;
  traceId: string | null;
}

export interface ProxyErrorEnvelope {
  ok: false;
  status: number;
  message: string;
  traceId?: string | null;
}

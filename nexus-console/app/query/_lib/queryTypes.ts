/**
 * B8 (§10 Batch B3b) — wire types for /internal/v1/query response.
 *
 * Kept in a client-safe module so the proxy fetcher and result renderer
 * share one source of truth without dragging server-only imports into
 * the client bundle.
 */

export type QueryRouterIntent =
  | "scenario_1"
  | "scenario_2"
  | "scenario_3"
  | "scenario_4"
  | "scenario_5"
  | "unknown";

export type QueryRouterFallbackReason =
  | "unknown_fallback"
  | "scenario_5_template_not_implemented"
  | null;

export type StepId =
  | "intent_classify"
  | "param_extract"
  | "dispatch"
  | "compose"
  | "unknown_fallback"
  | "scenario_5_placeholder";

export type StepStatus = "running" | "completed" | "failed";

export interface StepPayload {
  id: StepId;
  status: StepStatus;
  label: string;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  started_at_ms: number;
  completed_at_ms: number;
  error: string | null;
}

export interface QueryRouterAuditSummary {
  route?: string;
  caller_type?: string;
  intent?: QueryRouterIntent;
  intent_confidence?: number;
  invoked_tools?: string[];
  generated_ratio?: number;
  template_id?: string | null;
  query_route?: "v2";
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

export type QueryField = {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  anyOf?: QueryField[];
};

export type QuerySchema = {
  type?: string;
  properties?: Record<string, QueryField>;
  required?: string[];
};

export type SyncProvider = {
  provider_code: string;
  display_name: string;
  api_server_url: string;
  tenant_name: string;
  credential_status: string;
  adapter_version: string;
  status: string;
  query_schema: QuerySchema;
};

export type SyncPlan = {
  id: string;
  name: string;
  provider_code: string;
  status: "active" | "paused" | "deleted";
  frequency: string;
  query_config: Record<string, unknown>;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
};

export type SyncRun = {
  id: string;
  data_sync_config_id: string;
  provider_code: string;
  adapter_version: string;
  status: string;
  external_task_id: string | null;
  processed_count: number;
  success_count: number;
  failure_count: number;
  skipped_count: number;
  failure_summary: string | null;
  queued_at: string;
  updated_at: string;
};

export type SyncAuditEvent = {
  id: string;
  event_type: string;
  actor_type: string | null;
  actor_id: string | null;
  trace_id: string | null;
  summary: Record<string, string>;
  created_at: string;
};

export type SyncRunLogs = {
  run_id: string;
  plan_id: string;
  provider_code: string;
  status: string;
  adapter_version: string;
  query_hash: string;
  query_summary: string;
  external_task_id: string | null;
  processed_count: number;
  success_count: number;
  failure_count: number;
  skipped_count: number;
  failure_summary: string | null;
  last_control_action: string | null;
  last_control_requested_at: string | null;
  last_control_operator_id: string | null;
  created_at: string;
  updated_at: string;
  audit_total: number;
  audit_events: SyncAuditEvent[];
};

export type QueryField = {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  "x-enum-labels"?: string[];
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  anyOf?: QueryField[];
  items?: QueryField;
};

export type JobCollectionCategory = {
  id: string;
  name: string;
  titles: { id: string; name: string }[];
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
  tenant_name: string | null;
  auth_mode?: "none" | "tenant_token";
  execution_mode?: "paged_pull" | "external_job";
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
  external_status: string | null;
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

// Province dictionary verified on 2026-10-26; user-approved years extend to 2035.
// Fixed options: no runtime dictionary request.
export const MOE_YEARS = [2035, 2034, 2033, 2032, 2031, 2030, 2029, 2028, 2027, 2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016, 2015, 2014, 2013];
export const MOE_PROVINCES = [
  {
    "code": "BJ",
    "name": "北京市"
  },
  {
    "code": "TJ",
    "name": "天津市"
  },
  {
    "code": "HeB",
    "name": "河北省"
  },
  {
    "code": "SX",
    "name": "山西省"
  },
  {
    "code": "NM",
    "name": "内蒙古自治区"
  },
  {
    "code": "LN",
    "name": "辽宁省"
  },
  {
    "code": "JL",
    "name": "吉林省"
  },
  {
    "code": "HLJ",
    "name": "黑龙江省"
  },
  {
    "code": "SH",
    "name": "上海市"
  },
  {
    "code": "JS",
    "name": "江苏省"
  },
  {
    "code": "ZJ",
    "name": "浙江省"
  },
  {
    "code": "AH",
    "name": "安徽省"
  },
  {
    "code": "FJ",
    "name": "福建省"
  },
  {
    "code": "JX",
    "name": "江西省"
  },
  {
    "code": "SD",
    "name": "山东省"
  },
  {
    "code": "HeN",
    "name": "河南省"
  },
  {
    "code": "HuB",
    "name": "湖北省"
  },
  {
    "code": "HuN",
    "name": "湖南省"
  },
  {
    "code": "GD",
    "name": "广东省"
  },
  {
    "code": "GX",
    "name": "广西壮族自治区"
  },
  {
    "code": "HN",
    "name": "海南省"
  },
  {
    "code": "CQ",
    "name": "重庆市"
  },
  {
    "code": "SC",
    "name": "四川省"
  },
  {
    "code": "GZ",
    "name": "贵州省"
  },
  {
    "code": "YN",
    "name": "云南省"
  },
  {
    "code": "XZ",
    "name": "西藏自治区"
  },
  {
    "code": "SXS",
    "name": "陕西省"
  },
  {
    "code": "GS",
    "name": "甘肃省"
  },
  {
    "code": "QH",
    "name": "青海省"
  },
  {
    "code": "NX",
    "name": "宁夏回族自治区"
  },
  {
    "code": "XJ",
    "name": "新疆维吾尔自治区"
  },
  {
    "code": "XJBT",
    "name": "新疆生产建设兵团"
  }
];

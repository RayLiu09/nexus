import { apiBaseUrl } from "./api";

export type GovernanceRules = Record<string, unknown>;

export type RulesSummary = {
  schema_version: string;
  classifications: number;
  levels: number;
  tags: number;
  quality_dimensions: number;
  /**
   * 仅当保存时携带 recompute=true 时由后端填充：
   * 列出被重新调度回 processing 的版本数、被记录但未自动重跑的版本数等。
   * 与 nexus_app/governance/recompute.py:trigger_recompute 返回值结构对齐。
   */
  recompute?: RecomputeSummary | null;
};

export type RecomputeScope = "review_required_only" | "all_affected";

export interface RecomputeSummary {
  scope: RecomputeScope;
  affected_total: number;
  rescheduled_count: number;
  available_skipped_count: number;
  rescheduled_version_ids: string[];
  available_skipped_version_ids: string[];
}

export interface SaveRulesOptions {
  recompute?: boolean;
  recomputeScope?: RecomputeScope;
}

export type FetchRulesResult = {
  ok: true;
  data: GovernanceRules;
  etag: string;
} | {
  ok: false;
  error: string;
};

export type SaveRulesResult = {
  ok: true;
  summary: RulesSummary;
  etag: string;
} | {
  ok: false;
  status: number;
  error: string;
  currentRules?: GovernanceRules;
  currentEtag?: string;
};

export async function fetchGovernanceRules(): Promise<FetchRulesResult> {
  try {
    const res = await fetch(`${apiBaseUrl()}/v1/admin/governance-rules`, {
      cache: "no-store",
    });
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}` };
    }
    const json = await res.json();
    const etag = res.headers.get("ETag") ?? "";
    return { ok: true, data: json.data as GovernanceRules, etag };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function saveGovernanceRules(
  rules: GovernanceRules,
  ifMatch: string,
  options: SaveRulesOptions = {},
): Promise<SaveRulesResult> {
  try {
    const params = new URLSearchParams();
    if (options.recompute) {
      params.set("recompute", "true");
      params.set(
        "recompute_scope",
        options.recomputeScope ?? "review_required_only",
      );
    }
    const queryString = params.toString();
    const url = `${apiBaseUrl()}/v1/admin/governance-rules${queryString ? `?${queryString}` : ""}`;

    const res = await fetch(url, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "If-Match": ifMatch,
      },
      body: JSON.stringify(rules),
      cache: "no-store",
    });

    if (res.status === 409) {
      const body = await res.json();
      return {
        ok: false,
        status: 409,
        error: body.detail ?? "已被他人更新",
        currentRules: body.current_rules as GovernanceRules | undefined,
        currentEtag: body.current_etag as string | undefined,
      };
    }

    if (res.status === 428) {
      return { ok: false, status: 428, error: "缺少 If-Match 头" };
    }

    const json = await res.json();
    if (!res.ok) {
      return {
        ok: false,
        status: res.status,
        error: json?.detail ?? `HTTP ${res.status}`,
      };
    }

    const etag = res.headers.get("ETag") ?? "";
    return { ok: true, summary: json.data as RulesSummary, etag };
  } catch (e) {
    return {
      ok: false,
      status: 0,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

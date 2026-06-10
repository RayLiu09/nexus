import { apiBaseUrl } from "./api";

export type GovernanceRules = Record<string, unknown>;

export type RulesSummary = {
  schema_version: string;
  classifications: number;
  levels: number;
  tags: number;
  quality_dimensions: number;
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

export interface GovernanceRulesVersion {
  id: string;
  version: number;
  schema_version: string;
  status: string;
  change_summary: string | null;
  classifications_count: number;
  created_at: string | null;
  created_by: string | null;
}

export interface GovernanceRulesVersionDetail extends GovernanceRulesVersion {
  rules_content: GovernanceRules | null;
}

export async function fetchGovernanceRules(): Promise<{
  ok: true;
  data: GovernanceRules;
} | {
  ok: false;
  error: string;
}> {
  try {
    const res = await fetch(`${apiBaseUrl()}/api/admin/governance-rules`, {
      cache: "no-store",
    });
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}` };
    }
    const json = await res.json();
    return { ok: true, data: json.data as GovernanceRules };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function saveGovernanceRules(
  rules: GovernanceRules,
  options: SaveRulesOptions = {},
): Promise<{
  ok: true;
  summary: RulesSummary;
} | {
  ok: false;
  status: number;
  error: string;
}> {
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
    const url = `${apiBaseUrl()}/api/admin/governance-rules${queryString ? `?${queryString}` : ""}`;

    const res = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rules),
      cache: "no-store",
    });

    const json = await res.json();
    if (!res.ok) {
      return {
        ok: false,
        status: res.status,
        error: json?.detail ?? `HTTP ${res.status}`,
      };
    }

    return { ok: true, summary: json.data as RulesSummary };
  } catch (e) {
    return {
      ok: false,
      status: 0,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

export async function fetchGovernanceRulesVersions(): Promise<{
  ok: true;
  versions: GovernanceRulesVersion[];
} | {
  ok: false;
  error: string;
}> {
  try {
    const res = await fetch(
      `${apiBaseUrl()}/api/admin/governance-rules/versions`,
      { cache: "no-store" },
    );
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}` };
    }
    const json = await res.json();
    return { ok: true, versions: json.data as GovernanceRulesVersion[] };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function fetchGovernanceRulesVersion(
  versionId: string,
): Promise<{
  ok: true;
  version: GovernanceRulesVersionDetail;
} | {
  ok: false;
  error: string;
}> {
  try {
    const res = await fetch(
      `${apiBaseUrl()}/api/admin/governance-rules/versions/${versionId}`,
      { cache: "no-store" },
    );
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}` };
    }
    const json = await res.json();
    return { ok: true, version: json.data as GovernanceRulesVersionDetail };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

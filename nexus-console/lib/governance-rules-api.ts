import { apiBaseUrl } from "./api";

export type GovernanceRules = Record<string, unknown>;

export type RulesSummary = {
  schema_version: string;
  classifications: number;
  levels: number;
  tags: number;
  quality_dimensions: number;
};

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
  ifMatch: string
): Promise<SaveRulesResult> {
  try {
    const res = await fetch(`${apiBaseUrl()}/v1/admin/governance-rules`, {
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

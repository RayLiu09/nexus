import type { Asset } from "@/lib/api";

export type AssetWithMeta = Asset & {
  domain?: string | null;
  domain_name?: string | null;
  level?: string;
  current_version_no?: number | null;
  current_normalized_ref_id?: string | null;
  latest_version_id?: string | null;
  latest_version_no?: number | null;
  latest_normalized_ref_id?: string | null;
  quality_score?: number | null;
  governance_status?: string | null;
  index_status?: string | null;
};

// ── Stats (derived client-side, pre-aggregate-endpoint fallback) ──────────

export type AssetStats = {
  available: number;
  reviewRequired: number;
  currentNormalizedRefs: number;
  staleIndex: number;
  l3l4: number;
  autoAdoptionRate: number;
};

export type DomainDistItem = { domain: string; label: string; count: number };

export const DOMAIN_LABELS: Record<string, string> = {
  industry_policy: "产业政策",
  industry_report: "产业报告",
  sector_report: "行业报告",
  job_demand: "岗位需求数据",
  competency_analysis: "职业能力分析表",
  vocational_certificate: "职业类证书",
  teaching_standard: "专业教学标准",
  major_distribution: "专业布点数",
  talent_demand_report: "专业人才需求报告",
  talent_training_plan: "人才培养方案",
  major_profile: "专业简介",
  course_textbook: "教材",
};

const DOMAIN_ALIASES: Record<string, string> = {
  program_profile: "major_profile",
};

export const DOMAIN_OPTIONS = Object.entries(DOMAIN_LABELS).map(([value, label]) => ({
  value,
  label,
}));

export function canonicalDomain(code: string | null | undefined): string | null {
  if (!code) return null;
  return DOMAIN_ALIASES[code] ?? code;
}

export function domainLabel(code: string | null | undefined, name?: string | null): string {
  const canonical = canonicalDomain(code);
  if (canonical && DOMAIN_LABELS[canonical]) return DOMAIN_LABELS[canonical];
  if (name && name !== "program_profile") return name;
  if (!canonical) return "-";
  return canonical;
}

// ── Aggregate endpoint contract: GET /v1/assets/summary ──────────────────

/** Response from GET /v1/assets/summary — pre-computed aggregate stats. */
export interface AssetSummary {
  total: number;
  available: number;
  review_required: number;
  current_normalized_refs: number;
  stale_index: number;
  l3l4: number;
  auto_adoption_rate: number;
  domain_distribution: { domain: string; name?: string | null; count: number }[];
}

/** Map AssetSummary to the shape AssetsSummary component expects. */
export function toAssetStats(s: AssetSummary): AssetStats {
  return {
    available: s.available,
    reviewRequired: s.review_required,
    currentNormalizedRefs: s.current_normalized_refs,
    staleIndex: s.stale_index,
    l3l4: s.l3l4,
    autoAdoptionRate: s.auto_adoption_rate,
  };
}

/** Map AssetSummary.domain_distribution to the shape DomainDistribution expects. */
export function toDomainDistItems(s: AssetSummary): DomainDistItem[] {
  return s.domain_distribution.map((item) => ({
    domain: item.domain,
    label: domainLabel(item.domain, item.name),
    count: item.count,
  }));
}

export function deriveStats(assets: AssetWithMeta[]): AssetStats {
  let available = 0;
  let reviewRequired = 0;
  let currentNormalizedRefs = 0;
  let staleIndex = 0;
  let l3l4 = 0;
  let autoAdopted = 0;
  let totalDecisions = 0;

  for (const a of assets) {
    if (a.status === "available") available++;
    if (a.status === "review_required") reviewRequired++;
    if (a.current_normalized_ref_id) currentNormalizedRefs++;
    if (a.index_status === "stale") staleIndex++;
    if (a.level === "L3" || a.level === "L4") l3l4++;
    if (a.governance_status) {
      totalDecisions++;
      if (a.governance_status === "auto_passed" || a.governance_status === "auto_adopted")
        autoAdopted++;
    }
  }

  const autoAdoptionRate =
    totalDecisions > 0 ? Math.round((autoAdopted / totalDecisions) * 100) : 0;

  return { available, reviewRequired, currentNormalizedRefs, staleIndex, l3l4, autoAdoptionRate };
}

export function deriveDomainDist(assets: AssetWithMeta[]): DomainDistItem[] {
  const counts: Record<string, number> = {};
  for (const a of assets) {
    const domain = canonicalDomain(a.domain);
    if (domain) counts[domain] = (counts[domain] ?? 0) + 1;
  }
  return Object.entries(counts).map(([domain, count]) => ({
    domain,
    label: domainLabel(domain),
    count,
  }));
}

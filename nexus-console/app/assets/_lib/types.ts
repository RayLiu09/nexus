import type { DocumentAsset } from "@/lib/api";

export type AssetWithMeta = DocumentAsset & {
  domain?: string;
  level?: string;
  current_version_no?: string;
  current_normalized_ref_id?: string;
  quality_score?: number;
  governance_status?: string;
  index_status?: string;
};

export type AssetStats = {
  available: number;
  reviewRequired: number;
  currentNormalizedRefs: number;
  staleIndex: number;
  l3l4: number;
  autoAdoptionRate: number;
};

export type DomainDistItem = { domain: string; label: string; count: number };

const DOMAIN_LABELS: Record<string, string> = {
  D1: "教学资源",
  D2: "人才培养",
  D3: "科研数据",
  D4: "产教融合",
  D5: "政策法规",
  D6: "综合管理",
};

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
    if (a.domain) counts[a.domain] = (counts[a.domain] ?? 0) + 1;
  }
  return Object.keys(DOMAIN_LABELS).map((d) => ({
    domain: d,
    label: DOMAIN_LABELS[d],
    count: counts[d] ?? 0,
  }));
}

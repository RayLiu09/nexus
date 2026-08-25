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

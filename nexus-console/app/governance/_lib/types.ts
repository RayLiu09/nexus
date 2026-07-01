import type { TagDictionary } from "@/lib/tagLabels";
import { tagLabels } from "@/lib/tagLabels";
import { extractGovernanceTags } from "@/lib/governance-tags";
import {
  getRunQualityScore,
  isReviewPendingRun,
  selectCurrentQualityCalibrationRuns,
  selectCurrentReviewRuns,
  selectLatestGovernanceRuns,
} from "@/lib/governance-runs";

export type GovernanceRun = {
  id: string;
  normalized_ref_id: string;
  profile_id: string;
  model_alias: string;
  prompt_version: string;
  ai_output: Record<string, unknown> | null;
  quality_summary: Record<string, unknown> | null;
  validation_status: string;
  adoption_status: string;
  validation_error: string | null;
  created_at: string;
  updated_at: string;
  // 后端从 normalized_ref → asset_version → asset 关系链解出（见
  // nexus_api/api/internal/ai_governance.py::_serialize_run）。链路缺失时为
  // null，由前端回退到 normalized_ref_id 的 shortId 显示。
  asset_title?: string | null;
  asset_id?: string | null;
};

export type GovernanceStats = {
  pendingReview: number;
  ruleConflict: number;
  qualityPending: number;
  highConfidenceAdoptable: number;
  completedDecisions: number;
};

export function deriveStats(runs: GovernanceRun[]): GovernanceStats {
  const currentRuns = selectLatestGovernanceRuns(runs);
  const currentReviewRuns = selectCurrentReviewRuns(runs);
  const currentQualityRuns = selectCurrentQualityCalibrationRuns(runs);
  let pendingReview = 0;
  let ruleConflict = 0;
  let qualityPending = 0;
  let highConfidenceAdoptable = 0;
  let completedDecisions = 0;

  for (const r of currentRuns) {
    const conf = getConfidence(r);

    if (isReviewPendingRun(r)) {
      pendingReview++;
      if (r.adoption_status === "pending_rule_guardrail") ruleConflict++;
    }
    if (r.validation_status === "schema_valid" && conf >= 0.85) highConfidenceAdoptable++;
    if (
      r.adoption_status === "auto_adopted" ||
      r.adoption_status === "manually_adopted" ||
      r.adoption_status === "rejected"
    )
      completedDecisions++;
  }

  pendingReview = currentReviewRuns.length;
  qualityPending = currentQualityRuns.length;

  return {
    pendingReview,
    ruleConflict,
    qualityPending,
    highConfidenceAdoptable,
    completedDecisions,
  };
}

const CLASSIFICATION_LABELS: Record<string, string> = {
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
};

export function getClassification(run: GovernanceRun): string {
  const output = run.ai_output ?? {};
  const name = output.classification_name as string | undefined;
  if (name) return name;
  const code = (output.classification_code as string | undefined) ?? (output.classification as string | undefined);
  if (!code) return "-";
  return CLASSIFICATION_LABELS[code] ?? code;
}

export function getLevel(run: GovernanceRun): string {
  return (run.ai_output?.level as string) ?? "-";
}

export function getConfidence(run: GovernanceRun): number {
  return (run.ai_output?.confidence as number) ?? 0;
}

export function getQualityScore(run: GovernanceRun): number | null {
  return getRunQualityScore(run);
}

export function getQualityLevel(run: GovernanceRun): string {
  return (run.quality_summary?.quality_level as string) ?? "";
}

export function getTagCodes(run: GovernanceRun): string[] {
  return extractGovernanceTags(run.ai_output);
}

export function getTags(run: GovernanceRun, dictionary?: TagDictionary): string[] {
  return tagLabels(getTagCodes(run), dictionary);
}

export function getOrgScope(run: GovernanceRun): string {
  return (run.ai_output?.org_scope as string) ?? "-";
}

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
};

export type GovernanceStats = {
  pendingReview: number;
  ruleConflict: number;
  qualityPending: number;
  highConfidenceAdoptable: number;
  completedDecisions: number;
};

export function deriveStats(runs: GovernanceRun[]): GovernanceStats {
  let pendingReview = 0;
  let ruleConflict = 0;
  let qualityPending = 0;
  let highConfidenceAdoptable = 0;
  let completedDecisions = 0;

  for (const r of runs) {
    const conf = getConfidence(r);
    const score = getQualityScore(r);

    if (r.adoption_status === "review_required" || r.adoption_status === "pending_rule_guardrail") {
      pendingReview++;
      if (r.adoption_status === "pending_rule_guardrail") ruleConflict++;
    }
    if (score !== null && score < 70) qualityPending++;
    if (r.validation_status === "schema_valid" && conf >= 0.85) highConfidenceAdoptable++;
    if (
      r.adoption_status === "auto_adopted" ||
      r.adoption_status === "manually_adopted" ||
      r.adoption_status === "rejected"
    )
      completedDecisions++;
  }

  return {
    pendingReview,
    ruleConflict,
    qualityPending,
    highConfidenceAdoptable,
    completedDecisions,
  };
}

export function getClassification(run: GovernanceRun): string {
  return (run.ai_output?.classification as string) ?? "-";
}

export function getLevel(run: GovernanceRun): string {
  return (run.ai_output?.level as string) ?? "-";
}

export function getConfidence(run: GovernanceRun): number {
  return (run.ai_output?.confidence as number) ?? 0;
}

export function getQualityScore(run: GovernanceRun): number | null {
  const qs = run.quality_summary;
  if (!qs) return null;
  return (qs.quality_score as number) ?? null;
}

export function getQualityLevel(run: GovernanceRun): string {
  return (run.quality_summary?.quality_level as string) ?? "";
}

export function getTags(run: GovernanceRun): string[] {
  const t = run.ai_output?.tags;
  return Array.isArray(t) ? (t as string[]) : [];
}

export function getOrgScope(run: GovernanceRun): string {
  return (run.ai_output?.org_scope as string) ?? "-";
}

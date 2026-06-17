export type GovernanceRunLike = {
  id: string;
  normalized_ref_id: string;
  adoption_status: string;
  validation_status: string;
  quality_summary: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

const REVIEW_STATUSES = new Set(["review_required", "pending_rule_guardrail"]);

function timestamp(value: string): number {
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function isNewerRun<T extends GovernanceRunLike>(candidate: T, current: T): boolean {
  const candidateCreated = timestamp(candidate.created_at);
  const currentCreated = timestamp(current.created_at);
  if (candidateCreated !== currentCreated) return candidateCreated > currentCreated;
  return timestamp(candidate.updated_at) > timestamp(current.updated_at);
}

export function selectLatestGovernanceRuns<T extends GovernanceRunLike>(runs: T[]): T[] {
  const byRef = new Map<string, T>();

  for (const run of runs) {
    const current = byRef.get(run.normalized_ref_id);
    if (!current || isNewerRun(run, current)) {
      byRef.set(run.normalized_ref_id, run);
    }
  }

  return Array.from(byRef.values()).sort((a, b) => {
    const createdDiff = timestamp(b.created_at) - timestamp(a.created_at);
    if (createdDiff !== 0) return createdDiff;
    return timestamp(b.updated_at) - timestamp(a.updated_at);
  });
}

export function isReviewPendingRun(run: GovernanceRunLike): boolean {
  return REVIEW_STATUSES.has(run.adoption_status);
}

export function selectCurrentReviewRuns<T extends GovernanceRunLike>(runs: T[]): T[] {
  return selectLatestGovernanceRuns(runs).filter(isReviewPendingRun);
}

export function getRunQualityScore(run: GovernanceRunLike): number | null {
  const score = run.quality_summary?.quality_score;
  return typeof score === "number" ? score : null;
}

export function selectCurrentQualityCalibrationRuns<T extends GovernanceRunLike>(runs: T[]): T[] {
  return selectCurrentReviewRuns(runs).filter((run) => {
    const score = getRunQualityScore(run);
    return score !== null && score < 70;
  });
}

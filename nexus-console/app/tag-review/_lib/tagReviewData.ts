import type { AIGovernanceRun } from "@/lib/api";
import { extractGovernanceTags } from "@/lib/governance-tags";
import { selectLatestGovernanceRuns } from "@/lib/governance-runs";

export interface TagDraft {
  id: string;
  normalizedRefId: string;
  assetId?: string | null;
  assetTitle?: string | null;
  tags: string[];
  evidence: string;
  confidence: number;
}

export interface CommittedTag {
  id: string;
  normalizedRefId: string;
  assetId?: string | null;
  assetTitle?: string | null;
  tags: string[];
  confidence: number;
  committedAt: string;
}

function extractTags(run: AIGovernanceRun): string[] {
  return extractGovernanceTags(run.ai_output);
}

function evidenceText(run: AIGovernanceRun): string {
  const refs = run.ai_output?.evidence_refs;
  if (Array.isArray(refs) && refs.length > 0) {
    return refs
      .map((item) => {
        if (!item || typeof item !== "object") return "";
        const ref = item as Record<string, unknown>;
        const field = typeof ref.field === "string" ? ref.field : "evidence";
        const value = ref.value == null ? "" : String(ref.value);
        return value ? `${field}: ${value}` : field;
      })
      .filter(Boolean)
      .join("；");
  }
  const reasoning = run.ai_output?.reasoning;
  if (typeof reasoning === "string" && reasoning.length > 0) return reasoning;
  return "AI 治理输出包含标签建议，暂无证据片段。";
}

function tagConfidence(run: AIGovernanceRun): number {
  const outputConfidence = run.ai_output?.confidence;
  if (typeof outputConfidence === "number") return outputConfidence;
  const qualityConfidence = run.quality_summary?.confidence;
  if (typeof qualityConfidence === "number") return qualityConfidence;
  return 0;
}

function isAutoCommitted(run: AIGovernanceRun, confidence: number): boolean {
  return confidence >= 0.85
    && run.version_status === "available"
    && run.governance_result_status === "available"
    && run.index_admission === true;
}

function reviewEvidenceText(run: AIGovernanceRun, confidence: number): string {
  const evidence = evidenceText(run);
  if (confidence < 0.85) return evidence;
  const blockers: string[] = [];
  if (run.version_status && run.version_status !== "available") {
    blockers.push(`版本状态为 ${run.version_status}`);
  }
  if (run.governance_result_status && run.governance_result_status !== "available") {
    blockers.push(`治理结果为 ${run.governance_result_status}`);
  }
  if (run.index_admission === false) {
    blockers.push("未通过索引准入");
  }
  if (blockers.length === 0) return evidence;
  return `${evidence}；高置信标签尚未自动提交：${blockers.join("，")}。`;
}

export function toTagReviewData(runs: AIGovernanceRun[]): {
  drafts: TagDraft[];
  committed: CommittedTag[];
} {
  const drafts: TagDraft[] = [];
  const committed: CommittedTag[] = [];

  for (const run of selectLatestGovernanceRuns(runs)) {
    const tags = extractTags(run);
    if (tags.length === 0) continue;
    const confidence = tagConfidence(run);
    if (isAutoCommitted(run, confidence)) {
      committed.push({
        id: `committed-${run.id}`,
        normalizedRefId: run.normalized_ref_id,
        assetId: run.asset_id ?? null,
        assetTitle: run.asset_title ?? null,
        tags,
        confidence,
        committedAt: run.updated_at ?? run.created_at,
      });
    } else {
      drafts.push({
        id: `draft-${run.id}`,
        normalizedRefId: run.normalized_ref_id,
        assetId: run.asset_id ?? null,
        assetTitle: run.asset_title ?? null,
        tags,
        evidence: reviewEvidenceText(run, confidence),
        confidence,
      });
    }
  }

  return { drafts, committed };
}

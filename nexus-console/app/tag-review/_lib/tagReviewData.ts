import type { AIGovernanceRun } from "@/lib/api";
import { extractGovernanceTags } from "@/lib/governance-tags";

export interface TagDraft {
  id: string;
  normalizedRefId: string;
  tags: string[];
  evidence: string;
  confidence: number;
}

export interface CommittedTag {
  id: string;
  normalizedRefId: string;
  tags: string[];
  confidence: number;
  committedAt: string;
  assetTitle?: string;
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

export function toTagReviewData(runs: AIGovernanceRun[]): {
  drafts: TagDraft[];
  committed: CommittedTag[];
} {
  const drafts: TagDraft[] = [];
  const committed: CommittedTag[] = [];

  for (const run of runs) {
    const tags = extractTags(run);
    if (tags.length === 0) continue;
    const confidence = tagConfidence(run);
    if (confidence >= 0.85) {
      committed.push({
        id: `committed-${run.id}`,
        normalizedRefId: run.normalized_ref_id,
        tags,
        confidence,
        committedAt: run.updated_at ?? run.created_at,
      });
    } else {
      drafts.push({
        id: `draft-${run.id}`,
        normalizedRefId: run.normalized_ref_id,
        tags,
        evidence: evidenceText(run),
        confidence,
      });
    }
  }

  return { drafts, committed };
}

import type { AIGovernanceRun } from "@/lib/api";

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

const NON_BUSINESS_TAG_VALUES = new Set([
  "file_upload",
  "文件上传",
  "本地文件上传",
  "nas",
  "crawler",
  "爬虫",
  "database",
  "数据库",
  "webhook",
  "api推送",
  "API推送",
  "第三方API推送",
]);

function isValidTagValue(value: string): boolean {
  if (value.startsWith("#") || value.startsWith("_")) return false;
  if (NON_BUSINESS_TAG_VALUES.has(value)) return false;
  return !/(?:gpt|doubao|qwen|deepseek|claude|gemini)[-_a-z0-9.]*/i.test(value);
}

function extractTags(run: AIGovernanceRun): string[] {
  const tags: string[] = [];
  const seen = new Set<string>();

  function add(value: unknown): void {
    if (typeof value === "object" && value !== null) {
      const item = value as Record<string, unknown>;
      value = item.value ?? item.code ?? item.tag;
    }
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (trimmed && isValidTagValue(trimmed) && !seen.has(trimmed)) {
        seen.add(trimmed);
        tags.push(trimmed);
      }
    }
  }

  function addMany(value: unknown): void {
    if (Array.isArray(value)) {
      value.forEach(addMany);
      return;
    }
    if (typeof value === "object" && value !== null) {
      const item = value as Record<string, unknown>;
      if ("value" in item || "code" in item || "tag" in item) {
        add(item);
        return;
      }
      Object.values(item).forEach(addMany);
      return;
    }
    add(value);
  }

  addMany(run.ai_output?.tags);
  const stages = run.ai_output?._stages as Record<string, unknown> | undefined;
  const taggingStage = stages?.tagging as Record<string, unknown> | undefined;
  addMany(taggingStage?.tags);
  return tags;
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

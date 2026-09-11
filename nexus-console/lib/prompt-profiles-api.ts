import { getApiData, postApiData, putApiData } from "@/lib/api";
import { createIdempotencyKey } from "@/lib/idempotency";

export type PromptProfile = {
  id: string;
  profile_name: string;
  profile_version: number;
  task_type: string;
  scenario: string;
  status: "active" | "archived" | "disabled";
  prompt_version: string;
  prompt_template: string;
  output_schema: Record<string, unknown>;
  output_schema_version: string;
  scoring_weight_version: string;
  temperature: number;
  redaction_policy: "metadata_only" | "masked_content" | "full_content_private";
  content_hash: string;
  change_summary: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
};

export type PromptProfileCandidate = {
  profile_name: string;
  task_type: string;
  scenario: string;
  prompt_version: string;
  prompt_template: string;
  output_schema: Record<string, unknown>;
  output_schema_version: string;
  scoring_weight_version: string;
  temperature: number;
  redaction_policy: PromptProfile["redaction_policy"];
  change_summary?: string;
};

export type PromptValidationResult = {
  valid: boolean;
  errors: string[];
  warnings: string[];
  content_hash: string;
  model_alias: string;
  model_source: string;
};

export type PromptCandidateDryRunResult = {
  validation: PromptValidationResult;
  normalized_ref_id: string;
  task_type: string;
  model_alias: string;
  output: Record<string, unknown> | null;
  persisted: false;
};

export async function fetchPromptHistory(profileName: string): Promise<PromptProfile[]> {
  const result = await getApiData<PromptProfile[]>(
    `/api/ai/prompt-profiles/${encodeURIComponent(profileName)}/history`,
    [],
    { page: "1", pageSize: "100" },
  );
  if (!result.ok) throw new Error(result.error ?? "无法加载历史版本");
  return result.data;
}

export async function validatePromptCandidate(
  candidate: PromptProfileCandidate,
): Promise<PromptValidationResult> {
  const result = await postApiData<PromptValidationResult>(
    "/api/ai/prompt-profiles/validate",
    candidate,
  );
  return result.data;
}

export async function saveActivePrompt(
  profileName: string,
  payload: Omit<PromptProfileCandidate, "profile_name" | "task_type">,
): Promise<PromptProfile> {
  const result = await putApiData<PromptProfile>(
    `/api/ai/prompt-profiles/${encodeURIComponent(profileName)}/active`,
    payload,
    { idempotencyKey: createIdempotencyKey() },
  );
  return result.data;
}

export async function dryRunPromptCandidate(
  candidate: PromptProfileCandidate,
  normalizedRefId: string,
): Promise<PromptCandidateDryRunResult> {
  const result = await postApiData<PromptCandidateDryRunResult>("/api/ai/prompt-profiles/dry-run", {
    candidate,
    normalized_ref_id: normalizedRefId,
  });
  return result.data;
}

import { beforeEach, describe, expect, it, vi } from "vitest";

import { getApiData, postApiData, putApiData } from "@/lib/api";
import { createIdempotencyKey } from "@/lib/idempotency";
import {
  dryRunPromptCandidate,
  fetchPromptHistory,
  saveActivePrompt,
  validatePromptCandidate,
  type PromptProfileCandidate,
} from "./prompt-profiles-api";

vi.mock("@/lib/api", () => ({
  getApiData: vi.fn(),
  postApiData: vi.fn(),
  putApiData: vi.fn(),
}));

vi.mock("@/lib/idempotency", () => ({
  createIdempotencyKey: vi.fn(),
}));

const candidate: PromptProfileCandidate = {
  profile_name: "governance.classification",
  task_type: "classification",
  scenario: "metadata_governance",
  prompt_version: "v2",
  prompt_template: "{{RULES}}\n{{DOCUMENT}}",
  output_schema: { type: "object" },
  output_schema_version: "1.0",
  scoring_weight_version: "1.0",
  temperature: 0.2,
  redaction_policy: "masked_content",
};

describe("Prompt Profile Console API", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads encoded profile history through the browser proxy", async () => {
    vi.mocked(getApiData).mockResolvedValue({
      ok: true,
      data: [],
      error: null,
      traceId: null,
      total: 0,
    });

    await fetchPromptHistory("profile/name");

    expect(getApiData).toHaveBeenCalledWith("/api/ai/prompt-profiles/profile%2Fname/history", [], {
      page: "1",
      pageSize: "100",
    });
  });

  it("keeps validation and dry-run candidates structured", async () => {
    vi.mocked(postApiData)
      .mockResolvedValueOnce({ data: { valid: true } })
      .mockResolvedValueOnce({ data: { persisted: false } });

    await validatePromptCandidate(candidate);
    await dryRunPromptCandidate(candidate, "ref-1");

    expect(postApiData).toHaveBeenNthCalledWith(1, "/api/ai/prompt-profiles/validate", candidate);
    expect(postApiData).toHaveBeenNthCalledWith(2, "/api/ai/prompt-profiles/dry-run", {
      candidate,
      normalized_ref_id: "ref-1",
    });
  });

  it("sends one idempotency key when saving the active profile", async () => {
    vi.mocked(createIdempotencyKey).mockReturnValue("prompt-save-key");
    vi.mocked(putApiData).mockResolvedValue({ data: { id: "profile-v2" } });
    const payload = {
      scenario: candidate.scenario,
      prompt_version: candidate.prompt_version,
      prompt_template: candidate.prompt_template,
      output_schema: candidate.output_schema,
      output_schema_version: candidate.output_schema_version,
      scoring_weight_version: candidate.scoring_weight_version,
      temperature: candidate.temperature,
      redaction_policy: candidate.redaction_policy,
    };

    await saveActivePrompt(candidate.profile_name, payload);

    expect(putApiData).toHaveBeenCalledWith(
      "/api/ai/prompt-profiles/governance.classification/active",
      payload,
      { idempotencyKey: "prompt-save-key" },
    );
  });
});

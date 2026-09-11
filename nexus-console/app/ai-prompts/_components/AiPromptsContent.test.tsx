import { fireEvent, waitFor } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders, screen, within } from "@/test-utils/test-renderer";
import {
  fetchPromptHistory,
  saveActivePrompt,
  validatePromptCandidate,
  type PromptProfile,
} from "@/lib/prompt-profiles-api";
import AiPromptsContent from "./AiPromptsContent";

vi.mock("@/lib/prompt-profiles-api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/prompt-profiles-api")>();
  return {
    ...original,
    fetchPromptHistory: vi.fn(),
    validatePromptCandidate: vi.fn(),
    saveActivePrompt: vi.fn(),
    dryRunPromptCandidate: vi.fn(),
  };
});

function makeProfile(
  profileName: string,
  profileVersion: number,
  promptTemplate: string,
): PromptProfile {
  return {
    id: `${profileName}-${profileVersion}`,
    profile_name: profileName,
    profile_version: profileVersion,
    task_type: profileName.startsWith("governance.") ? "classification" : "retrieval_v2",
    scenario: profileName.startsWith("governance.") ? "metadata_governance" : "retrieval.intent",
    status: "active",
    prompt_version: `v${profileVersion}`,
    prompt_template: promptTemplate,
    output_schema: { type: "object", properties: { answer: { type: "string" } } },
    output_schema_version: "1.0",
    scoring_weight_version: "1.0",
    temperature: 0.2,
    redaction_policy: "masked_content",
    content_hash: "1234567890abcdef",
    change_summary: "initial",
    created_by: "operator-1",
    created_at: "2026-09-10T08:00:00Z",
    updated_at: "2026-09-10T08:00:00Z",
  };
}

const profiles = [
  makeProfile("governance.classification", 1, "## 分类模板\n\n{{RULES}}\n\n{{DOCUMENT}}"),
  makeProfile("governance.level_assessment", 2, "## 分级模板\n\n{{RULES}}\n\n{{DOCUMENT}}"),
  makeProfile("retrieval.intent_v2", 1, "## 意图模板\n\n{{QUERY}}"),
  makeProfile("occupation.job_demand.body_markdown_render", 1, "不应显示"),
];

describe("AiPromptsContent", () => {
  beforeAll(() => {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(validatePromptCandidate).mockResolvedValue({
      valid: true,
      errors: [],
      warnings: [],
      content_hash: "validated-hash-123456",
      model_alias: "runtime-model",
      model_source: "DEFAULT_GOVERNANCE_MODEL",
    });
  });

  it("renders the frozen core order, selects the first template, and edits directly", () => {
    renderWithProviders(<AiPromptsContent profiles={profiles} />);

    const coreNav = screen.getByRole("navigation", { name: "核心提示词模板" });
    expect(
      within(coreNav)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual([
      "数据资产分类",
      "数据资产分级",
      "数据资产质量评估",
      "数据资产打标",
      "知识结构推理",
      "检索意图识别",
      "检索参数提取",
      "检索结果答案组织",
    ]);
    expect(screen.getByRole("button", { name: "数据资产分类" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("textbox", { name: "提示词模板内容" })).toHaveValue(
      profiles[0].prompt_template,
    );
    expect(screen.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument();
    expect(screen.queryByText("岗位需求 Markdown 组织")).not.toBeInTheDocument();
    expect(screen.queryByText("不应显示")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /领域场景/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("confirms before discarding edits when switching scenarios", async () => {
    const { user } = renderWithProviders(<AiPromptsContent profiles={profiles} />);
    const editor = screen.getByRole("textbox", { name: "提示词模板内容" });
    await user.type(editor, "\n修改");
    await user.click(screen.getByRole("button", { name: "数据资产分级" }));

    expect((await screen.findAllByText("放弃未保存的修改？")).length).toBeGreaterThan(0);
    expect(editor).toHaveValue(`${profiles[0].prompt_template}\n修改`);
    await user.click(screen.getByRole("button", { name: "放弃并切换" }));

    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "提示词模板内容" })).toHaveValue(
        profiles[1].prompt_template,
      ),
    );
  });

  it("validates structured content and saves a new active version with a summary", async () => {
    const updated = {
      ...profiles[0],
      id: "classification-v2",
      profile_version: 2,
      prompt_version: "v2",
      prompt_template: `${profiles[0].prompt_template}\n新约束`,
      change_summary: "补充分类约束",
    };
    vi.mocked(saveActivePrompt).mockResolvedValue(updated);
    const { user } = renderWithProviders(<AiPromptsContent profiles={profiles} />);

    await user.type(screen.getByRole("textbox", { name: "提示词模板内容" }), "\n新约束");
    await user.clear(screen.getByRole("textbox", { name: "Prompt 版本" }));
    await user.type(screen.getByRole("textbox", { name: "Prompt 版本" }), "v2");
    await user.click(screen.getByRole("button", { name: "保存并生效" }));

    expect(
      await screen.findByText("保存将创建新的活动版本，并自动归档当前活动版本。"),
    ).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: /^变更摘要/ }), "补充分类约束");
    await user.click(screen.getByRole("button", { name: "确认保存并生效" }));

    await waitFor(() => expect(saveActivePrompt).toHaveBeenCalledOnce());
    expect(validatePromptCandidate).toHaveBeenCalledWith(
      expect.objectContaining({
        profile_name: "governance.classification",
        prompt_version: "v2",
        prompt_template: `${profiles[0].prompt_template}\n新约束`,
        output_schema: profiles[0].output_schema,
      }),
    );
    expect(saveActivePrompt).toHaveBeenCalledWith(
      "governance.classification",
      expect.objectContaining({
        prompt_version: "v2",
        output_schema: profiles[0].output_schema,
        change_summary: "补充分类约束",
      }),
    );
    expect(vi.mocked(saveActivePrompt).mock.calls[0][1]).not.toHaveProperty("litellm_model_alias");
    expect(vi.mocked(saveActivePrompt).mock.calls[0][1]).not.toHaveProperty("max_input_tokens");
  });

  it("rejects unsupported runtime variables before calling the backend", async () => {
    const { user } = renderWithProviders(<AiPromptsContent profiles={profiles} />);
    fireEvent.change(screen.getByRole("textbox", { name: "提示词模板内容" }), {
      target: { value: `${profiles[0].prompt_template}\n{{NEW_RUNTIME_VALUE}}` },
    });
    await user.click(screen.getByRole("button", { name: "校验" }));

    expect(await screen.findByText(/包含运行时不支持的变量/)).toBeInTheDocument();
    expect(validatePromptCandidate).not.toHaveBeenCalled();
  });

  it("locks editing when a rolling deployment returns the legacy list projection", () => {
    const legacyProfile = {
      ...profiles[0],
      prompt_template: undefined,
      output_schema: undefined,
      content_hash: undefined,
    } as unknown as PromptProfile;

    renderWithProviders(<AiPromptsContent profiles={[legacyProfile]} />);

    expect(screen.getByText("Prompt 数据契约不完整")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "提示词模板内容" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "输出 Schema" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "校验" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存并生效" })).toBeDisabled();
  });

  it("loads historical versions into a read-only preview", async () => {
    const archived = { ...profiles[0], id: "classification-old", status: "archived" as const };
    vi.mocked(fetchPromptHistory).mockResolvedValue([profiles[0], archived]);
    const { user } = renderWithProviders(<AiPromptsContent profiles={profiles} />);

    await user.click(screen.getByRole("button", { name: "历史版本" }));
    const preview = await screen.findByRole("region", { name: "历史版本只读内容" });

    expect(within(preview).getByText("配置版本 v1")).toBeInTheDocument();
    expect(within(preview).getByText(/^## 分类模板/, { selector: "pre" })).toBeInTheDocument();
    expect(within(preview).queryByRole("textbox")).not.toBeInTheDocument();
  });
});

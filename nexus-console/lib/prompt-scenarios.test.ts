import { describe, expect, it } from "vitest";

import {
  CORE_PROMPT_SCENARIOS,
  DOMAIN_PROMPT_SCENARIOS,
  extractPromptVariables,
  isPromptProfileVisible,
  validateScenarioVariables,
} from "./prompt-scenarios";

describe("Prompt scenario registry", () => {
  it("keeps the eight core scenarios in the frozen display order", () => {
    expect(CORE_PROMPT_SCENARIOS.map((scenario) => scenario.displayName)).toEqual([
      "数据资产分类",
      "数据资产分级",
      "数据资产质量评估",
      "数据资产打标",
      "知识结构推理",
      "检索意图识别",
      "检索参数提取",
      "检索结果答案组织",
    ]);
  });

  it("contains only editable business prompts in the domain group", () => {
    expect(DOMAIN_PROMPT_SCENARIOS.map((scenario) => scenario.profileName)).toEqual([
      "occupation.job_demand.requirement_extraction",
      "occupation.task_description_structuring",
      "knowledge_outline.heading_classifier",
      "professional.teaching_standard.course_derivation",
    ]);
  });

  it("hides technical Markdown rendering and inactive query expansion profiles", () => {
    expect(isPromptProfileVisible("occupation.job_demand.body_markdown_render")).toBe(false);
    expect(isPromptProfileVisible("occupation.ability_analysis.body_markdown_render")).toBe(false);
    expect(isPromptProfileVisible("future.body_markdown_render")).toBe(false);
    expect(isPromptProfileVisible("retrieval.query_expansion_v2")).toBe(false);
  });

  it("normalizes placeholders and rejects variables outside a scenario contract", () => {
    const scenario = CORE_PROMPT_SCENARIOS[0];
    const template = "Rules {{ RULES }} document {{DOCUMENT}} extra {{UNSUPPORTED}}";

    expect(extractPromptVariables(template)).toEqual([
      "{{RULES}}",
      "{{DOCUMENT}}",
      "{{UNSUPPORTED}}",
    ]);
    expect(validateScenarioVariables(template, scenario)).toEqual([
      "包含运行时不支持的变量：{{UNSUPPORTED}}",
    ]);
    expect(validateScenarioVariables("{{RULES}}", scenario)).toEqual([
      "缺少必需变量：{{DOCUMENT}}",
    ]);
  });
});

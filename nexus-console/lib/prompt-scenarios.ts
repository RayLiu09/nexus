export type PromptScenarioGroup = "core" | "domain";

export type PromptScenarioDefinition = {
  profileName: string;
  displayName: string;
  description: string;
  group: PromptScenarioGroup;
  allowedVariables: readonly string[];
  requiredVariables: readonly string[];
  dryRunSupported: boolean;
  impactText: string;
};

const GOVERNANCE_VARIABLES = ["{{RULES}}", "{{DOCUMENT}}"] as const;

export const CORE_PROMPT_SCENARIOS: readonly PromptScenarioDefinition[] = [
  {
    profileName: "governance.classification",
    displayName: "数据资产分类",
    description: "依据治理分类规则识别标准化数据资产所属类别。",
    group: "core",
    allowedVariables: GOVERNANCE_VARIABLES,
    requiredVariables: GOVERNANCE_VARIABLES,
    dryRunSupported: true,
    impactText: "保存后用于后续治理、重新治理和 AI 重评分。",
  },
  {
    profileName: "governance.level_assessment",
    displayName: "数据资产分级",
    description: "依据分级规则评估标准化数据资产的敏感级别。",
    group: "core",
    allowedVariables: GOVERNANCE_VARIABLES,
    requiredVariables: GOVERNANCE_VARIABLES,
    dryRunSupported: true,
    impactText: "保存后用于后续治理、重新治理和 AI 重评分。",
  },
  {
    profileName: "governance.quality_assessment",
    displayName: "数据资产质量评估",
    description: "按质量维度输出可校验的资产质量评估建议。",
    group: "core",
    allowedVariables: GOVERNANCE_VARIABLES,
    requiredVariables: GOVERNANCE_VARIABLES,
    dryRunSupported: true,
    impactText: "保存后用于后续治理、重新治理和 AI 重评分。",
  },
  {
    profileName: "governance.tagging",
    displayName: "数据资产打标",
    description: "依据标签规则为标准化资产生成结构化标签建议。",
    group: "core",
    allowedVariables: GOVERNANCE_VARIABLES,
    requiredVariables: GOVERNANCE_VARIABLES,
    dryRunSupported: true,
    impactText: "保存后用于后续治理、重新治理和 AI 重评分。",
  },
  {
    profileName: "governance.knowledge_inference",
    displayName: "知识结构推理",
    description: "推断资产适用的知识组织类型并提供可审计依据。",
    group: "core",
    allowedVariables: GOVERNANCE_VARIABLES,
    requiredVariables: GOVERNANCE_VARIABLES,
    dryRunSupported: true,
    impactText: "保存后用于后续治理、重新治理和 AI 重评分。",
  },
  {
    profileName: "retrieval.intent_v2",
    displayName: "检索意图识别",
    description: "识别用户查询对应的唯一检索业务场景。",
    group: "core",
    allowedVariables: ["{{QUERY}}"],
    requiredVariables: ["{{QUERY}}"],
    dryRunSupported: false,
    impactText: "保存后从下一次智能检索查询开始生效。",
  },
  {
    profileName: "retrieval.param_extract_v2",
    displayName: "检索参数提取",
    description: "按命中意图的参数契约从用户查询中提取检索参数。",
    group: "core",
    allowedVariables: ["{{QUERY}}", "{{INTENT}}", "{{PARAMS_SCHEMA}}"],
    requiredVariables: ["{{QUERY}}", "{{INTENT}}", "{{PARAMS_SCHEMA}}"],
    dryRunSupported: false,
    impactText: "保存后从下一次智能检索查询开始生效。",
  },
  {
    profileName: "retrieval.compose_v2",
    displayName: "检索结果答案组织",
    description: "将检索结果、引用和图表占位组织为最终 Markdown 答案。",
    group: "core",
    allowedVariables: ["{{QUERY}}", "{{INTENT}}", "{{TOOL_RESULTS}}", "{{CHART_PLACEHOLDERS}}"],
    requiredVariables: ["{{QUERY}}", "{{INTENT}}", "{{TOOL_RESULTS}}", "{{CHART_PLACEHOLDERS}}"],
    dryRunSupported: false,
    impactText: "保存后从下一次智能检索查询开始生效。",
  },
];

export const DOMAIN_PROMPT_SCENARIOS: readonly PromptScenarioDefinition[] = [
  {
    profileName: "occupation.job_demand.requirement_extraction",
    displayName: "岗位需求要素抽取",
    description: "从岗位记录中抽取技能、工具、证书、素养和任务要素。",
    group: "domain",
    allowedVariables: [],
    requiredVariables: [],
    dryRunSupported: false,
    impactText: "保存后用于下一次领域处理或重新处理。",
  },
  {
    profileName: "occupation.task_description_structuring",
    displayName: "职业任务描述结构化",
    description: "将职业任务描述结构化为角色、工具、环境和工作方式。",
    group: "domain",
    allowedVariables: [],
    requiredVariables: [],
    dryRunSupported: false,
    impactText: "保存后用于下一次领域处理或重新处理。",
  },
  {
    profileName: "knowledge_outline.heading_classifier",
    displayName: "教材知识大纲标题分类",
    description: "识别教材标题在知识大纲中的结构类型。",
    group: "domain",
    allowedVariables: [],
    requiredVariables: [],
    dryRunSupported: false,
    impactText: "保存后用于下一次领域处理或重新处理。",
  },
  {
    profileName: "professional.teaching_standard.course_derivation",
    displayName: "专业教学标准课程语义派生",
    description: "依据教学标准证据派生课程语义标签和复杂度分类。",
    group: "domain",
    allowedVariables: [],
    requiredVariables: [],
    dryRunSupported: false,
    impactText: "保存后用于下一次领域处理或重新处理。",
  },
];

export const PROMPT_SCENARIOS = [...CORE_PROMPT_SCENARIOS, ...DOMAIN_PROMPT_SCENARIOS] as const;

export const HIDDEN_PROMPT_PROFILE_PATTERNS = [
  /\.body_markdown_render$/,
  /^retrieval\.query_expansion_v2$/,
] as const;

const VARIABLE_PATTERN = /\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}/g;

export function findPromptScenario(profileName: string): PromptScenarioDefinition | undefined {
  return PROMPT_SCENARIOS.find((scenario) => scenario.profileName === profileName);
}

export function isPromptProfileVisible(profileName: string): boolean {
  return (
    findPromptScenario(profileName) !== undefined &&
    !HIDDEN_PROMPT_PROFILE_PATTERNS.some((pattern) => pattern.test(profileName))
  );
}

export function extractPromptVariables(template: string): string[] {
  return Array.from(template.matchAll(VARIABLE_PATTERN), (match) => `{{${match[1]}}}`);
}

export function validateScenarioVariables(
  template: string,
  scenario: PromptScenarioDefinition,
): string[] {
  const found = new Set(extractPromptVariables(template));
  const allowed = new Set(scenario.allowedVariables);
  const unknown = [...found].filter((variable) => !allowed.has(variable));
  const missing = scenario.requiredVariables.filter((variable) => !found.has(variable));
  const errors: string[] = [];

  if (unknown.length > 0) {
    errors.push(`包含运行时不支持的变量：${unknown.join("、")}`);
  }
  if (missing.length > 0) {
    errors.push(`缺少必需变量：${missing.join("、")}`);
  }
  return errors;
}

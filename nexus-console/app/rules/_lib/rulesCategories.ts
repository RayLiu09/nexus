import type { RuleCategoryId } from "./types";

/**
 * v3.2 §14 四类规则元数据。
 *
 * `jsonKey` 是该类在 governance_rules.json 顶层的字段名；
 * 上传/下载/编辑保存时都基于此键替换或合并到整份 rules。
 */
export interface RuleCategoryMeta {
  id: RuleCategoryId;
  /** v3.2 §14 中的中文名（卡片标题） */
  title: string;
  /** 一句话目标说明 */
  purpose: string;
  /** 下载/上传时的文件名前缀 */
  downloadFilenamePrefix: string;
}

export const RULE_CATEGORIES: ReadonlyArray<RuleCategoryMeta> = [
  {
    id: "classifications",
    title: "数据域分类",
    purpose: "根据文档元数据和内容，将资产分类到 D1-D4 数据域，并标注资产类型。",
    downloadFilenamePrefix: "domain_classification",
  },
  {
    id: "levels",
    title: "数据分级",
    purpose: "根据文档敏感度，设定 L1-L4 分级，标注是否需要审批与是否禁外部 LLM。",
    downloadFilenamePrefix: "data_classification",
  },
  {
    id: "tags",
    title: "标签设置",
    purpose: "从标签维度自动设置推荐标签，关联适用的数据域分类。",
    downloadFilenamePrefix: "tag_labeling",
  },
  {
    id: "quality_scoring",
    title: "AI 质量评分",
    purpose:
      "评估资产内容质量的 5 个维度（完整性 / 准确性 / 一致性 / 可用性 / 可追溯性）并产出综合分。",
    downloadFilenamePrefix: "quality_scoring",
  },
];

export function findCategory(id: RuleCategoryId): RuleCategoryMeta {
  const found = RULE_CATEGORIES.find((c) => c.id === id);
  if (!found) throw new Error(`未知规则类别：${id}`);
  return found;
}

/** 取当前生效规则中该类别的子文档（便于"下载当前模板"）。 */
export function extractCategorySection(
  rules: Record<string, unknown> | null,
  id: RuleCategoryId,
): unknown {
  if (!rules) return null;
  return rules[id] ?? null;
}

/** 将单类子文档合并回整份规则，用于按类别上传/在线编辑保存。 */
export function mergeCategorySection(
  rules: Record<string, unknown>,
  id: RuleCategoryId,
  section: unknown,
): Record<string, unknown> {
  return { ...rules, [id]: section };
}

/** 空模板（带最小示例字段） — 给用户下载用于新建规则集。 */
export function emptyTemplate(id: RuleCategoryId): unknown {
  switch (id) {
    case "classifications":
      return [
        {
          code: "D1",
          name: "示例分类",
          description: "在此填写分类描述（D1-D4）",
          criteria: ["在此填写命中此分类的判断标准"],
          examples: ["示例资产名"],
        },
      ];
    case "levels":
      return [
        {
          code: "L1",
          name: "公开",
          description: "可对外公开的数据",
          criteria: ["在此填写命中此分级的判断标准"],
          requires_approval: false,
          forbid_external_llm: false,
        },
      ];
    case "tags":
      return [
        {
          code: "example_tag",
          name: "示例标签",
          applicable_classifications: ["D1", "D2"],
          criteria: ["在此填写命中此标签的判断标准"],
        },
      ];
    case "quality_scoring":
      return {
        dimensions: [
          {
            name: "completeness",
            weight: 0.3,
            description: "内容完整性维度",
            check_items: [
              {
                name: "has_title",
                description: "文档必须有标题",
                severity: "blocking",
              },
            ],
          },
        ],
        thresholds: {
          pass: 80,
          warning: 60,
          review_required_below: 50,
        },
        confidence_threshold_auto_adopt: 0.85,
      };
  }
}

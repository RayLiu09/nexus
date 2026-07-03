export type ClassificationDictionaryEntry = {
  code: string;
  name?: string | null;
};

export type ClassificationDictionary = Record<string, string>;

const FALLBACK_CLASSIFICATION_LABELS: ClassificationDictionary = {
  industry_policy: "产业政策",
  industry_report: "产业报告",
  sector_report: "行业报告",
  job_demand: "岗位需求数据",
  competency_analysis: "职业能力分析表",
  vocational_certificate: "职业类证书",
  teaching_standard: "专业教学标准",
  major_distribution: "专业布点数",
  talent_demand_report: "专业人才需求报告",
  talent_training_plan: "人才培养方案",
  major_profile: "专业简介",
  course_textbook: "教材",
};

export function buildClassificationDictionary(
  entries: ClassificationDictionaryEntry[] | null | undefined,
): ClassificationDictionary {
  const labels: ClassificationDictionary = { ...FALLBACK_CLASSIFICATION_LABELS };
  for (const entry of entries ?? []) {
    if (entry.code && entry.name) labels[entry.code] = entry.name;
  }
  return labels;
}

export function classificationLabel(
  code: string | null | undefined,
  dictionary?: ClassificationDictionary,
): string {
  if (!code) return "-";
  return dictionary?.[code] ?? FALLBACK_CLASSIFICATION_LABELS[code] ?? code;
}

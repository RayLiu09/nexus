import type { QueryCitation } from "./queryTypes";

// Only business-facing fields are presented. Technical anchors remain in the
// structured citation for navigation and traceability, never in source details.
const FIELD_LABELS: Record<string, string> = {
  q: "关键词",
  keyword: "关键词",
  name: "名称",
  title: "标题",
  province: "省份",
  province_name: "省份",
  city: "城市",
  city_name: "城市",
  year: "年份",
  major_name: "专业",
  major_code: "专业代码",
  course_name: "课程",
  standard_title: "教学标准",
  textbook_title: "教材",
  job_title: "岗位",
  enterprise_name: "企业",
  park_name: "园区",
  school_name: "院校",
  education_level: "教育层次",
  course_type: "课程类别",
  category: "类别",
  count: "数量",
  total: "总数",
  total_count: "记录总数",
  record_count: "记录数",
  offering_count: "布点记录数",
  school_count: "院校数",
  job_count: "岗位数",
  unique_school_count: "院校数",
  hours: "学时",
  total_hours: "总学时",
  practice_hours: "实践学时",
  description: "说明",
  summary: "摘要",
  content: "内容",
  text: "正文",
  snippet: "节选",
  introduction: "介绍",
};
const FALLBACKS = {
  document: "平台文档",
  record: "业务记录",
  aggregate: "数据统计结果",
  external_web: "网页资料",
};

export function readableText(value: string) {
  return value
    .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, "")
    .replace(/\b(?:nx_|sk-)[A-Za-z0-9_-]{16,}\b/g, "")
    .trim();
}

export function citationTitle(source: QueryCitation) {
  const title = readableText(source.title)
    .replace(/[-_][a-f0-9]{12,64}(?=\.(?:html?|pdf|docx?|xlsx?|txt|md)$)/i, "")
    .replace(/\.(?:html?|pdf|docx?|xlsx?|txt|md)$/i, "");
  return !title || /^[a-z][a-z0-9_]+$/.test(title) ? FALLBACKS[source.source_type] : title;
}

function businessLines(value: unknown, depth = 0): string[] {
  if (depth > 4 || value === null || typeof value !== "object") return [];
  if (Array.isArray(value))
    return value.slice(0, 8).flatMap((item) => businessLines(item, depth + 1));
  return Object.entries(value).flatMap(([key, item]) => {
    const label = FIELD_LABELS[key];
    if (label && (typeof item === "string" || typeof item === "number")) {
      const text = readableText(String(item));
      return text ? [`${label}：${text}`] : [];
    }
    // Traverse result containers, never identity/governance/debug objects.
    if (["groups", "items", "records", "results", "data", "metrics", "totals"].includes(key)) {
      return businessLines(item, depth + 1);
    }
    return [];
  });
}

export function citationExcerpt(source: QueryCitation) {
  const excerpt = source.excerpt.trim();
  if (/^[{[]/.test(excerpt)) {
    try {
      const lines = businessLines(JSON.parse(excerpt));
      if (lines.length) return lines.join("\n");
    } catch {
      // Raw JSON may be truncated. Do not expose partial technical payloads.
    }
    return source.source_type === "aggregate"
      ? "该来源为平台数据统计，统计结果与口径请参阅回答正文。"
      : "该来源为平台业务查询结果，可结合回答与查询条件核对。";
  }
  return readableText(excerpt) || "请打开来源查看原文。";
}

export function readableScope(source: QueryCitation) {
  return businessLines(source.scope ?? {});
}

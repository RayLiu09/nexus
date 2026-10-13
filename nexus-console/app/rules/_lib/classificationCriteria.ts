export function classificationCriteria(classification: Record<string, unknown>): string[] {
  const description = typeof classification.description === "string"
    ? classification.description.trim()
    : "";
  const explicit = stringArray(classification.criteria);
  const titleKeywords = stringArray(classification.title_keywords);
  const contentKeywords = stringArray(classification.content_keywords);

  return [
    ...(description ? [`定义：${description}`] : []),
    ...explicit,
    ...(explicit.length === 0 && titleKeywords.length > 0
      ? [`标题/封面关键词：${titleKeywords.join("、")}`]
      : []),
    ...(explicit.length === 0 && contentKeywords.length > 0
      ? [`正文/结构关键词：${contentKeywords.join("、")}`]
      : []),
  ];
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

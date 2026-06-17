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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function isValidGovernanceTagValue(value: string): boolean {
  if (value.startsWith("#") || value.startsWith("_")) return false;
  if (NON_BUSINESS_TAG_VALUES.has(value)) return false;
  return !/(?:gpt|doubao|qwen|deepseek|claude|gemini)[-_a-z0-9.]*/i.test(value);
}

export function extractGovernanceTags(aiOutput: unknown): string[] {
  const tags: string[] = [];
  const seen = new Set<string>();

  function add(value: unknown): void {
    if (isRecord(value)) {
      value = value.value ?? value.code ?? value.tag;
    }
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (trimmed && isValidGovernanceTagValue(trimmed) && !seen.has(trimmed)) {
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
    if (isRecord(value)) {
      if ("value" in value || "code" in value || "tag" in value) {
        add(value);
        return;
      }
      Object.values(value).forEach(addMany);
      return;
    }
    add(value);
  }

  if (!isRecord(aiOutput)) return tags;

  addMany(aiOutput.tags);
  const stages = isRecord(aiOutput._stages) ? aiOutput._stages : undefined;
  const taggingStage = isRecord(stages?.tagging) ? stages.tagging : undefined;
  addMany(taggingStage?.tags);

  return tags;
}

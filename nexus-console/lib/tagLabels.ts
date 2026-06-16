export type TagDictionaryEntry = {
  code: string;
  name?: string | null;
};

export type TagDictionary = Record<string, string>;

const FALLBACK_TAG_LABELS: TagDictionary = {
  knowledge_asset: "知识资产",
  training_material: "教学资源",
  pii: "个人信息",
};

export function buildTagDictionary(entries: TagDictionaryEntry[] | null | undefined): TagDictionary {
  const labels: TagDictionary = { ...FALLBACK_TAG_LABELS };
  for (const entry of entries ?? []) {
    if (entry.code && entry.name) labels[entry.code] = entry.name;
  }
  return labels;
}

export function tagLabel(code: string | null | undefined, dictionary?: TagDictionary): string {
  if (!code) return "-";
  return dictionary?.[code] ?? FALLBACK_TAG_LABELS[code] ?? code;
}

export function tagLabels(codes: string[], dictionary?: TagDictionary): string[] {
  return codes.map((code) => tagLabel(code, dictionary));
}

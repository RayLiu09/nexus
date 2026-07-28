export type LevelDictionaryEntry = {
  code: string;
  name?: string | null;
  label?: string | null;
};

export type LevelDictionary = Record<string, string>;

export function buildLevelDictionary(
  entries: LevelDictionaryEntry[] | null | undefined,
): LevelDictionary {
  const labels: LevelDictionary = {};
  for (const entry of entries ?? []) {
    const label = entry.name ?? entry.label;
    if (entry.code && label) labels[entry.code] = label;
  }
  return labels;
}

export function levelLabel(
  code: string | null | undefined,
  dictionary?: LevelDictionary,
): string {
  if (!code) return "-";
  return dictionary?.[code] ?? code;
}

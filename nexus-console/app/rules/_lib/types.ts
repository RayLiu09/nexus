/**
 * NX-09 规则配置 — 共用类型。
 */
export interface ClassificationRow {
  code: string;
  name: string;
  description?: string;
  criteria: string[];
}

export interface LevelRow {
  code: string;
  name: string;
  description?: string;
  requires_approval: boolean;
  forbid_external_llm: boolean;
  criteria: string[];
}

export interface TagRow {
  code: string;
  name: string;
  applicable_classifications: string[];
  criteria: string[];
}

export interface DimensionRow {
  name: string;
  weight: number;
  check_items: unknown[];
  description: string;
}

export interface ExtractedTables {
  classifications: ClassificationRow[];
  levels: LevelRow[];
  tags: TagRow[];
  dimensions: DimensionRow[];
  thresholds: Record<string, unknown> | null;
  autoAdoptThreshold: number | string | null;
}

/** 与 governance_rules.json 顶层 4 类对齐。 */
export type RuleCategoryId = "classifications" | "levels" | "tags" | "quality_scoring";

/**
 * Runtime shape of `public/retrieval-fixtures.json`. Keep in sync with
 * the schema_version declared there so future migrations surface as
 * type errors.
 */

export type FixtureCategory =
  | "single_domain"
  | "tag_filter"
  | "rerank"
  | "aggregation"
  | "multi_hop"
  | "edge_case"
  | "negative";

export type FixtureDomain =
  | "job_demand"
  | "major_distribution"
  | "competency_analysis"
  | "course_textbook";

export interface FixturePreset {
  id: string;
  label: string;
  category: FixtureCategory;
  domain_focus: FixtureDomain;
  question: string;
  notes?: string;
}

export interface FixtureManifest {
  schema_version: string;
  description?: string;
  presets: FixturePreset[];
}

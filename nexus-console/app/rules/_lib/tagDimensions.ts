export type TagRuleDetail = {
  code: string;
  classification: string;
  criteria: string[];
};

export type TagDimensionRow = {
  code: string;
  name: string;
  source: string;
  description: string;
  values: string[];
  details: TagRuleDetail[];
};

const CLASSIFICATION_FIELDS: Record<string, string> = {
  professional_domain: "tagging_basis.professional_domain",
  education_level: "tagging_basis.education_level",
  geographic_scope: "geo_scope",
  timeliness: "timeliness",
  data_source_type: "data_source",
};

export function extractTagDimensions(rules: Record<string, unknown>): TagDimensionRow[] {
  const dimensions = record(rules.tag_dimensions);
  const classifications = Array.isArray(rules.classifications) ? rules.classifications : [];

  return Object.entries(dimensions).map(([code, rawDimension]) => {
    const dimension = record(rawDimension);
    const field = CLASSIFICATION_FIELDS[code] ?? String(dimension.binding_column ?? "");
    const details = classifications.flatMap((rawClassification) => {
      const classification = record(rawClassification);
      const basis = field.split(".").reduce<unknown>((value, part) => record(value)[part], classification);
      const criteria = formatBasis(basis);
      return criteria.length > 0 ? [{
        code: String(classification.code ?? ""),
        classification: String(classification.name ?? classification.code ?? ""),
        criteria,
      }] : [];
    });
    return {
      code,
      name: String(dimension.name ?? code),
      source: String(dimension.source ?? ""),
      description: String(dimension.description ?? ""),
      values: formatBasis(dimension.values),
      details: dimension.source === "fixed" ? [] : details,
    };
  });
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function formatBasis(value: unknown): string[] {
  if (typeof value === "string") return value.trim() ? [value.trim()] : [];
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string") return item.trim() ? [item.trim()] : [];
    const entry = record(item);
    const label = String(entry.value ?? "").trim();
    const criteria = String(entry.criteria ?? "").trim();
    const text = [label, criteria].filter(Boolean).join("：");
    return text ? [text] : [];
  });
}

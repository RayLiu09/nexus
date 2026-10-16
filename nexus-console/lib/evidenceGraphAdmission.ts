const GRAPH_HIDDEN_CLASSIFICATIONS = new Set([
  "industry_report",
  "sector_report",
  "talent_demand_report",
]);

export function shouldShowEvidenceGraph(
  graphAdmission: string | null | undefined,
  classification: string | null | undefined,
): boolean {
  return (
    graphAdmission !== "not_recommended" &&
    !GRAPH_HIDDEN_CLASSIFICATIONS.has(classification ?? "")
  );
}

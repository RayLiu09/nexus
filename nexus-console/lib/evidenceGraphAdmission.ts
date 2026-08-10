const OUTLINE_FIRST_REPORT_CLASSIFICATIONS = new Set([
  "industry_report",
  "sector_report",
]);

export function shouldShowEvidenceGraph(
  graphAdmission: string | null | undefined,
  classification: string | null | undefined,
): boolean {
  return (
    graphAdmission !== "not_recommended" &&
    !OUTLINE_FIRST_REPORT_CLASSIFICATIONS.has(classification ?? "")
  );
}

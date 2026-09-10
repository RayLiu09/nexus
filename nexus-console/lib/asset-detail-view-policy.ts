import type { RecordView } from "./api";

const HIDDEN_RECORD_VIEWS = new Set<RecordView>([
  "job_demand",
  "ability_analysis",
  "major_distribution",
]);

const HIDDEN_CLASSIFICATIONS = new Set([
  "job_demand",
  "competency_analysis",
  "major_distribution",
]);

const HIDDEN_DOMAIN_PROFILES = new Set([
  "job_demand.v1",
  "ability_analysis.pgsd.v1",
  "major_distribution.v1",
]);

export function shouldHideAssetDetailStructuredView(
  recordView: RecordView,
  classification?: string | null,
  domainProfile?: unknown,
): boolean {
  return (
    HIDDEN_RECORD_VIEWS.has(recordView) ||
    (classification != null && HIDDEN_CLASSIFICATIONS.has(classification)) ||
    (typeof domainProfile === "string" && HIDDEN_DOMAIN_PROFILES.has(domainProfile))
  );
}

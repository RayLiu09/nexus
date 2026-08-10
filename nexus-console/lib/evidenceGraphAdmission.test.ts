import { describe, expect, it } from "vitest";

import { shouldShowEvidenceGraph } from "./evidenceGraphAdmission";

describe("shouldShowEvidenceGraph", () => {
  it.each(["industry_report", "sector_report"])(
    "hides the graph entry for outline-first report classification %s",
    (classification) => {
      expect(shouldShowEvidenceGraph("recommended", classification)).toBe(false);
    },
  );

  it("keeps the graph entry for other graph-admitted documents", () => {
    expect(shouldShowEvidenceGraph("recommended", "industry_policy")).toBe(true);
  });

  it("honors an explicit graph admission block for every classification", () => {
    expect(shouldShowEvidenceGraph("not_recommended", "policy_document")).toBe(false);
  });
});

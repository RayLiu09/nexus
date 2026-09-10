import { describe, expect, it } from "vitest";

import { shouldHideAssetDetailStructuredView } from "./asset-detail-view-policy";

describe("shouldHideAssetDetailStructuredView", () => {
  it.each(["job_demand", "ability_analysis", "major_distribution"] as const)(
    "hides the migrated %s record view",
    (view) => {
      expect(shouldHideAssetDetailStructuredView(view)).toBe(true);
    },
  );

  it("recognizes job demand from compatibility signals", () => {
    expect(shouldHideAssetDetailStructuredView("generic_table", "job_demand")).toBe(true);
    expect(
      shouldHideAssetDetailStructuredView("generic_table", null, "job_demand.v1"),
    ).toBe(true);
  });

  it("retains the generic record fallback", () => {
    expect(shouldHideAssetDetailStructuredView("generic_table", "unknown", "generic_table.v1"))
      .toBe(false);
  });
});

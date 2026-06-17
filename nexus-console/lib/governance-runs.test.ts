import { describe, expect, it } from "vitest";
import {
  selectCurrentQualityCalibrationRuns,
  selectCurrentReviewRuns,
  selectLatestGovernanceRuns,
  type GovernanceRunLike,
} from "./governance-runs";

function run(overrides: Partial<GovernanceRunLike>): GovernanceRunLike {
  return {
    id: "run-1",
    normalized_ref_id: "ref-1",
    adoption_status: "review_required",
    validation_status: "schema_valid",
    quality_summary: { quality_score: 55 },
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
    ...overrides,
  };
}

describe("governance run selectors", () => {
  it("keeps only the latest run per normalized ref", () => {
    const latest = run({
      id: "latest",
      adoption_status: "auto_adopted",
      quality_summary: { quality_score: 88 },
      created_at: "2026-06-02T00:00:00Z",
      updated_at: "2026-06-02T00:00:00Z",
    });
    const historical = run({ id: "historical" });

    expect(selectLatestGovernanceRuns([historical, latest])).toEqual([latest]);
  });

  it("does not return historical review rows once the latest run is adopted", () => {
    const rows = [
      run({ id: "old-review", adoption_status: "review_required" }),
      run({
        id: "new-adopted",
        adoption_status: "auto_adopted",
        quality_summary: { quality_score: 91 },
        created_at: "2026-06-03T00:00:00Z",
        updated_at: "2026-06-03T00:00:00Z",
      }),
    ];

    expect(selectCurrentReviewRuns(rows)).toEqual([]);
    expect(selectCurrentQualityCalibrationRuns(rows)).toEqual([]);
  });

  it("keeps current low-quality review rows in calibration queue", () => {
    const current = run({
      id: "current-review",
      adoption_status: "pending_rule_guardrail",
      quality_summary: { quality_score: 62 },
      created_at: "2026-06-04T00:00:00Z",
      updated_at: "2026-06-04T00:00:00Z",
    });

    expect(selectCurrentReviewRuns([current])).toEqual([current]);
    expect(selectCurrentQualityCalibrationRuns([current])).toEqual([current]);
  });
});

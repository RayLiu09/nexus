import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { GovernanceTrace } from "./GovernanceTrackingContent";

vi.mock("./AssetRefCell", () => ({
  AssetRefCell: ({ title }: { title: string | null }) => <span>{title}</span>,
}));

vi.mock("./DecisionTrailDrawer", () => ({
  DecisionTrailDrawer: ({
    open,
    governanceResultId,
  }: {
    open: boolean;
    governanceResultId: string | null;
  }) => open ? <div data-testid="decision-trail-id">{governanceResultId}</div> : null,
}));

import { GovernanceTrackingContent } from "./GovernanceTrackingContent";

const row: GovernanceTrace = {
  governance_result_id: "historical-result-7",
  normalized_ref_id: "normalized-ref-1",
  asset_id: "asset-1",
  asset_title: "历史治理资产",
  classification: "industry_report",
  level: "L1",
  quality_summary: { quality_level: "pass", quality_score: 92 },
  governance_status: "available",
  index_admission: true,
  decision_mode: "human_overridden",
  review_decision_id: "review-1",
  reviewer_id: "reviewer-1",
  reviewer_name: "治理专家",
  review_reason: "人工调整分类",
  created_at: "2026-07-28T08:00:00Z",
  updated_at: "2026-07-28T08:00:00Z",
};

describe("GovernanceTrackingContent", () => {
  it("opens the exact historical governance result selected from the table", () => {
    render(
      <GovernanceTrackingContent
        initialRows={[row]}
        initialTotal={1}
        error={null}
        tagDictionary={{}}
        classificationDictionary={{ industry_report: "产业报告" }}
        levelDictionary={{ L1: "公开" }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "查看证据" }));

    expect(screen.getByText("产业报告")).toBeInTheDocument();
    expect(screen.getByText("公开")).toBeInTheDocument();
    expect(screen.queryByText("industry_report")).not.toBeInTheDocument();
    expect(screen.queryByText("L1")).not.toBeInTheDocument();
    expect(screen.getByTestId("decision-trail-id")).toHaveTextContent("historical-result-7");
  });
});

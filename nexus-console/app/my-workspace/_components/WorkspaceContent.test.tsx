import { describe, expect, it } from "vitest";

Object.defineProperty(globalThis, "ResizeObserver", {
  writable: true,
  value: class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
});

import { WorkspaceContent } from "./WorkspaceContent";
import { renderWithProviders, screen } from "@/test-utils/test-renderer";

describe("WorkspaceContent", () => {
  it("shows the asset name and ID for a pending task without the recent activity panel", () => {
    renderWithProviders(
      <WorkspaceContent
        pendingReview={[
          {
            id: "run-00000001",
            normalized_ref_id: "ref-00000001",
            profile_id: null,
            model_alias: "doubao/test-model",
            prompt_version: "v1",
            ai_output: { classification: "industry_policy" },
            quality_summary: null,
            validation_status: "schema_valid",
            adoption_status: "review_required",
            validation_error: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            asset_title: "电子商务产业政策",
            asset_id: "asset-00000001",
          },
        ]}
      />,
    );

    expect(screen.getByRole("link", { name: "电子商务产业政策" })).toHaveAttribute(
      "href",
      "/assets/asset-00000001",
    );
    expect(screen.getByText("asset")).toBeInTheDocument();
    expect(screen.getByText("产业政策")).toBeInTheDocument();
    expect(screen.queryByText("industry_policy")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "处理" })).toHaveAttribute("href", "/governance");
    expect(screen.queryByText("最近操作")).not.toBeInTheDocument();
  });
});

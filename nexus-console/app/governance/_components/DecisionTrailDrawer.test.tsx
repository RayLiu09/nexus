import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import type { GovernanceResultRead } from "../_lib/decisionTrail.types";

const { fetchGovernanceResultForRefMock } = vi.hoisted(() => ({
  fetchGovernanceResultForRefMock: vi.fn(),
}));

vi.mock("../_lib/governanceResultApi", () => ({
  fetchGovernanceResultForRef: fetchGovernanceResultForRefMock,
}));

import { DecisionTrailDrawer } from "./DecisionTrailDrawer";

function makeResult(overrides: Partial<GovernanceResultRead> = {}): GovernanceResultRead {
  return {
    id: "result-1",
    normalized_ref_id: "ref-1",
    ai_run_id: "run-1",
    classification: "sector_report",
    level: "L1",
    tags: [],
    org_scope: "all",
    index_admission: true,
    quality_summary: { quality_score: 85, quality_level: "pass" },
    decision_trail: [
      {
        field_name: "classification",
        ai_suggestion: "sector_report",
        ai_confidence: 0.95,
        threshold_check: { confidence_threshold_auto_adopt: 0.8, actual_confidence: 0.95 },
        final_value: "sector_report",
        adoption_status: "auto_adopted",
        review_reason: null,
      },
      {
        field_name: "tags",
        ai_suggestion: [],
        ai_confidence: 0.95,
        threshold_check: {
          confidence_threshold_auto_adopt: 0.8,
          actual_confidence: 0.95,
          valid_tags: [],
        },
        final_value: [],
        adoption_status: "auto_adopted",
        review_reason: null,
      },
    ],
    rules_schema_version: "1.0.0",
    rules_content_hash: "abc123",
    status: "available",
    created_by: null,
    trace_id: "trace-1",
    created_at: "2026-06-17T00:00:00Z",
    updated_at: "2026-06-17T00:00:00Z",
    ...overrides,
  };
}

describe("DecisionTrailDrawer", () => {
  beforeEach(() => {
    fetchGovernanceResultForRefMock.mockReset();
  });

  it("falls back to AI run tags when result.tags and trail final_value are empty", async () => {
    fetchGovernanceResultForRefMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: makeResult(),
      traceId: "trace-1",
    });

    render(
      <DecisionTrailDrawer
        open
        normalizedRefId="ref-1"
        onClose={() => {}}
        tagDictionary={{}}
        classificationDictionary={{ sector_report: "行业报告" }}
        fallbackTags={{
          _stages: {
            tagging: {
              tags: {
                professional_domain: [{ value: "电子商务" }],
                data_source_type: [{ value: "第三方行业研究机构" }],
              },
            },
          },
        }}
      />,
    );

    // OutcomeSummary shows the fallback-derived tags
    expect(await screen.findByText("#电子商务")).toBeInTheDocument();
    expect(screen.getByText("#第三方行业研究机构")).toBeInTheDocument();

    // Classification uses dictionary label, not raw code
    expect(screen.getAllByText("行业报告").length).toBeGreaterThan(0);
    expect(screen.queryByText("sector_report")).not.toBeInTheDocument();
  });

  it("normalizes threshold_check: drops empty valid_tags, exposes extracted_tag_count", async () => {
    fetchGovernanceResultForRefMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: makeResult(),
      traceId: "trace-1",
    });

    render(
      <DecisionTrailDrawer
        open
        normalizedRefId="ref-1"
        onClose={() => {}}
        tagDictionary={{}}
        classificationDictionary={{}}
        fallbackTags={["电子商务", "国际贸易"]}
      />,
    );

    await waitFor(() => {
      expect(fetchGovernanceResultForRefMock).toHaveBeenCalled();
    });

    // Open every <details> threshold panel so contents are queryable
    const detailsList = document.querySelectorAll("details");
    detailsList.forEach((d) => d.setAttribute("open", ""));

    // valid_tags key should be removed; extracted_tag_count should appear
    expect(screen.queryByText("valid_tags")).not.toBeInTheDocument();
    expect(screen.getByText("extracted_tag_count")).toBeInTheDocument();

    const countItem = screen.getByText("extracted_tag_count").closest("li");
    expect(countItem).not.toBeNull();
    expect(within(countItem as HTMLElement).getByText("2")).toBeInTheDocument();
  });

  it("uses committed result.tags when present and skips fallback", async () => {
    fetchGovernanceResultForRefMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: makeResult({
        tags: ["跨境电商"],
        decision_trail: [
          {
            field_name: "tags",
            ai_suggestion: ["跨境电商"],
            ai_confidence: 0.95,
            threshold_check: {
              confidence_threshold_auto_adopt: 0.8,
              actual_confidence: 0.95,
              extracted_tag_count: 1,
            },
            final_value: ["跨境电商"],
            adoption_status: "auto_adopted",
            review_reason: null,
          },
        ],
      }),
      traceId: "trace-1",
    });

    render(
      <DecisionTrailDrawer
        open
        normalizedRefId="ref-1"
        onClose={() => {}}
        tagDictionary={{}}
        classificationDictionary={{}}
        fallbackTags={["不应展示"]}
      />,
    );

    expect(await screen.findByText("#跨境电商")).toBeInTheDocument();
    expect(screen.queryByText("#不应展示")).not.toBeInTheDocument();
  });
});

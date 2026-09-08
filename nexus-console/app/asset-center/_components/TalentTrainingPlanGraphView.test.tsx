import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiResult, TalentTrainingPlanGraph } from "@/lib/api";

const { getApiDataMock } = vi.hoisted(() => ({ getApiDataMock: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, getApiData: getApiDataMock };
});

import { TalentTrainingPlanGraphView } from "./TalentTrainingPlanGraphView";

function graphResult(
  graphType: TalentTrainingPlanGraph["graph_type"],
  available?: boolean,
): ApiResult<TalentTrainingPlanGraph> {
  return {
    ok: true,
    error: null,
    traceId: null,
    total: null,
    data: {
      graph_type: graphType,
      deterministic: true,
      normalized_ref_id: "ref-1",
      plan_id: "plan/1",
      available,
      nodes: [],
      edges: [],
    },
  };
}

describe("TalentTrainingPlanGraphView", () => {
  beforeEach(() => getApiDataMock.mockReset());

  it("loads only the selected course graph endpoint", async () => {
    getApiDataMock.mockResolvedValue(graphResult("talent_training_plan_course_knowledge.v1"));

    render(<TalentTrainingPlanGraphView planId="plan/1" kind="course" />);

    await waitFor(() =>
      expect(getApiDataMock).toHaveBeenCalledWith(
        "/api/talent-training-plans/plan%2F1/course-knowledge-graph",
        null,
      ),
    );
    expect(getApiDataMock).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("暂无可绘制的图谱关系")).toBeInTheDocument();
  });

  it("loads only the selected position graph and explains unavailable evidence", async () => {
    getApiDataMock.mockResolvedValue(
      graphResult("talent_training_plan_position_capability.v1", false),
    );

    render(<TalentTrainingPlanGraphView planId="plan-2" kind="position" />);

    await waitFor(() =>
      expect(getApiDataMock).toHaveBeenCalledWith(
        "/api/talent-training-plans/plan-2/position-capability-graph",
        null,
      ),
    );
    expect(getApiDataMock).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("该方案未提供岗位能力图谱")).toBeInTheDocument();
  });
});

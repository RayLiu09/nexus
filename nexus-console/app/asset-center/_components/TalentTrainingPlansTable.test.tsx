import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TalentTrainingPlanSummary } from "@/lib/api";

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const { replaceMock } = vi.hoisted(() => ({ replaceMock: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => "/asset-center/major/training-plans",
}));

vi.mock("./TalentTrainingPlanGraphView", () => ({
  TalentTrainingPlanGraphView: ({ planId, kind }: { planId: string; kind: string }) => (
    <div data-testid="training-plan-graph">{`${planId}:${kind}`}</div>
  ),
}));

import { TalentTrainingPlansTable } from "./TalentTrainingPlansTable";

const row: TalentTrainingPlanSummary = {
  id: "plan-1",
  normalized_ref_id: "ref-1",
  asset_version_id: "version-1",
  institution_name: "湖州职业技术学院",
  major_name: "跨境电子商务",
  major_code: "530702",
  education_level: "高职",
  study_duration: "三年",
  training_goal: "培养跨境电子商务技术技能人才",
  confidence: 0.91,
  status: "generated",
  course_count: 18,
  career_orientation_summary: {
    major_categories: [{ name: "财经商贸大类", code: "53" }],
    major_classes: [{ name: "电子商务类", code: "5307" }],
    industries: [{ name: "批发业", code: "51" }],
    occupations: [{ name: "电子商务师", code: "4-01-06-01" }],
    positions: [{ name: "跨境电商运营专员" }],
  },
  created_at: "2026-09-08T00:00:00Z",
  updated_at: "2026-09-08T00:00:00Z",
};

function renderTable() {
  return render(
    <TalentTrainingPlansTable
      rows={[row]}
      total={1}
      page={1}
      pageSize={20}
      filters={{}}
      ok
      error={null}
      traceId={null}
    />,
  );
}

describe("TalentTrainingPlansTable", () => {
  beforeEach(() => replaceMock.mockReset());

  it("renders plan identity and the requested expandable career dimensions", () => {
    renderTable();

    for (const heading of ["专业名称", "专业代码", "修业年限", "培养层次", "院校名称", "操作"]) {
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getByText("湖州职业技术学院")).toBeInTheDocument();
    expect(screen.getByText("跨境电子商务")).toBeInTheDocument();
    const outerHeaderCount = screen.getAllByRole("columnheader").length;

    fireEvent.click(screen.getByRole("button", { name: /Expand row|展开行/ }));

    expect(screen.getByRole("heading", { level: 4, name: "专业归属" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 4, name: "职业面向" })).toBeInTheDocument();
    expect(screen.getByTestId("career-orientation-panel")).toHaveStyle({ marginLeft: "24px" });
    for (const label of [
      "专业大类（代码）",
      "专业类（代码）",
      "所属行业",
      "职业类别",
      "岗位名称",
    ]) {
      expect(screen.getByText(label, { exact: true })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("columnheader")).toHaveLength(outerHeaderCount);
    expect(screen.getByText("财经商贸大类 (53)")).toBeInTheDocument();
    expect(screen.getByText("电子商务类 (5307)")).toBeInTheDocument();
    expect(screen.getByText("跨境电商运营专员")).toBeInTheDocument();
  });

  it("opens each migrated graph in its own drawer", async () => {
    const user = userEvent.setup();
    renderTable();

    await user.click(screen.getByRole("button", { name: /课程知识图谱/ }));
    let dialog = screen.getByRole("dialog");
    expect(within(dialog).getByTestId("training-plan-graph")).toHaveTextContent("plan-1:course");
    await user.click(within(dialog).getByRole("button", { name: /Close|关闭/ }));

    await user.click(screen.getByRole("button", { name: /岗位能力图谱/ }));
    dialog = screen.getByRole("dialog");
    expect(within(dialog).getByTestId("training-plan-graph")).toHaveTextContent("plan-1:position");
  });
});

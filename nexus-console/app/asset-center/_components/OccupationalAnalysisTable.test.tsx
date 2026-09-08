import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AbilityAnalysis,
  ApiResult,
  OccupationalAbilityItem,
  OccupationalWorkTask,
} from "@/lib/api";

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const { replaceMock, getApiDataMock } = vi.hoisted(() => ({
  replaceMock: vi.fn(),
  getApiDataMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => "/asset-center/major/occupation-analyses",
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, getApiData: getApiDataMock };
});

vi.mock("@/app/assets/[assetId]/_components/CapabilityGraphView", () => ({
  CapabilityGraphView: ({
    normalizedRefId,
    buildType,
    embedded,
  }: {
    normalizedRefId: string;
    buildType: string;
    embedded?: boolean;
  }) => (
    <div data-embedded={embedded} data-testid="ability-graph">
      {`${normalizedRefId}:${buildType}`}
    </div>
  ),
}));

import { OccupationalAnalysisTable } from "./OccupationalAnalysisTable";

const analysis: AbilityAnalysis = {
  id: "analysis-1",
  normalized_ref_id: "ref-1",
  asset_version_id: "version-1",
  profile_id: "profile-1",
  analysis_model: "PGSD",
  major_name: "电子商务",
  major_direction: null,
  source_job_demand_dataset_id: null,
  task_count: 12,
  work_content_count: 30,
  ability_item_count: 90,
  general_ability_count: 20,
  development_ability_count: 10,
  occupational_ability_count: 45,
  social_ability_count: 15,
  schema_version: "ability_analysis.pgsd.v1",
  quality_summary: {},
};

const task: OccupationalWorkTask = {
  id: "task-1",
  analysis_id: analysis.id,
  task_code: "1",
  task_name: "市场数据采集",
  task_description: null,
  task_description_structured: {},
  display_order: 1,
  trace: {},
  work_contents: [],
};

function abilityItem(id: string, description: string): OccupationalAbilityItem {
  return {
    id,
    analysis_id: analysis.id,
    task_id: task.id,
    work_content_id: null,
    ability_code: `G-${id}`,
    ability_major_category_code: "G",
    ability_major_category_name: "通用能力",
    ability_sequence: id,
    ability_content: description,
    normalized_terms: {},
    confidence: 0.9,
    quality_flags: {},
  };
}

function apiResult<T>(data: T, total: number | null = null): ApiResult<T> {
  return { data, total, ok: true, error: null, traceId: null };
}

function renderTable() {
  return render(
    <OccupationalAnalysisTable
      rows={[analysis]}
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

describe("OccupationalAnalysisTable", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    getApiDataMock.mockReset();
    getApiDataMock.mockImplementation((path: string) => {
      if (path.endsWith("/tasks")) return Promise.resolve(apiResult([task], 1));
      return Promise.resolve(apiResult([abilityItem("1", "能够完成市场数据采集")], 1));
    });
  });

  it("renders the requested business columns, category counts, and row actions", () => {
    renderTable();

    for (const heading of [
      "专业名称",
      "分析模型",
      "典型任务数",
      "通用能力数",
      "发展能力数",
      "职业能力数",
      "社会能力数",
      "操作",
    ]) {
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getByText("电子商务")).toBeInTheDocument();
    expect(screen.getByText("PGSD")).toBeInTheDocument();
    for (const action of ["能力条目", "能力树", "能力图谱"]) {
      expect(screen.getByRole("button", { name: new RegExp(action) })).toBeInTheDocument();
    }
  });

  it("shows only three ability-item columns and drives pagination from the server", async () => {
    getApiDataMock.mockImplementation(
      (path: string, _fallback: unknown, params: Record<string, string>) => {
        if (path.endsWith("/tasks")) return Promise.resolve(apiResult([task], 1));
        if (params.page === "2") {
          return Promise.resolve(apiResult([abilityItem("21", "第二页能力")], 25));
        }
        return Promise.resolve(apiResult([abilityItem("1", "第一页能力")], 25));
      },
    );
    const user = userEvent.setup();
    renderTable();

    await user.click(screen.getByRole("button", { name: /能力条目/ }));
    const dialog = await screen.findByRole("dialog");
    for (const heading of ["类别", "能力描述", "对应任务名称"]) {
      expect(within(dialog).getByRole("columnheader", { name: heading })).toBeInTheDocument();
    }
    expect(within(dialog).getAllByRole("columnheader")).toHaveLength(3);
    expect(await screen.findByText("第一页能力")).toBeInTheDocument();
    expect(screen.getByText("市场数据采集")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("2"));
    await waitFor(() =>
      expect(getApiDataMock).toHaveBeenCalledWith(
        "/api/record-assets/ability-analyses/analysis-1/ability-items",
        [],
        { page: "2", pageSize: "20" },
      ),
    );
    expect(await screen.findByText("第二页能力")).toBeInTheDocument();
  });

  it("opens the migrated ability tree and graph views", async () => {
    const user = userEvent.setup();
    const first = renderTable();

    await user.click(screen.getByRole("button", { name: /能力树/ }));
    expect(await screen.findByText("市场数据采集")).toBeInTheDocument();
    expect(getApiDataMock).toHaveBeenCalledWith(
      "/api/record-assets/ability-analyses/analysis-1/tasks",
      [],
      { page: "1", pageSize: "200" },
    );
    first.unmount();

    renderTable();
    await user.click(screen.getByRole("button", { name: /能力图谱/ }));
    expect(screen.getByTestId("ability-graph")).toHaveTextContent("ref-1:ability_analysis");
    expect(screen.getByTestId("ability-graph")).toHaveAttribute("data-embedded", "true");
  });
});

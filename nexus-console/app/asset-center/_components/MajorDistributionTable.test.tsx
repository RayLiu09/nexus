import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MajorDistributionRecord } from "@/lib/api";

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const { replaceMock, refreshMock, patchMock, deleteMock } = vi.hoisted(() => ({
  replaceMock: vi.fn(),
  refreshMock: vi.fn(),
  patchMock: vi.fn(),
  deleteMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, refresh: refreshMock }),
  usePathname: () => "/asset-center/major/distributions",
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    patchApiData: patchMock,
    deleteApiData: deleteMock,
  };
});

import { MajorDistributionTable } from "./MajorDistributionTable";

const row: MajorDistributionRecord = {
  id: "record-1",
  dataset_id: "dataset-1",
  normalized_ref_id: "ref-1",
  source_record_key: "sheet-1:2",
  source_row_no: 2,
  year: 2025,
  year_text: "2025年",
  province_name: "浙江省",
  region_scope: "province",
  major_name: "电子商务",
  major_code: "530701",
  education_level: "高等职业教育专科",
  distribution_count: 36,
  quality_flags: {},
  trace: {},
  created_at: "2026-09-08T00:00:00Z",
};

function renderTable() {
  return render(
    <MajorDistributionTable
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

describe("MajorDistributionTable", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    refreshMock.mockReset();
    patchMock.mockReset();
    deleteMock.mockReset();
  });

  it("renders cross-dataset business fields and stores filters in the URL", async () => {
    renderTable();

    for (const heading of [
      "年份",
      "省份",
      "专业名称",
      "专业代码",
      "培养层次",
      "区域",
      "布点数",
      "操作",
    ]) {
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getByText("浙江省")).toBeInTheDocument();
    expect(screen.getByText("电子商务")).toBeInTheDocument();
    expect(screen.getByText("530701")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("专业名称"), "电子商务");
    await user.click(screen.getByRole("button", { name: /查询/ }));

    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith(
        "/asset-center/major/distributions?major_name=%E7%94%B5%E5%AD%90%E5%95%86%E5%8A%A1",
      ),
    );
  });

  it("clears visible filter values and the URL query", async () => {
    const user = userEvent.setup();
    render(
      <MajorDistributionTable
        rows={[row]}
        total={1}
        page={1}
        pageSize={20}
        filters={{ major_name: "电子商务", year: "2025" }}
        ok
        error={null}
        traceId={null}
      />,
    );

    const majorName = screen.getByPlaceholderText("专业名称");
    expect(majorName).toHaveValue("电子商务");
    await user.click(screen.getByRole("button", { name: /重置/ }));

    expect(majorName).toHaveValue("");
    expect(screen.getByPlaceholderText("年份")).toHaveValue("");
    expect(replaceMock).toHaveBeenCalledWith("/asset-center/major/distributions");
  });

  it("updates and deletes records through the existing audited proxy routes", async () => {
    const user = userEvent.setup();
    patchMock.mockResolvedValue({ data: { ...row, distribution_count: 40 }, meta: {} });
    deleteMock.mockResolvedValue({ data: { id: row.id, deleted: true }, meta: {} });
    renderTable();

    await user.click(screen.getByRole("button", { name: /编辑/ }));
    const countInput = screen.getByRole("spinbutton", { name: "布点数" });
    await user.clear(countInput);
    await user.type(countInput, "40");
    await user.click(screen.getByRole("button", { name: "保 存" }));

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith(
        "/api/record-assets/major-distribution-records/record-1",
        expect.objectContaining({ distribution_count: 40 }),
      ),
    );
    expect(await screen.findByText("40")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /删除/ }));
    await user.click(screen.getByRole("button", { name: "删 除" }));

    await waitFor(() =>
      expect(deleteMock).toHaveBeenCalledWith(
        "/api/record-assets/major-distribution-records/record-1",
      ),
    );
    expect(await screen.findByText("暂无专业布点记录")).toBeInTheDocument();
    expect(refreshMock).toHaveBeenCalledTimes(2);
  });
});

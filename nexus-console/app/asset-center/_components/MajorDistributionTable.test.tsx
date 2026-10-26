import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MajorOfferingRecord } from "@/lib/api";

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

const row: MajorOfferingRecord = {
  id: "record-1", sync_run_id: "run-1", provider_code: "moe_major_offering",
  year: 2025, province_code: "ZJ", province_name: "浙江省",
  major_name: "电子商务", major_code: "530701", school_code: null,
  school_name: "浙江某学院", study_duration: "3", remark: null,
  source_url: "https://zwfw.moe.gov.cn/zyyxzy/result.html",
  fetched_at: "2026-10-23T00:00:00Z", created_at: "2026-10-23T00:00:00Z",
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
      "学校标识码",
      "学校名称",
      "年限",
      "备注",
    ]) {
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getByText("浙江省")).toBeInTheDocument();
    expect(screen.getByText("电子商务")).toBeInTheDocument();
    expect(screen.getByText("530701")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("专业名称"), "电子商务");
    await user.click(screen.getByRole("button", { name: /检索/ }));

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

  it("is read only and exposes neither edit nor delete actions", () => {
    renderTable();
    expect(screen.queryByRole("button", { name: /编辑|删除/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "操作" })).not.toBeInTheDocument();
    expect(screen.getByText("浙江某学院")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "学校标识码" })).not.toBeInTheDocument();
    expect(screen.queryByText(/来源：教育部政务服务平台/)).not.toBeInTheDocument();
    expect(patchMock).not.toHaveBeenCalled();
    expect(deleteMock).not.toHaveBeenCalled();
  });

  it("exports all rows matching applied filters without list pagination or unsaved inputs", async () => {
    const user = userEvent.setup();
    render(<MajorDistributionTable rows={[row]} total={201} page={2} pageSize={100}
      filters={{ year: "2025", major_name: "电子商务", school_name: "浙江" }} ok error={null} traceId={null} />);
    const link = screen.getByRole("link", { name: /导出 Excel/ });
    const url = new URL(link.getAttribute("href")!, "http://localhost");
    expect(url.pathname).toBe("/api/asset-center/major-offerings/export");
    expect(Object.fromEntries(url.searchParams)).toEqual({ year: "2025", major_name: "电子商务", school_name: "浙江" });
    await user.type(screen.getByRole("textbox", { name: "专业名称" }), "草稿");
    expect(link.getAttribute("href")).toBe(url.pathname + url.search);
  });
});

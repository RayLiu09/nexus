import { App } from "antd";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const patchApiData = vi.hoisted(() => vi.fn());
const replaceMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ patchApiData }));

vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, refresh: vi.fn() }),
  usePathname: () => "/asset-center/major/talent-demand-reports",
}));

import { TalentDemandReportsTable } from "./TalentDemandReportsTable";

describe("TalentDemandReportsTable", () => {
  it("shows report identity and all document actions", () => {
    render(
      <App>
        <TalentDemandReportsTable
          rows={[{
            id: "asset-1", asset_name: "大数据技术专业人才需求与培养调研报告",
            major_name: "大数据技术", major_code: "510205", institution_name: null,
            content_tags: ["岗位需求"], normalized_ref_id: "ref-1", raw_object_id: "raw-1",
          }]}
          total={1} page={1} pageSize={20} ok error={null} traceId={null} canEdit
        />
      </App>,
    );
    expect(screen.getByText("大数据技术（510205）")).toBeInTheDocument();
    expect(screen.getByText("岗位需求")).toBeInTheDocument();
    for (const action of ["编辑", "解析预览", "RAG知识块", "原文下载"]) {
      expect(screen.getByRole("button", { name: action })).toBeEnabled();
    }
  });

  it("does not offer editing to a platform data administrator", () => {
    render(<App><TalentDemandReportsTable
      rows={[{
        id: "asset-1", asset_name: "报告", major_name: null, major_code: null,
        institution_name: null, content_tags: [], normalized_ref_id: "ref-1", raw_object_id: "raw-1",
      }]}
      total={1} page={1} pageSize={20} ok error={null} traceId={null} canEdit={false}
    /></App>);
    expect(screen.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument();
  });

  it("saves only completed identity fields through the list action", async () => {
    patchApiData.mockResolvedValueOnce({ data: {
      major_name: "大数据与会计", major_code: "530302", institution_name: null,
    } });
    const user = userEvent.setup();
    render(<App><TalentDemandReportsTable
      rows={[{
        id: "asset-2", asset_name: "会计报告", major_name: "大数据与会计", major_code: null,
        institution_name: null, content_tags: [], normalized_ref_id: "ref-2", raw_object_id: "raw-2",
      }]}
      total={1} page={1} pageSize={20} ok error={null} traceId={null} canEdit
    /></App>);
    await user.click(screen.getByRole("button", { name: "编辑" }));
    await user.type(within(screen.getByRole("dialog")).getByRole("textbox", { name: "专业代码" }), "530302");
    expect(screen.getByRole("dialog").textContent).toMatch(/保\s*存/);
    await user.click(screen.getByRole("button", { name: /保\s*存/ }));
    expect(patchApiData).toHaveBeenCalledWith(
      "/api/talent-demand-reports/asset-2/identity",
      { normalized_ref_id: "ref-2", major_code: "530302" },
    );
    expect(await screen.findByText("大数据与会计（530302）")).toBeInTheDocument();
  });

  it("searches the three identity fields and content tags from one toolbar", async () => {
    replaceMock.mockReset();
    const user = userEvent.setup();
    const filters = { major_name: "商务", major_code: "5307", institution_name: "重庆", content_tag: "融合" };
    render(<App><TalentDemandReportsTable rows={[]} total={120} page={1} pageSize={50}
      filters={filters} canEdit={false} ok error={null} traceId={null} /></App>);
    expect(screen.getAllByRole("form")).toHaveLength(1);
    expect(screen.queryByRole("textbox", { name: "区域" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "行业" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("listitem", { name: "2" }));
    let query = new URL(replaceMock.mock.lastCall![0], "http://localhost").searchParams;
    expect(Object.fromEntries(query)).toEqual({ ...filters, page: "2", pageSize: "50" });
    await user.clear(screen.getByRole("textbox", { name: "内容标签" }));
    await user.type(screen.getByRole("textbox", { name: "内容标签" }), " 数字 ");
    await user.click(screen.getByRole("button", { name: "检索" }));
    query = new URL(replaceMock.mock.lastCall![0], "http://localhost").searchParams;
    expect(Object.fromEntries(query)).toEqual({ ...filters, content_tag: "数字", pageSize: "50" });
    await user.click(screen.getByRole("button", { name: /重\s*置/ }));
    expect(screen.getByRole("textbox", { name: "专业名称" })).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "内容标签" })).toHaveValue("");
    expect(replaceMock).toHaveBeenLastCalledWith("/asset-center/major/talent-demand-reports?pageSize=50");
  });
});

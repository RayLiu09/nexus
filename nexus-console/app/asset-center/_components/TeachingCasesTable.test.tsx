import { App } from "antd";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/asset-center/teaching-resources/cases",
}));

import { TeachingCasesTable } from "./TeachingCasesTable";

describe("TeachingCasesTable", () => {
  it("shows the requested columns and document actions", () => {
    render(<App><TeachingCasesTable
      rows={[{
        id: "asset-1", asset_name: "智慧家居电商运营数据处理",
        content_tags: ["电商运营"], normalized_ref_id: "ref-1", raw_object_id: "raw-1",
      }]}
      total={1} page={1} pageSize={20} ok error={null} traceId={null}
    /></App>);
    expect(screen.getByText("智慧家居电商运营数据处理")).toBeInTheDocument();
    expect(screen.getByText("电商运营")).toBeInTheDocument();
    for (const action of ["解析预览", "RAG知识块", "原文下载"]) {
      expect(screen.getByRole("button", { name: action })).toBeEnabled();
    }
    expect(screen.getAllByRole("columnheader").map((node) => node.textContent)).toEqual([
      "资产名称", "内容标签", "操作",
    ]);
  });

  it("disables unavailable document actions", () => {
    render(<App><TeachingCasesTable
      rows={[{
        id: "asset-2", asset_name: "案例", content_tags: [],
        normalized_ref_id: null, raw_object_id: null,
      }]}
      total={1} page={1} pageSize={20} ok error={null} traceId={null}
    /></App>);
    for (const action of ["解析预览", "RAG知识块", "原文下载"]) {
      expect(screen.getByRole("button", { name: action })).toBeDisabled();
    }
  });

  it("opens the preview without a deprecated Drawer width warning", async () => {
    const consoleError = vi.spyOn(console, "error");
    try {
      render(<App><TeachingCasesTable
        rows={[{
          id: "asset-3", asset_name: "教学案例", content_tags: [],
          normalized_ref_id: "ref-3", raw_object_id: null,
        }]}
        total={1} page={1} pageSize={20} ok error={null} traceId={null}
      /></App>);
      await userEvent.click(screen.getByRole("button", { name: "解析预览" }));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      expect(consoleError.mock.calls.flat().join(" ")).not.toContain("Drawer] `width` is deprecated");
    } finally {
      consoleError.mockRestore();
    }
  });
});

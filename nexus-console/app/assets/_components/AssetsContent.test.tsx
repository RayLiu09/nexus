import { describe, expect, it, vi } from "vitest";

const replace = vi.fn();

Object.defineProperty(globalThis, "ResizeObserver", {
  writable: true,
  value: class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
});

vi.mock("next/navigation", () => ({
  usePathname: () => "/assets",
  useRouter: () => ({ replace }),
}));

import { AssetsContent } from "./AssetsContent";
import { renderWithProviders, screen } from "@/test-utils/test-renderer";

const catalogAsset = {
  id: "asset-1",
  data_source_id: "data-source-1",
  source_object_key: "report.pdf",
  title: "产业报告",
  asset_kind: "document",
  status: "available",
  org_scope: ["org-a"],
  metadata_summary: {},
  created_at: "2026-08-27T00:00:00Z",
  updated_at: "2026-08-27T00:00:00Z",
  current_version_no: 7,
  content_tags: ["产业", "报告", "人才", "区域"],
};

describe("AssetsContent", () => {
  it("submits a tag search while preserving the other catalog filters", async () => {
    const { user } = renderWithProviders(
      <AssetsContent
        assets={[]}
        totalCount={0}
        currentPage={2}
        pageSize={20}
        filters={{ domain: "industry_policy", level: "L2", status: "visible" }}
        ok
        error={null}
        traceId={null}
      />,
    );

    const input = screen.getByRole("searchbox", { name: "按标签搜索资产" });
    await user.type(input, "电子商务");
    await user.click(screen.getByRole("button", { name: /搜\s*索/ }));

    expect(replace).toHaveBeenLastCalledWith(
      "/assets?domain=industry_policy&level=L2&status=visible&tags=%E7%94%B5%E5%AD%90%E5%95%86%E5%8A%A1",
    );
  });

  it("does not render the removed saved-view action", () => {
    renderWithProviders(
      <AssetsContent
        assets={[]}
        totalCount={0}
        currentPage={1}
        pageSize={20}
        filters={{ status: "visible" }}
        ok
        error={null}
        traceId={null}
      />,
    );

    expect(screen.queryByRole("button", { name: "保存视图" })).not.toBeInTheDocument();
  });

  it("replaces organization scope and current version columns with official content tags", () => {
    renderWithProviders(
      <AssetsContent
        assets={[catalogAsset]}
        totalCount={1}
        currentPage={1}
        pageSize={20}
        filters={{ status: "visible" }}
        ok
        error={null}
        traceId={null}
      />,
    );

    expect(screen.queryByRole("columnheader", { name: "组织范围" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "当前版本" })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "内容标签" })).toBeInTheDocument();
    expect(screen.getByText("产业")).toBeInTheDocument();
    expect(screen.getByText("报告")).toBeInTheDocument();
    expect(screen.getByText("人才")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();
  });

  it("submits each comma-separated tag as an independent query value", async () => {
    const { user } = renderWithProviders(
      <AssetsContent
        assets={[]}
        totalCount={0}
        currentPage={1}
        pageSize={20}
        filters={{ status: "visible" }}
        ok
        error={null}
        traceId={null}
      />,
    );

    const input = screen.getByRole("searchbox", { name: "按标签搜索资产" });
    await user.type(input, "跨境电商，直播电商");
    await user.click(screen.getByRole("button", { name: /搜\s*索/ }));

    expect(replace).toHaveBeenLastCalledWith(
      "/assets?status=visible&tags=%E8%B7%A8%E5%A2%83%E7%94%B5%E5%95%86&tags=%E7%9B%B4%E6%92%AD%E7%94%B5%E5%95%86",
    );
  });
});

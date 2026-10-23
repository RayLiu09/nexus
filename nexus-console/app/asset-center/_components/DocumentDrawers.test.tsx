import { App } from "antd";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/asset-center",
}));
vi.mock("@/app/assets/[assetId]/_components/SourcePreviewSection", () => ({
  SourcePreviewSection: ({ refId }: { refId: string }) => <div>preview:{refId}</div>,
}));
vi.mock("@/app/assets/[assetId]/_components/ChunkListSection", () => ({
  ChunkListSection: ({ refId }: { refId: string }) => <div>chunks:{refId}</div>,
}));

import { IndustryPoliciesTable } from "./IndustryPoliciesTable";
import { TalentDemandReportsTable } from "./TalentDemandReportsTable";

describe("asset document drawers", () => {
  it.each(["policy", "talent-demand"] as const)(
    "%s opens and destroys document content without deprecated Drawer props",
    async (kind) => {
      const consoleError = vi.spyOn(console, "error");
      const consoleWarn = vi.spyOn(console, "warn");
      const user = userEvent.setup();
      try {
        const common = { total: 1, page: 1, pageSize: 20, ok: true, error: null, traceId: null };
        const row = {
          id: "asset-1",
          asset_name: "文档",
          normalized_ref_id: "ref-1",
          content_tags: [],
        };
        render(
          <App>
            {kind === "policy" ? (
              <IndustryPoliciesTable
                {...common}
                rows={[{ ...row, region: [], industry: [], publish_date: null }]}
                allCount={1}
                topicCounts={{ finance_commerce: 1, low_altitude: 0 }}
              />
            ) : (
              <TalentDemandReportsTable
                {...common}
                canEdit={false}
                rows={[
                  {
                    ...row,
                    major_name: null,
                    major_code: null,
                    institution_name: null,
                    raw_object_id: null,
                  },
                ]}
              />
            )}
          </App>,
        );
        await user.click(screen.getByRole("button", { name: "解析预览" }));
        expect(await screen.findByText("preview:ref-1")).toBeVisible();
        await user.click(screen.getByRole("button", { name: /Close|关闭/ }));
        await waitFor(() => expect(screen.queryByText("preview:ref-1")).not.toBeInTheDocument());
        await user.click(screen.getByRole("button", { name: /知识块/ }));
        expect(await screen.findByText("chunks:ref-1")).toBeVisible();
        const messages = [...consoleError.mock.calls, ...consoleWarn.mock.calls].flat().join(" ");
        expect(messages).not.toMatch(/\[antd: Drawer\].*deprecated|destroyOnClose/);
      } finally {
        consoleError.mockRestore();
        consoleWarn.mockRestore();
      }
    },
  );
});

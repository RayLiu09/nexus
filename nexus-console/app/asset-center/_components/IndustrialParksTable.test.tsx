import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { IndustrialPark } from "@/lib/api";

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
  usePathname: () => "/asset-center/market/industrial-parks",
}));

import { IndustrialParksTable } from "./IndustrialParksTable";

describe("IndustrialParksTable", () => {
  it("renders industry tags returned as text by the park API", () => {
    const park: IndustrialPark = {
      id: "park-1",
      park_name: "数字产业园",
      industry_tags: "数字经济、智能制造",
      introduction: "产业集聚园区",
      enterprise_count: 3,
      source_url: null,
    };

    render(
      <IndustrialParksTable
        rows={[park]}
        total={1}
        page={1}
        pageSize={20}
        ok
        error={null}
        traceId={null}
      />,
    );

    expect(screen.getByText("数字产业园")).toBeInTheDocument();
    expect(screen.getByText("数字经济、智能制造")).toBeInTheDocument();
  });
});

import { App } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  usePathname: () => "/asset-center/policy/industry-reports",
}));

import { IndustryPoliciesTable } from "./IndustryPoliciesTable";

describe("IndustryPoliciesTable topic filters", () => {
  beforeEach(() => replaceMock.mockReset());

  it("shows full-list counts and resets the page when a topic is selected", () => {
    render(
      <App>
        <IndustryPoliciesTable
          rows={[]}
          total={12}
          allCount={40}
          topicCounts={{ finance_commerce: 12, low_altitude: 9 }}
          page={1}
          pageSize={20}
          ok
          error={null}
          traceId={null}
        />
      </App>,
    );

    expect(screen.getByRole("button", { name: "全部 40" })).toHaveAttribute("aria-pressed", "true");
    const lowAltitude = screen.getByRole("button", { name: "低空经济类 9" });
    expect(lowAltitude.className).toContain("bg-amber-50");
    expect(screen.getByRole("button", { name: "财经商贸类 12" }).className).toContain(
      "bg-emerald-50",
    );
    fireEvent.click(lowAltitude);
    expect(replaceMock).toHaveBeenCalledWith(
      "/asset-center/policy/industry-reports?topic=low_altitude",
    );
  });

  it("retains the selected topic when pagination changes", async () => {
    const user = userEvent.setup();
    render(
      <App>
        <IndustryPoliciesTable
          rows={[]}
          total={28}
          allCount={40}
          topicCounts={{ finance_commerce: 28, low_altitude: 9 }}
          topic="finance_commerce"
          page={1}
          pageSize={20}
          filters={{ region: "重庆市", industry: "电子商务" }}
          ok
          error={null}
          traceId={null}
        />
      </App>,
    );

    await user.click(screen.getByRole("listitem", { name: "2" }));
    expect(replaceMock).toHaveBeenCalledWith(
      "/asset-center/policy/industry-reports?region=%E9%87%8D%E5%BA%86%E5%B8%82&industry=%E7%94%B5%E5%AD%90%E5%95%86%E5%8A%A1&topic=finance_commerce&page=2",
    );
  });

  it("submits tag filters at page one while retaining the selected topic", async () => {
    const user = userEvent.setup();
    render(
      <App>
        <IndustryPoliciesTable
          rows={[]}
          total={100}
          allCount={40}
          topicCounts={{ finance_commerce: 12, low_altitude: 9 }}
          topic="finance_commerce"
          page={3}
          pageSize={20}
          filters={{}}
          ok
          error={null}
          traceId={null}
        />
      </App>,
    );

    fireEvent.change(screen.getByRole("textbox", { name: "区域" }), {
      target: { value: " 重庆市 " },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "行业" }), {
      target: { value: "电子商务" },
    });
    await user.click(screen.getByRole("button", { name: "检索" }));
    expect(replaceMock).toHaveBeenLastCalledWith(
      "/asset-center/policy/industry-reports?region=%E9%87%8D%E5%BA%86%E5%B8%82&industry=%E7%94%B5%E5%AD%90%E5%95%86%E5%8A%A1&topic=finance_commerce",
    );
  });
});

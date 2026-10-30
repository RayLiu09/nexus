import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { EcommerceDemoBase, EcommerceDemoBaseAggregate } from "@/lib/api";
import { EcommerceDemoBasesView } from "./EcommerceDemoBasesView";

const { push, refresh, distribution } = vi.hoisted(() => ({
  push: vi.fn(),
  refresh: vi.fn(),
  distribution: vi.fn(() => <div />),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
  usePathname: () => "/asset-center/market/ecommerce-demo-bases",
}));
vi.mock("./NationalDemoBaseDistribution", () => ({ NationalDemoBaseDistribution: distribution }));
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const row: EcommerceDemoBase = {
  id: "provincial-1",
  level: "provincial",
  title: "江苏省电子商务示范基地",
  province_code: "320000",
  province_name: "江苏省",
  batch_code: null,
  batch_name: null,
  recognized_period: "2019年7月",
  recognized_year: 2019,
  recognized_month: 7,
  source_publish_at: "2019-07-31T18:00:00+00:00",
  source_order: 1,
  source_link_enabled: true,
  source_url: "https://dzswgf.mofcom.gov.cn/news/3/2019/7/3.html",
};
const aggregate: EcommerceDemoBaseAggregate = {
  matched_total: 1,
  batch_counts: [],
  province_counts: [],
  filter_options: {
    batches: [],
    provinces: [{ province_code: "320000", province_name: "江苏省", count: 142 }],
    recognized_years: [2019],
  },
  coverage: { imported_total: 142, source_files: [] },
};
const props = {
  rows: [row],
  total: 142,
  page: 2,
  pageSize: 20,
  level: "provincial" as const,
  filters: {},
  aggregate,
  ok: true,
  error: null,
  traceId: null,
};

function lastURL() {
  return new URL(push.mock.calls.at(-1)![0], "http://localhost");
}

describe("EcommerceDemoBasesView", () => {
  it("renders a provincial read-only list, continuous numbering and Shanghai publication date", () => {
    render(<EcommerceDemoBasesView {...props} />);
    expect(screen.getByText(row.title)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "省级电子商务示范基地" })).toBeInTheDocument();
    expect(screen.getByText("21")).toBeInTheDocument();
    expect(screen.getByText("2019/08/01")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看原文" })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
    expect(screen.queryByRole("columnheader", { name: "批次" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /新增|编辑|删除|导入/ })).not.toBeInTheDocument();
  });

  it("applies draft filters only on search and resets pagination", () => {
    render(<EcommerceDemoBasesView {...props} />);
    fireEvent.change(screen.getByRole("textbox", { name: "基地名称" }), {
      target: { value: "  商务  " },
    });
    fireEvent.click(screen.getByRole("button", { name: /检索/ }));
    expect(lastURL().searchParams.get("q")).toBe("商务");
    expect(lastURL().searchParams.has("page")).toBe(false);
  });

  it("paginates with submitted filters even when the search draft has changed", () => {
    render(<EcommerceDemoBasesView {...props} filters={{ q: "已提交" }} />);
    fireEvent.change(screen.getByRole("textbox", { name: "基地名称" }), {
      target: { value: "未提交" },
    });
    fireEvent.click(screen.getByTitle("3"));
    expect(lastURL().searchParams.get("q")).toBe("已提交");
    expect(lastURL().searchParams.get("page")).toBe("3");
  });

  it("switches views with incompatible filters cleared", () => {
    render(
      <EcommerceDemoBasesView
        {...props}
        level="national"
        filters={{ batch: "first", province_code: "320000", q: "商务" }}
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "省份" }));
    expect(lastURL().search).toBe("?level=provincial");
  });

  it("does not show a successful zero total on API failure and provides retry", () => {
    render(
      <EcommerceDemoBasesView
        {...props}
        rows={[]}
        total={null}
        ok={false}
        aggregate={null}
        error="读取失败"
        traceId="trace-park"
      />,
    );
    expect(screen.getByText("读取失败")).toBeInTheDocument();
    expect(screen.getByText("trace: trace-park")).toBeInTheDocument();
    expect(screen.queryByText("共 0 条")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /重\s*试/ }));
    expect(refresh).toHaveBeenCalled();
  });
});

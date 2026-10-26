import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import type { OccupationDictionaryRecord } from "@/lib/api";
import { OccupationDictionaryTable } from "./OccupationDictionaryTable";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/asset-center/major/occupation-dictionary",
}));
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);
const row: OccupationDictionaryRecord = {
  id: "ref-1",
  edition: 2022,
  occupation_code: "2-02-10-01",
  occupation_category: "2 专业技术人员",
  major_group: "2-02 工程技术人员",
  minor_group: "2-02-10 通信技术人员",
  occupation_name: "通信工程技术人员",
  definition: "从事通信网络规划的人员。",
  work_tasks: "1.规划网络。\n2.维护网络。",
};
const baseProps = {
  rows: [row],
  total: 41,
  page: 3,
  pageSize: 20,
  filters: {},
  ok: true,
  error: null,
  traceId: null,
};
beforeEach(() => replace.mockReset());

it("shows six requested columns and complete multiline text in a read-only list", () => {
  render(<OccupationDictionaryTable {...baseProps} />);
  for (const name of ["职业类别", "职业大类", "职业小类", "职业名称", "职业定义", "工作任务"]) {
    expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
  }
  expect(screen.getByText(row.definition)).toBeInTheDocument();
  expect(screen.getByText("1.规划网络。 2.维护网络。")).toHaveClass("whitespace-pre-wrap");
  expect(screen.queryByRole("button", { name: /编辑|删除/ })).not.toBeInTheDocument();
});

it("combines three filters, trims values and resets the page on search", async () => {
  const user = userEvent.setup();
  render(<OccupationDictionaryTable {...baseProps} />);
  await user.type(screen.getByPlaceholderText("职业大类"), " 工程 ");
  await user.type(screen.getByPlaceholderText("职业小类"), "通信");
  await user.type(screen.getByPlaceholderText("职业名称"), "技术");
  await user.click(screen.getByRole("button", { name: /检索/ }));
  await waitFor(() => {
    const url = new URL(replace.mock.calls.at(-1)![0], "http://localhost");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      major_group: "工程",
      minor_group: "通信",
      occupation_name: "技术",
    });
  });
});

it("preserves applied filters when paging and clears all visible values on reset", async () => {
  const user = userEvent.setup();
  render(
    <OccupationDictionaryTable {...baseProps} page={1} filters={{ occupation_name: "通信" }} />,
  );
  await user.click(screen.getByTitle("2"));
  await waitFor(() =>
    expect(replace).toHaveBeenCalledWith(
      "/asset-center/major/occupation-dictionary?occupation_name=%E9%80%9A%E4%BF%A1&page=2",
    ),
  );
  await user.click(screen.getByRole("button", { name: /重置/ }));
  expect(screen.getByPlaceholderText("职业名称")).toHaveValue("");
  expect(replace).toHaveBeenLastCalledWith("/asset-center/major/occupation-dictionary");
});

it("surfaces load failures without presenting them as empty successful data", () => {
  render(
    <OccupationDictionaryTable {...baseProps} rows={[]} total={0} ok={false} error="读取失败" />,
  );
  expect(screen.getByText("数据加载失败")).toBeInTheDocument();
});

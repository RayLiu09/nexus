import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { postFormApiData } from "@/lib/api";
import { MajorOfferingImport } from "./MajorOfferingImport";

vi.mock("@/lib/api", () => ({ postFormApiData: vi.fn() }));
afterEach(() => vi.resetAllMocks());

async function openAndChoose(onImported = vi.fn()) {
  const user = userEvent.setup();
  render(<MajorOfferingImport onImported={onImported} />);
  await user.click(screen.getByRole("button", { name: "导入布点数据" }));
  const file = new File(["excel"], "云南布点.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  await user.upload(screen.getByLabelText("布点 Excel 文件"), file);
  return { user, file };
}

it("offers a template and imports once while pending, then reports counts and refreshes", async () => {
  let finish!: (result: { data: { import_id: string; total_count: number; imported_count: number; skipped_count: number } }) => void;
  vi.mocked(postFormApiData).mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  const refresh = vi.fn();
  const { user, file } = await openAndChoose(refresh);
  expect(screen.getByRole("link", { name: "下载导入模板" })).toHaveAttribute("href", "/api/asset-center/major-offerings/import-template");
  const submit = screen.getByRole("button", { name: "导入" });
  fireEvent.click(submit);
  fireEvent.click(submit);
  expect(postFormApiData).toHaveBeenCalledTimes(1);
  const [path, data, options] = vi.mocked(postFormApiData).mock.calls[0];
  expect(path).toBe("/api/asset-center/major-offerings/import");
  expect(data.get("file")).toBe(file);
  expect(options.idempotencyKey).toBeTruthy();
  expect(screen.getByRole("button", { name: "取消" })).toBeDisabled();
  finish({ data: { import_id: "import-1", total_count: 29, imported_count: 20, skipped_count: 9 } });
  await waitFor(() => expect(screen.getByText("共 29 条，新增 20 条，重复跳过 9 条。")).toBeInTheDocument());
  expect(refresh).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole("button", { name: "完成" }));
});

it("keeps the same key for retry and shows row errors without refreshing", async () => {
  vi.mocked(postFormApiData).mockRejectedValue(new Error("第 3 行：专业代码缺失或格式不正确"));
  const refresh = vi.fn();
  const { user } = await openAndChoose(refresh);
  await user.click(screen.getByRole("button", { name: "导入" }));
  expect(await screen.findByText("第 3 行：专业代码缺失或格式不正确")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "导入" }));
  expect(postFormApiData).toHaveBeenCalledTimes(2);
  const calls = vi.mocked(postFormApiData).mock.calls;
  expect(calls[0][2].idempotencyKey).toBe(calls[1][2].idempotencyKey);
  expect(refresh).not.toHaveBeenCalled();
});

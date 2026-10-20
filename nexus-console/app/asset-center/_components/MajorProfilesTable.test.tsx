import { App } from "antd";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import type { MajorProfileDocument } from "@/lib/api";

const { patchApiDataMock, replaceMock, refreshMock } = vi.hoisted(() => ({
  patchApiDataMock: vi.fn(), replaceMock: vi.fn(), refreshMock: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, patchApiData: patchApiDataMock };
});
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, refresh: refreshMock }),
  usePathname: () => "/asset-center/major/profiles",
}));
vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

import { MajorProfilesTable } from "./MajorProfilesTable";

const row: MajorProfileDocument = {
  id: "asset-1", asset_name: "跨境电子商务专业简介",
  normalized_ref_id: "ref-1", raw_object_id: "raw-1",
  major_name: "跨境电子商务", major_code: "530702",
  institution_name: "浙江商业职业技术学院", education_level: "高职",
  content_tags: ["电子商务"],
};

function renderTable(canEdit = true) {
  return render(<App><MajorProfilesTable
    rows={[row]} total={87} page={1} pageSize={20} filters={{}} canEdit={canEdit}
    ok error={null} traceId={null}
  /></App>);
}

beforeEach(() => {
  patchApiDataMock.mockReset();
  replaceMock.mockReset();
  refreshMock.mockReset();
});

it("shows persisted identity columns and document actions without a profile detail panel", async () => {
  renderTable();
  expect(screen.getByText("跨境电子商务")).toBeInTheDocument();
  expect(screen.getByText("530702")).toBeInTheDocument();
  expect(screen.getByText("浙江商业职业技术学院")).toBeInTheDocument();
  expect(screen.getByText("高职")).toBeInTheDocument();
  for (const label of ["编辑", "解析预览", "RAG知识块", "原文下载"]) {
    expect(screen.getByRole("button", { name: label })).toBeEnabled();
  }
  expect(screen.queryByRole("button", { name: /展开/ })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "解析预览" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("解析预览");
});

it("audits manual metadata edits through the document endpoint", async () => {
  patchApiDataMock.mockResolvedValueOnce({ data: { education_level: "高职本科" } });
  renderTable();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "编辑" }));
  await user.clear(screen.getByRole("textbox", { name: "培养层次" }));
  await user.type(screen.getByRole("textbox", { name: "培养层次" }), "高职本科");
  await user.click(screen.getByRole("button", { name: /保\s*存/ }));
  expect(patchApiDataMock).toHaveBeenCalledWith(
    "/api/major-profile-documents/asset-1/metadata",
    { normalized_ref_id: "ref-1", education_level: "高职本科" },
  );
  expect(await screen.findByText("高职本科")).toBeInTheDocument();
});

it("hides editing when the current role lacks permission", () => {
  renderTable(false);
  expect(screen.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument();
});

import { App } from "antd";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CourseTextbookSummary } from "@/lib/api";

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
  usePathname: () => "/asset-center/teaching-resources/course-textbooks",
}));

vi.mock("./CourseTextbookKnowledgeOutlineView", () => ({
  CourseTextbookKnowledgeOutlineView: ({ refId, mode }: { refId: string; mode: string }) => (
    <div data-testid="knowledge-outline-view">{`${refId}:${mode}`}</div>
  ),
}));

vi.mock("./CourseTextbookTaskOutlineView", () => ({
  CourseTextbookTaskOutlineView: ({ refId, mode }: { refId: string; mode: string }) => (
    <div data-testid="task-outline-view">{`${refId}:${mode}`}</div>
  ),
}));

vi.mock("@/app/assets/[assetId]/_components/SourcePreviewSection", () => ({
  SourcePreviewSection: ({ refId }: { refId: string }) => (
    <div data-testid="source-preview">{refId}</div>
  ),
}));
vi.mock("@/app/assets/[assetId]/_components/ChunkListSection", () => ({
  ChunkListSection: ({
    refId,
    knowledgeTypeCode,
  }: {
    refId: string;
    knowledgeTypeCode: string;
  }) => <div data-testid="chunk-list">{`${refId}:${knowledgeTypeCode}`}</div>,
}));

import { CourseTextbooksTable } from "./CourseTextbooksTable";

const theory: CourseTextbookSummary = {
  profile_id: "profile-theory",
  normalized_ref_id: "ref-theory",
  asset_version_id: "version-theory",
  asset_id: "asset-theory",
  raw_object_id: "raw-theory",
  title: "短视频拍摄与剪辑",
  textbook_type: "theory",
  textbook_type_label: "理论型",
  source_subtype: "theory_knowledge",
  publisher: "高等教育出版社",
  chief_editors: ["何牧"],
  publication_year: 2025,
};

const training: CourseTextbookSummary = {
  profile_id: "profile-training",
  normalized_ref_id: "ref-training",
  asset_version_id: "version-training",
  asset_id: "asset-training",
  raw_object_id: null,
  title: "电子商务数据分析实践",
  textbook_type: "training",
  textbook_type_label: "实训型",
  source_subtype: "training_operation",
  publisher: null,
  chief_editors: [],
  publication_year: null,
};

function renderTable() {
  return render(
    <App>
      <CourseTextbooksTable
        rows={[theory, training]}
        total={2}
        page={1}
        pageSize={20}
        filters={{}}
        ok
        error={null}
        traceId={null}
      />
    </App>,
  );
}

describe("CourseTextbooksTable", () => {
  beforeEach(() => replaceMock.mockReset());

  it("renders the frozen columns and type-specific actions", () => {
    renderTable();

    expect(screen.getAllByRole("button", { name: "检索" })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "查询" })).not.toBeInTheDocument();

    for (const heading of ["教材名称", "类型", "出版社", "主编", "出版年份", "操作"]) {
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    }
    const theoryRow = screen
      .getAllByRole("row")
      .find((row) => within(row).queryByText(theory.title))!;
    expect(within(theoryRow).getByRole("button", { name: /知识大纲径向图/ })).toBeVisible();
    expect(within(theoryRow).getByRole("button", { name: "知识大纲树" })).toBeVisible();
    expect(within(theoryRow).queryByRole("button", { name: /任务大纲/ })).toBeNull();
    for (const action of ["解析预览", "RAG知识块", "原文下载"]) {
      expect(within(theoryRow).getByRole("button", { name: action })).toBeEnabled();
    }

    const trainingRow = screen
      .getAllByRole("row")
      .find((row) => within(row).queryByText(training.title))!;
    expect(within(trainingRow).getByRole("button", { name: /任务大纲树视图/ })).toBeVisible();
    expect(within(trainingRow).getByRole("button", { name: /任务大纲圆形树/ })).toBeVisible();
    expect(within(trainingRow).queryByRole("button", { name: /知识大纲/ })).toBeNull();
    expect(within(trainingRow).getByRole("button", { name: "原文下载" })).toBeDisabled();
  }, 15000);

  it("opens source preview and RAG chunks only for the selected textbook", async () => {
    const user = userEvent.setup();
    renderTable();
    expect(screen.queryByTestId("source-preview")).not.toBeInTheDocument();
    const theoryRow = screen
      .getAllByRole("row")
      .find((row) => within(row).queryByText(theory.title))!;
    await user.click(within(theoryRow).getByRole("button", { name: "解析预览" }));
    expect(within(screen.getByRole("dialog")).getByTestId("source-preview")).toHaveTextContent(
      "ref-theory",
    );
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: /Close|关闭/ }),
    );
    await user.click(within(theoryRow).getByRole("button", { name: "RAG知识块" }));
    expect(within(screen.getByRole("dialog")).getByTestId("chunk-list")).toHaveTextContent(
      "ref-theory:course_textbook",
    );
  });

  it("requests the selected version's original download", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      json: async () => ({ ok: true, data: { download_url: "https://example.test/source" } }),
    });
    const openMock = vi.spyOn(window, "open").mockImplementation(() => null);
    vi.stubGlobal("fetch", fetchMock);
    try {
      renderTable();
      await userEvent.click(screen.getAllByRole("button", { name: "原文下载" })[0]);
      await waitFor(() =>
        expect(fetchMock).toHaveBeenCalledWith("/api/raw-objects/raw-theory/download-url", {
          cache: "no-store",
        }),
      );
      expect(openMock).toHaveBeenCalledWith(
        "https://example.test/source",
        "_blank",
        "noopener,noreferrer",
      );
    } finally {
      openMock.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it("opens each selected business view in a locked-mode drawer", async () => {
    const user = userEvent.setup();
    renderTable();

    await user.click(screen.getByRole("button", { name: "知识大纲树" }));
    let dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("知识大纲树");
    expect(dialog).not.toHaveTextContent("Left-to-Right");
    expect(within(dialog).getByTestId("knowledge-outline-view")).toHaveTextContent(
      "ref-theory:left-to-right",
    );
    await user.click(within(dialog).getByRole("button", { name: /Close|关闭/ }));

    await user.click(screen.getByRole("button", { name: /任务大纲圆形树/ }));
    dialog = screen.getByRole("dialog");
    expect(within(dialog).getByTestId("task-outline-view")).toHaveTextContent(
      "ref-training:radial",
    );
  });
});

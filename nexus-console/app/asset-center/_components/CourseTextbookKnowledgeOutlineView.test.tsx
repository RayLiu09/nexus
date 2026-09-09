import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { screen, waitFor } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils/test-renderer";
import { server } from "@/test-utils/msw-server";
import { CourseTextbookKnowledgeOutlineView } from "./CourseTextbookKnowledgeOutlineView";

const { setOption } = vi.hoisted(() => ({ setOption: vi.fn() }));

vi.mock("echarts", () => ({
  init: vi.fn(() => ({
    setOption,
    on: vi.fn(),
    dispose: vi.fn(),
    isDisposed: vi.fn().mockReturnValue(false),
    resize: vi.fn(),
  })),
}));

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const REF_ID = "ref-course-textbook";
const OUTLINE = {
  ref_id: REF_ID,
  build_run_id: "run-1",
  total_nodes: 2,
  max_depth: 1,
  fallback_used: false,
  root_id: "root",
  nodes: [
    {
      id: "root",
      parent_id: null,
      level: 0,
      order_index: 0,
      title: "短视频拍摄与剪辑",
      numbering: null,
      numbering_path: null,
      anchor_range: null,
      chunk_count: 0,
    },
    {
      id: "chapter-1",
      parent_id: "root",
      level: 1,
      order_index: 0,
      title: "短视频认知",
      numbering: "第一章",
      numbering_path: [1],
      anchor_range: { block_ids: ["block-1"] },
      chunk_count: 3,
    },
  ],
};

beforeEach(() => {
  setOption.mockClear();
  server.resetHandlers();
  server.use(
    http.get(`/api/normalized-refs/${REF_ID}/knowledge-outline`, () =>
      HttpResponse.json({ data: OUTLINE }),
    ),
  );
});

afterEach(() => vi.clearAllMocks());

describe("CourseTextbookKnowledgeOutlineView", () => {
  it("renders the migrated radial view", async () => {
    renderWithProviders(<CourseTextbookKnowledgeOutlineView refId={REF_ID} mode="radial" />);

    await waitFor(() => expect(setOption).toHaveBeenCalled());
    const option = setOption.mock.calls[0][0];
    expect(option.series[0].layout).toBe("radial");
    expect(option.series[0].orient).toBeUndefined();
    expect(screen.queryByText("2 节点")).not.toBeInTheDocument();
    expect(screen.queryByText("1 级深度")).not.toBeInTheDocument();
  });

  it("uses a true ECharts Left-to-Right orthogonal tree", async () => {
    renderWithProviders(<CourseTextbookKnowledgeOutlineView refId={REF_ID} mode="left-to-right" />);

    await waitFor(() => expect(setOption).toHaveBeenCalled());
    const option = setOption.mock.calls[0][0];
    expect(option.series[0].layout).toBe("orthogonal");
    expect(option.series[0].orient).toBe("LR");
  });

  it("renders an explicit API error state", async () => {
    server.use(
      http.get(`/api/normalized-refs/${REF_ID}/knowledge-outline`, () =>
        HttpResponse.json({ error: { message: "outline unavailable" } }, { status: 500 }),
      ),
    );

    renderWithProviders(<CourseTextbookKnowledgeOutlineView refId={REF_ID} mode="radial" />);

    expect(await screen.findByText("outline unavailable")).toBeInTheDocument();
  });
});

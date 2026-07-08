import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test-utils/test-renderer";
import { server } from "@/test-utils/msw-server";
import { KnowledgeOutlineView } from "./KnowledgeOutlineView";

// Stub ECharts so radial-view tests don't need to actually initialize a chart
// in jsdom (which has no canvas + no ResizeObserver semantics ECharts expects).
vi.mock("echarts", () => {
  const chart = {
    setOption: vi.fn(),
    on: vi.fn(),
    dispose: vi.fn(),
    isDisposed: vi.fn().mockReturnValue(false),
    resize: vi.fn(),
  };
  return { init: vi.fn(() => chart) };
});

// jsdom lacks ResizeObserver — provide a minimal stub.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;

const REF_ID = "ref-theory-1";
const NODE_ID_CH1 = "node-ch-1";
const NODE_ID_11 = "node-1-1";

const OUTLINE_TREE = {
  ref_id: REF_ID,
  build_run_id: "run-1",
  total_nodes: 3,
  max_depth: 2,
  fallback_used: false,
  root_id: "node-root",
  nodes: [
    {
      id: "node-root",
      parent_id: null,
      level: 0,
      order_index: 0,
      title: "教材",
      numbering: null,
      numbering_path: null,
      anchor_range: null,
      chunk_count: 0,
    },
    {
      id: NODE_ID_CH1,
      parent_id: "node-root",
      level: 1,
      order_index: 0,
      title: "第1章 引论",
      numbering: "1",
      numbering_path: [1],
      anchor_range: null,
      chunk_count: 0,
    },
    {
      id: NODE_ID_11,
      parent_id: NODE_ID_CH1,
      level: 2,
      order_index: 0,
      title: "1.1 概念",
      numbering: "1.1",
      numbering_path: [1, 1],
      anchor_range: { block_ids: ["b3"], page_start: 2, page_end: 2 },
      chunk_count: 2,
    },
  ],
};

function withTreeHandler() {
  server.use(
    http.get(`/api/normalized-refs/${REF_ID}/knowledge-outline`, () =>
      HttpResponse.json({ data: OUTLINE_TREE, meta: { trace_id: null } }),
    ),
  );
}

beforeEach(() => {
  server.resetHandlers();
});

afterEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Gating & load
// ---------------------------------------------------------------------------

describe("KnowledgeOutlineView — gating", () => {
  it("skips fetch when isTheoryKnowledge is false", async () => {
    let called = false;
    server.use(
      http.get(`/api/normalized-refs/${REF_ID}/knowledge-outline`, () => {
        called = true;
        return HttpResponse.json({ data: OUTLINE_TREE, meta: { trace_id: null } });
      }),
    );

    renderWithProviders(<KnowledgeOutlineView refId={REF_ID} isTheoryKnowledge={false} />);
    // Empty-state renders synchronously (no data yet, no loading either).
    await waitFor(() => {
      expect(screen.getByText("暂无知识点大纲")).toBeInTheDocument();
    });
    expect(called).toBe(false);
  });

  it("renders empty-state hint when refId is null", () => {
    renderWithProviders(<KnowledgeOutlineView refId={null} isTheoryKnowledge={true} />);
    expect(screen.getByText("该资产尚无标准化引用，暂无知识点大纲。")).toBeInTheDocument();
  });
});

describe("KnowledgeOutlineView — auto-load", () => {
  it("fetches and renders tree titles for theory_knowledge refs", async () => {
    withTreeHandler();
    renderWithProviders(<KnowledgeOutlineView refId={REF_ID} isTheoryKnowledge={true} />);

    // Switch to Tree view where Antd renders titles as DOM text.
    // Antd Segmented + Tree nodes render inputs / wrappers with
    // pointer-events: none. Disable the CSS check so click bubbles through.
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    await waitFor(() => {
      expect(screen.getByRole("radio", { name: /树/ })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("radio", { name: /树/ }));

    await waitFor(() => {
      expect(screen.getByText(/第1章 引论/)).toBeInTheDocument();
      expect(screen.getByText(/1.1 概念/)).toBeInTheDocument();
    });
  });

  it("renders error alert when fetch fails", async () => {
    server.use(
      http.get(`/api/normalized-refs/${REF_ID}/knowledge-outline`, () =>
        HttpResponse.json(
          { error: { message: "backend down" }, meta: { trace_id: null } },
          { status: 500 },
        ),
      ),
    );

    renderWithProviders(<KnowledgeOutlineView refId={REF_ID} isTheoryKnowledge={true} />);
    await waitFor(() => {
      expect(screen.getByText(/backend down/)).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Node interaction → drawer
// ---------------------------------------------------------------------------

describe("KnowledgeOutlineView — node drawer", () => {
  it("opens Drawer with chunks when a leaf node is clicked in Tree view", async () => {
    withTreeHandler();
    server.use(
      http.get(`/api/knowledge-outline-nodes/${NODE_ID_11}/chunks`, () =>
        HttpResponse.json({
          data: {
            node_id: NODE_ID_11,
            chunks: [
              {
                id: "chk-1",
                normalized_ref_id: REF_ID,
                knowledge_type_code: "textbook_kb",
                chunk_index: 0,
                content_preview: "概念的定义正文…",
                source_block_ids: ["b3"],
                knowledge_outline_node_id: NODE_ID_11,
              },
            ],
            next_cursor: null,
          },
          meta: { trace_id: null },
        }),
      ),
    );

    // Antd Segmented + Tree nodes render inputs / wrappers with
    // pointer-events: none. Disable the CSS check so click bubbles through.
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    renderWithProviders(<KnowledgeOutlineView refId={REF_ID} isTheoryKnowledge={true} />);
    await waitFor(() => expect(screen.getByRole("radio", { name: /树/ })).toBeInTheDocument());
    await user.click(screen.getByRole("radio", { name: /树/ }));

    const leaf = await screen.findByText(/1.1 概念/);
    await user.click(leaf);

    await waitFor(() => expect(screen.getByText(/概念的定义正文/)).toBeInTheDocument());
  });

  it("shows 跳到原文 button when onJumpToBlock is provided and calls it", async () => {
    withTreeHandler();
    server.use(
      http.get(`/api/knowledge-outline-nodes/${NODE_ID_11}/chunks`, () =>
        HttpResponse.json({
          data: {
            node_id: NODE_ID_11,
            chunks: [
              {
                id: "chk-1",
                normalized_ref_id: REF_ID,
                knowledge_type_code: "textbook_kb",
                chunk_index: 0,
                content_preview: "…",
                source_block_ids: ["b3"],
                knowledge_outline_node_id: NODE_ID_11,
              },
            ],
            next_cursor: null,
          },
          meta: { trace_id: null },
        }),
      ),
    );

    const onJump = vi.fn();
    // Antd Segmented + Tree nodes render inputs / wrappers with
    // pointer-events: none. Disable the CSS check so click bubbles through.
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    renderWithProviders(
      <KnowledgeOutlineView refId={REF_ID} isTheoryKnowledge={true} onJumpToBlock={onJump} />,
    );
    await waitFor(() => expect(screen.getByRole("radio", { name: /树/ })).toBeInTheDocument());
    await user.click(screen.getByRole("radio", { name: /树/ }));
    await user.click(await screen.findByText(/1.1 概念/));

    const jumpBtn = await screen.findByRole("button", { name: /跳到原文/ });
    await user.click(jumpBtn);
    expect(onJump).toHaveBeenCalledWith("b3");
  });
});

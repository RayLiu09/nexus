import { beforeEach, describe, expect, it, vi } from "vitest";

const { getApiDataMock } = vi.hoisted(() => ({
  getApiDataMock: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  getApiData: getApiDataMock,
}));

import { loadWorkbenchData } from "./console-data";

describe("loadWorkbenchData", () => {
  beforeEach(() => {
    getApiDataMock.mockReset();
    getApiDataMock.mockImplementation(async (path: string, fallback: unknown) => ({
      data: path === "/internal/v1/workbench/summary" ? { asset_count: 309 } : fallback,
      ok: true,
      error: null,
      traceId: null,
      total: null,
    }));
  });

  it("loads exact summary metrics without downloading complete ledgers", async () => {
    const result = await loadWorkbenchData();
    const requestedPaths = getApiDataMock.mock.calls.map(([path]) => path);

    expect(result.summary.data).toEqual({ asset_count: 309 });
    expect(requestedPaths).toEqual([
      "/internal/v1/workbench/summary",
      "/internal/v1/runtime/state",
      "/internal/v1/data-sources",
      "/internal/v1/ingest/batches",
      "/internal/v1/audit-logs",
    ]);
    expect(requestedPaths).not.toContain("/internal/v1/assets");
    expect(requestedPaths).not.toContain("/internal/v1/raw-objects");
    expect(requestedPaths).not.toContain("/internal/v1/jobs");
    expect(requestedPaths).not.toContain("/internal/v1/normalized-refs");
    expect(requestedPaths).not.toContain("/internal/v1/ai/governance-runs");
    expect(getApiDataMock).toHaveBeenCalledWith("/internal/v1/ingest/batches", [], {
      pageSize: "20",
    });
    expect(getApiDataMock).toHaveBeenCalledWith("/internal/v1/audit-logs", [], { pageSize: "20" });
  });
});

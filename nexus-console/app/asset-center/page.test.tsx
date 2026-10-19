import { PassThrough } from "node:stream";
import { renderToPipeableStream } from "react-dom/server";
import { expect, it, vi } from "vitest";

import { getApiData, type ApiResult, type AssetCenterCounts } from "@/lib/api";
import AssetCenterPage from "./page";

vi.mock("@/lib/api", () => ({ getApiData: vi.fn() }));

it("streams resource links before the count request finishes", async () => {
  let resolveCounts!: (value: ApiResult<AssetCenterCounts>) => void;
  vi.mocked(getApiData).mockReturnValueOnce(
    new Promise<ApiResult<AssetCenterCounts>>((resolve) => {
      resolveCounts = resolve;
    }),
  );

  const output = new PassThrough();
  let html = "";
  const firstChunk = new Promise<string>((resolve) => {
    output.once("data", (chunk: Buffer) => resolve(chunk.toString()));
  });
  const finished = new Promise<void>((resolve, reject) => {
    output.on("data", (chunk: Buffer) => {
      html += chunk.toString();
    });
    output.on("end", resolve);
    output.on("error", reject);
  });
  const { pipe } = renderToPipeableStream(<AssetCenterPage />, {
    onShellReady() {
      pipe(output);
    },
  });

  const shell = await firstChunk;
  expect(shell).toContain("资产中心");
  expect(shell).toContain("/asset-center/policy/industry-policies");
  expect(shell).toContain("数量加载中");

  resolveCounts({
    ok: true,
    data: { counts: { "policy/industry-policies": 12 } },
    error: null,
    traceId: null,
    total: null,
  });
  await finished;
  expect(html).toContain("产教政策，12 条");
});

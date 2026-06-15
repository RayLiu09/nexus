import { beforeEach, describe, expect, it, vi } from "vitest";

const { ingestProxyPostMock } = vi.hoisted(() => ({
  ingestProxyPostMock: vi.fn(),
}));

vi.mock("@/lib/ingestProxy", () => ({
  ingestProxyPost: ingestProxyPostMock,
}));

import { POST } from "./route";

describe("POST /api/ingest/files/multi", () => {
  beforeEach(() => {
    ingestProxyPostMock.mockReset();
    ingestProxyPostMock.mockResolvedValue({
      ok: true,
      status: 202,
      data: { batch: { id: "batch-1", status: "submitted" }, items: [] },
      traceId: "trace-1",
    });
  });

  it("forwards batch_idempotency_key as Idempotency-Key", async () => {
    const payload = {
      data_source_id: "ds-1",
      batch_idempotency_key: "batch-key-1",
      files: [
        {
          file_idempotency_key: "file-key-1",
          filename: "sample.pdf",
          content_base64: "JVBERi0xLjQKJSVFT0YK",
          content_type: "application/pdf",
        },
      ],
    };

    const request = new Request("http://localhost/api/ingest/files/multi", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });

    const response = await POST(request);

    expect(response.status).toBe(202);
    expect(ingestProxyPostMock).toHaveBeenCalledWith(
      "/internal/v1/ingest/files/multi",
      payload,
      { "Idempotency-Key": "batch-key-1" },
    );
  });

  it("rejects an empty batch idempotency key before proxying", async () => {
    const request = new Request("http://localhost/api/ingest/files/multi", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ data_source_id: "ds-1", batch_idempotency_key: "   ", files: [] }),
    });

    const response = await POST(request);
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body.message).toContain("batch_idempotency_key");
    expect(ingestProxyPostMock).not.toHaveBeenCalled();
  });
});

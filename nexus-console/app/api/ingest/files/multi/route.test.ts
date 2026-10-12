import { beforeEach, describe, expect, it, vi } from "vitest";

const { ingestProxyPostMock, getServerSessionMock } = vi.hoisted(() => ({
  ingestProxyPostMock: vi.fn(),
  getServerSessionMock: vi.fn(),
}));

vi.mock("@/lib/ingestProxy", () => ({
  ingestProxyPost: ingestProxyPostMock,
}));
vi.mock("@/lib/auth/serverSession", () => ({
  getServerSession: getServerSessionMock,
}));

import { POST } from "./route";

describe("POST /api/ingest/files/multi", () => {
  beforeEach(() => {
    ingestProxyPostMock.mockReset();
    getServerSessionMock.mockReset();
    getServerSessionMock.mockResolvedValue({ role: "platform_data_admin" });
    ingestProxyPostMock.mockResolvedValue({
      ok: true,
      status: 202,
      data: { batch: { id: "batch-1", status: "submitted" }, items: [] },
      traceId: "trace-1",
    });
  });

  it("rejects unauthenticated requests before proxying", async () => {
    getServerSessionMock.mockResolvedValue(null);
    const response = await POST(new Request("http://localhost/api/ingest/files/multi", {
      method: "POST",
      body: JSON.stringify({ batch_idempotency_key: "batch-1", files: [] }),
    }));

    expect(response.status).toBe(401);
    expect(ingestProxyPostMock).not.toHaveBeenCalled();
  });

  it("forbids business experts before resolving a source or proxying", async () => {
    getServerSessionMock.mockResolvedValue({ role: "business_expert" });
    const response = await POST(new Request("http://localhost/api/ingest/files/multi", {
      method: "POST",
      body: JSON.stringify({ batch_idempotency_key: "batch-1", files: [] }),
    }));

    expect(response.status).toBe(403);
    expect(ingestProxyPostMock).not.toHaveBeenCalled();
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

  it("resolves the default upload source when none is supplied", async () => {
    ingestProxyPostMock
      .mockResolvedValueOnce({ ok: true, status: 200, data: { id: "default-source" } })
      .mockResolvedValueOnce({ ok: true, status: 202, data: { batch: { id: "batch-1" }, items: [] } });
    const request = new Request("http://localhost/api/ingest/files/multi", {
      method: "POST",
      body: JSON.stringify({ batch_idempotency_key: "first-upload", files: [] }),
    });

    const response = await POST(request);
    expect(response.status).toBe(202);
    expect(ingestProxyPostMock).toHaveBeenNthCalledWith(
      1, "/internal/v1/data-sources/default-upload", {},
    );
    expect(ingestProxyPostMock).toHaveBeenNthCalledWith(
      2, "/internal/v1/ingest/files/multi",
      { batch_idempotency_key: "first-upload", files: [], data_source_id: "default-source" },
      { "Idempotency-Key": "first-upload" },
    );
  });
});

import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CitationContentPreview } from "./CitationContentPreview";
import type { QueryCitation } from "../_lib/queryTypes";

const source: QueryCitation = {
  citation_id: "1", source_type: "document", title: "低空政策", excerpt: "目录元数据",
  tool: "find_documents", normalized_ref_id: "ref-first",
};
afterEach(() => vi.unstubAllGlobals());

describe("CitationContentPreview", () => {
  it("loads actual asset Markdown on demand and renders content rather than metadata", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, data: {
      body_markdown: "# 政策正文\n\n支持**低空产业链**发展。\n\n![插图](https://external.test/image)",
    } })));
    vi.stubGlobal("fetch", fetcher);
    render(<CitationContentPreview source={source} />);
    expect(screen.getByRole("status", { name: "正在加载资产正文" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "政策正文" })).toBeInTheDocument();
    expect(screen.getByText("低空产业链")).toBeInTheDocument();
    expect(screen.queryByText("目录元数据")).not.toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(fetcher.mock.calls[0][0]).toBe("/api/normalized-refs/ref-first/content");
  });

  it.each([403, 503])("shows a safe error for HTTP %s without exposing backend details", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: false, message: "private-key" }), { status })));
    render(<CitationContentPreview source={source} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(status === 403 ? "暂无权限" : "暂时无法加载");
    expect(document.body.textContent).not.toContain("private-key");
  });

  it("aborts an earlier read and ignores its late response when another asset opens", async () => {
    let resolveFirst!: (value: Response) => void;
    const first = new Promise<Response>((resolve) => { resolveFirst = resolve; });
    const fetcher = vi.fn().mockReturnValueOnce(first).mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, data: { body_markdown: "第二份资产正文" } })));
    vi.stubGlobal("fetch", fetcher);
    const { rerender } = render(<CitationContentPreview source={source} />);
    rerender(<CitationContentPreview source={{ ...source, normalized_ref_id: "ref-second" }} />);
    expect(await screen.findByText("第二份资产正文")).toBeInTheDocument();
    expect((fetcher.mock.calls[0][1].signal as AbortSignal).aborted).toBe(true);
    await act(async () => resolveFirst(new Response(JSON.stringify({ ok: true, data: { body_markdown: "过期的第一份正文" } }))));
    expect(screen.queryByText("过期的第一份正文")).not.toBeInTheDocument();
    expect(screen.getByText("第二份资产正文")).toBeInTheDocument();
  });

  it("handles an empty body without displaying raw record JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, data: { body_markdown: null, record_body: { private_id: "hidden" } } }))));
    render(<CitationContentPreview source={source} />);
    expect(await screen.findByText(/暂无可预览的正文/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("private_id");
  });

  it("previews acquired web content without calling a platform asset API", () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    render(<CitationContentPreview source={{ ...source, source_type: "external_web", excerpt: "网页实际内容" }} />);
    expect(screen.getByText("网页实际内容")).toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });
});

import { App } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SourcePreviewSection } from "./SourcePreviewSection";

vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

it("shows the extracted chart image in parsed preview and keeps text on image failure", async () => {
  const body = "# 白皮书\n\n**图1-3**\n\n数据来源：企查查\n\n后续段落";
  const captionStart = body.indexOf("**图1-3**");
  vi.stubGlobal("fetch", vi.fn(async () => ({
    json: async () => ({
      ok: true,
      data: {
        normalized_type: "document",
        body_markdown: body,
        blocks: [
          { block_id: "heading", md_char_range: [0, 6] },
          {
            block_id: "chart-1",
            block_type: "chart",
            caption: "图1-3",
            md_char_range: [captionStart, captionStart + "**图1-3**".length],
            image_uris: { "chart.jpg": "s3://bucket/parsed/version/artifact/images/chart.jpg" },
          },
        ],
      },
    }),
  })));

  render(<App><SourcePreviewSection refId="ref-1" /></App>);
  expect(await screen.findByText("解析预览")).toBeInTheDocument();
  const image = await screen.findByAltText("图1-3");
  expect(image).toHaveAttribute("src", "/api/normalized-refs/ref-1/blocks/chart-1/images/0");
  expect(screen.getByText("数据来源：企查查")).toBeInTheDocument();

  fireEvent.error(image);
  expect(await screen.findByText("解析图片加载失败，文字内容仍可查看")).toBeInTheDocument();
  expect(screen.getByText("后续段落")).toBeInTheDocument();
});

it("keeps an image visible when its block has no markdown range", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    json: async () => ({
      ok: true,
      data: {
        normalized_type: "document",
        body_markdown: "# 标题\n\n正文",
        blocks: [
          { block_id: "heading", md_char_range: [0, 4] },
          { block_id: "image-only", caption: "现场照片", md_char_range: null,
            image_uris: { "photo.png": "s3://bucket/parsed/version/artifact/images/photo.png" } },
        ],
      },
    }),
  })));

  render(<App><SourcePreviewSection refId="ref-2" /></App>);
  expect(await screen.findByAltText("现场照片")).toHaveAttribute(
    "src", "/api/normalized-refs/ref-2/blocks/image-only/images/0",
  );
});

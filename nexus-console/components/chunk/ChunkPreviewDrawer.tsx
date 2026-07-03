"use client";

import { useEffect, useMemo, useState } from "react";
import { Alert, Descriptions, Drawer, Empty, Image, Skeleton, Space, Tag, Typography } from "antd";
import type {
  ChunkPreviewResponse,
  KnowledgeChunkHit,
  MarkdownHighlightRange,
  PageAnchor,
} from "@/lib/chunkTypes";
import { LocatorChip } from "./LocatorChip";

interface ProxyEnvelope<T> {
  ok: true;
  status: number;
  data: T;
  traceId: string | null;
}

interface ProxyErrorEnvelope {
  ok: false;
  status: number;
  message: string;
}

export interface ChunkPreviewDrawerProps {
  chunk: KnowledgeChunkHit | null;
  open: boolean;
  onClose: () => void;
}

export function ChunkPreviewDrawer({ chunk, open, onClose }: ChunkPreviewDrawerProps) {
  const chunkId = previewChunkId(chunk);
  const [preview, setPreview] = useState<ChunkPreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setPreview(null);
      setError(null);
      setLoading(false);
      return;
    }
    if (!chunkId) {
      setPreview(null);
      setError("该 chunk 未携带 NEXUS chunk id，无法加载预览。");
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    setPreview(null);

    (async () => {
      try {
        const res = await fetch(
          `/api/knowledge-chunks/${encodeURIComponent(chunkId)}/preview`,
          { cache: "no-store" },
        );
        const body = (await res.json()) as
          | ProxyEnvelope<ChunkPreviewResponse>
          | ProxyErrorEnvelope;
        if (!body.ok) {
          throw new Error(body.message || `HTTP ${res.status}`);
        }
        if (!cancelled) setPreview(body.data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [chunkId, open]);

  const effectiveChunk = preview?.chunk ?? chunk;

  return (
    <Drawer
      title="知识块预览"
      open={open}
      onClose={onClose}
      size={1180}
      destroyOnHidden
    >
      {!chunk ? (
        <Empty description="未选中知识块" />
      ) : error ? (
        <Alert type="error" showIcon title={error} />
      ) : loading || !preview ? (
        <Skeleton active paragraph={{ rows: 10 }} />
      ) : (
        <div
          id={`chunk-preview-${chunkId ?? ""}`}
          className="chunk-preview-layout"
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) minmax(320px, 460px)",
            gap: "var(--space-4)",
            alignItems: "start",
          }}
        >
          <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
            <ChunkOverview preview={preview} chunk={effectiveChunk} />
            <MarkdownAnchorPanel preview={preview} />
          </div>
          <PageAnchorPanel preview={preview} />
          <style jsx>{`
            @media (max-width: 860px) {
              .chunk-preview-layout {
                grid-template-columns: minmax(0, 1fr) !important;
              }
            }
          `}</style>
        </div>
      )}
    </Drawer>
  );
}

function ChunkOverview({
  preview,
  chunk,
}: {
  preview: ChunkPreviewResponse;
  chunk: KnowledgeChunkHit | null;
}) {
  if (!chunk) return null;
  const headingPath = preview.highlight.heading_path ?? [];
  return (
    <section>
      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="知识类型">
          <Space size={6} wrap>
            {chunk.knowledge_type_code ? <Tag color="cyan">{chunk.knowledge_type_code}</Tag> : <Tag>unknown</Tag>}
            {chunk.chunk_type ? <Tag>{chunk.chunk_type}</Tag> : null}
            {preview.highlight.anchor_role ? <Tag color="blue">{preview.highlight.anchor_role}</Tag> : null}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="页面定位">
          <LocatorChip locator={chunk.locator} fallbackPage={chunk.source?.page} />
        </Descriptions.Item>
        {headingPath.length > 0 && (
          <Descriptions.Item label="章节路径">
            <Space size={4} wrap>
              {headingPath.map((h, index) => (
                <Tag key={`${h.level}-${h.title}-${index}`}>H{h.level} {h.title}</Tag>
              ))}
            </Space>
          </Descriptions.Item>
        )}
        {chunk.source_block_ids && chunk.source_block_ids.length > 0 && (
          <Descriptions.Item label="来源 Blocks">
            <Space size={4} wrap>
              {chunk.source_block_ids.map((blockId, index) => (
                <a key={`${blockId}-${index}`} href={`#block-${blockId}`}>
                  <Tag className="cursor-pointer font-mono text-xs">{blockId}</Tag>
                </a>
              ))}
            </Space>
          </Descriptions.Item>
        )}
        <Descriptions.Item label="Chunk ID">
          <Typography.Text className="font-mono text-xs">{previewChunkId(chunk) ?? "-"}</Typography.Text>
        </Descriptions.Item>
      </Descriptions>

      <Typography.Title level={5} className="!mb-2 !mt-4">
        知识块内容
      </Typography.Title>
      <div
        style={{
          border: "1px solid var(--line)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-3)",
          background: "var(--gray-50)",
          maxHeight: 220,
          overflow: "auto",
          whiteSpace: "pre-wrap",
          lineHeight: 1.7,
          fontSize: 13,
        }}
      >
        {chunk.content || "-"}
      </div>
    </section>
  );
}

function MarkdownAnchorPanel({ preview }: { preview: ChunkPreviewResponse }) {
  const body = preview.source.body_markdown;
  const ranges = preview.highlight.markdown_ranges ?? [];
  const excerpts = useMemo(
    () => buildMarkdownExcerpts(body, ranges),
    [body, ranges],
  );

  if (preview.normalized_ref.normalized_type === "record") {
    return (
      <section>
        <Typography.Title level={5} className="!mb-2">
          原文记录
        </Typography.Title>
        {preview.source.record_body ? (
          <pre className="max-h-[46vh] overflow-auto rounded border border-solid border-gray-200 p-3 text-xs">
            {JSON.stringify(preview.source.record_body, null, 2)}
          </pre>
        ) : (
          <Empty description="记录体为空" />
        )}
      </section>
    );
  }

  return (
    <section>
      <Typography.Title level={5} className="!mb-2">
        原文 Markdown 定位
      </Typography.Title>
      {!body ? (
        <Alert type="info" showIcon title="该 normalized ref 暂无 body_markdown，无法显示 markdown 定位。" />
      ) : excerpts.length === 0 ? (
        <Alert type="info" showIcon title="该知识块未携带 md_char_range/md_spans，无法在 markdown 中高亮定位。" />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
          {excerpts.map((excerpt, index) => (
            <div key={`${excerpt.range.start}-${excerpt.range.end}-${index}`}>
              <div className="mb-1 flex items-center gap-2">
                <Tag color="processing">span {index + 1}</Tag>
                {excerpt.range.block_id ? (
                  <a href={`#block-${excerpt.range.block_id}`}>
                    <Tag className="cursor-pointer font-mono text-xs">{excerpt.range.block_id}</Tag>
                  </a>
                ) : null}
                <Typography.Text type="secondary" className="text-xs">
                  {excerpt.range.start}-{excerpt.range.end}
                </Typography.Text>
              </div>
              <pre
                style={{
                  margin: 0,
                  maxHeight: 260,
                  overflow: "auto",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius-md)",
                  padding: "var(--space-3)",
                  background: "#fff",
                  fontSize: 12,
                  lineHeight: 1.7,
                }}
              >
                <span>{excerpt.before}</span>
                <mark
                  style={{
                    background: "var(--warning-50)",
                    color: "inherit",
                    padding: "1px 2px",
                    borderRadius: 3,
                  }}
                >
                  {excerpt.highlight}
                </mark>
                <span>{excerpt.after}</span>
              </pre>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function PageAnchorPanel({ preview }: { preview: ChunkPreviewResponse }) {
  const anchors = useMemo(
    () => normalizePageAnchors(preview.highlight.page_anchors ?? []),
    [preview.highlight.page_anchors],
  );
  const [activeIndex, setActiveIndex] = useState(0);
  const [imageError, setImageError] = useState(false);
  const anchor = anchors[activeIndex] ?? null;

  useEffect(() => {
    setActiveIndex(0);
  }, [preview.chunk.id, anchors.length]);

  useEffect(() => {
    setImageError(false);
  }, [anchor?.page, anchor?.bbox?.join(",")]);

  if (!anchor) {
    return (
      <section>
        <Typography.Title level={5} className="!mb-2">
          PDF 页面定位
        </Typography.Title>
        <Alert type="info" showIcon title="该知识块未携带 page/bbox 定位，无法生成页面截图。" />
      </section>
    );
  }

  const refId = preview.normalized_ref.ref_id;
  const src = pageImageSrc(refId, anchor);

  return (
    <section style={{ position: "sticky", top: 0 }}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <Typography.Title level={5} className="!mb-0">
          PDF 页面定位
        </Typography.Title>
        <Space size={4} wrap>
          <Tag>p{anchor.page}</Tag>
          {anchors.length > 1 ? <Tag color="processing">{activeIndex + 1}/{anchors.length}</Tag> : null}
          {anchor.block_id ? <Tag className="font-mono text-xs">{anchor.block_id}</Tag> : null}
        </Space>
      </div>

      {anchors.length > 1 ? (
        <div className="mb-2 flex flex-wrap gap-1">
          {anchors.map((item, index) => (
            <button
              key={`${item.page}-${item.block_id ?? "block"}-${index}`}
              type="button"
              onClick={() => setActiveIndex(index)}
              className="rounded border border-[var(--line)] px-2 py-1 text-xs hover:border-[var(--line-strong)]"
              style={{
                background: index === activeIndex ? "var(--brand-50)" : "#fff",
                color: index === activeIndex ? "var(--brand-700)" : "var(--text-muted)",
              }}
            >
              p{item.page}{item.block_id ? ` · ${item.block_id}` : ""}
            </button>
          ))}
        </div>
      ) : null}

      {imageError ? (
        <Alert
          type="warning"
          showIcon
          title="页面图片加载失败"
          description="常见原因：原始文件不是 PDF、对象存储缺失，或该 chunk 只有 markdown 定位。"
        />
      ) : (
        <div
          style={{
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-md)",
            background: "var(--gray-50)",
            padding: "var(--space-2)",
            maxHeight: "72vh",
            overflow: "auto",
          }}
        >
          <Image
            src={src}
            alt={`page ${anchor.page} source preview`}
            width="100%"
            preview={false}
            onError={() => setImageError(true)}
            style={{ display: "block", background: "#fff" }}
          />
        </div>
      )}
    </section>
  );
}

function previewChunkId(chunk: KnowledgeChunkHit | null): string | null {
  if (!chunk) return null;
  return chunk.id ?? chunk.nexus_chunk_id ?? null;
}

interface MarkdownExcerpt {
  range: MarkdownHighlightRange;
  before: string;
  highlight: string;
  after: string;
}

function buildMarkdownExcerpts(
  body: string | null,
  ranges: MarkdownHighlightRange[],
): MarkdownExcerpt[] {
  if (!body || ranges.length === 0) return [];
  const out: MarkdownExcerpt[] = [];
  for (const range of ranges) {
    const start = clamp(range.start, 0, body.length);
    const end = clamp(range.end, start, body.length);
    if (end <= start) continue;
    const contextStart = snapExcerptStart(body, Math.max(0, start - 240));
    const contextEnd = snapExcerptEnd(body, Math.min(body.length, end + 240));
    out.push({
      range: { ...range, start, end },
      before: body.slice(contextStart, start),
      highlight: body.slice(start, end),
      after: body.slice(end, contextEnd),
    });
  }
  return out;
}

function normalizePageAnchors(anchors: PageAnchor[]): PageAnchor[] {
  return anchors.filter((anchor) => Number.isFinite(anchor.page));
}

function pageImageSrc(refId: string, anchor: PageAnchor): string {
  const params = new URLSearchParams({ page: String(anchor.page) });
  if (anchor.bbox) {
    params.set("bbox", anchor.bbox.join(","));
  }
  return `/api/normalized-refs/${encodeURIComponent(refId)}/page-image?${params.toString()}`;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function snapExcerptStart(body: string, pos: number): number {
  let p = pos;
  while (p > 0 && body[p - 1] !== "\n") p--;
  return p;
}

function snapExcerptEnd(body: string, pos: number): number {
  let p = pos;
  while (p < body.length && body[p] !== "\n") p++;
  return p;
}

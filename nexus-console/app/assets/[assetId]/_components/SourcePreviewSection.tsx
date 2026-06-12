"use client";

/**
 * SourcePreviewSection — Asset Detail "原文预览" tab.
 *
 * Renders ``body_markdown`` from a normalized_ref split into block-anchored
 * segments using ``blocks[].md_char_range``. The markdown bytes themselves
 * are NEVER mutated; anchors live only in the rendered DOM (see ARCHITECT
 * "Chunk Locator Contract" / memory feedback_md_char_range_out_of_band).
 *
 * Record-type refs fall back to a JSON code block.
 *
 * Deep-link behaviour: a `#block-XXX` URL hash scrolls to and briefly
 * highlights the matching block on mount and on hashchange. Tab switching
 * still happens manually — wider URL state is P2.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Alert, Card, Empty, Skeleton } from "antd";
import type { NormalizedBlock, NormalizedRefContent } from "@/lib/chunkTypes";

// react-markdown ships a chunky parser; gate it behind a client-only dynamic
// import so we don't bloat the asset-detail server bundle. SSR is off because
// the viewer is purely a client tab.
const Markdown = dynamic(() => import("react-markdown"), {
  ssr: false,
  loading: () => <Skeleton active paragraph={{ rows: 3 }} />,
});

// remark-gfm enables GFM tables / strikethrough / task lists — closer to
// what MinerU's table-rendering pipeline emits.
const remarkGfmPromise = import("remark-gfm").then((m) => m.default);

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

export interface SourcePreviewSectionProps {
  refId: string | null;
}

export function SourcePreviewSection({ refId }: SourcePreviewSectionProps) {
  const [content, setContent] = useState<NormalizedRefContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!refId) {
      setContent(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const res = await fetch(`/api/normalized-refs/${encodeURIComponent(refId)}/content`, {
          cache: "no-store",
        });
        const body = (await res.json()) as ProxyEnvelope<NormalizedRefContent> | ProxyErrorEnvelope;
        if (!body.ok) throw new Error(body.message || `HTTP ${res.status}`);
        if (!cancelled) setContent(body.data);
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
  }, [refId]);

  if (!refId) {
    return (
      <Card className="!mt-4">
        <Empty description="该资产尚无标准化引用，无法预览原文" />
      </Card>
    );
  }
  if (error) {
    return (
      <Card className="!mt-4">
        <Alert type="error" showIcon title={error} />
      </Card>
    );
  }
  if (loading || !content) {
    return (
      <Card className="!mt-4">
        <Skeleton active paragraph={{ rows: 6 }} />
      </Card>
    );
  }
  if (content.normalized_type === "record") {
    return (
      <Card title="记录类资产" className="!mt-4">
        {content.record_body ? (
          <pre className="bg-bg m-0 max-h-[60vh] overflow-auto p-3 text-xs">
            {JSON.stringify(content.record_body, null, 2)}
          </pre>
        ) : (
          <Empty description="记录体为空" />
        )}
      </Card>
    );
  }
  if (!content.body_markdown) {
    return (
      <Card title="原文预览" className="!mt-4">
        <Empty description="该 ref 暂无 body_markdown" />
      </Card>
    );
  }
  return (
    <Card title="原文预览（按 block 锚定，可从 #block-xxx 跳转）" className="!mt-4">
      <MarkdownViewer body={content.body_markdown} blocks={content.blocks ?? []} />
    </Card>
  );
}

interface MarkdownViewerProps {
  body: string;
  blocks: NormalizedBlock[];
}

/**
 * Split body by md_char_range and render each block in its own anchor div.
 * body itself is sliced — substring extraction does not mutate the source.
 */
function MarkdownViewer({ body, blocks }: MarkdownViewerProps) {
  const segments = useMemo(() => buildSegments(body, blocks), [body, blocks]);
  const [activeBlock, setActiveBlock] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const handleHash = useCallback(() => {
    const hash = window.location.hash.replace(/^#/, "");
    if (!hash.startsWith("block-")) return;
    const el = rootRef.current?.querySelector<HTMLElement>(`#${cssEscape(hash)}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    setActiveBlock(hash.slice("block-".length));
    window.setTimeout(() => setActiveBlock(null), 2000);
  }, []);

  useEffect(() => {
    handleHash();
    window.addEventListener("hashchange", handleHash);
    return () => window.removeEventListener("hashchange", handleHash);
  }, [handleHash]);

  const [remarkPlugins, setRemarkPlugins] = useState<unknown[]>([]);
  useEffect(() => {
    let cancelled = false;
    remarkGfmPromise.then((p) => {
      if (!cancelled) setRemarkPlugins([p]);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (segments.length === 0) {
    return (
      <div className="prose max-w-none">
        <Markdown>{body}</Markdown>
      </div>
    );
  }
  return (
    <div ref={rootRef} className="prose max-w-none">
      {segments.map(({ blockId, text }) => (
        <div
          key={blockId}
          id={`block-${blockId}`}
          data-block-id={blockId}
          className={
            activeBlock === blockId ? "bg-warning/10 rounded px-2 py-1 transition-colors" : ""
          }
        >
          {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
          <Markdown remarkPlugins={remarkPlugins as any}>{text}</Markdown>
        </div>
      ))}
    </div>
  );
}

interface Segment {
  blockId: string;
  text: string;
}

function buildSegments(body: string, blocks: NormalizedBlock[]): Segment[] {
  if (!blocks || blocks.length === 0) return [];
  const out: Segment[] = [];
  // Sort by range start to render in document order regardless of input ordering
  const ranged = blocks
    .filter(
      (b): b is NormalizedBlock & { md_char_range: [number, number] } =>
        Array.isArray(b.md_char_range) && b.md_char_range.length === 2,
    )
    .sort((a, b) => a.md_char_range[0] - b.md_char_range[0]);
  for (const block of ranged) {
    const [start, end] = block.md_char_range;
    if (start < 0 || end > body.length || end <= start) continue;
    out.push({ blockId: block.block_id, text: body.slice(start, end) });
  }
  return out;
}

/**
 * CSS.escape polyfill — only used for the rare case where a block_id
 * contains characters that need escaping in a CSS selector.
 */
function cssEscape(value: string): string {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return CSS.escape(value);
  }
  return value.replace(/([^\w-])/g, "\\$1");
}

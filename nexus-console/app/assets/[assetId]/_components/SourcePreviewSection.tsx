"use client";

/**
 * SourcePreviewSection — Asset Detail "原文预览" tab.
 *
 * Renders ``body_markdown`` from a normalized_ref through react-markdown
 * with remark-gfm (GFM tables / strikethrough / task-lists).  The body is
 * split into anchored segments at line-start boundaries nearest to each
 * block's ``md_char_range[0]`` so that multi-line GFM structures (tables,
 * code fences) are never cut in the middle.
 *
 * Record-type refs fall back to a JSON code block.
 *
 * Deep-link: a `#block-XXX` URL hash scrolls to and briefly highlights the
 * matching block on mount and on hashchange.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Alert, Card, Empty, Skeleton } from "antd";
import remarkGfm from "remark-gfm";
import type { NormalizedBlock, NormalizedRefContent } from "@/lib/chunkTypes";

// react-markdown is chunked via next/dynamic — client-only, loaded on demand.
const Markdown = dynamic(() => import("react-markdown"), {
  ssr: false,
  loading: () => <Skeleton active paragraph={{ rows: 3 }} />,
});

// ---- data-fetch response shapes ------------------------------------------

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

// ---- public component ----------------------------------------------------

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
        const res = await fetch(
          `/api/normalized-refs/${encodeURIComponent(refId)}/content`,
          { cache: "no-store" },
        );
        const body = (await res.json()) as
          | ProxyEnvelope<NormalizedRefContent>
          | ProxyErrorEnvelope;
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
          <pre className="max-h-[60vh] overflow-auto p-3 text-xs">
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
    <Card title="原文预览" className="!mt-4">
      <MarkdownViewer
        body={content.body_markdown}
        blocks={content.blocks ?? []}
      />
    </Card>
  );
}

// ---- markdown viewer -----------------------------------------------------

interface MarkdownViewerProps {
  body: string;
  blocks: NormalizedBlock[];
}

function MarkdownViewer({ body, blocks }: MarkdownViewerProps) {
  // Build segments aligned to line starts so tables stay intact.
  const segments = useMemo(
    () => buildSegments(body, blocks),
    [body, blocks],
  );

  const [activeBlock, setActiveBlock] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const handleHash = useCallback(() => {
    const hash = window.location.hash.replace(/^#/, "");
    if (!hash.startsWith("block-")) return;
    const el = rootRef.current?.querySelector<HTMLElement>(
      `[id="${cssEscape(hash)}"]`,
    );
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

  // No blocks → render entire body as one Markdown (tables guaranteed intact).
  if (segments.length === 0) {
    return (
      <div className="md-preview max-h-[70vh] overflow-y-auto">
        <Markdown remarkPlugins={[remarkGfm]}>{body}</Markdown>
      </div>
    );
  }

  return (
    <div ref={rootRef} className="md-preview max-h-[70vh] overflow-y-auto">
      {segments.map(({ blockId, text }, index) => (
        <div
          key={`${blockId}-${index}`}
          id={`block-${blockId}`}
          data-block-id={blockId}
          className={
            activeBlock === blockId
              ? "bg-warning/10 rounded px-2 py-1 transition-colors"
              : ""
          }
        >
          <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
        </div>
      ))}
    </div>
  );
}

// ---- segment builder -----------------------------------------------------

interface Segment {
  blockId: string;
  text: string;
}

/**
 * Split `body` into segments anchored at block start positions.
 *
 * Each split is snapped to the nearest line-start boundary so that GFM
 * tables, fenced code blocks, and other multiline structures are never
 * cut in the middle — only at paragraph / heading / section breaks.
 */
function buildSegments(
  body: string,
  blocks: NormalizedBlock[],
): Segment[] {
  if (!blocks || blocks.length === 0) return [];

  // Collect unique split positions → line starts.
  const positions = new Set<number>();
  for (const b of blocks) {
    const r = b.md_char_range;
    if (!Array.isArray(r) || r.length !== 2) continue;
    const start = r[0];
    if (start <= 0 || start >= body.length) continue;
    positions.add(snapLineStart(body, start));
  }
  // Remove position 0 (beginning of body — no split needed).
  positions.delete(0);

  if (positions.size === 0) return [];

  const sorted = [...positions].sort((a, b) => a - b);

  // Slice body at each position.
  const segs: Segment[] = [];
  let cursor = 0;
  for (const pos of sorted) {
    if (pos <= cursor) continue; // deduplicate after snapping
    segs.push({
      blockId: findBlockIdAt(blocks, cursor),
      text: body.slice(cursor, pos),
    });
    cursor = pos;
  }
  // Tail segment.
  if (cursor < body.length) {
    segs.push({
      blockId: findBlockIdAt(blocks, cursor),
      text: body.slice(cursor),
    });
  }
  return segs;
}

/** Walk backwards from `pos` to find the nearest preceding newline. */
function snapLineStart(body: string, pos: number): number {
  if (pos <= 0) return 0;
  let p = pos - 1;
  while (p > 0 && body[p] !== "\n") p--;
  return body[p] === "\n" ? p + 1 : 0;
}

function findBlockIdAt(blocks: NormalizedBlock[], pos: number): string {
  for (const b of blocks) {
    const r = b.md_char_range;
    if (!Array.isArray(r) || r.length !== 2) continue;
    if (r[0] <= pos && pos <= r[1]) return b.block_id;
  }
  return "unknown";
}

// ---- css-escape polyfill -------------------------------------------------

function cssEscape(value: string): string {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return CSS.escape(value);
  }
  return value.replace(/([^\w-])/g, "\\$1");
}

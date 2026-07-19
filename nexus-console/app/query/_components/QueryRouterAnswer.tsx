"use client";

/**
 * B8 (§4.3 §7.1 §7.3) — Query Router v2 markdown renderer.
 *
 * Wraps `react-markdown` (+ remark-gfm for footnotes / tables) with
 * three v2-specific overrides:
 *
 * 1. `code` — when the fence language is `chart:echarts`, render an
 *    ECharts graph via `EchartsFence` instead of a plain <pre>. Other
 *    fenced blocks (inline code + arbitrary languages) fall through
 *    to Antd's typography defaults.
 * 2. `blockquote` — blocks led by `> ⚠️` are "generated content"
 *    (§4.3) and get a distinct warning-styled treatment so the reader
 *    knows they're model-inferred, not platform-anchored.
 * 3. Footnote anchor navigation — remark-gfm renders `[^refN]` as
 *    superscript links pointing to `#user-content-fn-refN`. We augment
 *    the anchor click with `scrollIntoView` so it works inside
 *    scrollable containers where the browser default falls flat.
 */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useCallback } from "react";
import type { ReactNode } from "react";

import { EchartsFence } from "./EchartsFence";

interface QueryRouterAnswerProps {
  markdown: string;
}

const CHART_LANG = "chart:echarts";
const GENERATED_MARKER = "⚠️";

export function QueryRouterAnswer({ markdown }: QueryRouterAnswerProps) {
  const handleAnchorClick = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.tagName !== "A") return;
    const anchor = target as HTMLAnchorElement;
    const href = anchor.getAttribute("href") || "";
    if (!href.startsWith("#")) return;
    const id = href.slice(1);
    const el = document.getElementById(id);
    if (!el) return;
    event.preventDefault();
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  return (
    <div
      className="query-router-answer prose prose-slate max-w-none text-sm"
      onClick={handleAnchorClick}
      data-testid="query-router-answer"
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code: CodeRenderer,
          blockquote: BlockquoteRenderer,
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}

// ---------------------------------------------------------------------------
// code — dispatch to EchartsFence for chart:echarts fenced blocks
// ---------------------------------------------------------------------------

interface CodeProps {
  className?: string;
  children?: ReactNode;
  inline?: boolean;
}

function CodeRenderer({ className, children, inline, ...rest }: CodeProps) {
  if (inline) {
    return (
      <code className={className} {...rest}>
        {children}
      </code>
    );
  }
  const lang = extractLanguage(className);
  if (lang === CHART_LANG) {
    return <EchartsFence raw={extractText(children)} />;
  }
  return (
    <pre className="border-line my-3 overflow-auto rounded-md border bg-gray-50 p-3 text-xs">
      <code className={className}>{children}</code>
    </pre>
  );
}

// ---------------------------------------------------------------------------
// blockquote — distinct styling for `> ⚠️` generated content
// ---------------------------------------------------------------------------

interface BlockquoteProps {
  children?: ReactNode;
}

function BlockquoteRenderer({ children }: BlockquoteProps) {
  const isGenerated = quoteMentionsGeneratedMarker(children);
  if (isGenerated) {
    return (
      <blockquote
        className="border-warning/30 bg-warning/5 text-warning-800 my-3 rounded-md border py-2 pr-3 pl-4"
        data-testid="query-generated-block"
        aria-label="模型推断内容"
      >
        {children}
      </blockquote>
    );
  }
  return (
    <blockquote className="border-line my-3 border-l-4 pl-4 text-gray-600">{children}</blockquote>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractLanguage(className: string | undefined): string | null {
  if (!className) return null;
  // react-markdown renders fence lang as `language-<lang>`, but colons
  // in the language tag (chart:echarts) survive the pass-through so we
  // just strip the leading `language-` prefix.
  const match = /language-(\S+)/.exec(className);
  return match ? match[1] : null;
}

function extractText(node: ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (node && typeof node === "object" && "props" in node) {
    const props = (node as { props?: { children?: ReactNode } }).props;
    return props ? extractText(props.children) : "";
  }
  return "";
}

function quoteMentionsGeneratedMarker(node: ReactNode): boolean {
  const text = extractText(node);
  return text.includes(GENERATED_MARKER);
}

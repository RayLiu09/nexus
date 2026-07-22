"use client";

/**
 * B8 (§4.3 §7.1 §7.3) — Query Router v2 markdown renderer.
 *
 * Wraps `react-markdown` (+ remark-gfm for footnotes / tables) with
 * three v2-specific overrides:
 *
 * 1. `pre` — react-markdown emits fenced code blocks as
 *    `<pre><code class="language-*">...</code></pre>`. We inspect the
 *    inner `<code>`'s className: `chart:echarts` → EchartsFence;
 *    anything else → a styled `<pre>` block.
 * 2. `code` — react-markdown emits inline code (e.g. `` `foo` `` inside
 *    a paragraph or a footnote definition) as a bare `<code>` element
 *    with no `<pre>` wrapper.  We MUST NOT introduce a `<pre>` here or
 *    React will throw a hydration error when the inline code lives
 *    inside a `<p>` (invalid HTML: `<p><pre>...`).
 * 3. `blockquote` — blocks led by `> ⚠️` are "generated content"
 *    (§4.3) and get a distinct warning-styled treatment so the reader
 *    knows they're model-inferred, not platform-anchored.
 *
 * Footnote anchor navigation: remark-gfm renders `[^refN]` as
 * superscript links pointing to `#user-content-fn-refN`. We augment
 * the anchor click with `scrollIntoView` so it works inside
 * scrollable containers where the browser default falls flat.
 */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useCallback, useState } from "react";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

import type { KnowledgeChunkHit } from "@/lib/chunkTypes";

import { EchartsFence } from "./EchartsFence";

interface QueryRouterAnswerProps {
  markdown: string;
  onSelectChunk?: (chunk: KnowledgeChunkHit) => void;
}

const CHART_LANG = "chart:echarts";
const GENERATED_MARKER = "⚠️";
const GRAPH_RELATIONS_HEADING_RE = /^#{1,6}\s+图谱关系\s*$/;
const MARKDOWN_LIST_ITEM_RE = /^\s*[-*+]\s+/;
const FOOTNOTE_DEFINITION_RE = /^\[\^[^\]]+\]:/;

type MarkdownSection =
  | { type: "markdown"; markdown: string }
  | { type: "graph_relations"; markdown: string; relationCount: number };

export function QueryRouterAnswer({ markdown, onSelectChunk }: QueryRouterAnswerProps) {
  const handleAnchorClick = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.tagName !== "A") return;
    const anchor = target as HTMLAnchorElement;
    const href = anchor.getAttribute("href") || "";
    if (!href.startsWith("#")) return;
    const id = href.slice(1);
    if (id.startsWith("chunk-preview-")) {
      const chunkId = decodeURIComponent(id.slice("chunk-preview-".length));
      if (!chunkId || !onSelectChunk) return;
      event.preventDefault();
      onSelectChunk({ chunk_id: chunkId, nexus_chunk_id: chunkId, id: chunkId, content: "" });
      return;
    }
    const el = document.getElementById(id);
    if (!el) return;
    event.preventDefault();
    const footnotes = el.closest("details");
    if (footnotes instanceof HTMLDetailsElement) footnotes.open = true;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [onSelectChunk]);

  const renderMarkdown = onSelectChunk ? addFootnotePreviewLinks(markdown) : markdown;

  return (
    <div
      className="query-router-answer prose prose-slate max-w-none text-sm"
      onClick={handleAnchorClick}
      data-testid="query-router-answer"
    >
      {splitGraphRelationSections(renderMarkdown).map((section, index) =>
        section.type === "graph_relations" ? (
          <GraphRelationsDisclosure
            key={`graph-relations-${index}`}
            markdown={section.markdown}
            relationCount={section.relationCount}
          />
        ) : (
          <MarkdownContent key={`markdown-${index}`} markdown={section.markdown} />
        ),
      )}
    </div>
  );
}

function MarkdownContent({ markdown }: { markdown: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        pre: PreRenderer,
        code: InlineCodeRenderer,
        blockquote: BlockquoteRenderer,
        section: FootnoteSectionRenderer,
      }}
    >
      {markdown}
    </ReactMarkdown>
  );
}

function GraphRelationsDisclosure({
  markdown,
  relationCount,
}: {
  markdown: string;
  relationCount: number;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const actionLabel = isOpen ? "收起图谱关系" : "展开图谱关系";
  const Icon = isOpen ? ChevronDown : ChevronRight;

  return (
    <section className="border-line my-3 border-y py-2" data-testid="query-graph-relations">
      <h3 className="m-0 text-sm font-semibold text-gray-800">
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded px-1 py-1 text-left hover:bg-gray-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
          onClick={() => setIsOpen((open) => !open)}
          aria-expanded={isOpen}
          aria-label={actionLabel}
          title={actionLabel}
        >
          <Icon aria-hidden="true" size={16} strokeWidth={2} />
          <span>图谱关系（{relationCount} 条）</span>
        </button>
      </h3>
      {isOpen ? <MarkdownContent markdown={markdown} /> : null}
    </section>
  );
}

function splitGraphRelationSections(markdown: string): MarkdownSection[] {
  const lines = markdown.split("\n");
  const sections: MarkdownSection[] = [];
  let markdownStart = 0;
  let index = 0;

  while (index < lines.length) {
    if (!GRAPH_RELATIONS_HEADING_RE.test(lines[index])) {
      index += 1;
      continue;
    }

    let listStart = index + 1;
    while (listStart < lines.length && lines[listStart].trim() === "") listStart += 1;
    if (listStart >= lines.length || !MARKDOWN_LIST_ITEM_RE.test(lines[listStart])) {
      index += 1;
      continue;
    }

    let listEnd = listStart;
    while (listEnd < lines.length) {
      const line = lines[listEnd];
      if (line.trim() === "" || MARKDOWN_LIST_ITEM_RE.test(line) || /^\s{2,}\S/.test(line)) {
        listEnd += 1;
        continue;
      }
      break;
    }
    while (listEnd > listStart && lines[listEnd - 1].trim() === "") listEnd -= 1;

    let sectionEnd = listEnd;
    while (
      sectionEnd < lines.length &&
      (lines[sectionEnd].trim() === "" || FOOTNOTE_DEFINITION_RE.test(lines[sectionEnd]))
    ) {
      sectionEnd += 1;
    }

    const precedingMarkdown = lines.slice(markdownStart, index).join("\n");
    if (precedingMarkdown) sections.push({ type: "markdown", markdown: precedingMarkdown });

    const relationMarkdown = lines.slice(listStart, sectionEnd).join("\n");
    sections.push({
      type: "graph_relations",
      markdown: relationMarkdown,
      relationCount: lines.slice(listStart, listEnd).filter((line) => MARKDOWN_LIST_ITEM_RE.test(line)).length,
    });
    markdownStart = sectionEnd;
    index = sectionEnd;
  }

  const trailingMarkdown = lines.slice(markdownStart).join("\n");
  if (trailingMarkdown || sections.length === 0) {
    sections.push({ type: "markdown", markdown: trailingMarkdown });
  }
  return sections;
}

const FOOTNOTE_CHUNK_ID_RE = /(^\[\^[^\]]+\]:[^\n]*?\bchunk_id\s*[:：]\s*`?)([0-9a-f-]{36})(`?[^\n]*)$/gim;

function addFootnotePreviewLinks(markdown: string): string {
  return markdown.replace(
    FOOTNOTE_CHUNK_ID_RE,
    (_matched, prefix: string, chunkId: string, suffix: string) =>
      `${prefix}${chunkId}${suffix} [查看原文](#chunk-preview-${chunkId})`,
  );
}

type FootnoteSectionProps = ComponentPropsWithoutRef<"section"> & {
  "data-footnotes"?: string;
};

function FootnoteSectionRenderer({ children, ...props }: FootnoteSectionProps) {
  const isFootnotes = Object.hasOwn(props, "data-footnotes");
  if (!isFootnotes) return <section {...props}>{children}</section>;
  const { "data-footnotes": _footnotes, ...sectionProps } = props;
  return (
    <details className="border-line mt-5 border-t pt-3" data-testid="query-footnotes">
      <summary className="cursor-pointer text-xs font-medium text-gray-600 hover:text-gray-900">
        来源引用
      </summary>
      <section {...sectionProps} className="mt-2 text-xs text-gray-500">
        {children}
      </section>
    </details>
  );
}

// ---------------------------------------------------------------------------
// pre — fenced code block; dispatch to EchartsFence when language matches
// ---------------------------------------------------------------------------

interface PreProps {
  children?: ReactNode;
}

function PreRenderer({ children }: PreProps) {
  const codeChild = findCodeChild(children);
  if (codeChild) {
    const className = readClassName(codeChild);
    const lang = extractLanguage(className);
    if (lang === CHART_LANG) {
      return <EchartsFence raw={extractText(codeChild)} />;
    }
  }
  return (
    <pre className="border-line my-3 overflow-auto rounded-md border bg-gray-50 p-3 text-xs">
      {children}
    </pre>
  );
}

// ---------------------------------------------------------------------------
// code — inline code only (no <pre> wrapper). Fenced blocks go via PreRenderer.
// ---------------------------------------------------------------------------

interface CodeProps {
  className?: string;
  children?: ReactNode;
}

function InlineCodeRenderer({ className, children, ...rest }: CodeProps) {
  return (
    <code className={className} {...rest}>
      {children}
    </code>
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

function extractLanguage(className: string | undefined | null): string | null {
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

// react-markdown's `pre` component receives its children directly; the
// child is normally a single React element for the inner `<code>`. We
// walk defensively because whitespace text nodes can sneak in.
function findCodeChild(node: ReactNode): ReactNode | null {
  if (Array.isArray(node)) {
    for (const item of node) {
      const found = findCodeChild(item);
      if (found) return found;
    }
    return null;
  }
  if (node && typeof node === "object" && "type" in node) {
    const el = node as { type?: unknown; props?: { children?: ReactNode } };
    if (el.type === "code" || (typeof el.type === "function" && el.type.name === "InlineCodeRenderer")) {
      return node;
    }
  }
  return null;
}

function readClassName(node: ReactNode): string | undefined {
  if (node && typeof node === "object" && "props" in node) {
    const props = (node as { props?: { className?: string } }).props;
    return props?.className;
  }
  return undefined;
}

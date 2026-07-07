"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { Alert, Card, Empty, Skeleton, Space, Tag } from "antd";
import type { ECharts, EChartsOption } from "echarts";

import type { NormalizedAssetRef } from "@/lib/api";
import type { NormalizedBlock, NormalizedRefContent } from "@/lib/chunkTypes";
import {
  downloadEchartsGraphImage,
  GraphViewportActions,
  type GraphImageHandle,
} from "./GraphViewportActions";

type Props = {
  normalizedRef: NormalizedAssetRef | null;
};

type ProxyEnvelope<T> = {
  ok: true;
  status: number;
  data: T;
  traceId: string | null;
};

type ProxyErrorEnvelope = {
  ok: false;
  status: number;
  message: string;
};

type DocumentGraphNode = {
  id: string;
  title: string;
  label: "文档" | "章/模块" | "节";
  depth: 0 | 1 | 2;
  blockId: string | null;
  startIndex: number;
  children: DocumentGraphNode[];
};

type HeadingCandidate = {
  block: NormalizedBlock;
  index: number;
  title: string;
  rawTitle: string;
  level: number;
};

type GraphSeriesNode = {
  id: string;
  name: string;
  value: string;
  category: number;
  depth: number;
  x: number;
  y: number;
  fixed: boolean;
  symbolSize: number;
  labelText: string;
  itemStyle: Record<string, unknown>;
  label: Record<string, unknown>;
};

type GraphSeriesLink = {
  source: string;
  target: string;
};

const HEADING_TYPES = new Set(["heading", "title"]);
const MAX_REASONABLE_CHAPTERS = 80;
const CHAPTER_MODULE_RE = /^\s*(?:第\s*[一二三四五六七八九十百千万零〇两\d]+\s*[章节篇单元模块]|项目\s*[一二三四五六七八九十百千万零〇两\d]+|模块\s*[一二三四五六七八九十百千万零〇两\d]+|单元\s*[一二三四五六七八九十百千万零〇两\d]+|Chapter\s+\d+|Unit\s+\d+|Module\s+\d+)\b/i;
const SECTION_HEADING_RE = /^\s*(?:第\s*[一二三四五六七八九十百千万零〇两\d]+\s*节|任务\s*[一二三四五六七八九十百千万零〇两\d]+|[一二三四五六七八九十百千万零〇两]+[、.．]\s*\S+|\d+(?:\.\d+)+\s+\S+|Section\s+\d+(?:\.\d+)*)\b/i;
const COLUMN_HEADING_RE = /^\s*(?:学习目标|教学目标|知识目标|能力目标|技能目标|素养目标|学习导图|学习要点|知识准备|内容提要|摘要|概述|简介|前言|导言|任务实施|操作步骤|课后练习|练习题|拓展阅读|案例导入|课堂活动|思考与练习|项目小结|本章小结)\s*$/;
const CHINESE_SECTION_RE = /^\s*[一二三四五六七八九十百千万零〇两]+[、.．]\s*(.+?)\s*$/;
const ARABIC_SECTION_RE = /^\s*\d+(?:[.．、]\s*)+(.+?)\s*$/;
const STRUCTURED_RE = /^\s*(项目|任务|单元|模块|章节|章|节)\s*([一二三四五六七八九十百千万零〇两\d]+)?[、.．\s]*(.+?)\s*$/;

export function DocumentKnowledgeGraphView({ normalizedRef }: Props) {
  const refId = normalizedRef?.id ?? null;
  const [content, setContent] = useState<NormalizedRefContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!refId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/normalized-refs/${encodeURIComponent(refId)}/content`,
        { cache: "no-store" },
      );
      const body = (await res.json()) as ProxyEnvelope<NormalizedRefContent> | ProxyErrorEnvelope;
      if (!body.ok) {
        throw new Error(body.message || `HTTP ${res.status}`);
      }
      setContent(body.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setContent(null);
    } finally {
      setLoading(false);
    }
  }, [refId]);

  useEffect(() => {
    if (!refId) return;
    load();
  }, [load, refId]);

  const roots = useMemo(
    () => buildDocumentGraph(content?.blocks ?? [], documentTitle(normalizedRef, content)),
    [content, normalizedRef],
  );
  const graphStats = useMemo(() => graphCounts(roots), [roots]);
  const graphRef = useRef<GraphImageHandle | null>(null);

  if (!refId) {
    return (
      <Card className="!mt-4" title="知识图谱">
        <Alert type="info" showIcon title="该资产尚无标准化引用，暂无可展示的知识图谱。" />
      </Card>
    );
  }

  return (
    <Card
      className="!mt-4"
      title={
        <Space wrap>
          <span>知识图谱</span>
          {graphStats.nodes > 0 ? <Tag color="processing">{graphStats.nodes} 节点</Tag> : null}
          {graphStats.chapters > 0 ? <Tag color="blue">{graphStats.chapters} 章/模块</Tag> : null}
          {graphStats.sections > 0 ? <Tag color="green">{graphStats.sections} 节</Tag> : null}
        </Space>
      }
      extra={
        roots.length > 0 ? (
          <GraphViewportActions
            title="知识图谱"
            immersive
            onDownload={() => graphRef.current?.downloadImage("知识图谱.png")}
          >
            <DocumentGraphCanvas ref={graphRef} roots={roots} fullscreen />
          </GraphViewportActions>
        ) : null
      }
    >
      {error ? <Alert type="error" showIcon className="!mb-3" title="加载知识图谱失败" description={error} /> : null}
      {loading && content === null ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : roots.length === 0 ? (
        <Empty description="该文档暂无可识别的标题层级。" />
      ) : (
        <DocumentGraphCanvas ref={graphRef} roots={roots} />
      )}
    </Card>
  );
}

const DocumentGraphCanvas = forwardRef<GraphImageHandle, { roots: DocumentGraphNode[]; fullscreen?: boolean }>(
  function DocumentGraphCanvas(
  {
    roots,
    fullscreen = false,
  },
  forwardedRef,
) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const option = useMemo<EChartsOption>(() => buildGraphOption(roots), [roots]);
  const nodeCount = useMemo(() => graphCounts(roots).nodes, [roots]);

  useImperativeHandle(forwardedRef, () => ({
    downloadImage: (filename: string) => downloadEchartsGraphImage({
      option,
      filename,
      nodeCount,
    }),
  }), [nodeCount, option]);

  useEffect(() => {
    const container = chartRef.current;
    if (!container) return;
    let disposed = false;
    let chart: ECharts | null = null;
    let resizeObserver: ResizeObserver | null = null;

    import("echarts").then((echarts) => {
      if (disposed || !chartRef.current) return;
      chart = echarts.init(chartRef.current);
      chart.setOption(option);
      resizeObserver = new ResizeObserver(() => {
        if (disposed || !chart || chart.isDisposed()) return;
        requestAnimationFrame(() => {
          if (!disposed && chart && !chart.isDisposed()) chart.resize();
        });
      });
      resizeObserver.observe(container);
      requestAnimationFrame(() => chart?.resize());
    });

    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      chart?.dispose();
    };
  }, [option]);

  return (
    <div
      ref={chartRef}
      style={{
        width: "100%",
        minHeight: fullscreen ? 0 : 680,
        height: fullscreen ? "100%" : "72vh",
        maxHeight: fullscreen ? "none" : 920,
        border: "1px solid var(--line)",
        borderRadius: "var(--radius-md)",
        background: "radial-gradient(circle at 20% 15%, #f8fafc 0, #ffffff 34%, #f8fafc 100%)",
      }}
      aria-label="文档知识图谱"
    />
  );
});

function buildDocumentGraph(blocks: NormalizedBlock[], fallbackTitle: string): DocumentGraphNode[] {
  const normalized = blocks.map((block, index) => ({ block, index }));
  if (normalized.length === 0) return [];

  const root: DocumentGraphNode = {
    id: "doc:root",
    title: fallbackTitle || "未命名文档",
    label: "文档",
    depth: 0,
    blockId: null,
    startIndex: 0,
    children: [],
  };

  const headings = normalized
    .filter(({ block }) => isHeadingBlock(block) && blockText(block))
    .map(({ block, index }) => headingCandidate(block, index));
  const firstHeading = headings[0];
  if (firstHeading && isDocumentTitleCandidate(firstHeading)) {
    root.title = firstHeading.title || root.title;
    root.blockId = firstHeading.block.block_id;
    root.startIndex = firstHeading.index;
  }
  const hasStrongChapters = headings.some((heading) => isStrongChapterTitle(heading.rawTitle));
  const levelOneChapterCandidates = headings.filter((heading) => isFallbackChapterCandidate(heading, root.blockId));
  const allowLevelOneFallback =
    !hasStrongChapters &&
    levelOneChapterCandidates.length > 0 &&
    levelOneChapterCandidates.length <= MAX_REASONABLE_CHAPTERS;

  let currentChapter: DocumentGraphNode | null = null;

  for (const heading of headings) {
    if (heading.block.block_id === root.blockId || isDocumentTitleCandidate(heading)) {
      continue;
    }
    if (isStrongChapterTitle(heading.rawTitle) || (allowLevelOneFallback && isFallbackChapterCandidate(heading, root.blockId))) {
      currentChapter = makeNode({
        block: heading.block,
        title: heading.title,
        label: "章/模块",
        depth: 1,
        index: heading.index,
      });
      root.children.push(currentChapter);
      continue;
    }

    if (isSectionCandidate(heading) && currentChapter) {
      currentChapter.children.push(makeNode({
        block: heading.block,
        title: heading.title,
        label: "节",
        depth: 2,
        index: heading.index,
      }));
    }
  }

  if (root.children.length === 0) {
    root.children.push(makeNode({
      block: normalized[0].block,
      title: root.title,
      label: "章/模块",
      depth: 1,
      index: 0,
    }));
  }

  return [root];
}

function makeNode({
  block,
  title,
  label,
  depth,
  index,
}: {
  block: NormalizedBlock;
  title: string;
  label: "章/模块" | "节";
  depth: 1 | 2;
  index: number;
}): DocumentGraphNode {
  return {
    id: `${depth}:${block.block_id}`,
    title,
    label,
    depth,
    blockId: block.block_id,
    startIndex: index,
    children: [],
  };
}

function headingCandidate(block: NormalizedBlock, index: number): HeadingCandidate {
  const rawTitle = blockText(block);
  const title = cleanHeadingTitle(rawTitle);
  const level = headingLevel(block);
  return { block, index, title, rawTitle, level };
}

function isDocumentTitleCandidate(heading: HeadingCandidate): boolean {
  return heading.level <= 1 && heading.index <= 3;
}

function isFallbackChapterCandidate(heading: HeadingCandidate, rootBlockId: string | null): boolean {
  if (heading.block.block_id === rootBlockId) return false;
  if (heading.level !== 1) return false;
  if (isColumnHeading(heading.rawTitle)) return false;
  if (isSectionTitle(heading.rawTitle)) return false;
  return Boolean(heading.title);
}

function isSectionCandidate(heading: HeadingCandidate): boolean {
  if (isSectionTitle(heading.rawTitle)) return true;
  return heading.level === 2 && !isColumnHeading(heading.rawTitle) && !isStrongChapterTitle(heading.rawTitle);
}

function isStrongChapterTitle(title: string): boolean {
  return CHAPTER_MODULE_RE.test(title.replace(/\s+/g, " ").trim());
}

function isSectionTitle(title: string): boolean {
  const normalized = title.replace(/\s+/g, " ").trim();
  if (isColumnHeading(normalized)) return false;
  return SECTION_HEADING_RE.test(normalized);
}

function isColumnHeading(title: string): boolean {
  return COLUMN_HEADING_RE.test(title.replace(/\s+/g, ""));
}

function buildGraphOption(roots: DocumentGraphNode[]): EChartsOption {
  const { nodes, links } = flattenGraph(roots);
  return {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      triggerOn: "mousemove",
      formatter: (params: unknown) => {
        const data = (params as { data?: GraphSeriesNode }).data;
        if (!data?.labelText) return "";
        return `${escapeHtml(data.labelText)}：${escapeHtml(data.name)}`;
      },
    },
    legend: [{
      top: 16,
      left: 20,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: "#475569", fontSize: 12 },
    }],
    series: [{
      type: "graph",
      layout: "none",
      data: nodes,
      links,
      categories: [
        { name: "文档" },
        { name: "章/模块" },
        { name: "节" },
      ],
      roam: true,
      draggable: true,
      top: 54,
      left: 32,
      right: 32,
      bottom: 32,
      edgeSymbol: ["none", "none"],
      lineStyle: {
        color: "#cbd5e1",
        width: 1.4,
        opacity: 0.86,
        curveness: 0.12,
      },
      label: {
        show: true,
        formatter: (params: unknown) => {
          const data = (params as { data?: GraphSeriesNode }).data;
          return data ? wrapLabel(data.name, data.depth) : "";
        },
      },
      emphasis: {
        focus: "adjacency",
        lineStyle: {
          width: 2.4,
          color: "#64748b",
        },
      },
      animationDuration: 450,
      animationDurationUpdate: 450,
    }],
  };
}

function flattenGraph(roots: DocumentGraphNode[]): { nodes: GraphSeriesNode[]; links: GraphSeriesLink[] } {
  const nodes: GraphSeriesNode[] = [];
  const links: GraphSeriesLink[] = [];
  const positions = layoutGraphNodes(roots);

  const visit = (node: DocumentGraphNode, parent: DocumentGraphNode | null) => {
    nodes.push(toSeriesNode(node, positions.get(node.id)));
    if (parent) {
      links.push({ source: parent.id, target: node.id });
    }
    node.children.forEach((child) => visit(child, node));
  };

  roots.forEach((root) => visit(root, null));
  return { nodes, links };
}

function layoutGraphNodes(roots: DocumentGraphNode[]): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const root = roots[0];
  if (!root) return positions;

  const chapterGap = 136;
  const sectionGap = 82;
  const xByDepth = [120, 440, 780];
  const chapterBands = root.children.map((chapter) => Math.max(chapterGap, Math.max(1, chapter.children.length) * sectionGap));
  const totalHeight = Math.max(360, chapterBands.reduce((sum, value) => sum + value, 0));
  let cursor = 0;

  positions.set(root.id, { x: xByDepth[0], y: totalHeight / 2 });
  root.children.forEach((chapter, index) => {
    const bandHeight = chapterBands[index];
    const bandTop = cursor;
    const chapterY = bandTop + bandHeight / 2;
    positions.set(chapter.id, { x: xByDepth[1], y: chapterY });

    if (chapter.children.length > 0) {
      const firstSectionY = chapterY - ((chapter.children.length - 1) * sectionGap) / 2;
      chapter.children.forEach((section, sectionIndex) => {
        positions.set(section.id, {
          x: xByDepth[2],
          y: firstSectionY + sectionIndex * sectionGap,
        });
      });
    }
    cursor += bandHeight;
  });

  return positions;
}

function toSeriesNode(node: DocumentGraphNode, position?: { x: number; y: number }): GraphSeriesNode {
  const style = nodeStyle(node.depth);
  return {
    id: node.id,
    name: node.title,
    value: node.id,
    labelText: node.label,
    depth: node.depth,
    x: position?.x ?? 0,
    y: position?.y ?? 0,
    fixed: true,
    category: node.depth,
    symbolSize: node.depth === 0 ? 58 : node.depth === 1 ? 42 : 28,
    itemStyle: {
      color: style.symbolColor,
      borderColor: style.borderColor,
      borderWidth: node.depth === 0 ? 3 : 1.6,
      shadowBlur: node.depth === 0 ? 10 : 3,
      shadowColor: style.shadowColor,
    },
    label: {
      color: style.textColor,
      backgroundColor: style.labelBackground,
      borderColor: style.borderColor,
      borderWidth: 1,
      borderRadius: 6,
      padding: [6, 8],
      fontWeight: node.depth < 2 ? 700 : 500,
      lineHeight: 17,
    },
  };
}

function nodeStyle(depth: number) {
  if (depth === 0) {
    return {
      symbolColor: "#7c3aed",
      borderColor: "#6d28d9",
      textColor: "#4c1d95",
      labelBackground: "#f5f3ff",
      shadowColor: "rgba(109, 40, 217, 0.2)",
    };
  }
  if (depth === 1) {
    return {
      symbolColor: "#2563eb",
      borderColor: "#1d4ed8",
      textColor: "#1e3a8a",
      labelBackground: "#eff6ff",
      shadowColor: "rgba(29, 78, 216, 0.16)",
    };
  }
  return {
    symbolColor: "#10b981",
    borderColor: "#047857",
    textColor: "#064e3b",
    labelBackground: "#ecfdf5",
    shadowColor: "rgba(4, 120, 87, 0.12)",
  };
}

function isHeadingBlock(block: NormalizedBlock): boolean {
  return HEADING_TYPES.has(String(block.block_type || "").toLowerCase()) || typeof block.heading_level === "number";
}

function headingLevel(block: NormalizedBlock): number {
  if (typeof block.heading_level === "number" && Number.isFinite(block.heading_level)) {
    return Math.max(1, Math.trunc(block.heading_level));
  }
  return String(block.block_type || "").toLowerCase() === "title" ? 1 : 2;
}

function blockText(block: NormalizedBlock): string {
  return String(block.text ?? block.content ?? "").trim();
}

function cleanHeadingTitle(value: string): string {
  const text = value.replace(/\s+/g, " ").trim();
  const chinese = text.match(CHINESE_SECTION_RE);
  if (chinese) return chinese[1].trim();
  const arabic = text.match(ARABIC_SECTION_RE);
  if (arabic) return arabic[1].trim();
  const structured = text.match(STRUCTURED_RE);
  if (structured?.[3]) return structured[3].trim();
  return text;
}

function documentTitle(ref: NormalizedAssetRef | null, content: NormalizedRefContent | null): string {
  const fromRef = String(ref?.title || "").trim();
  if (fromRef) return fromRef;
  return String(content?.ref_id || "").trim() || "未命名文档";
}

function graphCounts(roots: DocumentGraphNode[]): { nodes: number; chapters: number; sections: number } {
  const counts = { nodes: 0, chapters: 0, sections: 0 };
  const visit = (node: DocumentGraphNode) => {
    counts.nodes += 1;
    if (node.depth === 1) counts.chapters += 1;
    if (node.depth === 2) counts.sections += 1;
    node.children.forEach(visit);
  };
  roots.forEach(visit);
  return counts;
}

function wrapLabel(label: string, depth: number): string {
  const maxLineLength = depth === 2 ? 16 : 14;
  const maxLines = depth === 2 ? 3 : 2;
  const chars = Array.from(label);
  if (chars.length <= maxLineLength) return label;
  const lines: string[] = [];
  for (let index = 0; index < chars.length && lines.length < maxLines; index += maxLineLength) {
    lines.push(chars.slice(index, index + maxLineLength).join(""));
  }
  if (chars.length > maxLineLength * maxLines && lines.length > 0) {
    lines[lines.length - 1] = `${lines[lines.length - 1].slice(0, -1)}…`;
  }
  return lines.join("\n");
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

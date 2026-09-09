"use client";

import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Alert, Empty, Skeleton, Tag, Tree, Typography } from "antd";
import type { DataNode } from "antd/es/tree";
import type { ECharts, EChartsOption } from "echarts";
import remarkGfm from "remark-gfm";

import type { TaskOutlineEnvelope, TaskOutlineNode } from "@/lib/api";
import {
  downloadEchartsGraphImage,
  GraphViewportActions,
  type GraphImageHandle,
} from "@/app/assets/[assetId]/_components/GraphViewportActions";

const Markdown = dynamic(() => import("react-markdown"), {
  ssr: false,
  loading: () => <Skeleton active paragraph={{ rows: 2 }} />,
});

export type CourseTextbookTaskOutlineMode = "tree" | "radial";

type Props = {
  refId: string;
  mode: CourseTextbookTaskOutlineMode;
};

type ApiEnvelope =
  | {
      data: TaskOutlineEnvelope;
      error?: never;
      meta?: { trace_id?: string | null };
    }
  | {
      data?: never;
      error: { message?: string };
      meta?: { trace_id?: string | null };
    };

type OutlineTreeNode = {
  key: string;
  node: TaskOutlineNode | null;
  title: string;
  label: string;
  pageRange: string | null;
  children: OutlineTreeNode[];
};

type ChartTooltipData = {
  data?: {
    nodeLabel?: string;
    pageRange?: string;
    contentPreview?: string | null;
    name?: string;
  };
};

const NODE_LABELS: Record<string, string> = {
  book: "教材",
  project: "项目",
  task: "任务",
  task_section: "章节",
  operation_step: "步骤",
  task_artifact: "产物",
  assessment: "评价",
};

const SECTION_LABELS: Record<string, string> = {
  task_objective: "目标",
  task_background: "背景",
  task_analysis: "分析",
  knowledge_prepare: "知识准备",
  operation_steps: "任务实施",
  task_artifact: "任务产物",
  source_resource: "资源",
  task_reflection: "思考",
  assessment: "评价",
};

export function CourseTextbookTaskOutlineView({ refId, mode }: Props) {
  const [data, setData] = useState<TaskOutlineEnvelope | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const radialRef = useRef<GraphImageHandle | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/normalized-refs/${encodeURIComponent(refId)}/task-outline`, {
      cache: "no-store",
    })
      .then(async (response) => {
        const body = (await response.json()) as ApiEnvelope;
        if (!response.ok || body.error) {
          throw new Error(body.error?.message || `HTTP ${response.status}`);
        }
        if (!cancelled) setData(body.data);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
          setData(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refId]);

  const profile = data?.profile ?? null;
  const outlineTree = useMemo(() => buildOutlineTree(data?.nodes ?? []), [data?.nodes]);
  const graphDisabled = outlineTree.length === 0;

  return (
    <section className="flex min-h-[620px] flex-col gap-3">
      <div className="flex min-h-8 items-center justify-end">
        {profile && outlineTree.length > 0 ? (
          mode === "tree" ? (
            <GraphViewportActions
              title="任务大纲树"
              disabled={graphDisabled}
              downloadLabel="下载任务大纲 Markdown"
              downloadAriaLabel="下载任务大纲 Markdown"
              onDownload={() => downloadTextFile("任务大纲.md", outlineTreeToMarkdown(outlineTree))}
            >
              <div className="h-full overflow-auto">
                <TaskTreeSection roots={outlineTree} fullscreen />
              </div>
            </GraphViewportActions>
          ) : (
            <GraphViewportActions
              title="任务大纲圆形树"
              disabled={graphDisabled}
              immersive
              onDownload={() => radialRef.current?.downloadImage("任务大纲圆形树.png")}
            >
              <RadialTaskTree roots={outlineTree} fullscreen />
            </GraphViewportActions>
          )
        ) : null}
      </div>
      {error ? <Alert type="error" showIcon className="!mb-3" title={error} /> : null}
      {loading && data === null ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : !profile ? (
        <Empty description="该 ref 暂未构建任务大纲。" />
      ) : outlineTree.length === 0 ? (
        <Empty description="该任务大纲暂无节点。" />
      ) : (
        <div className="flex flex-col gap-4">
          {mode === "tree" ? <TaskTreeSection roots={outlineTree} /> : null}
          {mode === "radial" ? <RadialTaskTree ref={radialRef} roots={outlineTree} /> : null}
        </div>
      )}
    </section>
  );
}

function TaskTreeSection({
  roots,
  fullscreen = false,
}: {
  roots: OutlineTreeNode[];
  fullscreen?: boolean;
}) {
  const treeData = useMemo(() => roots.map(toDataNode), [roots]);
  const expandedKeys = useMemo(() => {
    const keys: string[] = [];
    const visit = (node: OutlineTreeNode) => {
      if (node.node && node.node.depth <= 1) keys.push(node.key);
      node.children.forEach(visit);
    };
    roots.forEach(visit);
    return keys;
  }, [roots]);

  return (
    <div
      className={`task-outline-tree-view border-line bg-bg-subtle w-full rounded border ${
        fullscreen ? "min-h-full overflow-auto px-5 py-4" : "overflow-x-auto px-4 py-3"
      }`}
    >
      <Tree
        className="min-w-full"
        treeData={treeData}
        defaultExpandedKeys={expandedKeys}
        showLine
        selectable={false}
        blockNode
        aria-label="任务大纲树"
      />
      <style jsx>{`
        .task-outline-tree-view :global(.ant-tree),
        .task-outline-tree-view :global(.ant-tree-list),
        .task-outline-tree-view :global(.ant-tree-list-holder),
        .task-outline-tree-view :global(.ant-tree-list-holder-inner) {
          width: 100%;
        }

        .task-outline-tree-view :global(.ant-tree-treenode) {
          align-items: flex-start;
          width: 100%;
        }

        .task-outline-tree-view :global(.ant-tree-node-content-wrapper) {
          flex: 1;
          min-width: 0;
          max-width: none;
        }

        .task-outline-tree-view :global(.ant-tree-title) {
          display: block;
          width: 100%;
          min-width: 0;
        }
      `}</style>
    </div>
  );
}

function toDataNode(item: OutlineTreeNode): DataNode {
  return {
    key: item.key,
    title: <TreeNodeTitle item={item} />,
    children: item.children.map(toDataNode),
  };
}

function TreeNodeTitle({ item }: { item: OutlineTreeNode }) {
  const node = item.node;
  const content = displayContent(item);
  return (
    <div className="w-full min-w-0 py-1 pr-2">
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <Tag className="!m-0" color={node?.node_type === "operation_step" ? "blue" : "default"}>
          {item.label}
        </Tag>
        <Typography.Text strong className="max-w-full">
          {item.title}
        </Typography.Text>
        {item.pageRange ? <Tag className="!m-0">{item.pageRange}</Tag> : null}
        {node?.source_block_ids.length ? (
          <Tag className="!m-0">{node.source_block_ids.length} blocks</Tag>
        ) : null}
      </div>
      {content ? <MarkdownContent content={content} /> : null}
    </div>
  );
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="task-outline-markdown border-line bg-bg text-text-secondary mt-2 w-full min-w-0 overflow-x-auto rounded border px-3 py-2 text-sm leading-6">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="mb-2 whitespace-pre-wrap last:mb-0">{children}</p>,
          table: ({ children }) => (
            <table className="my-2 w-full min-w-[680px] border-collapse text-xs leading-5">
              {children}
            </table>
          ),
          th: ({ children }) => (
            <th className="border-line bg-bg-subtle text-text-secondary border px-2 py-1 text-left font-medium">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-line bg-bg text-text-secondary border px-2 py-1 align-top">
              {children}
            </td>
          ),
          ul: ({ children }) => <ul className="mb-1 list-disc pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="mb-1 list-decimal pl-5">{children}</ol>,
          code: ({ children }) => (
            <code className="bg-fill rounded px-1 py-0.5 text-xs">{children}</code>
          ),
        }}
      >
        {content}
      </Markdown>
    </div>
  );
}

const RadialTaskTree = forwardRef<
  GraphImageHandle,
  { roots: OutlineTreeNode[]; fullscreen?: boolean }
>(function RadialTaskTree({ roots, fullscreen = false }, forwardedRef) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const instanceRef = useRef<ECharts | null>(null);
  const nodeCount = useMemo(() => countOutlineNodes(roots), [roots]);
  const option = useMemo<EChartsOption>(
    () => ({
      tooltip: {
        trigger: "item",
        triggerOn: "mousemove",
        formatter: (params) => {
          const item = Array.isArray(params) ? params[0] : params;
          const data = (item as ChartTooltipData | undefined)?.data;
          const page = data?.pageRange ? `<br/>${data.pageRange}` : "";
          const content = data?.contentPreview
            ? `<br/><span style="display:inline-block;max-width:360px;white-space:normal;line-height:1.5;margin-top:4px;">${escapeHtml(data.contentPreview)}</span>`
            : "";
          return `${data?.nodeLabel ?? "节点"}：${escapeHtml(data?.name ?? "")}${page}${content}`;
        },
      },
      series: [
        {
          type: "tree",
          data: [toChartTree(roots)],
          layout: "radial",
          top: 24,
          bottom: 24,
          left: 24,
          right: 24,
          symbol: "circle",
          symbolSize: 7,
          initialTreeDepth: 4,
          roam: true,
          expandAndCollapse: true,
          animationDuration: 300,
          animationDurationUpdate: 450,
          label: {
            position: "right",
            rotate: 0,
            fontSize: 11,
            overflow: "truncate",
            width: 120,
          },
          leaves: {
            label: {
              position: "right",
              rotate: 0,
              fontSize: 11,
              overflow: "truncate",
              width: 120,
            },
          },
          itemStyle: { color: "#1677ff" },
          lineStyle: { color: "#94a3b8", width: 1 },
          emphasis: { focus: "descendant" },
        },
      ],
    }),
    [roots],
  );

  useImperativeHandle(
    forwardedRef,
    () => ({
      downloadImage: (filename: string) =>
        downloadEchartsGraphImage({
          option,
          filename,
          nodeCount,
        }),
    }),
    [nodeCount, option],
  );

  useEffect(() => {
    if (!chartRef.current) return;
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;
    const container = chartRef.current;
    import("echarts").then((echarts) => {
      if (disposed) return;
      const chart = echarts.init(container);
      instanceRef.current = chart;
      chart.setOption(option);
      resizeObserver = new ResizeObserver(() => {
        if (disposed || chart.isDisposed()) return;
        requestAnimationFrame(() => {
          if (!disposed && !chart.isDisposed()) chart.resize();
        });
      });
      resizeObserver.observe(container);
      requestAnimationFrame(() => {
        if (!disposed && !chart.isDisposed()) chart.resize();
      });
    });
    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      instanceRef.current?.dispose();
      instanceRef.current = null;
    };
  }, [option]);

  useEffect(() => {
    instanceRef.current?.setOption(option, true);
  }, [option]);

  return (
    <div
      className={`border-line bg-bg-subtle w-full rounded border ${fullscreen ? "h-full min-h-0" : ""}`}
    >
      <div
        ref={chartRef}
        className={`w-full ${fullscreen ? "h-full min-h-0" : "h-[680px] min-h-[520px]"}`}
      />
    </div>
  );
});

function buildOutlineTree(nodes: TaskOutlineNode[]): OutlineTreeNode[] {
  const items = new Map<string, OutlineTreeNode>();
  const childrenByParent = new Map<string, OutlineTreeNode[]>();
  const roots: OutlineTreeNode[] = [];

  for (const node of nodes) {
    const title = node.title?.trim() || null;
    const content = node.summary?.trim() || node.content?.trim() || null;
    if (!title && !content) {
      continue;
    }
    items.set(node.id, {
      key: node.id,
      node,
      title: title || _shortTreeText(content),
      label: nodeLabel(node),
      pageRange: formatPageRange(node.locator),
      children: [],
    });
  }

  for (const item of items.values()) {
    const parentId = item.node?.parent_id ?? null;
    if (parentId && items.has(parentId)) {
      const siblings = childrenByParent.get(parentId) ?? [];
      siblings.push(item);
      childrenByParent.set(parentId, siblings);
    } else {
      roots.push(item);
    }
  }

  for (const [parentId, children] of childrenByParent.entries()) {
    const parent = items.get(parentId);
    if (parent) parent.children = sortOutlineNodes(children);
  }

  return sortOutlineNodes(roots);
}

function sortOutlineNodes(items: OutlineTreeNode[]) {
  return [...items].sort((a, b) => {
    const aNode = a.node;
    const bNode = b.node;
    if (aNode && bNode && aNode.order_no !== bNode.order_no) {
      return aNode.order_no - bNode.order_no;
    }
    return a.title.localeCompare(b.title, "zh-Hans-CN");
  });
}

function toChartTree(roots: OutlineTreeNode[]) {
  if (roots.length === 1) return toChartNode(roots[0]);
  return {
    name: "任务大纲",
    nodeLabel: "任务大纲",
    contentPreview: null,
    children: roots.map(toChartNode),
  };
}

function toChartNode(item: OutlineTreeNode): {
  name: string;
  nodeLabel: string;
  pageRange: string | null;
  contentPreview: string | null;
  children?: ReturnType<typeof toChartNode>[];
} {
  const children = item.children.map(toChartNode);
  return {
    name: item.title,
    nodeLabel: item.label,
    pageRange: item.pageRange,
    contentPreview: chartContentPreview(item),
    children: children.length > 0 ? children : undefined,
  };
}

function nodeLabel(node: TaskOutlineNode) {
  return node.section_type
    ? (SECTION_LABELS[node.section_type] ?? node.section_type)
    : (NODE_LABELS[node.node_type] ?? node.node_type);
}

function formatPageRange(locator: Record<string, unknown> | null): string | null {
  if (!locator) return null;
  const start = locator.page_start;
  const end = locator.page_end;
  if (typeof start !== "number") return null;
  if (typeof end === "number" && end !== start) return `p${start}-${end}`;
  return `p${start}`;
}

function displayContent(item: OutlineTreeNode): string | null {
  const node = item.node;
  const content = node?.summary || node?.content;
  if (content && content.trim()) return removeRepeatedTitleLine(content, item.title);
  if (!node || item.children.length > 0) return null;
  if (
    node.node_type === "project" ||
    node.node_type === "task" ||
    node.node_type === "task_section"
  ) {
    return null;
  }
  const title = item.title.trim();
  return title && title !== "(未命名节点)" ? title : null;
}

function chartContentPreview(item: OutlineTreeNode): string | null {
  const content = displayContent(item);
  if (content) return compactPreview(content, 180);
  if (item.node?.section_type === "operation_steps" && item.children.length > 0) {
    const stepTitles = item.children
      .filter((child) => child.node?.node_type === "operation_step")
      .slice(0, 6)
      .map((child) => child.title);
    if (stepTitles.length > 0) {
      return compactPreview(stepTitles.join("\n"), 180);
    }
  }
  return null;
}

function removeRepeatedTitleLine(content: string, title: string): string {
  const trimmedTitle = title.trim();
  const trimmedContent = content.trim();
  if (!trimmedTitle || !trimmedContent.startsWith(trimmedTitle)) return trimmedContent;
  const rest = trimmedContent.slice(trimmedTitle.length);
  if (!rest) return "";
  if (/^[\s\r\n。:：,，.．、]/.test(rest)) {
    return rest.replace(/^[\s\r\n。:：,，.．、]+/, "").trim();
  }
  return trimmedContent;
}

function compactPreview(value: string, maxLength: number): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length <= maxLength ? compact : `${compact.slice(0, maxLength)}...`;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function _shortTreeText(value: string | null): string {
  if (!value) return "(未命名节点)";
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length <= 80 ? compact : compact.slice(0, 80);
}

function countOutlineNodes(roots: OutlineTreeNode[]): number {
  let count = 0;
  const visit = (node: OutlineTreeNode) => {
    count += 1;
    node.children.forEach(visit);
  };
  roots.forEach(visit);
  return count;
}

function outlineTreeToMarkdown(roots: OutlineTreeNode[]): string {
  const lines: string[] = ["# 任务大纲", ""];
  const visit = (node: OutlineTreeNode, depth: number) => {
    const prefix = "  ".repeat(Math.max(0, depth - 1));
    const page = node.pageRange ? ` (${node.pageRange})` : "";
    lines.push(`${prefix}- ${node.label}：${node.title}${page}`);
    const content = displayContent(node);
    if (content) {
      for (const line of content.split(/\r?\n/)) {
        lines.push(`${prefix}  ${line}`);
      }
    }
    node.children.forEach((child) => visit(child, depth + 1));
  };
  roots.forEach((root) => visit(root, 1));
  return `${lines.join("\n")}\n`;
}

function downloadTextFile(filename: string, content: string): boolean {
  if (typeof document === "undefined") return false;
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    return true;
  } finally {
    URL.revokeObjectURL(url);
  }
}

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Empty, Modal, Skeleton, Space, Tag, Typography, message } from "antd";
import type { ECharts, EChartsOption } from "echarts";

import {
  GraphViewportActions,
  downloadEchartsGraphImage,
} from "@/app/assets/[assetId]/_components/GraphViewportActions";
import type {
  KnowledgeOutlineChunkListEntry,
  KnowledgeOutlineChunkPage,
  KnowledgeOutlineNode,
  KnowledgeOutlineTree,
} from "@/lib/api";

export type CourseTextbookKnowledgeOutlineMode = "radial" | "left-to-right";

type Props = {
  refId: string;
  mode: CourseTextbookKnowledgeOutlineMode;
};

type ApiEnvelope<T> = {
  data?: T;
  error?: { message?: string };
};

type TreeItem = {
  node: KnowledgeOutlineNode;
  children: TreeItem[];
};

type ChartTreeNode = {
  name: string;
  value: string;
  outline: {
    id: string;
    chunkCount: number;
  };
  children?: ChartTreeNode[];
};

const DRAWER_CHUNK_LIMIT = 50;

export function CourseTextbookKnowledgeOutlineView({ refId, mode }: Props) {
  const [tree, setTree] = useState<KnowledgeOutlineTree | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [chunks, setChunks] = useState<KnowledgeOutlineChunkPage | null>(null);
  const [chunksLoading, setChunksLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/normalized-refs/${encodeURIComponent(refId)}/knowledge-outline`, {
      cache: "no-store",
    })
      .then(async (response) => {
        const body = (await response.json()) as ApiEnvelope<KnowledgeOutlineTree>;
        if (!response.ok || body.error) {
          throw new Error(body.error?.message || `HTTP ${response.status}`);
        }
        if (!cancelled) setTree(body.data ?? null);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refId]);

  const roots = useMemo(() => buildTreeItems(tree), [tree]);
  const option = useMemo(() => buildChartOption(roots, mode), [mode, roots]);
  const selectedNode = useMemo(
    () => tree?.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [selectedNodeId, tree],
  );

  const openNode = useCallback(async (nodeId: string) => {
    if (nodeId === "synthetic-root") return;
    setSelectedNodeId(nodeId);
    setChunks(null);
    setChunksLoading(true);
    try {
      const response = await fetch(
        `/api/knowledge-outline-nodes/${encodeURIComponent(nodeId)}/chunks?limit=${DRAWER_CHUNK_LIMIT}`,
        { cache: "no-store" },
      );
      const body = (await response.json()) as ApiEnvelope<KnowledgeOutlineChunkPage>;
      if (!response.ok || body.error) {
        throw new Error(body.error?.message || `HTTP ${response.status}`);
      }
      setChunks(body.data ?? null);
    } catch (reason) {
      message.error(
        `加载节点内容失败：${reason instanceof Error ? reason.message : String(reason)}`,
      );
    } finally {
      setChunksLoading(false);
    }
  }, []);

  if (loading) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (error) return <Alert type="error" showIcon title={error} />;
  if (!tree || tree.nodes.length === 0) return <Empty description="暂无知识大纲" />;

  const viewTitle = mode === "radial" ? "知识大纲径向图" : "知识大纲树";
  const rootTitle = tree.nodes.find((node) => node.id === tree.root_id)?.title ?? "课程教材";

  return (
    <section className="flex min-h-[620px] flex-col gap-3">
      <div className="flex min-h-8 items-center justify-end">
        <GraphViewportActions
          title={viewTitle}
          disabled={tree.total_nodes <= 1}
          immersive
          downloadLabel={`下载${viewTitle} PNG`}
          downloadAriaLabel={`下载${viewTitle}`}
          onDownload={() =>
            downloadEchartsGraphImage({
              option,
              filename: `${rootTitle}-${mode === "radial" ? "径向图" : "左到右树"}.png`,
              nodeCount: tree.total_nodes,
            })
          }
        >
          <KnowledgeOutlineChart option={option} onNodeClick={openNode} fullscreen />
        </GraphViewportActions>
      </div>

      <KnowledgeOutlineChart option={option} onNodeClick={openNode} />

      <Modal
        open={selectedNodeId !== null}
        title={selectedNode?.title ?? "节点内容"}
        width={720}
        footer={null}
        destroyOnHidden
        onCancel={() => setSelectedNodeId(null)}
      >
        {chunksLoading ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : !chunks || chunks.chunks.length === 0 ? (
          <Empty description="该节点下暂无知识块" />
        ) : (
          <div
            role="list"
            className="border-line-light max-h-[560px] divide-y overflow-auto border-y"
          >
            {chunks.chunks.map(renderChunkItem)}
          </div>
        )}
      </Modal>
    </section>
  );
}

function KnowledgeOutlineChart({
  option,
  onNodeClick,
  fullscreen = false,
}: {
  option: EChartsOption;
  onNodeClick: (nodeId: string) => void;
  fullscreen?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    let disposed = false;
    let chart: ECharts | null = null;
    let resizeObserver: ResizeObserver | null = null;
    const container = containerRef.current;
    import("echarts").then((echarts) => {
      if (disposed) return;
      chart = echarts.init(container);
      chart.setOption(option);
      chart.on("click", (params) => {
        const data = (params as { data?: { outline?: { id?: unknown } } }).data;
        if (typeof data?.outline?.id === "string") onNodeClick(data.outline.id);
      });
      resizeObserver = new ResizeObserver(() => {
        if (!chart || chart.isDisposed()) return;
        requestAnimationFrame(() => chart?.resize());
      });
      resizeObserver.observe(container);
      requestAnimationFrame(() => chart?.resize());
    });
    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      chart?.dispose();
    };
  }, [onNodeClick, option]);

  return (
    <div
      className={`border-line bg-bg-subtle w-full overflow-hidden rounded border ${
        fullscreen ? "h-full min-h-0" : "h-[620px] min-h-[520px]"
      }`}
      data-outline-layout={
        (option.series as Array<{ layout?: string }> | undefined)?.[0]?.layout ?? "unknown"
      }
    >
      <div ref={containerRef} className="h-full w-full" />
    </div>
  );
}

function buildTreeItems(tree: KnowledgeOutlineTree | null): TreeItem[] {
  if (!tree) return [];
  const byParent = new Map<string | null, KnowledgeOutlineNode[]>();
  for (const node of tree.nodes) {
    const children = byParent.get(node.parent_id) ?? [];
    children.push(node);
    byParent.set(node.parent_id, children);
  }
  for (const children of byParent.values()) {
    children.sort((left, right) => left.order_index - right.order_index);
  }
  const build = (parentId: string | null): TreeItem[] =>
    (byParent.get(parentId) ?? []).map((node) => ({
      node,
      children: build(node.id),
    }));
  return build(null);
}

function displayLabel(node: KnowledgeOutlineNode): string {
  if (!node.numbering) return node.title;
  const title = node.title.trim();
  return title.startsWith(node.numbering) ? title : `${node.numbering} ${title}`;
}

function toChartTree(item: TreeItem): ChartTreeNode {
  return {
    name: displayLabel(item.node),
    value: item.node.id,
    outline: { id: item.node.id, chunkCount: item.node.chunk_count },
    children: item.children.length > 0 ? item.children.map(toChartTree) : undefined,
  };
}

export function buildCourseTextbookKnowledgeOutlineOption(
  roots: TreeItem[],
  mode: CourseTextbookKnowledgeOutlineMode,
): EChartsOption {
  const chartRoots = roots.map(toChartTree);
  const root: ChartTreeNode =
    chartRoots.length === 1
      ? chartRoots[0]
      : {
          name: "知识大纲",
          value: "synthetic-root",
          outline: { id: "synthetic-root", chunkCount: 0 },
          children: chartRoots,
        };
  const leftToRight = mode === "left-to-right";
  return {
    tooltip: {
      trigger: "item",
      formatter: (params) => {
        const item = Array.isArray(params) ? params[0] : params;
        const data = (item as { data?: ChartTreeNode }).data;
        const chunks = data?.outline.chunkCount ? `<br/>${data.outline.chunkCount} 知识块` : "";
        return `${escapeHtml(data?.name ?? "")}${chunks}`;
      },
    },
    series: [
      {
        type: "tree",
        data: [root],
        layout: leftToRight ? "orthogonal" : "radial",
        ...(leftToRight ? { orient: "LR" as const } : {}),
        top: leftToRight ? 36 : 24,
        bottom: leftToRight ? 36 : 24,
        left: leftToRight ? 88 : 24,
        right: leftToRight ? 220 : 24,
        symbol: "circle",
        symbolSize: leftToRight ? 9 : 8,
        initialTreeDepth: 4,
        roam: true,
        expandAndCollapse: true,
        animationDuration: 300,
        animationDurationUpdate: 450,
        label: {
          position: leftToRight ? "left" : "right",
          verticalAlign: "middle",
          align: leftToRight ? "right" : "left",
          fontSize: 11,
          overflow: "truncate",
          width: leftToRight ? 170 : 140,
        },
        leaves: {
          label: {
            position: "right",
            align: "left",
            fontSize: 11,
            overflow: "truncate",
            width: leftToRight ? 190 : 140,
          },
        },
        itemStyle: { color: leftToRight ? "#0f766e" : "#2563eb" },
        lineStyle: { color: "#94a3b8", width: 1 },
        emphasis: { focus: "descendant" },
      },
    ],
  };
}

function buildChartOption(
  roots: TreeItem[],
  mode: CourseTextbookKnowledgeOutlineMode,
): EChartsOption {
  return buildCourseTextbookKnowledgeOutlineOption(roots, mode);
}

function renderChunkItem(chunk: KnowledgeOutlineChunkListEntry) {
  return (
    <article key={chunk.id} role="listitem" className="px-1 py-3">
      <Space size={6} wrap className="!mb-1">
        <Tag className="!m-0">#{chunk.chunk_index + 1}</Tag>
        {chunk.source_block_ids.length > 0 ? (
          <Tag className="!m-0">{chunk.source_block_ids.length} blocks</Tag>
        ) : null}
      </Space>
      <Typography.Paragraph className="!mb-0 text-sm leading-6 whitespace-pre-wrap">
        {chunk.content_preview}
      </Typography.Paragraph>
    </article>
  );
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Drawer,
  Empty,
  List,
  Modal,
  Segmented,
  Skeleton,
  Space,
  Tag,
  Tree,
  Typography,
  message as antdMessage,
} from "antd";
import type { DataNode } from "antd/es/tree";
import type { ECharts, EChartsOption } from "echarts";

import type {
  KnowledgeOutlineChunkListEntry,
  KnowledgeOutlineChunkPage,
  KnowledgeOutlineNode,
  KnowledgeOutlineTree,
} from "@/lib/api";
import {
  GraphViewportActions,
  downloadEchartsGraphImage,
} from "./GraphViewportActions";

type Props = {
  refId: string | null;
  isTheoryKnowledge: boolean;
  // When provided, node click enables a "跳到原文" action that jumps
  // to the preview tab and highlights the target block.
  onJumpToBlock?: (blockId: string) => void;
};

type ViewMode = "tree" | "radial";

type ApiEnvelope<T> = {
  data?: T;
  error?: { message?: string };
};

type TreeItem = {
  key: string;
  node: KnowledgeOutlineNode;
  children: TreeItem[];
};

type ChartTreeNode = {
  name: string;
  value: string;
  data: {
    id: string;
    title: string;
    numbering: string | null;
    chunkCount: number;
  };
  children?: ChartTreeNode[];
};

const CHART_HEIGHT_INLINE = "h-[560px] min-h-[420px]";
const CHART_HEIGHT_FULLSCREEN = "h-full min-h-0";
const TREE_HEIGHT_INLINE = "max-h-[560px] overflow-auto";
const TREE_HEIGHT_FULLSCREEN = "h-full overflow-auto";
const DRAWER_CHUNK_LIMIT = 50;

export function KnowledgeOutlineView({ refId, isTheoryKnowledge, onJumpToBlock }: Props) {
  const [tree, setTree] = useState<KnowledgeOutlineTree | null>(null);
  const [loading, setLoading] = useState(false);
  // v2 review queue stub: pending count only. Full override drawer lands
  // in the next iteration.
  const [pendingReviewCount, setPendingReviewCount] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("radial");
  const [rebuilding, setRebuilding] = useState(false);
  const [drawerNodeId, setDrawerNodeId] = useState<string | null>(null);
  const [drawerChunks, setDrawerChunks] = useState<KnowledgeOutlineChunkPage | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);

  const load = useCallback(async () => {
    if (!refId || !isTheoryKnowledge) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/normalized-refs/${encodeURIComponent(refId)}/knowledge-outline`,
        { cache: "no-store" },
      );
      const body = (await res.json()) as ApiEnvelope<KnowledgeOutlineTree>;
      if (!res.ok || body.error) {
        throw new Error(body.error?.message || `HTTP ${res.status}`);
      }
      setTree(body.data ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setTree(null);
    } finally {
      setLoading(false);
    }
  }, [refId, isTheoryKnowledge]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!refId || !isTheoryKnowledge) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          `/api/normalized-refs/${encodeURIComponent(refId)}/knowledge-outline-reviews?status=pending&limit=200`,
          { cache: "no-store" },
        );
        if (!res.ok) return;
        const body = (await res.json()) as ApiEnvelope<{
          items?: Array<{ id: string }>;
        }>;
        if (!cancelled) {
          setPendingReviewCount(body.data?.items?.length ?? 0);
        }
      } catch {
        // Best-effort — silent failure keeps the outline view usable when
        // the v2 review API isn't reachable (e.g. rules-based rebuild only).
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refId, isTheoryKnowledge, tree?.build_run_id]);

  const rebuild = useCallback(async () => {
    if (!refId) return;
    setRebuilding(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/normalized-refs/${encodeURIComponent(refId)}/knowledge-outline/rebuild`,
        { method: "POST", cache: "no-store" },
      );
      const body = (await res.json()) as ApiEnvelope<KnowledgeOutlineTree>;
      if (!res.ok || body.error) {
        throw new Error(body.error?.message || `HTTP ${res.status}`);
      }
      setTree(body.data ?? null);
      antdMessage.success("知识点大纲已重建");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      antdMessage.error(`重建失败：${msg}`);
    } finally {
      setRebuilding(false);
    }
  }, [refId]);

  const handleRebuildClick = useCallback(() => {
    Modal.confirm({
      title: "重建知识点大纲？",
      content: "将替换当前大纲。同步执行，通常几秒内完成。",
      okText: "重建",
      cancelText: "取消",
      onOk: rebuild,
    });
  }, [rebuild]);

  const openDrawer = useCallback(async (nodeId: string) => {
    setDrawerNodeId(nodeId);
    setDrawerLoading(true);
    setDrawerChunks(null);
    try {
      const res = await fetch(
        `/api/knowledge-outline-nodes/${encodeURIComponent(nodeId)}/chunks?limit=${DRAWER_CHUNK_LIMIT}`,
        { cache: "no-store" },
      );
      const body = (await res.json()) as ApiEnvelope<KnowledgeOutlineChunkPage>;
      if (!res.ok || body.error) {
        throw new Error(body.error?.message || `HTTP ${res.status}`);
      }
      setDrawerChunks(body.data ?? null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      antdMessage.error(`加载节点内容失败：${msg}`);
    } finally {
      setDrawerLoading(false);
    }
  }, []);

  const rootTreeItems = useMemo(() => buildTreeItems(tree), [tree]);
  const chartOption = useMemo(() => buildChartOption(rootTreeItems), [rootTreeItems]);
  const antdTreeData = useMemo(() => rootTreeItems.map(toAntdTreeNode), [rootTreeItems]);

  const handleDownload = useCallback(
    async (currentTree: KnowledgeOutlineTree) => {
      const baseName = currentTree.nodes.find((n) => n.id === currentTree.root_id)
        ?.title || "知识点大纲";
      if (viewMode === "radial") {
        await downloadEchartsGraphImage({
          option: chartOption,
          filename: `${baseName}-径向图.png`,
          nodeCount: currentTree.total_nodes,
        });
      } else {
        downloadMarkdownFile(
          `${baseName}.md`,
          outlineTreeToMarkdown(currentTree),
        );
      }
    },
    [chartOption, viewMode],
  );
  const drawerNode = useMemo(() => {
    if (!drawerNodeId || !tree) return null;
    return tree.nodes.find((n) => n.id === drawerNodeId) ?? null;
  }, [drawerNodeId, tree]);
  const drawerNodeTitle = drawerNode?.title ?? null;
  // Prefer the node's own anchor (leaf-only). Fall back to first chunk's
  // origin block so non-leaf nodes still land somewhere useful.
  const jumpBlockId = useMemo(() => {
    const nodeAnchor = drawerNode?.anchor_range?.block_ids?.[0];
    if (nodeAnchor) return nodeAnchor;
    return drawerChunks?.chunks[0]?.source_block_ids?.[0] ?? null;
  }, [drawerNode, drawerChunks]);

  if (!refId) {
    return (
      <Card className="!mt-4" title="知识点大纲">
        <Alert type="info" showIcon title="该资产尚无标准化引用，暂无知识点大纲。" />
      </Card>
    );
  }

  return (
    <>
      <Card
        className="!mt-4"
        title={
          <Space wrap>
            <span>知识点大纲</span>
            {tree?.fallback_used ? <Tag color="warning">未识别标题，已回退为单节点</Tag> : null}
            {tree ? <Tag>{tree.total_nodes} 节点</Tag> : null}
            {tree && tree.max_depth > 0 ? <Tag>{tree.max_depth} 级深度</Tag> : null}
            {pendingReviewCount > 0 ? (
              <Tag color="warning" title="SME 待审的 LLM 分类项">
                {pendingReviewCount} 项待审
              </Tag>
            ) : null}
          </Space>
        }
        extra={
          <Space>
            <Segmented
              value={viewMode}
              onChange={(value) => setViewMode(value as ViewMode)}
              options={[
                { label: "径向", value: "radial" },
                { label: "树", value: "tree" },
              ]}
              aria-label="切换知识点大纲视图"
            />
            {tree && tree.total_nodes > 1 ? (
              <GraphViewportActions
                title={viewMode === "radial" ? "知识点大纲径向图" : "知识点大纲树"}
                disabled={tree.total_nodes <= 1}
                downloadLabel={
                  viewMode === "radial" ? "下载知识点大纲 PNG" : "下载知识点大纲 Markdown"
                }
                downloadAriaLabel={
                  viewMode === "radial"
                    ? "下载知识点大纲径向图"
                    : "下载知识点大纲树 Markdown"
                }
                onDownload={() => handleDownload(tree)}
                immersive={viewMode === "radial"}
              >
                {viewMode === "radial" ? (
                  <RadialChart
                    option={chartOption}
                    nodeCount={tree.total_nodes}
                    onNodeClick={openDrawer}
                    fullscreen
                  />
                ) : (
                  <TreeViewInner
                    tree={tree}
                    antdTreeData={antdTreeData}
                    onNodeSelect={openDrawer}
                    fullscreen
                  />
                )}
              </GraphViewportActions>
            ) : null}
            <Button onClick={handleRebuildClick} loading={rebuilding}>
              重建
            </Button>
          </Space>
        }
      >
        {error ? <Alert type="error" showIcon className="!mb-3" title={error} /> : null}
        {loading && tree === null ? (
          <Skeleton active paragraph={{ rows: 6 }} />
        ) : !tree ? (
          <Empty description="暂无知识点大纲" />
        ) : viewMode === "radial" ? (
          <RadialChart
            option={chartOption}
            nodeCount={tree.total_nodes}
            onNodeClick={openDrawer}
          />
        ) : (
          <TreeViewInner
            tree={tree}
            antdTreeData={antdTreeData}
            onNodeSelect={openDrawer}
          />
        )}
      </Card>

      <Drawer
        open={drawerNodeId !== null}
        onClose={() => setDrawerNodeId(null)}
        title={drawerNodeTitle ?? "节点内容"}
        width={520}
        destroyOnClose
        extra={
          onJumpToBlock && jumpBlockId ? (
            <Button
              type="link"
              onClick={() => {
                onJumpToBlock(jumpBlockId);
                setDrawerNodeId(null);
              }}
            >
              跳到原文
            </Button>
          ) : null
        }
      >
        {drawerLoading ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : !drawerChunks || drawerChunks.chunks.length === 0 ? (
          <Empty description="该节点下暂无知识块" />
        ) : (
          <List dataSource={drawerChunks.chunks} renderItem={renderChunkItem} />
        )}
      </Drawer>
    </>
  );
}

// ---------------------------------------------------------------------------
// Radial chart
// ---------------------------------------------------------------------------

type RadialChartProps = {
  option: EChartsOption;
  nodeCount: number;
  onNodeClick: (nodeId: string) => void;
  fullscreen?: boolean;
};

function RadialChart({ option, onNodeClick, fullscreen = false }: RadialChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ECharts | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;
    const container = containerRef.current;

    import("echarts").then((echarts) => {
      if (disposed) return;
      const chart = echarts.init(container);
      chartRef.current = chart;
      chart.setOption(option);
      chart.on("click", (params) => {
        // ECharts tree series click passes the node's raw data at params.data;
        // our ChartTreeNode nests the outline id at data.data.id.
        const data = (params as { data?: { data?: { id?: unknown } } }).data;
        const id = data?.data?.id;
        if (typeof id === "string") onNodeClick(id);
      });
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
      chartRef.current?.dispose();
      chartRef.current = null;
    };
    // Intentionally omit `onNodeClick` — the click handler is bound once
    // per chart lifecycle and reads the latest closure via ref-free capture
    // through the initial option; consumers pass a stable callback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [option]);

  const heightClass = fullscreen ? CHART_HEIGHT_FULLSCREEN : CHART_HEIGHT_INLINE;
  return (
    <div className={`border-line bg-bg-subtle w-full rounded border ${heightClass}`}>
      <div ref={containerRef} className="h-full w-full" />
    </div>
  );
}


// ---------------------------------------------------------------------------
// Tree view (Antd Tree) — shares maximize/download plumbing with the radial
// chart via the Card `extra` toolbar.
// ---------------------------------------------------------------------------

type TreeViewInnerProps = {
  tree: KnowledgeOutlineTree;
  antdTreeData: DataNode[];
  onNodeSelect: (nodeId: string) => void;
  fullscreen?: boolean;
};

function TreeViewInner({
  tree,
  antdTreeData,
  onNodeSelect,
  fullscreen = false,
}: TreeViewInnerProps) {
  const heightClass = fullscreen ? TREE_HEIGHT_FULLSCREEN : TREE_HEIGHT_INLINE;
  return (
    <div
      className={`border-line bg-bg-subtle rounded border px-4 py-3 ${heightClass}`}
    >
      <Tree
        treeData={antdTreeData}
        defaultExpandAll
        showLine
        blockNode
        onSelect={(keys) => {
          const key = keys[0];
          if (typeof key === "string" && key !== tree.root_id) {
            onNodeSelect(key);
          }
        }}
        aria-label="知识点大纲树"
      />
    </div>
  );
}


// ---------------------------------------------------------------------------
// Markdown export
// ---------------------------------------------------------------------------

function outlineTreeToMarkdown(tree: KnowledgeOutlineTree): string {
  const byParent = new Map<string | null, KnowledgeOutlineNode[]>();
  for (const node of tree.nodes) {
    const list = byParent.get(node.parent_id) ?? [];
    list.push(node);
    byParent.set(node.parent_id, list);
  }
  for (const list of byParent.values()) {
    list.sort((a, b) => a.order_index - b.order_index);
  }
  const lines: string[] = [];
  const walk = (parentId: string | null, depth: number) => {
    for (const node of byParent.get(parentId) ?? []) {
      const hashes = "#".repeat(Math.min(depth, 6));
      const label = node.numbering ? `${node.numbering} ${node.title}` : node.title;
      lines.push(`${hashes} ${label}`);
      walk(node.id, depth + 1);
    }
  };
  walk(null, 1);
  return `${lines.join("\n")}\n`;
}

function downloadMarkdownFile(filename: string, content: string): boolean {
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

// ---------------------------------------------------------------------------
// Chart / tree data builders
// ---------------------------------------------------------------------------

function buildTreeItems(tree: KnowledgeOutlineTree | null): TreeItem[] {
  if (!tree) return [];
  const byParent = new Map<string | null, KnowledgeOutlineNode[]>();
  for (const node of tree.nodes) {
    const list = byParent.get(node.parent_id) ?? [];
    list.push(node);
    byParent.set(node.parent_id, list);
  }
  for (const list of byParent.values()) {
    list.sort((a, b) => a.order_index - b.order_index);
  }

  const build = (parentId: string | null): TreeItem[] =>
    (byParent.get(parentId) ?? []).map((node) => ({
      key: node.id,
      node,
      children: build(node.id),
    }));

  return build(null);
}

function toChartTree(item: TreeItem): ChartTreeNode {
  const label = item.node.numbering ? `${item.node.numbering} ${item.node.title}` : item.node.title;
  return {
    name: label,
    value: item.node.id,
    data: {
      id: item.node.id,
      title: item.node.title,
      numbering: item.node.numbering,
      chunkCount: item.node.chunk_count,
    },
    children: item.children.length ? item.children.map(toChartTree) : undefined,
  };
}

function buildChartOption(roots: TreeItem[]): EChartsOption {
  const chartRoots = roots.map(toChartTree);
  const singleRoot: ChartTreeNode =
    chartRoots.length === 1
      ? chartRoots[0]
      : {
          name: "知识点大纲",
          value: "synthetic-root",
          data: { id: "synthetic-root", title: "知识点大纲", numbering: null, chunkCount: 0 },
          children: chartRoots,
        };

  return {
    tooltip: {
      trigger: "item",
      formatter: (params) => {
        const item = Array.isArray(params) ? params[0] : params;
        const data = (item as { data?: ChartTreeNode }).data;
        const chunk = data?.data?.chunkCount ? `<br/>${data.data.chunkCount} 知识块` : "";
        return `${escapeHtml(data?.name ?? "")}${chunk}`;
      },
    },
    series: [
      {
        type: "tree",
        data: [singleRoot],
        layout: "radial",
        top: 24,
        bottom: 24,
        left: 24,
        right: 24,
        symbol: "circle",
        symbolSize: 8,
        initialTreeDepth: 3,
        roam: true,
        expandAndCollapse: true,
        animationDuration: 300,
        animationDurationUpdate: 450,
        label: {
          position: "right",
          rotate: 0,
          fontSize: 11,
          overflow: "truncate",
          width: 140,
        },
        leaves: {
          label: {
            position: "right",
            rotate: 0,
            fontSize: 11,
            overflow: "truncate",
            width: 140,
          },
        },
        itemStyle: { color: "#2563eb" },
        lineStyle: { color: "#94a3b8", width: 1 },
        emphasis: { focus: "descendant" },
      },
    ],
  };
}

function toAntdTreeNode(item: TreeItem): DataNode {
  const label = item.node.numbering ? `${item.node.numbering} ${item.node.title}` : item.node.title;
  return {
    key: item.key,
    title: (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <Typography.Text strong>{label}</Typography.Text>
        {item.node.chunk_count > 0 ? <Tag className="!m-0">{item.node.chunk_count} 块</Tag> : null}
      </span>
    ),
    children: item.children.map(toAntdTreeNode),
  };
}

function renderChunkItem(chunk: KnowledgeOutlineChunkListEntry) {
  return (
    <List.Item key={chunk.id}>
      <div className="w-full">
        <div className="text-text-secondary mb-1 text-xs">
          #{chunk.chunk_index} · {chunk.source_block_ids.length} blocks
        </div>
        <div className="text-sm leading-6 whitespace-pre-wrap">
          {chunk.content_preview || "（无内容）"}
        </div>
      </div>
    </List.Item>
  );
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

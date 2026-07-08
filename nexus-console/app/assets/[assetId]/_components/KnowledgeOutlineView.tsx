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

type Props = {
  refId: string | null;
  isTheoryKnowledge: boolean;
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

const CHART_HEIGHT_CLASS = "h-[560px] min-h-[420px]";
const DRAWER_CHUNK_LIMIT = 50;

export function KnowledgeOutlineView({ refId, isTheoryKnowledge }: Props) {
  const [tree, setTree] = useState<KnowledgeOutlineTree | null>(null);
  const [loading, setLoading] = useState(false);
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
  const drawerNodeTitle = useMemo(() => {
    if (!drawerNodeId || !tree) return null;
    return tree.nodes.find((n) => n.id === drawerNodeId)?.title ?? null;
  }, [drawerNodeId, tree]);

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
          <RadialChart option={chartOption} nodeCount={tree.total_nodes} onNodeClick={openDrawer} />
        ) : (
          <div className="border-line bg-bg-subtle rounded border px-4 py-3">
            <Tree
              treeData={antdTreeData}
              defaultExpandAll
              showLine
              blockNode
              onSelect={(keys) => {
                const key = keys[0];
                if (typeof key === "string" && key !== tree.root_id) {
                  openDrawer(key);
                }
              }}
              aria-label="知识点大纲树"
            />
          </div>
        )}
      </Card>

      <Drawer
        open={drawerNodeId !== null}
        onClose={() => setDrawerNodeId(null)}
        title={drawerNodeTitle ?? "节点内容"}
        width={520}
        destroyOnClose
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
};

function RadialChart({ option, onNodeClick }: RadialChartProps) {
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

  return (
    <div className={`border-line bg-bg-subtle w-full rounded border ${CHART_HEIGHT_CLASS}`}>
      <div ref={containerRef} className="h-full w-full" />
    </div>
  );
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

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
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Drawer,
  Empty,
  Input,
  List,
  Skeleton,
  Space,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import { Network, RefreshCw, Search } from "lucide-react";
import type { ECharts, EChartsOption } from "echarts";

import {
  downloadEchartsGraphImage,
  GraphViewportActions,
  type GraphImageHandle,
} from "./GraphViewportActions";
import {
  getApiData,
  postApiData,
  type KnowledgeGraphBuild,
  type KnowledgeGraphEdge,
  type KnowledgeGraphEvidence,
  type KnowledgeGraphFact,
  type KnowledgeGraphLatestSummary,
  type KnowledgeGraphNode,
  type NormalizedAssetRef,
} from "@/lib/api";
import type { KnowledgeChunkHit } from "@/lib/chunkTypes";
import type { LocatorInfo } from "@/lib/chunkTypes";
import { ChunkPreviewDrawer } from "@/components/chunk/ChunkPreviewDrawer";
import { LocatorChip } from "@/components/chunk/LocatorChip";

type Props = {
  normalizedRef: NormalizedAssetRef | null;
};

type GraphState = {
  loading: boolean;
  build: KnowledgeGraphBuild | null;
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
  facts: KnowledgeGraphFact[];
  evidence: KnowledgeGraphEvidence[];
  totals: {
    nodes: number;
    edges: number;
    facts: number;
    evidence: number;
  };
  error: string | null;
};

type SelectedGraphItem =
  | { kind: "node"; item: KnowledgeGraphNode }
  | { kind: "edge"; item: KnowledgeGraphEdge }
  | { kind: "fact"; item: KnowledgeGraphFact }
  | null;

type GraphNodeDatum = {
  id: string;
  name: string;
  fullName: string;
  nodeType: string;
  confidence: number | null;
  category: number;
  symbolSize: number;
  itemStyle?: {
    borderColor?: string;
    borderWidth?: number;
  };
};

type GraphEdgeDatum = {
  id: string;
  source: string;
  target: string;
  relationType: string;
  confidence: number | null;
};

const STRATEGY_VERSION = "evidence_kg.v1";
const PAGE_SIZE = 200;
const MAX_GRAPH_ROWS = 1600;

const NODE_LABELS: Record<string, string> = {
  Organization: "组织",
  Policy: "政策",
  Report: "报告",
  Standard: "标准",
  Course: "课程",
  Book: "教材/书籍",
  Sop: "SOP",
  Metric: "指标",
  MetricValue: "指标值",
  Concept: "概念",
  Event: "事件",
  Person: "人员",
  Location: "地点",
  Unknown: "实体",
};

const NODE_COLORS = [
  "#2563eb",
  "#0d9488",
  "#d97706",
  "#7c3aed",
  "#dc2626",
  "#0284c7",
  "#16a34a",
  "#db2777",
  "#64748b",
];

export function EvidenceGraphView({ normalizedRef }: Props) {
  const normalizedRefId = normalizedRef?.id ?? null;
  const graphProfile = resolveGraphProfile(normalizedRef);
  const [state, setState] = useState<GraphState>({
    loading: Boolean(normalizedRefId),
    build: null,
    nodes: [],
    edges: [],
    facts: [],
    evidence: [],
    totals: { nodes: 0, edges: 0, facts: 0, evidence: 0 },
    error: null,
  });
  const [query, setQuery] = useState("");
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);
  const [selectedItem, setSelectedItem] = useState<SelectedGraphItem>(null);
  const [chunkPreview, setChunkPreview] = useState<KnowledgeChunkHit | null>(null);
  const [chunkDrawerOpen, setChunkDrawerOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const graphRef = useRef<GraphImageHandle | null>(null);

  const load = useCallback(async () => {
    if (!normalizedRefId) {
      setState({
        loading: false,
        build: null,
        nodes: [],
        edges: [],
        facts: [],
        evidence: [],
        totals: { nodes: 0, edges: 0, facts: 0, evidence: 0 },
        error: null,
      });
      return;
    }

    setState((prev) => ({ ...prev, loading: true, error: null }));
    const summary = await getApiData<KnowledgeGraphLatestSummary>(
      `/api/evidence-graphs/normalized-refs/${normalizedRefId}`,
      { build: null },
      { graph_profile: graphProfile, strategy_version: STRATEGY_VERSION },
    );
    if (!summary.ok) {
      setState({
        loading: false,
        build: null,
        nodes: [],
        edges: [],
        facts: [],
        evidence: [],
        totals: { nodes: 0, edges: 0, facts: 0, evidence: 0 },
        error: summary.error,
      });
      return;
    }

    const build = summary.data.build;
    if (!build) {
      setState({
        loading: false,
        build: null,
        nodes: [],
        edges: [],
        facts: [],
        evidence: [],
        totals: { nodes: 0, edges: 0, facts: 0, evidence: 0 },
        error: null,
      });
      return;
    }

    const [nodesRes, edgesRes, factsRes, evidenceRes] = await Promise.all([
      fetchPagedItems<KnowledgeGraphNode>(`/api/evidence-graphs/builds/${build.id}/nodes`),
      fetchPagedItems<KnowledgeGraphEdge>(`/api/evidence-graphs/builds/${build.id}/edges`),
      fetchPagedItems<KnowledgeGraphFact>(`/api/evidence-graphs/builds/${build.id}/facts`),
      fetchPagedItems<KnowledgeGraphEvidence>(`/api/evidence-graphs/builds/${build.id}/evidence`),
    ]);

    const error = [nodesRes, edgesRes, factsRes, evidenceRes].find((res) => !res.ok)?.error ?? null;
    setState({
      loading: false,
      build,
      nodes: normalizeNodes(nodesRes.data),
      edges: normalizeEdges(edgesRes.data),
      facts: normalizeFacts(factsRes.data),
      evidence: normalizeEvidence(evidenceRes.data),
      totals: {
        nodes: nodesRes.total,
        edges: edgesRes.total,
        facts: factsRes.total,
        evidence: evidenceRes.total,
      },
      error,
    });
  }, [graphProfile, normalizedRefId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setQuery("");
    setSelectedItem(null);
  }, [normalizedRefId]);

  const nodeById = useMemo(
    () => new Map(state.nodes.map((node) => [node.id, node])),
    [state.nodes],
  );

  const filteredGraph = useMemo(
    () => filterGraph(state.nodes, state.edges, nodeById, query),
    [nodeById, query, state.edges, state.nodes],
  );

  const evidenceByTarget = useMemo(() => groupEvidence(state.evidence), [state.evidence]);
  const selectedEvidence = useMemo(
    () => (selectedItem ? evidenceForSelection(selectedItem, evidenceByTarget) : []),
    [evidenceByTarget, selectedItem],
  );

  const isTruncated =
    state.nodes.length < state.totals.nodes ||
    state.edges.length < state.totals.edges ||
    state.facts.length < state.totals.facts ||
    state.evidence.length < state.totals.evidence;

  const submitBuild = useCallback(async () => {
    if (!normalizedRefId) return;
    setSubmitting(true);
    try {
      const result = await postApiData<{ skipped?: boolean; build?: KnowledgeGraphBuild }>(
        "/api/evidence-graphs/builds",
        {
          normalized_ref_id: normalizedRefId,
          graph_profile: graphProfile,
          strategy_version: STRATEGY_VERSION,
          force: false,
          dry_run: false,
        },
      );
      const skipped = result.data?.skipped;
      message.success(skipped ? "已有成功图谱构建" : "已提交图谱构建信封");
      await load();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交图谱构建失败");
    } finally {
      setSubmitting(false);
    }
  }, [graphProfile, load, normalizedRefId]);

  const openEvidenceChunk = useCallback((evidence: KnowledgeGraphEvidence) => {
    setChunkPreview(evidenceToChunkHit(evidence));
    setChunkDrawerOpen(true);
  }, []);

  if (!normalizedRefId) {
    return (
      <Card title="Evidence Graph">
        <Alert type="info" showIcon title="该资产尚无标准化引用，暂无可构建的 Evidence Graph。" />
      </Card>
    );
  }

  return (
    <>
      <Card
        title={
          <span className="inline-flex items-center gap-2">
            <Network size={16} />
            Evidence Graph
            <Tag className="!mr-0 !ml-1">{graphProfile}</Tag>
          </span>
        }
        extra={
          state.build ? (
            <div className="flex items-center gap-2">
              <Tag color={statusColor(state.build.status)} className="!mr-0">
                {state.build.status}
              </Tag>
              <GraphViewportActions
                title="Evidence Graph"
                disabled={filteredGraph.nodes.length === 0}
                onDownload={() => graphRef.current?.downloadImage("Evidence Graph.png")}
              >
                <EvidenceEchartsGraph
                  nodes={filteredGraph.nodes}
                  edges={filteredGraph.edges}
                  showEdgeLabels={showEdgeLabels}
                  searchQuery={query}
                  onSelect={setSelectedItem}
                  fullscreen
                />
              </GraphViewportActions>
            </div>
          ) : null
        }
      >
        {state.loading ? <Skeleton active paragraph={{ rows: 8 }} /> : null}
        {state.error ? (
          <Alert type="error" showIcon title="加载 Evidence Graph 失败" description={state.error} />
        ) : null}

        {!state.loading && !state.error && !state.build ? (
          <Empty description="尚未生成 Evidence Graph build" image={Empty.PRESENTED_IMAGE_SIMPLE}>
            <Button
              type="primary"
              icon={<RefreshCw size={16} aria-hidden="true" />}
              loading={submitting}
              onClick={submitBuild}
            >
              构建图谱
            </Button>
          </Empty>
        ) : null}

        {!state.loading && !state.error && state.build ? (
          <div className="flex flex-col gap-4">
            <BuildSummary
              build={state.build}
              totals={state.totals}
              onRefresh={load}
              refreshing={state.loading}
            />

            {isTruncated ? (
              <Alert
                type="warning"
                showIcon
                title={`当前最多加载 ${MAX_GRAPH_ROWS} 行：节点 ${state.nodes.length}/${state.totals.nodes}、边 ${state.edges.length}/${state.totals.edges}、事实 ${state.facts.length}/${state.totals.facts}、证据 ${state.evidence.length}/${state.totals.evidence}。`}
              />
            ) : null}

            <GraphToolbar
              query={query}
              onQueryChange={setQuery}
              showEdgeLabels={showEdgeLabels}
              onShowEdgeLabelsChange={setShowEdgeLabels}
            />

            {filteredGraph.nodes.length === 0 ? (
              <Empty description="当前筛选条件下无图谱节点" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <EvidenceEchartsGraph
                ref={graphRef}
                nodes={filteredGraph.nodes}
                edges={filteredGraph.edges}
                showEdgeLabels={showEdgeLabels}
                searchQuery={query}
                onSelect={setSelectedItem}
              />
            )}

            <FactList
              facts={state.facts}
              nodeById={nodeById}
              onSelect={(fact) => setSelectedItem({ kind: "fact", item: fact })}
            />
          </div>
        ) : null}
      </Card>

      <GraphDetailDrawer
        selected={selectedItem}
        nodeById={nodeById}
        evidence={selectedEvidence}
        onEvidenceOpen={openEvidenceChunk}
        onClose={() => setSelectedItem(null)}
      />
      <ChunkPreviewDrawer
        chunk={chunkPreview}
        open={chunkDrawerOpen}
        onClose={() => setChunkDrawerOpen(false)}
      />
    </>
  );
}

function BuildSummary({
  build,
  totals,
  onRefresh,
  refreshing,
}: {
  build: KnowledgeGraphBuild;
  totals: GraphState["totals"];
  onRefresh: () => void;
  refreshing: boolean;
}) {
  return (
    <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
      <div className="flex flex-wrap gap-2">
        <Tag color="blue">profile {build.graph_profile}</Tag>
        <Tag>strategy {build.strategy_version}</Tag>
        <Tag>chunks {build.source_chunk_count}</Tag>
        <Tag>candidate {build.candidate_count}</Tag>
        <Tag>节点 {totals.nodes}</Tag>
        <Tag>边 {totals.edges}</Tag>
        <Tag>事实 {totals.facts}</Tag>
        <Tag>证据 {totals.evidence}</Tag>
      </div>
      <Button
        icon={<RefreshCw size={16} aria-hidden="true" />}
        loading={refreshing}
        onClick={onRefresh}
      >
        刷新构建状态
      </Button>
    </div>
  );
}

function GraphToolbar({
  query,
  onQueryChange,
  showEdgeLabels,
  onShowEdgeLabelsChange,
}: {
  query: string;
  onQueryChange: (value: string) => void;
  showEdgeLabels: boolean;
  onShowEdgeLabelsChange: (value: boolean) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-2 lg:grid-cols-[minmax(220px,1fr)_auto]">
      <Input
        allowClear
        prefix={<Search size={16} aria-hidden="true" />}
        placeholder="搜索节点、关系或事实"
        value={query}
        onChange={(event) => onQueryChange(event.target.value)}
        aria-label="搜索 Evidence Graph"
      />
      <Checkbox
        checked={showEdgeLabels}
        onChange={(event) => onShowEdgeLabelsChange(event.target.checked)}
        className="self-center"
      >
        显示边标签
      </Checkbox>
    </div>
  );
}

function FactList({
  facts,
  nodeById,
  onSelect,
}: {
  facts: KnowledgeGraphFact[];
  nodeById: Map<string, KnowledgeGraphNode>;
  onSelect: (fact: KnowledgeGraphFact) => void;
}) {
  if (facts.length === 0) return null;
  return (
    <div className="rounded-md border border-[var(--line)]">
      <div className="border-0 border-b border-solid border-[var(--line)] px-3 py-2 text-sm font-semibold">
        事实列表
      </div>
      <List
        size="small"
        dataSource={facts.slice(0, 80)}
        renderItem={(fact) => (
          <List.Item
            className="cursor-pointer"
            onClick={() => onSelect(fact)}
            actions={[
              fact.confidence != null ? (
                <Tag key="confidence">{(fact.confidence * 100).toFixed(0)}%</Tag>
              ) : null,
            ]}
          >
            <List.Item.Meta
              title={formatFact(fact, nodeById)}
              description={`${fact.fact_type} · ${fact.predicate}`}
            />
          </List.Item>
        )}
      />
    </div>
  );
}

const EvidenceEchartsGraph = forwardRef<
  GraphImageHandle,
  {
    nodes: KnowledgeGraphNode[];
    edges: KnowledgeGraphEdge[];
    showEdgeLabels: boolean;
    searchQuery: string;
    onSelect: (item: Exclude<SelectedGraphItem, null>) => void;
    fullscreen?: boolean;
  }
>(function EvidenceEchartsGraph(
  { nodes, edges, showEdgeLabels, searchQuery, onSelect, fullscreen = false },
  forwardedRef,
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const instanceRef = useRef<ECharts | null>(null);
  const nodeRef = useRef(nodes);
  const edgeRef = useRef(edges);
  const option = useMemo(
    () => buildGraphOption(nodes, edges, showEdgeLabels, searchQuery),
    [edges, nodes, searchQuery, showEdgeLabels],
  );

  useEffect(() => {
    nodeRef.current = nodes;
    edgeRef.current = edges;
  }, [edges, nodes]);

  useImperativeHandle(
    forwardedRef,
    () => ({
      downloadImage: (filename: string) =>
        downloadEchartsGraphImage({ option, filename, nodeCount: nodes.length }),
    }),
    [nodes.length, option],
  );

  useEffect(() => {
    if (nodes.length === 0 || !containerRef.current) return;
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;
    const container = containerRef.current;

    import("echarts").then((echarts) => {
      if (disposed) return;
      const chart = echarts.init(container);
      instanceRef.current = chart;
      chart.setOption(option);
      chart.on("click", (params) => {
        if (!params.data || Array.isArray(params.data) || typeof params.data !== "object") return;
        const data = params.data as { id?: string };
        if (!data.id) return;
        if (params.dataType === "edge") {
          const edge = edgeRef.current.find((item) => item.id === data.id);
          if (edge) onSelect({ kind: "edge", item: edge });
          return;
        }
        const node = nodeRef.current.find((item) => item.id === data.id);
        if (node) onSelect({ kind: "node", item: node });
      });
      requestAnimationFrame(() => {
        if (!disposed && !chart.isDisposed()) chart.resize();
      });
      resizeObserver = new ResizeObserver(() => {
        if (disposed || chart.isDisposed()) return;
        requestAnimationFrame(() => {
          if (!disposed && !chart.isDisposed()) chart.resize();
        });
      });
      resizeObserver.observe(container);
    });

    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      instanceRef.current?.dispose();
      instanceRef.current = null;
    };
  }, [nodes.length, onSelect]);

  useEffect(() => {
    instanceRef.current?.setOption(option, true);
  }, [option]);

  return (
    <div
      ref={containerRef}
      className={`border-line bg-surface-alt w-full rounded-md border ${
        fullscreen ? "h-full min-h-[520px]" : "h-[620px] min-h-[420px]"
      }`}
      role="img"
      aria-label="Evidence Graph 可视化画布"
    />
  );
});

function buildGraphOption(
  nodes: KnowledgeGraphNode[],
  edges: KnowledgeGraphEdge[],
  showEdgeLabels: boolean,
  searchQuery: string,
): EChartsOption {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const drawableEdges = edges.filter(
    (edge) => nodeIds.has(edge.source_node_id) && nodeIds.has(edge.target_node_id),
  );
  const typeKeys = Array.from(new Set(nodes.map((node) => node.node_type || "Unknown")));
  const categoryIndex = new Map(typeKeys.map((key, index) => [key, index]));
  const degree = new Map<string, number>();
  for (const edge of drawableEdges) {
    degree.set(edge.source_node_id, (degree.get(edge.source_node_id) ?? 0) + 1);
    degree.set(edge.target_node_id, (degree.get(edge.target_node_id) ?? 0) + 1);
  }
  const q = searchQuery.trim().toLowerCase();

  return {
    animationDurationUpdate: 350,
    tooltip: {
      trigger: "item",
      confine: true,
      formatter: (params) => {
        if (Array.isArray(params)) return "";
        const data = params.data as Partial<GraphNodeDatum & GraphEdgeDatum> | null;
        if (!data) return "";
        if (params.dataType === "edge") {
          return `${data.relationType ?? "关系"}${formatConfidence(data.confidence)}`;
        }
        return `${data.fullName ?? data.name ?? ""}<br/>${NODE_LABELS[data.nodeType ?? ""] ?? data.nodeType ?? "实体"}${formatConfidence(data.confidence)}`;
      },
    },
    legend: {
      top: 0,
      type: "scroll",
    },
    series: [
      {
        type: "graph",
        layout: "force",
        top: 38,
        roam: true,
        draggable: true,
        categories: typeKeys.map((key, index) => ({
          name: NODE_LABELS[key] ?? key,
          itemStyle: { color: NODE_COLORS[index % NODE_COLORS.length] },
        })),
        force: {
          repulsion: 280,
          edgeLength: [80, 190],
          gravity: 0.08,
        },
        label: {
          show: true,
          position: "right",
          formatter: "{b}",
          fontSize: 11,
        },
        edgeLabel: {
          show: showEdgeLabels,
          formatter: (params) => {
            const data = params.data as { relationType?: string };
            return data.relationType ?? "";
          },
          fontSize: 10,
        },
        lineStyle: {
          color: "source",
          curveness: 0.14,
          opacity: 0.5,
        },
        emphasis: {
          focus: "adjacency",
          lineStyle: { width: 3 },
        },
        data: nodes.map((node) => {
          const matched =
            q &&
            [
              node.name,
              node.node_key,
              node.node_type,
              NODE_LABELS[node.node_type],
              JSON.stringify(node.properties ?? {}),
            ].some((value) => value?.toLowerCase().includes(q));
          return {
            id: node.id,
            name: truncateName(node.name),
            fullName: node.name,
            nodeType: node.node_type,
            confidence: node.confidence,
            category: categoryIndex.get(node.node_type || "Unknown") ?? 0,
            symbolSize: Math.min(24 + (degree.get(node.id) ?? 0) * 2, 54),
            itemStyle: {
              borderColor: matched ? "#c03946" : "#ffffff",
              borderWidth: matched ? 3 : 1,
            },
          } satisfies GraphNodeDatum;
        }),
        links: drawableEdges.map((edge) => ({
          id: edge.id,
          source: edge.source_node_id,
          target: edge.target_node_id,
          relationType: edge.relation_type,
          confidence: edge.confidence,
          lineStyle: {
            type: (edge.confidence ?? 1) < 0.75 ? "dashed" : "solid",
            opacity: Math.max(0.22, Math.min(0.8, edge.confidence ?? 0.55)),
          },
        })),
      },
    ],
  };
}

function GraphDetailDrawer({
  selected,
  nodeById,
  evidence,
  onEvidenceOpen,
  onClose,
}: {
  selected: SelectedGraphItem;
  nodeById: Map<string, KnowledgeGraphNode>;
  evidence: KnowledgeGraphEvidence[];
  onEvidenceOpen: (evidence: KnowledgeGraphEvidence) => void;
  onClose: () => void;
}) {
  const title = selected ? selectionTitle(selected, nodeById) : "图谱详情";
  return (
    <Drawer title={title} open={!!selected} onClose={onClose} size={560} destroyOnHidden>
      {selected ? (
        <div className="flex flex-col gap-4">
          <SelectionSummary selected={selected} nodeById={nodeById} />
          <section>
            <Typography.Text strong>Evidence</Typography.Text>
            {evidence.length === 0 ? (
              <Empty description="该对象暂无 evidence 记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <List
                className="mt-2"
                size="small"
                dataSource={evidence}
                renderItem={(item) => (
                  <List.Item
                    actions={[
                      <Button
                        key="open"
                        type="link"
                        size="small"
                        onClick={() => onEvidenceOpen(item)}
                      >
                        原文定位
                      </Button>,
                    ]}
                  >
                    <List.Item.Meta
                      title={
                        <Space size={6} wrap>
                          <LocatorChip locator={item.locator as LocatorInfo | null | undefined} />
                          {item.confidence != null ? (
                            <Tag>{(item.confidence * 100).toFixed(0)}%</Tag>
                          ) : null}
                          {item.extraction_method ? <Tag>{item.extraction_method}</Tag> : null}
                        </Space>
                      }
                      description={
                        <span className="text-sm whitespace-pre-wrap">{item.evidence_text}</span>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </section>
        </div>
      ) : null}
    </Drawer>
  );
}

function SelectionSummary({
  selected,
  nodeById,
}: {
  selected: Exclude<SelectedGraphItem, null>;
  nodeById: Map<string, KnowledgeGraphNode>;
}) {
  if (selected.kind === "node") {
    const node = selected.item;
    return (
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-2">
          <Tag color="blue">{NODE_LABELS[node.node_type] ?? node.node_type}</Tag>
          {node.confidence != null ? <Tag>{(node.confidence * 100).toFixed(0)}%</Tag> : null}
        </div>
        <DetailRow label="节点 Key" value={node.node_key} />
        <DetailRow label="名称" value={node.name} />
        <JsonBlock title="属性" value={node.properties} />
      </section>
    );
  }
  if (selected.kind === "edge") {
    const edge = selected.item;
    return (
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-2">
          <Tag color="purple">{edge.relation_type}</Tag>
          {edge.confidence != null ? <Tag>{(edge.confidence * 100).toFixed(0)}%</Tag> : null}
        </div>
        <DetailRow
          label="起点"
          value={nodeById.get(edge.source_node_id)?.name ?? edge.source_node_id}
        />
        <DetailRow
          label="终点"
          value={nodeById.get(edge.target_node_id)?.name ?? edge.target_node_id}
        />
        <JsonBlock title="属性" value={edge.properties} />
      </section>
    );
  }
  const fact = selected.item;
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Tag color="green">{fact.fact_type}</Tag>
        <Tag>{fact.predicate}</Tag>
        {fact.confidence != null ? <Tag>{(fact.confidence * 100).toFixed(0)}%</Tag> : null}
      </div>
      <DetailRow label="事实" value={formatFact(fact, nodeById)} />
      <JsonBlock title="限定信息" value={fact.qualifiers} />
    </section>
  );
}

function DetailRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-3 text-sm">
      <span className="text-muted">{label}</span>
      <Tooltip title={value ?? ""}>
        <span className="truncate">{value || "—"}</span>
      </Tooltip>
    </div>
  );
}

function JsonBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <section>
      <Typography.Text strong>{title}</Typography.Text>
      <pre className="border-line bg-surface-alt mt-2 max-h-[260px] overflow-auto rounded-md border p-3 text-xs">
        {JSON.stringify(value ?? {}, null, 2)}
      </pre>
    </section>
  );
}

type PagedResult<T> = {
  ok: boolean;
  data: T[];
  total: number;
  error: string | null;
};

async function fetchPagedItems<T extends { id: string }>(path: string): Promise<PagedResult<T>> {
  const data: T[] = [];
  let total = 0;
  let page = 1;
  while (data.length < MAX_GRAPH_ROWS) {
    const res = await getApiData<T[]>(path, [], {
      page: String(page),
      pageSize: String(PAGE_SIZE),
    });
    if (!res.ok) {
      return {
        ok: false,
        data,
        total: Math.max(total, data.length),
        error: res.error ?? "加载图谱数据失败",
      };
    }
    data.push(...res.data);
    total = res.total ?? data.length;
    if (data.length >= total || res.data.length < PAGE_SIZE) break;
    page += 1;
  }
  return { ok: true, data, total: Math.max(total, data.length), error: null };
}

function filterGraph(
  nodes: KnowledgeGraphNode[],
  edges: KnowledgeGraphEdge[],
  nodeById: Map<string, KnowledgeGraphNode>,
  query: string,
): { nodes: KnowledgeGraphNode[]; edges: KnowledgeGraphEdge[] } {
  const q = query.trim().toLowerCase();
  if (!q) return { nodes, edges };
  const matchedNodeIds = new Set<string>();
  for (const node of nodes) {
    if (
      [node.name, node.node_key, node.node_type, JSON.stringify(node.properties ?? {})].some(
        (value) => (value ?? "").toLowerCase().includes(q),
      )
    ) {
      matchedNodeIds.add(node.id);
    }
  }
  for (const edge of edges) {
    if (
      edge.relation_type.toLowerCase().includes(q) ||
      JSON.stringify(edge.properties ?? {})
        .toLowerCase()
        .includes(q)
    ) {
      matchedNodeIds.add(edge.source_node_id);
      matchedNodeIds.add(edge.target_node_id);
    }
  }
  const filteredNodes = nodes.filter((node) => matchedNodeIds.has(node.id));
  const filteredNodeIds = new Set(filteredNodes.map((node) => node.id));
  const filteredEdges = edges.filter(
    (edge) =>
      filteredNodeIds.has(edge.source_node_id) &&
      filteredNodeIds.has(edge.target_node_id) &&
      (matchedNodeIds.has(edge.source_node_id) ||
        matchedNodeIds.has(edge.target_node_id) ||
        nodeById.has(edge.source_node_id)),
  );
  return { nodes: filteredNodes, edges: filteredEdges };
}

function groupEvidence(evidence: KnowledgeGraphEvidence[]) {
  const byNode = new Map<string, KnowledgeGraphEvidence[]>();
  const byEdge = new Map<string, KnowledgeGraphEvidence[]>();
  const byFact = new Map<string, KnowledgeGraphEvidence[]>();
  for (const item of evidence) {
    if (item.entity_id) pushMap(byNode, item.entity_id, item);
    if (item.edge_id) pushMap(byEdge, item.edge_id, item);
    if (item.fact_id) pushMap(byFact, item.fact_id, item);
  }
  return { byNode, byEdge, byFact };
}

function evidenceForSelection(
  selected: Exclude<SelectedGraphItem, null>,
  grouped: ReturnType<typeof groupEvidence>,
): KnowledgeGraphEvidence[] {
  if (selected.kind === "node") return grouped.byNode.get(selected.item.id) ?? [];
  if (selected.kind === "edge") return grouped.byEdge.get(selected.item.id) ?? [];
  return grouped.byFact.get(selected.item.id) ?? [];
}

function pushMap<K, V>(map: Map<K, V[]>, key: K, value: V) {
  const list = map.get(key);
  if (list) {
    list.push(value);
    return;
  }
  map.set(key, [value]);
}

function evidenceToChunkHit(evidence: KnowledgeGraphEvidence): KnowledgeChunkHit {
  return {
    id: evidence.chunk_id,
    chunk_id: evidence.chunk_id,
    nexus_chunk_id: evidence.chunk_id,
    content: evidence.evidence_text,
    score: evidence.confidence ?? undefined,
    locator: evidence.locator as KnowledgeChunkHit["locator"],
    source_block_ids: evidence.source_block_ids,
    normalized_ref_id: evidence.normalized_ref_id,
    source: {
      normalized_ref_id: evidence.normalized_ref_id,
      page: pageFromLocator(evidence.locator),
    },
  };
}

function pageFromLocator(locator: Record<string, unknown> | null): number | undefined {
  const page = locator?.page_start;
  return typeof page === "number" ? page : undefined;
}

function normalizeNodes(items: KnowledgeGraphNode[]): KnowledgeGraphNode[] {
  return items.filter((item) => item.id && item.node_type && item.name);
}

function normalizeEdges(items: KnowledgeGraphEdge[]): KnowledgeGraphEdge[] {
  return items.filter((item) => item.id && item.source_node_id && item.target_node_id);
}

function normalizeFacts(items: KnowledgeGraphFact[]): KnowledgeGraphFact[] {
  return items.filter((item) => item.id && item.predicate);
}

function normalizeEvidence(items: KnowledgeGraphEvidence[]): KnowledgeGraphEvidence[] {
  return items.filter((item) => item.id && item.chunk_id && item.evidence_text);
}

function selectionTitle(
  selected: Exclude<SelectedGraphItem, null>,
  nodeById: Map<string, KnowledgeGraphNode>,
): string {
  if (selected.kind === "node") return selected.item.name;
  if (selected.kind === "edge") {
    return `${nodeById.get(selected.item.source_node_id)?.name ?? "起点"} -> ${
      nodeById.get(selected.item.target_node_id)?.name ?? "终点"
    }`;
  }
  return formatFact(selected.item, nodeById);
}

function formatFact(fact: KnowledgeGraphFact, nodeById: Map<string, KnowledgeGraphNode>): string {
  const subject = fact.subject_node_id ? nodeById.get(fact.subject_node_id)?.name : null;
  const object = fact.object_node_id
    ? nodeById.get(fact.object_node_id)?.name
    : fact.object_literal;
  return `${subject ?? "主体"} ${fact.predicate} ${object ?? "客体"}`;
}

function truncateName(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= 18) return normalized;
  return `${normalized.slice(0, 17)}...`;
}

function formatConfidence(value?: number | null): string {
  return value == null ? "" : `<br/>置信度 ${(value * 100).toFixed(0)}%`;
}

function statusColor(status: string): string {
  if (status === "succeeded") return "success";
  if (status === "failed") return "error";
  if (status === "deprecated") return "default";
  return "processing";
}

function resolveGraphProfile(ref: NormalizedAssetRef | null): string {
  const meta = ref?.metadata_summary ?? {};
  const explicit =
    stringValue(meta.graph_profile) ??
    stringValue(meta.evidence_graph_profile) ??
    stringValue(ref?.governance?.graph_profile);
  if (explicit) return explicit;

  const classification =
    stringValue(ref?.governance?.classification) ??
    stringValue(ref?.governance?.classification_code) ??
    stringValue(meta.classification) ??
    stringValue(meta.classification_code);
  if (classification === "industry_policy") return "policy_document";
  if (classification === "teaching_standard") return "standard_spec";
  if (classification === "standard_spec") return "standard_spec";
  if (classification === "sop_document") return "sop_document";
  if (classification === "course_textbook" || classification === "textbook") return "textbook";
  return "report_document";
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

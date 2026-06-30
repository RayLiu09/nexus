"use client";

import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import {
  Alert,
  Card,
  Checkbox,
  Drawer,
  Empty,
  Input,
  Skeleton,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { Search } from "lucide-react";
import type { ECharts, EChartsOption } from "echarts";
import {
  downloadEchartsGraphImage,
  GraphViewportActions,
  type GraphImageHandle,
} from "./GraphViewportActions";
import {
  getApiData,
  type CapabilityGraphStagingBuild,
  type CapabilityGraphStagingEdge,
  type CapabilityGraphStagingNode,
} from "@/lib/api";

type BuildType = "job_demand" | "ability_analysis";

type Props = {
  normalizedRefId: string;
  buildType: BuildType;
  title: string;
};

type GraphState = {
  loading: boolean;
  build: CapabilityGraphStagingBuild | null;
  nodes: CapabilityGraphStagingNode[];
  edges: CapabilityGraphStagingEdge[];
  nodesTotal: number;
  edgesTotal: number;
  error: string | null;
};

type GraphDisplayNode = CapabilityGraphStagingNode & {
  synthetic?: boolean;
};

type GraphDisplayEdge = CapabilityGraphStagingEdge & {
  synthetic?: boolean;
};

const GRAPH_PAGE_SIZE = 200;
const MAX_NODES_PER_TYPE = 1200;
const MAX_EDGES_PER_TYPE = 1600;

const NODE_TYPES_BY_BUILD: Record<BuildType, string[]> = {
  job_demand: ["JobRole", "Skill", "ProfessionalLiteracy", "WorkContent"],
  ability_analysis: ["WorkTask", "WorkContent", "Ability"],
};

const EDGE_TYPES_BY_BUILD: Record<BuildType, string[]> = {
  job_demand: [
    "JOB_ROLE_REQUIRES_SKILL",
    "JOB_ROLE_REQUIRES_LITERACY",
    "JOB_ROLE_REQUIRES_WORK_CONTENT",
  ],
  ability_analysis: [
    "TASK_HAS_WORK_CONTENT",
    "TASK_REQUIRES_ABILITY",
    "WORK_CONTENT_REQUIRES_ABILITY",
    "ABILITY_MAPS_TO_SKILL",
    "ABILITY_DERIVED_FROM_JOB_REQUIREMENT",
  ],
};

const NODE_LABELS: Record<string, string> = {
  JobRole: "岗位角色",
  Skill: "职业技能",
  SkillTool: "工具",
  SkillCertificate: "证书",
  ProfessionalLiteracy: "职业素养",
  JobWorkTask: "工作任务",
  JobAggregateSkill: "职业技能",
  JobAggregateLiteracy: "职业素养",
  JobAggregateTask: "工作任务",
  JobAggregateToolCertificate: "工具/证书",
  WorkTask: "工作任务",
  WorkContent: "工作内容",
  Ability: "能力条目",
  AbilityProfessional: "职业能力",
  AbilityGeneral: "通用能力",
  AbilitySocial: "社会能力",
  AbilityDevelopment: "发展能力",
};

const NODE_COLORS: Record<string, string> = {
  JobRole: "#2563eb",
  Skill: "#0d9488",
  SkillTool: "#4f46e5",
  SkillCertificate: "#db2777",
  ProfessionalLiteracy: "#d97706",
  JobWorkTask: "#7c3aed",
  JobAggregateSkill: "#14b8a6",
  JobAggregateLiteracy: "#f59e0b",
  JobAggregateTask: "#8b5cf6",
  JobAggregateToolCertificate: "#6366f1",
  WorkTask: "#2563eb",
  WorkContent: "#8b5cf6",
  Ability: "#64748b",
  AbilityProfessional: "#16a34a",
  AbilityGeneral: "#0284c7",
  AbilitySocial: "#ea580c",
  AbilityDevelopment: "#dc2626",
};

const EDGE_LABELS: Record<string, string> = {
  JOB_ROLE_REQUIRES_SKILL: "岗位要求技能",
  JOB_ROLE_REQUIRES_LITERACY: "岗位要求素养",
  JOB_ROLE_REQUIRES_WORK_CONTENT: "岗位要求工作内容",
  JOB_ROLE_HAS_AGGREGATE: "岗位汇聚分类",
  AGGREGATE_HAS_ITEM: "分类包含条目",
  TASK_HAS_WORK_CONTENT: "任务包含工作内容",
  TASK_REQUIRES_ABILITY: "任务要求能力",
  WORK_CONTENT_REQUIRES_ABILITY: "工作内容要求能力",
  ABILITY_DERIVED_FROM_JOB_REQUIREMENT: "能力来源于岗位需求",
  ABILITY_MAPS_TO_SKILL: "能力映射技能",
};

export function CapabilityGraphView({ normalizedRefId, buildType, title }: Props) {
  const [state, setState] = useState<GraphState>({
    loading: true,
    build: null,
    nodes: [],
    edges: [],
    nodesTotal: 0,
    edgesTotal: 0,
    error: null,
  });
  const [query, setQuery] = useState("");
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);
  const [selectedNode, setSelectedNode] = useState<CapabilityGraphStagingNode | null>(null);
  const graphRef = useRef<GraphImageHandle | null>(null);

  useEffect(() => {
    let active = true;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    getApiData<CapabilityGraphStagingBuild[]>("/api/capability-graph-staging/builds", [], {
      normalized_ref_id: normalizedRefId,
      build_type: buildType,
      pageSize: "1",
    }).then(async (listRes) => {
      if (!active) return;
      if (!listRes.ok) {
        setState({
          loading: false,
          build: null,
          nodes: [],
          edges: [],
          nodesTotal: 0,
          edgesTotal: 0,
          error: listRes.error,
        });
        return;
      }
      const build = listRes.data[0];
      if (!build) {
        setState({
          loading: false,
          build: null,
          nodes: [],
          edges: [],
          nodesTotal: 0,
          edgesTotal: 0,
          error: null,
        });
        return;
      }

      const [nodesRes, edgesRes] = await Promise.all([
        fetchGraphNodes(build.id, buildType),
        fetchGraphEdges(build.id, buildType),
      ]);
      if (!active) return;
      const normalizedNodes = normalizeGraphNodes(nodesRes.data);
      const normalizedEdges = normalizeGraphEdges(
        edgesRes.data,
        new Set(normalizedNodes.map((node) => node.id)),
      );
      setState({
        loading: false,
        build,
        nodes: normalizedNodes,
        edges: normalizedEdges,
        nodesTotal: nodesRes.total,
        edgesTotal: edgesRes.total,
        error:
          nodesRes.ok && edgesRes.ok
            ? null
            : (nodesRes.error ?? edgesRes.error ?? "加载图谱节点或边失败"),
      });
    });
    return () => {
      active = false;
    };
  }, [buildType, normalizedRefId]);

  const nodeTypes = useMemo(
    () => Array.from(new Set(state.nodes.map((node) => graphCategoryKey(node)))),
    [state.nodes],
  );

  useEffect(() => {
    setQuery("");
    setSelectedNode(null);
  }, [buildType, normalizedRefId]);

  const filteredNodes = useMemo(() => {
    const q = query.trim().toLowerCase();
    return state.nodes.filter((node) => {
      const categoryKey = graphCategoryKey(node);
      if (!q) return true;
      return [
        node.display_name,
        node.canonical_name,
        node.node_key,
        node.node_type,
        NODE_LABELS[categoryKey],
      ].some((value) => value?.toLowerCase().includes(q));
    });
  }, [query, state.nodes]);

  const filteredNodeIds = useMemo(
    () => new Set(filteredNodes.map((node) => node.id)),
    [filteredNodes],
  );

  const filteredEdges = useMemo(
    () =>
      state.edges.filter(
        (edge) =>
          filteredNodeIds.has(edge.source_node_id) && filteredNodeIds.has(edge.target_node_id),
      ),
    [filteredNodeIds, state.edges],
  );

  const isTruncated =
    state.nodes.length < state.nodesTotal || state.edges.length < state.edgesTotal;

  return (
    <Card
      title={title}
      size="small"
      extra={
        state.build ? (
          <div className="flex items-center gap-2">
            <Tag color="processing" className="!mr-0">{state.build.status}</Tag>
            <GraphViewportActions
              title={title}
              disabled={filteredNodes.length === 0}
              onDownload={() => graphRef.current?.downloadImage(`${title}.png`)}
            >
              <EchartsGraph
                nodes={filteredNodes}
                edges={filteredEdges}
                buildType={buildType}
                showEdgeLabels={showEdgeLabels}
                searchQuery={query}
                onNodeSelect={setSelectedNode}
                fullscreen
              />
            </GraphViewportActions>
          </div>
        ) : null
      }
    >
      {state.loading ? <Skeleton active paragraph={{ rows: 8 }} /> : null}
      {state.error ? (
        <Alert type="error" showIcon title="加载图谱失败" description={state.error} />
      ) : null}
      {!state.loading && !state.error && !state.build ? (
        <Empty description="尚未生成图谱 staging build" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : null}
      {!state.loading && !state.error && state.build ? (
        <div className="flex flex-col gap-4">
          {isTruncated ? (
            <Alert
              type="warning"
              showIcon
              message={`当前展示前 ${state.nodes.length}/${state.nodesTotal} 个节点、${state.edges.length}/${state.edgesTotal} 条边。`}
            />
          ) : null}

          <GraphToolbar
            query={query}
            onQueryChange={setQuery}
            showEdgeLabels={showEdgeLabels}
            onShowEdgeLabelsChange={setShowEdgeLabels}
          />

          {filteredNodes.length === 0 ? (
            <Empty description="当前筛选条件下无图谱节点" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <EchartsGraph
              ref={graphRef}
              nodes={filteredNodes}
              edges={filteredEdges}
              buildType={buildType}
              showEdgeLabels={showEdgeLabels}
              searchQuery={query}
              onNodeSelect={setSelectedNode}
            />
          )}

          <div className="flex flex-wrap gap-2" aria-label="图谱图例">
            {nodeTypes.map((type) => (
              <Tag key={type} color={tagColor(type)}>
                {NODE_LABELS[type] ?? type}
              </Tag>
            ))}
          </div>
        </div>
      ) : null}

      <NodeDetailDrawer node={selectedNode} onClose={() => setSelectedNode(null)} />
    </Card>
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
        placeholder="搜索节点"
        value={query}
        onChange={(event) => onQueryChange(event.target.value)}
        aria-label="搜索图谱节点"
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

type PagedGraphResult<T> = {
  ok: boolean;
  data: T[];
  total: number;
  error: string | null;
};

async function fetchGraphNodes(
  buildId: string,
  buildType: BuildType,
): Promise<PagedGraphResult<CapabilityGraphStagingNode>> {
  const results = await Promise.all(
    NODE_TYPES_BY_BUILD[buildType].map((nodeType) =>
      fetchPagedGraphItems<CapabilityGraphStagingNode>(
        `/api/capability-graph-staging/builds/${buildId}/nodes`,
        { node_type: nodeType },
        MAX_NODES_PER_TYPE,
      ),
    ),
  );
  return mergePagedGraphResults(results);
}

async function fetchGraphEdges(
  buildId: string,
  buildType: BuildType,
): Promise<PagedGraphResult<CapabilityGraphStagingEdge>> {
  const results = await Promise.all(
    EDGE_TYPES_BY_BUILD[buildType].map((edgeType) =>
      fetchPagedGraphItems<CapabilityGraphStagingEdge>(
        `/api/capability-graph-staging/builds/${buildId}/edges`,
        { edge_type: edgeType },
        MAX_EDGES_PER_TYPE,
      ),
    ),
  );
  return mergePagedGraphResults(results);
}

async function fetchPagedGraphItems<T extends { id: string }>(
  path: string,
  searchParams: Record<string, string>,
  maxItems: number,
): Promise<PagedGraphResult<T>> {
  const data: T[] = [];
  let total = 0;
  let page = 1;

  while (data.length < maxItems) {
    const res = await getApiData<T[]>(path, [], {
      ...searchParams,
      page: String(page),
      pageSize: String(GRAPH_PAGE_SIZE),
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
    if (data.length >= total || res.data.length < GRAPH_PAGE_SIZE) break;
    page += 1;
  }

  return { ok: true, data, total: Math.max(total, data.length), error: null };
}

function mergePagedGraphResults<T extends { id: string }>(
  results: PagedGraphResult<T>[],
): PagedGraphResult<T> {
  const byId = new Map<string, T>();
  let total = 0;
  let error: string | null = null;
  for (const result of results) {
    total += result.total;
    if (!result.ok) error = error ?? result.error ?? "加载图谱数据失败";
    for (const item of result.data) {
      if (!isRecord(item)) continue;
      const id = stringProperty(item.id);
      if (!id) continue;
      byId.set(id, item);
    }
  }
  return {
    ok: error == null,
    data: Array.from(byId.values()),
    total,
    error,
  };
}

function normalizeGraphNodes(items: unknown[]): CapabilityGraphStagingNode[] {
  const nodes: CapabilityGraphStagingNode[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    if (!isRecord(item)) continue;
    const id = stringProperty(item.id);
    const buildId = stringProperty(item.build_id);
    const nodeType = stringProperty(item.node_type);
    const nodeKey = stringProperty(item.node_key);
    if (!id || !buildId || !nodeType || !nodeKey || seen.has(id)) continue;
    seen.add(id);
    nodes.push({
      id,
      build_id: buildId,
      node_type: nodeType,
      node_key: nodeKey,
      display_name: stringProperty(item.display_name) ?? nodeKey,
      canonical_name: stringProperty(item.canonical_name),
      source_table: stringProperty(item.source_table),
      source_id: stringProperty(item.source_id),
      properties: isRecord(item.properties) ? item.properties : {},
      confidence: numberOrNull(item.confidence),
    });
  }
  return nodes;
}

function normalizeGraphEdges(
  items: unknown[],
  validNodeIds: Set<string>,
): CapabilityGraphStagingEdge[] {
  const edges: CapabilityGraphStagingEdge[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    if (!isRecord(item)) continue;
    const id = stringProperty(item.id);
    const buildId = stringProperty(item.build_id);
    const sourceNodeId = stringProperty(item.source_node_id);
    const targetNodeId = stringProperty(item.target_node_id);
    const edgeType = stringProperty(item.edge_type);
    if (
      !id ||
      !buildId ||
      !sourceNodeId ||
      !targetNodeId ||
      !edgeType ||
      seen.has(id) ||
      !validNodeIds.has(sourceNodeId) ||
      !validNodeIds.has(targetNodeId)
    ) {
      continue;
    }
    seen.add(id);
    edges.push({
      id,
      build_id: buildId,
      source_node_id: sourceNodeId,
      target_node_id: targetNodeId,
      edge_type: edgeType,
      source_table: stringProperty(item.source_table),
      source_id: stringProperty(item.source_id),
      evidence: isRecord(item.evidence) ? item.evidence : {},
      confidence: numberOrNull(item.confidence),
    });
  }
  return edges;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

const EchartsGraph = forwardRef<GraphImageHandle, {
  nodes: CapabilityGraphStagingNode[];
  edges: CapabilityGraphStagingEdge[];
  buildType: BuildType;
  showEdgeLabels: boolean;
  searchQuery: string;
  onNodeSelect: (node: GraphDisplayNode) => void;
  fullscreen?: boolean;
}>(function EchartsGraph({
  nodes,
  edges,
  buildType,
  showEdgeLabels,
  searchQuery,
  onNodeSelect,
  fullscreen = false,
}, ref) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const chartInstance = useRef<ECharts | null>(null);
  const displayGraph = useMemo(
    () => buildDisplayGraph(nodes, edges, buildType),
    [buildType, edges, nodes],
  );
  const nodesRef = useRef(displayGraph.nodes);

  useEffect(() => {
    nodesRef.current = displayGraph.nodes;
  }, [displayGraph.nodes]);

  const option = useMemo(
    () => buildGraphOption(displayGraph.nodes, displayGraph.edges, showEdgeLabels, searchQuery),
    [displayGraph.edges, displayGraph.nodes, searchQuery, showEdgeLabels],
  );

  useImperativeHandle(ref, () => ({
    downloadImage: (filename: string) => downloadEchartsGraphImage({
      option,
      filename,
      nodeCount: displayGraph.nodes.length,
    }),
  }), [displayGraph.nodes.length, option]);

  useEffect(() => {
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;

    import("echarts").then((echarts) => {
      if (disposed || !chartRef.current) return;
      const chart = echarts.init(chartRef.current);
      chartInstance.current = chart;
      chart.setOption(option);
      requestAnimationFrame(() => {
        if (!disposed && !chart.isDisposed()) chart.resize();
      });
      chart.on("click", (params) => {
        if (params.dataType !== "node") return;
        if (!params.data || Array.isArray(params.data) || typeof params.data !== "object") return;
        const data = params.data as { id?: string };
        if (!data.id) return;
        const node = nodesRef.current.find((item) => item.id === data.id);
        if (node) onNodeSelect(node);
      });
      resizeObserver = new ResizeObserver(() => {
        if (disposed || chart.isDisposed() || chartInstance.current !== chart) return;
        requestAnimationFrame(() => {
          if (!disposed && !chart.isDisposed() && chartInstance.current === chart) chart.resize();
        });
      });
      resizeObserver.observe(chartRef.current);
    });

    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, [onNodeSelect]);

  useEffect(() => {
    chartInstance.current?.setOption(option, true);
  }, [option]);

  return (
    <div
      ref={chartRef}
      className={`border-line bg-surface-alt w-full rounded-md border ${
        fullscreen ? "h-full min-h-[520px]" : "h-[560px] min-h-[420px]"
      }`}
      role="img"
      aria-label="能力图谱可视化画布"
    />
  );
});

function buildGraphOption(
  nodes: GraphDisplayNode[],
  edges: GraphDisplayEdge[],
  showEdgeLabels: boolean,
  searchQuery: string,
): EChartsOption {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const drawableEdges = edges.filter(
    (edge) => nodeIds.has(edge.source_node_id) && nodeIds.has(edge.target_node_id),
  );
  const categories = Array.from(new Set(nodes.map((node) => graphCategoryKey(node)))).map(
    (key) => ({
      name: NODE_LABELS[key] ?? key,
      itemStyle: { color: NODE_COLORS[key] ?? "#737373" },
    }),
  );
  const categoryIndex = new Map(
    Array.from(new Set(nodes.map((node) => graphCategoryKey(node)))).map((key, index) => [
      key,
      index,
    ]),
  );
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
        const data = params.data as {
          name?: string;
          nodeType?: string;
          categoryKey?: string;
          edgeType?: string;
          confidence?: number | null;
        } | null;
        if (!data) return "";
        if (params.dataType === "edge") {
          return `${EDGE_LABELS[data.edgeType ?? ""] ?? data.edgeType ?? "关系"}${formatConfidence(data.confidence)}`;
        }
        return `${data.name ?? ""}<br/>${NODE_LABELS[data.categoryKey ?? ""] ?? NODE_LABELS[data.nodeType ?? ""] ?? data.nodeType ?? ""}${formatConfidence(data.confidence)}`;
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
        categories,
        force: {
          repulsion: 260,
          edgeLength: [70, 180],
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
            const data = params.data as { edgeType?: string };
            return EDGE_LABELS[data.edgeType ?? ""] ?? data.edgeType ?? "";
          },
          fontSize: 10,
        },
        lineStyle: {
          color: "source",
          curveness: 0.12,
          opacity: 0.48,
        },
        emphasis: {
          focus: "adjacency",
          lineStyle: { width: 3 },
        },
        data: nodes.map((node) => {
          const categoryKey = graphCategoryKey(node);
          const matched =
            q &&
            [
              node.display_name,
              node.canonical_name,
              node.node_key,
              node.node_type,
              NODE_LABELS[categoryKey],
            ].some((value) => value?.toLowerCase().includes(q));
          return {
            id: node.id,
            name: truncateName(node.display_name),
            category: categoryIndex.get(categoryKey) ?? 0,
            nodeType: node.node_type,
            categoryKey,
            confidence: node.confidence,
            symbolSize: symbolSize(node.node_type, degree.get(node.id) ?? 0),
            itemStyle: {
              borderColor: matched ? "#c03946" : "#ffffff",
              borderWidth: matched ? 3 : 1,
            },
          };
        }),
        links: drawableEdges.map((edge) => ({
          source: edge.source_node_id,
          target: edge.target_node_id,
          edgeType: edge.edge_type,
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

function NodeDetailDrawer({
  node,
  onClose,
}: {
  node: GraphDisplayNode | null;
  onClose: () => void;
}) {
  const categoryKey = node ? graphCategoryKey(node) : null;

  return (
    <Drawer
      title={node?.display_name ?? "节点详情"}
      open={!!node}
      onClose={onClose}
      size={520}
      destroyOnHidden
    >
      {node ? (
        <div className="flex flex-col gap-4">
          <section className="flex flex-wrap gap-2">
            <Tag color={tagColor(categoryKey ?? node.node_type)}>
              {NODE_LABELS[categoryKey ?? node.node_type] ?? node.node_type}
            </Tag>
            {node.synthetic ? <Tag>展示汇聚节点</Tag> : null}
            {node.confidence != null ? (
              <Tag
                color={
                  node.confidence >= 0.85
                    ? "success"
                    : node.confidence >= 0.75
                      ? "warning"
                      : "error"
                }
              >
                置信度 {(node.confidence * 100).toFixed(0)}%
              </Tag>
            ) : null}
          </section>
          <DetailRow label="节点 Key" value={node.node_key} />
          <DetailRow label="规范名称" value={node.canonical_name} />
          <DetailRow label="来源表" value={node.source_table} />
          <DetailRow label="来源 ID" value={node.source_id} />
          <section>
            <Typography.Text strong>属性</Typography.Text>
            <pre className="border-line bg-surface-alt mt-2 max-h-[320px] overflow-auto rounded-md border p-3 text-xs">
              {JSON.stringify(node.properties ?? {}, null, 2)}
            </pre>
          </section>
        </div>
      ) : null}
    </Drawer>
  );
}

function DetailRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] gap-3 text-sm">
      <span className="text-muted">{label}</span>
      <Tooltip title={value ?? ""}>
        <span className="truncate">{value || "—"}</span>
      </Tooltip>
    </div>
  );
}

function symbolSize(nodeType: string, degree: number): number {
  if (nodeType === "JobAggregate") return Math.min(30 + degree * 1.5, 44);
  const base =
    nodeType === "JobRole" || nodeType === "WorkTask" ? 34 : nodeType === "WorkContent" ? 26 : 22;
  return Math.min(base + degree * 2, 48);
}

function graphCategoryKey(node: CapabilityGraphStagingNode): string {
  if (node.node_type === "JobAggregate") {
    const category =
      typeof node.properties?.aggregate_category === "string"
        ? node.properties.aggregate_category
        : "";
    return category || "JobAggregate";
  }
  if (node.node_type === "WorkContent" && node.properties?.item_type === "work_task_candidate") {
    return "JobWorkTask";
  }
  if (node.node_type === "Ability") return abilityCategoryKey(node);
  if (node.node_type !== "Skill") return node.node_type;
  const itemType = typeof node.properties?.item_type === "string" ? node.properties.item_type : "";
  if (itemType === "tool") return "SkillTool";
  if (itemType === "certificate") return "SkillCertificate";
  return "Skill";
}

function abilityCategoryKey(node: CapabilityGraphStagingNode): string {
  const category =
    typeof node.properties?.category === "string" ? node.properties.category.toUpperCase() : "";
  if (category === "P") return "AbilityProfessional";
  if (category === "G") return "AbilityGeneral";
  if (category === "S") return "AbilitySocial";
  if (category === "D") return "AbilityDevelopment";
  return "Ability";
}

function buildDisplayGraph(
  nodes: CapabilityGraphStagingNode[],
  edges: CapabilityGraphStagingEdge[],
  buildType: BuildType,
): { nodes: GraphDisplayNode[]; edges: GraphDisplayEdge[] } {
  if (buildType === "ability_analysis") {
    return {
      nodes: nodes.map((node) => normalizeAbilityAnalysisDisplayNode(node)),
      edges,
    };
  }
  if (buildType !== "job_demand") return { nodes, edges };

  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const displayNodes: GraphDisplayNode[] = [...nodes];
  const displayEdges: GraphDisplayEdge[] = [];
  const aggregateNodeByKey = new Map<string, GraphDisplayNode>();
  const aggregateEdgeKeys = new Set<string>();

  const getAggregateNode = (
    role: CapabilityGraphStagingNode,
    aggregateCategory: string,
  ): GraphDisplayNode => {
    const key = `${role.id}:${aggregateCategory}`;
    const existing = aggregateNodeByKey.get(key);
    if (existing) return existing;
    const node: GraphDisplayNode = {
      id: `aggregate:${key}`,
      build_id: role.build_id,
      node_type: "JobAggregate",
      node_key: `aggregate:${role.node_key}:${aggregateCategory}`,
      display_name: NODE_LABELS[aggregateCategory] ?? aggregateCategory,
      canonical_name: null,
      source_table: null,
      source_id: null,
      properties: {
        aggregate_category: aggregateCategory,
        parent_role_id: role.id,
        parent_role_name: role.display_name,
      },
      confidence: null,
      synthetic: true,
    };
    aggregateNodeByKey.set(key, node);
    displayNodes.push(node);
    return node;
  };

  const pushAggregateEdge = (
    edgeId: string,
    edgeType: string,
    sourceNodeId: string,
    targetNodeId: string,
    confidence: number | null,
  ) => {
    const key = `${edgeType}:${sourceNodeId}:${targetNodeId}`;
    if (aggregateEdgeKeys.has(key)) return;
    aggregateEdgeKeys.add(key);
    displayEdges.push({
      id: edgeId,
      build_id: "",
      source_node_id: sourceNodeId,
      target_node_id: targetNodeId,
      edge_type: edgeType,
      source_table: null,
      source_id: null,
      evidence: {},
      confidence,
      synthetic: true,
    });
  };

  for (const edge of edges) {
    if (
      edge.edge_type === "JOB_ROLE_REQUIRES_SKILL" ||
      edge.edge_type === "JOB_ROLE_REQUIRES_LITERACY" ||
      edge.edge_type === "JOB_ROLE_REQUIRES_WORK_CONTENT"
    ) {
      const role = nodeById.get(edge.source_node_id);
      const target = nodeById.get(edge.target_node_id);
      const aggregateCategory = target ? jobDemandAggregateCategory(target) : null;
      if (role?.node_type === "JobRole" && target && aggregateCategory) {
        const aggregateNode = getAggregateNode(role, aggregateCategory);
        pushAggregateEdge(
          `aggregate:${edge.id}:role`,
          "JOB_ROLE_HAS_AGGREGATE",
          role.id,
          aggregateNode.id,
          edge.confidence,
        );
        pushAggregateEdge(
          `aggregate:${edge.id}:item`,
          "AGGREGATE_HAS_ITEM",
          aggregateNode.id,
          target.id,
          edge.confidence,
        );
        continue;
      }
    }
    displayEdges.push(edge);
  }

  return { nodes: displayNodes, edges: displayEdges };
}

function normalizeAbilityAnalysisDisplayNode(node: CapabilityGraphStagingNode): GraphDisplayNode {
  if (node.node_type !== "WorkContent") return node;
  return {
    ...node,
    display_name: resolveWorkContentDisplayName(node),
  };
}

function resolveWorkContentDisplayName(node: CapabilityGraphStagingNode): string {
  const description = stringProperty(node.properties?.content_description);
  if (description) return stripWorkContentCodePrefix(description, node.properties?.content_code);
  const contentName = stringProperty(node.properties?.content_name);
  if (contentName && contentName !== stringProperty(node.properties?.content_code)) {
    return stripWorkContentCodePrefix(contentName, node.properties?.content_code);
  }
  return stripWorkContentCodePrefix(node.display_name, node.properties?.content_code);
}

function stringProperty(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed || null;
}

function stripWorkContentCodePrefix(value: string, contentCode: unknown): string {
  const code = typeof contentCode === "string" ? contentCode.trim() : "";
  const trimmed = value.trim();
  if (!trimmed) return value;
  if (code) {
    const withoutKnownCode = trimmed
      .replace(new RegExp(`^${escapeRegExp(code)}(?:[\\s、.．:：\\-]|$)+`), "")
      .trim();
    if (withoutKnownCode) return withoutKnownCode;
  }
  const withoutNumericCode = trimmed.replace(/^\d+(?:[.．]\d+)+(?:[\s、.．:：-]|$)+/, "").trim();
  return withoutNumericCode || value;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function jobDemandAggregateCategory(node: CapabilityGraphStagingNode): string | null {
  if (node.node_type === "ProfessionalLiteracy") return "JobAggregateLiteracy";
  if (node.node_type === "WorkContent" && node.properties?.item_type === "work_task_candidate") {
    return "JobAggregateTask";
  }
  if (node.node_type !== "Skill") return null;
  const itemType = typeof node.properties?.item_type === "string" ? node.properties.item_type : "";
  if (itemType === "tool" || itemType === "certificate") return "JobAggregateToolCertificate";
  return "JobAggregateSkill";
}

function truncateName(value: string): string {
  return value.length > 18 ? `${value.slice(0, 17)}...` : value;
}

function tagColor(nodeType: string): string {
  if (nodeType === "JobRole" || nodeType === "WorkTask") return "blue";
  if (nodeType === "Ability") return "default";
  if (nodeType === "Skill" || nodeType === "AbilityProfessional") return "green";
  if (nodeType === "AbilityGeneral") return "blue";
  if (nodeType === "AbilitySocial") return "orange";
  if (nodeType === "AbilityDevelopment") return "red";
  if (nodeType === "SkillTool") return "purple";
  if (nodeType === "SkillCertificate") return "magenta";
  if (nodeType === "ProfessionalLiteracy") return "gold";
  if (nodeType === "JobWorkTask" || nodeType === "WorkContent") return "purple";
  if (nodeType === "JobAggregateSkill") return "cyan";
  if (nodeType === "JobAggregateLiteracy") return "gold";
  if (nodeType === "JobAggregateTask") return "purple";
  if (nodeType === "JobAggregateToolCertificate") return "geekblue";
  return "default";
}

function formatConfidence(value?: number | null): string {
  return value == null ? "" : `<br/>置信度 ${(value * 100).toFixed(0)}%`;
}

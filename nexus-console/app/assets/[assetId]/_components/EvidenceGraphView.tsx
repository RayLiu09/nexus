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
  App,
  Button,
  Card,
  Checkbox,
  Drawer,
  Empty,
  Input,
  Progress,
  Skeleton,
  Space,
  Steps,
  Tag,
  Tooltip,
  Typography,
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

type BuildProcessPhase = "idle" | "preflight" | "submitted" | "waiting" | "succeeded" | "failed";

type CandidateSelectionSummary = {
  selected_chunk_count?: number;
  skipped_chunk_count?: number;
  total_semantic_chunk_count?: number;
  by_anchor_role?: Record<string, number>;
  skipped_by_reason?: Record<string, number>;
};

type BuildSubmitResponse = {
  skipped?: boolean;
  reason?: string;
  build?: KnowledgeGraphBuild;
  candidate_selection?: CandidateSelectionSummary;
};

type BuildProcessState = {
  phase: BuildProcessPhase;
  buildId: string | null;
  candidateSelection: CandidateSelectionSummary | null;
  message: string | null;
  error: string | null;
  pollCount: number;
  pollExhausted: boolean;
  updatedAt: string | null;
};

const STRATEGY_VERSION = "evidence_kg.v1";
const PAGE_SIZE = 200;
const MAX_GRAPH_ROWS = 1600;
const BUILD_POLL_INTERVAL_MS = 10000;
const BUILD_POLL_LIMIT = 30;

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
  const { message } = App.useApp();
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
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [buildProcess, setBuildProcess] = useState<BuildProcessState>({
    phase: "idle",
    buildId: null,
    candidateSelection: null,
    message: null,
    error: null,
    pollCount: 0,
    pollExhausted: false,
    updatedAt: null,
  });
  const graphRef = useRef<GraphImageHandle | null>(null);
  const pollTimerRef = useRef<number | null>(null);

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
    const active = await fetchLatestActiveBuild(normalizedRefId, graphProfile);
    if (!active.ok) {
      setState({
        loading: false,
        build: null,
        nodes: [],
        edges: [],
        facts: [],
        evidence: [],
        totals: { nodes: 0, edges: 0, facts: 0, evidence: 0 },
        error: active.error,
      });
      return;
    }

    if (active.build && isBuildInProgress(active.build)) {
      const build = active.build;
      setState({
        loading: false,
        build,
        nodes: [],
        edges: [],
        facts: [],
        evidence: [],
        totals: {
          nodes: build.node_count,
          edges: build.edge_count,
          facts: build.fact_count,
          evidence: 0,
        },
        error: null,
      });
      setBuildProcess((prev) =>
        buildProcessFromBuild(build, {
          pollCount: prev.buildId === build.id ? prev.pollCount : 0,
          pollExhausted: prev.buildId === build.id ? prev.pollExhausted : false,
          candidateSelection:
            prev.buildId === build.id
              ? prev.candidateSelection ?? candidateSelectionFromBuild(build)
              : candidateSelectionFromBuild(build),
        }),
      );
      return;
    }

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

    const build = summary.data.build ?? active.build;
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

    if (isZeroRowSucceededBuild(build)) {
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
      setBuildProcess({
        phase: "failed",
        buildId: build.id,
        candidateSelection: candidateSelectionFromBuild(build),
        message: null,
        error: "上一次构建状态为成功，但未产生任何图谱节点或事实，请重新构建。",
        pollCount: 0,
        pollExhausted: false,
        updatedAt: new Date().toISOString(),
      });
      return;
    }

    if (!canDisplayGraphData(build)) {
      setState({
        loading: false,
        build,
        nodes: [],
        edges: [],
        facts: [],
        evidence: [],
        totals: {
          nodes: build.node_count,
          edges: build.edge_count,
          facts: build.fact_count,
          evidence: 0,
        },
        error: null,
      });
      if (build.status === "failed") {
        setBuildProcess(buildProcessFromBuild(build));
      }
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
    if (!error) {
      setBuildProcess({
        phase: "idle",
        buildId: null,
        candidateSelection: null,
        message: null,
        error: null,
        pollCount: 0,
        pollExhausted: false,
        updatedAt: null,
      });
    }
  }, [graphProfile, normalizedRefId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(
    () => () => {
      if (pollTimerRef.current) window.clearTimeout(pollTimerRef.current);
    },
    [],
  );

  useEffect(() => {
    setQuery("");
    setSelectedItem(null);
    setBuildProcess({
      phase: "idle",
      buildId: null,
      candidateSelection: null,
      message: null,
      error: null,
      pollCount: 0,
      pollExhausted: false,
      updatedAt: null,
    });
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
  const buildInProgress = state.build ? isBuildInProgress(state.build) : false;
  const showGraphData = state.build ? canDisplayGraphData(state.build) : false;
  const showBuildProcessPanel =
    buildProcess.phase !== "idle" &&
    (buildProcess.phase !== "succeeded" || !showGraphData);

  useEffect(() => {
    if (!normalizedRefId || buildProcess.phase !== "waiting" || !buildProcess.buildId) return;
    if (pollTimerRef.current) window.clearTimeout(pollTimerRef.current);
    if (buildProcess.pollCount >= BUILD_POLL_LIMIT) {
      setBuildProcess((prev) => ({
        ...prev,
        message: `已自动轮询 ${BUILD_POLL_LIMIT} 次，构建仍在执行中。可稍后手动刷新状态。`,
        pollCount: BUILD_POLL_LIMIT,
        pollExhausted: true,
        updatedAt: new Date().toISOString(),
      }));
      return;
    }

    const buildId = buildProcess.buildId;
    const nextPollCount = buildProcess.pollCount + 1;
    pollTimerRef.current = window.setTimeout(async () => {
      const latest = await fetchLatestActiveBuild(normalizedRefId, graphProfile);
      if (!latest.ok) {
        setBuildProcess((prev) => ({
          ...prev,
          phase: "failed",
          error: latest.error ?? "轮询构建状态失败",
          pollCount: nextPollCount,
          pollExhausted: false,
          updatedAt: new Date().toISOString(),
        }));
        return;
      }

      const build = latest.build;
      if (!build) {
        setBuildProcess((prev) => ({
          ...prev,
          phase: "failed",
          error: "未找到当前 Evidence Graph build 状态。",
          pollCount: nextPollCount,
          pollExhausted: false,
          updatedAt: new Date().toISOString(),
        }));
        return;
      }

      const nextProcess = buildProcessFromBuild(build, {
        pollCount: nextPollCount,
        candidateSelection: buildProcess.candidateSelection,
      });
      setBuildProcess(nextProcess);
      if (build.status === "succeeded" || build.status === "review_required" || build.status === "failed") {
        await load();
        return;
      }
      if (build.id !== buildId) {
        await load();
      }
    }, BUILD_POLL_INTERVAL_MS);

    return () => {
      if (pollTimerRef.current) window.clearTimeout(pollTimerRef.current);
    };
  }, [
    buildProcess.buildId,
    buildProcess.candidateSelection,
    buildProcess.phase,
    buildProcess.pollCount,
    graphProfile,
    load,
    normalizedRefId,
  ]);

  const submitBuild = useCallback(async (force = false) => {
    if (!normalizedRefId) return;
    const refId = normalizedRefId;
    if (buildInProgress) {
      message.info("当前已有图谱构建正在执行，请等待后台处理完成。");
      return;
    }
    if (pollTimerRef.current) window.clearTimeout(pollTimerRef.current);
    setSubmitting(true);
    setBuildProcess({
      phase: "preflight",
      buildId: null,
      candidateSelection: null,
      message: "正在扫描当前标准化资产的语义知识块。",
      error: null,
      pollCount: 0,
      pollExhausted: false,
      updatedAt: new Date().toISOString(),
    });
    try {
      const basePayload = {
        normalized_ref_id: refId,
        graph_profile: graphProfile,
        strategy_version: STRATEGY_VERSION,
      };
      const buildEndpoint = force ? "/api/evidence-graphs/rebuild" : "/api/evidence-graphs/builds";
      const dryRun = await postApiData<CandidateSelectionSummary>(buildEndpoint, {
        ...basePayload,
        force,
        dry_run: true,
      });
      setBuildProcess((prev) => ({
        ...prev,
        phase: "submitted",
        candidateSelection: dryRun.data,
        message: `预检完成，选中 ${dryRun.data.selected_chunk_count ?? 0} 个候选知识块。`,
        updatedAt: new Date().toISOString(),
      }));
      if ((dryRun.data.selected_chunk_count ?? 0) <= 0) {
        const reason = (dryRun.data.total_semantic_chunk_count ?? 0) <= 0
          ? "当前标准化资产尚未生成语义知识块，请先完成知识块构建后再构建 Evidence Graph。"
          : "当前语义知识块不满足该图谱 profile 的候选条件，请先检查知识块角色或重建知识块。";
        setBuildProcess((prev) => ({
          ...prev,
          phase: "failed",
          message: null,
          error: reason,
          pollExhausted: false,
          updatedAt: new Date().toISOString(),
        }));
        message.warning(reason);
        return;
      }

      const result = await postApiData<BuildSubmitResponse>(buildEndpoint, {
        ...basePayload,
        force,
        dry_run: false,
      });
      const skipped = Boolean(result.data?.skipped);
      const build = result.data?.build ?? null;
      const candidateSelection = result.data?.candidate_selection ?? dryRun.data;
      setBuildProcess(
        build
          ? {
              ...buildProcessFromBuild(build, { candidateSelection }),
              message: skipped
                ? skippedBuildMessage(build)
                : "构建信封已创建，等待后台知识加工写入图谱结果。",
            }
          : {
              phase: skipped ? "succeeded" : "waiting",
              buildId: null,
              candidateSelection,
              message: skipped
                ? skippedBuildMessage(build)
                : "构建信封已创建，等待后台知识加工写入图谱结果。",
              error: null,
              pollCount: 0,
              pollExhausted: false,
              updatedAt: new Date().toISOString(),
            },
      );
      message.success(skipped ? "已有图谱构建记录" : "已提交图谱构建信封");
      await load();
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "提交图谱构建失败";
      setBuildProcess((prev) => ({
        ...prev,
        phase: "failed",
        message: null,
        error: errorMessage,
        pollExhausted: false,
        updatedAt: new Date().toISOString(),
      }));
      message.error(errorMessage);
    } finally {
      setSubmitting(false);
    }
  }, [buildInProgress, graphProfile, load, normalizedRefId]);

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
              <Button size="small" onClick={() => setDiagnosticsOpen(true)}>
                构建诊断
              </Button>
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
          <div className="flex flex-col gap-4">
            <Empty description="尚未生成 Evidence Graph build" image={Empty.PRESENTED_IMAGE_SIMPLE}>
              <Button
                type="primary"
                icon={<RefreshCw size={16} aria-hidden="true" />}
                loading={submitting}
                disabled={buildProcess.phase === "waiting"}
                onClick={() => submitBuild(false)}
              >
                {buildProcess.phase === "waiting" ? "构建中" : "构建图谱"}
              </Button>
            </Empty>
            {showBuildProcessPanel ? (
              <BuildProcessPanel process={buildProcess} onRefresh={load} />
            ) : null}
          </div>
        ) : null}

        {!state.loading && !state.error && state.build ? (
          <div className="flex flex-col gap-4">
            {showBuildProcessPanel ? (
              <BuildProcessPanel process={buildProcess} onRefresh={load} />
            ) : null}

            {buildInProgress ? (
              <Alert
                type="info"
                showIcon
                title="Evidence Graph 正在构建中"
                description="后台正在抽取并写入图谱节点、关系、事实与 evidence。构建完成后本页会自动刷新。"
              />
            ) : null}

            {state.build.status === "failed" ? (
              <div>
                <Button
                  type="primary"
                  icon={<RefreshCw size={16} aria-hidden="true" />}
                  loading={submitting}
                  onClick={() => submitBuild(true)}
                >
                  重新构建
                </Button>
              </div>
            ) : null}

            {showGraphData && isTruncated ? (
              <Alert
                type="warning"
                showIcon
                title={`当前最多加载 ${MAX_GRAPH_ROWS} 行：节点 ${state.nodes.length}/${state.totals.nodes}、边 ${state.edges.length}/${state.totals.edges}、事实 ${state.facts.length}/${state.totals.facts}、证据 ${state.evidence.length}/${state.totals.evidence}。`}
              />
            ) : null}

            {showGraphData ? (
              <GraphToolbar
                query={query}
                onQueryChange={setQuery}
                showEdgeLabels={showEdgeLabels}
                onShowEdgeLabelsChange={setShowEdgeLabels}
              />
            ) : null}

            {showGraphData && filteredGraph.nodes.length === 0 ? (
              <Empty description="当前筛选条件下无图谱节点" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : null}
            {showGraphData && filteredGraph.nodes.length > 0 ? (
              <EvidenceEchartsGraph
                ref={graphRef}
                nodes={filteredGraph.nodes}
                edges={filteredGraph.edges}
                showEdgeLabels={showEdgeLabels}
                searchQuery={query}
                onSelect={setSelectedItem}
              />
            ) : null}

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
      <BuildDiagnosticsDrawer
        build={state.build}
        open={diagnosticsOpen}
        onClose={() => setDiagnosticsOpen(false)}
      />
    </>
  );
}

function BuildProcessPanel({
  process,
  onRefresh,
}: {
  process: BuildProcessState;
  onRefresh: () => void | Promise<void>;
}) {
  if (process.phase === "idle") return null;

  const current = buildProcessStepIndex(process.phase);
  const percent = buildProcessPercent(process.phase, process.pollCount);
  const candidate = process.candidateSelection;
  const failed = process.phase === "failed";
  const showManualRefresh = process.phase === "waiting" && process.pollExhausted;

  return (
    <div className="rounded-md border border-[var(--line)] bg-[var(--surface-alt)] p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold">构建过程</span>
          <Tag color={failed ? "error" : process.phase === "succeeded" ? "success" : "processing"}>
            {buildProcessPhaseLabel(process.phase)}
          </Tag>
          {process.buildId ? <Tag>build {shortBuildId(process.buildId)}</Tag> : null}
        </div>
        {process.updatedAt ? (
          <span className="text-muted text-xs">
            更新于 {new Date(process.updatedAt).toLocaleTimeString("zh-CN", { hour12: false })}
          </span>
        ) : null}
        {showManualRefresh ? (
          <Button
            size="small"
            icon={<RefreshCw size={14} aria-hidden="true" />}
            onClick={() => void onRefresh()}
          >
            手动刷新
          </Button>
        ) : null}
      </div>

      <Steps
        size="small"
        current={current}
        status={failed ? "error" : process.phase === "succeeded" ? "finish" : "process"}
        items={[
          { title: "候选预检", content: "统计可抽取 chunks" },
          { title: "创建构建", content: "提交 build envelope" },
          { title: "后台加工", content: "等待抽取与持久化" },
          { title: "图谱可用", content: "刷新节点/事实/evidence" },
        ]}
      />

      <div className="mt-3">
        <Progress
          percent={percent}
          status={failed ? "exception" : process.phase === "succeeded" ? "success" : "active"}
          showInfo={false}
        />
      </div>

      {process.message ? (
        <Alert
          type={failed ? "error" : "info"}
          showIcon
          title={process.message}
          className="!mt-3"
        />
      ) : null}
      {process.error ? (
        <Alert
          type="error"
          showIcon
          title="构建状态异常"
          description={process.error}
          className="!mt-3"
        />
      ) : null}

      {candidate ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <Tag>语义块 {candidate.total_semantic_chunk_count ?? 0}</Tag>
          <Tag color="blue">候选 {candidate.selected_chunk_count ?? 0}</Tag>
          <Tag>跳过 {candidate.skipped_chunk_count ?? 0}</Tag>
          {Object.entries(candidate.by_anchor_role ?? {}).map(([role, count]) => (
            <Tag key={role}>
              {role} {count}
            </Tag>
          ))}
          {Object.entries(candidate.skipped_by_reason ?? {}).map(([reason, count]) => (
            <Tag key={reason} color="default">
              {reason} {count}
            </Tag>
          ))}
        </div>
      ) : null}
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
              <div role="list" className="mt-2 divide-y divide-[var(--line)] rounded-md border border-[var(--line)]">
                {evidence.map((item) => (
                  <div
                    key={item.id}
                    role="listitem"
                    className="flex items-start justify-between gap-3 px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <Space size={6} wrap>
                        <LocatorChip locator={item.locator as LocatorInfo | null | undefined} />
                        <Tooltip title={item.chunk_id}>
                          <Tag className="!mr-0 max-w-[180px] truncate font-mono">
                            {shortId(item.chunk_id)}
                          </Tag>
                        </Tooltip>
                        {item.confidence != null ? (
                          <Tag>{(item.confidence * 100).toFixed(0)}%</Tag>
                        ) : null}
                        {item.extraction_method ? <Tag>{item.extraction_method}</Tag> : null}
                      </Space>
                      <div className="mt-2 whitespace-pre-wrap text-sm text-[var(--text)]">
                        {item.evidence_text}
                      </div>
                    </div>
                    <Button
                      type="link"
                      size="small"
                      className="shrink-0"
                      onClick={() => onEvidenceOpen(item)}
                    >
                      原文定位
                    </Button>
                  </div>
                ))}
              </div>
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

function BuildDiagnosticsDrawer({
  build,
  open,
  onClose,
}: {
  build: KnowledgeGraphBuild | null;
  open: boolean;
  onClose: () => void;
}) {
  const summary = build?.quality_summary ?? {};
  const candidate = objectValue(summary.candidate_selection);
  const grouping = objectValue(summary.unit_grouping);
  const extraction = objectValue(summary.extraction);
  const persist = objectValue(summary.persist);
  const recoveries = arrayValue(summary.running_recoveries);

  return (
    <Drawer
      title="构建诊断"
      open={open}
      onClose={onClose}
      size={620}
      destroyOnHidden
    >
      {!build ? (
        <Empty description="暂无 Evidence Graph build" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div className="flex flex-col gap-5">
          <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <Tag color={statusColor(build.status)}>{build.status}</Tag>
              <Tag>build {shortBuildId(build.id)}</Tag>
              <Tag>{build.graph_profile}</Tag>
            </div>
            {build.error_message ? (
              <Alert type="error" showIcon title="构建错误" description={build.error_message} />
            ) : null}
          </section>

          <DiagnosticSection
            title="Candidate Selection"
            rows={[
              ["Semantic chunks", numberValue(candidate.total_semantic_chunk_count)],
              ["Selected chunks", numberValue(candidate.selected_chunk_count)],
              ["Skipped chunks", numberValue(candidate.skipped_chunk_count)],
            ]}
            maps={[
              ["By anchor role", recordValue(candidate.by_anchor_role)],
              ["Skipped reasons", recordValue(candidate.skipped_by_reason)],
            ]}
          />

          <DiagnosticSection
            title="Unit Grouping"
            rows={[
              ["Source candidates", numberValue(grouping.source_candidate_chunks)],
              ["Extraction units", numberValue(grouping.extraction_unit_count)],
              ["Avg chunks / unit", numberValue(grouping.avg_chunks_per_unit)],
              ["Max chunks / unit", numberValue(grouping.max_chunks_per_unit)],
            ]}
            maps={[["By unit type", recordValue(grouping.by_unit_type)]]}
          />

          <DiagnosticSection
            title="Extraction"
            rows={[
              ["Accepted", numberValue(extraction.accepted)],
              ["Rejected", numberValue(extraction.rejected)],
            ]}
            maps={[["Rejected by reason", recordValue(extraction.rejected_by_reason)]]}
          />
          <RejectSamples samples={arrayValue(extraction.reject_samples)} />

          <DiagnosticSection
            title="Persist And Governance"
            rows={[
              ["Input candidates", numberValue(persist.input_candidates)],
              ["Persisted candidates", numberValue(persist.persisted_candidates)],
              ["Duplicate facts", numberValue(persist.duplicate_fact_candidates)],
              ["Weak facts", numberValue(persist.weak_fact_candidates)],
              ["Multi-evidence facts", numberValue(persist.multi_evidence_fact_count)],
              ["Evidence rows / fact", numberValue(persist.evidence_rows_per_fact_avg)],
              ["Duplicate evidence rows", numberValue(persist.duplicate_evidence_rows)],
              ["Invalid evidence ids", numberValue(persist.invalid_evidence_chunk_ids)],
              ["Canonical entity aliases", numberValue(persist.canonicalized_entity_aliases)],
              ["Canonical predicates", numberValue(persist.canonicalized_predicates)],
              ["Canonical literals", numberValue(persist.canonicalized_literals)],
              ["Nodes written", numberValue(persist.nodes_written)],
              ["Facts written", numberValue(persist.facts_written)],
              ["Edges written", numberValue(persist.edges_written)],
              ["Evidence written", numberValue(persist.evidence_written)],
            ]}
            maps={[["Canonicalization rules", recordValue(persist.canonicalization_rules_applied)]]}
          />

          {recoveries.length > 0 ? (
            <section>
              <Typography.Text strong>Running Recoveries</Typography.Text>
              <div className="mt-2 flex flex-col gap-2">
                {recoveries.slice(-5).map((item, index) => (
                  <pre
                    key={index}
                    className="border-line bg-surface-alt max-h-[140px] overflow-auto rounded-md border p-2 text-xs"
                  >
                    {JSON.stringify(item, null, 2)}
                  </pre>
                ))}
              </div>
            </section>
          ) : null}

          <JsonBlock title="Raw quality_summary" value={summary} />
        </div>
      )}
    </Drawer>
  );
}

function DiagnosticSection({
  title,
  rows,
  maps,
}: {
  title: string;
  rows: Array<[string, number | null]>;
  maps?: Array<[string, Record<string, unknown>]>;
}) {
  const hasRows = rows.some(([, value]) => value != null);
  const visibleMaps = (maps ?? []).filter(([, value]) => Object.keys(value).length > 0);
  return (
    <section>
      <Typography.Text strong>{title}</Typography.Text>
      {!hasRows && visibleMaps.length === 0 ? (
        <Empty className="!mt-2" description="暂无诊断数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : null}
      {hasRows ? (
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {rows.map(([label, value]) => (
            <div key={label} className="rounded-md border border-[var(--line)] px-3 py-2">
              <div className="text-muted text-xs">{label}</div>
              <div className="mt-1 text-base font-semibold">{value == null ? "-" : formatMetric(value)}</div>
            </div>
          ))}
        </div>
      ) : null}
      {visibleMaps.map(([label, value]) => (
        <div key={label} className="mt-3">
          <Typography.Text type="secondary" className="text-xs">
            {label}
          </Typography.Text>
          <div className="mt-1 flex flex-wrap gap-2">
            {sortedEntries(value).map(([key, count]) => (
              <Tag key={key} className="!mr-0">
                {key} {String(count)}
              </Tag>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}

function RejectSamples({ samples }: { samples: unknown[] }) {
  if (samples.length === 0) return null;
  return (
    <section>
      <Typography.Text strong>Reject Samples</Typography.Text>
      <div className="mt-2 flex flex-col gap-2">
        {samples.slice(0, 5).map((sample, index) => (
          <pre
            key={index}
            className="border-line bg-surface-alt max-h-[140px] overflow-auto rounded-md border p-2 text-xs"
          >
            {JSON.stringify(sample, null, 2)}
          </pre>
        ))}
      </div>
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

async function fetchLatestActiveBuild(
  normalizedRefId: string,
  graphProfile: string,
): Promise<{ ok: boolean; build: KnowledgeGraphBuild | null; error: string | null }> {
  const builds = await getApiData<KnowledgeGraphBuild[]>("/api/evidence-graphs/builds", [], {
    normalized_ref_id: normalizedRefId,
    graph_profile: graphProfile,
    strategy_version: STRATEGY_VERSION,
    pageSize: "50",
  });
  if (!builds.ok) {
    return {
      ok: false,
      build: null,
      error: builds.error ?? "加载 Evidence Graph build 状态失败",
    };
  }
  return {
    ok: true,
    build:
      builds.data.find(
        (build) => build.status !== "deprecated" && !isZeroRowSucceededBuild(build),
      ) ?? null,
    error: null,
  };
}

function isBuildInProgress(build: KnowledgeGraphBuild): boolean {
  return build.status === "pending" || build.status === "running";
}

function canDisplayGraphData(build: KnowledgeGraphBuild): boolean {
  return (build.status === "succeeded" || build.status === "review_required") && !isZeroRowSucceededBuild(build);
}

function isZeroRowSucceededBuild(build: KnowledgeGraphBuild): boolean {
  return build.status === "succeeded" && build.node_count === 0 && build.fact_count === 0;
}

function candidateSelectionFromBuild(build: KnowledgeGraphBuild): CandidateSelectionSummary | null {
  const summary = build.quality_summary ?? {};
  const value = summary.candidate_selection;
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as CandidateSelectionSummary;
}

function buildProcessFromBuild(
  build: KnowledgeGraphBuild,
  options?: {
    pollCount?: number;
    pollExhausted?: boolean;
    candidateSelection?: CandidateSelectionSummary | null;
  },
): BuildProcessState {
  const candidateSelection = options?.candidateSelection ?? candidateSelectionFromBuild(build);
  const pollCount = options?.pollCount ?? 0;
  const phase: BuildProcessPhase =
    build.status === "failed"
      ? "failed"
      : build.status === "succeeded" || build.status === "review_required"
        ? "succeeded"
        : "waiting";
  return {
    phase,
    buildId: build.id,
    candidateSelection,
    message: buildProcessMessage(build, pollCount),
    error: build.error_message,
    pollCount,
    pollExhausted: phase === "waiting" && (options?.pollExhausted ?? pollCount >= BUILD_POLL_LIMIT),
    updatedAt: new Date().toISOString(),
  };
}

function buildProcessMessage(build: KnowledgeGraphBuild, pollCount: number): string {
  if (build.status === "pending") return "构建信封已创建，等待后台 worker 认领处理。";
  if (build.status === "running") {
    return pollCount > 0
      ? `后台正在抽取并写入图谱，已轮询 ${pollCount} 次。`
      : "后台正在抽取并写入图谱。";
  }
  if (build.status === "succeeded") return "图谱构建完成，正在加载图谱数据。";
  if (build.status === "review_required") return "图谱已生成，但存在低置信度或需复核内容。";
  if (build.status === "failed") return "图谱构建失败，请查看构建错误。";
  return "已存在 Evidence Graph build。";
}

function skippedBuildMessage(build?: KnowledgeGraphBuild | null): string {
  if (!build) return "已存在 Evidence Graph build，已加载当前状态。";
  if (isBuildInProgress(build)) return "已存在正在执行的构建，已切换到构建过程视图。";
  if (build.status === "succeeded") return "已存在成功构建，直接加载当前图谱。";
  if (build.status === "review_required") return "已存在需复核的图谱构建，直接加载当前图谱。";
  if (build.status === "failed") return "已存在失败的构建记录，请查看错误或执行重建。";
  return "已存在 Evidence Graph build，已加载当前状态。";
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

function formatMetric(value: number): string {
  if (!Number.isFinite(value)) return "-";
  if (Number.isInteger(value)) return value.toLocaleString("zh-CN");
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
}

function shortId(value: string): string {
  if (value.length <= 12) return value;
  return `${value.slice(0, 8)}...${value.slice(-4)}`;
}

function statusColor(status: string): string {
  if (status === "succeeded") return "success";
  if (status === "failed") return "error";
  if (status === "deprecated") return "default";
  return "processing";
}

function buildProcessStepIndex(phase: BuildProcessPhase): number {
  if (phase === "preflight") return 0;
  if (phase === "submitted") return 1;
  if (phase === "waiting" || phase === "failed") return 2;
  if (phase === "succeeded") return 3;
  return 0;
}

function buildProcessPercent(phase: BuildProcessPhase, pollCount: number): number {
  if (phase === "preflight") return 18;
  if (phase === "submitted") return 42;
  if (phase === "waiting") return Math.min(88, 48 + pollCount * 4);
  if (phase === "succeeded") return 100;
  if (phase === "failed") return Math.max(36, Math.min(88, 48 + pollCount * 4));
  return 0;
}

function buildProcessPhaseLabel(phase: BuildProcessPhase): string {
  if (phase === "preflight") return "预检中";
  if (phase === "submitted") return "已提交";
  if (phase === "waiting") return "处理中";
  if (phase === "succeeded") return "已完成";
  if (phase === "failed") return "失败";
  return "未开始";
}

function shortBuildId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value;
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

function objectValue(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function recordValue(value: unknown): Record<string, unknown> {
  return objectValue(value);
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function sortedEntries(value: Record<string, unknown>): Array<[string, unknown]> {
  return Object.entries(value).sort((left, right) => {
    const leftNumber = numberValue(left[1]);
    const rightNumber = numberValue(right[1]);
    if (leftNumber != null && rightNumber != null && leftNumber !== rightNumber) {
      return rightNumber - leftNumber;
    }
    return left[0].localeCompare(right[0]);
  });
}

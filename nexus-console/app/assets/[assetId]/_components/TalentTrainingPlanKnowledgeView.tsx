"use client";

import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { Alert, Empty, Segmented, Skeleton } from "antd";
import { BookOpen } from "lucide-react";
import type { ECharts, EChartsOption } from "echarts";

import { ChunkListSection } from "./ChunkListSection";
import { downloadEchartsGraphImage, GraphViewportActions, type GraphImageHandle } from "./GraphViewportActions";
import {
  getApiData,
  type TalentTrainingPlanGraph,
  type TalentTrainingPlanGraphEdge,
  type TalentTrainingPlanGraphNode,
} from "@/lib/api";

type ViewKey = "chunks" | "course_graph" | "position_graph";

type Props = {
  normalizedRefId: string | null;
  planId: string | null;
};

const VIEW_OPTIONS: Array<{ label: string; value: ViewKey }> = [
  { label: "RAG知识块", value: "chunks" },
  { label: "课程知识图谱", value: "course_graph" },
  { label: "岗位能力图谱", value: "position_graph" },
];

const NODE_LABELS: Record<string, string> = {
  TalentTrainingPlan: "人才培养方案",
  Course: "课程",
  CourseObjective: "课程目标",
  CourseContent: "课程内容",
  Position: "岗位",
  Skill: "技能/能力",
};

const NODE_COLORS: Record<string, string> = {
  TalentTrainingPlan: "#2563eb",
  Course: "#0d9488",
  CourseObjective: "#7c3aed",
  CourseContent: "#d97706",
  Position: "#db2777",
  Skill: "#16a34a",
};

const EDGE_LABELS: Record<string, string> = {
  PLAN_HAS_COURSE: "包含课程",
  COURSE_HAS_OBJECTIVE: "课程目标",
  COURSE_HAS_CONTENT: "课程内容",
  COURSE_COVERS_SKILL: "覆盖技能",
  PLAN_ORIENTS_TO_POSITION: "职业面向",
  POSITION_REQUIRES_SKILL: "岗位要求技能",
};

export function TalentTrainingPlanKnowledgeView({ normalizedRefId, planId }: Props) {
  const [view, setView] = useState<ViewKey>("chunks");
  const [state, setState] = useState<{
    loading: boolean;
    courseGraph: TalentTrainingPlanGraph | null;
    positionGraph: TalentTrainingPlanGraph | null;
    error: string | null;
  }>({ loading: Boolean(planId), courseGraph: null, positionGraph: null, error: null });

  useEffect(() => {
    let active = true;
    if (!planId) {
      setState({ loading: false, courseGraph: null, positionGraph: null, error: null });
      return () => { active = false; };
    }
    setState({ loading: true, courseGraph: null, positionGraph: null, error: null });
    Promise.all([
      getApiData<TalentTrainingPlanGraph>(`/api/talent-training-plans/${planId}/course-knowledge-graph`, null as unknown as TalentTrainingPlanGraph),
      getApiData<TalentTrainingPlanGraph>(`/api/talent-training-plans/${planId}/position-capability-graph`, null as unknown as TalentTrainingPlanGraph),
    ]).then(([courseGraph, positionGraph]) => {
      if (!active) return;
      const failed = [courseGraph, positionGraph].find((item) => !item.ok);
      setState({
        loading: false,
        courseGraph: courseGraph.ok ? courseGraph.data : null,
        positionGraph: positionGraph.ok ? positionGraph.data : null,
        error: failed?.error ?? null,
      });
    });
    return () => { active = false; };
  }, [planId]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <Segmented value={view} onChange={(value) => setView(value as ViewKey)} options={VIEW_OPTIONS} aria-label="切换人才培养方案知识视图" />
      </div>
      {view === "chunks" ? (
        <ChunkListSection refId={normalizedRefId} title="RAG知识块" emptyDescription="该方案暂未生成 RAG 语义知识块。" mode="preview" actionLabel="定位原文" />
      ) : null}
      {view !== "chunks" && state.loading ? <Skeleton active paragraph={{ rows: 8 }} /> : null}
      {view !== "chunks" && !state.loading && !planId ? (
        <Empty description="该资产尚未生成人才培养方案领域投影" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : null}
      {view !== "chunks" && !state.loading && state.error ? <Alert type="error" showIcon title="加载人才培养方案领域视图失败" description={state.error} /> : null}
      {view === "course_graph" && !state.loading && !state.error && state.courseGraph ? <PlanGraph graph={state.courseGraph} title="课程知识图谱" /> : null}
      {view === "position_graph" && !state.loading && !state.error && state.positionGraph ? <PositionGraph graph={state.positionGraph} /> : null}
    </div>
  );
}

function PositionGraph({ graph }: { graph: TalentTrainingPlanGraph }) {
  if (!graph.available) {
    return <Alert type="info" showIcon title="该方案未提供岗位能力图谱" description="规范化方案中没有可追溯的岗位—技能事实，因此未构造推断关系。" />;
  }
  return <PlanGraph graph={graph} title="岗位能力图谱" />;
}

function PlanGraph({ graph, title }: { graph: TalentTrainingPlanGraph; title: string }) {
  const graphRef = useRef<GraphImageHandle | null>(null);
  if (graph.nodes.length === 0) return <Empty description="暂无可绘制的图谱关系" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title inline-flex items-center gap-2"><BookOpen size={16} />{title}</span>
        <GraphViewportActions title={title} disabled={graph.nodes.length === 0} onDownload={() => graphRef.current?.downloadImage(`${title}.png`) ?? Promise.resolve(false)} immersive>
          <PlanGraphChart ref={graphRef} graph={graph} fullscreen />
        </GraphViewportActions>
      </div>
      <div className="card-body"><PlanGraphChart ref={graphRef} graph={graph} /></div>
    </div>
  );
}

type ChartNode = TalentTrainingPlanGraphNode & { category: number; symbolSize: number; name: string };
type ChartEdge = TalentTrainingPlanGraphEdge & { source: string; target: string; name: string };

const PlanGraphChart = forwardRef<GraphImageHandle, { graph: TalentTrainingPlanGraph; fullscreen?: boolean }>(function PlanGraphChart({ graph, fullscreen = false }, forwardedRef) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const instance = useRef<ECharts | null>(null);
  const categories = useMemo(() => [...new Set(graph.nodes.map((node) => node.node_type))], [graph.nodes]);
  const option = useMemo<EChartsOption>(() => {
    const nodeIds = new Set(graph.nodes.map((node) => node.id));
    const nodes: ChartNode[] = graph.nodes.map((node) => ({ ...node, name: compact(node.display_name), category: categories.indexOf(node.node_type), symbolSize: node.node_type === "TalentTrainingPlan" ? 64 : node.node_type === "Course" || node.node_type === "Position" ? 46 : 30 }));
    const edges: ChartEdge[] = graph.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target)).map((edge) => ({ ...edge, name: EDGE_LABELS[edge.relation_type] ?? edge.relation_type }));
    return { tooltip: { trigger: "item", confine: true, formatter: (params) => { const item = Array.isArray(params) ? params[0] : params; const data = item?.data as ChartNode | ChartEdge | undefined; if (!data) return ""; if ("display_name" in data) return nodeTooltip(data); return `<b>${escapeHtml(data.name)}</b>${evidenceText(data.evidence)}`; } }, legend: [{ top: 0, data: categories.map((type) => NODE_LABELS[type] ?? type) }], series: [{ type: "graph", layout: "force", roam: true, top: 36, label: { show: true, formatter: "{b}", width: 150, overflow: "break" }, edgeLabel: { show: false }, force: { repulsion: 260, edgeLength: 130 }, categories: categories.map((type) => ({ name: NODE_LABELS[type] ?? type, itemStyle: { color: NODE_COLORS[type] ?? "#64748b" } })), data: nodes, links: edges, lineStyle: { color: "source", curveness: 0.16, opacity: 0.72 }, emphasis: { focus: "adjacency" } }] };
  }, [categories, graph.edges, graph.nodes]);
  useImperativeHandle(forwardedRef, () => ({ downloadImage: (filename) => downloadEchartsGraphImage({ option, filename, nodeCount: graph.nodes.length }) }), [graph.nodes.length, option]);
  useEffect(() => { if (!containerRef.current) return; let disposed = false; let observer: ResizeObserver | null = null; const container = containerRef.current; import("echarts").then((echarts) => { if (disposed) return; const chart = echarts.init(container); instance.current = chart; chart.setOption(option); observer = new ResizeObserver(() => chart.resize()); observer.observe(container); }); return () => { disposed = true; observer?.disconnect(); instance.current?.dispose(); instance.current = null; }; }, [option]);
  return <div ref={containerRef} className={`w-full ${fullscreen ? "h-full min-h-[520px]" : "h-[620px] min-h-[420px]"}`} />;
});

function compact(value: string): string { const text = value.replace(/\s+/g, " ").trim(); return text.length > 28 ? `${text.slice(0, 14)}\n${text.slice(14, 28)}...` : text; }
function nodeTooltip(node: ChartNode): string {
  const type = escapeHtml(NODE_LABELS[node.node_type] ?? node.node_type);
  const text = escapeHtml(node.display_name);
  return `<div style="max-width:420px"><b>${type}</b><div style="margin-top:4px;white-space:pre-wrap;word-break:break-word;line-height:1.6">${text}</div>${evidenceText(node.evidence)}</div>`;
}
function escapeHtml(value: string): string { return value.replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char] ?? char); }
function evidenceText(evidence: Record<string, unknown>): string { const page = evidence.page ?? evidence.page_start; const block = evidence.block_id; return page || block ? `<div style="margin-top:4px;color:#64748b">${block ? `来源块：${escapeHtml(String(block))}` : ""}${page ? `${block ? " · " : ""}第 ${escapeHtml(String(page))} 页` : ""}</div>` : ""; }

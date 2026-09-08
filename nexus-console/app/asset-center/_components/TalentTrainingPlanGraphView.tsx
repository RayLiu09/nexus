"use client";

import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { Alert, Empty, Skeleton } from "antd";
import { BookOpen } from "lucide-react";
import type { ECharts, EChartsOption } from "echarts";

import {
  downloadEchartsGraphImage,
  GraphViewportActions,
  type GraphImageHandle,
} from "@/app/assets/[assetId]/_components/GraphViewportActions";
import {
  getApiData,
  type TalentTrainingPlanGraph,
  type TalentTrainingPlanGraphEdge,
  type TalentTrainingPlanGraphNode,
} from "@/lib/api";

export type TalentTrainingPlanGraphKind = "course" | "position";

type Props = {
  planId: string;
  kind: TalentTrainingPlanGraphKind;
};

const GRAPH_CONFIG = {
  course: {
    title: "课程知识图谱",
    path: "course-knowledge-graph",
  },
  position: {
    title: "岗位能力图谱",
    path: "position-capability-graph",
  },
} as const;

const NODE_LABELS: Record<string, string> = {
  TalentTrainingPlan: "人才培养方案",
  Course: "课程",
  CourseObjective: "课程目标",
  CourseContent: "课程内容",
  Position: "岗位",
  Skill: "技能/能力",
};

const NODE_COLORS: Record<string, string> = {
  TalentTrainingPlan: "#1d4ed8",
  Course: "#0f766e",
  CourseObjective: "#7c3aed",
  CourseContent: "#b45309",
  Position: "#be123c",
  Skill: "#15803d",
};

const EDGE_LABELS: Record<string, string> = {
  PLAN_HAS_COURSE: "包含课程",
  COURSE_HAS_OBJECTIVE: "课程目标",
  COURSE_HAS_CONTENT: "课程内容",
  COURSE_COVERS_SKILL: "覆盖技能",
  PLAN_ORIENTS_TO_POSITION: "职业面向",
  POSITION_REQUIRES_SKILL: "岗位要求技能",
};

export function TalentTrainingPlanGraphView({ planId, kind }: Props) {
  const [state, setState] = useState<{
    loading: boolean;
    graph: TalentTrainingPlanGraph | null;
    error: string | null;
  }>({ loading: true, graph: null, error: null });
  const config = GRAPH_CONFIG[kind];

  useEffect(() => {
    let active = true;
    getApiData<TalentTrainingPlanGraph>(
      `/api/talent-training-plans/${encodeURIComponent(planId)}/${config.path}`,
      null as unknown as TalentTrainingPlanGraph,
    ).then((result) => {
      if (!active) return;
      setState({
        loading: false,
        graph: result.ok ? result.data : null,
        error: result.ok ? null : result.error,
      });
    });
    return () => {
      active = false;
    };
  }, [config.path, planId]);

  if (state.loading) return <Skeleton active paragraph={{ rows: 10 }} />;
  if (state.error) {
    return (
      <Alert type="error" showIcon title={`加载${config.title}失败`} description={state.error} />
    );
  }
  if (!state.graph) {
    return <Empty description={`暂无${config.title}数据`} image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  if (kind === "position" && !state.graph.available) {
    return (
      <Alert
        type="info"
        showIcon
        title="该方案未提供岗位能力图谱"
        description="规范化方案中没有可追溯的岗位与技能事实，因此未构造推断关系。"
      />
    );
  }
  return <PlanGraph graph={state.graph} title={config.title} />;
}

function PlanGraph({ graph, title }: { graph: TalentTrainingPlanGraph; title: string }) {
  const graphRef = useRef<GraphImageHandle | null>(null);
  if (graph.nodes.length === 0) {
    return <Empty description="暂无可绘制的图谱关系" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  return (
    <section className="border-line bg-surface border">
      <div className="border-line flex items-center justify-between border-b px-4 py-3">
        <h3 className="text-text inline-flex items-center gap-2 text-sm font-semibold">
          <BookOpen size={16} aria-hidden="true" />
          {title}
        </h3>
        <GraphViewportActions
          title={title}
          disabled={graph.nodes.length === 0}
          onDownload={() =>
            graphRef.current?.downloadImage(`${title}.png`) ?? Promise.resolve(false)
          }
          immersive
        >
          <PlanGraphChart ref={graphRef} graph={graph} fullscreen />
        </GraphViewportActions>
      </div>
      <div className="p-3">
        <PlanGraphChart ref={graphRef} graph={graph} />
      </div>
    </section>
  );
}

type ChartNode = TalentTrainingPlanGraphNode & {
  category: number;
  symbolSize: number;
  name: string;
};
type ChartEdge = TalentTrainingPlanGraphEdge & {
  source: string;
  target: string;
  name: string;
};

const PlanGraphChart = forwardRef<
  GraphImageHandle,
  { graph: TalentTrainingPlanGraph; fullscreen?: boolean }
>(function PlanGraphChart({ graph, fullscreen = false }, forwardedRef) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const instance = useRef<ECharts | null>(null);
  const categories = useMemo(
    () => [...new Set(graph.nodes.map((node) => node.node_type))],
    [graph.nodes],
  );
  const option = useMemo<EChartsOption>(() => {
    const nodeIds = new Set(graph.nodes.map((node) => node.id));
    const nodes: ChartNode[] = graph.nodes.map((node) => ({
      ...node,
      name: compact(node.display_name),
      category: categories.indexOf(node.node_type),
      symbolSize:
        node.node_type === "TalentTrainingPlan"
          ? 64
          : node.node_type === "Course" || node.node_type === "Position"
            ? 46
            : 30,
    }));
    const edges: ChartEdge[] = graph.edges
      .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
      .map((edge) => ({
        ...edge,
        name: EDGE_LABELS[edge.relation_type] ?? edge.relation_type,
      }));
    return {
      tooltip: {
        trigger: "item",
        confine: true,
        formatter: (params) => {
          const item = Array.isArray(params) ? params[0] : params;
          const data = item?.data as ChartNode | ChartEdge | undefined;
          if (!data) return "";
          if ("display_name" in data) return nodeTooltip(data);
          return `<b>${escapeHtml(data.name)}</b>${evidenceText(data.evidence)}`;
        },
      },
      legend: [{ top: 0, data: categories.map((type) => NODE_LABELS[type] ?? type) }],
      series: [
        {
          type: "graph",
          layout: "force",
          roam: true,
          top: 36,
          label: { show: true, formatter: "{b}", width: 150, overflow: "break" },
          edgeLabel: { show: false },
          force: { repulsion: 260, edgeLength: 130 },
          categories: categories.map((type) => ({
            name: NODE_LABELS[type] ?? type,
            itemStyle: { color: NODE_COLORS[type] ?? "#64748b" },
          })),
          data: nodes,
          links: edges,
          lineStyle: { color: "source", curveness: 0.16, opacity: 0.72 },
          emphasis: { focus: "adjacency" },
        },
      ],
    };
  }, [categories, graph.edges, graph.nodes]);

  useImperativeHandle(
    forwardedRef,
    () => ({
      downloadImage: (filename) =>
        downloadEchartsGraphImage({ option, filename, nodeCount: graph.nodes.length }),
    }),
    [graph.nodes.length, option],
  );

  useEffect(() => {
    if (!containerRef.current) return;
    let disposed = false;
    let observer: ResizeObserver | null = null;
    const container = containerRef.current;
    import("echarts").then((echarts) => {
      if (disposed) return;
      const chart = echarts.init(container);
      instance.current = chart;
      chart.setOption(option);
      observer = new ResizeObserver(() => chart.resize());
      observer.observe(container);
    });
    return () => {
      disposed = true;
      observer?.disconnect();
      instance.current?.dispose();
      instance.current = null;
    };
  }, [option]);

  return (
    <div
      ref={containerRef}
      className={`w-full ${fullscreen ? "h-full min-h-[520px]" : "h-[620px] min-h-[420px]"}`}
    />
  );
});

function compact(value: string): string {
  const text = value.replace(/\s+/g, " ").trim();
  return text.length > 28 ? `${text.slice(0, 14)}\n${text.slice(14, 28)}...` : text;
}

function nodeTooltip(node: ChartNode): string {
  const type = escapeHtml(NODE_LABELS[node.node_type] ?? node.node_type);
  const text = escapeHtml(node.display_name);
  return `<div style="max-width:420px"><b>${type}</b><div style="margin-top:4px;white-space:pre-wrap;word-break:break-word;line-height:1.6">${text}</div>${evidenceText(node.evidence)}</div>`;
}

function escapeHtml(value: string): string {
  return value.replace(
    /[&<>'"]/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character] ??
      character,
  );
}

function evidenceText(evidence: Record<string, unknown>): string {
  const page = evidence.page ?? evidence.page_start;
  const block =
    evidence.block_id ?? (Array.isArray(evidence.block_ids) ? evidence.block_ids[0] : undefined);
  if (!page && !block) return "";
  return `<div style="margin-top:4px;color:#64748b">${block ? `来源块：${escapeHtml(String(block))}` : ""}${page ? `${block ? " · " : ""}第 ${escapeHtml(String(page))} 页` : ""}</div>`;
}

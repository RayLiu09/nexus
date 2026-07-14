"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { Alert, Card, Empty, Select, Skeleton, Tag } from "antd";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";

import {
  getApiData,
  type JobDemandRoleGraph,
} from "@/lib/api";
import {
  downloadEchartsGraphImage,
  GraphViewportActions,
  type GraphImageHandle,
} from "./GraphViewportActions";

type Props = { datasetId: string };

const ITEM_STYLE: Record<string, { label: string; color: string }> = {
  professional_skill: { label: "职业技能", color: "#0d9488" },
  tool: { label: "工具", color: "#4f46e5" },
  certificate: { label: "证书", color: "#db2777" },
  professional_literacy: { label: "职业素养", color: "#d97706" },
  work_task_candidate: { label: "工作任务", color: "#7c3aed" },
};

export function JobDemandGraphView({ datasetId }: Props) {
  const [state, setState] = useState<{
    loading: boolean;
    graph: JobDemandRoleGraph | null;
    error: string | null;
  }>({ loading: true, graph: null, error: null });
  const [selectedTitle, setSelectedTitle] = useState<string | undefined>();
  const graphRef = useRef<GraphImageHandle | null>(null);

  useEffect(() => {
    let active = true;
    setState((previous) => ({ ...previous, loading: true, error: null }));
    getApiData<JobDemandRoleGraph>(
      `/api/record-assets/job-demand-datasets/${encodeURIComponent(datasetId)}/role-graph`,
      { dataset_id: datasetId, build_id: "", selected_job_title: null, roles: [], nodes: [], edges: [] },
      selectedTitle ? { job_title: selectedTitle } : undefined,
    ).then((result) => {
      if (!active) return;
      if (!result.ok) {
        setState({ loading: false, graph: null, error: result.error });
        return;
      }
      setState({ loading: false, graph: result.data, error: null });
      setSelectedTitle(result.data.selected_job_title ?? undefined);
    });
    return () => {
      active = false;
    };
  }, [datasetId, selectedTitle]);

  return (
    <Card
      title="岗位能力图谱"
      size="small"
      extra={
        <GraphViewportActions
          title={state.graph?.selected_job_title ?? "岗位能力图谱"}
          disabled={!state.graph || state.graph.nodes.length === 0}
          onDownload={() => {
            void graphRef.current?.downloadImage(
              `${state.graph?.selected_job_title ?? "岗位能力"}-岗位能力图谱.png`,
            );
          }}
        >
          {state.graph ? <RoleGraphCanvas graph={state.graph} fullscreen /> : <div />}
        </GraphViewportActions>
      }
    >
      {state.loading ? <Skeleton active paragraph={{ rows: 7 }} /> : null}
      {state.error ? <Alert type="error" showIcon title="加载岗位能力图谱失败" description={state.error} /> : null}
      {!state.loading && !state.error && !state.graph ? (
        <Empty description="暂无岗位能力图谱数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : null}
      {!state.loading && !state.error && state.graph ? (
        <div className="flex flex-col gap-4">
          <Select
            value={state.graph.selected_job_title ?? undefined}
            options={state.graph.roles.map((role) => ({
              value: role.job_title,
              label: `${role.job_title} (${role.record_count})`,
            }))}
            onChange={setSelectedTitle}
            aria-label="选择岗位能力图谱"
            showSearch
            optionFilterProp="label"
          />
          <RoleGraphCanvas ref={graphRef} graph={state.graph} />
          <div className="flex flex-wrap gap-2">
            {Object.entries(ITEM_STYLE).map(([type, style]) => (
              <Tag key={type} color={style.color}>{style.label}</Tag>
            ))}
          </div>
        </div>
      ) : null}
    </Card>
  );
}

const RoleGraphCanvas = forwardRef<
  GraphImageHandle,
  { graph: JobDemandRoleGraph; fullscreen?: boolean }
>(function RoleGraphCanvas({ graph, fullscreen = false }, forwardedRef) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const option = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: "item" },
    series: [{
      type: "graph",
      layout: "force",
      roam: true,
      label: { show: true, position: "right", fontSize: 12 },
      force: { repulsion: 280, edgeLength: [70, 150], gravity: 0.08 },
      lineStyle: { color: "#94a3b8", opacity: 0.7, width: 1.2 },
      data: graph.nodes.map(toChartNode),
      links: graph.edges.map((edge) => ({
        source: edge.source_node_id,
        target: edge.target_node_id,
        name: edge.edge_type,
      })),
    }],
  }), [graph]);

  useImperativeHandle(forwardedRef, () => ({
    downloadImage: (filename: string) => downloadEchartsGraphImage({
      option,
      filename,
      nodeCount: graph.nodes.length,
    }),
  }), [graph.nodes.length, option]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !graph.selected_job_title) return;
    const chart = echarts.init(container);
    chart.setOption(option);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [graph.selected_job_title, option]);

  if (graph.nodes.length === 0) {
    return <Empty description="该岗位暂无能力图谱节点" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  return (
    <div className={`w-full ${fullscreen ? "h-full min-h-0" : "h-[520px]"}`}>
      <div ref={containerRef} className="h-full w-full" />
    </div>
  );
});

function toChartNode(node: JobDemandRoleGraph["nodes"][number]) {
  const itemType = typeof node.properties.item_type === "string"
    ? node.properties.item_type
    : null;
  if (node.node_type === "JobRole") {
    return {
      id: node.id,
      name: node.display_name,
      category: 0,
      symbolSize: 58,
      itemStyle: { color: "#1d4ed8" },
    };
  }
  if (node.node_type === "JobDemandRecord") {
    const company = typeof node.properties.company_name === "string"
      ? node.properties.company_name
      : null;
    const city = typeof node.properties.city === "string" ? node.properties.city : null;
    const reference = [company, city, node.node_key.slice(-8)].filter(Boolean).join(" · ");
    return {
      id: node.id,
      name: `招聘记录\n${reference}`,
      category: 1,
      symbolSize: 38,
      itemStyle: { color: "#2563eb" },
    };
  }
  const style = ITEM_STYLE[itemType ?? ""] ?? {
    label: node.node_type,
    color: node.node_type === "ProfessionalLiteracy" ? "#d97706" : "#64748b",
  };
  return {
    id: node.id,
    name: node.display_name,
    category: 2,
    symbolSize: 28,
    itemStyle: { color: style.color },
  };
}

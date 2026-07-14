"use client";

import { useEffect, useRef, useState } from "react";
import { Alert, Card, Empty, Select, Skeleton, Tag } from "antd";
import * as echarts from "echarts";

import {
  getApiData,
  type JobDemandRoleGraph,
} from "@/lib/api";

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
    <Card title="岗位能力" size="small">
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
          <RoleGraphCanvas graph={state.graph} />
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

function RoleGraphCanvas({ graph }: { graph: JobDemandRoleGraph }) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !graph.selected_job_title) return;
    const chart = echarts.init(container);
    const graphNodes = graph.nodes.map((node) => {
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
        return {
          id: node.id,
          name: company ? `${company}\n${node.display_name}` : node.display_name,
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
    });
    const links = graph.edges.map((edge) => ({
      source: edge.source_node_id,
      target: edge.target_node_id,
      value: edge.edge_type,
    }));
    chart.setOption({
      tooltip: { trigger: "item" },
      series: [{
        type: "graph",
        layout: "force",
        roam: true,
        label: { show: true, position: "right", fontSize: 12 },
        force: { repulsion: 280, edgeLength: [70, 150], gravity: 0.08 },
        lineStyle: { color: "#94a3b8", opacity: 0.7, width: 1.2 },
        data: graphNodes,
        links,
      }],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [graph]);

  if (graph.nodes.length === 0) {
    return <Empty description="该岗位暂无能力图谱节点" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  return <div ref={containerRef} style={{ height: 520, width: "100%" }} />;
}

"use client";

/**
 * B9.3 — Ability-analysis (PGSD) knowledge view.
 *
 * Layout (per design §9.3):
 * - Analysis summary card (analysis_model + counts + PGSD completeness)
 * - Task tree (Antd Tree) showing task → work_content → P-ability hierarchy
 * - General-abilities table (G / S / D — task-level, no work_content)
 * - Staging build mini-preview (latest build for this ref)
 *
 * `combined`-build staging is NOT auto-loaded here — operator opens the
 * staging preview page from the side action panel when interested.
 */

import { useEffect, useMemo, useState } from "react";
import {
  Alert, Badge, Card, Empty, Skeleton, Statistic, Table, Tag, Tree, Typography,
} from "antd";
import type { DataNode } from "antd/es/tree";
import type { ColumnsType } from "antd/es/table";
import {
  getApiData,
  type AbilityAnalysis,
  type CapabilityGraphStagingBuild,
  type CapabilityGraphStagingEdge,
  type CapabilityGraphStagingNode,
  type OccupationalAbilityItem,
  type OccupationalWorkTask,
} from "@/lib/api";

type Props = { normalizedRefId: string };


export function AbilityAnalysisKnowledgeView({ normalizedRefId }: Props) {
  const [state, setState] = useState<{
    loading: boolean;
    analysis: AbilityAnalysis | null;
    error: string | null;
  }>({ loading: true, analysis: null, error: null });

  useEffect(() => {
    let active = true;
    setState({ loading: true, analysis: null, error: null });
    getApiData<AbilityAnalysis[]>(
      "/api/record-assets/ability-analyses",
      [],
      { normalized_ref_id: normalizedRefId, pageSize: "1" },
    ).then(async (listRes) => {
      if (!active) return;
      if (!listRes.ok) {
        setState({ loading: false, analysis: null, error: listRes.error });
        return;
      }
      const summary = listRes.data[0];
      if (!summary) {
        setState({ loading: false, analysis: null, error: null });
        return;
      }
      // Detail endpoint includes the embedded profile (category_schema +
      // code_pattern). The list endpoint omits it to keep the row small.
      const detailRes = await getApiData<AbilityAnalysis>(
        `/api/record-assets/ability-analyses/${summary.id}`,
        summary,
      );
      if (!active) return;
      if (!detailRes.ok) {
        setState({ loading: false, analysis: summary, error: detailRes.error });
        return;
      }
      setState({ loading: false, analysis: detailRes.data, error: null });
    });
    return () => { active = false; };
  }, [normalizedRefId]);

  if (state.loading) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (state.error) {
    return (
      <Alert
        type="error" showIcon
        title="加载能力分析失败" description={state.error}
      />
    );
  }
  if (!state.analysis) {
    return (
      <Empty
        description="该 ref 没有关联的职业能力分析"
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    );
  }
  return <Loaded analysis={state.analysis} normalizedRefId={normalizedRefId} />;
}


function Loaded({
  analysis, normalizedRefId,
}: { analysis: AbilityAnalysis; normalizedRefId: string }) {
  return (
    <div className="flex flex-col gap-4">
      <AnalysisSummary analysis={analysis} />
      <TaskTreeSection analysisId={analysis.id} />
      <GeneralAbilitiesSection analysisId={analysis.id} />
      <StagingPreview normalizedRefId={normalizedRefId} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Summary card — analysis_model + counts + PGSD completeness
// ---------------------------------------------------------------------------


function AnalysisSummary({ analysis }: { analysis: AbilityAnalysis }) {
  // PGSD profile is always shipped on the detail endpoint; if it's missing
  // (custom future model) we degrade gracefully without showing the
  // completeness ribbon.
  const requiredCats = analysis.profile?.category_schema
    ?.map((c) => (typeof c["code"] === "string" ? (c["code"] as string) : null))
    .filter((c): c is string => !!c) ?? [];
  return (
    <Card title="能力分析概要" size="small">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Statistic title="分析模型" value={analysis.analysis_model} />
        <Statistic title="任务数" value={analysis.task_count} />
        <Statistic title="工作内容数" value={analysis.work_content_count} />
        <Statistic title="能力条目数" value={analysis.ability_item_count} />
      </div>
      <div className="text-muted mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span>专业：{analysis.major_name ?? "—"}</span>
        <span>方向：{analysis.major_direction ?? "—"}</span>
        <span>Schema：{analysis.schema_version}</span>
      </div>
      {requiredCats.length > 0 ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted">大类完整性：</span>
          {requiredCats.map((c) => <Tag key={c} color="blue">{c}</Tag>)}
        </div>
      ) : null}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Task tree — task → work_content → P-ability
// ---------------------------------------------------------------------------


function TaskTreeSection({ analysisId }: { analysisId: string }) {
  const [tasks, setTasks] = useState<{
    loading: boolean;
    list: OccupationalWorkTask[];
    error: string | null;
  }>({ loading: true, list: [], error: null });
  const [abilities, setAbilities] = useState<{
    loading: boolean;
    list: OccupationalAbilityItem[];
    error: string | null;
  }>({ loading: true, list: [], error: null });

  useEffect(() => {
    let active = true;
    setTasks({ loading: true, list: [], error: null });
    getApiData<OccupationalWorkTask[]>(
      `/api/record-assets/ability-analyses/${analysisId}/tasks`,
      [],
      { pageSize: "200" },
    ).then((res) => {
      if (!active) return;
      if (!res.ok) {
        setTasks({ loading: false, list: [], error: res.error });
        return;
      }
      setTasks({ loading: false, list: res.data, error: null });
    });
    return () => { active = false; };
  }, [analysisId]);

  useEffect(() => {
    let active = true;
    setAbilities({ loading: true, list: [], error: null });
    getApiData<OccupationalAbilityItem[]>(
      `/api/record-assets/ability-analyses/${analysisId}/ability-items`,
      [],
      { pageSize: "200" },
    ).then((res) => {
      if (!active) return;
      if (!res.ok) {
        setAbilities({ loading: false, list: [], error: res.error });
        return;
      }
      setAbilities({ loading: false, list: res.data, error: null });
    });
    return () => { active = false; };
  }, [analysisId]);

  // Build the tree once both sides resolve. Each ability hangs under its
  // (task, work_content) parent; G/S/D abilities (work_content_id=null)
  // are routed to the GeneralAbilitiesSection instead — not the tree.
  const treeData: DataNode[] = useMemo(() => {
    if (!tasks.list.length) return [];
    return tasks.list.map((task) => {
      const wcs = task.work_contents ?? [];
      return {
        key: `task:${task.id}`,
        title: <span><Tag color="blue">{task.task_code}</Tag>{task.task_name}</span>,
        children: wcs.map((wc) => {
          const wcAbilities = abilities.list.filter(
            (a) => a.work_content_id === wc.id,
          );
          return {
            key: `wc:${wc.id}`,
            title: (
              <span>
                <Tag color="default">{wc.content_code}</Tag>{wc.content_name}
                <span className="text-muted ml-2 text-xs">
                  {wcAbilities.length} 条
                </span>
              </span>
            ),
            children: wcAbilities.map((a) => ({
              key: `ab:${a.id}`,
              title: (
                <span>
                  <Tag color={a.ability_major_category_code === "P" ? "geekblue" : "purple"}>
                    {a.ability_code}
                  </Tag>
                  <span>{a.ability_content}</span>
                </span>
              ),
            })),
            disabled: wcAbilities.length === 0,
          };
        }),
      };
    });
  }, [tasks.list, abilities.list]);

  const loading = tasks.loading || abilities.loading;
  return (
    <Card title="任务 / 工作内容 / 能力树" size="small">
      {loading ? <Skeleton active paragraph={{ rows: 5 }} /> : null}
      {tasks.error ? (
        <Alert type="error" showIcon title="加载任务失败" description={tasks.error} />
      ) : null}
      {abilities.error ? (
        <Alert
          type="error" showIcon
          title="加载能力条目失败" description={abilities.error}
          className="!mt-2"
        />
      ) : null}
      {!loading && !tasks.error && treeData.length === 0 ? (
        <Empty description="该 analysis 暂无任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : null}
      {!loading && treeData.length > 0 ? (
        <Tree
          treeData={treeData}
          defaultExpandAll={treeData.length <= 3}
          showLine
          selectable={false}
          aria-label="能力分析任务树"
        />
      ) : null}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// General abilities (G / S / D) — task-level, no work_content parent
// ---------------------------------------------------------------------------


function GeneralAbilitiesSection({ analysisId }: { analysisId: string }) {
  const [state, setState] = useState<{
    loading: boolean;
    list: OccupationalAbilityItem[];
    error: string | null;
  }>({ loading: true, list: [], error: null });

  useEffect(() => {
    let active = true;
    setState({ loading: true, list: [], error: null });
    Promise.all(
      ["G", "S", "D"].map((cat) => getApiData<OccupationalAbilityItem[]>(
        `/api/record-assets/ability-analyses/${analysisId}/ability-items`,
        [],
        { category: cat, pageSize: "200" },
      )),
    ).then((results) => {
      if (!active) return;
      const failed = results.find((r) => !r.ok);
      if (failed) {
        setState({ loading: false, list: [], error: failed.error });
        return;
      }
      const merged = results.flatMap((r) => r.data);
      setState({ loading: false, list: merged, error: null });
    });
    return () => { active = false; };
  }, [analysisId]);

  const columns: ColumnsType<OccupationalAbilityItem> = [
    {
      title: "类别",
      dataIndex: "ability_major_category_code",
      key: "cat",
      width: 80,
      render: (code: string) => (
        <Tag color={
          code === "G" ? "green" : code === "S" ? "gold" : "purple"
        }>{code}</Tag>
      ),
    },
    { title: "编码", dataIndex: "ability_code", key: "code", width: 100 },
    { title: "内容", dataIndex: "ability_content", key: "content" },
  ];

  return (
    <Card
      title={<span>通用 / 社会 / 发展能力 (G / S / D)</span>}
      size="small"
    >
      {state.error ? (
        <Alert type="error" showIcon title="加载失败" description={state.error} />
      ) : (
        <Table<OccupationalAbilityItem>
          rowKey="id"
          size="small"
          loading={state.loading}
          columns={columns}
          dataSource={state.list}
          pagination={false}
          locale={{ emptyText: <Empty description="无 G/S/D 能力" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
        />
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Staging mini preview — latest build for this ref + node/edge counts
// ---------------------------------------------------------------------------


function StagingPreview({ normalizedRefId }: { normalizedRefId: string }) {
  const [state, setState] = useState<{
    loading: boolean;
    build: CapabilityGraphStagingBuild | null;
    nodes: CapabilityGraphStagingNode[];
    edges: CapabilityGraphStagingEdge[];
    error: string | null;
  }>({ loading: true, build: null, nodes: [], edges: [], error: null });

  useEffect(() => {
    let active = true;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    getApiData<CapabilityGraphStagingBuild[]>(
      "/api/capability-graph-staging/builds",
      [],
      { normalized_ref_id: normalizedRefId, pageSize: "1" },
    ).then(async (listRes) => {
      if (!active) return;
      if (!listRes.ok) {
        setState({ loading: false, build: null, nodes: [], edges: [], error: listRes.error });
        return;
      }
      const build = listRes.data[0];
      if (!build) {
        setState({ loading: false, build: null, nodes: [], edges: [], error: null });
        return;
      }
      // Preview: cap at 10 of each so we don't paint a huge table inline.
      const [nodesRes, edgesRes] = await Promise.all([
        getApiData<CapabilityGraphStagingNode[]>(
          `/api/capability-graph-staging/builds/${build.id}/nodes`,
          [], { pageSize: "10" },
        ),
        getApiData<CapabilityGraphStagingEdge[]>(
          `/api/capability-graph-staging/builds/${build.id}/edges`,
          [], { pageSize: "10" },
        ),
      ]);
      if (!active) return;
      setState({
        loading: false,
        build,
        nodes: nodesRes.ok ? nodesRes.data : [],
        edges: edgesRes.ok ? edgesRes.data : [],
        error: nodesRes.ok && edgesRes.ok
          ? null
          : (nodesRes.error ?? edgesRes.error ?? null),
      });
    });
    return () => { active = false; };
  }, [normalizedRefId]);

  return (
    <Card title="能力图谱 Staging 预览" size="small">
      {state.loading ? <Skeleton active paragraph={{ rows: 3 }} /> : null}
      {state.error ? (
        <Alert type="error" showIcon title="加载 staging 失败" description={state.error} />
      ) : null}
      {!state.loading && !state.error && !state.build ? (
        <Empty description="尚未生成 staging build" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : null}
      {state.build ? (
        <div className="flex flex-col gap-3">
          <div className="text-muted flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <span>构图类型：<Tag>{state.build.build_type}</Tag></span>
            <span>状态：<Tag color="processing">{state.build.status}</Tag></span>
            <span>Schema：{state.build.schema_version}</span>
          </div>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Statistic title="节点总数" value={summaryNumber(state.build.quality_summary, "nodes_total")} />
            <Statistic title="边总数" value={summaryNumber(state.build.quality_summary, "edges_total")} />
            <Statistic title="孤儿节点" value={summaryNumber(state.build.quality_summary, "orphan_nodes_count")} />
            <Statistic title="低置信边" value={summaryNumber(state.build.quality_summary, "low_confidence_edges_count")} />
          </div>
          <div>
            <Typography.Text strong className="mb-1 block">
              节点预览 <Badge count={state.nodes.length} showZero={false} />
            </Typography.Text>
            <div className="flex flex-wrap gap-2">
              {state.nodes.slice(0, 10).map((n) => (
                <Tag key={n.id} color="default">
                  <span className="opacity-60">{n.node_type}</span> {n.display_name}
                </Tag>
              ))}
              {state.nodes.length === 0 ? (
                <span className="text-muted text-sm">无节点</span>
              ) : null}
            </div>
          </div>
          <div>
            <Typography.Text strong className="mb-1 block">
              边类型预览 <Badge count={state.edges.length} showZero={false} />
            </Typography.Text>
            <div className="flex flex-wrap gap-2">
              {dedupeEdgeTypes(state.edges).map((t) => (
                <Tag key={t} color="blue">{t}</Tag>
              ))}
              {state.edges.length === 0 ? (
                <span className="text-muted text-sm">无边</span>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </Card>
  );
}


function summaryNumber(summary: Record<string, unknown>, key: string): number {
  const value = summary[key];
  return typeof value === "number" ? value : 0;
}


function dedupeEdgeTypes(edges: CapabilityGraphStagingEdge[]): string[] {
  return Array.from(new Set(edges.map((e) => e.edge_type)));
}

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
import { Alert, Card, Empty, Segmented, Skeleton, Statistic, Table, Tag, Tree } from "antd";
import type { DataNode } from "antd/es/tree";
import type { ColumnsType } from "antd/es/table";
import { CapabilityGraphView } from "./CapabilityGraphView";
import {
  getApiData,
  type AbilityAnalysis,
  type NormalizedAssetRef,
  type OccupationalAbilityItem,
  type OccupationalWorkTask,
} from "@/lib/api";

type Props = { normalizedRef: NormalizedAssetRef; assetTitle?: string | null };

export function AbilityAnalysisKnowledgeView({ normalizedRef, assetTitle }: Props) {
  const normalizedRefId = normalizedRef.id;
  const [state, setState] = useState<{
    loading: boolean;
    analysis: AbilityAnalysis | null;
    error: string | null;
  }>({ loading: true, analysis: null, error: null });

  useEffect(() => {
    let active = true;
    setState({ loading: true, analysis: null, error: null });
    getApiData<AbilityAnalysis[]>("/api/record-assets/ability-analyses", [], {
      normalized_ref_id: normalizedRefId,
      pageSize: "1",
    }).then(async (listRes) => {
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
    return () => {
      active = false;
    };
  }, [normalizedRefId]);

  if (state.loading) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (state.error) {
    return <Alert type="error" showIcon title="加载能力分析失败" description={state.error} />;
  }
  if (!state.analysis) {
    return (
      <Empty description="该 ref 没有关联的职业能力分析" image={Empty.PRESENTED_IMAGE_SIMPLE} />
    );
  }
  return <Loaded analysis={state.analysis} normalizedRef={normalizedRef} assetTitle={assetTitle} />;
}

function Loaded({
  analysis,
  normalizedRef,
  assetTitle,
}: {
  analysis: AbilityAnalysis;
  normalizedRef: NormalizedAssetRef;
  assetTitle?: string | null;
}) {
  const [viewMode, setViewMode] = useState<"list" | "tree" | "graph">("list");
  const normalizedRefId = normalizedRef.id;
  return (
    <div className="flex flex-col gap-4">
      <AnalysisSummary analysis={analysis} normalizedRef={normalizedRef} assetTitle={assetTitle} />
      <div className="flex justify-end">
        <Segmented
          value={viewMode}
          onChange={(value) => setViewMode(value as "list" | "tree" | "graph")}
          options={[
            { label: "列表", value: "list" },
            { label: "树视图", value: "tree" },
            { label: "能力图谱", value: "graph" },
          ]}
          aria-label="切换职业能力分析知识视图"
        />
      </div>
      {viewMode === "list" ? <AbilityItemsListSection analysisId={analysis.id} /> : null}
      {viewMode === "tree" ? <TaskTreeSection analysisId={analysis.id} /> : null}
      {viewMode === "graph" ? (
        <CapabilityGraphView
          normalizedRefId={normalizedRefId}
          buildType="ability_analysis"
          title="能力图谱"
        />
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Summary card — analysis_model + counts + PGSD completeness
// ---------------------------------------------------------------------------

function AnalysisSummary({
  analysis,
  normalizedRef,
  assetTitle,
}: {
  analysis: AbilityAnalysis;
  normalizedRef: NormalizedAssetRef;
  assetTitle?: string | null;
}) {
  // PGSD profile is always shipped on the detail endpoint; if it's missing
  // (custom future model) we degrade gracefully without showing the
  // completeness ribbon.
  const requiredCats =
    analysis.profile?.category_schema
      ?.map((c) => (typeof c["code"] === "string" ? (c["code"] as string) : null))
      .filter((c): c is string => !!c) ?? [];
  const displayMajor = analysis.major_name ?? inferMajorName(normalizedRef, assetTitle);
  const displayDirection = analysis.major_direction ?? inferMajorDirection(normalizedRef);
  return (
    <Card title="能力分析概要" size="small">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Statistic title="分析模型" value={analysis.analysis_model} />
        <Statistic title="任务数" value={analysis.task_count} />
        <Statistic title="工作内容数" value={analysis.work_content_count} />
        <Statistic title="能力条目数" value={analysis.ability_item_count} />
      </div>
      <div className="text-muted mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span>专业：{displayMajor ?? "—"}</span>
        <span>方向：{displayDirection ?? "—"}</span>
        <span>Schema：{analysis.schema_version}</span>
      </div>
      {requiredCats.length > 0 ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted">大类完整性：</span>
          {requiredCats.map((c) => (
            <Tag key={c} color="blue">
              {c}
            </Tag>
          ))}
        </div>
      ) : null}
    </Card>
  );
}

function inferMajorName(ref: NormalizedAssetRef, assetTitle?: string | null): string | null {
  const meta = ref.metadata_summary ?? {};
  const explicit = firstString(
    meta["major_name"],
    meta["major"],
    meta["specialty_name"],
    meta["program_name"],
    meta["professional_group_name"],
    meta["major_group_name"],
  );
  if (explicit) return explicit;
  return inferMajorNameFromTitle(
    firstString(
      ref.title,
      meta["title"],
      meta["source_title"],
      meta["filename"],
      meta["source_filename"],
      assetTitle,
    ),
  );
}

function inferMajorDirection(ref: NormalizedAssetRef): string | null {
  const meta = ref.metadata_summary ?? {};
  return firstString(
    meta["major_direction"],
    meta["direction"],
    meta["specialty_direction"],
    meta["program_direction"],
  );
}

function firstString(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value !== "string") continue;
    const trimmed = value.trim();
    if (trimmed) return trimmed;
  }
  return null;
}

function inferMajorNameFromTitle(value: string | null): string | null {
  if (!value) return null;
  const base = value
    .replace(/\.(xlsx|xls|docx|doc|pdf)$/i, "")
    .replace(/^\d{6,8}/, "")
    .replace(/^[-_（(【\[\s]+/, "")
    .trim();
  const exact = base.match(
    /(.+?(?:专业群|专业))(?:岗位（群）)?职业能力(?:及素养)?分析(?:表|报告)?$/,
  );
  if (exact?.[1]) return exact[1].trim();
  const match = base.match(/(.+?(?:专业群|专业))(?:.*?职业能力(?:及素养)?分析(?:表|报告)?)?/);
  if (match?.[1]) return match[1].trim();
  return null;
}

// ---------------------------------------------------------------------------
// Ability list — flat PGSD ability-item view
// ---------------------------------------------------------------------------

function AbilityItemsListSection({ analysisId }: { analysisId: string }) {
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
    return () => {
      active = false;
    };
  }, [analysisId]);

  useEffect(() => {
    let active = true;
    setAbilities({ loading: true, list: [], error: null });
    fetchAllAbilityItems(analysisId).then((res) => {
      if (!active) return;
      if (!res.ok) {
        setAbilities({ loading: false, list: [], error: res.error });
        return;
      }
      setAbilities({ loading: false, list: res.data, error: null });
    });
    return () => {
      active = false;
    };
  }, [analysisId]);

  const { taskById, workContentById } = useMemo(() => {
    const taskMap = new Map<string, OccupationalWorkTask>();
    const wcMap = new Map<string, { code: string; name: string }>();
    for (const task of tasks.list) {
      taskMap.set(task.id, task);
      for (const wc of task.work_contents ?? []) {
        wcMap.set(wc.id, { code: wc.content_code, name: wc.content_name });
      }
    }
    return { taskById: taskMap, workContentById: wcMap };
  }, [tasks.list]);

  const columns: ColumnsType<OccupationalAbilityItem> = [
    {
      title: "类别",
      dataIndex: "ability_major_category_code",
      key: "cat",
      width: 120,
      render: (code: string) => (
        <Tag color={abilityTagColor(code)}>{abilityCategoryLabel(code)}</Tag>
      ),
      filters: ["P", "G", "S", "D"].map((code) => ({
        text: abilityCategoryLabel(code),
        value: code,
      })),
      onFilter: (value, record) => record.ability_major_category_code === value,
    },
    { title: "编码", dataIndex: "ability_code", key: "code", width: 140 },
    {
      title: "能力内容",
      dataIndex: "ability_content",
      key: "content",
      ellipsis: true,
    },
    {
      title: "任务",
      key: "task",
      width: 220,
      render: (_, record) => {
        const task = taskById.get(record.task_id);
        return task ? `${task.task_code} ${task.task_name}` : "—";
      },
    },
    {
      title: "工作内容",
      key: "work_content",
      width: 220,
      render: (_, record) => {
        if (!record.work_content_id) return "—";
        const wc = workContentById.get(record.work_content_id);
        return wc ? `${wc.code} ${wc.name}` : "—";
      },
    },
    {
      title: "置信度",
      dataIndex: "confidence",
      key: "confidence",
      width: 96,
      render: (value: number | null) => (value == null ? "—" : `${(value * 100).toFixed(0)}%`),
    },
  ];

  const loading = tasks.loading || abilities.loading;
  return (
    <Card title="能力条目列表" size="small">
      {tasks.error ? (
        <Alert type="error" showIcon title="加载任务失败" description={tasks.error} />
      ) : null}
      {abilities.error ? (
        <Alert
          type="error"
          showIcon
          title="加载能力条目失败"
          description={abilities.error}
          className="!mt-2"
        />
      ) : null}
      {!tasks.error && !abilities.error ? (
        <Table<OccupationalAbilityItem>
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={abilities.list}
          pagination={{ pageSize: 20, showSizeChanger: true }}
          locale={{
            emptyText: <Empty description="暂无能力条目" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
          }}
        />
      ) : null}
    </Card>
  );
}

async function fetchAllAbilityItems(analysisId: string): Promise<{
  ok: boolean;
  data: OccupationalAbilityItem[];
  error: string | null;
}> {
  const pageSize = 200;
  const data: OccupationalAbilityItem[] = [];
  let page = 1;
  let total: number | null = null;

  while (total === null || data.length < total) {
    const res = await getApiData<OccupationalAbilityItem[]>(
      `/api/record-assets/ability-analyses/${analysisId}/ability-items`,
      [],
      { page: String(page), pageSize: String(pageSize) },
    );
    if (!res.ok) {
      return {
        ok: false,
        data,
        error: res.error ?? "加载能力条目失败",
      };
    }
    data.push(...res.data);
    total = res.total ?? data.length;
    if (res.data.length < pageSize) break;
    page += 1;
  }

  return { ok: true, data, error: null };
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
    return () => {
      active = false;
    };
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
    return () => {
      active = false;
    };
  }, [analysisId]);

  // Build the tree once both sides resolve. P abilities hang below their
  // work-content parent; G/S/D abilities hang directly below task-level
  // category groups so the tree mirrors the PGSD model in one structure.
  const treeData: DataNode[] = useMemo(() => {
    if (!tasks.list.length) return [];
    return tasks.list.map((task) => {
      const wcs = task.work_contents ?? [];
      const taskAbilities = abilities.list.filter((a) => a.task_id === task.id);
      const wcChildren = wcs.map((wc) => {
        const wcAbilities = taskAbilities.filter((a) => a.work_content_id === wc.id);
        return {
          key: `wc:${wc.id}`,
          title: (
            <span>
              <Tag color="purple">{wc.content_code}</Tag>
              {wc.content_name}
              <span className="text-muted ml-2 text-xs">{wcAbilities.length} 条</span>
            </span>
          ),
          children: wcAbilities.map(abilityTreeNode),
          disabled: wcAbilities.length === 0,
        };
      });
      const abilityGroupChildren: DataNode[] = [];
      for (const category of ["G", "S", "D"]) {
        const groupAbilities = taskAbilities.filter(
          (a) => a.ability_major_category_code === category && !a.work_content_id,
        );
        if (groupAbilities.length > 0) {
          abilityGroupChildren.push({
            key: `task:${task.id}:cat:${category}`,
            title: (
              <span>
                <Tag color={abilityTagColor(category)}>{category}</Tag>
                {abilityCategoryLabel(category)}
                <span className="text-muted ml-2 text-xs">{groupAbilities.length} 条</span>
              </span>
            ),
            children: groupAbilities.map(abilityTreeNode),
          });
        }
      }
      const children: DataNode[] = [];
      if (wcChildren.length > 0) {
        children.push({
          key: `task:${task.id}:cat:P`,
          title: (
            <span>
              <Tag color={abilityTagColor("P")}>P</Tag>
              职业能力
              <span className="text-muted ml-2 text-xs">
                {taskAbilities.filter((a) => a.ability_major_category_code === "P").length} 条
              </span>
            </span>
          ),
          children: wcChildren,
        });
      }
      children.push(...abilityGroupChildren);
      return {
        key: `task:${task.id}`,
        title: (
          <span>
            <Tag color="blue">{task.task_code}</Tag>
            {task.task_name}
          </span>
        ),
        children,
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
          type="error"
          showIcon
          title="加载能力条目失败"
          description={abilities.error}
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

function abilityTreeNode(ability: OccupationalAbilityItem): DataNode {
  return {
    key: `ab:${ability.id}`,
    title: (
      <span>
        <Tag color={abilityTagColor(ability.ability_major_category_code)}>
          {ability.ability_code}
        </Tag>
        <span>{ability.ability_content}</span>
      </span>
    ),
  };
}

function abilityCategoryLabel(code: string): string {
  if (code === "P") return "职业能力";
  if (code === "G") return "通用能力";
  if (code === "S") return "社会能力";
  if (code === "D") return "发展能力";
  return code || "未知";
}

function abilityTagColor(code: string): string {
  if (code === "P") return "green";
  if (code === "G") return "blue";
  if (code === "S") return "orange";
  if (code === "D") return "red";
  return "default";
}

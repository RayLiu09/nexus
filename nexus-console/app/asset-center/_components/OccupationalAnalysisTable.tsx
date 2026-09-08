"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Alert, Button, Drawer, Empty, Form, Input, Skeleton, Space, Table, Tag, Tree } from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import type { DataNode } from "antd/es/tree";
import { GitBranch, List, Network, Search, X } from "lucide-react";

import { CapabilityGraphView } from "@/app/assets/[assetId]/_components/CapabilityGraphView";
import { ApiState } from "@/components/ApiState";
import {
  getApiData,
  type AbilityAnalysis,
  type OccupationalAbilityItem,
  type OccupationalWorkTask,
} from "@/lib/api";

export type OccupationalAnalysisFilters = {
  major_name?: string;
};

type Props = {
  rows: AbilityAnalysis[];
  total: number;
  page: number;
  pageSize: number;
  filters: OccupationalAnalysisFilters;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

type DrawerMode = "items" | "tree" | "graph";
type DrawerState = { mode: DrawerMode; analysis: AbilityAnalysis } | null;

const CATEGORY_LABELS: Record<string, string> = {
  P: "职业能力",
  G: "通用能力",
  D: "发展能力",
  S: "社会能力",
};

const CATEGORY_COLORS: Record<string, string> = {
  P: "green",
  G: "blue",
  D: "red",
  S: "orange",
};

export function OccupationalAnalysisTable({
  rows,
  total,
  page,
  pageSize,
  filters,
  ok,
  error,
  traceId,
}: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
  const [drawer, setDrawer] = useState<DrawerState>(null);
  const [form] = Form.useForm<OccupationalAnalysisFilters>();

  useEffect(() => form.setFieldsValue({ major_name: undefined, ...filters }), [filters, form]);

  const replaceQuery = (
    next: OccupationalAnalysisFilters,
    nextPage = 1,
    nextPageSize = pageSize,
  ) => {
    const search = new URLSearchParams();
    if (next.major_name?.trim()) search.set("major_name", next.major_name.trim());
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  };

  const openDrawer = (mode: DrawerMode, analysis: AbilityAnalysis) => {
    setDrawer({ mode, analysis });
  };

  const columns = useMemo<ColumnsType<AbilityAnalysis>>(
    () => [
      {
        title: "专业名称",
        dataIndex: "major_name",
        width: 220,
        fixed: "left",
        render: (value: string | null) => <strong>{value || "-"}</strong>,
      },
      {
        title: "分析模型",
        dataIndex: "analysis_model",
        width: 120,
        render: (value: string) => <Tag color="blue">{value}</Tag>,
      },
      { title: "典型任务数", dataIndex: "task_count", width: 112, align: "right" },
      { title: "通用能力数", dataIndex: "general_ability_count", width: 112, align: "right" },
      {
        title: "发展能力数",
        dataIndex: "development_ability_count",
        width: 112,
        align: "right",
      },
      {
        title: "职业能力数",
        dataIndex: "occupational_ability_count",
        width: 112,
        align: "right",
      },
      { title: "社会能力数", dataIndex: "social_ability_count", width: 112, align: "right" },
      {
        title: "操作",
        key: "actions",
        width: 300,
        fixed: "right",
        render: (_, analysis) => (
          <Space size={2}>
            <Button
              type="link"
              size="small"
              icon={<List size={14} />}
              onClick={() => openDrawer("items", analysis)}
            >
              能力条目
            </Button>
            <Button
              type="link"
              size="small"
              icon={<GitBranch size={14} />}
              onClick={() => openDrawer("tree", analysis)}
            >
              能力树
            </Button>
            <Button
              type="link"
              size="small"
              icon={<Network size={14} />}
              onClick={() => openDrawer("graph", analysis)}
            >
              能力图谱
            </Button>
          </Space>
        ),
      },
    ],
    [],
  );

  const handleTableChange = (pagination: TablePaginationConfig) => {
    replaceQuery(filters, pagination.current ?? 1, pagination.pageSize ?? pageSize);
  };

  const drawerTitle = drawer
    ? `${drawer.analysis.major_name || "职业能力分析"} · ${
        drawer.mode === "items" ? "能力条目" : drawer.mode === "tree" ? "能力树" : "能力图谱"
      }`
    : "职业能力分析";

  return (
    <>
      <ApiState ok={ok} error={error} traceId={traceId} />
      <section className="border-line bg-surface border-y">
        <Form
          form={form}
          layout="inline"
          initialValues={filters}
          className="border-line flex gap-2 border-b px-4 py-3"
          onFinish={(values) => replaceQuery(values)}
        >
          <Form.Item name="major_name" className="!mb-0">
            <Input allowClear placeholder="专业名称" className="w-52" />
          </Form.Item>
          <Form.Item className="!mb-0">
            <Space size={8}>
              <Button htmlType="submit" type="primary" icon={<Search size={15} />}>
                查询
              </Button>
              <Button
                icon={<X size={15} />}
                onClick={() => {
                  form.setFieldsValue({ major_name: undefined });
                  replaceQuery({});
                }}
              >
                重置
              </Button>
            </Space>
          </Form.Item>
        </Form>

        <Table<AbilityAnalysis>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={rows}
          loading={pending}
          scroll={{ x: 1200 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 条`,
          }}
          locale={{ emptyText: ok ? "暂无职业能力分析" : "数据加载失败" }}
          onChange={handleTableChange}
        />
      </section>

      <Drawer
        open={drawer !== null}
        size="min(1120px, 82vw)"
        title={drawerTitle}
        destroyOnHidden
        onClose={() => setDrawer(null)}
      >
        {drawer?.mode === "items" ? <AbilityItemsView analysisId={drawer.analysis.id} /> : null}
        {drawer?.mode === "tree" ? <AbilityTreeView analysisId={drawer.analysis.id} /> : null}
        {drawer?.mode === "graph" ? (
          <CapabilityGraphView
            normalizedRefId={drawer.analysis.normalized_ref_id}
            buildType="ability_analysis"
            title="能力图谱"
            embedded
          />
        ) : null}
      </Drawer>
    </>
  );
}

function AbilityItemsView({ analysisId }: { analysisId: string }) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [tasks, setTasks] = useState<{
    loading: boolean;
    rows: OccupationalWorkTask[];
    error: string | null;
  }>({ loading: true, rows: [], error: null });
  const [items, setItems] = useState<{
    loading: boolean;
    rows: OccupationalAbilityItem[];
    total: number;
    error: string | null;
  }>({ loading: true, rows: [], total: 0, error: null });

  useEffect(() => {
    let active = true;
    fetchAllPages<OccupationalWorkTask>(
      `/api/record-assets/ability-analyses/${analysisId}/tasks`,
    ).then((result) => {
      if (!active) return;
      setTasks({ loading: false, rows: result.data, error: result.error });
    });
    return () => {
      active = false;
    };
  }, [analysisId]);

  useEffect(() => {
    let active = true;
    getApiData<OccupationalAbilityItem[]>(
      `/api/record-assets/ability-analyses/${analysisId}/ability-items`,
      [],
      { page: String(page), pageSize: String(pageSize) },
    ).then((result) => {
      if (!active) return;
      setItems({
        loading: false,
        rows: result.data,
        total: result.total ?? result.data.length,
        error: result.ok ? null : result.error,
      });
    });
    return () => {
      active = false;
    };
  }, [analysisId, page, pageSize]);

  const taskNames = useMemo(
    () => new Map(tasks.rows.map((task) => [task.id, task.task_name])),
    [tasks.rows],
  );
  const columns: ColumnsType<OccupationalAbilityItem> = [
    {
      title: "类别",
      dataIndex: "ability_major_category_code",
      width: 130,
      render: (code: string, item) => (
        <Tag color={CATEGORY_COLORS[code] ?? "default"}>
          {item.ability_major_category_name || CATEGORY_LABELS[code] || code}
        </Tag>
      ),
    },
    {
      title: "能力描述",
      dataIndex: "ability_content",
      ellipsis: true,
    },
    {
      title: "对应任务名称",
      dataIndex: "task_id",
      width: 240,
      render: (taskId: string) => taskNames.get(taskId) ?? "-",
    },
  ];

  const handlePageChange = (nextPage: number, nextPageSize: number) => {
    setItems((current) => ({ ...current, loading: true, error: null }));
    setPage(nextPageSize === pageSize ? nextPage : 1);
    setPageSize(nextPageSize);
  };

  return (
    <div className="flex flex-col gap-3">
      {tasks.error ? (
        <Alert type="error" showIcon title="加载任务名称失败" description={tasks.error} />
      ) : null}
      {items.error ? (
        <Alert type="error" showIcon title="加载能力条目失败" description={items.error} />
      ) : null}
      <Table<OccupationalAbilityItem>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items.rows}
        loading={items.loading || tasks.loading}
        tableLayout="fixed"
        pagination={{
          current: page,
          pageSize,
          total: items.total,
          showSizeChanger: true,
          pageSizeOptions: [20, 50, 100, 200],
          showTotal: (count) => `共 ${count} 条`,
          onChange: handlePageChange,
        }}
        locale={{
          emptyText: <Empty description="暂无能力条目" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
        }}
      />
    </div>
  );
}

function AbilityTreeView({ analysisId }: { analysisId: string }) {
  const [state, setState] = useState<{
    loading: boolean;
    tasks: OccupationalWorkTask[];
    abilities: OccupationalAbilityItem[];
    error: string | null;
  }>({ loading: true, tasks: [], abilities: [], error: null });

  useEffect(() => {
    let active = true;
    Promise.all([
      fetchAllPages<OccupationalWorkTask>(
        `/api/record-assets/ability-analyses/${analysisId}/tasks`,
      ),
      fetchAllPages<OccupationalAbilityItem>(
        `/api/record-assets/ability-analyses/${analysisId}/ability-items`,
      ),
    ]).then(([tasks, abilities]) => {
      if (!active) return;
      setState({
        loading: false,
        tasks: tasks.data,
        abilities: abilities.data,
        error: tasks.error ?? abilities.error,
      });
    });
    return () => {
      active = false;
    };
  }, [analysisId]);

  const treeData = useMemo(
    () => buildAbilityTree(state.tasks, state.abilities),
    [state.abilities, state.tasks],
  );

  if (state.loading) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (state.error) {
    return <Alert type="error" showIcon title="加载能力树失败" description={state.error} />;
  }
  if (treeData.length === 0) {
    return <Empty description="暂无能力树数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  return (
    <Tree
      treeData={treeData}
      defaultExpandAll={treeData.length <= 3}
      showLine
      selectable={false}
      aria-label="能力分析任务树"
    />
  );
}

function buildAbilityTree(
  tasks: OccupationalWorkTask[],
  abilities: OccupationalAbilityItem[],
): DataNode[] {
  return tasks.map((task) => {
    const taskAbilities = abilities.filter((ability) => ability.task_id === task.id);
    const workContents = (task.work_contents ?? []).map((content) => {
      const contentAbilities = taskAbilities.filter(
        (ability) => ability.work_content_id === content.id,
      );
      return {
        key: `work-content:${content.id}`,
        title: (
          <span>
            <Tag color="purple">{content.content_code}</Tag>
            {content.content_name}
            <span className="text-text-muted ml-2 text-xs">{contentAbilities.length} 条</span>
          </span>
        ),
        children: contentAbilities.map(abilityTreeNode),
        disabled: contentAbilities.length === 0,
      } satisfies DataNode;
    });
    const categoryGroups: DataNode[] = [];
    for (const category of ["G", "S", "D"]) {
      const categoryAbilities = taskAbilities.filter(
        (ability) => ability.ability_major_category_code === category && !ability.work_content_id,
      );
      if (categoryAbilities.length > 0) {
        categoryGroups.push({
          key: `task:${task.id}:category:${category}`,
          title: (
            <span>
              <Tag color={CATEGORY_COLORS[category]}>{CATEGORY_LABELS[category]}</Tag>
              <span className="text-text-muted ml-2 text-xs">{categoryAbilities.length} 条</span>
            </span>
          ),
          children: categoryAbilities.map(abilityTreeNode),
        });
      }
    }
    const children: DataNode[] = [];
    if (workContents.length > 0) {
      children.push({
        key: `task:${task.id}:category:P`,
        title: (
          <span>
            <Tag color={CATEGORY_COLORS.P}>{CATEGORY_LABELS.P}</Tag>
            <span className="text-text-muted ml-2 text-xs">
              {
                taskAbilities.filter((ability) => ability.ability_major_category_code === "P")
                  .length
              }
              条
            </span>
          </span>
        ),
        children: workContents,
      });
    }
    children.push(...categoryGroups);
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
}

function abilityTreeNode(ability: OccupationalAbilityItem): DataNode {
  return {
    key: `ability:${ability.id}`,
    title: (
      <span>
        <Tag color={CATEGORY_COLORS[ability.ability_major_category_code] ?? "default"}>
          {ability.ability_code}
        </Tag>
        {ability.ability_content}
      </span>
    ),
  };
}

async function fetchAllPages<T>(path: string): Promise<{ data: T[]; error: string | null }> {
  const pageSize = 200;
  const data: T[] = [];
  let page = 1;
  let total: number | null = null;
  while (total === null || data.length < total) {
    const result = await getApiData<T[]>(path, [], {
      page: String(page),
      pageSize: String(pageSize),
    });
    if (!result.ok) return { data, error: result.error ?? "数据加载失败" };
    data.push(...result.data);
    total = result.total ?? data.length;
    if (result.data.length < pageSize) break;
    page += 1;
  }
  return { data, error: null };
}

"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  Alert,
  App,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
} from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import { Download, List, Network, Search, X } from "lucide-react";

import { OccupationalAbilityGraph } from "./OccupationalAbilityGraph";
import { ApiState } from "@/components/ApiState";
import type { RawDownloadResponse } from "@/lib/chunkTypes";
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

type DrawerMode = "items" | "graph";
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
  const { message } = App.useApp();
  const [pending, startTransition] = useTransition();
  const [drawer, setDrawer] = useState<DrawerState>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
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

  async function download(analysis: AbilityAnalysis) {
    if (!analysis.raw_object_id) return;
    setDownloadingId(analysis.id);
    try {
      const response = await fetch(
        `/api/raw-objects/${encodeURIComponent(analysis.raw_object_id)}/download-url`,
        {
          cache: "no-store",
        },
      );
      const body = (await response.json()) as
        | { ok: true; data: RawDownloadResponse }
        | { ok: false; message?: string };
      if (!body.ok) throw new Error(body.message ?? "原文下载失败");
      window.open(body.data.download_url, "_blank", "noopener,noreferrer");
    } catch (cause) {
      message.error(cause instanceof Error ? cause.message : "原文下载失败");
    } finally {
      setDownloadingId(null);
    }
  }

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
        title: "专业代码",
        dataIndex: "major_code",
        width: 120,
        render: (value: string | null) => value || "-",
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
        width: 310,
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
              icon={<Network size={14} />}
              onClick={() => openDrawer("graph", analysis)}
            >
              能力图谱
            </Button>
            <Button
              type="link"
              size="small"
              icon={<Download size={14} />}
              disabled={!analysis.raw_object_id}
              loading={downloadingId === analysis.id}
              onClick={() => void download(analysis)}
            >
              原文下载
            </Button>
          </Space>
        ),
      },
    ],
    [downloadingId],
  );

  const handleTableChange = (pagination: TablePaginationConfig) => {
    replaceQuery(filters, pagination.current ?? 1, pagination.pageSize ?? pageSize);
  };

  const drawerTitle = drawer
    ? `${drawer.analysis.major_name || "职业能力分析"} · ${
        drawer.mode === "items" ? "能力条目" : "能力图谱"
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
          className="border-line flex flex-wrap justify-end gap-2 border-b px-4 py-3"
          onFinish={(values) => replaceQuery(values)}
        >
          <Form.Item name="major_name" className="!mb-0">
            <Input allowClear placeholder="专业名称" className="w-52" />
          </Form.Item>
          <Form.Item className="!mb-0">
            <Space size={8}>
              <Button htmlType="submit" type="primary" icon={<Search size={15} />}>
                检索
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
          scroll={{ x: 1420 }}
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
        size={
          drawer?.mode === "graph"
            ? "min(1440px, calc(100vw - 16px))"
            : "min(1120px, calc(100vw - 16px))"
        }
        title={drawerTitle}
        destroyOnHidden
        onClose={() => setDrawer(null)}
      >
        {drawer?.mode === "items" ? <AbilityItemsView analysisId={drawer.analysis.id} /> : null}
        {drawer?.mode === "graph" ? (
          <OccupationalAbilityGraph analysis={drawer.analysis} />
        ) : null}
      </Drawer>
    </>
  );
}

function AbilityItemsView({ analysisId }: { analysisId: string }) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedTaskCode, setSelectedTaskCode] = useState<string | null>(null);
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
      setSelectedTaskCode(result.data[0]?.task_code ?? null);
      if (result.data.length === 0) {
        setItems({ loading: false, rows: [], total: 0, error: null });
      }
    });
    return () => {
      active = false;
    };
  }, [analysisId]);

  useEffect(() => {
    let active = true;
    if (!selectedTaskCode) return;
    getApiData<OccupationalAbilityItem[]>(
      `/api/record-assets/ability-analyses/${analysisId}/ability-items`,
      [],
      { page: String(page), pageSize: String(pageSize), task_code: selectedTaskCode },
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
  }, [analysisId, page, pageSize, selectedTaskCode]);

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
      <Select
        aria-label="典型工作任务"
        className="w-full max-w-md"
        placeholder="选择典型工作任务"
        loading={tasks.loading}
        value={selectedTaskCode}
        options={tasks.rows.map((task) => ({ label: task.task_name, value: task.task_code }))}
        onChange={(code) => {
          setSelectedTaskCode(code);
          setPage(1);
          setItems({ loading: true, rows: [], total: 0, error: null });
        }}
      />
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
        dataSource={selectedTaskCode ? items.rows : []}
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

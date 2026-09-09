"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Button, Drawer, Form, Input, InputNumber, Select, Space, Table, Tag } from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import { GitFork, Network, Search, X } from "lucide-react";

import { ApiState } from "@/components/ApiState";
import type { CourseTextbookSummary } from "@/lib/api";
import {
  CourseTextbookKnowledgeOutlineView,
  type CourseTextbookKnowledgeOutlineMode,
} from "./CourseTextbookKnowledgeOutlineView";
import {
  CourseTextbookTaskOutlineView,
  type CourseTextbookTaskOutlineMode,
} from "./CourseTextbookTaskOutlineView";

export type CourseTextbookFilters = {
  title?: string;
  textbook_type?: "theory" | "training";
  publisher?: string;
  chief_editor?: string;
  publication_year?: number;
};

type Props = {
  rows: CourseTextbookSummary[];
  total: number;
  page: number;
  pageSize: number;
  filters: CourseTextbookFilters;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

type ViewKind = "knowledge-radial" | "knowledge-left-to-right" | "task-tree" | "task-radial";

type ViewSelection = {
  textbook: CourseTextbookSummary;
  kind: ViewKind;
};

const EMPTY_FILTERS: CourseTextbookFilters = {
  title: undefined,
  textbook_type: undefined,
  publisher: undefined,
  chief_editor: undefined,
  publication_year: undefined,
};

const VIEW_LABELS: Record<ViewKind, string> = {
  "knowledge-radial": "知识大纲径向图",
  "knowledge-left-to-right": "知识大纲树",
  "task-tree": "任务大纲树视图",
  "task-radial": "任务大纲圆形树",
};

export function CourseTextbooksTable({
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
  const [selection, setSelection] = useState<ViewSelection | null>(null);
  const [form] = Form.useForm<CourseTextbookFilters>();

  useEffect(() => form.setFieldsValue({ ...EMPTY_FILTERS, ...filters }), [filters, form]);

  const replaceQuery = (next: CourseTextbookFilters, nextPage = 1, nextPageSize = pageSize) => {
    const search = new URLSearchParams();
    for (const [key, rawValue] of Object.entries(next)) {
      if (typeof rawValue === "number") search.set(key, String(rawValue));
      if (typeof rawValue === "string" && rawValue.trim()) search.set(key, rawValue.trim());
    }
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  };

  const columns = useMemo<ColumnsType<CourseTextbookSummary>>(
    () => [
      {
        title: "教材名称",
        dataIndex: "title",
        width: 280,
        fixed: "left",
        render: (value: string) => <strong>{value || "-"}</strong>,
      },
      {
        title: "类型",
        dataIndex: "textbook_type_label",
        width: 96,
        align: "center",
        render: (value: CourseTextbookSummary["textbook_type_label"], row) => (
          <Tag color={row.textbook_type === "theory" ? "blue" : "cyan"} className="!m-0">
            {value}
          </Tag>
        ),
      },
      {
        title: "出版社",
        dataIndex: "publisher",
        width: 220,
        render: (value: string | null) => value || "-",
      },
      {
        title: "主编",
        dataIndex: "chief_editors",
        width: 180,
        render: (value: string[]) => (value.length > 0 ? value.join("、") : "-"),
      },
      {
        title: "出版年份",
        dataIndex: "publication_year",
        width: 110,
        align: "center",
        render: (value: number | null) => value ?? "-",
      },
      {
        title: "操作",
        key: "actions",
        width: 370,
        fixed: "right",
        render: (_, row) =>
          row.textbook_type === "theory" ? (
            <Space size={2}>
              <Button
                type="link"
                size="small"
                icon={<Network size={14} />}
                onClick={() => setSelection({ textbook: row, kind: "knowledge-radial" })}
              >
                知识大纲径向图
              </Button>
              <Button
                type="link"
                size="small"
                icon={<GitFork size={14} />}
                onClick={() => setSelection({ textbook: row, kind: "knowledge-left-to-right" })}
              >
                知识大纲树
              </Button>
            </Space>
          ) : (
            <Space size={2}>
              <Button
                type="link"
                size="small"
                icon={<GitFork size={14} />}
                onClick={() => setSelection({ textbook: row, kind: "task-tree" })}
              >
                任务大纲树视图
              </Button>
              <Button
                type="link"
                size="small"
                icon={<Network size={14} />}
                onClick={() => setSelection({ textbook: row, kind: "task-radial" })}
              >
                任务大纲圆形树
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
          <Form.Item name="title" className="!mb-0">
            <Input allowClear placeholder="教材名称" className="w-48" />
          </Form.Item>
          <Form.Item name="textbook_type" className="!mb-0">
            <Select
              allowClear
              placeholder="类型"
              className="w-28"
              options={[
                { value: "theory", label: "理论型" },
                { value: "training", label: "实训型" },
              ]}
            />
          </Form.Item>
          <Form.Item name="publisher" className="!mb-0">
            <Input allowClear placeholder="出版社" className="w-40" />
          </Form.Item>
          <Form.Item name="chief_editor" className="!mb-0">
            <Input allowClear placeholder="主编" className="w-32" />
          </Form.Item>
          <Form.Item name="publication_year" className="!mb-0">
            <InputNumber
              min={1800}
              max={2199}
              precision={0}
              placeholder="出版年份"
              className="!w-32"
            />
          </Form.Item>
          <Form.Item className="!mb-0">
            <Space size={8}>
              <Button htmlType="submit" type="primary" icon={<Search size={15} />}>
                查询
              </Button>
              <Button
                icon={<X size={15} />}
                onClick={() => {
                  form.setFieldsValue(EMPTY_FILTERS);
                  replaceQuery({});
                }}
              >
                重置
              </Button>
            </Space>
          </Form.Item>
        </Form>

        <Table<CourseTextbookSummary>
          rowKey="profile_id"
          size="small"
          columns={columns}
          dataSource={rows}
          loading={pending}
          tableLayout="fixed"
          scroll={{ x: 1260 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 条`,
          }}
          locale={{ emptyText: ok ? "暂无课程教材" : "数据加载失败" }}
          onChange={handleTableChange}
        />
      </section>

      <Drawer
        open={selection !== null}
        size="min(1160px, 84vw)"
        title={
          selection
            ? `${selection.textbook.title} · ${VIEW_LABELS[selection.kind]}`
            : "课程教材大纲"
        }
        destroyOnHidden
        onClose={() => setSelection(null)}
      >
        {selection ? <SelectedOutline selection={selection} /> : null}
      </Drawer>
    </>
  );
}

function SelectedOutline({ selection }: { selection: ViewSelection }) {
  if (selection.kind === "knowledge-radial" || selection.kind === "knowledge-left-to-right") {
    const mode: CourseTextbookKnowledgeOutlineMode =
      selection.kind === "knowledge-radial" ? "radial" : "left-to-right";
    return (
      <CourseTextbookKnowledgeOutlineView
        key={`${selection.textbook.normalized_ref_id}:${mode}`}
        refId={selection.textbook.normalized_ref_id}
        mode={mode}
      />
    );
  }
  const mode: CourseTextbookTaskOutlineMode = selection.kind === "task-tree" ? "tree" : "radial";
  return (
    <CourseTextbookTaskOutlineView
      key={`${selection.textbook.normalized_ref_id}:${mode}`}
      refId={selection.textbook.normalized_ref_id}
      mode={mode}
    />
  );
}

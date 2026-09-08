"use client";

import { useMemo, useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Button, Drawer, Form, Input, Select, Space, Table, Tag } from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import { BookOpen, Network, Search, X } from "lucide-react";

import { ApiState } from "@/components/ApiState";
import { CapabilityGraphView } from "@/app/assets/[assetId]/_components/CapabilityGraphView";
import type { TeachingStandardLibrary } from "@/lib/api";

export type TeachingStandardFilters = {
  major_code?: string;
  major_name?: string;
  education_level?: string;
  status?: string;
};

type Props = {
  rows: TeachingStandardLibrary[];
  total: number;
  page: number;
  pageSize: number;
  filters: TeachingStandardFilters;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

const STATUS_LABELS: Record<TeachingStandardLibrary["status"], string> = {
  review: "待审核",
  active: "已激活",
  superseded: "已废止",
};

function nameWithCode(name: string | null, code: string | null): string {
  if (!name && !code) return "-";
  return `${name ?? "-"}${code ? ` (${code})` : ""}`;
}

export function TeachingStandardsTable({
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
  const [graphLibrary, setGraphLibrary] = useState<TeachingStandardLibrary | null>(null);
  const [form] = Form.useForm<TeachingStandardFilters>();

  const replaceQuery = (next: TeachingStandardFilters, nextPage = 1, nextPageSize = pageSize) => {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(next)) {
      if (value?.trim()) search.set(key, value.trim());
    }
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  };

  const columns = useMemo<ColumnsType<TeachingStandardLibrary>>(
    () => [
      {
        title: "专业代码",
        dataIndex: "major_code",
        width: 112,
        fixed: "left",
        render: (value: string | null) => value || "-",
      },
      {
        title: "专业名称",
        dataIndex: "major_name",
        width: 180,
        fixed: "left",
        render: (value: string | null) => <strong>{value || "-"}</strong>,
      },
      {
        title: "专业大类",
        width: 220,
        render: (_, row) => nameWithCode(row.major_category_name, row.major_category_code),
      },
      {
        title: "专业类",
        width: 210,
        render: (_, row) => nameWithCode(row.major_class_name, row.major_class_code),
      },
      {
        title: "培养层次",
        dataIndex: "educational_level",
        width: 170,
        render: (value: string | null) => value || "-",
      },
      {
        title: "修业年限",
        dataIndex: "basic_study_years",
        width: 100,
        align: "center",
        render: (value: string | null) => value || "-",
      },
      {
        title: "状态",
        dataIndex: "status",
        width: 100,
        render: (value: TeachingStandardLibrary["status"]) => (
          <Tag
            color={value === "active" ? "success" : value === "review" ? "processing" : "default"}
          >
            {STATUS_LABELS[value]}
          </Tag>
        ),
      },
      {
        title: "操作",
        key: "actions",
        width: 220,
        fixed: "right",
        render: (_, row) => (
          <Space size={4}>
            <Button
              type="link"
              size="small"
              icon={<BookOpen size={14} />}
              onClick={() =>
                router.push(
                  `/asset-center/major/standard-course-library?libraryId=${encodeURIComponent(row.id)}`,
                )
              }
            >
              课程库
            </Button>
            <Button
              type="link"
              size="small"
              icon={<Network size={14} />}
              onClick={() => setGraphLibrary(row)}
            >
              职业领域图谱
            </Button>
          </Space>
        ),
      },
    ],
    [router],
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
          <Form.Item name="major_code" className="!mb-0">
            <Input allowClear placeholder="专业代码" className="w-32" />
          </Form.Item>
          <Form.Item name="major_name" className="!mb-0">
            <Input allowClear placeholder="专业名称" className="w-44" />
          </Form.Item>
          <Form.Item name="education_level" className="!mb-0">
            <Input allowClear placeholder="培养层次" className="w-48" />
          </Form.Item>
          <Form.Item name="status" className="!mb-0">
            <Select
              allowClear
              placeholder="状态"
              className="w-32"
              options={Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }))}
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
                  form.setFieldsValue({
                    major_code: undefined,
                    major_name: undefined,
                    education_level: undefined,
                    status: undefined,
                  });
                  replaceQuery({});
                }}
              >
                重置
              </Button>
            </Space>
          </Form.Item>
        </Form>

        <Table<TeachingStandardLibrary>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={rows}
          loading={pending}
          scroll={{ x: 1320 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 条`,
          }}
          locale={{ emptyText: ok ? "暂无专业教学标准" : "数据加载失败" }}
          onChange={handleTableChange}
        />
      </section>

      <Drawer
        open={graphLibrary !== null}
        size="min(1120px, 82vw)"
        title={
          graphLibrary
            ? `${graphLibrary.major_name ?? "专业教学标准"} · 职业领域图谱`
            : "职业领域图谱"
        }
        destroyOnHidden
        onClose={() => setGraphLibrary(null)}
      >
        {graphLibrary ? (
          <CapabilityGraphView
            normalizedRefId={graphLibrary.normalized_ref_id}
            buildType="teaching_standard"
            title="专业 → 职业领域 → 典型工作任务 / 主要教学内容与要求"
            embedded
          />
        ) : null}
      </Drawer>
    </>
  );
}

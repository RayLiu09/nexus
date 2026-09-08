"use client";

import { useEffect, useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  message,
} from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import { Pencil, Search, Trash2, X } from "lucide-react";

import { ApiState } from "@/components/ApiState";
import { deleteApiData, patchApiData, type MajorDistributionRecord } from "@/lib/api";

export type MajorDistributionFilters = {
  year?: string;
  province_name?: string;
  major_name?: string;
  major_code?: string;
  education_level?: string;
  region_scope?: string;
};

type Props = {
  rows: MajorDistributionRecord[];
  total: number;
  page: number;
  pageSize: number;
  filters: MajorDistributionFilters;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

const REGION_SCOPE_OPTIONS = [
  { label: "省级", value: "province" },
  { label: "全国", value: "national" },
];

const EMPTY_FILTERS: MajorDistributionFilters = {
  year: undefined,
  province_name: undefined,
  major_name: undefined,
  major_code: undefined,
  education_level: undefined,
  region_scope: undefined,
};

function regionScopeLabel(value: string): string {
  return REGION_SCOPE_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export function MajorDistributionTable({
  rows: incomingRows,
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
  const [rowOverrides, setRowOverrides] = useState<Record<string, MajorDistributionRecord>>({});
  const [deletedIds, setDeletedIds] = useState<Set<string>>(new Set());
  const [editTarget, setEditTarget] = useState<MajorDistributionRecord | null>(null);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [filterForm] = Form.useForm<MajorDistributionFilters>();
  const [editForm] = Form.useForm<Record<string, unknown>>();
  const [messageApi, messageContext] = message.useMessage();

  useEffect(
    () => filterForm.setFieldsValue({ ...EMPTY_FILTERS, ...filters }),
    [filterForm, filters],
  );
  useEffect(() => {
    if (!editTarget) return;
    editForm.setFieldsValue({
      year: editTarget.year,
      province_name: editTarget.province_name,
      major_name: editTarget.major_name,
      major_code: editTarget.major_code,
      education_level: editTarget.education_level,
      region_scope: editTarget.region_scope,
      distribution_count: editTarget.distribution_count,
    });
  }, [editForm, editTarget]);

  const rows = incomingRows
    .filter((record) => !deletedIds.has(record.id))
    .map((record) => rowOverrides[record.id] ?? record);

  const replaceQuery = (next: MajorDistributionFilters, nextPage = 1, nextPageSize = pageSize) => {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(next)) {
      if (value?.trim()) search.set(key, value.trim());
    }
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  };

  const saveRecord = async () => {
    if (!editTarget) return;
    const values = await editForm.validateFields();
    const payload = {
      year: values.year,
      province_name: String(values.province_name ?? "").trim(),
      major_name: String(values.major_name ?? "").trim(),
      major_code: String(values.major_code ?? "").trim(),
      education_level: values.education_level ? String(values.education_level).trim() : null,
      region_scope: String(values.region_scope ?? "").trim(),
      distribution_count: values.distribution_count,
    };
    setSaving(true);
    try {
      const result = await patchApiData<MajorDistributionRecord>(
        `/api/record-assets/major-distribution-records/${encodeURIComponent(editTarget.id)}`,
        payload,
      );
      setRowOverrides((current) => ({ ...current, [editTarget.id]: result.data }));
      setEditTarget(null);
      messageApi.success("专业布点记录已更新");
      router.refresh();
    } catch (saveError) {
      messageApi.error(saveError instanceof Error ? saveError.message : "更新失败");
    } finally {
      setSaving(false);
    }
  };

  const deleteRecord = async (record: MajorDistributionRecord) => {
    setDeletingId(record.id);
    try {
      await deleteApiData(
        `/api/record-assets/major-distribution-records/${encodeURIComponent(record.id)}`,
      );
      setDeletedIds((current) => new Set(current).add(record.id));
      messageApi.success("专业布点记录已删除");
      router.refresh();
    } catch (deleteError) {
      messageApi.error(deleteError instanceof Error ? deleteError.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  };

  const columns: ColumnsType<MajorDistributionRecord> = [
    { title: "年份", dataIndex: "year", width: 88, fixed: "left" },
    { title: "省份", dataIndex: "province_name", width: 120, fixed: "left" },
    {
      title: "专业名称",
      dataIndex: "major_name",
      width: 180,
      fixed: "left",
      ellipsis: true,
      render: (value: string) => <strong>{value}</strong>,
    },
    { title: "专业代码", dataIndex: "major_code", width: 118 },
    {
      title: "培养层次",
      dataIndex: "education_level",
      width: 160,
      render: (value: string | null) => value || "-",
    },
    {
      title: "区域",
      dataIndex: "region_scope",
      width: 96,
      render: (value: string) => <Tag>{regionScopeLabel(value)}</Tag>,
    },
    {
      title: "布点数",
      dataIndex: "distribution_count",
      width: 100,
      align: "right",
    },
    {
      title: "操作",
      key: "actions",
      width: 160,
      fixed: "right",
      render: (_, record) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            icon={<Pencil size={14} />}
            onClick={() => setEditTarget(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="删除专业布点记录"
            description={`确定删除“${record.province_name} / ${record.major_name} / ${record.year}”吗？`}
            okText="删除"
            okButtonProps={{ danger: true, loading: deletingId === record.id }}
            cancelText="取消"
            onConfirm={() => deleteRecord(record)}
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<Trash2 size={14} />}
              loading={deletingId === record.id}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const handleTableChange = (pagination: TablePaginationConfig) => {
    replaceQuery(filters, pagination.current ?? 1, pagination.pageSize ?? pageSize);
  };

  return (
    <>
      {messageContext}
      <ApiState ok={ok} error={error} traceId={traceId} />
      <section className="border-line bg-surface border-y">
        <Form
          form={filterForm}
          layout="inline"
          initialValues={filters}
          className="border-line flex gap-2 border-b px-4 py-3"
          onFinish={(values) => replaceQuery(values)}
        >
          <Form.Item name="year" className="!mb-0">
            <Input allowClear placeholder="年份" className="w-24" />
          </Form.Item>
          <Form.Item name="province_name" className="!mb-0">
            <Input allowClear placeholder="省份" className="w-28" />
          </Form.Item>
          <Form.Item name="major_name" className="!mb-0">
            <Input allowClear placeholder="专业名称" className="w-40" />
          </Form.Item>
          <Form.Item name="major_code" className="!mb-0">
            <Input allowClear placeholder="专业代码" className="w-32" />
          </Form.Item>
          <Form.Item name="education_level" className="!mb-0">
            <Input allowClear placeholder="培养层次" className="w-40" />
          </Form.Item>
          <Form.Item name="region_scope" className="!mb-0">
            <Select allowClear placeholder="区域" className="w-28" options={REGION_SCOPE_OPTIONS} />
          </Form.Item>
          <Form.Item className="!mb-0">
            <Space size={8}>
              <Button htmlType="submit" type="primary" icon={<Search size={15} />}>
                查询
              </Button>
              <Button
                icon={<X size={15} />}
                onClick={() => {
                  filterForm.setFieldsValue(EMPTY_FILTERS);
                  replaceQuery({});
                }}
              >
                重置
              </Button>
            </Space>
          </Form.Item>
        </Form>

        <Table<MajorDistributionRecord>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={rows}
          loading={pending}
          scroll={{ x: 1040 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 条`,
          }}
          locale={{ emptyText: ok ? "暂无专业布点记录" : "数据加载失败" }}
          onChange={handleTableChange}
        />
      </section>

      <Modal
        title="编辑专业布点记录"
        open={editTarget !== null}
        onCancel={() => setEditTarget(null)}
        onOk={saveRecord}
        okText="保存"
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" className="pt-2">
          <Form.Item name="year" label="年份" rules={[{ required: true, message: "请输入年份" }]}>
            <InputNumber className="w-full" min={1900} max={2200} precision={0} />
          </Form.Item>
          <Form.Item
            name="province_name"
            label="省份"
            rules={[{ required: true, message: "请输入省份" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="major_name"
            label="专业名称"
            rules={[{ required: true, message: "请输入专业名称" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="major_code"
            label="专业代码"
            rules={[{ required: true, message: "请输入专业代码" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="education_level" label="培养层次">
            <Input />
          </Form.Item>
          <Form.Item
            name="region_scope"
            label="区域"
            rules={[{ required: true, message: "请选择区域" }]}
          >
            <Select options={REGION_SCOPE_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="distribution_count"
            label="布点数"
            rules={[{ required: true, message: "请输入布点数" }]}
          >
            <InputNumber className="w-full" min={0} precision={0} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

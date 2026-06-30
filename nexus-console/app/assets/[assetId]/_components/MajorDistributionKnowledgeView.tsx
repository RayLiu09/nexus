"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Skeleton,
  Space,
  Statistic,
  Table,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  deleteApiData,
  getApiData,
  patchApiData,
  type MajorDistributionDataset,
  type MajorDistributionRecord,
} from "@/lib/api";

type Props = { normalizedRefId: string };

type RecordFilters = {
  year: string;
  province_name: string;
  education_level: string;
};

export function MajorDistributionKnowledgeView({ normalizedRefId }: Props) {
  const [datasetReloadKey, setDatasetReloadKey] = useState(0);
  const [state, setState] = useState<{
    loading: boolean;
    dataset: MajorDistributionDataset | null;
    error: string | null;
  }>({ loading: true, dataset: null, error: null });

  useEffect(() => {
    let active = true;
    setState({ loading: true, dataset: null, error: null });
    getApiData<MajorDistributionDataset[]>("/api/record-assets/major-distribution-datasets", [], {
      normalized_ref_id: normalizedRefId,
      pageSize: "1",
    }).then((res) => {
      if (!active) return;
      if (!res.ok) {
        setState({ loading: false, dataset: null, error: res.error });
        return;
      }
      setState({ loading: false, dataset: res.data[0] ?? null, error: null });
    });
    return () => {
      active = false;
    };
  }, [datasetReloadKey, normalizedRefId]);

  if (state.loading) return <Skeleton active paragraph={{ rows: 6 }} />;
  if (state.error) {
    return <Alert type="error" showIcon title="加载专业布点数据集失败" description={state.error} />;
  }
  if (!state.dataset) {
    return <Empty description="该 ref 没有关联的专业布点数据集" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  return (
    <div className="flex flex-col gap-4">
      <DatasetSummary dataset={state.dataset} />
      <RecordsSection
        normalizedRefId={normalizedRefId}
        dataset={state.dataset}
        onDatasetChanged={() => setDatasetReloadKey((value) => value + 1)}
      />
    </div>
  );
}

function DatasetSummary({ dataset }: { dataset: MajorDistributionDataset }) {
  return (
    <Card title="专业布点概要" size="small">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Statistic title="布点记录" value={dataset.record_count} />
        <Statistic title="覆盖省份" value={dataset.province_count} />
        <Statistic title="重复记录" value={dataset.duplicate_count} />
        <Statistic title="无效记录" value={dataset.invalid_count} />
      </div>
      <div className="text-muted mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span>专业：{dataset.major_name ?? "—"}</span>
        <span>专业代码：{dataset.major_code ?? "—"}</span>
        <span>层次：{dataset.education_level ?? "—"}</span>
        <span>年份：{formatYearRange(dataset.year_min, dataset.year_max)}</span>
        <span>来源渠道：{dataset.source_channel}</span>
        <span>Schema：{dataset.schema_version}</span>
      </div>
    </Card>
  );
}

function RecordsSection({
  normalizedRefId,
  dataset,
  onDatasetChanged,
}: {
  normalizedRefId: string;
  dataset: MajorDistributionDataset;
  onDatasetChanged: () => void;
}) {
  const { message, modal } = App.useApp();
  const [form] = Form.useForm<Record<string, unknown>>();
  const [filters, setFilters] = useState<RecordFilters>({
    year: "",
    province_name: "",
    education_level: "",
  });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [reloadKey, setReloadKey] = useState(0);
  const [editTarget, setEditTarget] = useState<MajorDistributionRecord | null>(null);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [state, setState] = useState<{
    loading: boolean;
    records: MajorDistributionRecord[];
    total: number;
    error: string | null;
  }>({ loading: true, records: [], total: 0, error: null });

  useEffect(() => {
    if (!editTarget) return;
    form.setFieldsValue({
      year: editTarget.year,
      province_name: editTarget.province_name,
      major_name: editTarget.major_name,
      major_code: editTarget.major_code,
      education_level: editTarget.education_level,
      region_scope: editTarget.region_scope,
      distribution_count: editTarget.distribution_count,
    });
  }, [editTarget, form]);

  const queryParams = useMemo(() => {
    const params: Record<string, string> = {
      normalized_ref_id: normalizedRefId,
      page: String(page),
      pageSize: String(pageSize),
    };
    for (const [key, value] of Object.entries(filters)) {
      const trimmed = value.trim();
      if (trimmed) params[key] = trimmed;
    }
    return params;
  }, [filters, normalizedRefId, page, pageSize]);

  useEffect(() => {
    let active = true;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    getApiData<MajorDistributionRecord[]>(
      "/api/record-assets/major-distribution-records",
      [],
      queryParams,
    ).then((res) => {
      if (!active) return;
      if (!res.ok) {
        setState({ loading: false, records: [], total: 0, error: res.error });
        return;
      }
      setState({
        loading: false,
        records: res.data,
        total: res.total ?? res.data.length,
        error: null,
      });
    });
    return () => {
      active = false;
    };
  }, [queryParams, reloadKey]);

  const refresh = () => setReloadKey((value) => value + 1);

  const handleSave = async () => {
    if (!editTarget) return;
    const values = await form.validateFields();
    const body = {
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
        `/api/record-assets/major-distribution-records/${editTarget.id}`,
        body,
      );
      setState((prev) => ({
        ...prev,
        records: prev.records.map((record) =>
          record.id === editTarget.id ? result.data : record,
        ),
      }));
      setEditTarget(null);
      message.success("专业布点记录已更新");
      refresh();
      onDatasetChanged();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "更新失败");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = (record: MajorDistributionRecord) => {
    modal.confirm({
      title: "删除专业布点记录",
      content: `确定删除「${record.province_name} / ${record.major_name} / ${record.year}」这条布点记录吗？`,
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        setDeletingId(record.id);
        try {
          await deleteApiData(`/api/record-assets/major-distribution-records/${record.id}`);
          setState((prev) => ({
            ...prev,
            records: prev.records.filter((item) => item.id !== record.id),
            total: Math.max(0, prev.total - 1),
          }));
          message.success("专业布点记录已删除");
          refresh();
          onDatasetChanged();
        } catch (error) {
          message.error(error instanceof Error ? error.message : "删除失败");
        } finally {
          setDeletingId(null);
        }
      },
    });
  };

  const columns: ColumnsType<MajorDistributionRecord> = [
    {
      title: "年份",
      dataIndex: "year",
      width: 96,
      sorter: (a, b) => a.year - b.year,
    },
    {
      title: "省份",
      dataIndex: "province_name",
      width: 128,
    },
    {
      title: "专业名称",
      dataIndex: "major_name",
      ellipsis: true,
    },
    {
      title: "专业代码",
      dataIndex: "major_code",
      width: 120,
    },
    {
      title: "层次",
      dataIndex: "education_level",
      width: 104,
      render: (value: string | null) => value ?? "—",
    },
    {
      title: "区域",
      dataIndex: "region_scope",
      width: 104,
      render: (value: string) => <Tag>{regionScopeLabel(value)}</Tag>,
    },
    {
      title: "布点数",
      dataIndex: "distribution_count",
      width: 112,
      align: "right",
      sorter: (a, b) => a.distribution_count - b.distribution_count,
    },
    {
      title: "操作",
      key: "actions",
      width: 128,
      fixed: "right",
      render: (_, record) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => setEditTarget(record)}>
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            danger
            loading={deletingId === record.id}
            onClick={() => handleDelete(record)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Card title="专业布点列表" size="small">
      <div className="mb-3 grid grid-cols-1 gap-2 md:grid-cols-3">
        <Input
          allowClear
          placeholder="年份"
          value={filters.year}
          onChange={(event) => {
            setPage(1);
            setFilters((prev) => ({ ...prev, year: event.target.value }));
          }}
        />
        <Input
          allowClear
          placeholder="省份"
          value={filters.province_name}
          onChange={(event) => {
            setPage(1);
            setFilters((prev) => ({ ...prev, province_name: event.target.value }));
          }}
        />
        <Select
          allowClear
          placeholder="层次"
          value={filters.education_level || undefined}
          onChange={(value) => {
            setPage(1);
            setFilters((prev) => ({ ...prev, education_level: value ?? "" }));
          }}
          options={educationLevelOptions(dataset.education_level)}
        />
      </div>

      {state.error ? (
        <Alert
          type="error"
          showIcon
          title="加载专业布点列表失败"
          description={state.error}
          className="mb-3"
        />
      ) : null}

      <Table
        rowKey="id"
        size="small"
        loading={state.loading}
        columns={columns}
        dataSource={state.records}
        locale={{ emptyText: <Empty description="暂无专业布点记录" /> }}
        pagination={{
          current: page,
          pageSize,
          total: state.total,
          showSizeChanger: true,
          showTotal: (total, range) => `${range[0]}-${range[1]} / ${total} 条`,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
          },
        }}
      />

      <Modal
        title="编辑专业布点记录"
        open={!!editTarget}
        onCancel={() => setEditTarget(null)}
        onOk={handleSave}
        okText="保存"
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" className="pt-2">
          <Form.Item
            name="year"
            label="年份"
            rules={[{ required: true, message: "请输入年份" }]}
          >
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
          <Form.Item name="education_level" label="层次">
            <Select allowClear options={educationLevelOptions(dataset.education_level)} />
          </Form.Item>
          <Form.Item
            name="region_scope"
            label="区域"
            rules={[{ required: true, message: "请选择区域" }]}
          >
            <Select
              options={[
                { label: "省级", value: "province" },
                { label: "全国", value: "national" },
              ]}
            />
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
    </Card>
  );
}

function educationLevelOptions(value: string | null) {
  const levels = ["本科", "高职", "中职"];
  if (value && !levels.includes(value)) levels.unshift(value);
  return levels.map((level) => ({ label: level, value: level }));
}

function formatYearRange(min: number | null, max: number | null): string {
  if (min == null && max == null) return "—";
  if (min != null && max != null && min !== max) return `${min}-${max}`;
  return String(min ?? max);
}

function regionScopeLabel(value: string): string {
  if (value === "province") return "省级";
  if (value === "national") return "全国";
  return value;
}

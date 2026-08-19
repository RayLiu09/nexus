"use client";

import { useEffect, useState } from "react";
import { Alert, App, Button, Drawer, Form, Input, Select, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { EditOutlined } from "@ant-design/icons";
import { AssetRefCell } from "@/components/shared/AssetRefCell";
import { classificationLabel, type ClassificationDictionary } from "@/lib/classificationLabels";
import { createIdempotencyKey } from "@/lib/idempotency";
import { levelLabel, type LevelDictionary } from "@/lib/levelLabels";

type TagEntry = { value: string };
type StructuredTags = Record<string, TagEntry[]> & { time_ranges?: unknown[] };

export interface GovernanceReviewItem {
  governance_result_id: string;
  normalized_ref_id: string;
  asset_id: string | null;
  asset_title: string | null;
  classification: string | null;
  level: string | null;
  org_scope: string | null;
  tags: StructuredTags;
  quality_summary: Record<string, unknown>;
  created_at: string | null;
}

interface RuleOption {
  code: string;
  name?: string;
  label?: string;
}
interface ReviewContext {
  rules: { classifications: RuleOption[]; levels: RuleOption[] };
}
interface Props {
  initialItems: GovernanceReviewItem[];
  initialTotal: number;
  ok: boolean;
  error: string | null;
  traceId: string | null;
  classificationDictionary: ClassificationDictionary;
  levelDictionary: LevelDictionary;
}

const TAG_BUCKETS = [
  "regions",
  "industries",
  "occupations",
  "majors",
  "abilities",
  "topics",
] as const;
const BUCKET_LABELS: Record<(typeof TAG_BUCKETS)[number], string> = {
  regions: "区域",
  industries: "行业",
  occupations: "职业",
  majors: "专业",
  abilities: "能力",
  topics: "主题",
};

function asText(tags: StructuredTags, bucket: string): string {
  const values = Array.isArray(tags[bucket]) ? tags[bucket] : [];
  return values
    .map((item) => item?.value)
    .filter(Boolean)
    .join("，");
}

function splitValues(value: string): TagEntry[] {
  return [
    ...new Set(
      value
        .split(/[，,、\n]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ].map((item) => ({ value: item }));
}

function buildTags(values: Record<string, string>): StructuredTags {
  const tags: StructuredTags = { time_ranges: [] };
  for (const bucket of TAG_BUCKETS) tags[bucket] = splitValues(values[bucket] ?? "");
  const periods = (values.time_ranges ?? "")
    .split(/[，,、\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
  tags.time_ranges = periods.map((item) => {
    const match = item.match(/^(\d{4})(?:\s*-\s*(\d{4}))?$/);
    if (!match) throw new Error("时间范围仅支持 YYYY 或 YYYY-YYYY");
    return match[2]
      ? { kind: "year_range", start: Number(match[1]), end: Number(match[2]) }
      : { kind: "point_in_time", year: Number(match[1]) };
  });
  return tags;
}

export default function TagReviewContent({
  initialItems,
  initialTotal,
  ok,
  error,
  traceId,
  classificationDictionary,
  levelDictionary,
}: Props) {
  const [items, setItems] = useState(initialItems);
  const [total, setTotal] = useState(initialTotal);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [queueLoading, setQueueLoading] = useState(false);
  const [item, setItem] = useState<GovernanceReviewItem | null>(null);
  const [context, setContext] = useState<ReviewContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm<Record<string, string>>();
  const { message } = App.useApp();

  const loadPage = async (nextPage: number, nextPageSize = pageSize) => {
    setQueueLoading(true);
    try {
      const response = await fetch(
        `/api/governance-reviews/pending?page=${nextPage}&pageSize=${nextPageSize}`,
        { cache: "no-store" },
      );
      const envelope = (await response.json()) as {
        data?: GovernanceReviewItem[];
        meta?: { total?: number | null };
        error?: { message?: string };
      };
      if (!response.ok || !envelope.data) {
        throw new Error(envelope.error?.message ?? "无法加载治理审核队列");
      }
      setItems(envelope.data);
      setTotal(envelope.meta?.total ?? envelope.data.length);
      setPage(nextPage);
      setPageSize(nextPageSize);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "无法加载治理审核队列");
    } finally {
      setQueueLoading(false);
    }
  };

  useEffect(() => {
    if (!item) return;
    // The form is conditional on `item`; populate it only after Drawer/Form mount.
    form.setFieldsValue({
      classification: item.classification ?? "",
      level: item.level ?? "",
      org_scope: item.org_scope ?? "",
      quality_disposition: "pass",
      quality_reason: "",
      review_reason: "",
      ...Object.fromEntries(TAG_BUCKETS.map((bucket) => [bucket, asText(item.tags, bucket)])),
      time_ranges: "",
    });
  }, [form, item]);

  const openReview = async (row: GovernanceReviewItem) => {
    setLoading(true);
    try {
      const res = await fetch(
        `/api/governance-results/${encodeURIComponent(row.governance_result_id)}/review-context`,
        { cache: "no-store" },
      );
      const envelope = (await res.json()) as { data?: ReviewContext; error?: { message?: string } };
      if (!res.ok || !envelope.data)
        throw new Error(envelope.error?.message ?? "无法加载审核上下文");
      setContext(envelope.data);
      setItem(row);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "无法加载审核上下文");
    } finally {
      setLoading(false);
    }
  };

  const submit = async () => {
    if (!item) return;
    const values = await form.validateFields();
    let tags: StructuredTags;
    try {
      tags = buildTags(values);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "标签格式不正确");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(
        `/api/governance-results/${encodeURIComponent(item.governance_result_id)}/review-decisions`,
        {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "Idempotency-Key": createIdempotencyKey(),
          },
          body: JSON.stringify({
            classification: values.classification,
            level: values.level,
            org_scope: values.org_scope,
            tags,
            quality_review: {
              disposition: values.quality_disposition,
              reason: values.quality_reason,
            },
            review_reason: values.review_reason,
            feedback_labels: [],
          }),
        },
      );
      const envelope = (await res.json()) as {
        data?: { version_status?: string };
        error?: { message?: string };
      };
      if (!res.ok) throw new Error(envelope.error?.message ?? "提交治理结论失败");
      setItem(null);
      await loadPage(page, pageSize);
      message.success(
        envelope.data?.version_status === "available"
          ? "治理结论已提交，知识索引续跑已排队"
          : "治理结论已提交，资产仍待其它准入项解除",
      );
    } catch (err) {
      message.error(err instanceof Error ? err.message : "提交治理结论失败");
    } finally {
      setLoading(false);
    }
  };

  const columns: ColumnsType<GovernanceReviewItem> = [
    {
      title: "数据资产",
      render: (_v, row) => (
        <AssetRefCell
          title={row.asset_title}
          assetId={row.asset_id}
          normalizedRefId={row.normalized_ref_id}
        />
      ),
    },
    {
      title: "数据分类",
      dataIndex: "classification",
      width: 120,
      render: (value: string | null) => displayClassification(value, classificationDictionary),
    },
    {
      title: "数据分级",
      dataIndex: "level",
      width: 100,
      render: (value: string | null) => displayLevel(value, levelDictionary),
    },
    {
      title: "当前标签",
      dataIndex: "tags",
      render: (tags: StructuredTags) => (
        <>
          {TAG_BUCKETS.flatMap((bucket) => tags[bucket] ?? []).map((entry) => (
            <Tag key={entry.value}>{entry.value}</Tag>
          ))}
        </>
      ),
    },
    {
      title: "操作",
      width: 84,
      render: (_v, row) => (
        <Button
          size="small"
          icon={<EditOutlined />}
          loading={loading && item?.governance_result_id === row.governance_result_id}
          onClick={() => void openReview(row)}
        >
          审核
        </Button>
      ),
    },
  ];

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {!ok && (
        <Alert
          type="error"
          showIcon
          title="治理审核队列加载失败"
          description={`${error ?? "未知错误"}${traceId ? `（trace: ${traceId}）` : ""}`}
        />
      )}
      <div className="content-panel">
        <Table
          rowKey="governance_result_id"
          dataSource={items}
          columns={columns}
          loading={queueLoading}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            onChange: (nextPage, nextPageSize) => void loadPage(nextPage, nextPageSize),
          }}
          locale={{ emptyText: "暂无待治理审核资产" }}
        />
      </div>
      <Drawer
        title="治理审核"
        open={Boolean(item)}
        onClose={() => setItem(null)}
        size="large"
        destroyOnClose
        extra={
          <Button type="primary" loading={loading} onClick={() => void submit()}>
            提交治理结论
          </Button>
        }
      >
        {item && (
          <Form form={form} layout="vertical" requiredMark="optional">
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              title="提交后将生成不可变治理结论和新的官方治理快照。"
            />
            <Form.Item
              label="数据分类"
              name="classification"
              rules={[{ required: true, message: "请选择数据分类" }]}
            >
              <Select
                options={(context?.rules.classifications ?? []).map((entry) => ({
                  value: entry.code,
                  label: entry.name ?? entry.label ?? entry.code,
                }))}
              />
            </Form.Item>
            <Form.Item
              label="数据分级"
              name="level"
              rules={[{ required: true, message: "请选择数据分级" }]}
            >
              <Select
                options={(context?.rules.levels ?? []).map((entry) => ({
                  value: entry.code,
                  label: entry.name ?? entry.label ?? entry.code,
                }))}
              />
            </Form.Item>
            <Form.Item
              label="组织范围"
              name="org_scope"
              rules={[{ required: true, message: "请填写组织范围" }]}
            >
              <Input />
            </Form.Item>
            {TAG_BUCKETS.map((bucket) => (
              <Form.Item key={bucket} label={`${BUCKET_LABELS[bucket]}标签`} name={bucket}>
                <Input placeholder="使用逗号、顿号或换行分隔" />
              </Form.Item>
            ))}
            <Form.Item
              label="时间标签"
              name="time_ranges"
              extra="支持 YYYY 或 YYYY-YYYY，多个值使用逗号分隔"
            >
              <Input />
            </Form.Item>
            <Form.Item label="质量处置" name="quality_disposition" rules={[{ required: true }]}>
              <Select
                options={[
                  { value: "pass", label: "通过" },
                  { value: "review_required", label: "仍需复核" },
                ]}
              />
            </Form.Item>
            <Form.Item
              label="质量处置说明"
              name="quality_reason"
              rules={[{ required: true, message: "请填写质量处置说明" }]}
            >
              <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
            </Form.Item>
            <Form.Item
              label="审核结论说明"
              name="review_reason"
              rules={[{ required: true, message: "请填写审核结论说明" }]}
            >
              <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
            </Form.Item>
          </Form>
        )}
      </Drawer>
    </div>
  );
}

function displayClassification(value: string | null, dictionary: ClassificationDictionary): string {
  if (!value) return "未确定";
  const label = classificationLabel(value, dictionary);
  return label === value ? "未识别分类" : label;
}

function displayLevel(value: string | null, dictionary: LevelDictionary): string {
  if (!value) return "未确定";
  const label = levelLabel(value, dictionary);
  return label === value ? "未识别分级" : label;
}

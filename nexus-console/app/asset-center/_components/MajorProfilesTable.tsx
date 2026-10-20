"use client";

import { useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { App, Button, Drawer, Form, Input, Space, Table, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import { BookOpen, Download, FileText, Pencil, Search, X } from "lucide-react";

import { ApiState } from "@/components/ApiState";
import { patchApiData, type MajorProfileDocument } from "@/lib/api";
import type { RawDownloadResponse } from "@/lib/chunkTypes";
import { ChunkListSection } from "@/app/assets/[assetId]/_components/ChunkListSection";
import { SourcePreviewSection } from "@/app/assets/[assetId]/_components/SourcePreviewSection";

export type MajorProfileFilters = { q?: string };

type Props = {
  canEdit: boolean;
  rows: MajorProfileDocument[];
  total: number;
  page: number;
  pageSize: number;
  filters: MajorProfileFilters;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

export function MajorProfilesTable({ rows, total, page, pageSize, filters, ok, error, traceId, canEdit }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const { message } = App.useApp();
  const [pending, startTransition] = useTransition();
  const [drawer, setDrawer] = useState<{ row: MajorProfileDocument; view: "preview" | "chunks" } | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<MajorProfileDocument | null>(null);
  const [saving, setSaving] = useState(false);
  const [overrides, setOverrides] = useState<Record<string, MajorProfileDocument>>({});
  const [form] = Form.useForm<Pick<MajorProfileDocument, "major_name" | "major_code" | "institution_name" | "education_level">>();

  function edit(row: MajorProfileDocument) {
    form.setFieldsValue({
      major_name: row.major_name,
      major_code: row.major_code,
      institution_name: row.institution_name,
      education_level: row.education_level,
    });
    setEditTarget(row);
  }

  async function save() {
    if (!editTarget?.normalized_ref_id) return;
    const values = await form.validateFields();
    const changes = Object.fromEntries(
      (["major_name", "major_code", "institution_name", "education_level"] as const)
        .map((field) => [field, values[field]?.trim() || null] as const)
        .filter(([field, value]) => value !== editTarget[field]),
    );
    if (!Object.keys(changes).length) {
      setEditTarget(null);
      return;
    }
    setSaving(true);
    try {
      const result = await patchApiData<MajorProfileDocument>(
        `/api/major-profile-documents/${encodeURIComponent(editTarget.id)}/metadata`,
        { normalized_ref_id: editTarget.normalized_ref_id, ...changes },
      );
      setOverrides((current) => ({ ...current, [editTarget.id]: { ...editTarget, ...result.data } }));
      setEditTarget(null);
      message.success("专业简介元数据已更新");
      router.refresh();
    } catch (cause) {
      message.error(cause instanceof Error ? cause.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  function navigate(q: string | undefined, nextPage = 1, nextPageSize = pageSize) {
    const search = new URLSearchParams();
    if (q?.trim()) search.set("q", q.trim());
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  }

  async function download(row: MajorProfileDocument) {
    if (!row.raw_object_id) return;
    setDownloadingId(row.id);
    try {
      const response = await fetch(`/api/raw-objects/${encodeURIComponent(row.raw_object_id)}/download-url`, {
        cache: "no-store",
      });
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

  const columns: ColumnsType<MajorProfileDocument> = [
    { title: "资产名称", dataIndex: "asset_name", width: 330, ellipsis: true },
    { title: "专业名称", dataIndex: "major_name", width: 175, render: (value: string | null) => value || "-" },
    { title: "专业代码", dataIndex: "major_code", width: 115, render: (value: string | null) => value || "-" },
    { title: "院校名称", dataIndex: "institution_name", width: 220, render: (value: string | null) => value || "-" },
    { title: "培养层次", dataIndex: "education_level", width: 140, render: (value: string | null) => value || "-" },
    {
      title: "内容标签", dataIndex: "content_tags", width: 220,
      render: (values: string[]) => values?.length ? (
        <span>
          {values.slice(0, 3).map((value) => <Tag key={value}>{value}</Tag>)}
          {values.length > 3 && <Tooltip title={values.join("，")}><Tag>+{values.length - 3}</Tag></Tooltip>}
        </span>
      ) : "-",
    },
    {
      title: "操作", key: "actions", width: 410, fixed: "right",
      render: (_, row) => (
        <Space size={4}>
          {canEdit && <Button type="link" size="small" icon={<Pencil size={14} />}
            disabled={!row.normalized_ref_id} onClick={() => edit(row)}>编辑</Button>}
          <Button type="link" size="small" icon={<FileText size={14} />}
            disabled={!row.normalized_ref_id} onClick={() => setDrawer({ row, view: "preview" })}>
            解析预览
          </Button>
          <Button type="link" size="small" icon={<BookOpen size={14} />}
            disabled={!row.normalized_ref_id} onClick={() => setDrawer({ row, view: "chunks" })}>
            RAG知识块
          </Button>
          <Button type="link" size="small" icon={<Download size={14} />}
            disabled={!row.raw_object_id} loading={downloadingId === row.id}
            onClick={() => void download(row)}>
            原文下载
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <>
      <ApiState ok={ok} error={error} traceId={traceId} />
      <section className="border-line bg-surface border-y">
        <Form layout="inline" initialValues={filters} className="border-line flex gap-2 border-b px-4 py-3"
          onFinish={(values: MajorProfileFilters) => navigate(values.q)}>
          <Form.Item name="q" className="!mb-0">
            <Input allowClear placeholder="资产名称" className="w-64" />
          </Form.Item>
          <Form.Item className="!mb-0">
            <Space size={8}>
              <Button htmlType="submit" type="primary" icon={<Search size={15} />}>查询</Button>
              <Button icon={<X size={15} />} onClick={() => navigate(undefined)}>重置</Button>
            </Space>
          </Form.Item>
        </Form>
        <Table<MajorProfileDocument>
          rowKey="id" size="small" columns={columns}
          dataSource={rows.map((row) => overrides[row.id] ?? row)} loading={pending}
          tableLayout="fixed" scroll={{ x: 1610 }}
          pagination={{ current: page, pageSize, total, showSizeChanger: true,
            showTotal: (count) => `共 ${count} 条` }}
          locale={{ emptyText: ok ? "暂无专业简介" : "数据加载失败" }}
          onChange={(pagination) => navigate(filters.q, pagination.current ?? 1, pagination.pageSize ?? pageSize)}
        />
      </section>
      <Drawer open={drawer !== null} onClose={() => setDrawer(null)} destroyOnHidden
        size="min(960px, calc(100vw - 32px))"
        title={drawer ? `${drawer.view === "preview" ? "解析预览" : "RAG知识块"} · ${drawer.row.asset_name}` : undefined}>
        {drawer?.view === "preview" && <SourcePreviewSection refId={drawer.row.normalized_ref_id} />}
        {drawer?.view === "chunks" && <ChunkListSection
          refId={drawer.row.normalized_ref_id} title="RAG知识块" mode="preview"
          actionLabel="预览定位" knowledgeTypeCode="major_profile_knowledge" />}
      </Drawer>
      <Drawer open={editTarget !== null} onClose={() => setEditTarget(null)} destroyOnHidden
        title="编辑专业简介元数据" size="min(520px, calc(100vw - 32px))"
        extra={<Button type="primary" loading={saving} onClick={() => void save()}>保存</Button>}>
        <Form form={form} layout="vertical">
          <Form.Item name="major_name" label="专业名称"><Input maxLength={160} allowClear /></Form.Item>
          <Form.Item name="major_code" label="专业代码" rules={[{ pattern: /^\d{4,6}$/, message: "请输入4至6位数字" }]}>
            <Input maxLength={6} allowClear />
          </Form.Item>
          <Form.Item name="institution_name" label="院校名称"><Input maxLength={300} allowClear /></Form.Item>
          <Form.Item name="education_level" label="培养层次"><Input maxLength={80} allowClear /></Form.Item>
        </Form>
      </Drawer>
    </>
  );
}

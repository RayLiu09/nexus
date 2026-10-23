"use client";

import { useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { App, Button, Drawer, Form, Input, Space, Table, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import { BookOpen, Download, FileText, Pencil } from "lucide-react";

import { ApiState } from "@/components/ApiState";
import { patchApiData, type TalentDemandReport } from "@/lib/api";
import { reportDocumentQuery, type ReportDocumentFilters } from "@/lib/asset-center/document-filters";
import { DocumentIdentitySearch } from "./DocumentIdentitySearch";
import type { RawDownloadResponse } from "@/lib/chunkTypes";
import { ChunkListSection } from "@/app/assets/[assetId]/_components/ChunkListSection";
import { SourcePreviewSection } from "@/app/assets/[assetId]/_components/SourcePreviewSection";

type Props = {
  filters?: ReportDocumentFilters;
  canEdit: boolean;
  rows: TalentDemandReport[];
  total: number;
  page: number;
  pageSize: number;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

export function TalentDemandReportsTable({ filters = {}, rows, total, page, pageSize, ok, error, traceId, canEdit }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const { message } = App.useApp();
  const [pending, startTransition] = useTransition();
  const [drawer, setDrawer] = useState<{ row: TalentDemandReport; view: "preview" | "chunks" } | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<TalentDemandReport | null>(null);
  const [saving, setSaving] = useState(false);
  const [overrides, setOverrides] = useState<Record<string, TalentDemandReport>>({});
  const [form] = Form.useForm<Pick<TalentDemandReport, "major_name" | "major_code" | "institution_name">>();

  function navigate(values: ReportDocumentFilters, nextPage = 1, nextPageSize = pageSize) {
    const search = new URLSearchParams(reportDocumentQuery(values));
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  }

  function edit(row: TalentDemandReport) {
    form.setFieldsValue({
      major_name: row.major_name,
      major_code: row.major_code,
      institution_name: row.institution_name,
    });
    setEditTarget(row);
  }

  async function save() {
    if (!editTarget?.normalized_ref_id) return;
    const values = await form.validateFields();
    const changes = Object.fromEntries(
      (["major_name", "major_code", "institution_name"] as const)
        .map((field) => [field, values[field]?.trim() || null] as const)
        .filter(([field, value]) => value && value !== editTarget[field]),
    );
    if (!Object.keys(changes).length) {
      setEditTarget(null);
      return;
    }
    setSaving(true);
    try {
      const result = await patchApiData<Pick<TalentDemandReport, "major_name" | "major_code" | "institution_name">>(
        `/api/talent-demand-reports/${encodeURIComponent(editTarget.id)}/identity`,
        { normalized_ref_id: editTarget.normalized_ref_id, ...changes },
      );
      setOverrides((current) => ({
        ...current,
        [editTarget.id]: { ...editTarget, ...result.data },
      }));
      setEditTarget(null);
      message.success("报告信息已更新");
      router.refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function download(row: TalentDemandReport) {
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
    } catch (error) {
      message.error(error instanceof Error ? error.message : "原文下载失败");
    } finally {
      setDownloadingId(null);
    }
  }

  const columns: ColumnsType<TalentDemandReport> = [
    { title: "资产名称", dataIndex: "asset_name", width: 320, fixed: "left" },
    {
      title: "专业名称（专业代码）", key: "major", width: 245,
      render: (_, row) => row.major_name
        ? `${row.major_name}${row.major_code ? `（${row.major_code}）` : ""}`
        : row.major_code || "-",
    },
    { title: "院校名称", dataIndex: "institution_name", width: 200,
      render: (value: string | null) => value || "-" },
    {
      title: "内容标签", dataIndex: "content_tags", width: 265,
      render: (values: string[]) => values?.length ? (
        <span>
          {values.slice(0, 3).map((value) => <Tag key={value}>{value}</Tag>)}
          {values.length > 3 && <Tooltip title={values.join("，")}><Tag>+{values.length - 3}</Tag></Tooltip>}
        </span>
      ) : "-",
    },
    {
      title: "操作", key: "actions", width: 370, fixed: "right",
      render: (_, row) => (
        <Space size={4}>
          {canEdit && <Button type="link" size="small" icon={<Pencil size={14} />}
            disabled={!row.normalized_ref_id} onClick={() => edit(row)}>
            编辑
          </Button>}
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
      <div className="mb-3 flex flex-wrap justify-end">
        <DocumentIdentitySearch withContentTag key={JSON.stringify(filters)} filters={filters} pending={pending}
          onSearch={(values) => navigate(values)} />
      </div>
      <Table<TalentDemandReport>
        rowKey="id" columns={columns} dataSource={rows.map((row) => overrides[row.id] ?? row)} loading={pending}
        scroll={{ x: 1400 }} locale={{ emptyText: ok ? "暂无人才需求调研" : "暂无数据" }}
        pagination={{
          current: page, pageSize, total, showSizeChanger: true,
          showTotal: (value) => `共 ${value} 条`,
          onChange: (nextPage, nextPageSize) => navigate(filters, nextPage, nextPageSize),
        }}
      />
      <Drawer
        open={drawer !== null} onClose={() => setDrawer(null)} destroyOnHidden
        size="min(960px, calc(100vw - 32px))"
        title={drawer ? `${drawer.view === "preview" ? "解析预览" : "RAG知识块"} · ${drawer.row.asset_name}` : undefined}
      >
        {drawer?.view === "preview" && <SourcePreviewSection refId={drawer.row.normalized_ref_id} />}
        {drawer?.view === "chunks" && <ChunkListSection
          refId={drawer.row.normalized_ref_id} title="RAG知识块" mode="preview"
          actionLabel="预览定位" knowledgeTypeCode="talent_demand_report" />}
      </Drawer>
      <Drawer title="编辑人才需求调研" open={editTarget !== null}
        onClose={() => setEditTarget(null)} destroyOnHidden size="default"
        footer={<div className="flex justify-end gap-2">
          <Button onClick={() => setEditTarget(null)}>取消</Button>
          <Button type="primary" loading={saving} onClick={() => void save()}>保存</Button>
        </div>}>
        <Form form={form} layout="vertical">
          <Form.Item label="专业名称" name="major_name" rules={[{ max: 100, message: "最多100字" }]}>
            <Input maxLength={100} placeholder="填写专业名称" />
          </Form.Item>
          <Form.Item label="专业代码" name="major_code"
            rules={[{ pattern: /^\d{4,6}$/, message: "请输入4至6位数字" }]}>
            <Input maxLength={6} placeholder="填写专业代码" />
          </Form.Item>
          <Form.Item label="院校名称" name="institution_name" rules={[{ max: 100, message: "最多100字" }]}>
            <Input maxLength={100} placeholder="填写院校名称" />
          </Form.Item>
        </Form>
      </Drawer>
    </>
  );
}

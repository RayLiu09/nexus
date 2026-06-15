"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { CloudUploadOutlined, InboxOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Form,
  Progress,
  Select,
  Space,
  Spin,
  Tag,
  Upload,
  message,
} from "antd";
import type { UploadFile, UploadProps } from "antd";
import Link from "next/link";

import type { DataSource } from "@/lib/api";
import { NexusApiError, postApiData } from "@/lib/api";
import { FileStatusList } from "@/components/ingest/FileStatusList";
import type { BatchSubmitItem, BatchSubmitResult, SelectedFile } from "@/lib/ingest/batchTypes";
import { fileToBase64 } from "@/lib/ingest/fileToBase64";
import { useBatchStatus } from "@/lib/ingest/useBatchStatus";

// ── Constants ─────────────────────────────────────────────────────────────

const MAX_FILES = 20;
const MAX_FILE_BYTES = 100 * 1024 * 1024;
const ACCEPT_EXT = ".pdf,.txt,.md,.html,.json,.docx,.xlsx,.csv,.png,.jpg,.jpeg";

// ── Context ───────────────────────────────────────────────────────────────

interface QuickUploadContextValue {
  open: (prefillDataSourceId?: string) => void;
  close: () => void;
  isOpen: boolean;
}

const QuickUploadContext = createContext<QuickUploadContextValue | null>(null);

/** Imperatively open the global Quick Upload drawer from any client component. */
export function useQuickUpload(): QuickUploadContextValue {
  const ctx = useContext(QuickUploadContext);
  if (!ctx) {
    throw new Error("useQuickUpload must be used inside <QuickUploadProvider>");
  }
  return ctx;
}

// ── Helpers ───────────────────────────────────────────────────────────────

function statusTone(status: string): "default" | "success" | "warning" | "error" | "processing" {
  if (status === "completed") return "success";
  if (status === "failed") return "error";
  if (status === "partial_failed" || status === "duplicate_skipped") return "warning";
  return "processing";
}

function statusLabel(status: string): string {
  switch (status) {
    case "open":
      return "已创建（待提交文件）";
    case "submitted":
      return "已提交";
    case "raw_persisted":
      return "原始已持久化";
    case "processing":
      return "处理中";
    case "completed":
      return "已完成";
    case "partial_failed":
      return "部分失败";
    case "failed":
      return "全部失败";
    case "duplicate_skipped":
      return "整体跳过（重复）";
    default:
      return status;
  }
}

interface SourcesProxyOk {
  ok: true;
  status: number;
  data: DataSource[];
  traceId: string | null;
}
interface SourcesProxyErr {
  ok: false;
  status: number;
  message: string;
}
type SourcesProxyResult = SourcesProxyOk | SourcesProxyErr;

async function fetchDataSources(signal: AbortSignal): Promise<DataSource[]> {
  const resp = await fetch("/api/data-sources", { signal, cache: "no-store" });
  const text = await resp.text();
  let body: SourcesProxyResult;
  try {
    body = JSON.parse(text) as SourcesProxyResult;
  } catch {
    throw new Error(`Invalid JSON from /api/data-sources: ${text.slice(0, 200)}`);
  }
  if (!body.ok) {
    throw new Error(body.message ?? `Failed to fetch data sources (HTTP ${resp.status})`);
  }
  return body.data;
}

// ── Drawer body ───────────────────────────────────────────────────────────

interface DrawerBodyProps {
  prefillDataSourceId?: string;
  onClose: () => void;
}

function QuickUploadBody({ prefillDataSourceId, onClose }: DrawerBodyProps) {
  const [form] = Form.useForm<{ data_source_id: string }>();
  const [sources, setSources] = useState<DataSource[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [items, setItems] = useState<BatchSubmitItem[]>([]);
  const [submittedSourceId, setSubmittedSourceId] = useState<string | null>(null);

  const { detail: batchDetail, error: pollError, isPolling } = useBatchStatus(batchId);

  // Lazy load data sources when drawer mounts.
  useEffect(() => {
    const controller = new AbortController();
    setSourcesLoading(true);
    fetchDataSources(controller.signal)
      .then((data) => {
        setSources(data);
        setSourcesError(null);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setSourcesError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setSourcesLoading(false);
      });
    return () => controller.abort();
  }, []);

  // file_upload 类型才允许通过此 drawer 接收文件
  const fileUploadSources = useMemo(
    () => sources.filter((s) => s.source_type === "file_upload" && s.status !== "disabled"),
    [sources],
  );

  // Apply prefilled source if it matches a file_upload entry.
  useEffect(() => {
    if (!prefillDataSourceId) return;
    if (fileUploadSources.some((s) => s.id === prefillDataSourceId)) {
      form.setFieldValue("data_source_id", prefillDataSourceId);
    }
  }, [prefillDataSourceId, fileUploadSources, form]);

  const fileNamesByKey = useMemo<Record<string, string>>(() => {
    return fileList.reduce<Record<string, string>>((acc, file) => {
      if (file.uid && file.name) acc[file.uid] = file.name;
      return acc;
    }, {});
  }, [fileList]);

  const uploadProps: UploadProps = {
    multiple: true,
    fileList,
    beforeUpload: (file, files) => {
      const incomingTotal = fileList.length + files.length;
      if (incomingTotal > MAX_FILES) {
        message.warning(`单次最多上传 ${MAX_FILES} 个文件，请分批处理`);
        return Upload.LIST_IGNORE;
      }
      if (file.size > MAX_FILE_BYTES) {
        message.warning(`文件 ${file.name} 超过 100MB 限制`);
        return Upload.LIST_IGNORE;
      }
      return false;
    },
    onChange: ({ fileList: next }) => {
      setFileList(next.slice(0, MAX_FILES));
    },
    onRemove: (file) => {
      setFileList((prev) => prev.filter((f) => f.uid !== file.uid));
    },
    accept: ACCEPT_EXT,
  };

  const handleReset = useCallback(() => {
    form.resetFields();
    setFileList([]);
    setItems([]);
    setBatchId(null);
    setSubmittedSourceId(null);
    setSubmitError(null);
  }, [form]);

  const handleSubmit = async () => {
    setSubmitError(null);
    try {
      const values = await form.validateFields();
      if (fileList.length === 0) {
        message.warning("请至少选择一个文件");
        return;
      }
      setSubmitting(true);

      const selected: SelectedFile[] = await Promise.all(
        fileList.map(async (file) => {
          const raw = (file.originFileObj ?? null) as File | null;
          if (!raw) throw new Error(`文件 ${file.name} 无法读取`);
          return {
            key: file.uid,
            name: file.name,
            size: file.size ?? raw.size,
            type: file.type ?? raw.type ?? "application/octet-stream",
            base64: await fileToBase64(raw),
          };
        }),
      );

      const batchKey = `quick-upload-${Date.now()}`;
      const payload = {
        data_source_id: values.data_source_id,
        batch_idempotency_key: batchKey,
        files: selected.map((file) => ({
          file_idempotency_key: file.key,
          filename: file.name,
          content_base64: file.base64,
          content_type: file.type || "application/octet-stream",
        })),
      };

      const result = await postApiData<BatchSubmitResult>(
        "/api/ingest/files/multi",
        payload as Record<string, unknown>,
      );
      setItems(result.data.items);
      setBatchId(result.data.batch.id);
      setSubmittedSourceId(values.data_source_id);
      message.success(`已入队 ${result.data.items.length} 个文件`);
    } catch (err) {
      if (err instanceof NexusApiError) {
        setSubmitError(err.message);
      } else {
        setSubmitError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const totalFiles = items.length;
  const detailEntries = Object.values(batchDetail?.batch_status_detail ?? {});
  const finishedCount = detailEntries.filter((v) =>
    ["succeeded", "failed", "dead_lettered", "cancelled"].includes(v),
  ).length;
  const percent = totalFiles === 0 ? 0 : Math.round((finishedCount / totalFiles) * 100);

  // ── Render: sources loading ──────────────────────────────────────────────
  if (sourcesLoading) {
    return (
      <div className="flex h-full items-center justify-center py-12">
        <Spin tip="加载数据源列表…" />
      </div>
    );
  }

  if (sourcesError) {
    return <Alert type="error" showIcon title="无法加载数据源列表" description={sourcesError} />;
  }

  // ── Render: no file_upload sources ────────────────────────────────────────
  if (fileUploadSources.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <div className="text-sm">
            <div className="mb-2 font-medium">尚未注册「本地文件上传」类型数据源</div>
            <div className="text-text-secondary">
              快速上传需要先创建一个 file_upload 类型的数据源作为归属。
            </div>
          </div>
        }
      >
        <Link href="/data-sources/new" onClick={onClose}>
          <Button type="primary">前往创建数据源</Button>
        </Link>
      </Empty>
    );
  }

  // ── Render: post-submit progress view ────────────────────────────────────
  if (batchId) {
    const isDone = batchDetail !== null && !isPolling && percent === 100;
    return (
      <div className="flex h-full flex-col gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <span className="text-sm font-medium">批次状态</span>
            {batchDetail && (
              <Tag color={statusTone(batchDetail.status)}>{statusLabel(batchDetail.status)}</Tag>
            )}
            {isPolling && <Tag color="processing">轮询中</Tag>}
            <code className="text-text-muted ml-auto font-mono text-xs">
              {batchId.slice(0, 8)}…
            </code>
          </div>
          <Progress percent={percent} status={isDone ? "success" : "active"} />
          <p className="text-text-secondary mt-1 text-xs">
            {finishedCount} / {totalFiles} 个文件已完成处理
          </p>
        </div>

        {pollError && (
          <Alert type="warning" showIcon title="状态查询失败" description={pollError} />
        )}

        <FileStatusList
          submittedItems={items}
          fileNamesByKey={fileNamesByKey}
          batchDetail={batchDetail}
        />

        <div className="border-line-light mt-auto flex items-center justify-between gap-2 border-t pt-3">
          {submittedSourceId && (
            <Link
              href={`/data-sources/${submittedSourceId}?tab=history`}
              onClick={onClose}
              className="text-brand text-sm"
            >
              在数据源中查看完整历史 →
            </Link>
          )}
          <Space>
            <Button onClick={handleReset} icon={<ReloadOutlined />}>
              再传一批
            </Button>
            <Button type="primary" onClick={onClose}>
              完成
            </Button>
          </Space>
        </div>
      </div>
    );
  }

  // ── Render: pre-submit form ───────────────────────────────────────────────
  return (
    <Form<{ data_source_id: string }>
      form={form}
      layout="vertical"
      initialValues={
        prefillDataSourceId && fileUploadSources.some((s) => s.id === prefillDataSourceId)
          ? { data_source_id: prefillDataSourceId }
          : undefined
      }
    >
      <Form.Item
        name="data_source_id"
        label="归属数据源"
        rules={[{ required: true, message: "请选择数据源" }]}
        extra="仅可选择「本地文件上传」类型数据源。其他类型请在数据源详情页配置定时同步。"
      >
        <Select
          placeholder="选择数据源"
          showSearch
          optionFilterProp="label"
          options={fileUploadSources.map((source) => ({
            value: source.id,
            label: `${source.name} [${source.code}]`,
          }))}
        />
      </Form.Item>

      <Form.Item label={`文件（最多 ${MAX_FILES} 个，单文件 ≤ 100MB）`} required>
        <Upload.Dragger {...uploadProps}>
          <p className="text-brand text-3xl">
            <InboxOutlined />
          </p>
          <p className="mt-2 text-sm font-medium">点击或拖拽文件到此处</p>
          <p className="text-text-secondary text-xs">
            支持 PDF / 文档 / 表格 / 图片 / JSON 等常见格式
          </p>
        </Upload.Dragger>
      </Form.Item>

      {submitError && (
        <Alert className="mb-3" type="error" showIcon title="提交失败" description={submitError} />
      )}

      <div className="border-line-light flex items-center justify-between gap-2 border-t pt-3">
        <span className="text-text-muted text-xs">
          {fileList.length} / {MAX_FILES} 个文件已选
        </span>
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            icon={<CloudUploadOutlined />}
            loading={submitting}
            disabled={fileList.length === 0}
            onClick={handleSubmit}
          >
            上传并入库
          </Button>
        </Space>
      </div>
    </Form>
  );
}

// ── Provider ──────────────────────────────────────────────────────────────

export function QuickUploadProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [prefillDataSourceId, setPrefillDataSourceId] = useState<string | undefined>();
  // Force-remount the body each time the drawer opens so state resets cleanly.
  const [openKey, setOpenKey] = useState(0);

  const open = useCallback((id?: string) => {
    setPrefillDataSourceId(id);
    setOpenKey((k) => k + 1);
    setIsOpen(true);
  }, []);
  const close = useCallback(() => setIsOpen(false), []);

  const value = useMemo<QuickUploadContextValue>(
    () => ({ open, close, isOpen }),
    [open, close, isOpen],
  );

  return (
    <QuickUploadContext.Provider value={value}>
      {children}
      <Drawer
        title={
          <Space>
            <CloudUploadOutlined />
            <span>快速上传</span>
          </Space>
        }
        placement="right"
        width={560}
        open={isOpen}
        onClose={close}
        destroyOnHidden
      >
        {isOpen && (
          <QuickUploadBody
            key={openKey}
            prefillDataSourceId={prefillDataSourceId}
            onClose={close}
          />
        )}
      </Drawer>
    </QuickUploadContext.Provider>
  );
}

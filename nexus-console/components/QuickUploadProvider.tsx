"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { CloudUploadOutlined, InboxOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Drawer,
  Form,
  Progress,
  Space,
  Tag,
  Upload,
  message,
} from "antd";
import type { UploadFile, UploadProps } from "antd";
import Link from "next/link";

import { NexusApiError, postApiData } from "@/lib/api";
import { FileStatusList } from "@/components/ingest/FileStatusList";
import type { BatchSubmitItem, BatchSubmitResult, SelectedFile } from "@/lib/ingest/batchTypes";
import { fileToBase64 } from "@/lib/ingest/fileToBase64";
import { useBatchStatus } from "@/lib/ingest/useBatchStatus";

// ── Constants ─────────────────────────────────────────────────────────────

const MAX_FILES = 20;
const MAX_FILE_BYTES = 100 * 1024 * 1024;
const ACCEPT_EXT = ".pdf,.txt,.md,.html,.json,.docx,.pptx,.xlsx,.csv,.png,.jpg,.jpeg";

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

// ── Drawer body ───────────────────────────────────────────────────────────

interface DrawerBodyProps {
  prefillDataSourceId?: string;
  onClose: () => void;
}

function QuickUploadBody({ prefillDataSourceId, onClose }: DrawerBodyProps) {
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [items, setItems] = useState<BatchSubmitItem[]>([]);

  const { detail: batchDetail, error: pollError, isPolling } = useBatchStatus(batchId);

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
    setFileList([]);
    setItems([]);
    setBatchId(null);
    setSubmitError(null);
  }, []);

  const handleSubmit = async () => {
    setSubmitError(null);
    try {
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
        data_source_id: prefillDataSourceId,
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
          <Link href={`/raw-ledger?batch_id=${batchId}`} onClick={onClose} className="text-brand text-sm">
            查看批次原始数据
          </Link>
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
    <Form layout="vertical">

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
        size={560}
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

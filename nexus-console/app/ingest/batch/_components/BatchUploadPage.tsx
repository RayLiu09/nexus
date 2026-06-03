"use client";

import { CloudUploadOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Form,
  Progress,
  Select,
  Space,
  Tag,
  Upload,
  message,
} from "antd";
import type { UploadFile, UploadProps } from "antd";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import type { DataSource } from "@/lib/api";
import { postApiData, NexusApiError } from "@/lib/api";

import type {
  BatchSubmitItem,
  BatchSubmitResult,
  SelectedFile,
} from "./batch.types";
import { FileStatusList } from "./FileStatusList";
import { useBatchStatus } from "./useBatchStatus";

const MAX_FILES = 20;
const MAX_FILE_BYTES = 100 * 1024 * 1024;

interface BatchUploadPageProps {
  sources: DataSource[];
}

interface FormValues {
  data_source_id: string;
}

async function fileToBase64(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

function statusTone(status: string): "default" | "success" | "warning" | "error" | "processing" {
  if (status === "completed") return "success";
  if (status === "failed") return "error";
  if (status === "partial_failed") return "warning";
  if (status === "duplicate_skipped") return "warning";
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

export function BatchUploadPage({ sources }: BatchUploadPageProps) {
  const [form] = Form.useForm<FormValues>();
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
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

  const handleReset = useCallback(() => {
    form.resetFields();
    setFileList([]);
    setItems([]);
    setBatchId(null);
    setSubmitError(null);
  }, [form]);

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
    accept: ".pdf,.txt,.md,.html,.json,.docx,.xlsx,.csv,.png,.jpg,.jpeg",
  };

  const handleSubmit = async () => {
    setSubmitError(null);
    try {
      const values = await form.validateFields();
      if (fileList.length === 0) {
        message.warning("请至少选择一个文件");
        return;
      }
      setIsSubmitting(true);

      const selected: SelectedFile[] = await Promise.all(
        fileList.map(async (file) => {
          const raw = (file.originFileObj ?? null) as File | null;
          if (!raw) {
            throw new Error(`文件 ${file.name} 无法读取`);
          }
          return {
            key: file.uid,
            name: file.name,
            size: file.size ?? raw.size,
            type: file.type ?? raw.type ?? "application/octet-stream",
            base64: await fileToBase64(raw),
          };
        }),
      );

      const batchKey = `console-multi-${Date.now()}`;
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
      message.success(`批次已创建，${result.data.items.length} 个文件已入队`);
    } catch (err) {
      if (err instanceof NexusApiError) {
        setSubmitError(err.message);
      } else {
        const text = err instanceof Error ? err.message : String(err);
        setSubmitError(text);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const totalFiles = items.length;
  const detailEntries = Object.values(batchDetail?.batch_status_detail ?? {});
  const finishedCount = detailEntries.filter((v) =>
    ["succeeded", "failed", "dead_lettered", "cancelled"].includes(v),
  ).length;
  const percent = totalFiles === 0 ? 0 : Math.round((finishedCount / totalFiles) * 100);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(360px,1fr)]">
      <Card
        title="选择数据源与文件"
        extra={
          <Link href="/ingest" className="text-xs text-brand">
            ← 返回单文件接入
          </Link>
        }
      >
        <Form<FormValues> form={form} layout="vertical">
          <Form.Item
            name="data_source_id"
            label="数据源"
            rules={[{ required: true, message: "请选择数据源" }]}
          >
            <Select
              placeholder="选择已注册的数据源"
              options={sources.map((source) => ({
                value: source.id,
                label: `${source.name} [${source.code}]`,
              }))}
              showSearch
              optionFilterProp="label"
              disabled={sources.length === 0 || batchId !== null}
            />
          </Form.Item>
          <Form.Item
            label={`文件列表（最多 ${MAX_FILES} 个，单文件 ≤ 100MB）`}
            required
          >
            <Upload.Dragger {...uploadProps} disabled={batchId !== null} className="!p-0">
              <p className="text-2xl">
                <CloudUploadOutlined />
              </p>
              <p className="mt-2 text-sm">点击或拖拽多个文件到此处</p>
              <p className="text-xs text-text-secondary">
                支持 PDF / 文档 / 表格 / 图片 / JSON 等常见格式
              </p>
            </Upload.Dragger>
          </Form.Item>

          {submitError && (
            <Alert
              className="mb-3"
              type="error"
              showIcon
              message="提交失败"
              description={submitError}
            />
          )}

          <Space>
            <Button
              type="primary"
              icon={<CloudUploadOutlined />}
              loading={isSubmitting}
              disabled={fileList.length === 0 || batchId !== null}
              onClick={handleSubmit}
            >
              提交批次（{fileList.length}/{MAX_FILES}）
            </Button>
            <Button icon={<ReloadOutlined />} onClick={handleReset} disabled={isSubmitting}>
              重置
            </Button>
          </Space>
        </Form>
      </Card>

      <Card
        title={
          <Space>
            <span>批次状态</span>
            {batchDetail && <Tag color={statusTone(batchDetail.status)}>{statusLabel(batchDetail.status)}</Tag>}
            {isPolling && <Tag color="processing">轮询中</Tag>}
          </Space>
        }
        extra={
          batchId && (
            <code className="font-mono text-xs text-text-muted">{batchId.slice(0, 8)}…</code>
          )
        }
      >
        {!batchId && (
          <Alert
            type="info"
            showIcon
            message="尚未提交批次"
            description="选择数据源并添加文件后点击「提交批次」，提交后此处会实时展示处理进度。"
          />
        )}

        {batchId && (
          <>
            <div className="mb-3">
              <Progress percent={percent} status={percent === 100 ? "success" : "active"} />
              <p className="mt-1 text-xs text-text-secondary">
                {finishedCount} / {totalFiles} 个文件已完成处理
              </p>
            </div>

            {pollError && (
              <Alert
                type="warning"
                showIcon
                message="状态查询失败"
                description={pollError}
                className="mb-3"
              />
            )}

            <FileStatusList
              submittedItems={items}
              fileNamesByKey={fileNamesByKey}
              batchDetail={batchDetail}
            />
          </>
        )}
      </Card>
    </div>
  );
}

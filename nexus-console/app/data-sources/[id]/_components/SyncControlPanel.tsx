"use client";

import { Alert, Button, Card, Space, Statistic, Tag, Tooltip } from "antd";
import { CloudUploadOutlined, ClockCircleOutlined, EditOutlined } from "@ant-design/icons";
import { useMemo } from "react";

import { useQuickUpload } from "@/components/QuickUploadProvider";
import { formatTime } from "@/lib/format-time";
import type { DataSource, IngestBatch } from "@/lib/api";

const SOURCE_TYPE_LABELS: Record<string, string> = {
  file_upload: "本地文件上传",
  nas: "NAS 同步",
  crawler: "Crawler 爬虫",
  database: "数据库对接",
  webhook: "API 推送",
};

const FAILURE_STATUSES = new Set(["failed", "partial_failed"]);

interface SyncControlPanelProps {
  dataSource: DataSource;
  relatedBatches: IngestBatch[];
}

function readScheduleCron(ds: DataSource): string | null {
  const cfg = (ds.connection_config ?? {}) as Record<string, unknown>;
  // 兼容 cfg_schedule_cron / schedule_cron 两种字段命名
  const value = cfg.schedule_cron ?? cfg.cfg_schedule_cron;
  if (typeof value === "string" && value.trim().length > 0) {
    return value.trim();
  }
  return null;
}

export function SyncControlPanel({ dataSource, relatedBatches }: SyncControlPanelProps) {
  const { open: openQuickUpload } = useQuickUpload();

  const stats = useMemo(() => {
    const total = relatedBatches.length;
    const failed = relatedBatches.filter((b) => FAILURE_STATUSES.has(b.status)).length;
    const success = relatedBatches.filter((b) => b.status === "completed").length;
    const successRate = total === 0 ? null : Math.round((success / total) * 100);
    const lastBatch = relatedBatches[0]; // 调用方按 updated_at desc 排序传入
    return {
      total,
      failed,
      success,
      successRate,
      lastUpdate: lastBatch ? formatTime(lastBatch.updated_at).display : "—",
    };
  }, [relatedBatches]);

  const cron = readScheduleCron(dataSource);
  const isFileUpload = dataSource.source_type === "file_upload";
  const supportsSchedule = !isFileUpload;
  const typeLabel = SOURCE_TYPE_LABELS[dataSource.source_type] ?? dataSource.source_type;

  return (
    <div className="grid gap-4">
      {/* ── 健康指标 ── */}
      <Card title="同步健康">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Statistic title="累计批次" value={stats.total} />
          <Statistic
            title="成功率"
            value={stats.successRate === null ? "—" : `${stats.successRate}%`}
            styles={{ content: {
              color: stats.successRate !== null && stats.successRate < 80 ? "var(--warning-600)" : undefined,
            } }}
          />
          <Statistic
            title="失败批次"
            value={stats.failed}
            styles={{ content: { color: stats.failed > 0 ? "var(--danger-600)" : undefined } }}
          />
          <Statistic title="最近活动" value={stats.lastUpdate} />
        </div>
      </Card>

      {/* ── 同步策略 ── */}
      <Card
        title={
          <Space>
            <ClockCircleOutlined />
            <span>同步策略</span>
          </Space>
        }
        extra={<Tag>{typeLabel}</Tag>}
      >
        {isFileUpload ? (
          <Alert
            type="info"
            showIcon
            title="按需上传"
            description="本地文件上传类型不需要定时计划。点击下方按钮即可拖拽上传文件，系统会立即入库并触发处理流水线。"
          />
        ) : cron ? (
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-text-secondary text-xs">已配置 Cron</div>
              <code className="font-mono text-sm">{cron}</code>
            </div>
            <Tag color="success">定时同步已启用</Tag>
          </div>
        ) : (
          <Alert
            type="warning"
            showIcon
            title="未配置定时同步"
            description="如需让系统按计划自动同步，请在「配置」标签的连接器配置中填写 Cron 表达式。"
          />
        )}
      </Card>

      {/* ── 操作 ── */}
      <Card title="操作">
        {isFileUpload ? (
          <Space wrap>
            <Button
              type="primary"
              icon={<CloudUploadOutlined />}
              onClick={() => openQuickUpload(dataSource.id)}
            >
              上传文件到此数据源
            </Button>
            <span className="text-text-secondary text-xs">
              将打开「快速上传」抽屉，归属数据源已预选为当前。
            </span>
          </Space>
        ) : (
          <Space wrap>
            <Tooltip title="后端尚未提供手动触发接口，将在后续版本支持。">
              <Button disabled>立即同步</Button>
            </Tooltip>
            <Tooltip title="在「配置」标签编辑连接器配置以调整调度计划。">
              <Button icon={<EditOutlined />} disabled>
                编辑同步计划
              </Button>
            </Tooltip>
            {supportsSchedule && (
              <span className="text-text-secondary text-xs">
                调度编辑入口与连接器配置统一在「配置」标签，避免分散。
              </span>
            )}
          </Space>
        )}
      </Card>
    </div>
  );
}

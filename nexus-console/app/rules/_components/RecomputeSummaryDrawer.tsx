"use client";

import { Descriptions, Drawer, Space, Tag, Typography } from "antd";
import type { RecomputeSummary } from "@/lib/governance-rules-api";

function VersionIdList({
  title,
  ids,
  emptyLabel,
}: {
  title: string;
  ids: string[];
  emptyLabel: string;
}) {
  return (
    <div>
      <Typography.Text strong>{title}</Typography.Text>
      <div className="mt-2">
        {ids.length === 0 ? (
          <Typography.Text type="secondary">{emptyLabel}</Typography.Text>
        ) : (
          <Space size={4} wrap>
            {ids.map((id) => (
              <Tag key={id} className="font-mono text-xs">
                {id}
              </Tag>
            ))}
          </Space>
        )}
      </div>
    </div>
  );
}

export function RecomputeSummaryDrawer({
  summary,
  onClose,
}: {
  summary: RecomputeSummary | null;
  onClose: () => void;
}) {
  return (
    <Drawer
      title="批量重跑结果"
      size={520}
      open={summary !== null}
      onClose={onClose}
      destroyOnClose
    >
      {summary && (
        <Space orientation="vertical" size="middle" className="w-full">
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="重跑范围">
              <Tag color="processing">{summary.scope}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="受影响 normalized_ref 总数">
              {summary.affected_total}
            </Descriptions.Item>
            <Descriptions.Item label="已回流到 processing 的版本数">
              <Tag color="success">{summary.rescheduled_count}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="保留 available 不变（仅审计）">
              <Tag color="default">{summary.available_skipped_count}</Tag>
            </Descriptions.Item>
          </Descriptions>

          <VersionIdList
            title="被重新调度的版本"
            ids={summary.rescheduled_version_ids}
            emptyLabel="无"
          />
          <VersionIdList
            title="登记审计但未自动重跑的 available 版本"
            ids={summary.available_skipped_version_ids}
            emptyLabel="无"
          />
        </Space>
      )}
    </Drawer>
  );
}

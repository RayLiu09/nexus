"use client";

import { Badge, Button, Space, Tag, Typography } from "antd";

import type { Mode } from "../_lib/playgroundTypes";
import { MODE_LABELS } from "../_lib/playgroundTypes";

interface ConversationHeaderProps {
  mode: Mode;
  loading: boolean;
  onClear: () => void;
}

export function ConversationHeader({ mode, loading, onClear }: ConversationHeaderProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] px-5 py-4">
      <Space size="middle">
        <Badge status={loading ? "processing" : "success"} />
        <div>
          <Typography.Title level={4} className="!mb-0">
            检索/召回验证窗口
          </Typography.Title>
          <Typography.Text type="secondary">当前模式：{MODE_LABELS[mode]}</Typography.Text>
        </div>
      </Space>
      <Space>
        <Tag color={loading ? "processing" : "default"}>{loading ? "执行中" : "可交互"}</Tag>
        <Button size="small" onClick={onClear} disabled={loading}>
          清空
        </Button>
      </Space>
    </div>
  );
}

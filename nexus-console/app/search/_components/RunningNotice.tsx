"use client";

import { Alert, Typography } from "antd";

export function RunningNotice({ query }: { query: string }) {
  return (
    <Alert
      type="info"
      showIcon
      title="正在执行检索/查询流程"
      description={<Typography.Text type="secondary">当前问题：{query}</Typography.Text>}
    />
  );
}

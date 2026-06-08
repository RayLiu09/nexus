"use client";

import { Alert, Button } from "antd";

interface ApiStateProps {
  ok: boolean;
  error: string | null;
  traceId?: string | null;
  onRetry?: () => void;
}

export function ApiState({ ok, error, traceId, onRetry }: ApiStateProps) {
  if (ok) return null;

  return (
    <Alert
      type="error"
      showIcon
      title="API 不可用"
      description={
        <div className="flex flex-col gap-1">
          <span>{error || "无法连接到后端服务"}</span>
          {traceId && <span className="font-mono text-xs">trace: {traceId}</span>}
        </div>
      }
      className="mb-4"
      action={
        onRetry ? (
          <Button size="small" type="primary" ghost onClick={onRetry}>
            重试
          </Button>
        ) : undefined
      }
    />
  );
}

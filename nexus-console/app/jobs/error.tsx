"use client";

import { ErrorState } from "@/components/shared/ErrorState";

export default function JobsErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <ErrorState
      title="作业中心页面加载异常"
      description={error.message || "数据加载失败，请重试。"}
      onRetry={reset}
    />
  );
}

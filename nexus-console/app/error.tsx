"use client";

import { ErrorState } from "@/components/shared/ErrorState";

export default function RootErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg">
      <ErrorState
        title="页面加载异常"
        description={error.message || "服务器渲染时发生错误，请重试。"}
        onRetry={reset}
      />
    </div>
  );
}

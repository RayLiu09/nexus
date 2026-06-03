"use client";

/**
 * 路由级错误边界（基于 react-error-boundary）。
 *
 * 用于在 `app/<route>/page.tsx` 顶层与全局 AppShell 兜底渲染错误。
 * 失败时显示 ErrorState（A1 四态规范），并尝试展示 trace_id（若错误对象
 * 上挂有 `.traceId`，例如来自 `lib/api.ts:NexusApiError`）。
 */
import { ErrorBoundary, type FallbackProps } from "react-error-boundary";
import type { ErrorInfo, ReactNode } from "react";

import { ErrorState } from "./ErrorState";

interface TracedError extends Error {
  traceId?: string | null;
}

function RouteFallback({ error, resetErrorBoundary }: FallbackProps) {
  const traced = error as TracedError;
  return (
    <ErrorState
      title="页面渲染异常"
      description={traced?.message || "组件抛出了未处理的异常。请重试或联系平台支持。"}
      traceId={traced?.traceId ?? undefined}
      onRetry={resetErrorBoundary}
    />
  );
}

export interface RouteBoundaryProps {
  children: ReactNode;
  /** 自定义 fallback；缺省走 ErrorState（A1）。 */
  fallback?: React.ComponentType<FallbackProps>;
  /** 错误时机回调（后续可对接 Sentry 等）。 */
  onError?: (error: unknown, info: ErrorInfo) => void;
}

export function RouteBoundary({ children, fallback, onError }: RouteBoundaryProps) {
  return (
    <ErrorBoundary FallbackComponent={fallback ?? RouteFallback} onError={onError}>
      {children}
    </ErrorBoundary>
  );
}

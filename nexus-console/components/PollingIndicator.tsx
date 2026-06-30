"use client";

import { Button } from "antd";
import { PauseOutlined, CaretRightOutlined, ReloadOutlined } from "@ant-design/icons";

type PollingState = "active" | "paused" | "error";

type PollingIndicatorProps = {
  state: PollingState;
  intervalSeconds?: number;
  lastUpdate?: string;
  responseMs?: number;
  onRefresh?: () => void;
  onToggle?: () => void;
  refreshing?: boolean;
};

const stateConfig: Record<PollingState, { label: string; dotClass: string }> = {
  active: { label: "自动刷新中", dotClass: "active" },
  paused: { label: "已暂停自动刷新", dotClass: "paused" },
  error: { label: "刷新失败·重试中", dotClass: "error" }
};

export function PollingIndicator({
  state,
  intervalSeconds,
  lastUpdate,
  responseMs,
  onRefresh,
  onToggle,
  refreshing = false,
}: PollingIndicatorProps) {
  const config = stateConfig[state];

  return (
    <div className="polling-indicator">
      <span className={`polling-dot ${config.dotClass}`} />
      <span>
        {config.label}
        {state === "active" && intervalSeconds ? ` · 每${intervalSeconds}秒` : ""}
      </span>
      {lastUpdate && <span className="text-muted">上次更新: {lastUpdate}</span>}
      {responseMs != null && <span className="text-muted">响应: {responseMs}ms</span>}
      {onRefresh && (
        <Button
          type="text"
          size="small"
          icon={<ReloadOutlined />}
          onClick={onRefresh}
          loading={refreshing}
          disabled={refreshing}
        >
          手动刷新
        </Button>
      )}
      {onToggle && (
        <Button
          type="text"
          size="small"
          icon={state === "active" ? <PauseOutlined /> : <CaretRightOutlined />}
          onClick={onToggle}
        >
          {state === "active" ? "暂停" : "恢复"}
        </Button>
      )}
    </div>
  );
}

/** Convenience: compact polling dot for use in inline contexts */
export function PollingDot({ state }: { state: PollingState }) {
  const config = stateConfig[state];
  return <span className={`polling-dot ${config.dotClass}`} title={config.label} />;
}

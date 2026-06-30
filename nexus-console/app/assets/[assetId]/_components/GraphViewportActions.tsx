"use client";

import { useState, type ReactNode } from "react";
import { Button, Modal, Space, Tooltip } from "antd";
import type { EChartsOption } from "echarts";
import { Download, Maximize2 } from "lucide-react";

export type GraphImageHandle = {
  downloadImage: (filename: string) => Promise<boolean>;
};

type Props = {
  title: string;
  disabled?: boolean;
  onDownload: () => void;
  children: ReactNode;
};

export function GraphViewportActions({ title, disabled = false, onDownload, children }: Props) {
  const [open, setOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      await onDownload();
    } finally {
      setDownloading(false);
    }
  };

  return (
    <>
      <Space size={4}>
        <Tooltip title="下载完整图谱 PNG">
          <Button
            type="text"
            size="small"
            icon={<Download size={16} aria-hidden="true" />}
            onClick={handleDownload}
            disabled={disabled || downloading}
            loading={downloading}
            aria-label={`下载${title}图片`}
          />
        </Tooltip>
        <Tooltip title="全屏展示">
          <Button
            type="text"
            size="small"
            icon={<Maximize2 size={16} aria-hidden="true" />}
            onClick={() => setOpen(true)}
            disabled={disabled}
            aria-label={`全屏展示${title}`}
          />
        </Tooltip>
      </Space>
      <Modal
        title={title}
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        width="calc(100vw - 32px)"
        centered
        destroyOnHidden
        style={{ top: 16 }}
        styles={{
          body: {
            height: "calc(100vh - 118px)",
            minHeight: 0,
            overflow: "hidden",
            padding: 16,
          },
        }}
      >
        <div className="h-full min-h-0">{children}</div>
      </Modal>
    </>
  );
}

export async function downloadEchartsGraphImage({
  option,
  filename,
  nodeCount,
}: {
  option: EChartsOption;
  filename: string;
  nodeCount: number;
}): Promise<boolean> {
  if (typeof document === "undefined") return false;

  const width = clamp(Math.round(900 + Math.sqrt(Math.max(nodeCount, 1)) * 190), 1600, 4096);
  const height = clamp(Math.round(700 + Math.sqrt(Math.max(nodeCount, 1)) * 140), 1100, 3072);
  const container = document.createElement("div");
  container.style.position = "fixed";
  container.style.left = "-10000px";
  container.style.top = "-10000px";
  container.style.width = `${width}px`;
  container.style.height = `${height}px`;
  container.style.pointerEvents = "none";
  container.style.background = "#ffffff";
  document.body.appendChild(container);

  const echarts = await import("echarts");
  const chart = echarts.init(container, undefined, {
    renderer: "canvas",
    width,
    height,
  });

  try {
    chart.setOption(buildExportOption(option), true);
    chart.resize({ width, height });
    await waitForGraphLayout();
    const url = chart.getDataURL({
      type: "png",
      pixelRatio: 1,
      backgroundColor: "#ffffff",
    });
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    return true;
  } finally {
    chart.dispose();
    container.remove();
  }
}

function buildExportOption(option: EChartsOption): EChartsOption {
  const source = option as Record<string, unknown>;
  const seriesValue = source.series;
  const series = Array.isArray(seriesValue)
    ? seriesValue
    : seriesValue
      ? [seriesValue]
      : [];

  return {
    ...option,
    animation: false,
    animationDuration: 0,
    animationDurationUpdate: 0,
    series: series.map((item) => {
      if (!isRecord(item)) return item;
      return {
        ...item,
        animation: false,
        animationDuration: 0,
        animationDurationUpdate: 0,
        roam: false,
        left: 32,
        right: 32,
        bottom: 32,
      };
    }),
  } as EChartsOption;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function waitForGraphLayout(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        window.setTimeout(resolve, 900);
      });
    });
  });
}

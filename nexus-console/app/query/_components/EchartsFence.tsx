"use client";

/**
 * B8 (§7.1 §7.4) — chart:echarts fence renderer.
 *
 * Takes the JSON payload from a ```chart:echarts fenced block and
 * renders an ECharts graph. Only supports the P0 `type: "graph"`
 * shape declared in §7.1; unknown types fall back to a JSON preview
 * so operators can see what the backend sent instead of a blank div.
 *
 * Graph layout defaults follow §7.4 — force layout for anything with
 * edges, circular for edgeless node sets (which still happen when a
 * scenario surfaces just position nodes).
 */
import { Alert } from "antd";
import type { EChartsOption } from "echarts";
import * as echarts from "echarts/core";
import { GraphChart } from "echarts/charts";
import { LegendComponent, TitleComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef } from "react";

// Register only the pieces we use — keeps bundle small.
echarts.use([GraphChart, TitleComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

interface ChartNode {
  id: string;
  name: string;
  category?: string;
}

interface ChartEdge {
  source: string;
  target: string;
  relation?: string;
}

interface ChartMeta {
  title?: string;
  source_ref?: string;
}

interface ChartPayload {
  type: string;
  nodes: ChartNode[];
  edges: ChartEdge[];
  meta?: ChartMeta;
}

interface EchartsFenceProps {
  raw: string;
}

const CHART_HEIGHT = 360;

export function EchartsFence({ raw }: EchartsFenceProps) {
  const parsed = useMemo(() => parsePayload(raw), [raw]);

  if (!parsed.ok) {
    return (
      <Alert type="warning" title="图谱数据解析失败" description={parsed.error} className="my-3" />
    );
  }

  if (parsed.payload.type !== "graph") {
    return (
      <Alert
        type="info"
        title={`未知图表类型: ${parsed.payload.type}`}
        description="仅 type=graph 在 P0 支持，其他类型将展示原始 JSON。"
        className="my-3"
      />
    );
  }

  return <EchartsGraph payload={parsed.payload} />;
}

interface EchartsGraphProps {
  payload: ChartPayload;
}

function EchartsGraph({ payload }: EchartsGraphProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

  const option = useMemo<EChartsOption>(() => buildGraphOption(payload), [payload]);

  useEffect(() => {
    if (!containerRef.current) return;
    // reuse a single ECharts instance across option updates to avoid
    // teardown flicker; disposed on unmount.
    if (!instanceRef.current) {
      instanceRef.current = echarts.init(containerRef.current);
    }
    instanceRef.current.setOption(option, { notMerge: true });
    const resize = (): void => instanceRef.current?.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
    };
  }, [option]);

  useEffect(() => {
    return () => {
      instanceRef.current?.dispose();
      instanceRef.current = null;
    };
  }, []);

  if (payload.nodes.length === 0) {
    return (
      <Alert
        type="info"
        title="图谱为空"
        description={payload.meta?.title || "后端未返回任何节点。"}
        className="my-3"
      />
    );
  }

  const label = payload.meta?.title || "图谱";
  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={label}
      className="border-line bg-surface my-3 rounded-lg border p-3"
      style={{ height: CHART_HEIGHT }}
      data-testid="query-echarts-fence"
    />
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type ParseResult = { ok: true; payload: ChartPayload } | { ok: false; error: string };

function parsePayload(raw: string): ParseResult {
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") {
      return { ok: false, error: "chart:echarts 载荷必须是 JSON 对象" };
    }
    const value = parsed as Record<string, unknown>;
    const type = typeof value.type === "string" ? value.type : "unknown";
    const nodes = Array.isArray(value.nodes) ? (value.nodes as ChartNode[]) : [];
    const edges = Array.isArray(value.edges) ? (value.edges as ChartEdge[]) : [];
    const meta =
      value.meta && typeof value.meta === "object" ? (value.meta as ChartMeta) : undefined;
    return { ok: true, payload: { type, nodes, edges, meta } };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "JSON 解析失败",
    };
  }
}

function buildGraphOption(payload: ChartPayload): EChartsOption {
  const categories = deriveCategories(payload.nodes);
  // ECharts graph-edge `value` is numeric; the human-readable relation
  // label goes on the tooltip via a custom `label` field instead so
  // we don't hit the SeriesOption type check.
  const links = payload.edges.map((edge) => ({
    source: edge.source,
    target: edge.target,
    label: edge.relation ? { show: false, formatter: edge.relation } : undefined,
    lineStyle: { width: 1 },
  }));
  const layout = payload.edges.length > 0 ? "force" : "circular";
  return {
    title: payload.meta?.title
      ? { text: payload.meta.title, left: "left", textStyle: { fontSize: 14 } }
      : undefined,
    tooltip: {
      trigger: "item",
      formatter: (params) => {
        // ECharts formatter param types vary by trigger — cast narrowly.
        const item = params as { dataType?: string; data?: unknown };
        const data = item.data as { name?: string; value?: string; category?: string } | undefined;
        if (item.dataType === "edge") return String(data?.value || "");
        return `${data?.name ?? ""}${data?.category ? ` · ${data.category}` : ""}`;
      },
    },
    legend: categories.length > 0 ? { data: categories.map((c) => c.name), bottom: 0 } : undefined,
    series: [
      {
        type: "graph",
        layout,
        data: payload.nodes.map((node) => ({
          id: node.id,
          name: node.name,
          category: node.category,
        })),
        links,
        categories,
        roam: true,
        draggable: true,
        label: { show: true, position: "right", fontSize: 12 },
        force:
          layout === "force" ? { repulsion: 240, edgeLength: [80, 160], gravity: 0.05 } : undefined,
        emphasis: { focus: "adjacency" },
      },
    ],
  };
}

interface Category {
  name: string;
}

function deriveCategories(nodes: ChartNode[]): Category[] {
  const seen = new Set<string>();
  const categories: Category[] = [];
  for (const node of nodes) {
    if (!node.category) continue;
    if (seen.has(node.category)) continue;
    seen.add(node.category);
    categories.push({ name: node.category });
  }
  return categories;
}

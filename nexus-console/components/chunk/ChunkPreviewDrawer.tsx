"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Descriptions, Drawer, Empty, Image, Segmented, Skeleton, Space, Tag, Typography } from "antd";
import type { ECharts, EChartsOption } from "echarts";
import type {
  ChunkSemanticContextResponse,
  ChunkPreviewResponse,
  KnowledgeChunkHit,
  MarkdownHighlightRange,
  PageAnchor,
  SemanticHierarchyContext,
  SemanticHierarchyNode,
  SemanticHierarchyParentScope,
} from "@/lib/chunkTypes";
import { LocatorChip } from "./LocatorChip";

interface ProxyEnvelope<T> {
  ok: true;
  status: number;
  data: T;
  traceId: string | null;
}

interface ProxyErrorEnvelope {
  ok: false;
  status: number;
  message: string;
}

export interface ChunkPreviewDrawerProps {
  chunk: KnowledgeChunkHit | null;
  open: boolean;
  onClose: () => void;
}

type PreviewView = "source" | "semantic";

type KnowledgeGraphChartNode = {
  name: string;
  value?: string;
  nodeType: string;
  isCurrent: boolean;
  containsCurrent: boolean;
  collapsed?: boolean;
  chunkRange?: [number, number] | null;
  chunks?: number;
  itemStyle?: Record<string, unknown>;
  label?: Record<string, unknown>;
  children?: KnowledgeGraphChartNode[];
};

export function ChunkPreviewDrawer({ chunk, open, onClose }: ChunkPreviewDrawerProps) {
  const chunkId = previewChunkId(chunk);
  const [preview, setPreview] = useState<ChunkPreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<PreviewView>("source");
  const [semantic, setSemantic] = useState<ChunkSemanticContextResponse | null>(null);
  const [semanticLoading, setSemanticLoading] = useState(false);
  const [semanticError, setSemanticError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setPreview(null);
      setError(null);
      setLoading(false);
      setView("source");
      setSemantic(null);
      setSemanticError(null);
      setSemanticLoading(false);
      return;
    }
    if (!chunkId) {
      setPreview(null);
      setError("该 chunk 未携带 NEXUS chunk id，无法加载预览。");
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    setPreview(null);

    (async () => {
      try {
        const res = await fetch(
          `/api/knowledge-chunks/${encodeURIComponent(chunkId)}/preview`,
          { cache: "no-store" },
        );
        const body = (await res.json()) as
          | ProxyEnvelope<ChunkPreviewResponse>
          | ProxyErrorEnvelope;
        if (!body.ok) {
          throw new Error(body.message || `HTTP ${res.status}`);
        }
        if (!cancelled) setPreview(body.data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [chunkId, open]);

  useEffect(() => {
    setSemantic(null);
    setSemanticError(null);
    setSemanticLoading(false);
  }, [chunkId]);

  useEffect(() => {
    if (!open || view !== "semantic") return;
    if (!chunkId) {
      setSemantic(null);
      setSemanticError("该 chunk 未携带 NEXUS chunk id，无法加载知识图谱。");
      return;
    }
    if (semantic) return;

    let cancelled = false;
    setSemanticLoading(true);
    setSemanticError(null);

    (async () => {
      try {
        const res = await fetch(
          `/api/knowledge-chunks/${encodeURIComponent(chunkId)}/semantic-context`,
          { cache: "no-store" },
        );
        const body = (await res.json()) as
          | ProxyEnvelope<ChunkSemanticContextResponse>
          | ProxyErrorEnvelope;
        if (!body.ok) {
          throw new Error(body.message || `HTTP ${res.status}`);
        }
        if (!cancelled) setSemantic(body.data);
      } catch (err) {
        if (!cancelled) {
          setSemanticError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setSemanticLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [chunkId, open, semantic, view]);

  const effectiveChunk = preview?.chunk ?? chunk;

  return (
    <Drawer
      title="知识块预览"
      open={open}
      onClose={onClose}
      size={1180}
      destroyOnHidden
    >
      {!chunk ? (
        <Empty description="未选中知识块" />
      ) : error ? (
        <Alert type="error" showIcon title={error} />
      ) : loading || !preview ? (
        <Skeleton active paragraph={{ rows: 10 }} />
      ) : (
        <>
          <div className="mb-4">
            <Segmented<PreviewView>
              value={view}
              onChange={setView}
              options={[
                { label: "原文定位", value: "source" },
                { label: "知识图谱", value: "semantic" },
              ]}
            />
          </div>
          {view === "source" ? (
            <div
              id={`chunk-preview-${chunkId ?? ""}`}
              className="chunk-preview-layout"
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(0, 1fr) minmax(320px, 460px)",
                gap: "var(--space-4)",
                alignItems: "start",
              }}
            >
              <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
                <ChunkOverview preview={preview} chunk={effectiveChunk} />
                <MarkdownAnchorPanel preview={preview} />
              </div>
              <PageAnchorPanel preview={preview} />
              <style jsx>{`
                @media (max-width: 860px) {
                  .chunk-preview-layout {
                    grid-template-columns: minmax(0, 1fr) !important;
                  }
                }
              `}</style>
            </div>
          ) : (
            <SemanticContextPanel
              semantic={semantic}
              loading={semanticLoading}
              error={semanticError}
            />
          )}
        </>
      )}
    </Drawer>
  );
}

function ChunkOverview({
  preview,
  chunk,
}: {
  preview: ChunkPreviewResponse;
  chunk: KnowledgeChunkHit | null;
}) {
  if (!chunk) return null;
  const headingPath = preview.highlight.heading_path ?? [];
  return (
    <section>
      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="知识类型">
          <Space size={6} wrap>
            {chunk.knowledge_type_code ? <Tag color="cyan">{chunk.knowledge_type_code}</Tag> : <Tag>unknown</Tag>}
            {chunk.chunk_type ? <Tag>{chunk.chunk_type}</Tag> : null}
            {preview.highlight.anchor_role ? <Tag color="blue">{preview.highlight.anchor_role}</Tag> : null}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="页面定位">
          <LocatorChip locator={chunk.locator} fallbackPage={chunk.source?.page} />
        </Descriptions.Item>
        {headingPath.length > 0 && (
          <Descriptions.Item label="章节路径">
            <Space size={4} wrap>
              {headingPath.map((h, index) => (
                <Tag key={`${h.level}-${h.title}-${index}`}>H{h.level} {h.title}</Tag>
              ))}
            </Space>
          </Descriptions.Item>
        )}
        {chunk.source_block_ids && chunk.source_block_ids.length > 0 && (
          <Descriptions.Item label="来源 Blocks">
            <Space size={4} wrap>
              {chunk.source_block_ids.map((blockId, index) => (
                <a key={`${blockId}-${index}`} href={`#block-${blockId}`}>
                  <Tag className="cursor-pointer font-mono text-xs">{blockId}</Tag>
                </a>
              ))}
            </Space>
          </Descriptions.Item>
        )}
        <Descriptions.Item label="Chunk ID">
          <Typography.Text className="font-mono text-xs">{previewChunkId(chunk) ?? "-"}</Typography.Text>
        </Descriptions.Item>
      </Descriptions>

      <Typography.Title level={5} className="!mb-2 !mt-4">
        知识块内容
      </Typography.Title>
      <div
        style={{
          border: "1px solid var(--line)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-3)",
          background: "var(--gray-50)",
          maxHeight: 220,
          overflow: "auto",
          whiteSpace: "pre-wrap",
          lineHeight: 1.7,
          fontSize: 13,
        }}
      >
        {chunk.content || "-"}
      </div>
    </section>
  );
}

function MarkdownAnchorPanel({ preview }: { preview: ChunkPreviewResponse }) {
  const body = preview.source.body_markdown;
  const ranges = preview.highlight.markdown_ranges ?? [];
  const excerpts = useMemo(
    () => buildMarkdownExcerpts(body, ranges),
    [body, ranges],
  );

  if (preview.normalized_ref.normalized_type === "record") {
    return (
      <section>
        <Typography.Title level={5} className="!mb-2">
          原文记录
        </Typography.Title>
        {preview.source.record_body ? (
          <pre className="max-h-[46vh] overflow-auto rounded border border-solid border-gray-200 p-3 text-xs">
            {JSON.stringify(preview.source.record_body, null, 2)}
          </pre>
        ) : (
          <Empty description="记录体为空" />
        )}
      </section>
    );
  }

  return (
    <section>
      <Typography.Title level={5} className="!mb-2">
        原文 Markdown 定位
      </Typography.Title>
      {!body ? (
        <Alert type="info" showIcon title="该 normalized ref 暂无 body_markdown，无法显示 markdown 定位。" />
      ) : excerpts.length === 0 ? (
        <Alert type="info" showIcon title="该知识块未携带 md_char_range/md_spans，无法在 markdown 中高亮定位。" />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
          {excerpts.map((excerpt, index) => (
            <div key={`${excerpt.range.start}-${excerpt.range.end}-${index}`}>
              <div className="mb-1 flex items-center gap-2">
                <Tag color="processing">span {index + 1}</Tag>
                {excerpt.range.block_id ? (
                  <a href={`#block-${excerpt.range.block_id}`}>
                    <Tag className="cursor-pointer font-mono text-xs">{excerpt.range.block_id}</Tag>
                  </a>
                ) : null}
                <Typography.Text type="secondary" className="text-xs">
                  {excerpt.range.start}-{excerpt.range.end}
                </Typography.Text>
              </div>
              <pre
                style={{
                  margin: 0,
                  maxHeight: 260,
                  overflow: "auto",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius-md)",
                  padding: "var(--space-3)",
                  background: "#fff",
                  fontSize: 12,
                  lineHeight: 1.7,
                }}
              >
                <span>{excerpt.before}</span>
                <mark
                  style={{
                    background: "var(--warning-50)",
                    color: "inherit",
                    padding: "1px 2px",
                    borderRadius: 3,
                  }}
                >
                  {excerpt.highlight}
                </mark>
                <span>{excerpt.after}</span>
              </pre>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function PageAnchorPanel({ preview }: { preview: ChunkPreviewResponse }) {
  const anchors = useMemo(
    () => normalizePageAnchors(preview.highlight.page_anchors ?? []),
    [preview.highlight.page_anchors],
  );
  const [activeIndex, setActiveIndex] = useState(0);
  const [imageError, setImageError] = useState(false);
  const anchor = anchors[activeIndex] ?? null;

  useEffect(() => {
    setActiveIndex(0);
  }, [preview.chunk.id, anchors.length]);

  useEffect(() => {
    setImageError(false);
  }, [anchor?.page, anchor?.bbox?.join(",")]);

  if (!anchor) {
    return (
      <section>
        <Typography.Title level={5} className="!mb-2">
          PDF 页面定位
        </Typography.Title>
        <Alert type="info" showIcon title="该知识块未携带 page/bbox 定位，无法生成页面截图。" />
      </section>
    );
  }

  const refId = preview.normalized_ref.ref_id;
  const src = pageImageSrc(refId, anchor);

  return (
    <section style={{ position: "sticky", top: 0 }}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <Typography.Title level={5} className="!mb-0">
          PDF 页面定位
        </Typography.Title>
        <Space size={4} wrap>
          <Tag>p{anchor.page}</Tag>
          {anchors.length > 1 ? <Tag color="processing">{activeIndex + 1}/{anchors.length}</Tag> : null}
          {anchor.block_id ? <Tag className="font-mono text-xs">{anchor.block_id}</Tag> : null}
        </Space>
      </div>

      {anchors.length > 1 ? (
        <div className="mb-2 flex flex-wrap gap-1">
          {anchors.map((item, index) => (
            <button
              key={`${item.page}-${item.block_id ?? "block"}-${index}`}
              type="button"
              onClick={() => setActiveIndex(index)}
              className="rounded border border-[var(--line)] px-2 py-1 text-xs hover:border-[var(--line-strong)]"
              style={{
                background: index === activeIndex ? "var(--brand-50)" : "#fff",
                color: index === activeIndex ? "var(--brand-700)" : "var(--text-muted)",
              }}
            >
              p{item.page}{item.block_id ? ` · ${item.block_id}` : ""}
            </button>
          ))}
        </div>
      ) : null}

      {imageError ? (
        <Alert
          type="warning"
          showIcon
          title="页面图片加载失败"
          description="常见原因：原始文件不是 PDF、对象存储缺失，或该 chunk 只有 markdown 定位。"
        />
      ) : (
        <div
          style={{
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-md)",
            background: "var(--gray-50)",
            padding: "var(--space-2)",
            maxHeight: "72vh",
            overflow: "auto",
          }}
        >
          <Image
            src={src}
            alt={`page ${anchor.page} source preview`}
            width="100%"
            preview={false}
            onError={() => setImageError(true)}
            style={{ display: "block", background: "#fff" }}
          />
        </div>
      )}
    </section>
  );
}

function SemanticContextPanel({
  semantic,
  loading,
  error,
}: {
  semantic: ChunkSemanticContextResponse | null;
  loading: boolean;
  error: string | null;
}) {
  if (error) {
    return <Alert type="error" showIcon title={error} />;
  }
  if (loading || !semantic) {
    return <Skeleton active paragraph={{ rows: 8 }} />;
  }

  const context = semantic.context;
  const hierarchy = context.hierarchy;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      <section>
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="当前 Chunk">
            <Typography.Text className="font-mono text-xs">
              {semantic.chunk.id ?? semantic.chunk.nexus_chunk_id ?? semantic.chunk.chunk_id}
            </Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="层级路径">
            {hierarchy?.path.length ? (
              <Space size={4} wrap>
                {hierarchy.path.map((item) => (
                  <Tag key={item.node_id} color={nodeTypeColor(item.node_type)}>
                    {nodeTypeLabel(item.node_type)} · {item.display_title || item.title}
                  </Tag>
                ))}
              </Space>
            ) : (
              <Typography.Text type="secondary">未识别章节路径</Typography.Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="所属范围">
            {hierarchy?.parent_scope ? (
              <Space size={6} wrap>
                <Tag color="processing">{hierarchy.parent_scope.display_title || hierarchy.parent_scope.title}</Tag>
                {hierarchy.parent_scope.chunk_range ? (
                  <Tag>
                    chunk #{hierarchy.parent_scope.chunk_range[0]}-{hierarchy.parent_scope.chunk_range[1]}
                  </Tag>
                ) : null}
                <Tag>{hierarchy.parent_scope.knowledge_points.length} 个知识点</Tag>
              </Space>
            ) : (
              <Typography.Text type="secondary">暂无可展示的父节点范围</Typography.Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="构建来源">
            <Space size={4} wrap>
              <Tag>{hierarchy?.source === "normalized_blocks" ? "normalized blocks" : "chunk locator"}</Tag>
              <Tag>{context.policy.source}</Tag>
            </Space>
          </Descriptions.Item>
        </Descriptions>
      </section>

      {!hierarchy || !hierarchy.parent_scope ? (
        <Empty description="当前知识块暂无可展示的知识图谱。" />
      ) : (
        <KnowledgeGraphPanel hierarchy={hierarchy} />
      )}
    </div>
  );
}

function KnowledgeGraphPanel({ hierarchy }: { hierarchy: SemanticHierarchyContext }) {
  const scope = hierarchy.parent_scope;
  const roots = useMemo(() => focusedHierarchyRoots(hierarchy), [hierarchy]);
  const leafCount = useMemo(() => countLeafNodes(roots), [roots]);

  if (!scope) {
    return <Empty description="暂无知识图谱数据。" />;
  }

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Typography.Title level={5} className="!mb-0">
          {scope.display_title || scope.title}
        </Typography.Title>
        <Tag color={nodeTypeColor(scope.node_type)}>{nodeTypeLabel(scope.node_type)}</Tag>
        {scope.chunk_range ? <Tag>chunk #{scope.chunk_range[0]}-{scope.chunk_range[1]}</Tag> : null}
        <Tag>{leafCount} 个知识点</Tag>
      </div>
      <KnowledgeGraphTreeChart roots={roots} />
    </section>
  );
}

function parentScopeToNode(
  scope: NonNullable<SemanticHierarchyContext["parent_scope"]>,
  currentChunkId: string,
): SemanticHierarchyNode {
  const overviewLeafNodes = scope.overview_chunks.map((item, index) => (
    chunkToLeafNode(item, scope, currentChunkId, index)
  ));
  const overviewChunkIds = new Set(
    scope.overview_chunks
      .flatMap((item) => [item.id, item.chunk_id])
      .filter((item): item is string => Boolean(item)),
  );
  const knowledgePoints = scope.knowledge_points.filter((node) => {
    const nodeChunkIds = node.chunks.flatMap((item) => [item.id, item.chunk_id]);
    return !nodeChunkIds.some((item) => overviewChunkIds.has(item));
  });
  return {
    node_id: scope.node_id,
    title: scope.title,
    display_title: scope.display_title,
    node_type: scope.node_type,
    level: scope.level,
    source_block_id: scope.source_block_id,
    seq_range: scope.seq_range,
    is_current: false,
    contains_current: true,
    chunks: [],
    chunk_range: scope.chunk_range,
    children: [...overviewLeafNodes, ...knowledgePoints, ...scope.children],
  };
}

function chunkToLeafNode(
  chunk: SemanticHierarchyParentScope["overview_chunks"][number],
  scope: NonNullable<SemanticHierarchyContext["parent_scope"]>,
  currentChunkId: string,
  index: number,
): SemanticHierarchyNode {
  const isCurrent = chunk.id === currentChunkId || chunk.chunk_id === currentChunkId;
  return {
    node_id: `chunk:${chunk.id || chunk.chunk_id || index}`,
    title: chunk.content,
    display_title: summarizeChunkTitle(chunk.content),
    node_type: "knowledge_point",
    level: scope.level + 1,
    source_block_id: chunk.source_block_ids?.[0] ?? null,
    seq_range: null,
    is_current: isCurrent,
    contains_current: isCurrent,
    chunks: [chunk],
    chunk_range: [chunk.chunk_index, chunk.chunk_index],
    children: [],
  };
}

function summarizeChunkTitle(content: string): string {
  const text = content.replace(/\s+/g, " ").replace(/[。；;\s]+$/g, "").trim();
  if (!text) return "未命名知识点";
  const chars = Array.from(text);
  return chars.length <= 48 ? text : `${chars.slice(0, 47).join("")}…`;
}

function focusedHierarchyRoots(hierarchy: SemanticHierarchyContext): SemanticHierarchyNode[] {
  const scope = hierarchy.parent_scope;
  if (!scope) return hierarchy.tree;

  const scopeNode = parentScopeToNode(scope, hierarchy.current_chunk_id);
  const path = hierarchy.path.filter((item) => item.node_id !== hierarchy.current_node_id);
  if (path.length === 0) return [scopeNode];

  let child: SemanticHierarchyNode = scopeNode;
  for (let index = path.length - 1; index >= 0; index -= 1) {
    const item = path[index];
    if (item.node_id === scope.node_id) {
      child = { ...scopeNode, contains_current: true };
      continue;
    }
    child = {
      node_id: item.node_id,
      title: item.title,
      display_title: item.display_title,
      node_type: item.node_type,
      level: item.level,
      source_block_id: item.source_block_id,
      seq_range: item.seq_range,
      is_current: false,
      contains_current: true,
      chunks: [],
      chunk_range: scope.chunk_range,
      children: [child],
    };
  }
  return [child];
}

function KnowledgeGraphTreeChart({ roots }: { roots: SemanticHierarchyNode[] }) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const option = useMemo<EChartsOption>(() => buildKnowledgeGraphOption(roots), [roots]);

  useEffect(() => {
    const container = chartRef.current;
    if (!container) return;
    let disposed = false;
    let chart: ECharts | null = null;
    let removeResize: (() => void) | null = null;
    let resizeTimer: number | null = null;

    import("echarts").then((echarts) => {
      if (disposed || !chartRef.current) return;
      chart = echarts.init(chartRef.current);
      chart.setOption(option);
      const resize = () => chart?.resize();
      window.addEventListener("resize", resize);
      removeResize = () => window.removeEventListener("resize", resize);
      resizeTimer = window.setTimeout(resize, 120);
    });

    return () => {
      disposed = true;
      if (resizeTimer) window.clearTimeout(resizeTimer);
      removeResize?.();
      chart?.dispose();
    };
  }, [option]);

  return (
    <div
      ref={chartRef}
      style={{
        width: "100%",
        minHeight: 560,
        height: "64vh",
        maxHeight: 820,
        border: "1px solid var(--line)",
        borderRadius: "var(--radius-md)",
        background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
        boxShadow: "inset 0 1px 0 rgba(255, 255, 255, 0.8)",
      }}
      aria-label="知识图谱树图"
    />
  );
}

function toChartNode(node: SemanticHierarchyNode): KnowledgeGraphChartNode {
  const isCurrent = node.is_current || node.chunks.some((item) => Boolean(item.is_current));
  const style = chartNodeStyle(node.node_type, isCurrent, node.contains_current);
  const children = node.children.map(toChartNode);
  return {
    name: node.display_title || node.title,
    value: node.node_id,
    nodeType: node.node_type,
    isCurrent,
    containsCurrent: node.contains_current,
    collapsed: false,
    chunkRange: node.chunk_range,
    chunks: node.chunks.length,
    itemStyle: {
      color: style.symbolColor,
      borderColor: style.borderColor,
      borderWidth: isCurrent ? 3 : 1.5,
      shadowBlur: isCurrent ? 8 : 0,
      shadowColor: isCurrent ? "rgba(180, 83, 9, 0.28)" : "transparent",
    },
    label: {
      fontWeight: isCurrent || node.contains_current ? 600 : 400,
      color: style.textColor,
      backgroundColor: style.labelBackground,
      borderColor: style.borderColor,
      borderWidth: 1,
      borderRadius: 6,
      padding: [6, 8],
      lineHeight: 17,
    },
    ...(children.length > 0 ? { children } : {}),
  };
}

function chartNodeStyle(nodeType: string, isCurrent: boolean, containsCurrent: boolean) {
  if (isCurrent) {
    return {
      symbolColor: "#f59e0b",
      borderColor: "#b45309",
      textColor: "#78350f",
      labelBackground: "#fffbeb",
    };
  }
  if (nodeType === "knowledge_point") {
    return {
      symbolColor: containsCurrent ? "#10b981" : "#34d399",
      borderColor: containsCurrent ? "#047857" : "#059669",
      textColor: "#064e3b",
      labelBackground: "#ecfdf5",
    };
  }
  if (nodeType === "section") {
    return {
      symbolColor: containsCurrent ? "#2563eb" : "#60a5fa",
      borderColor: containsCurrent ? "#1d4ed8" : "#3b82f6",
      textColor: "#1e3a8a",
      labelBackground: "#eff6ff",
    };
  }
  return {
    symbolColor: containsCurrent ? "#7c3aed" : "#94a3b8",
    borderColor: containsCurrent ? "#6d28d9" : "#64748b",
    textColor: containsCurrent ? "#4c1d95" : "#334155",
    labelBackground: containsCurrent ? "#f5f3ff" : "#f8fafc",
  };
}

function buildKnowledgeGraphOption(roots: SemanticHierarchyNode[]): EChartsOption {
  const data = roots.map(toChartNode);
  return {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      triggerOn: "mousemove",
      formatter: (params: unknown) => {
        const dataNode = (params as { data?: KnowledgeGraphChartNode }).data;
        if (!dataNode) return "";
        const range = dataNode.chunkRange ? `<br/>chunk #${dataNode.chunkRange[0]}-${dataNode.chunkRange[1]}` : "";
        return `${nodeTypeLabel(dataNode.nodeType)}：${dataNode.name}${range}`;
      },
    },
    series: [
      {
        type: "tree",
        data,
        top: 42,
        left: 96,
        bottom: 42,
        right: 220,
        orient: "LR",
        roam: true,
        expandAndCollapse: false,
        initialTreeDepth: 20,
        animationDuration: 220,
        animationDurationUpdate: 220,
        symbol: "roundRect",
        symbolSize: [14, 14],
        edgeShape: "curve",
        lineStyle: {
          color: "#cbd5e1",
          width: 1.6,
          curveness: 0.18,
        },
        label: {
          position: "right",
          verticalAlign: "middle",
          align: "left",
          color: "#334155",
          fontSize: 12,
          lineHeight: 16,
          distance: 10,
          formatter: (params: unknown) => {
            const dataNode = (params as { data?: KnowledgeGraphChartNode }).data;
            return dataNode ? wrapChartLabel(dataNode.name, dataNode.nodeType) : "";
          },
        },
        leaves: {
          label: {
            position: "right",
            verticalAlign: "middle",
            align: "left",
            distance: 12,
            lineHeight: 16,
          },
        },
        itemStyle: {
          color: "#2563eb",
          borderColor: "#1d4ed8",
          borderWidth: 1,
        },
        emphasis: {
          focus: "descendant",
        },
      },
    ],
  };
}

function wrapChartLabel(label: string, nodeType: string): string {
  const maxLineLength = nodeType === "knowledge_point" ? 18 : 14;
  const maxLines = nodeType === "knowledge_point" ? 3 : 2;
  const chars = Array.from(label);
  if (chars.length <= maxLineLength) return label;
  const lines: string[] = [];
  for (let index = 0; index < chars.length && lines.length < maxLines; index += maxLineLength) {
    lines.push(chars.slice(index, index + maxLineLength).join(""));
  }
  if (chars.length > maxLineLength * maxLines && lines.length > 0) {
    lines[lines.length - 1] = `${lines[lines.length - 1].slice(0, -1)}…`;
  }
  return lines.join("\n");
}

function countLeafNodes(nodes: SemanticHierarchyNode[]): number {
  let count = 0;
  const visit = (node: SemanticHierarchyNode) => {
    if (node.children.length === 0 || node.node_type === "knowledge_point") {
      count += 1;
      return;
    }
    node.children.forEach(visit);
  };
  nodes.forEach(visit);
  return count;
}

function nodeTypeLabel(type: string): string {
  return {
    chapter: "章",
    section: "节",
    knowledge_point: "知识点",
  }[type] ?? type;
}

function nodeTypeColor(type: string): string {
  return {
    chapter: "cyan",
    section: "blue",
    knowledge_point: "processing",
  }[type] ?? "default";
}

function previewChunkId(chunk: KnowledgeChunkHit | null): string | null {
  if (!chunk) return null;
  return chunk.id ?? chunk.nexus_chunk_id ?? null;
}

interface MarkdownExcerpt {
  range: MarkdownHighlightRange;
  before: string;
  highlight: string;
  after: string;
}

function buildMarkdownExcerpts(
  body: string | null,
  ranges: MarkdownHighlightRange[],
): MarkdownExcerpt[] {
  if (!body || ranges.length === 0) return [];
  const out: MarkdownExcerpt[] = [];
  for (const range of ranges) {
    const start = clamp(range.start, 0, body.length);
    const end = clamp(range.end, start, body.length);
    if (end <= start) continue;
    const contextStart = snapExcerptStart(body, Math.max(0, start - 240));
    const contextEnd = snapExcerptEnd(body, Math.min(body.length, end + 240));
    out.push({
      range: { ...range, start, end },
      before: body.slice(contextStart, start),
      highlight: body.slice(start, end),
      after: body.slice(end, contextEnd),
    });
  }
  return out;
}

function normalizePageAnchors(anchors: PageAnchor[]): PageAnchor[] {
  return anchors.filter((anchor) => Number.isFinite(anchor.page));
}

function pageImageSrc(refId: string, anchor: PageAnchor): string {
  const params = new URLSearchParams({ page: String(anchor.page) });
  if (anchor.bbox) {
    params.set("bbox", anchor.bbox.join(","));
  }
  return `/api/normalized-refs/${encodeURIComponent(refId)}/page-image?${params.toString()}`;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function snapExcerptStart(body: string, pos: number): number {
  let p = pos;
  while (p > 0 && body[p - 1] !== "\n") p--;
  return p;
}

function snapExcerptEnd(body: string, pos: number): number {
  let p = pos;
  while (p < body.length && body[p] !== "\n") p++;
  return p;
}

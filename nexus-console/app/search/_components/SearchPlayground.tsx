"use client";

/**
 * SearchPlayground — 检索/QA 验证入口（消费侧 demo，非最终用户搜索门户）。
 *
 * 数据流：
 * - 所有后端调用走 Next.js route handler（/api/search、/api/qa、
 *   /api/raw-objects/[id]/download-url），caller_key 不暴露到浏览器
 *   （见 lib/searchProxy.ts）。
 * - chunk 列表通过 ChunkCard 渲染；点击"展开详情"开 ChunkDetailDrawer。
 * - QA 模式答案区顶部展示 AnswerConfidenceBadge。
 */

import { useCallback, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Segmented,
  Select,
  Skeleton,
  Slider,
  Space,
  Tag,
  Typography,
} from "antd";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type {
  KnowledgeRetrievalResponse,
  KnowledgeTypeOption,
  QaResponse,
  RetrievalConversationStep,
  RetrievalResult,
  RetrievalSourceRef,
  SearchResponse,
} from "../_lib/searchTypes";
import type { KnowledgeChunkHit } from "@/lib/chunkTypes";
import { ChunkCard } from "@/components/chunk/ChunkCard";
import { ChunkDetailDrawer } from "@/components/chunk/ChunkDetailDrawer";
import { AnswerConfidenceBadge } from "./AnswerConfidenceBadge";

type Mode = "search" | "qa" | "retrieval";

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

const DEFAULT_TOP_K = 5;
const DEFAULT_THRESHOLD = 0.7;

export function SearchPlayground({ knowledgeTypes }: { knowledgeTypes: KnowledgeTypeOption[] }) {
  const [mode, setMode] = useState<Mode>("search");
  const [query, setQuery] = useState("");
  const [kb, setKb] = useState<string | undefined>(undefined);
  const [topK, setTopK] = useState<number>(DEFAULT_TOP_K);
  const [threshold, setThreshold] = useState<number>(DEFAULT_THRESHOLD);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchData, setSearchData] = useState<SearchResponse | null>(null);
  const [qaData, setQaData] = useState<QaResponse | null>(null);
  const [retrievalData, setRetrievalData] = useState<KnowledgeRetrievalResponse | null>(null);

  const [selectedChunk, setSelectedChunk] = useState<KnowledgeChunkHit | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const reset = useCallback(() => {
    setSearchData(null);
    setQaData(null);
    setRetrievalData(null);
    setError(null);
  }, []);

  const handleSubmit = useCallback(async () => {
    const trimmed = query.trim();
    if (!trimmed) {
      setError("请先输入查询关键词或问题");
      return;
    }
    setLoading(true);
    reset();
    try {
      if (mode === "search") {
        const data = await fetchSearch(trimmed, kb, topK, threshold);
        setSearchData(data);
      } else if (mode === "qa") {
        const data = await fetchQa(trimmed, kb, topK);
        setQaData(data);
      } else {
        const data = await fetchKnowledgeRetrieval(trimmed);
        setRetrievalData(data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [mode, query, kb, topK, threshold, reset]);

  const openChunkDetail = useCallback((chunk: KnowledgeChunkHit) => {
    setSelectedChunk(chunk);
    setDrawerOpen(true);
  }, []);

  return (
    <>
      <Space orientation="vertical" size="middle" className="w-full">
        <Card>
          <Form layout="vertical" onFinish={handleSubmit}>
            <Space size="middle" wrap>
              <Segmented<Mode>
                value={mode}
                onChange={(v) => {
                  setMode(v);
                  reset();
                }}
                options={[
                  { label: "语义检索", value: "search" },
                  { label: "问答 (QA)", value: "qa" },
                  { label: "召回编排", value: "retrieval" },
                ]}
              />
              {mode !== "retrieval" && (
                <>
                  <Form.Item label="知识库" className="!mb-0" style={{ minWidth: 220 }}>
                    <Select
                      allowClear
                      placeholder="默认 textbook_kb"
                      value={kb}
                      onChange={(v) => setKb(v ?? undefined)}
                      options={knowledgeTypes.map((kt) => ({
                        value: kt.code,
                        label: `${kt.name}（${kt.code}）`,
                      }))}
                    />
                  </Form.Item>
                  <Form.Item label="top_k" className="!mb-0">
                    <InputNumber
                      min={1}
                      max={50}
                      value={topK}
                      onChange={(v) => setTopK(typeof v === "number" ? v : DEFAULT_TOP_K)}
                    />
                  </Form.Item>
                </>
              )}
              {mode === "search" && (
                <Form.Item label="相似度阈值" className="!mb-0" style={{ minWidth: 200 }}>
                  <Slider
                    min={0}
                    max={1}
                    step={0.05}
                    value={threshold}
                    onChange={(v) => setThreshold(v)}
                  />
                </Form.Item>
              )}
            </Space>

            <Form.Item label={mode === "search" ? "检索关键词" : "问题"} className="!mt-4 !mb-2">
              <Input.Search
                size="large"
                enterButton={
                  mode === "search" ? "检索" : mode === "qa" ? "提问" : "执行召回"
                }
                loading={loading}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onSearch={handleSubmit}
                placeholder={
                  mode === "search"
                    ? "例如：教材中关于光合作用的章节"
                    : mode === "qa"
                      ? "例如：光合作用的暗反应阶段发生在哪里？"
                      : "例如：近三年高职电子商务专业布点数变化，并说明相关专业简介依据"
                }
              />
            </Form.Item>

            {error && (
              <Alert
                type="error"
                showIcon
                className="!mt-2"
                title={error}
                action={
                  <Button size="small" onClick={handleSubmit}>
                    重试
                  </Button>
                }
              />
            )}
          </Form>
        </Card>

        <ResultPanel
          mode={mode}
          loading={loading}
          searchData={searchData}
          qaData={qaData}
          retrievalData={retrievalData}
          onSelectChunk={openChunkDetail}
        />
      </Space>

      <ChunkDetailDrawer
        chunk={selectedChunk}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </>
  );
}

// ── Result panel ────────────────────────────────────────────────────────

interface ResultPanelProps {
  mode: Mode;
  loading: boolean;
  searchData: SearchResponse | null;
  qaData: QaResponse | null;
  retrievalData: KnowledgeRetrievalResponse | null;
  onSelectChunk: (chunk: KnowledgeChunkHit) => void;
}

function ResultPanel({
  mode,
  loading,
  searchData,
  qaData,
  retrievalData,
  onSelectChunk,
}: ResultPanelProps) {
  if (loading) {
    return (
      <Card>
        <Skeleton active paragraph={{ rows: 4 }} />
      </Card>
    );
  }

  if (mode === "search") {
    if (!searchData) {
      return (
        <Card>
          <Empty description="输入查询后将展示命中的 chunk 列表与引用追溯" />
        </Card>
      );
    }
    return <SearchResultList data={searchData} onSelectChunk={onSelectChunk} />;
  }

  if (mode === "qa") {
    if (!qaData) {
      return (
        <Card>
          <Empty description="输入问题后将展示 AI 回答与引用源" />
        </Card>
      );
    }
    return <QaResult data={qaData} onSelectChunk={onSelectChunk} />;
  }

  if (!retrievalData) {
    return (
      <Card>
        <Empty description="输入问题后将展示多步骤召回、辅助分析与 Markdown 结果" />
      </Card>
    );
  }
  return <RetrievalResultView data={retrievalData} />;
}

function SearchResultList({
  data,
  onSelectChunk,
}: {
  data: SearchResponse;
  onSelectChunk: (chunk: KnowledgeChunkHit) => void;
}) {
  if (data.results.length === 0) {
    return (
      <Card>
        <Empty description="没有命中任何 chunk，尝试降低相似度阈值或更换关键词" />
      </Card>
    );
  }
  return (
    <Card
      title={
        <Space>
          <span>检索结果</span>
          <Tag color="processing">命中 {data.count}</Tag>
          {data.kb && <Tag color="purple">KB: {data.kb}</Tag>}
        </Space>
      }
    >
      <List<KnowledgeChunkHit>
        dataSource={data.results}
        renderItem={(item) => (
          <List.Item key={item.chunk_id}>
            <ChunkCard chunk={item} onSelect={onSelectChunk} />
          </List.Item>
        )}
      />
    </Card>
  );
}

function QaResult({
  data,
  onSelectChunk,
}: {
  data: QaResponse;
  onSelectChunk: (chunk: KnowledgeChunkHit) => void;
}) {
  return (
    <Space orientation="vertical" size="middle" className="w-full">
      <Card
        title={
          <Space>
            <span>AI 回答</span>
            <AnswerConfidenceBadge confidence={data.answer_confidence} />
          </Space>
        }
      >
        <Typography.Paragraph className="!mb-0 whitespace-pre-wrap">
          {data.answer || "（空回答）"}
        </Typography.Paragraph>
      </Card>
      <Card
        title={
          <Space>
            <span>引用源</span>
            <Tag color="processing">{data.sources.length}</Tag>
            {data.kb && <Tag color="purple">KB: {data.kb}</Tag>}
          </Space>
        }
      >
        {data.sources.length === 0 ? (
          <Empty description="未返回引用源" />
        ) : (
          <List<KnowledgeChunkHit>
            dataSource={data.sources}
            renderItem={(src, idx) => (
              <List.Item key={src.chunk_id ?? `src-${idx}`}>
                <ChunkCard chunk={src} onSelect={onSelectChunk} />
              </List.Item>
            )}
          />
        )}
      </Card>
    </Space>
  );
}

function RetrievalResultView({ data }: { data: KnowledgeRetrievalResponse }) {
  const isClarification = data.status === "needs_clarification";
  return (
    <Space orientation="vertical" size="middle" className="w-full">
      <Card
        title={
          <Space wrap>
            <span>{isClarification ? "需要补充问题" : "召回结果"}</span>
            <Tag color={statusColor(data.status)}>{statusLabel(data.status)}</Tag>
            <Tag color="blue">范围: {data.access_scope}</Tag>
          </Space>
        }
      >
        {isClarification ? (
          <ClarificationBlock data={data} />
        ) : data.markdown ? (
          <div className="max-w-none leading-7">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.markdown}</ReactMarkdown>
          </div>
        ) : (
          <Empty description="本次召回没有生成 Markdown 结果" />
        )}
      </Card>

      <RetrievalStepTimeline steps={data.conversation_steps} results={data.retrieval_results} />

      <Collapse
        defaultActiveKey={isClarification ? ["intent", "plan"] : ["intent"]}
        items={[
          {
            key: "intent",
            label: "意图识别",
            children: <IntentAnalysisPanel data={data} />,
          },
          {
            key: "plan",
            label: "召回计划",
            children: <RetrievalPlanPanel data={data} />,
          },
          {
            key: "sources",
            label: `来源与定位 (${data.source_refs.length})`,
            children: <SourceRefList refs={data.source_refs} />,
          },
        ]}
      />
    </Space>
  );
}

function ClarificationBlock({ data }: { data: KnowledgeRetrievalResponse }) {
  const clarification = data.clarification;
  return (
    <Space orientation="vertical" size="small" className="w-full">
      <Alert
        type="warning"
        showIcon
        title={clarification?.message ?? "当前问题的检索意图不够清晰。"}
      />
      {clarification?.missing_constraints?.length ? (
        <div>
          <Typography.Text strong>缺失约束</Typography.Text>
          <Space wrap className="ml-2">
            {clarification.missing_constraints.map((item) => (
              <Tag key={item}>{item}</Tag>
            ))}
          </Space>
        </div>
      ) : null}
      {clarification?.suggested_refinements?.length ? (
        <List
          size="small"
          header={<Typography.Text strong>建议补充</Typography.Text>}
          dataSource={clarification.suggested_refinements}
          renderItem={(item) => <List.Item>{item}</List.Item>}
        />
      ) : null}
    </Space>
  );
}

function RetrievalStepTimeline({
  steps,
  results,
}: {
  steps: RetrievalConversationStep[];
  results: RetrievalResult[];
}) {
  return (
    <Card title="执行步骤">
      <List
        grid={{ gutter: 12, xs: 1, sm: 2, lg: 3, xl: 5 }}
        dataSource={steps}
        renderItem={(step) => (
          <List.Item key={step.step}>
            <Card size="small" title={step.title}>
              <Space orientation="vertical" size={4} className="w-full">
                <Tag color={statusColor(step.status)}>{statusLabel(step.status)}</Tag>
                {step.message && (
                  <Typography.Text type="secondary">{step.message}</Typography.Text>
                )}
                {step.step === "parallel_retrieval" && (
                  <SubQuerySummary results={results} />
                )}
              </Space>
            </Card>
          </List.Item>
        )}
      />
    </Card>
  );
}

function SubQuerySummary({ results }: { results: RetrievalResult[] }) {
  if (!results.length) return null;
  return (
    <Space orientation="vertical" size={2} className="w-full">
      {results.map((result) => (
        <Typography.Text key={result.query_id} type="secondary">
          {result.query_id} · {result.domain} · {result.result_shape ?? "-"} ·{" "}
          {statusLabel(result.status)}
          {result.error_message ? ` · ${result.error_message}` : ""}
        </Typography.Text>
      ))}
    </Space>
  );
}

function IntentAnalysisPanel({ data }: { data: KnowledgeRetrievalResponse }) {
  const intent = data.intent;
  return (
    <Space orientation="vertical" size="small" className="w-full">
      <Space wrap>
        {intent.business_domains.map((domain) => (
          <Tag key={domain} color="blue">
            {domain}
          </Tag>
        ))}
        {intent.retrieval_channels.map((channel) => (
          <Tag key={channel} color="purple">
            {channel}
          </Tag>
        ))}
        <Tag color="green">{intent.question_type}</Tag>
        <Tag color={intent.confidence >= intent.confidence_threshold ? "success" : "warning"}>
          置信度 {formatPercent(intent.confidence)}
        </Tag>
      </Space>
      {Object.keys(intent.constraints ?? {}).length > 0 && (
        <pre className="max-h-56 overflow-auto rounded bg-slate-50 p-3 text-xs">
          {JSON.stringify(intent.constraints, null, 2)}
        </pre>
      )}
      {intent.suggested_refinements?.length ? (
        <List
          size="small"
          header={<Typography.Text strong>建议优化</Typography.Text>}
          dataSource={intent.suggested_refinements}
          renderItem={(item) => <List.Item>{item}</List.Item>}
        />
      ) : null}
    </Space>
  );
}

function RetrievalPlanPanel({ data }: { data: KnowledgeRetrievalResponse }) {
  const plan = data.retrieval_plan;
  if (!plan) return <Empty description="未生成召回计划" />;
  return (
    <Space orientation="vertical" size="small" className="w-full">
      <Typography.Text type="secondary">{plan.merge_goal}</Typography.Text>
      <List
        dataSource={plan.sub_queries}
        renderItem={(subQuery) => (
          <List.Item key={subQuery.query_id}>
            <Card size="small" className="w-full">
              <Space orientation="vertical" size="small" className="w-full">
                <Space wrap>
                  <Tag color="processing">{subQuery.query_id}</Tag>
                  <Tag>{subQuery.channel}</Tag>
                  <Tag>{subQuery.domain}</Tag>
                  <Typography.Text>{subQuery.purpose}</Typography.Text>
                </Space>
                <Typography.Text>{subQuery.query_text}</Typography.Text>
                <pre className="max-h-64 overflow-auto rounded bg-slate-50 p-3 text-xs">
                  {JSON.stringify(
                    subQuery.structured_plan ?? subQuery.unstructured_plan ?? {},
                    null,
                    2,
                  )}
                </pre>
              </Space>
            </Card>
          </List.Item>
        )}
      />
    </Space>
  );
}

function SourceRefList({ refs }: { refs: RetrievalSourceRef[] }) {
  if (!refs.length) return <Empty description="未返回来源定位" />;
  return (
    <List
      dataSource={refs}
      renderItem={(ref) => (
        <List.Item key={ref.source_ref_id}>
          <Space orientation="vertical" size={2} className="w-full">
            <Space wrap>
              <Tag color="processing">{ref.source_ref_id}</Tag>
              <Tag>{ref.channel}</Tag>
              <Tag>{ref.domain}</Tag>
              {ref.score != null && <Tag color="green">{ref.score.toFixed(3)}</Tag>}
            </Space>
            <Typography.Text type="secondary">
              {ref.asset_id ?? "-"} / {ref.asset_version_id ?? "-"} /{" "}
              {ref.normalized_ref_id ?? "-"}
            </Typography.Text>
            <Typography.Text type="secondary">
              {ref.chunk_id ?? ref.record_ref ?? "无 chunk/record 定位"}
            </Typography.Text>
            {ref.locator && Object.keys(ref.locator).length > 0 && (
              <pre className="max-h-32 overflow-auto rounded bg-slate-50 p-2 text-xs">
                {JSON.stringify(ref.locator, null, 2)}
              </pre>
            )}
          </Space>
        </List.Item>
      )}
    />
  );
}

// ── Client-side fetch helpers ───────────────────────────────────────────

async function fetchSearch(
  q: string,
  kb: string | undefined,
  topK: number,
  threshold: number,
): Promise<SearchResponse> {
  const params = buildParams({ q, kb, top_k: topK, similarity_threshold: threshold });
  return readEnvelope<SearchResponse>(await fetch(`/api/search?${params}`, { cache: "no-store" }));
}

async function fetchQa(q: string, kb: string | undefined, topK: number): Promise<QaResponse> {
  const params = buildParams({ q, kb, top_k: topK });
  return readEnvelope<QaResponse>(await fetch(`/api/qa?${params}`, { cache: "no-store" }));
}

async function fetchKnowledgeRetrieval(q: string): Promise<KnowledgeRetrievalResponse> {
  return readEnvelope<KnowledgeRetrievalResponse>(
    await fetch("/api/knowledge-retrieval", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query: q }),
      cache: "no-store",
    }),
  );
}

function buildParams(p: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) {
    if (v === undefined || v === null || v === "") continue;
    params.set(k, String(v));
  }
  return params.toString();
}

async function readEnvelope<T>(res: Response): Promise<T> {
  const body = (await res.json()) as ProxyEnvelope<T> | ProxyErrorEnvelope;
  if (!body.ok) {
    throw new Error(body.message || `HTTP ${res.status}`);
  }
  return body.data;
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: "等待",
    running: "执行中",
    completed: "完成",
    needs_clarification: "需澄清",
    blocked: "阻断",
    failed: "失败",
    skipped: "跳过",
    planned: "已规划",
    partial: "部分完成",
  };
  return labels[status] ?? status;
}

function statusColor(status: string): string {
  const colors: Record<string, string> = {
    pending: "default",
    running: "processing",
    completed: "success",
    needs_clarification: "warning",
    blocked: "warning",
    failed: "error",
    skipped: "default",
    planned: "processing",
    partial: "warning",
  };
  return colors[status] ?? "default";
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

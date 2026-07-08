"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Collapse,
  Empty,
  Input,
  InputNumber,
  List,
  Progress,
  Segmented,
  Select,
  Slider,
  Space,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock3,
  Database,
  FileSearch,
  ListChecks,
  Loader2,
  MessagesSquare,
  RefreshCw,
  Search,
  Send,
  Settings2,
  Split,
  UserRound,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { ChunkCard } from "@/components/chunk/ChunkCard";
import { ChunkDetailDrawer } from "@/components/chunk/ChunkDetailDrawer";
import type { KnowledgeChunkHit } from "@/lib/chunkTypes";

import { AnswerConfidenceBadge } from "./AnswerConfidenceBadge";
import type {
  KnowledgeRetrievalResponse,
  KnowledgeTypeOption,
  QaResponse,
  RetrievalConversationStep,
  RetrievalResult,
  RetrievalSourceRef,
  SearchResponse,
} from "../_lib/searchTypes";

type Mode = "retrieval" | "search" | "qa";
type MessageRole = "user" | "assistant";
type MessageStatus = "idle" | "running" | "completed" | "needs_clarification" | "failed";

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

interface ConversationMessage {
  id: string;
  role: MessageRole;
  mode: Mode;
  query: string;
  createdAt: Date;
  status: MessageStatus;
  searchData?: SearchResponse;
  qaData?: QaResponse;
  retrievalData?: KnowledgeRetrievalResponse;
  error?: string;
}

const DEFAULT_TOP_K = 5;
const DEFAULT_THRESHOLD = 0.7;

const MODE_LABELS: Record<Mode, string> = {
  retrieval: "智能召回",
  search: "语义检索",
  qa: "问答验证",
};

export function SearchPlayground({ knowledgeTypes }: { knowledgeTypes: KnowledgeTypeOption[] }) {
  const [mode, setMode] = useState<Mode>("retrieval");
  const [query, setQuery] = useState("");
  const [kb, setKb] = useState<string | undefined>(undefined);
  const [topK, setTopK] = useState<number>(DEFAULT_TOP_K);
  const [threshold, setThreshold] = useState<number>(DEFAULT_THRESHOLD);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [progressTick, setProgressTick] = useState(0);
  const [selectedChunk, setSelectedChunk] = useState<KnowledgeChunkHit | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const feedRef = useRef<HTMLDivElement | null>(null);

  const loading = activeRunId !== null;

  useEffect(() => {
    if (!loading) return;
    const timer = window.setInterval(() => {
      setProgressTick((value) => value + 1);
    }, 900);
    return () => window.clearInterval(timer);
  }, [loading]);

  useEffect(() => {
    feedRef.current?.scrollTo({
      top: feedRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, progressTick]);

  const modeOptions = useMemo(
    () => [
      {
        label: (
          <span className="inline-flex items-center gap-1.5">
            <MessagesSquare size={14} aria-hidden="true" />
            智能召回
          </span>
        ),
        value: "retrieval" as const,
      },
      {
        label: (
          <span className="inline-flex items-center gap-1.5">
            <Search size={14} aria-hidden="true" />
            语义检索
          </span>
        ),
        value: "search" as const,
      },
      {
        label: (
          <span className="inline-flex items-center gap-1.5">
            <FileSearch size={14} aria-hidden="true" />
            问答验证
          </span>
        ),
        value: "qa" as const,
      },
    ],
    [],
  );

  const appendUserAndAssistant = useCallback((trimmed: string, runMode: Mode): string => {
    const now = new Date();
    const runId = createId("run");
    const userMessage: ConversationMessage = {
      id: createId("user"),
      role: "user",
      mode: runMode,
      query: trimmed,
      createdAt: now,
      status: "completed",
    };
    const assistantMessage: ConversationMessage = {
      id: runId,
      role: "assistant",
      mode: runMode,
      query: trimmed,
      createdAt: now,
      status: "running",
    };
    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setActiveRunId(runId);
    setProgressTick(0);
    setQuery("");
    return runId;
  }, []);

  const completeRun = useCallback((runId: string, patch: Partial<ConversationMessage>) => {
    setMessages((prev) =>
      prev.map((message) =>
        message.id === runId
          ? {
              ...message,
              ...patch,
            }
          : message,
      ),
    );
    setActiveRunId(null);
  }, []);

  const executeQuery = useCallback(
    async (trimmed: string, runMode: Mode) => {
      if (!trimmed || activeRunId) return;
      const runId = appendUserAndAssistant(trimmed, runMode);
      try {
        if (runMode === "search") {
          const data = await fetchSearch(trimmed, kb, topK, threshold);
          completeRun(runId, { status: "completed", searchData: data });
          return;
        }
        if (runMode === "qa") {
          const data = await fetchQa(trimmed, kb, topK);
          completeRun(runId, { status: "completed", qaData: data });
          return;
        }

        const data = await fetchKnowledgeRetrieval(trimmed);
        completeRun(runId, {
          status: data.status === "needs_clarification" ? "needs_clarification" : "completed",
          retrievalData: data,
        });
      } catch (err) {
        completeRun(runId, {
          status: "failed",
          error: err instanceof Error ? err.message : String(err),
        });
      }
    },
    [activeRunId, appendUserAndAssistant, completeRun, kb, threshold, topK],
  );

  const handleSubmit = useCallback(async () => {
    const trimmed = query.trim();
    await executeQuery(trimmed, mode);
  }, [executeQuery, mode, query]);

  const rerunMessage = useCallback(
    (message: ConversationMessage) => {
      if (loading) return;
      void executeQuery(message.query, message.mode);
    },
    [executeQuery, loading],
  );

  const applyRefinement = useCallback(
    (text: string) => {
      if (loading) return;
      setMode("retrieval");
      setQuery(text);
    },
    [loading],
  );

  const openChunkDetail = useCallback((chunk: KnowledgeChunkHit) => {
    setSelectedChunk(chunk);
    setDrawerOpen(true);
  }, []);

  return (
    <>
      <section className="grid min-h-[calc(100vh-210px)] grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="overflow-hidden" styles={{ body: { padding: 0 } }}>
          <div className="flex min-h-[calc(100vh-230px)] flex-col bg-[var(--surface)]">
            <ConversationHeader mode={mode} loading={loading} onClear={() => setMessages([])} />

            <div ref={feedRef} className="flex-1 overflow-y-auto bg-[var(--surface-alt)] px-4 py-5">
              {messages.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="暂无检索会话"
                  className="mt-20"
                />
              ) : (
                <Space orientation="vertical" size="large" className="w-full">
                  {messages.map((message) => (
                    <ConversationBubble
                      key={message.id}
                      message={message}
                      progressTick={progressTick}
                      onSelectChunk={openChunkDetail}
                      onRerun={rerunMessage}
                      onApplyRefinement={applyRefinement}
                    />
                  ))}
                </Space>
              )}
            </div>

            <Composer
              mode={mode}
              modeOptions={modeOptions}
              query={query}
              loading={loading}
              onModeChange={setMode}
              onQueryChange={setQuery}
              onSubmit={handleSubmit}
              kb={kb}
              topK={topK}
              threshold={threshold}
              knowledgeTypes={knowledgeTypes}
              onKbChange={setKb}
              onTopKChange={setTopK}
              onThresholdChange={setThreshold}
            />
          </div>
        </Card>

        <RunInspector
          latestAssistant={[...messages].reverse().find((message) => message.role === "assistant")}
          progressTick={progressTick}
        />
      </section>

      <ChunkDetailDrawer
        chunk={selectedChunk}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </>
  );
}

function ConversationHeader({
  mode,
  loading,
  onClear,
}: {
  mode: Mode;
  loading: boolean;
  onClear: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] px-5 py-4">
      <Space size="middle">
        <Badge status={loading ? "processing" : "success"} />
        <div>
          <Typography.Title level={4} className="!mb-0">
            检索/召回验证窗口
          </Typography.Title>
          <Typography.Text type="secondary">当前模式：{MODE_LABELS[mode]}</Typography.Text>
        </div>
      </Space>
      <Space>
        <Tag color={loading ? "processing" : "default"}>{loading ? "执行中" : "可交互"}</Tag>
        <Button size="small" onClick={onClear} disabled={loading}>
          清空
        </Button>
      </Space>
    </div>
  );
}

function Composer({
  mode,
  modeOptions,
  query,
  loading,
  onModeChange,
  onQueryChange,
  onSubmit,
  kb,
  topK,
  threshold,
  knowledgeTypes,
  onKbChange,
  onTopKChange,
  onThresholdChange,
}: {
  mode: Mode;
  modeOptions: Array<{ label: ReactNode; value: Mode }>;
  query: string;
  loading: boolean;
  onModeChange: (mode: Mode) => void;
  onQueryChange: (query: string) => void;
  onSubmit: () => void;
  kb: string | undefined;
  topK: number;
  threshold: number;
  knowledgeTypes: KnowledgeTypeOption[];
  onKbChange: (value: string | undefined) => void;
  onTopKChange: (value: number) => void;
  onThresholdChange: (value: number) => void;
}) {
  return (
    <div className="border-t border-[var(--line)] bg-[var(--surface)] p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Segmented<Mode>
          value={mode}
          onChange={onModeChange}
          options={modeOptions}
          disabled={loading}
        />
        {mode !== "retrieval" && (
          <>
            <Select
              allowClear
              className="min-w-64"
              placeholder="默认 textbook_kb"
              value={kb}
              onChange={(v) => onKbChange(v ?? undefined)}
              disabled={loading}
              options={knowledgeTypes.map((kt) => ({
                value: kt.code,
                label: `${kt.name}（${kt.code}）`,
              }))}
            />
            <InputNumber
              addonBefore="top_k"
              min={1}
              max={50}
              value={topK}
              disabled={loading}
              onChange={(v) => onTopKChange(typeof v === "number" ? v : DEFAULT_TOP_K)}
            />
          </>
        )}
        {mode === "search" && (
          <div className="flex min-w-64 items-center gap-2">
            <Typography.Text type="secondary">阈值</Typography.Text>
            <Slider
              className="min-w-40"
              min={0}
              max={1}
              step={0.05}
              value={threshold}
              disabled={loading}
              onChange={onThresholdChange}
            />
            <Typography.Text className="w-10">{threshold.toFixed(2)}</Typography.Text>
          </div>
        )}
      </div>

      <div className="flex items-end gap-3 rounded-lg border border-[var(--line)] bg-[var(--surface-alt)] p-3">
        <Input.TextArea
          autoSize={{ minRows: 1, maxRows: 4 }}
          variant="borderless"
          value={query}
          disabled={loading}
          placeholder={
            mode === "retrieval"
              ? "输入需要检索/召回的问题"
              : mode === "search"
                ? "输入检索关键词"
                : "输入需要验证的问题"
          }
          onChange={(e) => onQueryChange(e.target.value)}
          onPressEnter={(event) => {
            if (!event.shiftKey) {
              event.preventDefault();
              void onSubmit();
            }
          }}
        />
        <Tooltip title={loading ? "当前任务执行中" : "发送"}>
          <Button
            type="primary"
            shape="circle"
            icon={loading ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}
            disabled={loading || !query.trim()}
            onClick={() => void onSubmit()}
          />
        </Tooltip>
      </div>
    </div>
  );
}

function ConversationBubble({
  message,
  progressTick,
  onSelectChunk,
  onRerun,
  onApplyRefinement,
}: {
  message: ConversationMessage;
  progressTick: number;
  onSelectChunk: (chunk: KnowledgeChunkHit) => void;
  onRerun: (message: ConversationMessage) => void;
  onApplyRefinement: (text: string) => void;
}) {
  const isUser = message.role === "user";
  return (
    <div className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && <AssistantAvatar status={message.status} />}
      <div className={isUser ? "max-w-[76%]" : "max-w-[92%] flex-1"}>
        <div className={`mb-1 flex items-center gap-2 ${isUser ? "justify-end" : ""}`}>
          <Typography.Text strong>{isUser ? "用户" : "检索执行器"}</Typography.Text>
          <Typography.Text type="secondary" className="text-xs">
            {formatTime(message.createdAt)}
          </Typography.Text>
          {!isUser && <Tag color={statusColor(message.status)}>{statusLabel(message.status)}</Tag>}
        </div>

        {isUser ? (
          <div className="rounded-lg bg-[var(--brand)] px-4 py-3 text-[var(--text-inverse)]">
            <Typography.Paragraph className="!mb-0 whitespace-pre-wrap !text-inherit">
              {message.query}
            </Typography.Paragraph>
          </div>
        ) : (
          <div className="rounded-lg border border-[var(--line)] bg-[var(--surface)] p-4 shadow-sm">
            <AssistantMessageBody
              message={message}
              progressTick={progressTick}
              onSelectChunk={onSelectChunk}
              onApplyRefinement={onApplyRefinement}
            />
            <div className="mt-4 flex justify-end">
              <Button
                size="small"
                icon={<RefreshCw size={14} />}
                disabled={message.status === "running"}
                onClick={() => onRerun(message)}
              >
                重新执行
              </Button>
            </div>
          </div>
        )}
      </div>
      {isUser && (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--brand-soft)] text-[var(--brand)]">
          <UserRound size={17} aria-hidden="true" />
        </div>
      )}
    </div>
  );
}

function AssistantAvatar({ status }: { status: MessageStatus }) {
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--accent-bg)] text-[var(--accent-strong)]">
      {status === "running" ? (
        <Loader2 size={17} className="animate-spin" aria-hidden="true" />
      ) : (
        <Bot size={17} aria-hidden="true" />
      )}
    </div>
  );
}

function AssistantMessageBody({
  message,
  progressTick,
  onSelectChunk,
  onApplyRefinement,
}: {
  message: ConversationMessage;
  progressTick: number;
  onSelectChunk: (chunk: KnowledgeChunkHit) => void;
  onApplyRefinement: (text: string) => void;
}) {
  if (message.error) {
    return <Alert type="error" showIcon title={message.error} />;
  }

  if (message.mode === "search") {
    return (
      <LegacySearchResult
        query={message.query}
        loading={message.status === "running"}
        data={message.searchData}
        onSelectChunk={onSelectChunk}
      />
    );
  }

  if (message.mode === "qa") {
    return (
      <LegacyQaResult
        query={message.query}
        loading={message.status === "running"}
        data={message.qaData}
        onSelectChunk={onSelectChunk}
      />
    );
  }

  return (
    <RetrievalConversationResult
      message={message}
      progressTick={progressTick}
      onApplyRefinement={onApplyRefinement}
    />
  );
}

function LegacySearchResult({
  query,
  loading,
  data,
  onSelectChunk,
}: {
  query: string;
  loading: boolean;
  data?: SearchResponse;
  onSelectChunk: (chunk: KnowledgeChunkHit) => void;
}) {
  const steps = loading
    ? buildLegacySteps("search", 0)
    : buildLegacySteps("search", 3, data?.results.length ?? 0);

  return (
    <Space orientation="vertical" size="middle" className="w-full">
      <ExecutionSteps steps={steps} results={[]} compact />
      {!data ? (
        <RunningNotice query={query} />
      ) : data.results.length === 0 ? (
        <Empty description="没有命中任何 chunk" />
      ) : (
        <div>
          <ResultSectionTitle
            title="语义检索结果"
            tags={[
              `命中 ${data.count}`,
              data.kb ? `KB ${data.kb}` : null,
              `caller ${data.caller_id}`,
            ]}
          />
          <List<KnowledgeChunkHit>
            dataSource={data.results}
            renderItem={(item) => (
              <List.Item key={item.chunk_id}>
                <ChunkCard chunk={item} onSelect={onSelectChunk} />
              </List.Item>
            )}
          />
        </div>
      )}
    </Space>
  );
}

function LegacyQaResult({
  query,
  loading,
  data,
  onSelectChunk,
}: {
  query: string;
  loading: boolean;
  data?: QaResponse;
  onSelectChunk: (chunk: KnowledgeChunkHit) => void;
}) {
  const steps = loading
    ? buildLegacySteps("qa", 0)
    : buildLegacySteps("qa", 3, data?.sources.length ?? 0);

  return (
    <Space orientation="vertical" size="middle" className="w-full">
      <ExecutionSteps steps={steps} results={[]} compact />
      {!data ? (
        <RunningNotice query={query} />
      ) : (
        <>
          <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-alt)] p-4">
            <Space className="mb-3" wrap>
              <Typography.Text strong>AI 回答</Typography.Text>
              <AnswerConfidenceBadge confidence={data.answer_confidence} />
              {data.kb && <Tag color="purple">KB: {data.kb}</Tag>}
            </Space>
            <Typography.Paragraph className="!mb-0 whitespace-pre-wrap">
              {data.answer || "（空回答）"}
            </Typography.Paragraph>
          </div>
          <div>
            <ResultSectionTitle title="引用源" tags={[`${data.sources.length}`]} />
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
          </div>
        </>
      )}
    </Space>
  );
}

function RetrievalConversationResult({
  message,
  progressTick,
  onApplyRefinement,
}: {
  message: ConversationMessage;
  progressTick: number;
  onApplyRefinement: (text: string) => void;
}) {
  const data = message.retrievalData;
  const steps = data?.conversation_steps?.length
    ? data.conversation_steps
    : buildLiveRetrievalSteps(progressTick);
  const results = data?.retrieval_results ?? [];

  return (
    <Space orientation="vertical" size="middle" className="w-full">
      <ExecutionSteps steps={steps} results={results} />

      {!data ? (
        <RunningNotice query={message.query} />
      ) : data.status === "needs_clarification" ? (
        <ClarificationPanel data={data} onApplyRefinement={onApplyRefinement} />
      ) : (
        <MarkdownAnswer data={data} />
      )}

      {data && (
        <Collapse
          ghost
          defaultActiveKey={data.status === "needs_clarification" ? ["intent", "plan"] : ["intent"]}
          items={[
            {
              key: "intent",
              label: <CollapseLabel icon={<Split size={15} />} text="意图识别辅助分析" />,
              children: <IntentAnalysisPanel data={data} />,
            },
            {
              key: "plan",
              label: <CollapseLabel icon={<ListChecks size={15} />} text="召回计划" />,
              children: <RetrievalPlanPanel data={data} />,
            },
            {
              key: "results",
              label: (
                <CollapseLabel
                  icon={<Database size={15} />}
                  text={`执行结果 (${data.retrieval_results.length})`}
                />
              ),
              children: <RetrievalResultList results={data.retrieval_results} />,
            },
            {
              key: "sources",
              label: (
                <CollapseLabel
                  icon={<FileSearch size={15} />}
                  text={`来源与定位 (${data.source_refs.length})`}
                />
              ),
              children: <SourceRefList refs={data.source_refs} />,
            },
          ]}
        />
      )}
    </Space>
  );
}

function ExecutionSteps({
  steps,
  results,
  compact = false,
}: {
  steps: RetrievalConversationStep[];
  results: RetrievalResult[];
  compact?: boolean;
}) {
  const completed = steps.filter((step) => step.status === "completed").length;
  const progress = steps.length ? Math.round((completed / steps.length) * 100) : 0;

  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-alt)] p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Space>
          <Settings2 size={16} aria-hidden="true" />
          <Typography.Text strong>执行过程</Typography.Text>
          <Tag color="processing">{steps.length} 步</Tag>
        </Space>
        <Progress percent={progress} size="small" className="max-w-48" />
      </div>

      <div
        className={
          compact
            ? "grid grid-cols-1 gap-3 md:grid-cols-3"
            : "grid grid-cols-1 gap-3 lg:grid-cols-5"
        }
      >
        {steps.map((step, index) => (
          <StepTile
            key={`${step.step}-${index}`}
            step={step}
            index={index}
            relatedResults={step.step === "parallel_retrieval" ? results : []}
          />
        ))}
      </div>
    </div>
  );
}

function StepTile({
  step,
  index,
  relatedResults,
}: {
  step: RetrievalConversationStep;
  index: number;
  relatedResults: RetrievalResult[];
}) {
  return (
    <div className="min-h-32 rounded-lg border border-[var(--line)] bg-[var(--surface)] p-3">
      <div className="mb-2 flex items-start justify-between gap-2">
        <Space size="small" align="start">
          <StepIcon status={step.status} />
          <div>
            <Typography.Text strong className="block">
              {index + 1}. {step.title}
            </Typography.Text>
            <Tag color={statusColor(step.status)} className="mt-1">
              {statusLabel(step.status)}
            </Tag>
          </div>
        </Space>
      </div>
      {step.message && (
        <Typography.Paragraph type="secondary" className="!mb-2 text-xs">
          {step.message}
        </Typography.Paragraph>
      )}
      {step.progress && Object.keys(step.progress).length > 0 && (
        <JsonPreview value={step.progress} maxHeight="max-h-24" />
      )}
      {step.display_payload && Object.keys(step.display_payload).length > 0 && (
        <div className="mt-2">
          <JsonPreview value={step.display_payload} maxHeight="max-h-40" />
        </div>
      )}
      {relatedResults.length > 0 && (
        <div className="mt-2 space-y-1">
          {relatedResults.map((result) => (
            <Typography.Text key={result.query_id} type="secondary" className="block text-xs">
              {result.query_id} · {result.domain} · {result.result_shape ?? "-"} ·{" "}
              {statusLabel(result.status)}
            </Typography.Text>
          ))}
        </div>
      )}
    </div>
  );
}

function StepIcon({ status }: { status: string }) {
  const className = "mt-0.5 shrink-0";
  if (status === "running") return <Loader2 size={16} className={`${className} animate-spin`} />;
  if (status === "completed") return <CheckCircle2 size={16} className={className} />;
  if (status === "failed" || status === "blocked")
    return <AlertTriangle size={16} className={className} />;
  return <Clock3 size={16} className={className} />;
}

function RunningNotice({ query }: { query: string }) {
  return (
    <Alert
      type="info"
      showIcon
      title="正在执行检索/查询流程"
      description={<Typography.Text type="secondary">当前问题：{query}</Typography.Text>}
    />
  );
}

function MarkdownAnswer({ data }: { data: KnowledgeRetrievalResponse }) {
  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-alt)] p-4">
      <ResultSectionTitle
        title="结构化结果"
        tags={[
          statusLabel(data.status),
          `来源 ${data.source_refs.length}`,
          `范围 ${data.access_scope}`,
        ]}
      />
      {data.markdown ? (
        <div className="prose max-w-none leading-7">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.markdown}</ReactMarkdown>
        </div>
      ) : (
        <Empty description="本次召回没有生成 Markdown 结果" />
      )}
      {data.warnings.length > 0 && (
        <Alert
          type="warning"
          showIcon
          className="mt-4"
          title="结果警告"
          description={data.warnings.join("；")}
        />
      )}
    </div>
  );
}

function ClarificationPanel({
  data,
  onApplyRefinement,
}: {
  data: KnowledgeRetrievalResponse;
  onApplyRefinement: (text: string) => void;
}) {
  const clarification = data.clarification;
  const refinements = clarification?.suggested_refinements?.length
    ? clarification.suggested_refinements
    : (data.intent.suggested_refinements ?? []);

  return (
    <div className="rounded-lg border border-[var(--warning-100)] bg-[var(--warning-bg)] p-4">
      <Alert
        type="warning"
        showIcon
        title={clarification?.message ?? "当前问题的检索意图不够清晰。"}
      />
      {clarification?.missing_constraints?.length ? (
        <div className="mt-4">
          <Typography.Text strong>缺失约束</Typography.Text>
          <Space wrap className="ml-2">
            {clarification.missing_constraints.map((item) => (
              <Tag key={item}>{item}</Tag>
            ))}
          </Space>
        </div>
      ) : null}
      {refinements.length > 0 && (
        <div className="mt-4">
          <Typography.Text strong>可继续追问</Typography.Text>
          <div className="mt-2 flex flex-wrap gap-2">
            {refinements.map((item) => (
              <Button key={item} size="small" onClick={() => onApplyRefinement(item)}>
                {item}
              </Button>
            ))}
          </div>
        </div>
      )}
    </div>
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
        <Tag>阈值 {formatPercent(intent.confidence_threshold)}</Tag>
      </Space>
      {intent.output_expectation?.length ? (
        <div>
          <Typography.Text type="secondary">输出期望：</Typography.Text>
          <Space wrap>
            {intent.output_expectation.map((item) => (
              <Tag key={item}>{item}</Tag>
            ))}
          </Space>
        </div>
      ) : null}
      {Object.keys(intent.constraints ?? {}).length > 0 && (
        <JsonPreview value={intent.constraints ?? {}} />
      )}
      {intent.candidate_intents?.length ? <JsonPreview value={intent.candidate_intents} /> : null}
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
            <div className="w-full rounded-lg border border-[var(--line)] bg-[var(--surface-alt)] p-3">
              <Space orientation="vertical" size="small" className="w-full">
                <Space wrap>
                  <Tag color="processing">{subQuery.query_id}</Tag>
                  <Tag>{subQuery.channel}</Tag>
                  <Tag>{subQuery.domain}</Tag>
                  <Typography.Text>{subQuery.purpose}</Typography.Text>
                </Space>
                <Typography.Text>{subQuery.query_text}</Typography.Text>
                <JsonPreview value={subQuery.structured_plan ?? subQuery.unstructured_plan ?? {}} />
              </Space>
            </div>
          </List.Item>
        )}
      />
    </Space>
  );
}

function RetrievalResultList({ results }: { results: RetrievalResult[] }) {
  if (!results.length) return <Empty description="未返回执行结果" />;
  return (
    <List
      dataSource={results}
      renderItem={(result) => (
        <List.Item key={result.query_id}>
          <div className="w-full rounded-lg border border-[var(--line)] bg-[var(--surface-alt)] p-3">
            <Space orientation="vertical" size="small" className="w-full">
              <Space wrap>
                <Tag color="processing">{result.query_id}</Tag>
                <Tag>{result.channel}</Tag>
                <Tag>{result.domain}</Tag>
                <Tag color={statusColor(result.status)}>{statusLabel(result.status)}</Tag>
                {result.elapsed_ms != null && <Tag>{result.elapsed_ms} ms</Tag>}
              </Space>
              {result.error_message && <Alert type="error" showIcon title={result.error_message} />}
              <JsonPreview
                value={{
                  result_shape: result.result_shape,
                  items: result.items,
                  records: result.records,
                  aggregations: result.aggregations,
                  source_refs: result.source_refs?.map((ref) => ref.source_ref_id),
                }}
              />
            </Space>
          </div>
        </List.Item>
      )}
    />
  );
}

function SourceRefList({ refs }: { refs: RetrievalSourceRef[] }) {
  if (!refs.length) return <Empty description="未返回来源定位" />;
  return (
    <List
      dataSource={refs}
      renderItem={(ref) => (
        <List.Item key={ref.source_ref_id}>
          <div className="w-full rounded-lg border border-[var(--line)] bg-[var(--surface-alt)] p-3">
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
                <JsonPreview value={ref.locator} maxHeight="max-h-32" />
              )}
            </Space>
          </div>
        </List.Item>
      )}
    />
  );
}

function RunInspector({
  latestAssistant,
  progressTick,
}: {
  latestAssistant: ConversationMessage | undefined;
  progressTick: number;
}) {
  const data = latestAssistant?.retrievalData;
  const steps =
    latestAssistant?.status === "running"
      ? buildLiveRetrievalSteps(progressTick)
      : (data?.conversation_steps ?? []);
  const activeStep =
    steps.find((step) => step.status === "running") ??
    [...steps].reverse().find((step) => step.status === "completed") ??
    null;

  return (
    <aside className="rounded-lg border border-[var(--line)] bg-[var(--surface)] p-4">
      <Space orientation="vertical" size="middle" className="w-full">
        <Space>
          <Database size={16} aria-hidden="true" />
          <Typography.Text strong>执行观察</Typography.Text>
        </Space>

        {!latestAssistant ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无执行任务" />
        ) : (
          <>
            <div className="rounded-lg bg-[var(--surface-alt)] p-3">
              <Typography.Text type="secondary" className="block">
                当前问题
              </Typography.Text>
              <Typography.Paragraph className="mt-1 !mb-0">
                {latestAssistant.query}
              </Typography.Paragraph>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <MetricBox label="模式" value={MODE_LABELS[latestAssistant.mode]} />
              <MetricBox label="状态" value={statusLabel(latestAssistant.status)} />
              <MetricBox
                label="步骤"
                value={
                  steps.length
                    ? `${steps.filter((s) => s.status === "completed").length}/${steps.length}`
                    : "-"
                }
              />
              <MetricBox label="来源" value={data ? String(data.source_refs.length) : "-"} />
            </div>

            {activeStep && (
              <div className="rounded-lg border border-[var(--line)] p-3">
                <Typography.Text type="secondary" className="block">
                  当前步骤
                </Typography.Text>
                <Space className="mt-2">
                  <StepIcon status={activeStep.status} />
                  <Typography.Text strong>{activeStep.title}</Typography.Text>
                </Space>
                {activeStep.message && (
                  <Typography.Paragraph type="secondary" className="mt-2 !mb-0 text-sm">
                    {activeStep.message}
                  </Typography.Paragraph>
                )}
              </div>
            )}

            {data?.intent && (
              <div className="rounded-lg border border-[var(--line)] p-3">
                <Typography.Text type="secondary" className="block">
                  识别置信度
                </Typography.Text>
                <Progress
                  percent={Math.round(data.intent.confidence * 100)}
                  size="small"
                  status={
                    data.intent.confidence >= data.intent.confidence_threshold
                      ? "success"
                      : "exception"
                  }
                />
              </div>
            )}
          </>
        )}
      </Space>
    </aside>
  );
}

function MetricBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-alt)] p-3">
      <Typography.Text type="secondary" className="block text-xs">
        {label}
      </Typography.Text>
      <Typography.Text strong>{value}</Typography.Text>
    </div>
  );
}

function ResultSectionTitle({ title, tags }: { title: string; tags: Array<string | null> }) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <Typography.Text strong>{title}</Typography.Text>
      {tags
        .filter((tag): tag is string => Boolean(tag))
        .map((tag) => (
          <Tag key={tag}>{tag}</Tag>
        ))}
    </div>
  );
}

function CollapseLabel({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <Space>
      {icon}
      <span>{text}</span>
    </Space>
  );
}

function JsonPreview({ value, maxHeight = "max-h-56" }: { value: unknown; maxHeight?: string }) {
  return (
    <pre
      className={`${maxHeight} overflow-auto rounded bg-white p-3 text-xs text-[var(--text-secondary)]`}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function buildLiveRetrievalSteps(tick: number): RetrievalConversationStep[] {
  const activeIndex = Math.min(Math.floor(tick / 2), 4);
  const base = [
    ["intent_recognition", "意图识别", "理解用户问题并映射到平台数据领域"],
    ["query_transformation", "问题转化", "生成可执行的结构化/非结构化召回计划"],
    ["parallel_retrieval", "并行检索", "按召回计划执行各子查询"],
    ["context_assembly", "上下文组装", "合并检索片段、结构化记录和来源定位"],
    ["summary_generation", "结果生成", "生成可追溯的 Markdown 结构化结果"],
  ] as const;
  return base.map(([step, title, message], index) => ({
    step,
    title,
    message,
    display_to_user: true,
    status: index < activeIndex ? "completed" : index === activeIndex ? "running" : "pending",
    progress: index === activeIndex ? { elapsed_ticks: tick } : undefined,
  }));
}

function buildLegacySteps(
  mode: "search" | "qa",
  activeIndex: number,
  count?: number,
): RetrievalConversationStep[] {
  const base =
    mode === "search"
      ? [
          ["query_parse", "查询解析", "读取检索参数"],
          ["semantic_search", "语义检索", "调用语义检索接口"],
          ["citation_render", "引用呈现", "展示命中 chunk 与定位"],
        ]
      : [
          ["question_parse", "问题解析", "读取问答参数"],
          ["qa_request", "问答执行", "调用 QA 接口生成回答"],
          ["source_render", "来源呈现", "展示引用源"],
        ];
  return base.map(([step, title, message], index) => ({
    step,
    title,
    message: count != null && index === base.length - 1 ? `${message}，返回 ${count} 条` : message,
    display_to_user: true,
    status: index < activeIndex ? "completed" : index === activeIndex ? "running" : "pending",
  }));
}

// Client-side fetch helpers.

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

function createId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    idle: "就绪",
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
    idle: "default",
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

function formatTime(value: Date): string {
  return value.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

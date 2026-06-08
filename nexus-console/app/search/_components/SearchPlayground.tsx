"use client";

/**
 * SearchPlayground — 检索/QA 验证入口（消费侧 demo，非最终用户搜索门户）。
 *
 * 设计要点：
 * - 数据请求经 Next.js route handler /api/search 与 /api/qa 服务端代理，
 *   caller_key 不暴露到浏览器（见 lib/searchProxy.ts）。
 * - Tab 切换检索 / QA 两种模式；两侧共享 KB 选择、top_k、查询输入。
 * - 错误态、空态、loading 态走 Antd Skeleton / Empty / Alert。
 */

import { useCallback, useState } from "react";
import {
  Alert,
  Button,
  Card,
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
import type {
  KnowledgeTypeOption,
  QaResponse,
  SearchChunk,
  SearchResponse,
} from "../_lib/searchTypes";

type Mode = "search" | "qa";

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

export function SearchPlayground({
  knowledgeTypes,
}: {
  knowledgeTypes: KnowledgeTypeOption[];
}) {
  const [mode, setMode] = useState<Mode>("search");
  const [query, setQuery] = useState("");
  const [kb, setKb] = useState<string | undefined>(undefined);
  const [topK, setTopK] = useState<number>(DEFAULT_TOP_K);
  const [threshold, setThreshold] = useState<number>(DEFAULT_THRESHOLD);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchData, setSearchData] = useState<SearchResponse | null>(null);
  const [qaData, setQaData] = useState<QaResponse | null>(null);

  const reset = useCallback(() => {
    setSearchData(null);
    setQaData(null);
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
      } else {
        const data = await fetchQa(trimmed, kb, topK);
        setQaData(data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [mode, query, kb, topK, threshold, reset]);

  return (
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
              ]}
            />
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
            {mode === "search" && (
              <Form.Item
                label="相似度阈值"
                className="!mb-0"
                style={{ minWidth: 200 }}
              >
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
              enterButton={mode === "search" ? "检索" : "提问"}
              loading={loading}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onSearch={handleSubmit}
              placeholder={
                mode === "search"
                  ? "例如：教材中关于光合作用的章节"
                  : "例如：光合作用的暗反应阶段发生在哪里？"
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
      />
    </Space>
  );
}

// ── Result panel ────────────────────────────────────────────────────────

interface ResultPanelProps {
  mode: Mode;
  loading: boolean;
  searchData: SearchResponse | null;
  qaData: QaResponse | null;
}

function ResultPanel({ mode, loading, searchData, qaData }: ResultPanelProps) {
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
    return <SearchResultList data={searchData} />;
  }

  if (!qaData) {
    return (
      <Card>
        <Empty description="输入问题后将展示 AI 回答与引用源" />
      </Card>
    );
  }
  return <QaResult data={qaData} />;
}

function SearchResultList({ data }: { data: SearchResponse }) {
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
      <List<SearchChunk>
        dataSource={data.results}
        renderItem={(item) => (
          <List.Item key={item.chunk_id}>
            <Space orientation="vertical" size={4} className="w-full">
              <Space size={6} wrap>
                <Tag color="blue">score {item.score?.toFixed?.(3) ?? "-"}</Tag>
                {item.source?.doc_name && (
                  <Tag>{String(item.source.doc_name)}</Tag>
                )}
                {item.source?.page !== undefined && (
                  <Tag>page {String(item.source.page)}</Tag>
                )}
                {item.source?.normalized_ref_id && (
                  <Typography.Text className="font-mono" style={{ fontSize: 12 }}>
                    {String(item.source.normalized_ref_id)}
                  </Typography.Text>
                )}
              </Space>
              <Typography.Paragraph
                className="!mb-0"
                ellipsis={{ rows: 3, expandable: true, symbol: "展开" }}
              >
                {item.content}
              </Typography.Paragraph>
            </Space>
          </List.Item>
        )}
      />
    </Card>
  );
}

function QaResult({ data }: { data: QaResponse }) {
  return (
    <Space orientation="vertical" size="middle" className="w-full">
      <Card title="AI 回答">
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
          <List
            dataSource={data.sources}
            renderItem={(src, idx) => (
              <List.Item key={src.chunk_id ?? `src-${idx}`}>
                <Space orientation="vertical" size={4} className="w-full">
                  <Space size={6} wrap>
                    {src.doc_name && <Tag>{String(src.doc_name)}</Tag>}
                    {src.page !== undefined && <Tag>page {String(src.page)}</Tag>}
                    {src.normalized_ref_id && (
                      <Typography.Text className="font-mono" style={{ fontSize: 12 }}>
                        {String(src.normalized_ref_id)}
                      </Typography.Text>
                    )}
                  </Space>
                  {src.content && (
                    <Typography.Paragraph
                      className="!mb-0"
                      ellipsis={{ rows: 3, expandable: true, symbol: "展开" }}
                    >
                      {String(src.content)}
                    </Typography.Paragraph>
                  )}
                </Space>
              </List.Item>
            )}
          />
        )}
      </Card>
    </Space>
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

async function fetchQa(
  q: string,
  kb: string | undefined,
  topK: number,
): Promise<QaResponse> {
  const params = buildParams({ q, kb, top_k: topK });
  return readEnvelope<QaResponse>(await fetch(`/api/qa?${params}`, { cache: "no-store" }));
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

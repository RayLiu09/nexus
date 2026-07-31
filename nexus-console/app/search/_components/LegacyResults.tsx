"use client";

import { Empty, Space, Tag, Typography } from "antd";

import { ChunkCard } from "@/components/chunk/ChunkCard";
import type { KnowledgeChunkHit } from "@/lib/chunkTypes";

import type { QaResponse, SearchResponse } from "../_lib/searchTypes";
import { ResultSectionTitle, buildLegacySteps } from "../_lib/playgroundHelpers";

import { AnswerConfidenceBadge } from "./AnswerConfidenceBadge";
import { ExecutionSteps } from "./ExecutionSteps";
import { RunningNotice } from "./RunningNotice";

interface LegacySearchResultProps {
  query: string;
  loading: boolean;
  data?: SearchResponse;
  onSelectChunk: (chunk: KnowledgeChunkHit) => void;
}

export function LegacySearchResult({
  query,
  loading,
  data,
  onSelectChunk,
}: LegacySearchResultProps) {
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
          <div role="list" className="flex flex-col gap-3">
            {data.results.map((item) => (
              <div role="listitem" key={item.chunk_id}>
                <ChunkCard chunk={item} onSelect={onSelectChunk} />
              </div>
            ))}
          </div>
        </div>
      )}
    </Space>
  );
}

interface LegacyQaResultProps {
  query: string;
  loading: boolean;
  data?: QaResponse;
  onSelectChunk: (chunk: KnowledgeChunkHit) => void;
}

export function LegacyQaResult({ query, loading, data, onSelectChunk }: LegacyQaResultProps) {
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
              <div role="list" className="flex flex-col gap-3">
                {data.sources.map((src, idx) => (
                  <div role="listitem" key={src.chunk_id ?? `src-${idx}`}>
                    <ChunkCard chunk={src} onSelect={onSelectChunk} />
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </Space>
  );
}

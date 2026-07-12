"use client";

import { Alert, Empty, List, Space, Tag, Typography } from "antd";

import type {
  KnowledgeRetrievalResponse,
  RetrievalResult,
  RetrievalSourceRef,
} from "@/lib/retrievalTypes";

import {
  InlineJsonPreview,
  formatPercent,
  statusColor,
  statusLabel,
} from "../_lib/playgroundHelpers";

export function IntentAnalysisPanel({ data }: { data: KnowledgeRetrievalResponse }) {
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
        <InlineJsonPreview value={intent.constraints ?? {}} />
      )}
      {intent.candidate_intents?.length ? (
        <InlineJsonPreview value={intent.candidate_intents} />
      ) : null}
    </Space>
  );
}

export function RetrievalPlanPanel({ data }: { data: KnowledgeRetrievalResponse }) {
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
                <InlineJsonPreview
                  value={subQuery.structured_plan ?? subQuery.unstructured_plan ?? {}}
                />
              </Space>
            </div>
          </List.Item>
        )}
      />
    </Space>
  );
}

export function RetrievalResultList({ results }: { results: RetrievalResult[] }) {
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
              <InlineJsonPreview
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

export function SourceRefList({ refs }: { refs: RetrievalSourceRef[] }) {
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
                <InlineJsonPreview value={ref.locator} maxHeight="max-h-32" />
              )}
            </Space>
          </div>
        </List.Item>
      )}
    />
  );
}

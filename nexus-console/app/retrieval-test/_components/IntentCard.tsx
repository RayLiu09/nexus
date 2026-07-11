"use client";

import { Card, Progress, Tag } from "antd";
import { Target } from "lucide-react";

import type { RetrievalIntent } from "@/lib/retrievalTypes";

import { JsonPreview } from "./JsonPreview";

interface IntentCardProps {
  intent: RetrievalIntent;
}

export function IntentCard({ intent }: IntentCardProps) {
  const confidencePct = Math.round(intent.confidence * 100);
  const thresholdPct = Math.round(intent.confidence_threshold * 100);
  const meetsThreshold = intent.confidence >= intent.confidence_threshold;

  return (
    <Card
      size="small"
      title={
        <span className="inline-flex items-center gap-2">
          <Target size={16} className="text-brand" />
          意图识别
        </span>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-gray-600">领域</span>
          {intent.business_domains.length === 0 ? (
            <Tag color="default">未识别</Tag>
          ) : (
            intent.business_domains.map((d) => (
              <Tag key={d} color="blue">
                {d}
              </Tag>
            ))
          )}
          <span className="ml-4 text-sm text-gray-600">通道</span>
          {intent.retrieval_channels.length === 0 ? (
            <Tag color="default">未指定</Tag>
          ) : (
            intent.retrieval_channels.map((c) => (
              <Tag key={c} color="purple">
                {c}
              </Tag>
            ))
          )}
          <span className="ml-4 text-sm text-gray-600">问题类型</span>
          <Tag color="green">{intent.question_type}</Tag>
        </div>

        <div className="flex items-center gap-4">
          <span className="w-16 shrink-0 text-sm text-gray-600">置信度</span>
          <Progress
            percent={confidencePct}
            size="small"
            status={meetsThreshold ? "success" : "exception"}
            className="max-w-md"
          />
          <span className="whitespace-nowrap text-xs text-gray-500">
            阈值 {thresholdPct}%
          </span>
          <Tag color={meetsThreshold ? "success" : "warning"}>
            {meetsThreshold ? "达到阈值" : "低于阈值 — 需澄清"}
          </Tag>
        </div>

        {intent.output_expectation && intent.output_expectation.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-gray-600">期望输出</span>
            {intent.output_expectation.map((exp) => (
              <Tag key={exp} color="cyan">
                {exp}
              </Tag>
            ))}
          </div>
        )}

        {intent.suggested_refinements && intent.suggested_refinements.length > 0 && (
          <div className="rounded-md bg-yellow-50 p-3">
            <div className="mb-1 text-sm font-medium text-yellow-800">建议澄清</div>
            <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-xs text-yellow-700">
              {intent.suggested_refinements.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
        )}

        {intent.constraints && Object.keys(intent.constraints).length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm text-gray-600">
              constraints ({Object.keys(intent.constraints).length})
            </summary>
            <div className="mt-2">
              <JsonPreview value={intent.constraints} label="constraints" />
            </div>
          </details>
        )}

        {intent.candidate_intents && intent.candidate_intents.length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm text-gray-600">
              candidate_intents ({intent.candidate_intents.length})
            </summary>
            <div className="mt-2">
              <JsonPreview value={intent.candidate_intents} label="candidate_intents" />
            </div>
          </details>
        )}
      </div>
    </Card>
  );
}
